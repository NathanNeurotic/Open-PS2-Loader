/* PC CARD power/reset sequence adapted from PS2SDK DEV9 (Marcus R. Brown,
   2003), Academic Free License 2.0; see PS2SDK_LICENSE.txt.
   CF uses the memory window proven by DIAG4/5 on SCPH-10000. No Sony SPEED
   register, interrupt handler, DMA or DEV9 library is installed here. */
#include <types.h>
#include <string.h>
#include <thbase.h>
#include "pcclog.h"
#include "pccf_ata.h"
#ifndef PCCF_SETTLE_US
#define PCCF_SETTLE_US 1000
#endif
#ifndef PCCF_HW_TEST
#define HW_R16(a)    (*(volatile u16 *)(a))
#define HW_W16(a, v) (*(volatile u16 *)(a) = (v))
#define HW_R32(a)    (*(volatile u32 *)(a))
#define HW_W32(a, v) (*(volatile u32 *)(a) = (v))
#define HW_R8(a)     (*(volatile u8 *)(a))
#define HW_W8(a, v)  (*(volatile u8 *)(a) = (v))
#endif
#define REG(n)  (0xbf800000U + (n))
#define CARD(n) (0xb0000000U + (n))
static const unsigned int save16_addr[] = {0x1460, 0x1468, 0x146a, 0x1474, 0x147a, 0x147c, 0x147e};
static const unsigned int save32_addr[] = {0x1418, 0x141c, 0x1420};
static u16 saved16[7], selector;
static u32 saved32[3];
static int started;
static unsigned int read_command_logs;
static unsigned int pio_data_timing = 0x001a10bbU;
static unsigned int pio_cpu32, pio_settle_us = PCCF_SETTLE_US;
static unsigned int pio_fallback_restart;
#include "pccf_pio_bulk.inc"
static unsigned char card_read8(void *context, unsigned int offset)
{
    (void)context;
    return HW_R8(CARD(offset));
}
static unsigned short card_read16(void *context, unsigned int offset)
{
    (void)context;
    return HW_R16(CARD(offset));
}
static void access_window(void *context, unsigned int space, unsigned int width)
{
    (void)context;
    HW_W32(REG(0x1418), (space == 0 && width == 16) ? pio_data_timing : (0x001a00bbU | (width == 16 ? 0x1000U : 0)));
    HW_W16(REG(0x1460), (selector & ~3U) | space);
}
static void wait_ms(void *context, unsigned int milliseconds)
{
    (void)context;
    DelayThread(milliseconds * 1000);
}
/* Retain bounded CIS/map validation without emitting tuple or register dumps.
   The separate SD-DIAG branches keep detailed hardware diagnostics. */
static void quiet_trace(const char *format, ...)
{
    (void)format;
}
static int read_cf_profile(pcdiag_cis_info_t *info)
{
    unsigned int attempt, elapsed = 0;
    for (attempt = 0; attempt < 3; ++attempt) {
        int rc = pcdiag_cis_dump_info(card_read8, NULL, quiet_trace, info);
        if (!rc && pcdiag_cis_cf_candidate(info)) {
            pccardTrace("pccf: CIS accepted extra_wait_ms=%u fixed-disk memory-index=0 COR=0200", elapsed);
            return 0;
        }
        if (attempt == 2)
            break;
        pccardTrace("pccf: CIS not ready/unsupported rc=%d; retry after %u ms", rc, attempt ? 4000U : 1000U);
        wait_ms(NULL, attempt ? 4000 : 1000);
        elapsed += attempt ? 4000 : 1000;
        if (!pccf_hw_present()) {
            pccardTrace("pccf: CIS stopped: card removed or power lost");
            return -1;
        }
    }
    pccardTrace("pccf: CIS unsupported after extra_wait_ms=5000; no ATA commands attempted");
    return -1;
}
int pccf_hw_present(void)
{
    return started && (HW_R16(REG(0x1462)) & 3) == 0 && (HW_R16(REG(0x146c)) & 1);
}
static int issue_read_count(void *context, unsigned int command, unsigned int lba, unsigned int count)
{
    unsigned int i, observed[5], expected[5], mismatch = 0;
    (void)context;
    if (!((command == 0xec && lba == 0 && count == 1) ||
          (command == 0x20 && count && count <= 64 && lba < PCDIAG_ATA_LBA28_SECTORS &&
           count <= PCDIAG_ATA_LBA28_SECTORS - lba)) ||
        !pccf_hw_present() || (HW_R16(REG(0x1460)) & 3) || (HW_R32(REG(0x1418)) & 0x1000U))
        return -1;
    if (command == 0x20) {
        HW_W8(CARD(6), 0xe0 | ((lba >> 24) & 15));
        for (i = 0; i < 4; ++i)
            (void)HW_R8(CARD(0x0e));
        if (pio_settle_us)
            DelayThread(pio_settle_us); /* Settle device/head selection. */
        HW_W8(CARD(2), count);
        HW_W8(CARD(3), lba & 0xff);
        HW_W8(CARD(4), (lba >> 8) & 0xff);
        HW_W8(CARD(5), (lba >> 16) & 0xff);
        if (pio_settle_us)
            DelayThread(pio_settle_us); /* Settle parameters before command. */
        if (!pccf_hw_present())
            return -1;
        expected[0] = count;
        expected[1] = lba & 0xff;
        expected[2] = (lba >> 8) & 0xff;
        expected[3] = (lba >> 16) & 0xff;
        expected[4] = 0xe0 | ((lba >> 24) & 15);
        for (i = 0; i < 5; ++i) {
            observed[i] = HW_R8(CARD(i + 2));
            if (observed[i] != expected[i])
                mismatch = 1;
        }
        if (read_command_logs++ < 8 || mismatch)
            pccardTrace("pccf: TASKFILE lba=%08lx match=%u SC=%02x SN=%02x CL=%02x CH=%02x DH=%02x",
                        (unsigned long)lba, !mismatch, observed[0], observed[1], observed[2], observed[3], observed[4]);
        if (mismatch) {
            pccardTrace("pccf: TASKFILE mismatch; read command not sent");
            return -1;
        }
    }
    HW_W8(CARD(7), command);
    return 0;
}
/* Extended taskfile high bytes must be sent first. Device/head keeps
   only the LBA bit; LBA[27:24] belongs in the high LBA register instead. */
