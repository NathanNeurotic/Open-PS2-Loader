"""Compile real iLinkman paths and fault-inject bus changes and early TX errors.

The only instrumentation replaces a volatile receive-FIFO read with a counted
read. This verifies draining with TTY logging disabled as well as enabled.
--source-dir checks an unmodified source snapshot to demonstrate the failures.
"""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--source-dir', type=Path)
args = parser.parse_args()
managers = [args.source_dir] if args.source_dir else [
    ROOT / 'modules/ilink/iLinkman/src',
    ROOT / 'modules/bdmassault/ilink_bd_assault/src/iLinkman/src',
]


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    assert match, signature
    return source[match.start():source.index('\n}', match.start()) + 2]


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
typedef unsigned int u32;
typedef struct { unsigned int lo,hi; } iop_sys_clock_t;
struct TransactionContextData { int GenerationNumber; unsigned short NodeID; unsigned char speed; };
struct ieee1394_TrPacketHdr { unsigned int header,offset_high,offset_low,misc; };
static unsigned char NextRequestLabel;
enum { IEEE1394_TCODE_READQ=4, IEEE1394_TCODE_READQ_RESPONSE=6, IEEE1394_TCODE_WRITEQ=0, IEEE1394_TCODE_WRITE_RESPONSE=2 };
static void iLinkPrepareResponse(struct TransactionContextData *ctx,unsigned char label,unsigned char code,void *buffer,unsigned int length) {
    (void)ctx;(void)label;(void)code;(void)buffer;(void)length;
}
struct Registers { unsigned int ubufTransmitClear,ubufTransmitNext,ubufTransmitLast; };
static struct Registers regs;
static struct Registers *ILINKRegisterBase=&regs;
static int GenerationNumber=1,IntrEventFlag=2,UBUFTxSema=3;
static unsigned int LocalCachedIntr0Register;
enum { iLinkEventDataSent=1,iLinkEventDataReceived=2,iLinkEventError=4,iLinkEventRequestError=128,
       iLink_INTR0_InvAck=8,iLink_INTR0_STO=16,iLink_INTR0_AckMiss=32,iLink_INTR0_RetEx=64,iLink_INTR0_UResp=256,
       WEF_OR=1 };
