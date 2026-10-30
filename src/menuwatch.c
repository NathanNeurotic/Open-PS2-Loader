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

#include "include/opl.h"
#include "include/gui.h"
#include "include/pad.h"
#include "include/diaglog.h"
#include "include/menuwatch.h"

#define MENUWATCH_POLL_US     (250 * 1000)
#define MENUWATCH_STALL_S     8  // in the menu
#define MENUWATCH_BOOT_S      20 // while booting, where a device wait can be long
#define MENUWATCH_STACK_SIZE  (16 * 1024)
#define MENUWATCH_REPORT_SIZE (24 * 1024)
#define MENUWATCH_LOG_SIZE    (12 * 1024)

// GS privileged registers: with both read circuits off the screen shows the background colour, so
// the colour is visible whatever the last frame was.
#define GS_PMODE   ((volatile u64 *)0x12000000)
#define GS_BGCOLOR ((volatile u64 *)0x120000E0)

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
                                        "frame end (render flush, vsync)", "input dispatch", "frame hook"};

    return (step > 0 && step < (int)(sizeof(names) / sizeof(names[0]))) ? names[step] : names[0];
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
    *GS_PMODE = 0;
    *GS_BGCOLOR = (u64)r | ((u64)g << 8) | ((u64)b << 16);
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

static int buildReport(int stalledFor, int frame)
{
    ee_thread_status_t status;
    ee_sema_t sema;
    u32 notReady = 0, empty = 0;
    int len = 0, id, logLen, wrapped = 0;

    padGetFaultCounters(&notReady, &empty);
    len = add(len,
              "RiptOPL %s menu freeze report\r\n"
              "%d s after boot, no frame drawn for %d s (frame %d)\r\n"
              "GUI thread %d last entered: %s\r\n"
              "longest run of missed pad reads: %u polls; of empty reads: %u polls\r\n\r\n"
              "EE threads (id, state, priority, entry, wait type/id, wakeups):\r\n",
              OPL_VERSION, (int)(clock() / CLOCKS_PER_SEC), stalledFor, frame,
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

static void watchThread(void *arg)
{
    int lastFrame = guiFrameId, lastStep = watchStep, stalledPolls = 0, stallLimit, len;

    (void)arg;
    for (;;) {
        DelayThread(MENUWATCH_POLL_US);
        // The menu limit counts from the first menu step, not from the last boot splash frame.
        if (watchStep != lastStep) {
            if (lastStep == MENUWATCH_BOOT)
                stalledPolls = 0;
            lastStep = watchStep;
        }
        if (guiFrameId != lastFrame) {
            lastFrame = guiFrameId;
            stalledPolls = 0;
            continue;
        }
        stallLimit = watchStep == MENUWATCH_BOOT ? MENUWATCH_BOOT_S : MENUWATCH_STALL_S;
        if (++stalledPolls < stallLimit * (1000000 / MENUWATCH_POLL_US))
            continue;

        // Magenta: the watchdog fired. Everything after this needs the IOP.
        screen(0xFF, 0x00, 0xFF);
        len = buildReport(stallLimit, lastFrame);
        if (writeReport("mc0:/RIPTOPL-FREEZE.TXT", len) || writeReport("mc1:/RIPTOPL-FREEZE.TXT", len))
            screen(0x00, 0xFF, 0x00); // green: the report is on the card
        else
            screen(0xFF, 0x80, 0x00); // orange: the report could not be written
        SleepThread();                // one report per boot
    }
}

void menuWatchStep(int step)
{
    watchStep = step;
}

void menuWatchStart(void)
{
    ee_thread_t thread;
    int id;

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
