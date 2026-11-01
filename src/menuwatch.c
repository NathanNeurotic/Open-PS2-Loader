/*
  Menu freeze report (diagnostic builds only). See include/menuwatch.h.

  Written for a report of the menu freezing a few seconds after boot on a fat console, with every
  device off and RiptOPL booted from the memory card: nothing on the console says where it stopped.
  The watchdog runs above every other EE thread, so it still gets the CPU when the GUI thread spins
  or waits forever. What it cannot survive is the EE with interrupts off (DelayThread never returns).

  An EE exception (a NULL pointer, a bad address, a reserved instruction ...) looked the same: with no
  handler the kernel parks the CPU, so the watchdog never ran either and the screen just froze. The
  crash catcher (from YAOPL, Roman Kelesidis: yaopl/yaopl ebffcf6) takes those exceptions, sends the
  crashed thread into crashReport() on a stack of its own and writes RIPTOPL-CRASH.TXT with the
  exception, the registers and the code addresses on the stack. A VBlank interrupt handler (YAOPL
  c1fdeb0) keeps the last PCs it interrupted, so a freeze report also says where the EE was running.
*/

#ifdef __OPLDIAG

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <kernel.h>
#include <delaythread.h>
#include <ee_debug.h> // the crash catcher's exception handlers (libeedebug)

#include "include/opl.h"
#include "include/gui.h"
#include "include/pad.h"
#include "include/diaglog.h"
#include "include/renderman.h"
#include "include/menuwatch.h"

#define MENUWATCH_POLL_US     (250 * 1000)
#define MENUWATCH_STALL_S     8  // in the menu
#define MENUWATCH_BOOT_S      20 // while booting, where a device wait can be long
#define MENUWATCH_INTRO_S     60 // boot splash: counted from the stage start, frames or not
#define MENUWATCH_STACK_SIZE  (16 * 1024)
#define MENUWATCH_REPORT_SIZE (24 * 1024)
#define MENUWATCH_LOG_SIZE    (12 * 1024)

// GS privileged registers: with both read circuits off the screen shows the background colour, so
// the colour is visible whatever the last frame was.
#define MW_GS_PMODE   ((volatile u64 *)0x12000000)
#define MW_GS_BGCOLOR ((volatile u64 *)0x120000E0)

extern void *_gp;

static volatile int watchStep = MENUWATCH_BOOT;
static int guiThreadId = -1;
static u8 watchStack[MENUWATCH_STACK_SIZE] __attribute__((aligned(16)));
static char report[MENUWATCH_REPORT_SIZE];
static char logCopy[MENUWATCH_LOG_SIZE];

// Crash catcher state. The exception handler runs in exception context (no kernel calls): it only
// copies registers here and redirects the thread into crashReport().
#define CRASH_STACK_SIZE (16 * 1024)
#define EPC_SAMPLES      16
typedef struct
{
    u32 cause, epc, badvaddr, status;
    u32 at, v0, v1, a0, a1, a2, a3, t0, t1, t2, t3, s0, s1, s2, s3, s4, s5, s6, s7, t9, gp, sp, fp, ra;
} crash_regs_t;
static crash_regs_t crashRegs;
static volatile int crashCount;
static u8 crashStack[CRASH_STACK_SIZE] __attribute__((aligned(16)));
static u8 parkStack[256] __attribute__((aligned(16))); // a second exception parks here: the report may still be on crashStack
static int epcHandlerId = -1;
static int crashCatcherOn;
static volatile u32 epcRing[EPC_SAMPLES];
static volatile u32 epcTicks;
extern char _ftext[], _etext[];

static const char *stepName(int step)
{
    static const char *const names[] = {"?", "boot (before the menu loop)", "frame start (GUI lock, render start)", "pad read",
                                        "screen draw and input", "overlays", "notifications", "deferred menu updates",
                                        "frame end (render flush, vsync)", "input dispatch", "frame hook",
                                        "boot: pad driver, boot folder and memory card probes (red)",
                                        "boot: settings file location and early video-mode read (yellow)",
                                        "boot: video, language, theme and GUI setup (blue)",
                                        "boot: IO thread and menu setup (cyan)",
                                        "boot: controller scan and wait (white)",
                                        "boot: loading the settings (grey)",
                                        "boot: intro screen and device start-up (purple)"};

    return (step > 0 && step < (int)(sizeof(names) / sizeof(names[0]))) ? names[step] : names[0];
}

