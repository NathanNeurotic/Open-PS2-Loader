"""Exercise modules/bdm/libbdm/src/bd_cache.c -- the BDM block cache every FAT/exFAT device reads
through -- against a simulated block device that can fail or cut reads short.

The source is compiled unmodified on the host with stub SDK headers. The defect this guards: a
failed or short 8-sector refill used to be returned as a SUCCESSFUL read of the evicted block's
bytes, and cached under the new LBA. Run with --baseline <file> to point it at another bd_cache.c
(for example the SDK original) and watch those cases fail.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = root / 'modules/bdm/libbdm/src/bd_cache.c'
if len(sys.argv) == 3 and sys.argv[1] == '--baseline':
    source = Path(sys.argv[2])

STUB_TAMTYPES = r'''
#pragma once
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
'''

STUB_BDM = r'''
#pragma once
#include <tamtypes.h>
struct block_device
{
    void *priv;
    char *name;
    unsigned int devNr;
    unsigned int parNr;
    unsigned char parId;
    unsigned int sectorSize;
    u64 sectorOffset;
    u64 sectorCount;
    int (*read)(struct block_device *bd, u64 sector, void *buffer, u16 count);
    int (*write)(struct block_device *bd, u64 sector, const void *buffer, u16 count);
    void (*flush)(struct block_device *bd);
    int (*stop)(struct block_device *bd);
    char *path;
};
'''

STUB_SYSMEM = r'''
#pragma once
#include <stdlib.h>
#define ALLOC_FIRST 0
static inline void *AllocSysMemory(int mode, int size, void *ptr) { (void)mode; (void)ptr; return calloc(1, (size_t)size); }
static inline int FreeSysMemory(void *ptr) { free(ptr); return 0; }
'''

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <bd_cache.h>

#define DISK_SECTORS 256
static unsigned char disk[DISK_SECTORS * 512];
static int fail_from = -1, fail_to = -1; /* read of any sector in [from, to] fails */
static int short_reads;                  /* reads return at most this many sectors (0 = off) */
static int device_reads;

static int dev_read(struct block_device *bd, u64 sector, void *buffer, u16 count)
{
    (void)bd;
    device_reads++;
    if (sector + count > DISK_SECTORS)
        return -5; /* past the end: the drivers return -EIO */
    for (u64 s = sector; s < sector + count; s++)
        if ((int)s >= fail_from && (int)s <= fail_to)
            return -5;
    int n = count;
    if (short_reads && n > short_reads)
        n = short_reads;
    memcpy(buffer, disk + sector * 512, (size_t)n * 512);
    return n;
}

static int dev_write(struct block_device *bd, u64 sector, const void *buffer, u16 count)
{
    (void)bd;
    memcpy(disk + sector * 512, buffer, (size_t)count * 512);
    return count;
}

static void dev_flush(struct block_device *bd) { (void)bd; }
static int dev_stop(struct block_device *bd) { (void)bd; return 0; }

static int is_sector(const unsigned char *buf, int lba)
{
    for (int i = 0; i < 512; i++)
        if (buf[i] != (unsigned char)(lba * 7 + 1))
            return 0;
    return 1;
}

int main(void)
{
    for (int s = 0; s < DISK_SECTORS; s++)
        memset(disk + s * 512, s * 7 + 1, 512);

    struct block_device raw = {0};
    raw.name = "sim";
    raw.sectorSize = 512;
    raw.sectorCount = DISK_SECTORS;
    raw.read = dev_read;
    raw.write = dev_write;
    raw.flush = dev_flush;
    raw.stop = dev_stop;
    struct block_device *bd = bd_cache_create(&raw);
    unsigned char buf[8 * 512];

    /* A normal read fills the cache; a second read of the block is a hit. */
    assert(bd->read(bd, 0, buf, 1) == 1 && is_sector(buf, 0));
    int before = device_reads;
    assert(bd->read(bd, 3, buf, 1) == 1 && is_sector(buf, 3));
    assert(device_reads == before);

    /* THE DEFECT. The refill for LBA 16 fails. The read must fail -- not hand back the bytes of the
       block that slot held before (LBA 0-7). */
    for (int i = 0; i < 32 * 8; i += 8) { /* touch every other block so the LBA 0 block is evicted */
        fail_from = fail_to = -1;
        bd->read(bd, 40 + (u64)i % 200, buf, 1);
    }
    fail_from = 16;
    fail_to = 23;
    memset(buf, 0xEE, sizeof(buf));
    int r = bd->read(bd, 16, buf, 1);
    assert(r != 1);
    assert(!is_sector(buf, 0));

    /* ...and the failure must not be cached: once the device recovers, the real data comes back. */
    fail_from = fail_to = -1;
    assert(bd->read(bd, 16, buf, 1) == 1 && is_sector(buf, 16));
    assert(bd->read(bd, 17, buf, 1) == 1 && is_sector(buf, 17));

    /* A read error on a sector the caller did not ask for (inside the 8-sector refill) must not fail
       the sectors it did ask for. */
    fail_from = fail_to = 37;
    assert(bd->read(bd, 34, buf, 2) == 2 && is_sector(buf, 34) && is_sector(buf + 512, 35));
    fail_from = fail_to = -1;
    assert(bd->read(bd, 37, buf, 1) == 1 && is_sector(buf, 37));

    /* A short refill is not cached: the caller still gets exactly what it asked for. */
    short_reads = 4;
    assert(bd->read(bd, 100, buf, 2) == 2 && is_sector(buf, 100) && is_sector(buf + 512, 101));
    short_reads = 0;
    assert(bd->read(bd, 106, buf, 1) == 1 && is_sector(buf, 106));

    /* The last sectors of the device: the 8-sector refill runs past the end, the read must not. */
    assert(bd->read(bd, DISK_SECTORS - 2, buf, 1) == 1 && is_sector(buf, DISK_SECTORS - 2));
    assert(bd->read(bd, DISK_SECTORS - 1, buf, 1) == 1 && is_sector(buf, DISK_SECTORS - 1));

    /* Writes still invalidate: after a write through the cache, a read sees the new bytes. */
    assert(bd->read(bd, 200, buf, 1) == 1);
    memset(buf, (200 * 7 + 1) ^ 0xFF, 512);
    assert(bd->write(bd, 200, buf, 1) == 1);
    memset(disk + 200 * 512, 200 * 7 + 1, 512); /* restore the pattern on disk ... */
    assert(bd->read(bd, 200, buf, 1) == 1 && is_sector(buf, 200)); /* ... and the cache must not mask it */

    bd_cache_destroy(bd);
    puts("bd_cache: all cases passed");
    return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stubs = Path(tmp) / 'stubs'
        stubs.mkdir()
        (stubs / 'tamtypes.h').write_text(STUB_TAMTYPES)
        (stubs / 'bdm.h').write_text(STUB_BDM)
        (stubs / 'sysmem.h').write_text(STUB_SYSMEM)
        harness = Path(tmp) / 'harness.c'
        harness.write_text(HARNESS)
        exe = Path(tmp) / 'bd_cache_test'
        cmd = ['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function',
               '-I', str(stubs), '-I', str(root / 'modules/bdm/libbdm/include'),
               '-I', str(root / 'modules/bdm/libbdm/src/include'),
               str(source), str(harness), '-o', str(exe)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print('bd_cache harness failed to compile:\n' + result.stderr)
            sys.exit(1)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            print('bd_cache checks FAILED:\n' + result.stderr)
            sys.exit(1)


main()
