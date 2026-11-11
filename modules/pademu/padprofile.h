/*
  padprofile.h PADEMU's .pad profiles (RIPPS2 build 129)

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2).
*/

#ifndef PADPROFILE_H
#define PADPROFILE_H

// RIPPS2 build 129: PADEMU's .pad profiles (padprofile.c)
#include <ds34common.h>
#include "include/padfile.h"

#define PADEMU_PROFILES_FLAG (1 << 19) // PadEmuSettings: the .pad block follows the eight bytes of settings

extern pad_def_t padProfiles[PAD_DEFS_MAX];
extern int padProfileCount;

void padProfilesLoad(const unsigned char *block);                                            // NULL: none
int padProfileFind(unsigned vid, unsigned pid);                                              // the profile's index, or -1
void padProfileDecode(int def, const unsigned char *report, int len, struct ds2report *ds2); // a report to the DS2's
void padGameMapApply(struct ds2report *ds2);                                                 // the game's button map

#endif
