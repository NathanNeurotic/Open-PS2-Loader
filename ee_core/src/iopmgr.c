/*
  Copyright 2009-2010, Ifcaro, jimmikaelkael & Polo
  Copyright 2006-2008 Polo
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Some parts of the code are taken from HD Project by Polo
*/

#include <iopcontrol.h>

#include "ee_core.h"
#include "iopmgr.h"
#include "modules.h"
#include "modmgr.h"
#include "util.h"
#include "syshook.h"
#include "coreconfig.h"
#include "reset_arg_bounds.h"
#ifdef INGAMEDIAG
#include "freeze_diag_core.h"
#endif
#ifdef RETROACHIEVEMENTS
#include "ra.h"
#include "ra_overlay.h"
#include "../../modules/network/common/ra_snap.h"
#endif

extern int _iop_reboot_count;

#ifdef RETROACHIEVEMENTS
/* Snapshot buffer in IOP RAM. The EE allocates it so it knows the address and
   can DMA straight into it without touching the SIF command table, which the
   game shares -- a command number is an index into a table the game owns, and
   sceSifAddCmdHandler returns void, so overrunning it fails silently.
   Zero means the allocation failed. Read by ra.c. */
unsigned int ra_snap_iop = 0;

/* Is there anything to send? The EE leaves raWatchList NULL when the user has
   telemetry switched off or the game has no watch list (see src/system.c), so
   this one test covers both.

   DEVIATION from upstream, which brings the network up in every mode
   unconditionally. That costs roughly 57 KB of the module storage region and
   puts SMAP on the NIC in every game launched from the RA build, whether or not
   a single achievement is being tracked. Gated, a RA build with nothing to
   watch loads exactly what the default build loads. */
static int RA_TelemetryWanted(struct EECoreConfig_t *config)
{
    return config->raWatchList != NULL && config->raWatchCount > 0 &&
           config->raSnapBuf != NULL && config->raSnapBytes > 0 &&
           config->raNodeCount >= 0 && config->raNodeCount <= RA_NODE_MAX &&
           config->raSnapBytes <= RA_SNAP_MAX_BYTES - config->raNodeCount * RA_NODE_PAIR_BYTES;
}

/* Eight hex digits; there is no sprintf in ee_core. The buffer addresses travel
   to raudp as a load-argument string. */
static void RA_Hex32(unsigned int v, char *out)
{
    int i;

    for (i = 7; i >= 0; i--) {
        out[i] = "0123456789ABCDEF"[v & 0xF];
        v >>= 4;
    }
    out[8] = '\0';
}
#endif

static int imgdrv_offset_ioprpimg = 0;
static int imgdrv_offset_ioprpsiz = 0;