static int isBootStep(int step)
{
    return step == MENUWATCH_BOOT || (step >= MENUWATCH_BOOT_DIR && step <= MENUWATCH_BOOT_INTRO);
}

static const char *threadState(int status)
{
    switch (status) {
        case THS_RUN:
            return "RUN";
        case THS_READY:
            return "READY";
        case THS_WAIT:
            return "WAIT";
        case THS_SUSPEND:
            return "SUSPEND";
        case THS_WAITSUSPEND:
            return "WAIT+SUSPEND";
        case THS_DORMANT:
            return "DORMANT";
        default:
            return "?";
    }
}

static void screen(u8 r, u8 g, u8 b)
{
    *MW_GS_PMODE = 0;
    *MW_GS_BGCOLOR = (u64)r | ((u64)g << 8) | ((u64)b << 16);
}

// The boot stage's colour (include/menuwatch.h), so a boot that never drew a frame says where it
// stopped without the card. Before rmInit() the screen is still set up by the launcher, which is
// enough for the background colour to show.
static void bootColour(int step)
{
    static const u8 colours[][3] = {
        {0xFF, 0x00, 0x00}, // red: boot folder, memory card probes, pad driver
        {0xFF, 0xFF, 0x00}, // yellow: settings file location, early video-mode read
        {0x00, 0x00, 0xFF}, // blue: video, language, theme, GUI setup
        {0x00, 0xFF, 0xFF}, // cyan: IO thread, menu setup
        {0xFF, 0xFF, 0xFF}, // white: controller scan and wait
        {0x80, 0x80, 0x80}, // grey: loading the settings
        {0x80, 0x00, 0xFF}, // purple: intro screen, device start-up
    };
    int i;

    if (step < MENUWATCH_BOOT_DIR || step > MENUWATCH_BOOT_INTRO)
        return;
    screen(colours[step - MENUWATCH_BOOT_DIR][0], colours[step - MENUWATCH_BOOT_DIR][1], colours[step - MENUWATCH_BOOT_DIR][2]);
    for (i = 0; i < 5; i++)
        DelayThread(1000 * 1000);
}