static int issue_rw(void *context, unsigned int command, unsigned int lba, unsigned int count)
{
    unsigned int i, extended = command == 0x24 || command == 0x34;
    unsigned int writing = command == 0x30 || command == 0x34;
    if (command == 0x20)
        return issue_read_count(context, command, lba, count);
#ifdef GAME_DRIVER
    if (command != 0x24)
        return -1;
#endif
    if (!(extended || writing || command == 0xe7 || command == 0xea) ||
        !pccf_hw_present() || (HW_R16(REG(0x1460)) & 3) ||
        (HW_R32(REG(0x1418)) & 0x1000U))
        return -1;
    if (extended || writing) {
        if (!count || count > 64 || (!extended && (lba >= PCDIAG_ATA_LBA28_SECTORS || count > PCDIAG_ATA_LBA28_SECTORS - lba)))
            return -1;
        HW_W8(CARD(6), extended ? 0xe0 : 0xe0 | ((lba >> 24) & 15));
        for (i = 0; i < 4; i++)
            (void)HW_R8(CARD(0x0e));
        if (writing)
            DelayThread(1000);
        else if (pio_settle_us)
            DelayThread(pio_settle_us);
        if (extended) {
            HW_W8(CARD(2), 0);
            HW_W8(CARD(3), (lba >> 24) & 255);
            HW_W8(CARD(4), 0);
            HW_W8(CARD(5), 0);
        }
        HW_W8(CARD(2), count);
        HW_W8(CARD(3), lba & 255);
        HW_W8(CARD(4), (lba >> 8) & 255);
        HW_W8(CARD(5), (lba >> 16) & 255);
        if (writing)
            DelayThread(1000);
        else if (pio_settle_us)
            DelayThread(pio_settle_us);
    }
    if (!pccf_hw_present())
        return -1;
    HW_W8(CARD(7), command);
    return 0;
}
#ifndef GAME_DRIVER
static void pio_write_sector(const unsigned char *buffer)
{
    unsigned int i;
    HW_W32(REG(0x1418), 0x001a10bbU);
    HW_W16(REG(0x1460), selector & ~3U);
    for (i = 0; i < 512; i += 2)
        HW_W16(CARD(0), (unsigned int)buffer[i] | ((unsigned int)buffer[i + 1] << 8));
}
#endif
static int issue_read(void *context, unsigned int command, unsigned int lba)
{
    return issue_read_count(context, command, lba, 1);
}
static int issue_sectors(void *context, unsigned int lba, unsigned int count)
{
    return issue_read_count(context, 0x20, lba, count);
}
static unsigned int time_us(void)
{
    iop_sys_clock_t now;
    u32 seconds, microseconds;
    GetSystemTime(&now);
    SysClock2USec(&now, &seconds, &microseconds);
    return seconds * 1000000U + microseconds;
}
#include "pccf_pio_profile.inc"
void pccf_hw_stop(void)
{
    unsigned int i;
    if (!started)
        return;
    HW_W16(REG(0x147e), 1);
    HW_W16(REG(0x146c), 0);
    for (i = 0; i < 6; ++i)
        HW_W16(REG(save16_addr[i]), saved16[i]);
    for (i = 0; i < 3; ++i)
        HW_W32(REG(save32_addr[i]), saved32[i]);
    HW_W16(REG(0x147e), saved16[6]);
    started = 0;
    pccardTrace("pccf: PC CARD powered off; saved host settings restored");
}
int pccf_hw_start(pccf_ata_t *ata)
{
    static const pcdiag_cf_ops_t memory = {card_read8, card_read16, access_window, wait_ms};
    static const pcdiag_ata_ops_t ops = {&memory, issue_read};
    pcdiag_cis_info_t info;
    unsigned int i, voltage, status;
    int tune_rc;
    u16 v;
    ata->ready = 0;
    if ((HW_R16(REG(0x146e)) & 0xf0) != 0x20)
        return -1;
    status = HW_R16(REG(0x1462));
    pio_data_timing = 0x001a10bbU;
    pio_cpu32 = 0;
    pio_settle_us = PCCF_SETTLE_US;
    read_command_logs = 0;
    pccardTrace("pccf: START REV=%04x CARDSTAT=%04x POWER=%04x MODE=%04x",
                HW_R16(REG(0x146e)), status, HW_R16(REG(0x146c)), HW_R16(REG(0x1474)));
    /* 0x146e is DEV9 REV. Restrict this first driver to retail PC CARD.
       Never seize an already powered adapter owned by another driver. */
    if ((HW_R16(REG(0x146e)) & 0xf0) != 0x20 || (status & 3) != 0 ||
        (status & 0x0c) == 4 || HW_R16(REG(0x146c)) != 0 || HW_R16(REG(0x1474)) != 0) {
        pccardTrace("pccf: START rejected: no compatible idle 16-bit PC CARD controller/card");
        return -1;
    }
    voltage = (status & 0x0c) == 0x0c ? 2 : 1;
    for (i = 0; i < 7; ++i)
        saved16[i] = HW_R16(REG(save16_addr[i]));
    for (i = 0; i < 3; ++i)
        saved32[i] = HW_R32(REG(save32_addr[i]));
    selector = saved16[0];
    started = 1;
    HW_W32(REG(0x1420), 0x51011);
    HW_W32(REG(0x1418), 0x1a00bb);
    HW_W32(REG(0x141c), 0xef1a3043);
    HW_W16(REG(0x147e), 1);
    HW_W16(REG(0x1460), selector & ~3U);
    HW_W16(REG(0x1474), 0);
    v = HW_R16(REG(0x1464));
    HW_W16(REG(0x1464), v);
    v = HW_R16(REG(0x1466));
    HW_W16(REG(0x1466), v);
    HW_W16(REG(0x1468), 0x10);
    HW_W16(REG(0x146a), 0x90);
    HW_W16(REG(0x147c), 1);
    HW_W16(REG(0x147a), HW_R16(REG(0x147c)));
    v = (voltage == 1 ? 4 : 8) | 0x10;
    HW_W16(REG(0x146c), v);
    DelayThread(22000);
    if (!(HW_R16(REG(0x1462)) & 0x100))
        goto fail;
    HW_W16(REG(0x146c), v | 2);
    DelayThread(500000);
    HW_W16(REG(0x146c), v | 3);
    v = HW_R16(REG(0x1464));
    HW_W16(REG(0x1464), v);
    v = HW_R16(REG(0x1466));
    HW_W16(REG(0x1466), v);
    pccardTrace("pccf: RESET done voltage=%uV CARDSTAT=%04x POWER=%04x", voltage == 1 ? 3U : 5U,
                HW_R16(REG(0x1462)), HW_R16(REG(0x146c)));
    access_window(NULL, 2, 8);
    if (read_cf_profile(&info)) {
        pccardTrace("pccf: CIS rejected: unsupported/incomplete CF memory profile");
        goto fail;
    }
    if (pcdiag_cf_probe(&info, &memory, NULL, quiet_trace)) {
        pccardTrace("pccf: CF memory profile/configuration rejected");
        goto fail;
    }
    if (pccf_ata_attach(ata, &ops, NULL, pccardTrace))
        goto fail;
    ata->issue_read_sectors = issue_sectors;
    ata->issue_command = issue_rw;
#ifndef GAME_DRIVER
    ata->write_sector = pio_write_sector;
#endif
    ata->time_us = time_us;
    if (!pio_fallback_restart && (tune_rc = pio_profile(ata)) != 0) {
        pccardTrace("CF: profile verification failed rc=%d; restarting with original PIO", tune_rc);
        ata->ready = 0;
        pccf_hw_stop();
        DelayThread(100000);
        pio_fallback_restart = 1;
        tune_rc = pccf_hw_start(ata);
        pio_fallback_restart = 0;
        return tune_rc;
    }

    access_window(NULL, 0, 8);
    pccardTrace("pccf: PC CARD remains powered; SPACE=0, PIO polling");
    return 0;
fail:
    ata->ready = 0;
    pccf_hw_stop();
    return -1;
}
