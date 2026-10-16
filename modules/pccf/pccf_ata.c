/* Persistent form of DIAG5's hardware-tested EC/20 PIO data-in protocol.
   All status waits are bounded. A transfer error latches the session offline,
   so subsequent requests cannot issue commands into an uncertain state. */
#include <string.h>
#include "pccf_ata.h"
static unsigned char identify[512];
static unsigned int word(unsigned int i)
{
    return (unsigned int)identify[i * 2] | ((unsigned int)identify[i * 2 + 1] << 8);
}
static void ata_string(unsigned int first, unsigned int size, char *out)
{
    unsigned int i, c;
    for (i = 0; i < size; ++i) {
        c = identify[first * 2 + (i ^ 1U)];
        out[i] = c >= 32 && c <= 126 ? c : '?';
    }
    while (size && out[size - 1] == ' ')
        --size;
    out[size] = 0;
}
static int wait_status(pccf_ata_t *ata, int drq, const char *phase)
{
    const pcdiag_cf_ops_t *io = ata->ops->memory;
    unsigned int ms, spin, s = 0;
    for (ms = 0; ms < PCDIAG_ATA_POLL_LIMIT_MS; ++ms) {
        for (spin = 0;; ++spin) {
            s = io->read8(ata->context, 0x0e);
            if (!s || s == 0xff)
                break;
            if (!(s & 0x80)) {
                if (s & 0x21)
                    break;
                if (drq ? ((s & 8) != 0) : (!(s & 8) && (s & 0x40)))
                    return 0;
            }
            if (!ata->fast_poll || spin == 63)
                break;
        }
        if (!s || s == 0xff || (!(s & 0x80) && (s & 0x21)))
            break;
        io->wait_ms(ata->context, 1);
    }
    ata->trace("pccf: ATA FAIL phase=%s status=%02x error=%02x waited_ms=%u",
               phase, s, (unsigned int)io->read8(ata->context, 1), ms);
    ata->ready = 0;
    return -1;
}
static int transfer(pccf_ata_t *ata, unsigned int command,
                    unsigned int lba, unsigned int count, unsigned char *buffer)
{
    const pcdiag_cf_ops_t *io = ata->ops->memory;
    unsigned int i, v, sector;
    io->set_access(ata->context, 0, 8);
    if (wait_status(ata, 0, "before-command"))
        return -1;
    /* Conservative command spacing for CF bridges. No retry after a failed
       transaction: preserve the offline latch and log the failing address. */
    /* Preparation/settling is handled by the host, once per command. */
    if ((ata->issue_command && command != 0xec ?
             ata->issue_command(ata->context, command, lba, count) :
         command == 0x20 && ata->issue_read_sectors ?
             ata->issue_read_sectors(ata->context, lba, count) :
             ata->ops->issue_read_command(ata->context, command, lba))) {
        ata->trace("pccf: ATA FAIL host rejected cmd=%02x lba=%08lx", command, (unsigned long)lba);
        ata->ready = 0;
        return -1;
    }
    ++ata->commands;
    if (count > 1)
        ++ata->multi_commands;
    for (i = 0; i < 4; ++i)
        io->read8(ata->context, 0x0e);
    for (sector = 0; sector < count; ++sector) {
        if (wait_status(ata, 1, "data-request")) {
            ata->trace("pccf: ATA failed command cmd=%02x lba=%08lx count=%u completed_words=%u",
                       command, (unsigned long)(lba + sector), count, sector * 256);
            return -1;
        }
        /* READ SECTORS has one DRQ/data phase per sector. Acknowledge status,
           transfer exactly 256 words, then poll the next phase in byte mode. */
        (void)io->read8(ata->context, 7);
        io->set_access(ata->context, 0, 16);
        if (ata->read_sector)
            ata->read_sector(buffer + sector * 512);
        else
            for (i = 0; i < 256; ++i) {
                v = io->read16(ata->context, 0);
                buffer[sector * 512 + i * 2] = v & 0xff;
                buffer[sector * 512 + i * 2 + 1] = v >> 8;
            }
        io->set_access(ata->context, 0, 8);
        for (i = 0; i < 4; ++i)
            io->read8(ata->context, 0x0e);
    }
    if (wait_status(ata, 0, "transfer-complete")) {
        ata->trace("pccf: ATA failed command cmd=%02x lba=%08lx completed_words=%u", command, (unsigned long)lba, count * 256);
        return -1;
    }
    v = io->read8(ata->context, 7);
    if ((v & 0xa9) || !(v & 0x40)) {
        ata->trace("pccf: ATA FAIL final status=%02x cmd=%02x lba=%08lx", v, command, (unsigned long)lba);
        ata->ready = 0;
        return -1;
    }
    if (ata->commands <= 8 || (count > 1 && ata->multi_commands <= 4))
        ata->trace("pccf: ATA OK cmd=%02x lba=%08lx count=%u words=%u status=%02x",
                   command, (unsigned long)lba, count, count * 256, v);
    return 0;
}
int pccf_ata_attach(pccf_ata_t *ata, const pcdiag_ata_ops_t *ops,
                    void *context, pcdiag_cis_trace_t trace)
{
    const pcdiag_cf_ops_t *io = ops->memory;
    unsigned int s, alt, sc, sn, cl, ch, dh, pair, conf, cap, sectors, valid106, i, sum = 0;
    unsigned int reset_signature, zero_signature;
    memset(ata, 0, sizeof(*ata));
    ata->ops = ops;
    ata->context = context;
    ata->trace = trace;
    io->set_access(context, 0, 8);
    /* CIS may be readable while ATA is still completing reset. Wait for BSY
       to clear before checking the startup signature, at most five seconds. */
    for (i = 0; i < 5000; ++i) {
        alt = io->read8(context, 0x0e);
        if (alt == 0xff || !(alt & 0x80))
            break;
        io->wait_ms(context, 1);
    }
    trace("pccf: ATA startup wait_ms=%u ALT=%02x", i, alt);
    if (i == 5000) {
        trace("pccf: ATA startup timeout; no command sent");
        return -1;
    }
    s = io->read8(context, 7);
    alt = io->read8(context, 0x0e);
    sc = io->read8(context, 2);
    sn = io->read8(context, 3);
    cl = io->read8(context, 4);
    ch = io->read8(context, 5);
    dh = io->read8(context, 6);
    io->set_access(context, 0, 16);
    pair = io->read16(context, 6);
    io->set_access(context, 0, 8);
    trace("pccf: ATA PRECHECK ST=%02x ALT=%02x SC=%02x SN=%02x CL=%02x CH=%02x DH=%02x PAIR06=%04x", s, alt, sc, sn, cl, ch, dh, pair);
    reset_signature = sc == 1 && sn == 1 && !cl && !ch && dh == 0xa0;
    /* The tested SD-CF bridge supplies a valid memory
       CIS and ST=50/ALT=50/PAIR06=5000, but zeroes its taskfile on startup.
       Permit this exact observed pattern for a read-only IDENTIFY attempt.
       Retain byte/word agreement, readiness and all IDENTIFY validation. */
    zero_signature = s == 0x50 && !sc && !sn && !cl && !ch && !dh;
    if (s != alt || s != (pair >> 8) || dh != (pair & 0xff) ||
        !(s & 0x40) || (s & 0xa9) || (!reset_signature && !zero_signature)) {
        trace("pccf: ATA rejected reset signature or byte/word map; no command sent");
        return -1;
    }
    if (zero_signature)
        trace("pccf: zero startup signature accepted for IDENTIFY only; response validation required");
    if (transfer(ata, 0xec, 0, 1, identify))
        return -1;
    conf = word(0);
    cap = word(49);
    sectors = word(60) | (word(61) << 16);
    for (i = 0; i < 512; ++i)
        sum += identify[i];
    if (!conf || conf == 0xffff || ((conf & 0x8000) && conf != 0x848a) ||
        !(cap & 0x200) || !sectors || sectors == 0xffffffffU ||
        (identify[510] == 0xa5 && (sum & 0xff))) {
        trace("pccf: IDENTIFY rejected word0=%04x word49=%04x sectors=%08lx integrity=%02x checksum=%02x",
              conf, cap, (unsigned long)sectors, (unsigned int)identify[510], sum & 0xff);
        return -1;
    }
    valid106 = word(106);
    if ((valid106 & 0xc000) == 0x4000 && (valid106 & 0x1000) && (word(117) != 256 || word(118))) {
        trace("pccf: IDENTIFY rejected logical sector size; only 512-byte sectors supported");
        return -1;
    }
    ata->lba48 = (word(83) & 0xc400) == 0x4400;
    ata->flush_command = (word(83) & 0xc000) == 0x4000 ?
                             ((word(83) & 0x2000) ? 0xea : ((word(83) & 0x1000) ? 0xe7 : 0)) :
                             0;
    ata->write_cache = !!(word(85) & 0x20);
    if (ata->lba48) {
        unsigned int ext = word(100) | (word(101) << 16);
        if (word(102) || word(103))
            ext = 0xffffffffU; /* Bounded to 2 TiB minus one sector. */
        if (!ext || ext < sectors)
            return -1;
        sectors = ext;
    }
    ata->sectors = ata->lba48 ? sectors : sectors > PCDIAG_ATA_LBA28_SECTORS ? PCDIAG_ATA_LBA28_SECTORS :
                                                                               sectors;
    ata_string(27, 40, ata->model);
    ata_string(10, 20, ata->serial);
    ata_string(23, 8, ata->firmware);
    ata->ready = 1;
    trace("CF: LBA48=%u sectors=%08lx flush=%02x cache=%u", ata->lba48, (unsigned long)ata->sectors, ata->flush_command, ata->write_cache);
    trace("pccf: IDENTIFY ACCEPTED model=%s serial=%s firmware=%s sectors=%08lx MiB=%lu",
          ata->model, ata->serial, ata->firmware, (unsigned long)ata->sectors, (unsigned long)(ata->sectors / 2048));
    return 0;
}
int pccf_ata_read(pccf_ata_t *ata, unsigned int lba, unsigned int count, unsigned char *buffer)
{
    unsigned int i;
    if (!ata->ready || !buffer || !count || count > 64 || lba >= ata->sectors ||
        count > ata->sectors - lba)
        return -1;
    unsigned int extended = lba >= PCDIAG_ATA_LBA28_SECTORS || count > PCDIAG_ATA_LBA28_SECTORS - lba;
    if (extended && (!ata->lba48 || !ata->issue_command))
        return -1;
    if (ata->issue_read_sectors || ata->issue_command) {
        if (transfer(ata, extended ? 0x24 : 0x20, lba, count, buffer))
            return -1;
        ata->sector_reads += count;
        return 0;
    }
    for (i = 0; i < count; ++i) {
        if (transfer(ata, 0x20, lba + i, 1, buffer + i * 512))
            return -1;
        ++ata->sector_reads;
    }
    return 0;
}

