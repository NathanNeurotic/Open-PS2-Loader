/*
  Menu freeze report (diagnostic builds only). See include/menuwatch.h.

  Written for a report of the menu freezing a few seconds after boot on a fat console, with every
  device off and RiptOPL booted from the memory card: nothing on the console says where it stopped.
  The watchdog runs above every other EE thread, so it still gets the CPU when the GUI thread spins
  or waits forever. What it cannot survive is the EE with interrupts off (DelayThread never returns).
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
#include <debug.h>

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
              "longest run of missed pad reads: %u polls; of empty reads: %u polls\r\n\r\n"
              "EE threads (id, state, priority, entry, wait type/id, wakeups):\r\n",
              OPL_VERSION, (int)(clock() / CLOCKS_PER_SEC), stalledFor, frameNote,
              guiThreadId, stepName(watchStep), (unsigned)notReady, (unsigned)empty);

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

// 1 until the watchdog starts: after that the screen belongs to the colours and the menu.
static int traceOn = 1;

// Each early boot step, printed on screen as it starts. The first call sets up the debug text screen,
// which needs only the GS, so it works before the IOP is reset. A boot that stops here leaves its
// last step on screen.
void bootTrace(const char *step)
{
    static int count;

    if (!traceOn)
        return;
    if (count == 0) {
        init_scr();
        scr_printf("\n  RiptOPL %s boot trace (diagnostic build)\n", OPL_VERSION);
        scr_printf("  If the screen stops changing, the last line is where it stopped.\n\n");
    }
    scr_printf("  %2d  %s\n", ++count, step);
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

void menuWatchStep(int step)
{
    if (step >= MENUWATCH_BOOT_DIR && step <= MENUWATCH_BOOT_INTRO)
        diagLog("boot stage: %s", stepName(step)); // the order and timing of every stage, in the report
    watchStep = step;
}

void menuWatchStart(void)
{
    ee_thread_t thread;
    int id;

    bootTrace("watchdog starting: from here a stop shows a colour");
    traceOn = 0;
    guiThreadId = GetThreadId();
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