static int add(int len, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static int add(int len, const char *fmt, ...)
{
    va_list ap;
    int n;

    if (len >= MENUWATCH_REPORT_SIZE - 1)
        return len;
    va_start(ap, fmt);
    n = vsnprintf(report + len, MENUWATCH_REPORT_SIZE - len, fmt, ap);
    va_end(ap);
    if (n < 0)
        return len;
    len += n;
    return len < MENUWATCH_REPORT_SIZE - 1 ? len : MENUWATCH_REPORT_SIZE - 1;
}

// The last PCs the VBlank interrupt found the EE at, oldest first: where a spinning thread spins.
static int addEpcSamples(int len)
{
    u32 ticks = epcTicks;
    int i, n = ticks < EPC_SAMPLES ? (int)ticks : EPC_SAMPLES;

    if (n == 0)
        return add(len, "PC at the last VBlanks: none sampled\r\n");
    len = add(len, "PC at the last %d VBlanks (oldest first, code is %08x-%08x):", n, (unsigned)(uintptr_t)_ftext, (unsigned)(uintptr_t)_etext);
    for (i = n; i > 0; i--)
        len = add(len, " %08x", (unsigned)epcRing[(ticks - i) % EPC_SAMPLES]);
    return add(len, "\r\n");
}

static int buildReport(int stalledFor, int frameAge, int frame)
{
    char frameNote[64];
    ee_thread_status_t status;
    ee_sema_t sema;
    u32 notReady = 0, empty = 0;
    int len = 0, id, logLen, wrapped = 0;

    // Frame 0 means the boot never drew anything: say so rather than give a frame age.
    if (frame == 0)
        snprintf(frameNote, sizeof(frameNote), "no frame drawn yet");
    else
        snprintf(frameNote, sizeof(frameNote), "last frame drawn %d s ago (frame %d)", frameAge, frame);
    padGetFaultCounters(&notReady, &empty);
    len = add(len,
              "RiptOPL %s menu freeze report\r\n"
              "%d s after boot, stuck for %d s, %s\r\n"
              "GUI thread %d last entered: %s\r\n"
              "longest run of missed pad reads: %u polls; of empty reads: %u polls\r\n\r\n",
              OPL_VERSION, (int)(clock() / CLOCKS_PER_SEC), stalledFor, frameNote,
              guiThreadId, stepName(watchStep), (unsigned)notReady, (unsigned)empty);

    len = addEpcSamples(len);
    len = add(len, "\r\nEE threads (id, state, priority, entry, wait type/id, wakeups):\r\n");
    for (id = 1; id < 256; id++) {
        if (ReferThreadStatus(id, &status) < 0)
            continue;
        len = add(len, "%3d %-12s prio %3d entry %08x wait %u/%u wakeups %u%s\r\n", id, threadState(status.status),
                  status.current_priority, (unsigned)(uintptr_t)status.func, (unsigned)status.waitType, (unsigned)status.waitId,
                  (unsigned)status.wakeupCount, id == guiThreadId ? "  <- GUI" : (id == GetThreadId() ? "  <- watchdog" : ""));
        if (status.waitType == TSW_SEMA && ReferSemaStatus(status.waitId, &sema) >= 0)
            len = add(len, "      sema %u: count %d/%d, %d waiting\r\n", (unsigned)status.waitId, sema.count, sema.max_count, sema.wait_threads);
    }

    logLen = diagCopy(logCopy, sizeof(logCopy) - 1, &wrapped);
    logCopy[logLen] = '\0';
    len = add(len, "\r\nLog%s:\r\n%s", wrapped ? " (oldest lines rolled out)" : "", logCopy);
    return len;
}

static int writeReport(const char *path, int len)
{
    int fd, ok;

    if ((fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666)) < 0)
        return 0;
    ok = write(fd, report, len) == len;
    if (close(fd) < 0) // the card commits on close, so a failed close is a failed write
        ok = 0;
    return ok;
}

static void watchThread(void *arg)
{
    // Count frames at rmEndFrame, not guiFrameId: dialogs (About, Settings pages, message boxes) run
    // their own rmStartFrame/rmEndFrame loop and never advance guiFrameId, so a dialog left open
    // read as a frozen menu.
    unsigned int lastFrame = rmFramesDrawn;
    int lastStep = watchStep, stalledPolls = 0, framePolls = 0, stallLimit, countFrames, len;

    (void)arg;
    for (;;) {
        DelayThread(MENUWATCH_POLL_US);
        // The menu limit counts from the first menu step, not from the last boot splash frame, and
        // each boot stage gets its own limit: a boot that moves on is not stuck.
        if (watchStep != lastStep) {
            if (isBootStep(lastStep))
                stalledPolls = 0;
            lastStep = watchStep;
        }
        // The boot splash keeps drawing while it waits for the deferred device start-up, so until
        // that finishes its frames prove nothing: the stage counts from its start, with a longer
        // limit. After it, the splash is only playing the boot sound or holding for the theme,
        // which can take as long as a theme likes, so frames count again.
        countFrames = watchStep != MENUWATCH_BOOT_INTRO || guiInitComplete();
        if (rmFramesDrawn != lastFrame) {
            lastFrame = rmFramesDrawn;
            framePolls = 0;
            if (countFrames) {
                stalledPolls = 0;
                continue;
            }
        } else
            framePolls++;
        if (watchStep == MENUWATCH_BOOT_INTRO)
            stallLimit = MENUWATCH_INTRO_S;
        else
            stallLimit = isBootStep(watchStep) ? MENUWATCH_BOOT_S : MENUWATCH_STALL_S;
        if (++stalledPolls < stallLimit * (1000000 / MENUWATCH_POLL_US))
            continue;
        if (crashCount)
            SleepThread(); // the crash report covers it: the crashed thread drew no frame since

        // A boot stage first shows its own colour for 5 s: that needs nothing but the GS.
        bootColour(lastStep);
        // Magenta: the watchdog fired. Everything after this needs the IOP.
        screen(0xFF, 0x00, 0xFF);
        len = buildReport(stallLimit, framePolls / (1000000 / MENUWATCH_POLL_US), lastFrame);
        if (writeReport("mc0:/RIPTOPL-FREEZE.TXT", len) || writeReport("mc1:/RIPTOPL-FREEZE.TXT", len))
            screen(0x00, 0xFF, 0x00); // green: the report is on the card
        else
            screen(0xFF, 0x80, 0x00); // orange: the report could not be written
        SleepThread();                // one report per boot
    }
}

