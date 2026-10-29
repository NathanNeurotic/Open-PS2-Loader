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
    IGR_MENU_CANNOT_DRAW, // no frame to draw on (none seen, or a format the panel cannot write): leave as before
};

// Draws the panel over the paused game and reads the pad until a choice is made. The caller has
// stopped every game thread and held the game's interrupts; buttons() returns libpad's mask (1 = held).
int IGR_MenuRun(u16 (*buttons)(void));

#endif
