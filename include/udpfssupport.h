#ifndef __UDPFS_SUPPORT_H
#define __UDPFS_SUPPORT_H

#include "include/iosupport.h"
#include "include/mcemu.h"

// A VMC for udpfs_mcemu on the OPL core (modules/mcemu/mcemu.h McImageSpec with UDPFS_DRIVER): fd is
// the server's handle for the .bin, opened read-write by the menu and kept open across the IOP reset.
typedef struct
{
    int active;       /* Activation flag */
    int fd;           /* Server handle of the VMC file */
    int flags;        /* Card flag */
    vmc_spec_t specs; /* Card specifications */
} udpfs_vmc_infos_t;

// Reuse ETH's refresh cadence: this is a network filesystem, so the same slow-poll delay applies.
#define UDPFS_MODE_UPDATE_DELAY 300

void udpfsInit(item_list_t *itemList); // Init the udpfs: network-filesystem device (loads the UDPFS ioman IRX chain).
void udpfsIopWasReset(void);           // forget the module latches after an in-menu IOP reset
int udpfsGetModulesLoaded(void);       // 1 if the UDPFS ioman NIC stack is loaded (SMB/UDPBD must not load on top).
// GUI thread (menu frame hook): show a notice a background UDPFS scan queued, e.g. an IP conflict.
void udpfsShowPendingNotice(void);
// Explicit-loader helper: synchronously load the UDPFS filesystem stack and wait briefly for the
// server-backed root to answer. Fails closed if SMB/UDPBD already owns the NIC.
int udpfsEnsureReady(u32 timeoutMs);
item_list_t *udpfsGetObject(int initOnly);

#endif