static const char *exceptionName(u32 code)
{
    switch (code) {
        case 1:
            return "TLB modified";
        case 2:
            return "TLB miss on a load or fetch (bad pointer)";
        case 3:
            return "TLB miss on a store (bad pointer)";
        case 4:
            return "address error on a load or fetch (unaligned or kernel address)";
        case 5:
            return "address error on a store (unaligned or kernel address)";
        case 6:
            return "bus error on an instruction fetch";
        case 7:
            return "bus error on a data access";
        case 10:
            return "reserved instruction";
        case 11:
            return "coprocessor unusable";
        case 12:
            return "arithmetic overflow";
        case 13:
            return "trap";
        default:
            return "?";
    }
}

// A second exception while reporting: keep the first report's state and stop this thread.
static void crashPark(void)
{
    for (;;)
        SleepThread();
}

// Runs in the thread that raised the exception, on crashStack, after crashException() returned into it.
static void crashReport(void)
{
    const u32 *stack;
    int len, i, n, logLen, wrapped = 0, tid = GetThreadId();
    u32 code = (crashRegs.cause >> 2) & 0x1F;
    ee_thread_status_t status;

    screen(0x80, 0x00, 0x00); // dark red: an exception was caught, the report is being written
    len = add(0,
              "RiptOPL %s menu CRASH report\r\n"
              "%d s after boot, exception %u: %s\r\n"
              "in thread %d%s, GUI thread last entered: %s\r\n\r\n"
              "EPC %08x  BadVAddr %08x  Cause %08x  Status %08x\r\n"
              "at %08x v0 %08x v1 %08x a0 %08x a1 %08x a2 %08x a3 %08x\r\n"
              "t0 %08x t1 %08x t2 %08x t3 %08x t9 %08x\r\n"
              "s0 %08x s1 %08x s2 %08x s3 %08x s4 %08x s5 %08x s6 %08x s7 %08x\r\n"
              "gp %08x sp %08x fp %08x ra %08x\r\n",
              OPL_VERSION, (int)(clock() / CLOCKS_PER_SEC), (unsigned)code, exceptionName(code),
              tid, tid == guiThreadId ? " (GUI)" : "", stepName(watchStep),
              (unsigned)crashRegs.epc, (unsigned)crashRegs.badvaddr, (unsigned)crashRegs.cause, (unsigned)crashRegs.status,
              (unsigned)crashRegs.at, (unsigned)crashRegs.v0, (unsigned)crashRegs.v1, (unsigned)crashRegs.a0,
              (unsigned)crashRegs.a1, (unsigned)crashRegs.a2, (unsigned)crashRegs.a3,
              (unsigned)crashRegs.t0, (unsigned)crashRegs.t1, (unsigned)crashRegs.t2, (unsigned)crashRegs.t3, (unsigned)crashRegs.t9,
              (unsigned)crashRegs.s0, (unsigned)crashRegs.s1, (unsigned)crashRegs.s2, (unsigned)crashRegs.s3,
              (unsigned)crashRegs.s4, (unsigned)crashRegs.s5, (unsigned)crashRegs.s6, (unsigned)crashRegs.s7,
              (unsigned)crashRegs.gp, (unsigned)crashRegs.sp, (unsigned)crashRegs.fp, (unsigned)crashRegs.ra);
    if (ReferThreadStatus(tid, &status) >= 0)
        len = add(len, "thread entry %08x, priority %d\r\n", (unsigned)(uintptr_t)status.func, status.current_priority);

    // Code addresses on the crashed thread's stack: mostly return addresses, a rough backtrace to look
    // up in the build's map file. Only a sane, aligned stack pointer in main RAM is read.
    len = add(len, "\r\nCode addresses on the stack (callers first found first):\r\n");
    if (crashRegs.sp >= 0x00100000 && crashRegs.sp < 0x01FFF000 && (crashRegs.sp & 3) == 0) {
        stack = (const u32 *)(uintptr_t)crashRegs.sp;
        for (i = 0, n = 0; i < 512 && n < 32 && crashRegs.sp + (u32)i * 4 < 0x02000000; i++) {
            if (stack[i] >= (u32)(uintptr_t)_ftext && stack[i] < (u32)(uintptr_t)_etext && (stack[i] & 3) == 0) {
                len = add(len, "%08x%s", (unsigned)stack[i], (++n % 8) == 0 ? "\r\n" : " ");
            }
        }
        if (n % 8)
            len = add(len, "\r\n");
    } else
        len = add(len, "(stack pointer not readable)\r\n");

    len = addEpcSamples(len);
    len = add(len, "\r\nEE threads (id, state, priority, entry, wait type/id, wakeups):\r\n");
    for (i = 1; i < 256; i++) {
        if (ReferThreadStatus(i, &status) < 0)
            continue;
        len = add(len, "%3d %-12s prio %3d entry %08x wait %u/%u wakeups %u%s\r\n", i, threadState(status.status),
                  status.current_priority, (unsigned)(uintptr_t)status.func, (unsigned)status.waitType, (unsigned)status.waitId,
                  (unsigned)status.wakeupCount, i == tid ? "  <- crashed" : (i == guiThreadId ? "  <- GUI" : ""));
    }
    logLen = diagCopy(logCopy, sizeof(logCopy) - 1, &wrapped);
    logCopy[logLen] = '\0';
    len = add(len, "\r\nLog%s:\r\n%s", wrapped ? " (oldest lines rolled out)" : "", logCopy);

    if (writeReport("mc0:/RIPTOPL-CRASH.TXT", len) || writeReport("mc1:/RIPTOPL-CRASH.TXT", len))
        screen(0x00, 0xFF, 0x00); // green: the report is on the card
    else
        screen(0xFF, 0x80, 0x00); // orange: the report could not be written
    crashPark();
}

