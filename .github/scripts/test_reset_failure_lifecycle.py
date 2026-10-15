"""Execute production reset callers with failed special-reset stages, standard/RA."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
manager = (ROOT / "ee_core/src/iopmgr.c").read_text(encoding="utf-8")
hooks = (ROOT / "ee_core/src/syshook.c").read_text(encoding="utf-8")
# The real syscall trampoline must preserve C's failure result. A C-only
# harness misses an unconditional success written in the MIPS return slot.
assembly = (ROOT / "ee_core/src/asm.S").read_text(encoding="utf-8")
trampoline = assembly[assembly.index("_SifSetDma:"):assembly.index(".end    _SifSetDma")]
after_call = trampoline[trampoline.index("jal     New_SifSetDma"):]
assert "jr      $ra\n    nop" in after_call
assert "$v0" not in after_call, "reset trampoline overwrites C return value"


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


program = r'''
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "ee_core/include/reset_arg_bounds.h"
typedef unsigned int u32;
typedef int s32;
typedef struct {void *src;} SifDmaTransfer_t;
#define RESET_ARG_MAX 79
typedef struct _iop_reset_pkt {int arglen; char arg[RESET_ARG_MAX + 1];} SifCmdResetData_t;
typedef struct {void *epc, *gp;} t_ExecData;
static struct {unsigned int ModStorageStart;} storage;
#define USE_LOCAL_EECORE_CONFIG __typeof__(storage) *config = &storage; (void)config
#define DPRINTF(...) ((void)0)
#define DBGCOL(...) ((void)0)
#define BGCOLND(...) ((void)0)
#define COMPAT_MODE_6 64
#define PADOPEN_HOOK 0
static int EnableDebug, iop_reboot_count, set_reg_disabled=1, set_reg_hook;
static int g_compat_mask, padOpen_hooked, disable_padOpen_hook;
static int special_calls, fail_stage, exits, loads, wipes, sleeps, ticks;
static unsigned last_payload_length;
static char last_payload[RESET_ARG_MAX + 1];
static unsigned int ra_snap_iop;
static int _end;
static void SifInitRpc(int n) {(void)n;}
static int Reset_Iop(const char *s,int n) {(void)s;(void)n;return 1;}
static int SifIopSync(void) {return 1;}
static void SifInitIopHeap(void) {}
static void LoadFileInit(void) {}
static void sbv_patch_enable_lmb(void) {}
static int ResetIopSpecial(const char *a,unsigned int n) {
 last_payload_length=n;
 if (n) {assert(n<=sizeof(last_payload));memcpy(last_payload,a,n);}
 if (++special_calls==fail_stage) return 0;
 ra_snap_iop=42;return 1;
}
static void SifExitIopHeap(void) {exits++;}
static void LoadFileExit(void) {exits++;}
static void SifExitRpc(void) {exits++;}
#define OPL_MODULE_ID_MCEMU 1
static int LoadOPLModule(int id,int mode,int n,void *p) {
 (void)id;(void)mode;(void)n;(void)p;loads++;return 1;
}
static void Install_IGR(void) {}
static int pad_buffer_live, invalidations;
static void Invalidate_PadBuffer(void) {
 assert(disable_padOpen_hook == 1);
 pad_buffer_live=0;padOpen_hooked=0;invalidations++;
}
static int Install_PadOpen_Hook(int a,int b,int c) {
 (void)a;(void)b;(void)c;
 assert(!pad_buffer_live && disable_padOpen_hook);
 return 1;
}
#ifdef RETROACHIEVEMENTS
static void Install_RA_Vblank(void) {ticks++;}
#endif
static void WipeUserMemory(void *a,void *b) {(void)a;(void)b;wipes++;}
static void FlushCache(int n) {(void)n;}
static int LoadElf(char *s,t_ExecData *e) {(void)s;(void)e;loads++;return -1;}
static void apply_patches(char *s) {(void)s;}
static void CleanExecPS2(void *e,void *g,int n,char **a) {(void)e;(void)g;(void)n;(void)a;}
static void SleepThread(void) {sleeps++;}
@RESET@
@DMA@
@ELF@
static void prepare(int stage) {
 fail_stage=stage;special_calls=exits=loads=wipes=sleeps=ticks=0;
 iop_reboot_count=1;set_reg_disabled=1;set_reg_hook=0;ra_snap_iop=99;
 disable_padOpen_hook=0;g_compat_mask=COMPAT_MODE_6;
 pad_buffer_live=1;invalidations=0;
}
int main(void) {
 char arg[11]="0123456789";
 for(int stage=1;stage<=2;stage++) {
  prepare(stage);
  assert(!New_Reset_Iop(arg,11));
  assert(exits==3 && loads==0 && set_reg_hook==0 && iop_reboot_count==1);
#ifdef RETROACHIEVEMENTS
  assert(ra_snap_iop==0);
#endif
 }
 prepare(1);assert(!New_Reset_Iop(arg,11));
 fail_stage=0;special_calls=0;
 assert(New_Reset_Iop(arg,11));
 assert(iop_reboot_count==2 && set_reg_hook==4 && loads==1);
 prepare(0);
 assert(New_Reset_Iop(arg,11));
 assert(special_calls==2 && exits==3 && loads==1 && set_reg_hook==4);
 prepare(0);assert(New_Reset_Iop(arg,9));assert(special_calls==1);
 char full_arg[80]; memset(full_arg,'A',sizeof(full_arg));
 prepare(0);assert(New_Reset_Iop(full_arg,80));
 assert(special_calls==2 && last_payload_length==70);
 for(unsigned n=0;n<last_payload_length;n++) assert(last_payload[n]=='A');
 for(int bad=81;bad<=83;bad++) {
  prepare(0);assert(New_Reset_Iop(full_arg,bad));assert(special_calls==1);
 }
 prepare(0);assert(New_Reset_Iop(NULL,80));assert(special_calls==1);
 struct _iop_reset_pkt packet={11,"0123456789"};
 SifDmaTransfer_t dma={&packet};
 for(int stage=1;stage<=2;stage++) {
  prepare(stage);assert(New_SifSetDma(&dma,1)==0);
  assert(!disable_padOpen_hook && ticks==0 && loads==0);
  assert(!pad_buffer_live && invalidations==1);
 }
 prepare(0);assert(New_SifSetDma(&dma,1)==1);
 assert(!disable_padOpen_hook);
 assert(!pad_buffer_live && invalidations==1);
#ifdef RETROACHIEVEMENTS
 assert(ticks==1);
#else
 assert(ticks==0);
#endif
 for(int stage=0;stage<=2;stage++) {
  prepare(stage);g_compat_mask=0;padOpen_hooked=1;
  assert(New_SifSetDma(&dma,1)==(stage==0));
  assert(!pad_buffer_live && invalidations==1 && padOpen_hooked==1);
  assert(!disable_padOpen_hook && ticks==0);
 }
 prepare(1);sysLoadElf("game.elf",0,NULL);
 assert(wipes==0 && loads==0 && sleeps==1 && set_reg_disabled==1);
 prepare(0);sysLoadElf("game.elf",0,NULL);
 assert(wipes==1 && loads==2 && sleeps==1);
 puts("PASS: reset failure cleanup, DMA result, RA tick and pre-wipe ELF gate");
}
'''.replace("@RESET@", function(manager, "int New_Reset_Iop("))
program = program.replace("@DMA@", function(hooks, "u32 New_SifSetDma("))
program = program.replace("@ELF@", function(hooks, "void sysLoadElf("))

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    source = path / "test.c"
    source.write_text(program, encoding="utf-8")
    for defines in ([], ["-DRETROACHIEVEMENTS"]):
        exe = path / "test.exe"
        subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-int-to-pointer-cast",
                        "-I", str(ROOT), *defines, str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)
