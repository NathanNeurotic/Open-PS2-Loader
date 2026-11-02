#ifndef __RIPTLITE_H
#define __RIPTLITE_H

// RiptOPLite: a build that carries the drivers of ONE game source (tools/lite_devices.py, Makefile RIPTOPLITE=<device>).
//
// The build passes RIPTOPLITE plus exactly one RIPTOPLITE_<DEVICE>. Every other source's IRX is
// left out of the ELF (tools/lite_devices.py lists what each device keeps); its symbols resolve to
// empty stubs that sysLoadModuleBuffer refuses, so a stray load fails instead of starting garbage.
// What keeps those paths unreachable is this header: the LITE_HAS_* gates below compile the
// loaders of an absent source out, and liteApplyDeviceMask() (src/riptlite.c) holds every
// absent source's settings off whatever the shared config file says.
//
// A full build defines none of this and every LITE_HAS_* is 1, so nothing changes there.
//
// MMCE's modules and the menu's network stack (netman, SMAP, ps2ip, the NBD server) stay in every
// lite build: Game ID, the MMCE IGR boot-card switch and the network tools need them. Only
// RIPTOPLITE_MMCE adds the MMCE games page; only SMB/UDPBD/UDPFS add a network games source.

#ifdef RIPTOPLITE

#ifdef RIPTOPLITE_USB
#define LITE_HAS_USB     1
#define LITE_DEVICE_NAME "USB"
#else
#define LITE_HAS_USB 0
#endif
#ifdef RIPTOPLITE_MX4SIO
#define LITE_HAS_MX4SIO  1
#define LITE_DEVICE_NAME "MX4SIO"
#else
#define LITE_HAS_MX4SIO 0
#endif
#ifdef RIPTOPLITE_ILINK
#define LITE_HAS_ILINK   1
#define LITE_DEVICE_NAME "iLink"
#else
#define LITE_HAS_ILINK 0
#endif
// HDD: the internal drive in either format, APA/PFS (HDD page) and exFAT (BDM), plus DESR DVR ISOs.
#ifdef RIPTOPLITE_HDD
#define LITE_HAS_APA     1
#define LITE_HAS_BDMHDD  1
#define LITE_HAS_DVR     1
#define LITE_DEVICE_NAME "HDD"
#else
#define LITE_HAS_APA    0
#define LITE_HAS_BDMHDD 0
#define LITE_HAS_DVR    0
#endif
#ifdef RIPTOPLITE_SMB
#define LITE_HAS_SMB     1
#define LITE_DEVICE_NAME "SMB"
#else
#define LITE_HAS_SMB 0
#endif
#ifdef RIPTOPLITE_UDPBD
#define LITE_HAS_UDPBD   1
#define LITE_DEVICE_NAME "UDPBD"
#else
#define LITE_HAS_UDPBD 0
#endif
// UDPFS: both of its accesses, Files (the UDPFS page) and IMG (a BDM block device).
#ifdef RIPTOPLITE_UDPFS
#define LITE_HAS_UDPFS   1
#define LITE_DEVICE_NAME "UDPFS"
#else
#define LITE_HAS_UDPFS 0
#endif
#ifdef RIPTOPLITE_MMCE
#define LITE_HAS_MMCE_GAMES 1
#define LITE_DEVICE_NAME    "MMCE"
#else
#define LITE_HAS_MMCE_GAMES 0
#endif

// Exactly one device per build.
#define LITE_DEVICES_A_ (LITE_HAS_USB + LITE_HAS_MX4SIO + LITE_HAS_ILINK + LITE_HAS_APA)
#define LITE_DEVICES_B_ (LITE_HAS_SMB + LITE_HAS_UDPBD + LITE_HAS_UDPFS + LITE_HAS_MMCE_GAMES)
#if LITE_DEVICES_A_ + LITE_DEVICES_B_ != 1
#error "RIPTOPLITE needs exactly one RIPTOPLITE_<DEVICE>"
#endif

// Sources no lite build carries.
#define LITE_HAS_PCCF 0
#define LITE_HAS_HTTP 0
// The menu's network stack and the NBD server stay in every lite build (user decision 2026-11-02:
// the network modules are backbone for other things), so the Network page stays too.
#define LITE_HAS_NBD  1

#else // full build

#define LITE_HAS_USB        1
#define LITE_HAS_MX4SIO     1
#define LITE_HAS_ILINK      1
#define LITE_HAS_APA        1
#define LITE_HAS_BDMHDD     1
#define LITE_HAS_DVR        1
#define LITE_HAS_SMB        1
#define LITE_HAS_UDPBD      1
#define LITE_HAS_UDPFS      1
#define LITE_HAS_MMCE_GAMES 1
#define LITE_HAS_PCCF       1
#define LITE_HAS_HTTP       1
#define LITE_HAS_NBD        1

#endif

// The BDM layer (bdm.irx, the FAT/exFAT driver, its cdvdman): every block-device source.
#define LITE_HAS_BDM   (LITE_HAS_USB || LITE_HAS_MX4SIO || LITE_HAS_ILINK || LITE_HAS_BDMHDD || LITE_HAS_UDPBD || LITE_HAS_UDPFS || LITE_HAS_PCCF)
// The menu's TCP/IP stack (netman, SMAP, ps2ip): SMB, HTTP and the NBD server. UDPBD and UDPFS bring their own.
#define LITE_HAS_TCPIP (LITE_HAS_SMB || LITE_HAS_HTTP || LITE_HAS_NBD)
// The menu's SMB filesystem (smbman/smb2man): the SMB games source, and in RetroAchievements builds the
// share the achievements page reads ART/CADUCEUS.KEY and badges from whatever the game device
// (tools/lite_devices.py RA_ALWAYS keeps the drivers).
#if LITE_HAS_SMB || defined(RETROACHIEVEMENTS)
#define LITE_HAS_SMB_SHARE 1
#else
#define LITE_HAS_SMB_SHARE 0
#endif
// A network games source: the protocol-specific rows of the Network page.
#define LITE_HAS_NET_SOURCE (LITE_HAS_SMB || LITE_HAS_UDPBD || LITE_HAS_UDPFS || LITE_HAS_HTTP)

#include <tamtypes.h>       // u32, for config.h
#include "include/config.h" // config_set_t

// Holds every source this build does not carry off, and the one it does carry on. Run after the
// config file is read and after every settings change. A no-op in a full build.
void liteApplyDeviceMask(void);
// The shared config file belongs to the full build too: a lite build must not overwrite which
// sources it uses. Take the file's values when it is read; put them back before it is written.
void liteRememberDeviceKeys(config_set_t *configOPL);
void liteRestoreDeviceKeys(config_set_t *configOPL);

#endif