static int ResetIopSpecial(const char *args, unsigned int arglen)
{
    USE_LOCAL_EECORE_CONFIG;
    int i;
    void *pIOP_buffer, *IOPRP_img, *imgdrv_irx;
    unsigned int length_rounded, CommandLen, size_IOPRP_img, size_imgdrv_irx;
    char command[RESET_ARG_MAX + 1];

    if (arglen > 0) {
        if (args == NULL || arglen > sizeof(command) - EE_RESET_SUFFIX_BYTES) {
            DPRINTF("ResetIopSpecial: invalid argument length\n");
            return 0;
        }
        strncpy(command, args, arglen);
        command[arglen] = '\0'; /* In a normal IOP reset process, the IOP reset command line will be NULL-terminated properly somewhere.
                        Since we're now taking things into our own hands, NULL terminate it here.
                        Some games like SOCOM3 will use a command line that isn't NULL terminated, resulting in things like "cdrom0:\RUN\IRX\DNAS300.IMGG;1" */
        _strcpy(&command[arglen + 1], "host0:");
        CommandLen = arglen + 7;
    } else {
        _strcpy(command, "host0:");
        CommandLen = 6;
    }

    GetOPLModInfo(OPL_MODULE_ID_IOPRP, &IOPRP_img, &size_IOPRP_img);
    GetOPLModInfo(OPL_MODULE_ID_IMGDRV, &imgdrv_irx, &size_imgdrv_irx);

    length_rounded = (size_IOPRP_img + 0xF) & ~0xF;
    pIOP_buffer = SifAllocIopHeap(length_rounded);
    if (pIOP_buffer == NULL) {
        DPRINTF("ResetIopSpecial: IOP allocation failed\n");
        return 0; // never DMA an IOPRP image to address zero
    }

    CopyToIop(IOPRP_img, length_rounded, pIOP_buffer);

    if (imgdrv_offset_ioprpimg == 0 || imgdrv_offset_ioprpsiz == 0) {
        for (i = 0; i + 4 <= size_imgdrv_irx; i += 4) {
            if (*(u32 *)((&((unsigned char *)imgdrv_irx)[i])) == 0xDEC1DEC1) {
                imgdrv_offset_ioprpimg = i;
            }
            if (*(u32 *)((&((unsigned char *)imgdrv_irx)[i])) == 0xDEC2DEC2) {
                imgdrv_offset_ioprpsiz = i;
            }
        }
    }

    if (imgdrv_offset_ioprpimg == 0 || imgdrv_offset_ioprpsiz == 0) {
        // A missing magic word would otherwise overwrite the IRX header and load a corrupt imgdrv.
        DPRINTF("ResetIopSpecial: imgdrv patch points not found\n");
        SifFreeIopHeap(pIOP_buffer);
        return 0;
    }

    *(void **)(UNCACHED_SEG(&((unsigned char *)imgdrv_irx)[imgdrv_offset_ioprpimg])) = pIOP_buffer;
    *(u32 *)(UNCACHED_SEG(&((unsigned char *)imgdrv_irx)[imgdrv_offset_ioprpsiz])) = size_IOPRP_img;

    LoadMemModule(0, imgdrv_irx, size_imgdrv_irx, 0, NULL);

    DIntr();
    ee_kmode_enter();
    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_BOOTEND);
    ee_kmode_exit();
    EIntr();

    LoadOPLModule(OPL_MODULE_ID_UDNL, SIF_RPC_M_NOWAIT, CommandLen, command);

    DIntr();
    ee_kmode_enter();
    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_SIFINIT);
    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_CMDINIT);
    Old_SifSetReg(SIF_SYSREG_RPCINIT, 0);
    Old_SifSetReg(SIF_SYSREG_SUBADDR, (int)NULL);
    ee_kmode_exit();
    EIntr();

    LoadFileExit(); // OPL's integrated LOADFILE RPC does not automatically unbind itself after IOP resets.

    _iop_reboot_count++; // increment reboot counter to allow RPC clients to detect unbinding!

    while (!SifIopSync()) {
        ;
    }

    SifInitRpc(0);
    SifInitIopHeap();
    LoadFileInit();
    sbv_patch_enable_lmb();

    DPRINTF("Loading extra IOP modules...\n");

#ifdef RETROACHIEVEMENTS
    // Physical discs use ROM CDVDMAN, so DEV9 and SMSUTILS must load separately.
    if (config->GameMode == DISC_MODE && (RA_TelemetryWanted(config)
#ifdef __LOAD_DEBUG_MODULES
                                          || 1
#endif
                                          )) {
        LoadOPLModule(OPL_MODULE_ID_DEV9, 0, 0, NULL);
        LoadOPLModule(OPL_MODULE_ID_SMSUTILS, 0, 0, NULL);
    }
#endif

#ifdef __LOAD_DEBUG_MODULES
#if !defined(TTY_PPC)
    // The menu never packs these for UDPBD/UDPFS, whose block driver owns the adapter; the loads just fail.
    LoadOPLModule(OPL_MODULE_ID_SMSTCPIP, 0, 0, NULL);
    LoadOPLModule(OPL_MODULE_ID_SMAP, 0, g_ipconfig_len, g_ipconfig);
