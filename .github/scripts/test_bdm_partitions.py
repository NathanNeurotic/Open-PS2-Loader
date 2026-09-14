"""Exercise modules/bdm's MBR/GPT partition drivers and partition I/O bounds on the host.

part_driver.c, part_driver_mbr.c and part_driver_gpt.c are compiled unmodified against stub SDK
headers and a simulated 512-byte-sector device. These pin the review fixes on PR #650: whole-range
MBR validation, freeing the probe buffer on a failed read, GPT entry-size/count/bounds validation,
inclusive GPT lengths, GPT only on whole devices, and partition reads/writes that cannot cross into
the next partition. It also checks that bd_cache refuses devices whose sectors are not 512 bytes.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
src = root / 'modules/bdm/src'

STUB_TYPES = r'''
#pragma once
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
'''

STUB_BDM = r'''
#pragma once
#include <types.h>
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
struct file_system
{
    void *priv;
    char *name;
    int (*connect_bd)(struct block_device *bd);
    void (*disconnect_bd)(struct block_device *bd);
};
void bdm_connect_bd(struct block_device *bd);
void bdm_disconnect_bd(struct block_device *bd);
void bdm_connect_fs(struct file_system *fs);
'''

STUB_SYSMEM = r'''
#pragma once
#include <stdlib.h>
#define ALLOC_FIRST 0
extern int allocs, frees, fail_alloc;
static inline void *AllocSysMemory(int mode, int size, void *ptr) { (void)mode; (void)ptr; if (fail_alloc) return NULL; allocs++; return calloc(1, (size_t)size); }
static inline int FreeSysMemory(void *ptr) { if (ptr) frees++; free(ptr); return 0; }
'''

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <bdm.h>
#include "part_driver.h"

extern void part_init(void);
extern struct block_device *bd_cache_create(struct block_device *bd);

int allocs, frees, fail_alloc;
static struct block_device *connected[16];
static int nconnected;
void bdm_connect_bd(struct block_device *bd) { connected[nconnected++] = bd; }
void bdm_disconnect_bd(struct block_device *bd) { (void)bd; }
void bdm_connect_fs(struct file_system *fs) { (void)fs; }

#define DISK_SECTORS 64
static unsigned char disk[DISK_SECTORS * 512];
static int fail_reads, dev_reads;
static u64 last_io_sector;
static int last_io_count;

static int dev_read(struct block_device *bd, u64 sector, void *buffer, u16 count)
{
    (void)bd;
    dev_reads++;
    last_io_sector = sector;
    last_io_count = count;
    if (fail_reads || sector + count > DISK_SECTORS)
        return -5;
    memcpy(buffer, disk + sector * 512, (size_t)count * 512);
    return count;
}

static int dev_write(struct block_device *bd, u64 sector, const void *buffer, u16 count)
{
    (void)bd;
    (void)buffer;
    last_io_sector = sector;
    last_io_count = count;
    return count;
}

static void put32(unsigned char *p, u32 v) { memcpy(p, &v, 4); }
static void put64(unsigned char *p, u64 v) { memcpy(p, &v, 8); }

static struct block_device raw;

static void reset(void)
{
    memset(disk, 0, sizeof(disk));
    memset(connected, 0, sizeof(connected));
    nconnected = 0;
    fail_reads = fail_alloc = 0;
    for (int i = 0; i < MAX_PARTITIONS; i++)
        g_part[i].bd = NULL;
    memset(&raw, 0, sizeof(raw));
    raw.name = "sim";
    raw.sectorSize = 512;
    raw.sectorCount = DISK_SECTORS;
    raw.read = dev_read;
    raw.write = dev_write;
}

static void mbr_entry(int i, u8 type, u32 first, u32 count)
{
    unsigned char *e = disk + 0x1BE + i * 16;
    e[4] = type;
    put32(e + 8, first);
    put32(e + 12, count);
    disk[0x1FE] = 0x55;
    disk[0x1FF] = 0xAA;
}

static void gpt_header(u32 count, u32 entry_size)
{
    unsigned char *h = disk + 512;
    memcpy(h, "EFI PART", 8);
    put64(h + 0x28, 4);  /* first usable */
    put64(h + 0x30, 60); /* last usable */
    put64(h + 0x48, 2);  /* entries at LBA 2 */
    put32(h + 0x50, count);
    put32(h + 0x54, entry_size);
}

static void gpt_entry(int i, u64 first, u64 last)
{
    unsigned char *e = disk + 2 * 512 + i * 128;
    e[0] = 0xA2; /* any non-null type GUID that is not reserved/ESP */
    e[1] = 0xA0;
    put64(e + 32, first);
    put64(e + 40, last);
}

int main(void)
{
    part_init();

    /* MBR: a partition that fits is connected with the table's geometry. */
    reset();
    mbr_entry(0, 0x07, 8, 40);
    assert(part_connect_mbr(&raw) == 0 && nconnected == 1);
    assert(connected[0]->sectorOffset == 8 && connected[0]->sectorCount == 40);

    /* Partition I/O stays inside the partition. */
    struct block_device *p = connected[0];
    unsigned char buf[4 * 512];
    assert(p->read(p, 39, buf, 1) == 1 && last_io_sector == 47);
    assert(p->read(p, 39, buf, 2) < 0);
    assert(p->read(p, 41, buf, 1) < 0);
    assert(p->write(p, 40, buf, 1) < 0);
    assert(p->write(p, 36, buf, 4) == 4 && last_io_sector == 44);
    assert(p->write(p, 0xFFFFFFFFFFFFFFFFull, buf, 2) < 0); /* no wrap-around */

    /* MBR: a partition running past the end of the device is rejected, not advertised. */
    reset();
    mbr_entry(0, 0x07, 8, 100);
    assert(part_connect_mbr(&raw) != 0 && nconnected == 0);

    /* MBR: a failed probe read releases its buffer. */
    reset();
    fail_reads = 1;
    int a = allocs, f = frees;
    assert(part_connect_mbr(&raw) != 0);
    assert(allocs - a == frees - f);

    /* GPT: lengths are inclusive, and parsing stops at the declared entry count even when more
       non-empty entries follow in the same sector. */
    reset();
    gpt_header(2, 128);
    gpt_entry(0, 10, 19);
    gpt_entry(1, 20, 29);
    gpt_entry(2, 30, 39); /* beyond partition_count */
    assert(part_connect_gpt(&raw) == 0 && nconnected == 2);
    assert(connected[0]->sectorOffset == 10 && connected[0]->sectorCount == 10);
    assert(connected[1]->sectorOffset == 20 && connected[1]->sectorCount == 10);

    /* GPT: a reversed entry is skipped instead of underflowing into a huge partition. */
    reset();
    gpt_header(4, 128);
    gpt_entry(0, 30, 25);
    gpt_entry(1, 40, 49);
    assert(part_connect_gpt(&raw) == 0 && nconnected == 1 && connected[0]->sectorOffset == 40);

    /* GPT: an entry size other than 128 bytes is refused. */
    reset();
    gpt_header(4, 256);
    gpt_entry(0, 10, 19);
    assert(part_connect_gpt(&raw) != 0 && nconnected == 0);

    /* GPT: a partition's own block device is never parsed as a GPT. */
    reset();
    gpt_header(4, 128);
    gpt_entry(0, 10, 19);
    raw.sectorOffset = 8;
    int reads = dev_reads;
    assert(part_connect_gpt(&raw) != 0 && dev_reads == reads);

    /* GPT: allocation failure reports failure, not a successful mount. */
    reset();
    gpt_header(4, 128);
    gpt_entry(0, 10, 19);
    fail_alloc = 1;
    assert(part_connect_gpt(&raw) != 0 && nconnected == 0);

    /* The block cache refuses devices whose sectors are not 512 bytes (its slots are 8 * 512). */
    reset();
    raw.sectorSize = 4096;
    assert(bd_cache_create(&raw) == NULL);
    raw.sectorSize = 512;
    fail_alloc = 1;
    assert(bd_cache_create(&raw) == NULL);

    puts("bdm partitions: all cases passed");
    return 0;
}
'''


def main():
    bdm_c = (src / 'bdm.c').read_text().replace('\r\n', '\n')
    match = re.search(r'static void bdm_try_mount\(.*?\n\}\n', bdm_c, re.S)
    if match is None or 'sectorSize != 512' not in match.group(0) or \
            match.group(0).find('sectorSize != 512') > match.group(0).find('connect_bd('):
        print('bdm.c: bdm_try_mount no longer refuses non-512-byte devices before offering them to a driver')
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        stubs = Path(tmp) / 'stubs'
        stubs.mkdir()
        (stubs / 'types.h').write_text(STUB_TYPES)
        (stubs / 'tamtypes.h').write_text(STUB_TYPES)
        (stubs / 'bdm.h').write_text(STUB_BDM)
        (stubs / 'sysmem.h').write_text(STUB_SYSMEM)
        harness = Path(tmp) / 'harness.c'
        harness.write_text(HARNESS)
        exe = Path(tmp) / 'partitions_test'
        cmd = ['cc', '-std=gnu99', '-w', '-I', str(stubs), '-I', str(src / 'include'),
               '-I', str(root / 'modules/bdm/libbdm/include'), '-I', str(root / 'modules/bdm/libbdm/src/include'),
               str(src / 'part_driver.c'), str(src / 'part_driver_mbr.c'), str(src / 'part_driver_gpt.c'),
               str(root / 'modules/bdm/libbdm/src/bd_cache.c'), str(harness), '-o', str(exe)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print('partition harness failed to compile:\n' + result.stderr)
            sys.exit(1)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            print('bdm partition checks FAILED:\n' + result.stderr)
            sys.exit(1)


main()
