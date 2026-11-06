/*
  padprofile.c the menu's .pad profiles (RIPPS2 build 129)

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2).

  The same code PADEMU runs in a game (modules/pademu/padprofile.c, with the reference decoder src/padfile.c): the
  launcher hands the menu the profiles it hands PADEMU (DS34USB_SET_PROFILES), so a profiled pad steers the menu as it
  plays the game.
*/

#include "ds34usb.h" // mips_memcpy, mips_memset (smsutils.S)
#define PADPROFILE_NO_IMPORTS
#include "../../pademu/padprofile.c"
