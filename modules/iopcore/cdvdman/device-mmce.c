
#include <stdint.h>

#include "internal.h"

#include "device.h"
#include "ioplib_util.h"
#include "mmcedrv_config.h"

extern struct cdvdman_settings_mmce cdvdman_settings;

// The driver implements s64 mmcedrv_get_size(int fd) and returns -1 on failure. Declaring the low
// 32 bits only (as this once did with uint32_t) turns that -1 into 0xFFFFFFFF, which passes a "> 0"
// validity check -- an ERROR then reads as a huge valid ISO. Keep the full 64-bit signed return.
int64_t (*fp_mmcedrv_get_size)(int fd);
int (*fp_mmcedrv_read_sector)(int type, unsigned int sector_start, unsigned int sector_count, void *buffer);
void (*fp_mmcedrv_config_set)(int setting, int value);
int (*fp_mmcedrv_read)(int fd, int size, void *ptr);
int (*fp_mmcedrv_write)(int fd, int size, void *ptr);
int (*fp_mmcedrv_lseek)(int fd, int offset, int whence);

static int mmce_io_sema;
// 0 until DeviceFSInit confirmed the device answers for our iso_fd. A failed/timed-out init leaves it
// 0 so reads fail fast with SCECdErREAD instead of silently wedging the IOP right after the PS2 logo.
static int mmce_dev_ready;
// How long a failed read waits for the card to answer again before it is an error: a card swap (card exit,
// flush, close, 500 ms, open) plus most of an 8 MB card load. 100 ms probes.
#define MMCE_SWAP_RECOVERY_PROBES 150
// Set when that recovery budget ran out without the card answering: until it answers a probe again,
// reads fail fast (one probe each) instead of each paying the whole budget.
static int mmce_dev_lost;

void DeviceInit(void)
{
    DPRINTF("%s\n", __func__);

    iop_sema_t sema;
    sema.initial = 1;
    sema.max = 1;
    sema.option = 0;
    sema.attr = SA_THPRI;
    mmce_io_sema = CreateSema(&sema);

    DPRINTF("Sema created: 0x%x\n", mmce_io_sema);
}

void DeviceDeinit(void)
{
    DPRINTF("%s\n", __func__);
}

int DeviceReady(void)
{
    // DPRINTF("%s\n", __func__);
    return SCECdComplete;
}

void DeviceFSInit(void)
{
    int64_t iso_size = 0;

    // get modload export table. getModInfo returns 0 AND leaves info.exports UNINITIALIZED when the
    // module isn't resident (ioplib_util.c:94), so reading info.exports[4..9] after a failed lookup
    // dereferences stack garbage -- a straight IOP crash, indistinguishable from the freezes this file
    // exists to make diagnosable. If mmcedrv somehow isn't loaded, bail with the fail-fast state so
    // reads return SCECdErREAD instead. (A NULL check on the resulting pointers would miss this: the
    // garbage is not necessarily NULL.)
    modinfo_t info;
    if (!getModInfo("mmcedrv\0", &info)) {
        mmce_dev_ready = 0;
        DPRINTF("DeviceFSInit: mmcedrv not resident -- reads will fail fast\n");
        return;
    }

    //Get func ptrs
    fp_mmcedrv_get_size = (void *)info.exports[4];
    fp_mmcedrv_read_sector = (void *)info.exports[5];
    fp_mmcedrv_config_set = (void *)info.exports[6];
    fp_mmcedrv_read = (void *)info.exports[7];
    fp_mmcedrv_write = (void *)info.exports[8];
    fp_mmcedrv_lseek = (void *)info.exports[9];

    //Set port and iso fd
    DPRINTF("Port: %i\n", cdvdman_settings.port);
    DPRINTF("Ack wait cycles: %i\n", cdvdman_settings.ack_wait_cycles);
    DPRINTF("Use alarms: %i\n", cdvdman_settings.use_alarms);

    fp_mmcedrv_config_set(MMCEDRV_SETTING_PORT, cdvdman_settings.port);
    fp_mmcedrv_config_set(MMCEDRV_SETTING_ACK_WAIT_CYCLES, cdvdman_settings.ack_wait_cycles);
    fp_mmcedrv_config_set(MMCEDRV_SETTING_USE_ALARMS, cdvdman_settings.use_alarms);

    DPRINTF("Waiting for device...\n");

    // This runs on the first filesystem access after EVERY IOP reboot -- including the game's own
    // IOPRP reboot right after the PS2 logo. BOUND the wait: a card that loses our iso_fd across the
    // reboot, or a wedged transport, must surface as read errors (diagnosable, often a game error
    // screen) rather than an unbounded silent freeze the user can't tell apart from other hangs.
    for (int tries = 0; tries < 100; tries++) { // 10 s of 100 ms polls; a healthy card answers in ms
        iso_size = fp_mmcedrv_get_size(cdvdman_settings.iso_fd);
        if (iso_size > 0) {
            mmce_dev_ready = 1;
            DPRINTF("Waiting for device...done! connected to %llu byte iso\n", (long long int)iso_size);
            return;
        }
        DelayThread(100 * 1000); // 100ms
    }

    mmce_dev_ready = 0;
    DPRINTF("Waiting for device...TIMED OUT (last get_size %lld) -- reads will fail fast\n", (long long int)iso_size);
}