// libeedebug level 1 handler, in exception context: no kernel calls here.
static int crashException(EE_RegFrame *frame)
{
    if (crashCount++ == 0) {
        crashRegs.cause = frame->cause;
        crashRegs.epc = frame->epc;
        crashRegs.badvaddr = frame->badvaddr;
        crashRegs.status = frame->status;
        crashRegs.at = frame->at[0];
        crashRegs.v0 = frame->v0[0];
        crashRegs.v1 = frame->v1[0];
        crashRegs.a0 = frame->a0[0];
        crashRegs.a1 = frame->a1[0];
        crashRegs.a2 = frame->a2[0];
        crashRegs.a3 = frame->a3[0];
        crashRegs.t0 = frame->t0[0];
        crashRegs.t1 = frame->t1[0];
        crashRegs.t2 = frame->t2[0];
        crashRegs.t3 = frame->t3[0];
        crashRegs.s0 = frame->s0[0];
        crashRegs.s1 = frame->s1[0];
        crashRegs.s2 = frame->s2[0];
        crashRegs.s3 = frame->s3[0];
        crashRegs.s4 = frame->s4[0];
        crashRegs.s5 = frame->s5[0];
        crashRegs.s6 = frame->s6[0];
        crashRegs.s7 = frame->s7[0];
        crashRegs.t9 = frame->t9[0];
        crashRegs.gp = frame->gp[0];
        crashRegs.sp = frame->sp[0];
        crashRegs.fp = frame->fp[0];
        crashRegs.ra = frame->ra[0];
        frame->epc = (u32)&crashReport;
        // Resume on a stack of our own: the crashed thread's may be what broke.
        frame->sp[0] = (u32)(crashStack + CRASH_STACK_SIZE - 64);
    } else {
        frame->epc = (u32)&crashPark; // an exception in the report itself (or a second thread): keep the first
        frame->sp[0] = (u32)(parkStack + sizeof(parkStack) - 64);
    }
    frame->gp[0] = (u32)&_gp;
    frame->ra[0] = 0;
    return 0;
}

