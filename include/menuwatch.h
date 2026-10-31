#ifndef __OPL_MENUWATCH_H
#define __OPL_MENUWATCH_H

/*
  Menu freeze report (diagnostic builds only).

  A watchdog thread checks that the menu keeps drawing frames. When no frame has been drawn for
  8 seconds (20 before the menu loop starts), it turns the screen magenta, writes what every EE
  thread is waiting on to mc0:/RIPTOPL-FREEZE.TXT (mc1: if that fails), then turns the screen green,
  or orange when neither card took the file. A screen that stays magenta means the write never
  finished: the IOP or the memory card is not answering.

  menuWatchStep() marks where the GUI thread is inside its frame, so the report can name the step
  it stopped in. Before the menu loop it marks the boot stage instead: a boot that never draws a
  frame first shows that stage's colour for 5 seconds, so a tester can say where it stopped even
  when the card write fails. A black screen that never shows any colour means the watchdog never
  ran (the EE stopped inside reset() or crashed), or the launcher left no picture for the colour to
  show on. Other builds compile all of this away.

  bootTrace() covers the part before the watchdog can run: from the first line of main() through
  the IOP reset, every module load and the boot stages up to the video setup, each step is printed
  on screen as it starts, so a boot that stops there leaves its last step on screen. From the video
  setup on, the stage colours take over.
*/

enum MenuWatchStep {
    MENUWATCH_BOOT = 1,
    MENUWATCH_FRAME_START,
    MENUWATCH_PADS,
    MENUWATCH_SHOW,
    MENUWATCH_OVERLAYS,
    MENUWATCH_NOTIFICATIONS,
    MENUWATCH_DEFERRED,
    MENUWATCH_FRAME_END,
    MENUWATCH_INPUT,
    MENUWATCH_FRAME_HOOK,
    // Boot stages, in order. A boot that stops before its first frame turns the screen this stage's
    // colour for 5 seconds before the magenta/green/orange report colours (menuwatch.c bootColour).
    MENUWATCH_BOOT_DIR,      // red: boot folder, memory card probes, pad driver
    MENUWATCH_BOOT_CONFIG,   // yellow: settings file location, early video-mode read
    MENUWATCH_BOOT_VIDEO,    // blue: video, language, theme, GUI setup
    MENUWATCH_BOOT_DEVICES,  // cyan: IO thread, menu setup
    MENUWATCH_BOOT_PADS,     // white: controller scan and wait
    MENUWATCH_BOOT_SETTINGS, // grey: loading the settings (skipped with START)
    MENUWATCH_BOOT_INTRO,    // purple: intro screen, device start-up
};

#ifdef __OPLDIAG
void menuWatchStart(void);
void menuWatchStep(int step);
void bootTrace(const char *step);
#else
static inline void menuWatchStart(void)
{
}
static inline void menuWatchStep(int step)
{
    (void)step;
}
static inline void bootTrace(const char *step)
{
    (void)step;
}
#endif

#endif