#ifdef DEBUG_TTY_FEEDBACK
#define DEBUG_PRINTF(...) do { if (0) printf(__VA_ARGS__); } while(0)
#else
#define DEBUG_PRINTF(...) ((void)0)
#endif
static int available,waits,signals,blocks,alarms,cancels,earlyError,rxReads,failures;
static int changeOnClear,changeOnResponse;
static jmp_buf blocked;
static int WaitSema(int id) {
    (void)id;waits++;
    if(!available) { blocks++;longjmp(blocked,1); }
    available=0;return 0;
}
static int SignalSema(int id) { (void)id;signals++;available=1;return 0; }
static int ClearEventFlag(int id,unsigned int bits) {
    (void)id;(void)bits;
    if(changeOnClear) GenerationNumber++;
    return 0;
}
static int WaitEventFlag(int id,int bits,int mode,u32 *out) {
    (void)id;(void)bits;(void)mode;
    if(changeOnResponse && (bits&iLinkEventRequestError)) GenerationNumber++;
    *out=(earlyError && (earlyError==1 || (bits&iLinkEventRequestError))) ? (bits&iLinkEventRequestError ? iLinkEventRequestError : iLinkEventError) : iLinkEventDataSent|iLinkEventDataReceived;
    return 0;
}
static int iSetEventFlag(int id,int bits) { (void)id;(void)bits;return 0; }
static int SetAlarm(iop_sys_clock_t *clock,unsigned int (*fn)(void *),void *arg) {
    (void)clock;(void)fn;(void)arg;alarms++;return 0;
}
static int CancelAlarm(unsigned int (*fn)(void *),void *arg) {
    (void)fn;(void)arg;cancels++;alarms=0;return 0;
}
static unsigned int read_rx(volatile unsigned int *buffer) { rxReads++;return *buffer; }
@FUNCTIONS@
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL: %s\n",msg);failures++; } } while(0)
static void reset(void) {
    available=1;waits=signals=blocks=alarms=cancels=earlyError=rxReads=changeOnClear=changeOnResponse=0;
    GenerationNumber=1;LocalCachedIntr0Register=0;memset(&regs,0,sizeof(regs));
}
static void stale(int headerLength,int payloadLength,int atClear) {
    unsigned int header[]={1,2,3},payload[]={4,5};
    reset();changeOnClear=atClear;
    struct TransactionContextData old={.GenerationNumber=atClear ? 1 : 0};
    CHECK(iLinkSendData(&old,header,headerLength,payload,payloadLength)==-1021,
          "stale transaction reports the generation error");
    CHECK(available && waits==signals,"generation error releases the TX semaphore");
    CHECK(regs.ubufTransmitLast==0,"generation error does not commit a partial packet");
    changeOnClear=0;
    struct TransactionContextData fresh={.GenerationNumber=GenerationNumber};
    if(setjmp(blocked)==0) {
        CHECK(iLinkSendData(&fresh,header,3,payload,2)==2,"new generation can transmit");
    } else {
        CHECK(0,"new generation blocked behind leaked TX semaphore");
    }
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    (void)read_rx;
    stale(3,2,0);stale(0,2,0);stale(3,2,1);
    reset();unsigned int data[]={1,2,3};
    struct TransactionContextData ctx={.GenerationNumber=1};
    CHECK(iLinkSendData(&ctx,data,3,NULL,0)==0 && available,"successful TX unlocks");
    reset();earlyError=1;
    CHECK(iLinkSendData(NULL,data,3,NULL,0)<0 && available,"response TX error unlocks");
    reset();earlyError=1;
    CHECK(iLinkSync(12)<0,"early response error is reported");
    CHECK(alarms==0 && cancels==1,"early error cancels its alarm before a retry");
    reset();CHECK(iLinkSync(12)==12 && alarms==0,"successful response cancels alarm");
    for(int write=0;write<2;write++) {
        reset();earlyError=2;changeOnResponse=1;
        CHECK((write ? iLinkWriteReq(&ctx,0,0,data,4) : iLinkReadReq(&ctx,0,0,data,4))==-1021,
              "UBUF response wait reports a generation change as reset, not split timeout");
        CHECK(available && alarms==0,"bus reset releases transmit and alarm resources");
        reset();earlyError=2;
        CHECK((write ? iLinkWriteReq(&ctx,0,0,data,4) : iLinkReadReq(&ctx,0,0,data,4))==-1024,
              "unchanged generation preserves a real split timeout");
        reset();
        CHECK((write ? iLinkWriteReq(&ctx,0,0,data,4) : iLinkReadReq(&ctx,0,0,data,4))==12,
              "successful quadlet request retains its transfer result");
    }
    reset();NoResponseHandler(0,data,3);
    CHECK(rxReads==3,"unhandled packet is drained with current TTY configuration");
    return failures ? 1 : 0;
}
'''

failed = False
for manager in managers:
    tx = (manager / 'iLink_TxRx.c').read_text(encoding='utf-8')
    intr = (manager / 'iLink_intr.c').read_text(encoding='utf-8')
    functions = '\n'.join(function(tx, s) for s in (
        'static int iLinkSendData(', 'static unsigned int TimeoutCallbackFunction(', 'static int iLinkSync(',
        'int iLinkReadReq(', 'int iLinkWriteReq('))
    functions = 'static iop_sys_clock_t Timeout={0,0};\n' + functions
    functions += '\n' + function(intr, 'static void NoResponseHandler(').replace('data = *buffer;', 'data = read_rx(buffer);')
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'manager.c'
        source.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        exe = Path(directory) / 'manager.exe'
        for flags in ([], ['-DDEBUG_TTY_FEEDBACK']):
            subprocess.run(['gcc','-std=c99','-Wall','-Wextra','-Werror',*flags,str(source),'-o',str(exe)],check=True)
            run = subprocess.run([str(exe)],capture_output=True,text=True)
            print(str(manager), 'TTY on' if flags else 'TTY off')
            print(run.stdout,end='')
            failed |= run.returncode != 0
if failed:
    raise SystemExit(1)
print('PASS: generation cancellation unlocks TX, retry alarms retire, and RX packets drain')
