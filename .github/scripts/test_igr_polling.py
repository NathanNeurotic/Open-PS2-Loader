"""IGR samples input from a VBLANK_END interrupt handler in every build (issue #984).

Two alarm-based replacements failed on real hardware: a priority-127 polling thread (busy games
never let it run) and sampling in the EE alarm callback (controller and power button both dead in
game). Standard and RetroAchievements builds therefore share OPL's original handler: it samples the
pad and power button each frame, and on a request stops DMA/GS, suspends every game thread and
wakes the worker at priority 0, all from interrupt context. Mode 6 keeps a snapshot-only RA handler.

This compiles the real padhook.c functions twice -- standard and RA -- against kernel stubs and
checks: worker/handler installation and retry, pad/power detection, IOP-reset pad invalidation,
interrupt-side shutdown handoff, the production worker with early and spurious wakes,
actual reset-caller reinstallation after ExecPS2, and that no EE alarm sampler comes back.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'ee_core/src/padhook.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('ee_core/src/padhook.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


# Every build samples from the handler; the failed alarm samplers must not come back.
if 'IGR_VBLANK_HANDLER' in source:
    failures.append('padhook.c: the VBLANK_END handler is unconditional; IGR_VBLANK_HANDLER must not return')
for alarm_call in ('SetAlarm(', 'iSetAlarm(', 'ReleaseAlarm('):
    if alarm_call in source:
        failures.append('padhook.c: IGR must not sample from an EE alarm (%s found, issue #984)' % alarm_call)

asm_source = (root / 'ee_core/src/asm.S').read_text(encoding='utf-8').replace('\r\n', '\n')
for hook_name in ('_SifSetDma', 'Hook_ExecPS2', 'Hook_CreateThread'):
    block = asm_source[asm_source.index(hook_name + ':'):asm_source.index('.end    ' + hook_name)]
    if 'la      $gp, _gp' not in block:
        failures.append('asm.S: %s must load _gp before calling C functions' % hook_name)
    if hook_name in ('_SifSetDma', 'Hook_CreateThread') and ('sd      $gp,' not in block or 'ld      $gp,' not in block):
        failures.append('asm.S: %s must save and restore caller $gp' % hook_name)

install_hook = function_text('int Install_PadOpen_Hook(')
if 'iFlushCache(0);' not in install_hook or 'iFlushCache(2);' not in install_hook:
    failures.append('padhook.c: Install_PadOpen_Hook must flush data and instruction caches after patching')

common = ''.join(function_text(sig) for sig in (
    'void Invalidate_PadBuffer(',
    'static void Set_libpad_Params(',
    'static void IGR_CheckInputs(',
    'static void IGR_StopDmaAndGs(',
))
reset = function_text('void Reset_Padhook(')
handler = function_text('static int IGR_Intc_Handler(')
worker = function_text('static void IGR_Thread(')
install = function_text('void Install_IGR(')
mode6 = ''.join(function_text(sig) for sig in (
    'static int RA_Intc_Handler(',
    'void Install_RA_Vblank(',
    'void IGR_RequestReset(',
))


# Exercise the reset caller with the real installer, not a successful-call stub.
syshook = (root / 'ee_core/src/syshook.c').read_text(encoding='utf-8')
reset_at = syshook.index('u32 New_SifSetDma(')
reset_hook = syshook[reset_at:syshook.index('\n}', reset_at) + 2]
RESET_STUBS = r'''
#define COMPAT_MODE_6 0x20
#define PADOPEN_HOOK 0
static int g_compat_mask, disable_padOpen_hook, padScans, resetResult = 1;
struct _iop_reset_pkt { int arglen; char arg[16]; };
typedef struct { void *src; } SifDmaTransfer_t;
static int New_Reset_Iop(const char *arg, int len) { (void)arg; (void)len; return resetResult; }
static int Install_PadOpen_Hook(u32 a, u32 b, int mode)
{
    (void)a; (void)b; (void)mode;
    padScans++;
    return 1;
}
#ifdef RETROACHIEVEMENTS
static unsigned int ra_snap_iop;
static void Install_RA_Vblank(void) {}
#endif
'''

RESET_CHECKS = r'''
    g_cfg.GameMode = 0;
    struct _iop_reset_pkt packet = {0, {0}};
    SifDmaTransfer_t dma = {&packet};
    for (int cycle = 0; cycle < 2; cycle++) {
        /* ExecPS2 destroys kernel objects, but the new ELF is already patched. */
        Reset_Padhook();
        padOpen_hooked = 1;
        armPad();
        int oldCreates = nCreate, oldHandlers = nAddIntc;
        CHECK(New_SifSetDma(&dma, 1) == 1 && !disable_padOpen_hook,
              "intercepted reboot completes and releases the scan guard");
        CHECK(nCreate == oldCreates + 1 && IGR_Thread_ID >= 0 && padScans == 0,
              "retained PadOpen patch still recreates the actual IGR worker without rescanning");
        CHECK(Pad_Data.pad_buf == NULL && padOpen_hooked == 1,
              "reboot preserves the patch but invalidates the stale pad buffer");
        CHECK(nAddIntc == oldHandlers + 1 && IGR_Intc_ID >= 0,
              "reset caller installs a fresh VBLANK sampler after ExecPS2");
        New_SifSetDma(&dma, 1);
        CHECK(nCreate == oldCreates + 1 && padScans == 0,
              "another IOP reset reuses the surviving worker and controller patch");
        resetResult = 0;
        CHECK(New_SifSetDma(&dma, 1) == 0 && !disable_padOpen_hook && IGR_Thread_ID >= 0,
              "failed IOP reset releases the guard without losing the live monitor");
        resetResult = 1;
    }
    Reset_Padhook();
    startFailures = 1;
    New_SifSetDma(&dma, 1);
    CHECK(IGR_Thread_ID < 0, "worker start failure remains retryable with a retained patch");
    New_SifSetDma(&dma, 1);
    CHECK(IGR_Thread_ID >= 0 && padScans == 0,
          "next reset retries the actual installer even though the ELF is already patched");
    Reset_Padhook();
    g_compat_mask = COMPAT_MODE_6;
    int oldCreates = nCreate;
    New_SifSetDma(&dma, 1);
    CHECK(IGR_Thread_ID < 0 && nCreate == oldCreates && padScans == 0,
          "disabled IGR creates neither worker nor pad scan through the reset caller");
'''


def host_safe(text):
    # MIPS hardware instructions have no host meaning; retain the production C logic.
    text = text.replace('asm volatile("sync.l\\n");', ';')
    # GetCop0 is stubbed to zero, so this MIPS-only performance-counter branch is never taken.
    return re.sub(r'__asm__ __volatile__\(\s*" mfc0  \$3, \$25;".*?\);', ';', text, flags=re.S)


HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;
typedef unsigned long long u64;

#define DPRINTF(...) ((void)0)
#define DISC_MODE 9
#define TH_SELF 0
#define kINTC_VBLANK_END 3
#define IGR_STACK_SIZE 4096
#define IGR_LIBPAD 1
#define IGR_LIBPAD2 2
#define IGR_PAD_STABLE_V1 0x06
#define IGR_PAD_STABLE_V2 0x01
#define IGR_COMBO_R1_L1_R2_L2 0xF0
#define IGR_COMBO_START_SELECT 0xF6
#define IGR_COMBO_R3_L3 0xF9
#define IGR_COMBO_UP 0xEF
static int intrEnabled = 1, unprotectedReads;
static void (*beforeDisable)(void);
static int DI(void) {
    if (intrEnabled && beforeDisable) {
        void (*interrupt)(void) = beforeDisable;
        beforeDisable = NULL;
        interrupt();
    }
    int previous = intrEnabled;
    intrEnabled = 0;
    return previous;
}
static void EI(void) { intrEnabled = 1; }
static void *checkedUncached(void *ptr) {
    if (intrEnabled) unprotectedReads++;
    return ptr;
}
#define UNCACHED_SEG(x) checkedUncached(x)

typedef struct { u16 libpad; u16 libversion; u8 *pad_buf; int vb_count; int pos_combo1; int pos_combo2;
                 int pos_state; int pos_frame; volatile u8 combo_type; u8 prev_frame; } paddata_t;
typedef struct { int press; int vb_count; int latched; } powerbuttondata_t;
/* Match the layout and fields of ps2sdk's ee_thread_t, not a success-only subset. */
typedef struct {
    int status;
    void (*func)(void *);
    void *stack;
    int stack_size;
    void *gp_reg;
    int initial_priority;
    int current_priority;
    u32 attr;
    u32 option;
} ee_thread_t;

struct cfg { int EnableGSMOp; int GameMode; int gCheatList; int MMCEIGRSettings; };
static struct cfg g_cfg;
#define USE_LOCAL_EECORE_CONFIG struct cfg *config = &g_cfg;

/* Fake hardware. The GS reset bit clears itself on the next read, as the real GS does. */
static volatile u32 dmaReg[16];
#define R_EE_D_ENABLER (&dmaReg[0])
#define R_EE_D_ENABLEW (&dmaReg[1])
#define R_EE_D_CTRL (&dmaReg[2])
#define R_EE_D_STAT (&dmaReg[3])
#define R_EE_D0_CHCR (&dmaReg[4])
#define R_EE_D1_CHCR (&dmaReg[5])
#define R_EE_D2_CHCR (&dmaReg[6])
#define R_EE_D3_CHCR (&dmaReg[7])
#define R_EE_D4_CHCR (&dmaReg[8])
#define R_EE_D8_CHCR (&dmaReg[9])
#define R_EE_D9_CHCR (&dmaReg[10])
static volatile u64 gsCsr;
static volatile u64 *gsCsrReg(void)
{
    static int calls;
    if (calls++ & 1)
        gsCsr = 0;
    return &gsCsr;
}
#define R_EE_GS_CSR (gsCsrReg())
static volatile u8 ndin, poff, sdin, scmd;
#define CDVD_R_NDIN (&ndin)
#define CDVD_R_POFF (&poff)
#define CDVD_R_SDIN (&sdin)
#define CDVD_R_SCMD (&scmd)
static int unprotectedKmode;
static void ee_kmode_enter(void) { if (intrEnabled) unprotectedKmode++; }
static void ee_kmode_exit(void) { if (intrEnabled) unprotectedKmode++; }

static int padOpen_hooked;
static paddata_t Pad_Data;
static powerbuttondata_t Power_Button;
static int IGR_Thread_ID = -1;
static int IGR_Intc_ID = -1;
static u8 IGR_Stack[IGR_STACK_SIZE];
static void *_gp;

/* Kernel stubs: every call is counted so the test can say exactly what ran. */
static int nAlarm, nSleep, nWake, lastWake, nPrio, lastPrioThread = -1, lastPrio = -1;
static int nResetEE, lastResetEE, nSuspend, nISuspend, nIResetEE, nIPrio, nIWake, nCreate, nStart, nDelete;
static int createFailures, startFailures;
static ee_thread_t lastCreatedThread;
static int nAddIntc, lastIntcCause = -1, nEnableIntc, nRA;
static u8 padBuf[128];

/* Any EE alarm use would show up here: padhook.c must not arm one (checked above, too). */
static s32 SetAlarm(u16 time, void (*cb)(s32, u16, void *), void *common)
{
    (void)time; (void)cb; (void)common;
    nAlarm++;
    return -1;
}
static int IGR_Intc_Handler(int cause);
static void IGR_Thread(void *arg);
static void (*beforeSleep)(void);
static int pendingWake, workerWaiting, dropRunningWake, lostRunningWakes, consumedWakes, strayWakeups;
static void SleepThread(void)
{
    nSleep++;
    if (strayWakeups) {
        strayWakeups--;
        return;
    }
    /* Inject the interrupt after the production worker read its latch, before it blocks. */
    if (beforeSleep) {
        void (*interrupt)(void) = beforeSleep;
        beforeSleep = NULL;
        interrupt();
    }
    if (!pendingWake) {
        /* Also model raw kernels that reject a RUNNING-thread wake: the persistent
           VBLANK handler runs again after this worker enters WAIT. */
        workerWaiting = 1;
        IGR_Intc_Handler(0);
        workerWaiting = 0;
    }
    if (!pendingWake) {
        fputs("FAIL production worker blocked without a pending or repeated VBLANK wake\n", stderr);
        exit(1);
    }
    pendingWake--;
    consumedWakes++;
}
static void iWakeupThread(int id)
{
    nWake++;
    lastWake = id;
    if (dropRunningWake && !workerWaiting) {
        lostRunningWakes++;
        return;
    }
    pendingWake++;
}
static void WakeupThread(int id) { nWake++; lastWake = id; }
static void ChangeThreadPriority(int id, int prio) { nPrio++; lastPrioThread = id; lastPrio = prio; }
static void ResetEE(u32 bits) { nResetEE++; lastResetEE = bits; }
static void SuspendThread(int id) { (void)id; nSuspend++; }
static void iResetEE(u32 bits) { (void)bits; nIResetEE++; }
static void iSuspendThread(int id) { (void)id; nISuspend++; }
static void iChangeThreadPriority(int id, int prio) { (void)id; (void)prio; nIPrio++; }
static int CreateThread(ee_thread_t *p)
{
    nCreate++;
    lastCreatedThread = *p;
    if (createFailures > 0) {
        createFailures--;
        return -1;
    }
    return 5;
}
static int StartThread(int id, void *arg)
{
    (void)id; (void)arg;
    nStart++;
    if (startFailures > 0) {
        startFailures--;
        return -1;
    }
    return 0;
}
static int DeleteThread(int id) { (void)id; nDelete++; return 0; }
static int AddIntcHandler(int cause, int (*h)(int), int next) { (void)h; (void)next; nAddIntc++; lastIntcCause = cause; return 7; }
static void EnableIntc(int cause) { (void)cause; nEnableIntc++; }
static void ExitHandler(void) {}
static void RA_OnVblank(void) { nRA++; }
/* Reset services are inert; the complete production worker still executes its wait and exit path. */
static int EnableDebug, workerShutdowns, workerExitCalls, workerRpcCalls, prematureShutdown;
#define DBGCOL(...) ((void)0)
#define OPL_MODULE_ID_RESETSPU 1
#define OPL_MODULE_ID_MMCEDRV 2
#define OPL_MODULE_ID_MMCEIGR 3
static void SifInitRpc(int mode)
{
    (void)mode;
    workerRpcCalls++;
    if (!Pad_Data.combo_type)
        prematureShutdown++;
}
static void oplIGRShutdown(int poweroff) { (void)poweroff; workerShutdowns++; }
static int Reset_Iop(const char *arg, int len) { (void)arg; (void)len; return 1; }
static void Remove_Kernel_Hooks(void) {}
static void InitializeTLB(void) {}
static u32 GetCop0(int reg) { (void)reg; return 0; }
static void DisableGSM(void) {}
static void DisableCheats(void) {}
static int SifIopSync(void) { return 1; }
static void SifInitIopHeap(void) {}
static void LoadFileInit(void) {}
static void sbv_patch_enable_lmb(void) {}
static int LoadOPLModule(int id, int mode, int len, void *arg)
{
    (void)id; (void)mode; (void)len; (void)arg;
    return 1;
}
static void SifExitIopHeap(void) {}
static void LoadFileExit(void) {}
static void SifExitRpc(void) {}
static void IGR_Exit(s32 code) { (void)code; workerExitCalls++; }

@CODE@


static int fails;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL %s\n", msg); fails++; } } while (0)

static void armPad(void)
{
    memset(padBuf, 0, sizeof(padBuf));
    Pad_Data.libpad = IGR_LIBPAD;
    Pad_Data.libversion = 0x0160;
    Pad_Data.pad_buf = padBuf;
    Pad_Data.pos_combo1 = 3;
    Pad_Data.pos_combo2 = 2;
    Pad_Data.pos_state = 112;
    Pad_Data.pos_frame = 88;
}

static void prepareWorker(void)
{
    g_cfg.GameMode = g_cfg.EnableGSMOp = g_cfg.gCheatList = g_cfg.MMCEIGRSettings = 0;
    IGR_Thread_ID = 5;
    armPad();
    Pad_Data.combo_type = 0;
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    ndin = poff = scmd = 0;
    pendingWake = workerWaiting = dropRunningWake = lostRunningWakes = consumedWakes = strayWakeups = 0;
    nSleep = nWake = nIResetEE = nISuspend = nIPrio = 0;
    workerShutdowns = workerExitCalls = workerRpcCalls = prematureShutdown = 0;
    beforeSleep = NULL;
}

static void requestAtSleep(void)
{
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    IGR_Intc_Handler(0);
}

int main(void)
{
    (void)RA_OnVblank;

    createFailures = 1;
    Install_IGR();
    CHECK(IGR_Thread_ID < 0 && nCreate == 1 && nStart == 0, "a failed CreateThread stays retryable");
    CHECK(nAddIntc == 0, "no interrupt is registered without a live worker");

    startFailures = 1;
    Install_IGR();
    CHECK(IGR_Thread_ID < 0 && nCreate == 2 && nStart == 1 && nDelete == 1,
          "a failed StartThread deletes its dormant worker and remains retryable");
    CHECK(nAddIntc == 0, "a failed worker never arms the interrupt");

    Install_IGR();
    Install_IGR(); /* a repeated pad open must not recreate the worker or handler */
    CHECK(IGR_Thread_ID == 5 && nCreate == 3 && nStart == 2 && nDelete == 1,
          "retry installs one worker and repeated hooks leave it alone");
    CHECK(lastCreatedThread.status == 0 && lastCreatedThread.current_priority == 0 &&
          lastCreatedThread.attr == 0 && lastCreatedThread.option == 0 &&
          lastCreatedThread.initial_priority == 127,
          "IGR CreateThread receives a fully initialized kernel structure");

    armPad();
    Power_Button.press = 1;
    Power_Button.vb_count = 17;
    Power_Button.latched = 1;
    Pad_Data.combo_type = IGR_COMBO_START_SELECT;
    Install_IGR();
    CHECK(Pad_Data.pad_buf == padBuf && Pad_Data.combo_type == IGR_COMBO_START_SELECT &&
          Power_Button.press == 1 && Power_Button.vb_count == 17 && Power_Button.latched == 1,
          "repeated IGR installation preserves live input and power state");

    armPad();
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[88] = 1;
    Pad_Data.prev_frame = 0;
    Pad_Data.vb_count = 10;
    IGR_CheckInputs();
    CHECK(padOpen_hooked == 1 && Pad_Data.prev_frame == 1 && Pad_Data.vb_count == 0,
          "advancing pad frame counter marks padOpen_hooked");
    Pad_Data.vb_count = 10;
    IGR_CheckInputs();
    CHECK(padOpen_hooked == 1 && Pad_Data.prev_frame == 1 && Pad_Data.vb_count == 0,
          "pausing pad polling during prompts or loads does not clear padOpen_hooked");

    /* IOP reboot leaves an EE worker alive but ends the pad buffer's lifetime.
       Reused memory can look exactly like a stable pad holding the reset combo. */
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    Pad_Data.combo_type = 0;
    Pad_Data.vb_count = 7;
    Pad_Data.prev_frame = 44;
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    Invalidate_PadBuffer();
    CHECK(Pad_Data.pad_buf == NULL && Pad_Data.vb_count == 0 && Pad_Data.prev_frame == 0 && padOpen_hooked == 1,
          "IOP reset discards the old pad buffer without forcing a live-RAM PadOpen rescan");
    padOpen_hooked = 0;
    IGR_CheckInputs();
    CHECK(Pad_Data.combo_type == 0 && IGR_Thread_ID == 5,
          "reused old pad memory cannot reset the game; the worker survives");

    Power_Button.press = 1;
    Power_Button.vb_count = 17;
    Power_Button.latched = 1;
    Pad_Data.combo_type = IGR_COMBO_START_SELECT;
    intrEnabled = 0;
    Invalidate_PadBuffer();
    CHECK(!intrEnabled && Pad_Data.combo_type == IGR_COMBO_START_SELECT &&
          Power_Button.press == 1 && Power_Button.vb_count == 17 && Power_Button.latched == 1,
          "invalidation preserves disabled interrupts and pending reset/power state");
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    Pad_Data.combo_type = 0;
    Set_libpad_Params(padBuf);
    CHECK(!intrEnabled && Pad_Data.pad_buf == padBuf && Pad_Data.pos_state == 112,
          "pad reopen publishes its buffer without enabling disabled interrupts");
    IGR_CheckInputs();
    CHECK(!intrEnabled && Pad_Data.combo_type == IGR_COMBO_START_SELECT && unprotectedReads == 0 && unprotectedKmode == 0,
          "a reopened pad detects real input with an atomic buffer snapshot");
    intrEnabled = 1;
    Invalidate_PadBuffer();
    CHECK(intrEnabled, "invalidation restores interrupts when they were enabled");
    Set_libpad_Params(padBuf);
    Pad_Data.combo_type = 0;
    IGR_CheckInputs();
    CHECK(intrEnabled && unprotectedReads == 0 && unprotectedKmode == 0 && Pad_Data.combo_type == IGR_COMBO_START_SELECT,
          "thread-context polling protects reads and kmode window and restores enabled interrupts");

    /* The physical button IRQ may remain asserted for multiple polling frames
       when Mechacon cancellation is delayed. Count only the first edge. */
    g_cfg.GameMode = 0;
    Pad_Data.pad_buf = NULL;
    Pad_Data.combo_type = 0;
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    ndin = 0x20; poff = 0x04; scmd = 0;
    for (int k = 0; k < 54; ++k)
        IGR_CheckInputs();
    CHECK(Power_Button.press == 1 && Power_Button.latched == 1 &&
          Pad_Data.combo_type == IGR_COMBO_R3_L3,
          "held CDVD event requests power-off, not false double-press reset");
    CHECK(scmd == 0x1B, "single event still issues hardware cancel");
    poff = 0;
    IGR_CheckInputs();
    CHECK(Power_Button.latched == 0, "input re-arms when hardware status clears");
    poff = 0x04;
    IGR_CheckInputs();
    CHECK(Power_Button.press == 2, "new event counts as second press");
    Pad_Data.combo_type = 0;
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    ndin = poff = scmd = 0;
@CHECKS@
    return fails ? 1 : 0;
}
'''

STANDARD_CHECKS = r'''
    CHECK(nAddIntc == 1 && lastIntcCause == kINTC_VBLANK_END && nEnableIntc == 1 && IGR_Intc_ID == 7,
          "standard build registers its VBLANK_END handler once, after the worker starts");
    CHECK(nAlarm == 0, "no EE alarm is armed");

    /* The handler samples in interrupt context, so a game that never yields cannot starve it. */
    armPad();
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[3] = padBuf[2] = 0;
    IGR_Intc_Handler(0);
    CHECK(Pad_Data.combo_type == 0 && nISuspend == 0 && nWake == 0 && nIResetEE == 0,
          "an idle frame neither stops the game nor wakes the worker");
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    IGR_Intc_Handler(0);
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT, "the handler latches the reset combo");
    CHECK(nIResetEE == 1 && nISuspend == 254 && nIPrio == 1 && nWake == 1 && lastWake == IGR_Thread_ID,
          "interrupt-context shutdown: reset the EE, suspend every game thread, then wake the worker");
    CHECK(nResetEE == 0 && nSuspend == 0 && nRA == 0, "no thread-only calls and no RA work from the handler");
    /* Until the worker leaves for the exit ELF, a latched request repeats the handoff every frame,
       exactly as OPL's original handler did: the game stays stopped and the worker stays woken. */
    IGR_Intc_Handler(0);
    CHECK(nIResetEE == 2 && nISuspend == 508 && nIPrio == 2 && nWake == 2 && lastWake == IGR_Thread_ID,
          "a request still latched next frame repeats the same interrupt-side handoff");

    /* The physical power button needs no controller hook. */
    Pad_Data.combo_type = 0;
    Pad_Data.pad_buf = NULL;
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    ndin = 0x20; poff = 0x04; scmd = 0;
    {
        int before = nISuspend, k;
        for (k = 0; k < 60 && !Pad_Data.combo_type; k++)
            IGR_Intc_Handler(0);
        CHECK(Pad_Data.combo_type == IGR_COMBO_R3_L3 && Power_Button.press == 1 && nISuspend == before + 254,
              "one physical press powers off through the handler with no pad buffer");
    }
    ndin = poff = scmd = 0;

    /* ExecPS2 ends the old game's threads and handlers; the next pad-open installs new ones. */
    Reset_Padhook();
    CHECK(IGR_Thread_ID == -1 && IGR_Intc_ID == -1, "ExecPS2 forgets the old worker and handler");
    Install_IGR();
    CHECK(IGR_Thread_ID == 5 && IGR_Intc_ID == 7 && nAddIntc == 2 && Pad_Data.combo_type == 0,
          "the next game installs a fresh worker and handler with no stale request");
'''


WORKER_CHECKS = r'''
    prepareWorker();
    requestAtSleep();
    IGR_Thread(NULL);
    CHECK(nSleep == 0 && consumedWakes == 0 && workerShutdowns == 1 && workerExitCalls == 1,
          "production worker handles a prelatched request without sleeping");

    prepareWorker();
    beforeSleep = requestAtSleep;
    IGR_Thread(NULL);
    CHECK(nSleep == 1 && consumedWakes == 1 && pendingWake == 0 && lostRunningWakes == 0 &&
          nIResetEE == 1 && nISuspend == 254 && workerShutdowns == 1 && workerExitCalls == 1,
          "request at the production check/sleep boundary consumes its pending wake and exits");

    prepareWorker();
    strayWakeups = 1;
    beforeSleep = requestAtSleep;
    IGR_Thread(NULL);
    CHECK(nSleep == 2 && consumedWakes == 1 && workerShutdowns == 1 && workerExitCalls == 1 &&
          prematureShutdown == 0,
          "production worker rechecks a spurious wake before starting shutdown");

    prepareWorker();
    dropRunningWake = 1;
    beforeSleep = requestAtSleep;
    IGR_Thread(NULL);
    CHECK(nSleep == 1 && lostRunningWakes == 1 && consumedWakes == 1 && pendingWake == 0 &&
          nIResetEE == 2 && nISuspend == 508 && workerShutdowns == 1 && workerExitCalls == 1,
          "repeated VBLANK handoff recovers even when a raw kernel drops the early wake");
'''

RA_CHECKS = r'''
    CHECK(nAddIntc == 1 && lastIntcCause == kINTC_VBLANK_END && nEnableIntc == 1,
          "RA build keeps its VBLANK_END handler, registered once");

    /* Every frame feeds RetroAchievements; a combo stops the game from interrupt context. */
    armPad();
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    IGR_Intc_Handler(0);
    CHECK(nRA == 1, "the handler still calls RA_OnVblank");
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT, "the handler sees the same combo");
    CHECK(nIResetEE == 1 && nISuspend == 254 && nIPrio == 1 && nIWake == 0 + nWake, "interrupt-context shutdown, then wake the thread");
    CHECK(nResetEE == 0 && nSuspend == 0, "no thread-only calls from the handler");

    /* Disc mode has no OPL shutdown RPC: R3+L3 is ignored there. */
    Pad_Data.combo_type = 0;
    g_cfg.GameMode = DISC_MODE;
    padBuf[2] = IGR_COMBO_R3_L3;
    IGR_Intc_Handler(0);
    CHECK(Pad_Data.combo_type == 0, "RA disc mode ignores the power-off combo");
'''


MODE6_HARNESS = r'''
#include <stdio.h>
typedef unsigned char u8;
#define kINTC_VBLANK_END 3
#define IGR_COMBO_START_SELECT 0xF6
typedef struct { u8 combo_type; } paddata_t;
static paddata_t Pad_Data;
static int IGR_Thread_ID = -1, RA_Intc_ID = -1;
static int nAddIntc, nEnableIntc, nRA, lastIntcCause, failRegistration = 1;
static int AddIntcHandler(int cause, int (*h)(int), int next)
{
    (void)h; (void)next;
    nAddIntc++;
    lastIntcCause = cause;
    if (failRegistration) {
        failRegistration = 0;
        return -1;
    }
    return 7;
}
static void EnableIntc(int cause) { (void)cause; nEnableIntc++; }
static void RA_OnVblank(void) { nRA++; }
static void ExitHandler(void) {}
@CODE@
static int fails;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL %s\\n", msg); fails++; } } while (0)
int main(void)
{
@CHECKS@
    return fails ? 1 : 0;
}
'''

MODE6_CHECKS = r'''
    CHECK(IGR_Thread_ID == -1 && RA_Intc_ID == -1,
          "Mode 6 begins without an IGR worker or RA interrupt");
    Install_RA_Vblank();
    CHECK(nAddIntc == 1 && nEnableIntc == 0 && RA_Intc_ID == -1,
          "a failed RA handler registration enables no interrupt and remains retryable");
    Install_RA_Vblank();
    Install_RA_Vblank();
    CHECK(nAddIntc == 2 && nEnableIntc == 1 && RA_Intc_ID == 7 &&
          lastIntcCause == kINTC_VBLANK_END,
          "RA-only VBLANK handler installs once after retry");
    RA_Intc_Handler(0);
    CHECK(nRA == 1 && IGR_Thread_ID == -1 && Pad_Data.combo_type == 0,
          "Mode 6 handler takes a snapshot without invoking IGR input or shutdown");
    IGR_RequestReset();
    CHECK(Pad_Data.combo_type == 0,
          "client reset cannot arm an absent IGR worker in Mode 6");
    IGR_Thread_ID = 5;
    IGR_RequestReset();
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT,
          "normal IGR worker still accepts client reset");
'''

def build_and_run(name, defines, code, checks, harness=HARNESS):
    program = defines + harness.replace('@CODE@', host_safe(code)).replace('@CHECKS@', checks)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function',
                                '-Wno-unused-variable', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=10)
        output = (run.stdout + run.stderr).strip()
        if run.returncode != 0 or output:
            failures.extend(('%s: ' % name + line) for line in (output.splitlines() or ['exited %d' % run.returncode]))


if not failures:
    reset_code = RESET_STUBS + reset_hook
    build_and_run('standard', '', common + handler + worker + install + reset + reset_code,
                  STANDARD_CHECKS + RESET_CHECKS + WORKER_CHECKS)
    # nWake counts iWakeupThread for the RA handler too (the stub is shared), so the check compares it.
    ra_checks = RA_CHECKS.replace('nIWake == 0 + nWake', 'nWake == 1')
    build_and_run('retroachievements', '#define RETROACHIEVEMENTS\n',
                  common + handler + worker + install + reset + reset_code, ra_checks + RESET_CHECKS + WORKER_CHECKS)
    build_and_run('ra_mode6', '#define RETROACHIEVEMENTS\n', mode6, MODE6_CHECKS, MODE6_HARNESS)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('IGR: VBLANK sampling, production worker wakes, reset reinstallation and RA Mode 6 passed')