#endif
#ifdef __DECI2_DEBUG
    LoadOPLModule(OPL_MODULE_ID_DRVTIF, 0, 0, NULL);
    LoadOPLModule(OPL_MODULE_ID_TIFINET, 0, 0, NULL);
#elif defined(TTY_UDP)
    LoadOPLModule(OPL_MODULE_ID_UDPTTY, 0, 0, NULL);
    LoadOPLModule(OPL_MODULE_ID_IOPTRAP, 0, 0, NULL);
#elif defined(TTY_PPC)
    LoadOPLModule(OPL_MODULE_ID_PPCTTY, 0, 0, NULL);
    LoadOPLModule(OPL_MODULE_ID_IOPTRAP, 0, 0, NULL);
#endif
#endif

#ifdef PADEMU
#define PADEMU_ARG || config->EnablePadEmuOp
#else
#define PADEMU_ARG
#endif
    if (config->GameMode == BDM_USB_MODE PADEMU_ARG) {
        LoadOPLModule(OPL_MODULE_ID_USBD, 0, 11, "thpri=2,3");
    }

#if defined(RETROACHIEVEMENTS) && !defined(__LOAD_DEBUG_MODULES)
    /* RetroAchievements telemetry needs the network in every mode, including
       games running from USB: raudp imports SMAPSendPacket from the SMAP
       driver, so without SMAP it fails to link and nothing is sent. ETH mode
       loads both modules in its own branch below; every other mode loads them
       here, and only when there is actually a watch list to stream.

       RA_PROBE (lab, 12.09): a ladder for the hunt after X-Men Origins would
       not finish loading under the fork while it runs on stock OPL. 1 loads
       nothing of ours, 2 the stack only, 3 the stack and SMAP, 4 those and
       raudp but no snapshots from the EE. 0, the default, is the real thing. */
    if (config->GameMode != ETH_MODE && config->GameMode != HTTP_MODE && config->GameMode != BDM_UDP_MODE &&
        config->GameMode != BDM_UFS_MODE && RA_TelemetryWanted(config)) {
        if (RA_PROBE != 1)
            LoadOPLModule(OPL_MODULE_ID_SMSTCPIP, 0, 0, NULL);
        if (RA_PROBE != 1 && RA_PROBE != 2)
            LoadOPLModule(OPL_MODULE_ID_SMAP, 0, g_ipconfig_len, g_ipconfig);
    }
