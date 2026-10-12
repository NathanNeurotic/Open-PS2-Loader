"""Compile reset payload bounds and verify the EE core uses the guarded offset."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "ee_core/src/iopmgr.c").read_text(encoding="utf-8")
assert "eeResetPayloadLength(arglen, sizeof(((SifCmdResetData_t *)0)->arg), RESET_ARG_MAX + 1)" in source
assert "arg != NULL && payloadLen >= 0" in source
assert "arg[EE_RESET_PREFIX_BYTES]" in source
assert "arglen < (int)sizeof(reset_pkt.arg) - 1" in source
assert "reset_pkt.arg[arglen] = '\\0';" in source
assert "if (pIOP_buffer == NULL)" in source
assert "arglen > sizeof(command) - EE_RESET_SUFFIX_BYTES" in source
begin = source.index("    if (arglen > 0) {", source.index("static int ResetIopSpecial("))
end = source.index("    GetOPLModInfo(", begin)
construction = source[begin:end]
outbound_start = source.index("int Reset_Iop(")
outbound = source[outbound_start:source.index("\n}", outbound_start) + 2]
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define DPRINTF(...) ((void)0)
#define _strcpy strcpy
#define SIF_CMD_RESET_CMD 3
#define SIF_SYSREG_SUBADDR 1
#define SIF_REG_SMFLAG 2
#define SIF_STAT_BOOTEND 4
#define SIF_STAT_SIFINIT 8
#define SIF_STAT_CMDINIT 16
#define SIF_SYSREG_RPCINIT 3
#define SIF_DMA_ERT 1
#define SIF_DMA_INT_O 2
typedef struct {
    struct {unsigned psize,dest,cid,opt;} header;
    int arglen,mode;
    char arg[80];
} SifCmdResetData_t;
struct t_SifDmaTransfer {void *src,*dest; unsigned size,attr;};
static int _iop_reboot_count, dma_calls, reg_calls, cache_calls, intr_calls;
static SifCmdResetData_t sent;
static void *SifGetReg(int reg) {(void)reg;return NULL;}
static void SifWriteBackDCache(void *p,unsigned n) {(void)p;(void)n;cache_calls++;}
static void DIntr(void) {intr_calls++;}
static void EIntr(void) {}
static void ee_kmode_enter(void) {}
static void ee_kmode_exit(void) {}
static int Old_SifSetReg(unsigned reg,int value) {(void)reg;(void)value;reg_calls++;return 1;}
static int Old_SifSetDma(struct t_SifDmaTransfer *dma,int count) {
    assert(count==1 && dma->size==sizeof(sent));
    sent=*(SifCmdResetData_t *)dma->src;dma_calls++;return 1;
}
@OUTBOUND@
#include "ee_core/include/reset_arg_bounds.h"
static int build_command(const char *args, unsigned arglen, char *out, unsigned *length) {
    char command[80];
    unsigned CommandLen;
@CONSTRUCTION@
    memcpy(out, command, CommandLen);
    *length = CommandLen;
    return 1;
}
int main(void) {
    char oversized[81], exact[80];
    memset(oversized,'B',80);oversized[80]=0;
    memset(exact,'C',79);exact[79]=0;
    _iop_reboot_count=100;
    assert(!Reset_Iop(oversized,0));
    assert(_iop_reboot_count==100 && !dma_calls && !reg_calls && !cache_calls && !intr_calls);
    assert(Reset_Iop(exact,7));
    assert(_iop_reboot_count==101 && dma_calls==1 && sent.arglen==79 && sent.mode==7);
    assert(!memcmp(sent.arg,exact,sizeof(exact)));
    assert(Reset_Iop(NULL,0) && sent.arglen==0 && sent.arg[0]==0);
    assert(Reset_Iop("",0) && sent.arglen==0);
    char payload[80], out[82]; unsigned length=0;
    memset(payload,'A',sizeof(payload)); memset(out,'Z',sizeof(out));
    assert(build_command(payload,73,out,&length) && length==80);
    assert(out[72]=='A' && out[73]==0 && !memcmp(out+74,"host0:",6));
    assert(out[80]=='Z' && out[81]=='Z');
    memset(out,'Z',sizeof(out));
    assert(!build_command(payload,74,out,&length) && out[0]=='Z');
    assert(!build_command(NULL,1,out,&length));
    assert(build_command(NULL,0,out,&length) && length==6 && !memcmp(out,"host0:",6));
    assert(eeResetPayloadLength(-1, 80, 80) == -1);
    assert(eeResetPayloadLength(0, 80, 80) == -1);
    assert(eeResetPayloadLength(9, 80, 80) == -1);
    assert(eeResetPayloadLength(10, 80, 80) == 0);
    assert(eeResetPayloadLength(11, 80, 80) == 1);
    assert(eeResetPayloadLength(80, 80, 80) == 70);
    assert(eeResetPayloadLength(81, 80, 80) == -1);
    assert(eeResetPayloadLength(10, 80, 6) == -1);
    assert(eeResetPayloadLength(82, 80, 80) == -1);
    assert(eeResetPayloadLength(83, 80, 80) == -1);
    assert(eeResetPayloadLength(19, 80, 16) == 9);
    assert(eeResetPayloadLength(20, 80, 16) == -1);
    assert(eeResetPayloadLength(2147483647, 80, 80) == -1);
    puts("PASS: IOP reset payload boundary validation");
    return 0;
}
'''.replace("@CONSTRUCTION@", construction).replace("@OUTBOUND@", outbound)
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "test.c"
    exe = Path(d) / "test"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-pointer-to-int-cast", "-I", str(root),
                    str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
