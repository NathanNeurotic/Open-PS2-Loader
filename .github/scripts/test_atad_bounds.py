"""Exercise the production ATA transfer function against a recording command stub.

No disk is opened. Optional source path permits testing a historical implementation.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "modules/hdd/atad/src/ps2atad.c"
source = path.read_text()
start = source.index("int ata_device_sector_io64(int device, void *buf, u64 lba, u32 nsectors, int dir)\n{")
production = source[start:source.index("\n}", start) + 2]

prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define USE_SPD_REGS
#define SPD_REG16(x) spd_reg
#define SPD_IF_DMA_ENABLE 1
#define ATA_RES_ERR_NODEV (-1)
#define ATA_RES_ERR_IO (-2)
#define ATA_RES_ERR_ICRC (-3)
#define ATA_C_READ_DMA 0xc8
#define ATA_C_WRITE_DMA 0xca
#define ATA_C_READ_DMA_EXT 0x25
#define ATA_C_WRITE_DMA_EXT 0x35
static u16 spd_reg __attribute__((unused)); /* Historical sources clean up DMA here. */
static struct { int exists, lba48; u32 total_sectors; u64 total_sectors_lba48; } atad_devinfo[2];
static int ata_dvrp_workaround;
static int calls, waits, crc_failures, exec_error, wait_error;
static u8 buffer[65537 * 512];
static struct { void *buf; u64 lba; u32 count; u16 encoded, command; int device; } trace[8];
static int sceAtaExecCmd(void *buf, u32 count, u16 feature, u16 encoded,
                         u16 sector, u16 lcyl, u16 hcyl, u16 select, u16 command) {
    (void)feature;
    assert(calls < 8); /* Detect non-progress without hanging the test. */
    int ext = command == ATA_C_READ_DMA_EXT || command == ATA_C_WRITE_DMA_EXT;
    u64 lba = (sector & 255) | ((u64)(lcyl & 255) << 8) | ((u64)(hcyl & 255) << 16);
    if (ext)
        lba |= ((u64)(sector >> 8) << 24) | ((u64)(lcyl >> 8) << 32) | ((u64)(hcyl >> 8) << 40);
    else
        lba |= (u64)(select & 15) << 24;
    trace[calls].buf = buf;
    trace[calls].lba = lba;
    trace[calls].count = count;
    trace[calls].encoded = encoded;
    trace[calls].command = command;
    trace[calls++].device = (select >> 4) & 1;
    return exec_error;
}
static int sceAtaWaitResult(void) {
    waits++;
    if (crc_failures > 0) { crc_failures--; return ATA_RES_ERR_ICRC; }
    return wait_error;
}
static void reset(int ext, u64 capacity) {
    memset(atad_devinfo, 0, sizeof(atad_devinfo));
    memset(trace, 0, sizeof(trace));
    calls = waits = crc_failures = exec_error = wait_error = ata_dvrp_workaround = 0;
    for (int i = 0; i < 2; i++) {
        atad_devinfo[i].exists = 1;
        atad_devinfo[i].lba48 = ext;
        atad_devinfo[i].total_sectors = capacity > 0x10000000 ? 0x10000000 : capacity;
        atad_devinfo[i].total_sectors_lba48 = capacity;
    }
}
'''

tests = r'''
int main(void) {
    const u64 limit = 0x10000000;
    for (int dir = 0; dir <= 1; dir++) {
        reset(1, 100);
        assert(ata_device_sector_io64(-1, buffer, 0, 1, dir) == ATA_RES_ERR_NODEV);
        assert(ata_device_sector_io64(2, buffer, 0, 1, dir) == ATA_RES_ERR_NODEV);
        atad_devinfo[0].exists = 0;
        assert(ata_device_sector_io64(0, buffer, 0, 1, dir) == ATA_RES_ERR_NODEV);
        assert(calls == 0);

        reset(1, 0);
        assert(ata_device_sector_io64(0, buffer, 0, 1, dir) == ATA_RES_ERR_IO && calls == 0);
        reset(1, 100);
        assert(ata_device_sector_io64(0, buffer, 100, 1, dir) == ATA_RES_ERR_IO);
        assert(ata_device_sector_io64(0, buffer, 99, 2, dir) == ATA_RES_ERR_IO);
        assert(ata_device_sector_io64(0, buffer, UINT64_MAX, 2, dir) == ATA_RES_ERR_IO);
        assert(ata_device_sector_io64(0, buffer, 1, UINT32_MAX, dir) == ATA_RES_ERR_IO);
        assert(calls == 0);
        assert(ata_device_sector_io64(0, buffer, 0, 0, dir) == 0 && calls == 0);
        assert(ata_device_sector_io64(1, buffer, 99, 1, dir) == 0);
        assert(calls == 1 && trace[0].device == 1 && trace[0].lba == 99 && trace[0].count == 1);
        assert(trace[0].command == (dir ? ATA_C_WRITE_DMA_EXT : ATA_C_READ_DMA_EXT));

        /* Even implausible IDENTIFY capacity must not permit 28-bit address truncation. */
        reset(0, limit + 100);
        assert(ata_device_sector_io64(0, buffer, limit, 1, dir) == ATA_RES_ERR_IO);
        assert(ata_device_sector_io64(0, buffer, limit - 1, 2, dir) == ATA_RES_ERR_IO);
        assert(calls == 0);
        assert(ata_device_sector_io64(0, buffer, limit - 1, 1, dir) == 0);
        assert(calls == 1 && trace[0].lba == limit - 1);
        assert(trace[0].command == (dir ? ATA_C_WRITE_DMA : ATA_C_READ_DMA));

        reset(0, 1000);
        assert(ata_device_sector_io64(0, buffer, 10, 257, dir) == 0 && calls == 2);
        assert(trace[0].count == 256 && (trace[0].encoded & 255) == 0);
        assert(trace[1].count == 1 && trace[1].lba == 266 && trace[1].buf == buffer + 256 * 512);

        /* 65536 is encoded as zero only in the taskfile, never in the DMA count. */
        reset(1, 100000);
        assert(ata_device_sector_io64(0, buffer, 7, 65536, dir) == 0 && calls == 1);
        assert(trace[0].encoded == 0 && trace[0].count == 65536 && trace[0].lba == 7);
        reset(1, 100000);
        assert(ata_device_sector_io64(0, buffer, 7, 65537, dir) == 0 && calls == 2);
        assert(trace[1].count == 1 && trace[1].lba == 65543 && trace[1].buf == buffer + 65536 * 512);

        reset(1, 0xffffffff);
        assert(ata_device_sector_io64(0, buffer, 0xabcdef01, 1, dir) == 0);
        assert(trace[0].lba == 0xabcdef01);

        /* DVR switches at the reported legacy capacity, including a malformed oversized one. */
        const u32 boundaries[] = {1000, 0x10000000, 0x10000010};
        for (unsigned i = 0; i < sizeof(boundaries) / sizeof(boundaries[0]); i++) {
            reset(1, limit + 100);
            ata_dvrp_workaround = 1;
            atad_devinfo[0].total_sectors = boundaries[i];
            u64 boundary = boundaries[i] > limit ? limit : boundaries[i];
            assert(ata_device_sector_io64(0, buffer, boundary - 1, 2, dir) == 0 && calls == 2);
            assert(trace[0].lba == boundary - 1 && trace[0].count == 1);
            assert(trace[0].command == (dir ? ATA_C_WRITE_DMA : ATA_C_READ_DMA));
            assert(trace[1].lba == boundary && trace[1].count == 1 && trace[1].buf == buffer + 512);
            assert(trace[1].command == (dir ? ATA_C_WRITE_DMA_EXT : ATA_C_READ_DMA_EXT));
        }

        reset(1, 100);
        crc_failures = 2;
        assert(ata_device_sector_io64(0, buffer, 5, 1, dir) == 0 && calls == 3 && waits == 3);
        assert(trace[0].lba == trace[2].lba && trace[0].buf == trace[2].buf);
        reset(1, 100);
        crc_failures = 3;
        assert(ata_device_sector_io64(0, buffer, 5, 1, dir) == ATA_RES_ERR_ICRC && calls == 3);
        reset(1, 100);
        exec_error = ATA_RES_ERR_IO;
        assert(ata_device_sector_io64(0, buffer, 5, 1, dir) == ATA_RES_ERR_IO && calls == 1 && waits == 0);
        reset(1, 1000);
        wait_error = ATA_RES_ERR_IO;
        assert(ata_device_sector_io64(0, buffer, 5, 257, dir) == ATA_RES_ERR_IO && calls == 1);
        printf("PASS: ATA %s bounds, taskfile encoding, DMA counts, DVR transitions and retries\n", dir ? "write" : "read");
    }
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="atad-bounds-tests-") as temp:
    c = Path(temp) / "test.c"
    exe = Path(temp) / "test"
    c.write_text(prefix + production + tests)
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
