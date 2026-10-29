/*
 * UDPFS FHI for OPL's in-game cdvdman (UDPFS Files games on the OPL core).
 *
 * The menu opens the game's ISO on udpfs_ioman ("udpfs:") and keeps it open across the IOP reset; the
 * server handle it read with ioctl2 0x80 travels to cdvdman in its settings. After the reset this module
 * reconnects to the same server and reads 512-byte sectors of that handle with BREAD. udpfsd keeps a
 * peer's open handles when the peer re-discovers it (Connection.ResetPeer), which is what lets a handle
 * outlive the reset; Neutrino's udpfs_fhi relies on the same behaviour.
 *
 * Adapted from rickgaiser/neutrino iop/udpfs/src/udpfs_fhi.c. Differences: the handle comes from the
 * caller instead of a MODULE_SETTINGS_MAGIC struct (cdvdman already owns the game's settings), the
 * export library is "udpfsfhi" so it never answers for Neutrino's "fhi", and the server is found by a
 * lazy-connect watchdog (the udpfs_bd pattern) so a server that is late, or a session that drops in
 * game, recovers without a module reload.
 */

#include <errno.h>
#include <stdint.h>
#include <thbase.h>
#include <thsemap.h>
#include <loadcore.h>

#include "main.h"
#include "udpfs_core.h"

/* One request at a time: the core owns one socket and one receive destination. The watchdog's
 * discovery takes the same lock, so it can never reset a session under an active read. */
static int g_sema = -1;
static int g_tid = -1;

/* [5] 1 while the session to the server is up. */
int udpfs_fhi_connected(void)
{
    return udpfs_core_is_connected();
}

/* [4] Read count 512-byte sectors of handle from sector. Returns count, or a negative errno. */
int udpfs_fhi_read(int32_t handle, void *buffer, uint32_t sector, uint32_t count)
{
    int ret;

    if (handle < 0)
        return -EBADF;
    if (count == 0)
        return 0;

    WaitSema(g_sema);
    ret = udpfs_core_is_connected() ? udpfs_core_bread(handle, (uint64_t)sector, buffer, count, 512) : -EIO;
    SignalSema(g_sema);

    if (ret < 0)
        M_DEBUG("udpfs_fhi: read handle=%d sector=%u count=%u failed: %d\n", (int)handle, (unsigned int)sector, (unsigned int)count, ret);
    return ret;
}

/* [6] Write count 512-byte sectors of handle from sector (a VMC opened read-write). Returns count, or a
 * negative errno. udpfsd refuses it on a handle opened read-only or on a read-only share. */
int udpfs_fhi_write(int32_t handle, const void *buffer, uint32_t sector, uint32_t count)
{
    int ret;

    if (handle < 0)
        return -EBADF;
    if (count == 0)
        return 0;

    WaitSema(g_sema);
    ret = udpfs_core_is_connected() ? udpfs_core_bwrite(handle, (uint64_t)sector, buffer, count, 512) : -EIO;
    SignalSema(g_sema);

    if (ret < 0)
        M_DEBUG("udpfs_fhi: write handle=%d sector=%u count=%u failed: %d\n", (int)handle, (unsigned int)sector, (unsigned int)count, ret);
    return ret;
}

/* Socket-once: udpfs_core_init binds the UDPRDMA socket on its first call and only re-discovers after
 * that, because the ministack has no udp_unbind. Never exit and re-init the core here. */
static void udpfs_fhi_try_connect(void)
{
    WaitSema(g_sema);
    if (!udpfs_core_is_connected())
        udpfs_core_init(); /* up to ~5 s of discovery when the server does not answer */
    SignalSema(g_sema);
}

static int udpfs_fhi_watchdog(void *arg)
{
    (void)arg;
    while (1) {
        if (!udpfs_core_is_connected())
            udpfs_fhi_try_connect();
        DelayThread(1000 * 1000); // 1s
    }
    return 0;
}

int udpfs_fhi_init(void)
{
    iop_sema_t sema_info;
    iop_thread_t thinfo;

    sema_info.attr = 0;
    sema_info.option = 0;
    sema_info.initial = 1;
    sema_info.max = 1;
    g_sema = CreateSema(&sema_info);
    if (g_sema < 0)
        return -1;

    thinfo.attr = TH_C;
    thinfo.option = 0;
    thinfo.thread = (void *)udpfs_fhi_watchdog;
    thinfo.stacksize = 0x1000;
    thinfo.priority = 0x20;
    g_tid = CreateThread(&thinfo);
    if (g_tid < 0) {
        DeleteSema(g_sema);
        g_sema = -1;
        return -1;
    }
    return 0;
}

/* First connection attempt while the EE core waits on this module's start, then the watchdog. */
void udpfs_fhi_start(void)
{
    M_DEBUG("UDPFS FHI over UDPRDMA (lazy connect)\n");
    udpfs_fhi_try_connect();
    StartThread(g_tid, NULL);
}