#ifndef GAME_DRIVER
/* Writes use conservative 16-bit stores, flush before reporting success,
   and read every sector back. Never retry an uncertain write transaction. */
int pccf_ata_write(pccf_ata_t *ata, unsigned int lba, unsigned int count, const unsigned char *buffer)
{
    static unsigned char verify[512];
    const pcdiag_cf_ops_t *io = ata->ops->memory;
    unsigned int i, sector, command;
    if (!ata->ready || !buffer || !count || count > 64 || lba >= ata->sectors ||
        count > ata->sectors - lba || !ata->issue_command || !ata->write_sector ||
        (ata->write_cache && !ata->flush_command))
        return -1;
    command = lba >= PCDIAG_ATA_LBA28_SECTORS || count > PCDIAG_ATA_LBA28_SECTORS - lba ? 0x34 : 0x30;
    if (command == 0x34 && !ata->lba48)
        return -1;
    io->set_access(ata->context, 0, 8);
    if (wait_status(ata, 0, "before-write"))
        return -1;
    if (ata->issue_command(ata->context, command, lba, count))
        goto fail;
    for (i = 0; i < 4; i++)
        io->read8(ata->context, 0x0e);
    for (sector = 0; sector < count; sector++) {
        if (wait_status(ata, 1, "write-drq"))
            goto fail;
        (void)io->read8(ata->context, 7);
        ata->write_sector(buffer + sector * 512);
        io->set_access(ata->context, 0, 8);
        for (i = 0; i < 4; i++)
            io->read8(ata->context, 0x0e);
    }
    if (wait_status(ata, 0, "write-complete"))
        goto fail;
    if (ata->flush_command) {
        if (ata->issue_command(ata->context, ata->flush_command, 0, 0))
            goto fail;
        for (i = 0; i < 4; i++)
            io->read8(ata->context, 0x0e);
        if (wait_status(ata, 0, "write-flush"))
            goto fail;
    }
    for (sector = 0; sector < count; sector++) {
        if (pccf_ata_read(ata, lba + sector, 1, verify) || memcmp(verify, buffer + sector * 512, 512))
            goto fail;
    }
    if (++ata->write_commands <= 8)
        ata->trace("CF: WRITE VERIFIED lba=%08lx count=%u", (unsigned long)lba, count);
    return 0;
fail:
    ata->trace("CF: WRITE FAILED lba=%08lx count=%u; session offline", (unsigned long)lba, count);
    ata->ready = 0;
    return -1;
}
#endif
