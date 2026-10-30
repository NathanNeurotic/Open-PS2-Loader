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
  it stopped in. Other builds compile all of this away.
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
};

#ifdef __OPLDIAG
void menuWatchStart(void);
void menuWatchStep(int step);
#else
static inline void menuWatchStart(void)
{
}
static inline void menuWatchStep(int step)
{
    (void)step;
}
#endif

#endif
