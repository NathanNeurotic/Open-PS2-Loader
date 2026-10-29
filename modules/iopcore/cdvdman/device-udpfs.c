/*
 * UDPFS Files games on the OPL core. The menu opened the ISO on udpfs_ioman and kept it open across
 * the IOP reset; cdvdman_settings.iso_handle is the server's handle for it (ioctl2 0x80). After the
 * reset the EE core loads udpfs_smap, udpfs_ministack and udpfs_fhi, which reconnects to the server
 * and reads 512-byte sectors of that handle. A disc sector is four of them.
 *
 * A VMC works the same way: the menu opened its .bin read-write, and mcemu reads and writes 512-byte
 * pages of that handle through udpfs_vmc_read and udpfs_vmc_write (the oplutils exports).
 */

#include <stdint.h>

#include "internal.h"

#include "device.h"
#include "ioplib_util.h"

extern struct cdvdman_settings_udpfs cdvdman_settings;

// udpfs_fhi's "udpfsfhi" library: [4] read, [5] connected, [6] write
// (modules/network/udpfs_fhi/src/exports.tab).
static int (*fp_udpfs_fhi_read)(int handle, void *buffer, u32 sector, u32 count);
static int (*fp_udpfs_fhi_connected)(void);
static int (*fp_udpfs_fhi_write)(int handle, const void *buffer, u32 sector, u32 count);

static int udpfs_io_sema;
// 0 until DeviceFSInit saw the session up. A failed or timed-out init leaves it 0 so reads fail fast
// with SCECdErREAD instead of every read waiting out a server that is not there.
static int udpfs_dev_ready;

// How long to wait for the server: at start, and again when a read finds the session down.
#define UDPFS_WAIT_POLLS 300 // 30 s of 100 ms polls; the watchdog in udpfs_fhi re-discovers every ~6 s

void DeviceInit(void)
{
    iop_sema_t sema;

    DPRINTF("%s\n", __func__);

    sema.initial = 1;
    sema.max = 1;
    sema.option = 0;
    sema.attr = SA_THPRI;
    udpfs_io_sema = CreateSema(&sema);

    // A USB host controller the menu's USBD left running would corrupt the modules loaded after this
    // one, as on the udp BDM device (device-bdm.c, YAOPL 15eee615).
    cdvdman_usb_host_stop();
}

void DeviceDeinit(void)
{
    DPRINTF("%s\n", __func__);
}

int DeviceReady(void)
{
    return SCECdComplete;
}

static int udpfs_wait_connected(void)
{
    int tries;

    for (tries = 0; tries < UDPFS_WAIT_POLLS; tries++) {
        if (fp_udpfs_fhi_connected())
            return 1;
        DelayThread(100 * 1000); // 100ms
    }
    return 0;
}

void DeviceFSInit(void)
{
    modinfo_t info;

    DPRINTF("%s\n", __func__);

    // getModInfo leaves info.exports unset when the library is not resident, so check it first. The
    // EE core halts on a red screen when udpfs_fhi does not start (modmgr.c IsRequiredTransport), so
    // this is a backstop.
    if (!getModInfo("udpfsfhi", &info)) {
        udpfs_dev_ready = 0;
        DPRINTF("DeviceFSInit: udpfs_fhi not resident -- reads will fail fast\n");
        return;
    }
    fp_udpfs_fhi_read = (void *)info.exports[4];
    fp_udpfs_fhi_connected = (void *)info.exports[5];
    fp_udpfs_fhi_write = (void *)info.exports[6];

    DPRINTF("Waiting for the UDPFS server (handle %d)...\n", (int)cdvdman_settings.iso_handle);
    udpfs_dev_ready = udpfs_wait_connected();
    DPRINTF("Waiting for the UDPFS server...%s\n", udpfs_dev_ready ? "connected" : "TIMED OUT -- reads will fail fast");
}

void DeviceLock(void)
{
    DPRINTF("%s\n", __func__);
    WaitSema(udpfs_io_sema);
}

void DeviceUnmount(void)
{
    DPRINTF("%s\n", __func__);
}

void DeviceStop(void)
{
    DPRINTF("%s\n", __func__);
}

// Shared by disc reads and VMC pages; only used with udpfs_io_sema held.
static u8 bounce[2048] __attribute__((aligned(64)));

// One attempt at a run of disc sectors, through a bounce buffer when the caller's is not word
// aligned (the ZSO reader can pass one; the network receive path writes words).
static int udpfs_read_once(u32 lsn, void *buffer, unsigned int sectors)
{
    u8 *p = buffer;

    if (((u32)buffer & 3) == 0)
        return fp_udpfs_fhi_read(cdvdman_settings.iso_handle, buffer, lsn * 4, sectors * 4) == (int)(sectors * 4);

    while (sectors > 0) {
        if (fp_udpfs_fhi_read(cdvdman_settings.iso_handle, bounce, lsn * 4, 4) != 4)
            return 0;
        memcpy(p, bounce, 2048);
        p += 2048;
        lsn++;
        sectors--;
    }
    return 1;
}