#endif

    // Optional except for MX4SIO; the menu packs it for VMC/PADEMU too, never for MMCE games
    // (src/system.c sendIrxKernelRAM). Unpacked, this load fails harmlessly.
    int sio2manLoaded = LoadOPLModule(OPL_MODULE_ID_SIO2MAN, 0, 0, NULL);

    switch (config->GameMode) {
        case BDM_CF_MODE:
            LoadOPLModule(OPL_MODULE_ID_PCCF, 0, 6, "owned");
            break;
        case BDM_USB_MODE:
            LoadOPLModule(OPL_MODULE_ID_USBMASSBD, 0, 0, NULL);
            break;
        case ETH_MODE:
#ifndef __LOAD_DEBUG_MODULES
            LoadOPLModule(OPL_MODULE_ID_SMSTCPIP, 0, 0, NULL);
            LoadOPLModule(OPL_MODULE_ID_SMAP, 0, g_ipconfig_len, g_ipconfig);
#endif
            LoadOPLModule(OPL_MODULE_ID_SMBINIT, 0, 0, NULL);
            break;
        case HTTP_MODE:
#ifndef __LOAD_DEBUG_MODULES
            LoadOPLModule(OPL_MODULE_ID_SMSTCPIP, 0, 0, NULL);
            LoadOPLModule(OPL_MODULE_ID_SMAP, 0, g_ipconfig_len, g_ipconfig);
#endif
            break;
        case HDD_MODE:
            break;
#ifdef RETROACHIEVEMENTS
        case DISC_MODE:
            break; // ROM CDVDMAN serves the optical drive.
#endif
        case BDM_ILK_MODE:
            // IEEE1394_bd requires iLinkman, exactly as mx4sio_bd requires sio2man below. Do not
            // start it if that dependency failed: an IEEE1394_bd with no manager under it never
            // brings the block device up, and cdvdman then waits on a device that will never
            // arrive -- a hang with nothing on screen to explain it.
            //
            // Every other transport already checks this. The MX4SIO case below checks it, and the
            // menu-side loader in bdmsupport.c checks it FOR iLink (it gates IEEE1394_BD on
            // iLinkManModLoaded). This game-side path was the only one that did not, so a
            // post-reset iLinkman failure was silent here and loud everywhere else.
            if (LoadOPLModule(OPL_MODULE_ID_ILINK, 0, 0, NULL) > 0)
                LoadOPLModule(OPL_MODULE_ID_ILINKBD, 0, 0, NULL);
            break;
        case BDM_M4S_MODE:
            // mx4sio_bd requires PS2SDK's sio2man. Do not start it if that dependency failed.
            if (sio2manLoaded > 0)
                LoadOPLModule(OPL_MODULE_ID_MX4SIOBD, 0, 0, NULL);
            break;
        case BDM_HDD_MODE:
            break;
        case MMCE_MODE:
            LoadOPLModule(OPL_MODULE_ID_MMCEDRV, 0, 0, NULL);
            break;
        case BDM_UDP_MODE:
        case BDM_UFS_MODE: {
            // The chain the menu loaded, reloaded after the reset. dev9 and bdm now come from
            // bdm_udp_cdvdman; the server is found by broadcast, so the driver needs only the PS2's
            // static IP (the menu filled g_ps2_ip with it for these modes). Each module needs the one
            // before it, so stop at the first that does not start: cdvdman then waits for a device
            // that never comes, which is the same visible failure as a server that never answers.
            char ipArg[3 + sizeof(config->g_ps2_ip)];
            _strcpy(ipArg, "ip=");
            _strcpy(&ipArg[3], config->g_ps2_ip);
            if (config->GameMode == BDM_UDP_MODE)
                LoadOPLModule(OPL_MODULE_ID_SMAP_UDPBD, 0, strlen(ipArg) + 1, ipArg);
            else if (LoadOPLModule(OPL_MODULE_ID_UDPFS_SMAP, 0, 0, NULL) > 0 &&
                     LoadOPLModule(OPL_MODULE_ID_UDPFS_MINISTACK, 0, strlen(ipArg) + 1, ipArg) > 0)
                LoadOPLModule(OPL_MODULE_ID_UDPFS_BD, 0, 0, NULL);
            break;
        }
    };

