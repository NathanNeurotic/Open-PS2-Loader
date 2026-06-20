/*
  Copyright 2024, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  VCD (PS1-via-POPSTARTER) support. Scans a device's POPS/ folder for *.VCD images and resolves
  the per-device POPSTARTER.ELF + the boot selector. RiptOPL surfaces these as a per-device
  "VCD view" (no separate page; no "PS1"/"POPS" wording in our UI). POPSTARTER.ELF is the only
  externally-named tool. Launch + the BDMA-module equip live elsewhere (system.c / opl.c).
*/

#ifndef __VCDSUPPORT_H
#define __VCDSUPPORT_H

#include "include/iosupport.h"
#include "include/supportbase.h" // base_game_info_t (for vcdFillGameList)

#define VCD_NAME_MAX  256  // VCD basename without ".VCD" (incl NUL); becomes the selector game name
#define VCD_ID_MAX    16   // extracted PS1 disc ID, e.g. "SCUS_123.45"
#define VCD_MAX_ITEMS 2048 // hard cap on VCDs scanned from one folder

// POPStarter access-type prefix, prepended to the selector .ELF token per device class.
#define VCD_PREFIX_MASS "XX." // USB / MX4SIO / iLink (local block devices)
#define VCD_PREFIX_SMB  "SB." // SMB / ETH (network)
#define VCD_PREFIX_HDD  ""    // HDD / pfs (deferred)

typedef struct
{
    char name[VCD_NAME_MAX]; // VCD basename WITHOUT ".VCD" (the POPSTARTER selector game name)
    char gameId[VCD_ID_MAX]; // PS1 disc ID when name matches SXXX_NNN.NN.Title, else "" (art/cfg key)
} vcd_entry_t;

// Scan "<devPrefix>POPS/" for *.VCD (case-insensitive). Returns the count; *outList is a malloc'd
// vcd_entry_t array the caller frees (NULL/0 on none/error). POSIX dir IO only (newlib-port rule).
int vcdScanDir(const char *devPrefix, vcd_entry_t **outList);

// Build "<devPrefix>POPS/POPSTARTER.ELF" into out; returns 1 if that file exists, else 0.
int vcdResolvePopstarter(const char *devPrefix, char *out, int outSize);

// Build the POPSTARTER argv[0] selector "<devPrefix>POPS/<prefix><name>.ELF" into out.
void vcdBuildSelector(const char *devPrefix, const char *prefix, const char *name, char *out, int outSize);

// ---- per-device VCD view (L3 toggle) ----------------------------------------------
// Does this device class get a VCD view? (BDM range for now; MMCE/ETH added in a later stage.)
int vcdModeSupported(int mode);
// Is the given device mode currently showing its VCD list (vs its disc list)?
int vcdViewActive(int mode);
// Flip the VCD view for a mode + mark it dirty so the owning support's NeedsUpdate forces a rescan.
void vcdToggleView(int mode);
// Returns 1 exactly once after a toggle (and clears the flag) -- call from the support's NeedsUpdate.
int vcdConsumeDirty(int mode);

// Fill a base_game_info_t list (memalign'd like sbReadList; frees *outGames first) from
// <devPrefix>POPS/*.VCD. Returns the count. name = VCD basename, startup = PS1 id (or "" = no art).
int vcdFillGameList(const char *devPrefix, base_game_info_t **outGames);

// ---- safe memory-card copy (free-space gated) -------------------------------------
// Used by the BDMA/SMB module equip + the POPSTARTER config writers so a full or interrupted
// write can never wreck the card. Every write onto mc?:/POPSTARTER/ must go through these.

// Room for `needBytes` (+ safety margin) on `path`'s card? 1 = yes, 0 = no, -1 = not an MC / can't tell.
int vcdMcHasSpace(const char *path, int needBytes);
// Copy srcPath -> dstPath: 0 ok, -1 src missing, -2 MC too full (nothing written), -3 IO error (partial removed).
int vcdSafeCopyFile(const char *srcPath, const char *dstPath);
// Write a buffer to dstPath under the same gate: 0 ok, -2 MC too full, -3 IO error (partial removed).
int vcdSafeWriteFile(const char *dstPath, const void *buf, int len);

#endif
