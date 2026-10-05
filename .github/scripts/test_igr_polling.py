"""IGR without a VBLANK_END handler (upstream OPL #1762), except in RetroAchievements builds.

Merely registering a VBLANK_END interrupt handler black-screens some games (Fatal Fury: Battle
Archives Volume 2). Standard builds now poll the pad from the IGR thread, woken about once a frame by
an alarm, and stop the game themselves from thread context. RetroAchievements builds keep the
handler: RA_OnVblank's snapshot DMA (isceSifSetDma) and unlock overlay are interrupt-context code
that must run every frame.

This compiles the real padhook.c functions twice -- standard and RA -- against kernel stubs and
checks: who registers what at install, that a combo or the power button is detected the same way on
both paths, and that the shutdown preparation (priority, DMA/GS stop, ResetEE, suspend every other
thread) happens exactly once, with the thread-context calls on one path and the i* calls on the other.
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


# The handler may only exist, and only be registered, in RA builds.
if not re.search(r'#ifdef RETROACHIEVEMENTS\s*\n#define IGR_VBLANK_HANDLER', source):
    failures.append('padhook.c: IGR_VBLANK_HANDLER must be defined for RETROACHIEVEMENTS builds only')
handler_at = source.find('static int IGR_Intc_Handler(')
guard_at = source.rfind('#ifdef IGR_VBLANK_HANDLER', 0, handler_at)
if handler_at < 0 or guard_at < 0 or source.find('#endif', guard_at) < handler_at:
    failures.append('padhook.c: IGR_Intc_Handler must sit inside #ifdef IGR_VBLANK_HANDLER')

common = ''.join(function_text(sig) for sig in (
    'static void IGR_CheckInputs(',
    'static void IGR_StopDmaAndGs(',
))
polling = ''.join(function_text(sig) for sig in (
    'static void IGR_Poll_Alarm(',
    'static void IGR_PollUntilRequested(',
))
handler = function_text('static int IGR_Intc_Handler(')
install = function_text('void Install_IGR(')


def host_safe(text):
    # The MIPS barrier has no host meaning; everything else compiles as written.
    return text.replace('asm volatile("sync.l\\n");', ';')


HARNESS = r'''
#include <stdio.h>
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
#define UNCACHED_SEG(x) (x)

typedef struct { u16 libpad; u16 libversion; u8 *pad_buf; int vb_count; int pos_combo1; int pos_combo2;
                 int pos_state; int pos_frame; u8 combo_type; u8 prev_frame; } paddata_t;
typedef struct { int press; int vb_count; } powerbuttondata_t;
typedef struct { void *gp_reg; void (*func)(void *); void *stack; int stack_size; int initial_priority; } ee_thread_t;

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
static void ee_kmode_enter(void) {}
static void ee_kmode_exit(void) {}

static int padOpen_hooked;
static paddata_t Pad_Data;
static powerbuttondata_t Power_Button;
static int IGR_Thread_ID = -1;
static int IGR_Intc_ID = -1;
static u8 IGR_Stack[IGR_STACK_SIZE];
static void *_gp;

/* Kernel stubs: every call is counted so the test can say exactly what ran. */
static int nAlarm, alarmFails, nSleep, nNop, nWake, lastWake, nPrio, lastPrioThread = -1, lastPrio = -1;
static int nResetEE, lastResetEE, nSuspend, nISuspend, nIResetEE, nIPrio, nIWake, nCreate, nStart;
static int nAddIntc, lastIntcCause = -1, nEnableIntc, nRA;
static int sleepsUntilCombo = -1, powerPressAtSleep = -1;
static u8 padBuf[128];
static void (*alarmHandler)(s32, u16, void *);
static void *alarmCommon;

static s32 SetAlarm(u16 time, void (*cb)(s32, u16, void *), void *common)
{
    nAlarm++;
    if (alarmFails > 0) {
        alarmFails--;
        return -1;
    }
    if (time != 256)
        printf("FAIL alarm time %u, expected 256 (about one frame)\n", time);
    alarmHandler = cb;
    alarmCommon = common;
    return 1;
}
static void SleepThread(void)
{
    nSleep++;
    if (alarmHandler)
        alarmHandler(1, 256, alarmCommon); /* the alarm fires and wakes us */
    if (sleepsUntilCombo == nSleep) {
        padBuf[112] = IGR_PAD_STABLE_V1;
        padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
        padBuf[2] = IGR_COMBO_START_SELECT;
    }
    if (powerPressAtSleep == nSleep) {
        ndin = 0x20;
        poff = 0x04;
    } else {
        poff = 0; /* one press, released */
    }
}
static void nopdelay(void) { nNop++; }
static void iWakeupThread(int id) { nWake++; lastWake = id; }
static void ChangeThreadPriority(int id, int prio) { nPrio++; lastPrioThread = id; lastPrio = prio; }
static void ResetEE(u32 bits) { nResetEE++; lastResetEE = bits; }
static void SuspendThread(int id) { (void)id; nSuspend++; }
static void iResetEE(u32 bits) { (void)bits; nIResetEE++; }
static void iSuspendThread(int id) { (void)id; nISuspend++; }
static void iChangeThreadPriority(int id, int prio) { (void)id; (void)prio; nIPrio++; }
static int CreateThread(ee_thread_t *p) { (void)p; nCreate++; return 5; }
static void StartThread(int id, void *arg) { (void)id; (void)arg; nStart++; }
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
    Install_IGR();
    Install_IGR(); /* a second pad open must not create a second thread or handler */
    CHECK(nCreate == 1 && nStart == 1, "install creates and starts the IGR thread exactly once");
@CHECKS@
    return fails ? 1 : 0;
}
'''

STANDARD_CHECKS = r'''
    CHECK(nAddIntc == 0 && nEnableIntc == 0, "standard build registers nothing on VBLANK_END");
    CHECK(IGR_Intc_ID == -1, "standard build leaves the handler id unset");

    /* A combo held from the third frame. */
    armPad();
    sleepsUntilCombo = 3;
    IGR_PollUntilRequested();
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT, "polling sees Start+Select with R1+L1+R2+L2");
    CHECK(nSleep == 3 && nAlarm == 3, "polling sleeps on a one-frame alarm between checks");
    CHECK(nWake == 3 && lastWake == IGR_Thread_ID, "the alarm wakes the IGR thread");
    CHECK(nPrio == 1 && lastPrioThread == TH_SELF && lastPrio == 0, "the thread raises itself to priority 0");
    CHECK(nResetEE == 1 && lastResetEE == 0x7F, "thread context calls ResetEE(0x7F)");
    CHECK(nIResetEE == 0 && nISuspend == 0, "no interrupt-only calls from the thread");
    CHECK(nSuspend == 254, "every thread but the IGR thread is suspended");

    /* No free alarm slot: never sleep without one; keep polling. */
    nAlarm = nSleep = nNop = 0;
    alarmHandler = NULL;
    Pad_Data.combo_type = 0;
    armPad();
    alarmFails = 2;
    sleepsUntilCombo = 1;
    IGR_PollUntilRequested();
    CHECK(nNop == 2 && nSleep == 1, "a failed SetAlarm delays instead of sleeping forever");

    /* One power-button press: about a second later, power off. */
    nSleep = 0;
    Pad_Data.combo_type = 0;
    Pad_Data.pad_buf = NULL;
    Power_Button.press = 0;
    Power_Button.vb_count = 0;
    sleepsUntilCombo = -1;
    powerPressAtSleep = 1;
    IGR_PollUntilRequested();
    CHECK(Pad_Data.combo_type == IGR_COMBO_R3_L3 && Power_Button.press == 1, "one power-button press powers off");
    CHECK(nSleep >= 50, "the power button waits about a second for a second press");
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


def build_and_run(name, defines, code, checks):
    program = defines + HARNESS.replace('@CODE@', host_safe(code)).replace('@CHECKS@', checks)
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
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        if run.returncode != 0 or run.stdout.strip():
            failures.extend(('%s: ' % name + line) for line in (run.stdout.strip().splitlines() or ['exited %d' % run.returncode]))


if not failures:
    build_and_run('standard', '', common + polling + install, STANDARD_CHECKS)
    # nWake counts iWakeupThread for the RA handler too (the stub is shared), so the check compares it.
    ra_checks = RA_CHECKS.replace('nIWake == 0 + nWake', 'nWake == 1')
    build_and_run('retroachievements', '#define RETROACHIEVEMENTS\n#define IGR_VBLANK_HANDLER\n',
                  common + handler + install, ra_checks)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('IGR: standard builds poll without VBLANK_END; RA builds keep the handler; one shutdown path each')