void DeviceLock(void)
{
    DPRINTF("%s\n", __func__);
    WaitSema(mmce_io_sema);
}

void DeviceUnmount(void)
{
    DPRINTF("%s\n", __func__);
}

void DeviceStop(void)
{
    DPRINTF("%s\n", __func__);
}

int DeviceReadSectors(u64 lsn, void *buffer, unsigned int sectors)
{
    int rv = SCECdErNO;
    int res = 0;
    int retries = 0;

    DPRINTF("%s(%u, 0x%p, %u)\n", __func__, (unsigned int)lsn, buffer, sectors);

    // Hold mmce_io_sema across the WHOLE function. Every mmcedrv call in this file is serialized through
    // it -- the VMC path (mmce_read_offset/write_offset) runs on a different IOP thread and drives the
    // same non-reentrant SIO2 link -- and the late-recovery re-probe below is an mmcedrv call too, so it
    // must be inside the lock (not before it, which raced a concurrent VMC transaction). Taking it here
    // also makes the mmce_dev_ready check-and-set atomic. (DeviceLock, the only other taker, is the
    // shutdown-only barrier in oplShutdown -- never held by a caller of this function, so no deadlock.)
    WaitSema(mmce_io_sema);

    if (!mmce_dev_ready) {
        // Init never saw the device (or a read below lost it). Guard the pointer: DeviceFSInit leaves it
        // NULL when mmcedrv wasn't resident (it bails before resolving the exports), and these are
        // zero-init statics on first boot; nothing can be read then. One cheap re-probe per read: a card
        // that came back late (slow SD re-enumeration across the IOP reboot) recovers here. A card that
        // does not answer still gets the read and the bounded recovery wait below ONCE (it may be mid-swap,
        // see there); after that budget ran out, reads fail fast until a probe answers again.
        if (fp_mmcedrv_get_size == NULL) {
            SignalSema(mmce_io_sema);
            return SCECdErREAD;
        }
        if (fp_mmcedrv_get_size(cdvdman_settings.iso_fd) > 0) {
            mmce_dev_ready = 1;
            mmce_dev_lost = 0;
        } else if (mmce_dev_lost) {
            SignalSema(mmce_io_sema);
            return SCECdErREAD;
        }
    }

    do {
        res = fp_mmcedrv_read_sector(cdvdman_settings.iso_fd, (u32)lsn, sectors, buffer);
        retries++;
    } while (res != sectors && retries < 3);

    // Three fast retries cover a glitch, not a card that is swapping: an MMCE switching to the game's folder
    // (its own Game ID detection reacting to the OSD history write, or a switch deferred past the launch's
    // wait) answers nothing for about a second and then slowly while the new card loads. That used to
    // end here as SCECdErREAD for good, a black screen or a game frozen after the PS2 logo. Wait for the
    // card to answer for our handle again, bounded, then read once more. A genuinely failed read costs one
    // extra probe (the card answers at once, the retry fails again).
    if (res != sectors && fp_mmcedrv_get_size != NULL) {
        int probes;
        for (probes = 0; probes < MMCE_SWAP_RECOVERY_PROBES; probes++) {
            DelayThread(100 * 1000);
            if (fp_mmcedrv_get_size(cdvdman_settings.iso_fd) > 0)
                break;
        }
        if (probes < MMCE_SWAP_RECOVERY_PROBES) {
            DPRINTF("%s: the card answers again after %d ms; retrying\n", __func__, (probes + 1) * 100);
            res = fp_mmcedrv_read_sector(cdvdman_settings.iso_fd, (u32)lsn, sectors, buffer);
            retries++;
        } else {
            // The card never answered: do not pay this wait again on every read (cdvdman issues one per
            // sector for the odd sizes), fail fast until a probe at the top answers again.
            DPRINTF("%s: the card did not answer for %d ms; failing fast until it does\n", __func__, MMCE_SWAP_RECOVERY_PROBES * 100);
            mmce_dev_ready = 0;
            mmce_dev_lost = 1;
        }
    }
    SignalSema(mmce_io_sema);

    // Judge the LAST attempt, not the retry counter: a read that succeeds on the 3rd try also leaves
    // retries == 3, and the old counter check misreported that success as SCECdErREAD.
    if (res != sectors) {
        DPRINTF("%s: Failed to read after %d retries, sector: %u, count: %u, buffer: 0x%p\n", __func__, retries, (unsigned int)lsn, sectors, buffer);
        rv = SCECdErREAD;
    }

    return rv;
}