#ifdef RETROACHIEVEMENTS
    /* RetroAchievements telemetry, loaded LAST because it imports
       SMAPSendPacket from the SMAP driver above. The snapshot buffer is
       allocated here, while the IOP heap is up and the game has not started,
       and its address handed to the module as a load argument. Size it to
       this game's direct watches and pointer-chain pairs rather than the
       global worst-case capacity; no extra IOP heap is used for small sets. */
    ra_snap_iop = 0;
    if (RA_TelemetryWanted(config) && RA_PROBE != 1 && RA_PROBE != 2 && RA_PROBE != 3) {
        unsigned int bytes = config->raSnapBytes + config->raNodeCount * RA_NODE_PAIR_BYTES;
        void *snap = SifAllocIopHeap(RA_SNAP_TOTAL_FOR(bytes));

        if (snap != NULL) {
            /* Shared offsets keep the EE/IOP load contract in agreement. */
            char args[RA_ARG_MAX + 1 + IPCONFIG_MAX_LEN];
            int k, n;

            ra_snap_iop = (unsigned int)snap;
            RA_Hex32(ra_snap_iop, &args[RA_ARG_SNAP]);
            args[RA_ARG_EVENT - 1] = ',';
            RA_Hex32((unsigned int)RA_OverlayEventBuffer(), &args[RA_ARG_EVENT]);
            args[RA_ARG_RX - 1] = ',';
            args[RA_ARG_RX] = '0' + ((config->GameMode == ETH_MODE || config->GameMode == HTTP_MODE) ? 0 : 1) +
                              (config->raClientMode == 1 ? 2 : 0) + (config->raHostPinned ? 4 : 0);
            args[RA_ARG_ID - 1] = ',';
            for (n = 0; n < RA_ARG_ID_MAX && config->GameID[n] != '\0'; n++)
                args[RA_ARG_ID + n] = config->GameID[n];
            for (; n < RA_ARG_ID_MAX; n++)
                args[RA_ARG_ID + n] = ' ';
            args[RA_ARG_HOST - 1] = ',';
            for (n = 0; n < 15 && config->raHost[n]; n++)
                args[RA_ARG_HOST + n] = config->raHost[n];
            args[RA_ARG_HOST + n] = '\0';
            n += RA_ARG_HOST + 1;

            for (k = 0; k < g_ipconfig_len && k < IPCONFIG_MAX_LEN; k++)
                args[n + k] = g_ipconfig[k];

            if (LoadOPLModule(OPL_MODULE_ID_RAUDP, 0, n + k, args) < 1) {
                /* Optional telemetry failed. Reclaim its snapshot allocation
                   and leave the game's launch and other IOP modules alone. */
                ra_snap_iop = 0;
                SifFreeIopHeap(snap);
            }
        } else {
            /* No buffer, so nothing can be sent. Leaving ra_snap_iop at zero
               makes ra.c's per-frame path a no-op, and there is no reason to
               start the module just to have it idle. */
            ra_snap_iop = 0;
        }
    }
#endif
    return 1;
}

/*----------------------------------------------------------------*/
/* Reset IOP to include our modules.                              */
/*----------------------------------------------------------------*/
int New_Reset_Iop(const char *arg, int arglen)
{
    USE_LOCAL_EECORE_CONFIG;
    int reset_ok = 0;
#ifdef RETROACHIEVEMENTS
    ra_snap_iop = 0;
#endif
    DPRINTF("New_Reset_Iop start!\n");
    if (EnableDebug)
        DBGCOL(0xFF00FF, IOPMGR, "New_Reset_Iop()");

    SifInitRpc(0);

    iop_reboot_count++;

    // Reseting IOP.
    while (!Reset_Iop("", 0)) {
        ;
    }
    while (!SifIopSync()) {
        ;
    }

    SifInitRpc(0);
    SifInitIopHeap();
    LoadFileInit();
    sbv_patch_enable_lmb();

    if (!ResetIopSpecial(NULL, 0))
        goto reset_finished;
    if (EnableDebug)
        DBGCOL(0x00A5FF, IOPMGR, "ResetIopSpecial (without args) finished!");

    if (arglen > 0) {
        int payloadLen = eeResetPayloadLength(arglen, sizeof(((SifCmdResetData_t *)0)->arg), RESET_ARG_MAX + 1);
        if (arg != NULL && payloadLen >= 0) {
            if (!ResetIopSpecial(&arg[EE_RESET_PREFIX_BYTES], payloadLen))
                goto reset_finished;
            if (EnableDebug)
                DBGCOL(0x00FFFF, IOPMGR, "ResetIopSpecial (with args) finished!");
        } else {
            DPRINTF("New_Reset_Iop: invalid reset packet, using default IOP reset\n");
        }
    }

    if (iop_reboot_count >= 2) {
#ifdef PADEMU
        config->PadEmuSettings |= (LoadOPLModule(OPL_MODULE_ID_MCEMU, 0, 0, NULL) > 0) << 24;
#else
        LoadOPLModule(OPL_MODULE_ID_MCEMU, 0, 0, NULL);
#endif
    }

#ifdef PADEMU
    if (iop_reboot_count >= 2 && config->EnablePadEmuOp) {
        char args_for_pademu[8];
        memcpy(args_for_pademu, &config->PadEmuSettings, 4);
        memcpy(args_for_pademu + 4, &config->PadMacroSettings, 4);
        LoadOPLModule(OPL_MODULE_ID_PADEMU, 0, sizeof(args_for_pademu), args_for_pademu);
    }
#endif

    reset_ok = 1;
reset_finished:
    // Mode 3 unhooks after the second completed OPL reset, not a failed attempt.
    if (!reset_ok)
        iop_reboot_count--;
#ifdef INGAMEDIAG
    if (!reset_ok)
        g_freeze_diag_reset_failures++;
#endif
#ifdef RETROACHIEVEMENTS
    if (!reset_ok)
        ra_snap_iop = 0;
#endif
    DPRINTF("Exiting services...\n");
    SifExitIopHeap();
    LoadFileExit();
    SifExitRpc();

    DPRINTF("New_Reset_Iop complete!\n");
    // we have 4 SifSetReg calls to skip in ELF's SifResetIop, not when we use it ourselves
    if (set_reg_disabled)
        set_reg_hook = reset_ok ? 4 : 0;

    if (EnableDebug)
        BGCOLND(0x000000);

    return reset_ok;
}