// Samples the interrupted PC every VBlank: the freeze and crash reports list the last ones.
static int epcSampler(int cause)
{
    u32 epc;

    (void)cause;
    __asm__ __volatile__("mfc0 %0, $14"
                         : "=r"(epc));
    epcRing[epcTicks % EPC_SAMPLES] = epc;
    epcTicks++;
    ExitHandler();
    return 0;
}

static void crashCatcherStart(void)
{
    // TLB, address and bus errors, reserved instruction, coprocessor unusable, overflow, trap: the
    // exceptions that otherwise park the CPU without a word (YAOPL's set, caught on a console there).
    static const int codes[] = {1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13};
    unsigned int i;

    if (ee_dbg_install(1) < 0) {
        diagLog("crash catcher: libeedebug did not install");
        return;
    }
    for (i = 0; i < sizeof(codes) / sizeof(codes[0]); i++)
        ee_dbg_set_level1_handler(codes[i], &crashException);
    epcHandlerId = AddIntcHandler(INTC_VBLANK_S, &epcSampler, 0);
    if (epcHandlerId >= 0)
        EnableIntc(INTC_VBLANK_S);
    crashCatcherOn = 1;
    diagLog("crash catcher on, VBlank PC sampler %s", epcHandlerId >= 0 ? "on" : "failed");
}

// Called at the end of deinit()/deinitEx(): the next program must not inherit our VBlank handler or
// exception hooks (they point into this ELF's memory). Only the sampler is removed from the VBlank
// interrupt; other handlers on it keep it enabled.
void menuWatchStop(void)
{
    if (epcHandlerId >= 0) {
        RemoveIntcHandler(INTC_VBLANK_S, epcHandlerId);
        epcHandlerId = -1;
    }
    if (crashCatcherOn) {
        ee_dbg_remove(1);
        crashCatcherOn = 0;
    }
}

void menuWatchStep(int step)
{
    if (step >= MENUWATCH_BOOT_DIR && step <= MENUWATCH_BOOT_INTRO) {
        diagLog("boot stage: %s", stepName(step)); // the order and timing of every stage, in the report
        // The text screen lasts until the video setup takes the GS over; after that a stop shows the
        // stage colour instead.
        if (step == MENUWATCH_BOOT_VIDEO) {
            bootTrace("video setup: from here a stop shows a colour");
            bootTraceEnd();
        } else
            bootTrace(stepName(step));
    }
    watchStep = step;
}

void menuWatchStart(void)
{
    ee_thread_t thread;
    int id;

    bootTrace("watchdog started");
    guiThreadId = GetThreadId();
    crashCatcherStart();
    memset(&thread, 0, sizeof(thread));
    thread.func = (void *)&watchThread;
    thread.stack = watchStack;
    thread.stack_size = sizeof(watchStack);
    thread.gp_reg = &_gp;
    thread.initial_priority = 1; // above everything: the GUI is 31, the IO worker 32, BGM 30/31
    if ((id = CreateThread(&thread)) >= 0 && StartThread(id, NULL) < 0) {
        DeleteThread(id);
        id = -1;
    }
    diagLog("menu watchdog %s (thread %d)", id >= 0 ? "on" : "failed", id);
}

#endif