//TODO: For VMCs
int mmce_read_offset(int fd, unsigned int offset, unsigned int size, unsigned char *buffer)
{
    int ret = 0;
    DPRINTF("%s\n", __func__);

    cdvdman_vmc_io_begin(0);
    WaitSema(mmce_io_sema);
#ifdef INGAMEDIAG
    freeze_diag_vmc_begin(FREEZE_DIAG_VMC_READ, offset / 512);
#endif
    if (fp_mmcedrv_lseek && fp_mmcedrv_read) {
        if (fp_mmcedrv_lseek(fd, offset, 0) >= 0) {
            if (fp_mmcedrv_read(fd, size, buffer) == (int)size)
                ret = 1;
        }
    }
#ifdef INGAMEDIAG
    freeze_diag_vmc_end();
#endif
    SignalSema(mmce_io_sema);
    cdvdman_vmc_io_end();

    return ret;
}

int mmce_write_offset(int fd, unsigned int offset, unsigned int size, const unsigned char *buffer)
{
    int ret = 0;
    DPRINTF("%s\n", __func__);

    cdvdman_vmc_io_begin(1);
    WaitSema(mmce_io_sema);
#ifdef INGAMEDIAG
    freeze_diag_vmc_begin(FREEZE_DIAG_VMC_WRITE, offset / 512);
#endif
    if (fp_mmcedrv_lseek && fp_mmcedrv_write) {
        if (fp_mmcedrv_lseek(fd, offset, 0) >= 0) {
            if (fp_mmcedrv_write(fd, size, (void *)buffer) == (int)size)
                ret = 1;
        }
    }
#ifdef INGAMEDIAG
    freeze_diag_vmc_end();
#endif
    SignalSema(mmce_io_sema);
    cdvdman_vmc_io_end();

    return ret;
}