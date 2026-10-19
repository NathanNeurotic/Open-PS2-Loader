"""Exercise the production VBLANK sampler, retained requests and RA Mode 6.

Hardware and kernel calls are stubbed. Tests establish source behavior, not
console compatibility of VBLANK_END (notably Fatal Fury BA2).
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


if 'SetAlarm(' in source or 'IGR_Poll_Generation' in source:
    failures.append('IGR must not depend on Timer 3 alarms or rearm state')

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
polling = ''.join(function_text(sig) for sig in (
    'static void IGR_WaitForRequest(',
    'void Reset_Padhook(',
))
handler = function_text('static int IGR_Intc_Handler(')
install = function_text('void Install_IGR(')
mode6 = ''.join(function_text(sig) for sig in (
    'static int RA_Intc_Handler(',
    'void Install_RA_Vblank(',
    'void IGR_RequestReset(',
))


def host_safe(text):
    # The MIPS barrier has no host meaning; everything else compiles as written.
    return text.replace('asm volatile("sync.l\\n");', ';')


HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <string.h>

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

struct cfg { int EnableGSMOp; int GameMode; };
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
static int gsResets;
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
static int IGR_Request_Sema = -1;
typedef struct { int count, max_count, init_count, wait_threads; u32 attr, option; } ee_sema_t;
static int semaFailures, semaCreates;
static int CreateSema(ee_sema_t *p) {
    semaCreates++;
    if (p->init_count != 0 || p->max_count != 1) return -1;
    if (semaFailures) { semaFailures--; return -1; }
    return 3;
}
static u8 IGR_Stack[IGR_STACK_SIZE];
static void *_gp;

/* Kernel stubs: every call is counted so the test can say exactly what ran. */
static int nSleep, nWake, lastWake, nPrio, lastPrioThread = -1, lastPrio = -1;
static int nResetEE, lastResetEE, nSuspend, nISuspend, nIResetEE, nIPrio, nIWake, nCreate, nStart, nDelete;
static int createFailures, startFailures;
static ee_thread_t lastCreatedThread;
static int nAddIntc, lastIntcCause = -1, nEnableIntc, nRA;
static u8 padBuf[128];

static int IGR_Intc_Handler(int cause);
static void SleepThread(void)
{
    nSleep++;
    for (int k = 0; k < 150 && !Pad_Data.combo_type; k++) {
        int old = DI();
        IGR_Intc_Handler(0);
        if (old) EI();
    }
}
static void iWakeupThread(int id) { nWake++; lastWake = id; }
static void iSignalSema(int id) { (void)id; nWake++; lastWake = IGR_Thread_ID; }
static void WaitSema(int id) { (void)id; SleepThread(); }
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
static void IGR_Thread(void *arg) { (void)arg; }

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

int main(void)
{
    (void)RA_OnVblank;

    semaFailures = 1;
    Install_IGR();
    CHECK(IGR_Request_Sema < 0 && nCreate == 0,
          "failed request semaphore never starts an unwakeable worker or sampler");
    createFailures = 1;
    Install_IGR();
    CHECK(IGR_Thread_ID < 0 && nCreate == 1 && nStart == 0, "a failed CreateThread stays retryable");
    CHECK(nAddIntc == 0, "RA must not register an interrupt without a live worker");

    startFailures = 1;
    Install_IGR();
    CHECK(IGR_Thread_ID < 0 && nCreate == 2 && nStart == 1 && nDelete == 1,
          "a failed StartThread deletes its dormant worker and remains retryable");
    CHECK(nAddIntc == 0, "a failed worker never arms the RA interrupt");

    Install_IGR();
    Install_IGR(); /* a repeated pad open must not recreate the worker or handler */
    CHECK(IGR_Thread_ID == 5 && nCreate == 3 && nStart == 2 && nDelete == 1,
          "retry installs one worker and repeated hooks leave it alone");
    CHECK(lastCreatedThread.status == 0 && lastCreatedThread.current_priority == 0 &&
          lastCreatedThread.attr == 0 && lastCreatedThread.option == 0 &&
          lastCreatedThread.initial_priority == 127,
          "IGR CreateThread receives a fully initialized kernel structure");
    CHECK(semaCreates == 2 && IGR_Request_Sema == 3,
          "semaphore allocation retries once and is reused across worker retries and pad opens");

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
    CHECK(nAddIntc == 1 && nEnableIntc == 1 && IGR_Intc_ID >= 0,
          "one VBLANK sampler installed before the worker runs");
    armPad();
    padBuf[112] = IGR_PAD_STABLE_V1;
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    IGR_Intc_Handler(0);
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT && nWake == 1 && nISuspend == 254,
          "input detection and priority-zero handoff do not need an alarm or worker CPU");
    CHECK(nResetEE == 0 && nIResetEE == 0, "interrupt leaves peripheral shutdown to the worker");
    IGR_WaitForRequest();
    CHECK(nSleep == 0 && nResetEE == 1 && lastResetEE == 0x7f,
          "worker consumes prelatched request and resets once");
#ifdef RETROACHIEVEMENTS
    CHECK(nRA == 1, "combined handler still feeds RA");
    g_cfg.GameMode = DISC_MODE;
    Pad_Data.combo_type = 0;
    padBuf[2] = IGR_COMBO_R3_L3;
    IGR_Intc_Handler(0);
    CHECK(Pad_Data.combo_type == 0, "physical-disc RA ignores the OPL poweroff RPC");
    g_cfg.GameMode = 0;
#endif
    // Physical power remains sampled with NO live controller buffer.
    Pad_Data.pad_buf = NULL; Pad_Data.combo_type = 0;
    Power_Button.press = Power_Button.vb_count = Power_Button.latched = 0;
    ndin = 0x20; poff = 0x04;
    int before = nSleep;
    IGR_WaitForRequest();
    CHECK(Pad_Data.combo_type == IGR_COMBO_R3_L3 && nSleep == before + 1,
          "power button wakes the blocked worker independently of pad and timers");
    Reset_Padhook();
    CHECK(IGR_Thread_ID == -1 && IGR_Intc_ID == -1 && IGR_Request_Sema == -1,
          "ExecPS2 invalidates all kernel-owned handles");
    Pad_Data.combo_type = 0; poff = 0;
    Install_IGR();
    CHECK(IGR_Thread_ID >= 0 && IGR_Request_Sema >= 0 && nAddIntc == 2,
          "new ELF reinstalls its sampler and request channel");
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
        if run.returncode != 0 or run.stdout.strip():
            failures.extend(('%s: ' % name + line) for line in (run.stdout.strip().splitlines() or ['exited %d' % run.returncode]))


if not failures:
    build_and_run('standard', '', common + polling + handler + install, STANDARD_CHECKS)
    build_and_run('retroachievements', '#define RETROACHIEVEMENTS\n',
                  common + polling + handler + install, STANDARD_CHECKS)
    build_and_run('ra_mode6', '#define RETROACHIEVEMENTS\n', mode6, MODE6_CHECKS, MODE6_HARNESS)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('IGR: VBLANK baseline, controller/power detection, lifecycle and RA Mode 6 passed')
