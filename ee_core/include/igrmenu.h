/*
  igrmenu.h the in-game menu (RIPPS2's, by akilluminati47); see src/igrmenu.c.
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#ifndef IGRMENU_H
#define IGRMENU_H

#include <tamtypes.h>

enum {
    IGR_MENU_RESUME = 0,  // back to the game
    IGR_MENU_EXIT,        // EXIT GAME, or the power button twice: the IGR path, as the combo always did
    IGR_MENU_POWEROFF,    // POWER OFF, or the power button once
    IGR_MENU_CANNOT_DRAW, // the menu is not there to run (RA editions: no overlay for this launch): leave as before
    // The menu ran but could not draw: the combo leaves as before. Distinct so Debug Colors can say which
    // (padhook.c IGR_Thread, docs/IGR.md). Keep them after IGR_MENU_CANNOT_DRAW: >= is the test.
    IGR_MENU_NO_FRAME,    // no DISPFB write recorded by the GS tracker, or a format / size the panel cannot use
    IGR_MENU_GS_BUSY,     // the game's VIF1 / GIF transfers did not finish, or VIF1 is stalled, within the wait
    IGR_MENU_DRAW_FAILED, // the first page did not go through (VIF1 did not take the lines)
};

// Draws the panel over the paused game and reads the pad until a choice is made. The caller has
// stopped every game thread and held the game's interrupts; buttons() returns libpad's mask (1 = held).
int IGR_MenuRun(u16 (*buttons)(void));

#endif
