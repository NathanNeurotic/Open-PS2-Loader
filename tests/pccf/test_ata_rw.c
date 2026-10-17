#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../../modules/pccf/pccf_ata.c"
static unsigned char disk[64 * 512], ident[512];
static unsigned int pos, remaining, lastcmd, commands[200], nc, writes, base;
static int fail_flush, corrupt, fail_drq;
static unsigned char rd8(void *ctx, unsigned int reg)
{
    (void)ctx;
    if (reg == 7 || reg == 14)
        return ((fail_flush && (lastcmd == 0xea || lastcmd == 0xe7)) || (fail_drq && lastcmd == 0x30)) ? 0x51 : remaining ? 0x58 :
                                                                                                                            0x50;
    return 0;
}
static unsigned short rd16(void *ctx, unsigned int reg)
{
    unsigned char *src;
    unsigned int v;
    (void)ctx;
    if (reg == 6)
        return 0x5000;
    assert(remaining && reg == 0);
    src = lastcmd == 0xec ? ident : disk;
    v = src[pos] | (src[pos + 1] << 8);
    pos += 2;
    if (!(pos % 512))
        remaining--;
    return v;
}
static void access_mode(void *c, unsigned int s, unsigned int w)
{
    (void)c;
    assert(s == 0 && (w == 8 || w == 16));
}
static void wait_ms(void *c, unsigned int ms)
{
    (void)c;
    (void)ms;
}
static void trace(const char *s, ...) { (void)s; }
static int command(void *c, unsigned int cmd, unsigned int lba, unsigned int count)
{
    (void)c;
    assert(nc < 200);
    commands[nc++] = cmd;
    lastcmd = cmd;
    if (cmd == 0xea || cmd == 0xe7) {
        remaining = 0;
        return 0;
    }
    pos = cmd == 0xec ? 0 : (lba - base) * 512;
    remaining = count;
    assert(pos + count * 512 <= sizeof(disk));
    return 0;
}
static int identify_cmd(void *c, unsigned int cmd, unsigned int lba) { return command(c, cmd, lba, 1); }
static void wr_sector(const unsigned char *b)
{
    assert(remaining);
    memcpy(disk + pos, b, 512);
    if (corrupt)
        disk[pos] ^= 1;
    pos += 512;
    remaining--;
    writes++;
}
static const pcdiag_cf_ops_t io = {rd8, rd16, access_mode, wait_ms};
static const pcdiag_ata_ops_t ops = {&io, identify_cmd};
static pccf_ata_t a;
static void setup(unsigned int lba)
{
    memset(&a, 0, sizeof(a));
    base = lba;
    pos = remaining = lastcmd = nc = writes = 0;
    fail_flush = corrupt = fail_drq = 0;
    a.ops = &ops;
    a.trace = trace;
    a.ready = 1;
    a.sectors = 1000000000;
    a.lba48 = 1;
    a.flush_command = 0xea;
    a.write_cache = 1;
    a.issue_command = command;
    a.write_sector = wr_sector;
}
static void word_set(int i, unsigned int v)
{
    ident[i * 2] = v;
    ident[i * 2 + 1] = v >> 8;
}
int main(void)
{
    unsigned char in[64 * 512 + 1], out[64 * 512];
    unsigned int i;
    for (i = 0; i < sizeof(in); i++)
        in[i] = (i * 37 + i / 512) & 255;
    setup(32);
    assert(pccf_ata_write(&a, 32, 64, in + 1) == 0 && writes == 64 && a.ready);
    assert(commands[0] == 0x30 && commands[1] == 0xea && nc == 66);
    assert(!memcmp(disk, in + 1, sizeof(disk)));
    assert(pccf_ata_read(&a, 32, 64, out) == 0 && !memcmp(out, in + 1, sizeof(out)));
    setup(0x30000000);
    assert(pccf_ata_write(&a, base, 2, in) == 0 && commands[0] == 0x34 && commands[2] == 0x24);
    setup(0x0fffffff);
    assert(pccf_ata_read(&a, base, 2, out) == 0 && commands[0] == 0x24);
    setup(0x30000000);
    a.lba48 = 0;
    assert(pccf_ata_read(&a, base, 1, out) < 0 && pccf_ata_write(&a, base, 1, in) < 0 && nc == 0);
    setup(0);
    a.flush_command = 0;
    assert(pccf_ata_write(&a, 0, 1, in) < 0 && nc == 0);
    a.write_cache = 0;
    assert(pccf_ata_write(&a, 0, 1, in) == 0 && nc == 2);
    setup(0);
    fail_flush = 1;
    assert(pccf_ata_write(&a, 0, 1, in) < 0 && !a.ready && writes == 1 && nc == 2);
    assert(pccf_ata_write(&a, 0, 1, in) < 0 && nc == 2);
    setup(0);
    corrupt = 1;
    assert(pccf_ata_write(&a, 0, 1, in) < 0 && !a.ready && writes == 1);
    setup(0);
    fail_drq = 1;
    assert(pccf_ata_write(&a, 0, 1, in) < 0 && !a.ready && !writes);
    setup(0);
    assert(pccf_ata_write(&a, a.sectors, 1, in) < 0 && !nc);
    assert(pccf_ata_write(&a, a.sectors - 1, 2, in) < 0 && !nc);
    assert(pccf_ata_write(&a, 0, 65, in) < 0 && !nc);
    assert(pccf_ata_write(&a, 0, 0, in) < 0 && !nc);
    /* Actual IDENTIFY parser: 512GB, legacy LBA28, malformed extended capacity. */
    memset(ident, 0, sizeof(ident));
    word_set(0, 0x848a);
    word_set(49, 0x200);
    word_set(60, 0xffff);
    word_set(61, 0x0fff);
    word_set(83, 0x7400);
    word_set(85, 0x20);
    word_set(100, 1000000000 & 65535);
    word_set(101, 1000000000 >> 16);
    setup(0);
    assert(pccf_ata_attach(&a, &ops, 0, trace) == 0);
    assert(a.sectors == 1000000000 && a.lba48 && a.flush_command == 0xea && a.write_cache);
    word_set(83, 0);
    setup(0);
    assert(pccf_ata_attach(&a, &ops, 0, trace) == 0 && !a.lba48 && a.sectors == 0x0fffffff);
    word_set(83, 0x7400);
    word_set(100, 1);
    word_set(101, 0);
    setup(0);
    assert(pccf_ata_attach(&a, &ops, 0, trace) < 0 && !a.ready);
    puts("PASS actual ATA: IDENTIFY LBA48, high/cross-boundary reads/writes, 64 sectors, flush, readback, corruption, failure latch, bounds");
}