/*----------------------------------------------------------------------------------------*/
/* Reset IOP. This function replaces SifIopReset from the PS2SDK                          */
/*----------------------------------------------------------------------------------------*/
int Reset_Iop(const char *arg, int mode)
{
    static SifCmdResetData_t reset_pkt __attribute__((aligned(64)));
    struct t_SifDmaTransfer dmat;
    int arglen;

    /*    SifStopDma();        For the sake of IGR (Which uses this function), don't disable SIF0 (IOP -> EE)
                because some games will be still spamming DMA transfers across SIF0 when IGR is invoked.
                SCE documents that DMA transfers should be stopped before IOP resets, but has neglected
                to explain the effects of not doing so.
                So far, it seems like the SIF (at least SIF0) will stop functioning properly.

                2 commits before this one, OPL appears to have worked around this problem by preventing
                the SIF BOOTEND flag from being set,
                which allowed SifInitCmd() to run ASAP (Even before the IOP finishes rebooting.
                That caused SifSetDChain() to be run ASAP, which re-enables SIF0.
                I don't find that a good workaround because it may result in a timing problem.    */

    for (arglen = 0; arg != NULL && arglen < (int)sizeof(reset_pkt.arg) - 1 && arg[arglen] != '\0'; arglen++)
        reset_pkt.arg[arglen] = arg[arglen];
    if (arg != NULL && arg[arglen] != '\0')
        return 0; // never submit a truncated reset command
    reset_pkt.arg[arglen] = '\0';

    _iop_reboot_count++; // increment reboot counter to allow RPC clients to detect unbinding!

    reset_pkt.header.psize = sizeof reset_pkt; // dsize is not initialized (and not processed, even on the IOP).
    reset_pkt.header.cid = SIF_CMD_RESET_CMD;
    reset_pkt.arglen = arglen;
    reset_pkt.mode = mode;

    dmat.src = &reset_pkt;
    dmat.dest = (void *)SifGetReg(SIF_SYSREG_SUBADDR);
    dmat.size = sizeof(reset_pkt);
    dmat.attr = SIF_DMA_ERT | SIF_DMA_INT_O;
    SifWriteBackDCache(&reset_pkt, sizeof(reset_pkt));

    DIntr();
    ee_kmode_enter();
    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_BOOTEND);

    if (!Old_SifSetDma(&dmat, 1)) {
        ee_kmode_exit();
        EIntr();
        return 0;
    }

    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_SIFINIT);
    Old_SifSetReg(SIF_REG_SMFLAG, SIF_STAT_CMDINIT);
    Old_SifSetReg(SIF_SYSREG_RPCINIT, 0);
    Old_SifSetReg(SIF_SYSREG_SUBADDR, (int)NULL);
    ee_kmode_exit();
    EIntr();

    return 1;
}