int DeviceReadSectors(u64 lsn, void *buffer, unsigned int sectors)
{
    int rv = SCECdErNO;
    int attempt;

    DPRINTF("%s(%u, 0x%p, %u)\n", __func__, (unsigned int)lsn, buffer, sectors);

    if (fp_udpfs_fhi_read == NULL)
        return SCECdErREAD;

    WaitSema(udpfs_io_sema);
    if (!udpfs_dev_ready) {
        // Init never saw the server. One cheap check per read: a server started late recovers here.
        if (!fp_udpfs_fhi_connected()) {
            SignalSema(udpfs_io_sema);
            return SCECdErREAD;
        }
        udpfs_dev_ready = 1;
    }

    // A dropped session is re-discovered by udpfs_fhi's watchdog; wait for it once per attempt rather
    // than failing the game's read on the first blip. The server kept our handle, so the read resumes.
    for (attempt = 0; attempt < 3; attempt++) {
        if (udpfs_read_once((u32)lsn, buffer, sectors))
            break;
        // No wait after the last attempt: it would only delay the error.
        if (attempt < 2 && !udpfs_wait_connected())
            attempt = 3;
    }
    if (attempt >= 3) {
        DPRINTF("%s: read failed, sector: %u, count: %u\n", __func__, (unsigned int)lsn, sectors);
        rv = SCECdErREAD;
    }
    SignalSema(udpfs_io_sema);

    return rv;
}

// One attempt at a run of VMC pages (512-byte sectors of the VMC's handle), bounced when the caller's
// buffer is not word aligned.
static int udpfs_vmc_once(int handle, u32 sector, u32 count, u8 *buffer, int is_write)
{
    if (((u32)buffer & 3) == 0) {
        if (is_write)
            return fp_udpfs_fhi_write(handle, buffer, sector, count) == (int)count;
        return fp_udpfs_fhi_read(handle, buffer, sector, count) == (int)count;
    }

    while (count > 0) {
        if (is_write) {
            memcpy(bounce, buffer, 512);
            if (fp_udpfs_fhi_write(handle, bounce, sector, 1) != 1)
                return 0;
        } else {
            if (fp_udpfs_fhi_read(handle, bounce, sector, 1) != 1)
                return 0;
            memcpy(buffer, bounce, 512);
        }
        buffer += 512;
        sector++;
        count--;
    }
    return 1;
}

// 1 when every byte was transferred, 0 otherwise (mcemu then fails the page instead of acknowledging
// a save that never landed). A dropped session gets the same wait-and-retry as a disc read.
static int udpfs_vmc_io(int handle, unsigned int offset, unsigned int size, unsigned char *buffer, int is_write)
{
    int ok = 0;
    int attempt;

    if (handle < 0 || size == 0 || (offset & 511) != 0 || (size & 511) != 0)
        return 0;
    if (fp_udpfs_fhi_read == NULL || fp_udpfs_fhi_write == NULL)
        return 0;

    cdvdman_vmc_io_begin(is_write);
    WaitSema(udpfs_io_sema);
#ifdef INGAMEDIAG
    freeze_diag_vmc_begin(is_write ? FREEZE_DIAG_VMC_WRITE : FREEZE_DIAG_VMC_READ, offset / 512);
#endif
    if (udpfs_dev_ready || fp_udpfs_fhi_connected()) {
        udpfs_dev_ready = 1;
        for (attempt = 0; attempt < 3 && !ok; attempt++) {
            ok = udpfs_vmc_once(handle, offset / 512, size / 512, buffer, is_write);
            if (!ok && (attempt == 2 || !udpfs_wait_connected()))
                break;
        }
    }
#ifdef INGAMEDIAG
    freeze_diag_vmc_end();
#endif
    SignalSema(udpfs_io_sema);
    cdvdman_vmc_io_end();

    if (!ok)
        DPRINTF("%s: VMC %s failed, handle: %d, offset: 0x%x, size: %u\n", __func__, is_write ? "write" : "read", handle, offset, size);
    return ok;
}

int udpfs_vmc_read(int handle, unsigned int offset, unsigned int size, unsigned char *buffer)
{
    return udpfs_vmc_io(handle, offset, size, buffer, 0);
}

int udpfs_vmc_write(int handle, unsigned int offset, unsigned int size, const unsigned char *buffer)
{
    return udpfs_vmc_io(handle, offset, size, (unsigned char *)buffer, 1);
}
