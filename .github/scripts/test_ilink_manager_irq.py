"""Drive the real ISR and PHT waiter through errors, normal IRQs and a bus reset.

Only MMIO interrupt reads are scripted: a hardware acknowledgment removes each
sample before the next loop. Missing wake-ups escape through a host guard.
"""
from pathlib import Path
import argparse
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MANAGERS = ('modules/ilink/iLinkman/src', 'modules/bdmassault/ilink_bd_assault/src/iLinkman/src')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    assert match, signature
    return source[match.start():source.index('\n}', match.start()) + 2]


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8; typedef uint64_t u64;
#include "iLink_internal.h"
#undef DEBUG_PRINTF
#undef iDEBUG_PRINTF
#define DEBUG_PRINTF(...) ((void)0)
#define iDEBUG_PRINTF(...) ((void)0)
#define WEF_OR 1
#define DMAC_CHCR_TR (1u<<24)
#define DMAC_CHCR_CO (1u<<9)
static struct ILINKMemMap regs;
static struct ILINKMemMap *ILINKRegisterBase=&regs;
static struct DMAChannelRegBlock dma[3], *iLinkDMACRegs=dma;
static unsigned int LocalCachedIntr0Register,irq0,irq1,flags,failures;
static int IntrEventFlag=1,GenerationNumber=1,delivered,simulate_response,response_copied;
static jmp_buf no_wake;
static unsigned int read_intr0(void) {
    unsigned int v=irq0;irq0=0;
    if(v&iLink_INTR0_PBCntR) dma[0].chcr=0;
    return v;
}
static unsigned int read_intr1(void) { unsigned int v=irq1;irq1=0;return v; }
static int iSetEventFlag(int id,unsigned int f) { (void)id;flags|=f;return 0; }
static int ClearEventFlag(int id,unsigned int mask) { (void)id;flags&=mask;return 0; }
void iLinkInitPHT(void) { dma[0].chcr=dma[2].chcr=0; }
void iLinkPHYBusReset(void) {}
@ISR@
static int WaitEventFlag(int id,unsigned int wanted,int mode,u32 *out) {
    (void)id;(void)mode;
    if(!delivered) { delivered=1;iLinkIntrHandler(NULL); }
    if(simulate_response && !(flags&wanted)) {
        response_copied=1;flags|=iLinkEventDataReceived;
    }
    if(!(flags&wanted)) longjmp(no_wake,1);
    if(out) *out=flags&wanted;
    return 0;
}
@PHT@
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL %s\n",msg);failures++; } } while(0)
static void reset(unsigned int intr0) {
    memset(&regs,0,sizeof(regs));memset(dma,0,sizeof(dma));
    regs.intr0Mask=regs.intr1Mask=~0u;
    flags=LocalCachedIntr0Register=irq1=delivered=0;GenerationNumber=1;irq0=intr0;simulate_response=response_copied=0;
}
static void transfer(unsigned int intr0,int expected) {
    reset(intr0);struct TransactionContextData ctx={.GenerationNumber=1};
    unsigned int payload[2]={0};
    if(setjmp(no_wake)==0) {
        int result=iLinkPHTSendData(&ctx,IEEE1394_TCODE_WRITEB,0xffff,0xf0010000,payload,8,0);
        CHECK(result==expected,"PHT reports the interrupt's actual error/result");
        CHECK(dma[0].chcr==0,"PHT transfer cannot retain a live TX DMA buffer on return");
    } else CHECK(0,"PHT waiter did not wake for its interrupt");
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    transfer(iLink_INTR0_STO,-1024);
    transfer(iLink_INTR0_RetEx,-1026);
    transfer(iLink_INTR0_InvAck,-1023);
    transfer(iLink_INTR0_AckMiss,-1025);
    transfer(iLink_INTR0_PhyRst,-1021);
    transfer(iLink_INTR0_RetEx|iLink_INTR0_PBCntR,-1026);
    transfer(iLink_INTR0_PBCntR,8);
    reset(iLink_INTR0_PBCntR);simulate_response=1;
    struct TransactionContextData reader={.GenerationNumber=1};
    if(setjmp(no_wake)==0) {
        CHECK(iLinkPHTSendData(&reader,IEEE1394_TCODE_READB,0xffff,0xf0010000,NULL,8,0)==8,
              "block read waits for its response");
        CHECK(response_copied,"block read cannot finish on PBCntR before response copy");
    } else CHECK(0,"block read did not wake for copied response");
    reset(iLink_INTR0_RetEx);iLinkIntrHandler(NULL);
    CHECK(LocalCachedIntr0Register&iLink_INTR0_RetEx,"error survives ISR's terminal zero sample");
    irq0=iLink_INTR0_URx;iLinkIntrHandler(NULL);
    CHECK(LocalCachedIntr0Register&iLink_INTR0_RetEx,"unrelated receive IRQ cannot erase the error");
    return failures ? 1 : 0;
}
'''


def run(manager):
    intr=(manager/'iLink_intr.c').read_text(encoding='utf-8')
    dma=(manager/'iLink_DMA.c').read_text(encoding='utf-8')
    isr=function(intr,'int iLinkIntrHandler(')
    isr=isr.replace('= ILINKRegisterBase->intr0 &','= read_intr0() &')
    isr=isr.replace('= ILINKRegisterBase->intr1 &','= read_intr1() &')
    text=HARNESS.replace('@ISR@',isr).replace('@PHT@',function(dma,'static int iLinkPHTSendData('))
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory);cfile=folder/'irq.c';exe=folder/('irq.exe' if sys.platform=='win32' else 'irq')
        cfile.write_text(text,encoding='utf-8')
        subprocess.run(['gcc','-std=gnu99','-Wall','-Wextra','-Werror','-Wno-pointer-to-int-cast',
                        '-Wno-builtin-declaration-mismatch','-I',str(manager/'include'),str(cfile),'-o',str(exe)],check=True,timeout=60)
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
        print(str(manager)+':')
        if result.returncode == 0:
            print(result.stdout.strip() or 'PASS: IRQ errors, reset wake-up and DMA retirement')
        else:
            print(result.stdout.strip() or 'FAIL: harness exited %d' % result.returncode)
            if result.stderr: print(result.stderr.strip())
        return result.returncode==0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    args=parser.parse_args()
    results=[run(args.source_root/p) for p in MANAGERS]
    sys.exit(0 if all(results) else 1)
