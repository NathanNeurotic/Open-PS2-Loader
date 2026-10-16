/* PCMCIA CF block device for OPL menu and game core.
   No SPEED, DEV9 interrupt handler or DMA. PS2SDK BDM ABI 1.1. */
#include <irx.h>
#include <loadcore.h>
#include <bdm.h>
#include <thbase.h>
#include <thsemap.h>
#include <sysclib.h>
#include <errno.h>
#include "pccf_ata.h"
#include "pcclog.h"
#include "pccf_mbr.h"

IRX_ID("pccf_bd", 1, 1);
static pccf_ata_t ata;
static int io_lock = -1;
static struct block_device device;
/* Preserve the ATA trace callback ABI without collecting or formatting logs. */
void pccardTrace(const char *format, ...) { (void)format; }

static int cf_read(struct block_device *bd, u64 sector, void *buffer, u16 count)
{
    unsigned int remaining = count, take;
    unsigned char *out = buffer;
    int rc = count;
    (void)bd;
    if (!buffer || !count || sector >= ata.sectors || count > ata.sectors - sector)
        return -EINVAL;
    WaitSema(io_lock);
    if (!ata.ready || !pccf_hw_present()) {
        ata.ready = 0;
        rc = -EIO;
        goto done;
    }
    while (remaining) {
        take = remaining > 64 ? 64 : remaining;
        if (pccf_ata_read(&ata, (unsigned int)sector, take, out)) {
            rc = -EIO;
            break;
        }
        sector += take;
        out += take * 512;
        remaining -= take;
    }
done:
    SignalSema(io_lock);
    return rc;
}
static int cf_write(struct block_device *bd, u64 sector, const void *buffer, u16 count)
{
#ifdef GAME_DRIVER
    (void)bd;
    (void)sector;
    (void)buffer;
    (void)count;
    return -EROFS;
#else
    unsigned int remaining = count, take;
    const unsigned char *in = buffer;
    int rc = count;
    (void)bd;
    if (!buffer || !count || sector >= ata.sectors || count > ata.sectors - sector)
        return -EINVAL;
    WaitSema(io_lock);
    if (!ata.ready || !pccf_hw_present()) {
        ata.ready = 0;
        rc = -EIO;
        goto done;
    }
    while (remaining) {
        take = remaining > 64 ? 64 : remaining;
        if (pccf_ata_write(&ata, (unsigned int)sector, take, in)) {
            rc = -EIO;
            break;
        }
        sector += take;
        in += take * 512;
        remaining -= take;
    }
done:
    SignalSema(io_lock);
    return rc;
#endif
}
/* Each successful GUI write already flushes and verifies before returning. */
static void cf_flush(struct block_device *bd) { (void)bd; }
static int cf_stop(struct block_device *bd)
{
    (void)bd;
    WaitSema(io_lock);
    ata.ready = 0;
    pccf_hw_stop();
    SignalSema(io_lock);
    return 0;
}

static int pccf_owned_handoff(int argc, char **argv)
{
#ifdef GAME_DRIVER
    // LOADFILE inserts the module name at argv[0].
    return argc == 2 && argv && argv[1] && !strcmp(argv[1], "owned");
#else
    (void)argc;
    (void)argv;
    return 0;
#endif
}

int _start(int argc, char **argv)
{
    iop_sema_t sema;
    int rc;
    (void)argc;
    (void)argv;
    memset(&sema, 0, sizeof(sema));
    sema.initial = 1;
    sema.max = 1;
    io_lock = CreateSema(&sema);
    if (io_lock < 0)
        return MODULE_NO_RESIDENT_END;
    /* Only the game loader carries an explicit handoff from our own menu source.
       The integrated GUI never reclaims a powered PC CARD owned by another driver. */
    if (pccf_owned_handoff(argc, argv) &&
        (*(volatile u16 *)0xbf80146e & 0xf0) == 0x20 &&
        *(volatile u16 *)0xbf801474 == 0 && *(volatile u16 *)0xbf80146c != 0) {
        *(volatile u16 *)0xbf80147e = 1;
        *(volatile u16 *)0xbf80146c = 0;
        DelayThread(100000);
    }
    rc = pccf_hw_start(&ata);
    if (rc) {
        DeleteSema(io_lock);
        return MODULE_NO_RESIDENT_END;
    }
    unsigned char mbr[512];
    if (pccf_ata_read(&ata, 0, 1, mbr) || !pccf_mbr_valid(mbr, ata.sectors)) {
        ata.ready = 0;
        pccf_hw_stop();
        DeleteSema(io_lock);
        return MODULE_NO_RESIDENT_END;
    }
    memset(&device, 0, sizeof(device));
    device.name = "cf";
    device.devNr = 0;
    device.parNr = 0;
    device.sectorSize = 512;
    device.sectorCount = ata.sectors;
    device.read = cf_read;
    device.write = cf_write;
    device.flush = cf_flush;
    device.stop = cf_stop;
    bdm_connect_bd(&device);
    return MODULE_RESIDENT_END;
}
