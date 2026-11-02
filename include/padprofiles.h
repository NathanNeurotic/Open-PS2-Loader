/*
  padprofiles.h the user's .pad USB pad profiles: read for a launch and for the menu's USB pad driver

  Copyright 2026, RIPPS2 contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  From RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2): its ripps2pads.h, under neutral
  names. The module and every call to it are built only with PADEMU.
*/

#ifndef __PADPROFILES_H
#define __PADPROFILES_H

#include "include/padfile.h" // pad_def_t

// Read <settings home>/PADS/*.pad (up to PAD_DEFS_MAX profiles, each one padProfilesLeftOut keeps) and
// PADS/GAMES/<gameId>.pad (gameId may be NULL: no game map), and pack them for this launch. 0 when a block is ready, -1
// when there is none (no PADS folder, no usable profile and no game map). On the launching thread, before the drives are
// let go.
int padProfilesPrepare(const char *gameId);

// This launch's PAD_BLOCK_SIZE block for PADEMU (after its 8 settings bytes), or NULL. The launching thread only.
const unsigned char *padProfilesBlock(void);

// Drops the launch block, reading nothing. sbPrepare calls it first, so a launch that reads no profiles (PADEMU off for
// the game, or the Bluetooth PADEMU) never gets one an earlier launch that did not start left behind. The launching thread.
void padProfilesClear(void);

// Any thread: PADS read again for the menu's USB pad driver (ds34usb.irx). The next readPads on the GUI thread hands it
// over. With no PADS folder and nothing sent before, nothing is sent at all.
void padProfilesMenuLoad(void);

// The GUI thread, from readPads: hands a fresh read to the driver.
void padProfilesMenuTick(void);

// The GUI thread: Set Up A USB Pad open (1: every HID pad taken, none profiled, both ports) or closed (0: the profiles
// again, the menu's one port). 0, or < 0 when the driver did not take it (an open that fails is undone).
int padProfilesMenuLearn(int on);

// After an IOP reset reloaded the driver without them: the menu's profiles are sent again (nothing when none were sent).
void padProfilesMenuResend(void);

// Any thread: 1 when the menu's copy, as the last padProfilesMenuLoad left it, holds a profile for vid:pid (Set Up A USB
// Pad asks after it saves one: the block holds the first PAD_DEFS_MAX the packer meets)
int padProfilesMenuHas(unsigned vid, unsigned pid);

// "<settings home>/PADS" into out. 0, or -1 when the home is empty, holds '?' (no memory card found), is raw APA
// (hdd...: a partition namespace, not a file system) or does not fit.
int padProfilesDir(char *out, int size);

/* Controllers > My Pads lists each PADS/VVVV_PPPP.pad with what a game gets of it, so it asks what the launcher's packer
   asks: the file read the same way, then the reader (padDefParse), then padProfilesLeftOut. */

// The largest .pad the launcher reads, in bytes. A larger one is left out, never read cut short
#define PAD_PROFILE_TEXT_MAX 4095

// A profile's text, NUL ended, into buf (size bytes; PAD_PROFILE_TEXT_MAX + 1 for the launcher's limit). Its length, -1
// when it cannot be opened or read, -2 when it is larger than size - 1 bytes
int padProfilesRead(const char *path, char *buf, int size);

// Why the launcher leaves out a profile the reader accepted, or PAD_PROFILE_USED
enum {
    PAD_PROFILE_USED = 0,
    PAD_PROFILE_NOT_GENERIC, // decoder= is not generic: the Pad Emulator plays generic profiles only
    PAD_PROFILE_BUILT_IN,    // a Sony ID (054C, 12BA) or the ShanWan PS3 pad 2563:0575: neither USB driver profiles it
};
int padProfilesLeftOut(const pad_def_t *def);

#endif
