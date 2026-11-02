/*
  padprofile.c PADEMU's .pad profiles (RIPPS2 build 129)

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2).

  The launcher reads the user's PADS/VVVV_PPPP.pad files and the game's PADS/GAMES/<game ID>.pad, checks them and packs
  them into one block of PAD_BLOCK_SIZE bytes (RIPPS2's pad-spec.md, format 1; docs/PAD-PROFILES.md here), which follows
  PADEMU's eight bytes of settings in its arguments (pademu.c). Here the block is read once at start, and the reference
  decoder (src/padfile.c, built decode-only) turns a profiled pad's reports into the DualShock 2's. No text and no file is
  touched in the game. Of the two PADEMU builds only the USB one links this (Makefile): the Bluetooth driver has no use
  for it. The menu's USB driver builds the same file (modules/ds34usb/iop/padprofile.c).
*/

#ifndef PADPROFILE_NO_IMPORTS // the menu driver (modules/ds34usb) has its own headers
#include "irx_imports.h"
#endif
#include "padprofile.h"

// sysclib.h maps them to the compiler's builtins; padfile.c gets the IOP's own copies (smsutils) instead
#undef memcpy
#undef memset
#define memcpy(d, s, n) mips_memcpy((d), (s), (n))
#define memset(d, c, n) mips_memset((d), (c), (n))
#define PADFILE_DECODE_ONLY
#include "../../src/padfile.c"

pad_def_t padProfiles[PAD_DEFS_MAX];
int padProfileCount = 0;
unsigned char padGameMap[PAD_B_COUNT];
int padGameMapOn = 0;

void padProfilesLoad(const unsigned char *block)
{
    padProfileCount = 0;
    padGameMapOn = 0;
    if (block == NULL || padBlockUnpack(block, PAD_BLOCK_SIZE, padProfiles, &padProfileCount, padGameMap) != 0) {
        padProfileCount = 0;
        return;
    }
    padGameMapOn = !padMapIsSame(padGameMap);
}

int padProfileFind(unsigned vid, unsigned pid)
{
    int i;
    for (i = 0; i < padProfileCount; i++)
        if (padProfiles[i].vid == vid && padProfiles[i].pid == pid)
            return i;
    return -1;
}

void padProfileDecode(int def, const unsigned char *report, int len, struct ds2report *ds2)
{
    unsigned short buttons;
    unsigned char axes[4];
    unsigned pressed;

    if (def < 0 || def >= padProfileCount)
        return;
    padTranslate(&padProfiles[def], report, len, &buttons, axes);
    ds2->nButtonState = buttons;
    ds2->LeftStickX = axes[PAD_AX_LX];
    ds2->LeftStickY = axes[PAD_AX_LY];
    ds2->RightStickX = axes[PAD_AX_RX];
    ds2->RightStickY = axes[PAD_AX_RY];
    pressed = (unsigned short)~buttons; // a generic pad has no pressure: 255 while held, as the DS4's
    ds2->PressureRight = pressed & (1u << PAD_B_RIGHT) ? 0xFF : 0;
    ds2->PressureLeft = pressed & (1u << PAD_B_LEFT) ? 0xFF : 0;
    ds2->PressureUp = pressed & (1u << PAD_B_UP) ? 0xFF : 0;
    ds2->PressureDown = pressed & (1u << PAD_B_DOWN) ? 0xFF : 0;
    ds2->PressureTriangle = pressed & (1u << PAD_B_TRIANGLE) ? 0xFF : 0;
    ds2->PressureCircle = pressed & (1u << PAD_B_CIRCLE) ? 0xFF : 0;
    ds2->PressureCross = pressed & (1u << PAD_B_CROSS) ? 0xFF : 0;
    ds2->PressureSquare = pressed & (1u << PAD_B_SQUARE) ? 0xFF : 0;
    ds2->PressureL1 = pressed & (1u << PAD_B_L1) ? 0xFF : 0;
    ds2->PressureR1 = pressed & (1u << PAD_B_R1) ? 0xFF : 0;
    ds2->PressureL2 = pressed & (1u << PAD_B_L2) ? 0xFF : 0;
    ds2->PressureR2 = pressed & (1u << PAD_B_R2) ? 0xFF : 0;
}

void padGameMapApply(struct ds2report *ds2)
{
    if (padGameMapOn)
        ds2->nButtonState = padApplyMap(ds2->nButtonState, padGameMap);
}
