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

#endif
