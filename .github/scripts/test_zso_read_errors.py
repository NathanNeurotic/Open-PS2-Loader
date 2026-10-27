"""A failed device read in the ZSO reader is reported as a read error, never decoded as data.

The in-game sector cache (DeviceReadSectorsCached in cdvdman.c) ignored a failed window fill,
returned success, and kept serving that window on later hits. The cache is on by default for USB,
HDD and SMB, so most in-game ZSO data reads went through it and a read error reached the game as
garbage sectors. ziso_read_sector() also returned 0 for a failed read, which
DeviceReadSectorsCompressed reported as end of media (SCECdErEOM) instead of a read error.

A ZSO file seldom ends on a sector boundary. Over SMB the read of its last sector stops at the end
of the file, and smb_ReadFile reported that as a failed read, so once failed window fills were no
longer ignored the end of a ZSO image could not be read over SMB. smb_ReadFile now returns the
short count and the SMB sector reader pads that last sector with zeros, as a block device does.

Compiles the real ziso_init/ziso_read_sector, the real LZ4 decoder, and either the in-game reader
(DeviceReadSectorsCached, read_raw_data, DeviceReadSectorsCompressed from cdvdman.c) or the menu
reader (ReadHDDSectors, longLseek, read_raw_data from src/zso.c) against an in-memory ZSO image
with injected device failures. The in-game reader runs over two devices: a block device that reads
whole sectors (like BDM), and SMB, built from the real smb_ReadFile/smb_ReadCD (smb.c) and
DeviceReadSectors (device-smb.c) over a server that sends what the file holds and zero bytes at its
end. Checks: persistent and one-shot failures are errors, through the sector cache too; a later
read after a failure returns the right data (no poisoned index or sector cache is kept, including
an older valid window); a cache window that runs past the end of the image still serves the
sectors inside it; the last, partial sector of an SMB file reads; a split SMB image reads up to
and across a part boundary; an index read too short for the request is a failed read; a tiny
image whose index read ends at EOF still decodes.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(text, pattern, what):
    match = re.search(pattern, text, re.M)
    if match is None:
        sys.exit('%s not found' % what)
    return text[match.start():text.index('\n}', match.start()) + 3]


cdvdman = read('modules/iopcore/cdvdman/cdvdman.c')
smb = read('modules/iopcore/cdvdman/smb.c')
device_smb = read('modules/iopcore/cdvdman/device-smb.c')
menu = read('src/zso.c')
cache_statics = '\n'.join(re.findall(r'^static u(?:8|64) (?:MAX_SECTOR_CACHE|\*sector_cache|cur_sector) = [^;]+;',
                                     cdvdman, re.M))
if cache_statics.count(';') != 3:
    sys.exit('cdvdman.c: sector cache statics not found')
INGAME = '\n\n'.join(function(cdvdman, pattern, 'cdvdman.c ' + pattern) for pattern in (
    r'^int DeviceReadSectorsCached\([^;{]*\)\s*\{', r'^int read_raw_data\([^;{]*\)\s*\{',
    r'^int DeviceReadSectorsCompressed\([^;{]*\)\s*\{'))
SMB = '\n\n'.join([function(smb, pattern, 'smb.c ' + pattern) for pattern in (
    r'^int smb_ReadFile\([^;{]*\)\s*\{', r'^int smb_ReadCD\([^;{]*\)\s*\{')] +
    [function(device_smb, r'^int DeviceReadSectors\([^;{]*\)\s*\{', 'device-smb.c DeviceReadSectors')])
MENU = '\n\n'.join(function(menu, pattern, 'src/zso.c ' + pattern) for pattern in (
    r'^static \w+ ReadHDDSectors\([^;{]*\)\s*\{', r'^static void longLseek\([^;{]*\)\s*\{',
    r'^int read_raw_data\([^;{]*\)\s*\{'))

TAMTYPES = r'''
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;
'''

COMMON = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include "zso.c" /* the real shared reader: ziso_init + ziso_read_sector */

void *ziso_alloc(u32 size) { void *p = NULL; return posix_memalign(&p, 64, size) ? NULL : p; } /* aligned: ziso_init's realign stays off */

static u8 image[1 << 20];
static u32 imageSize;
static int failures;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); failures++; } } while (0)

static u8 expected(u32 block, u32 byte, int zeros) { return zeros ? 0 : (u8)(block * 31 + byte * 7 + 1); }

/* blocks: raw (top bit set) patterned blocks, or LZ4-compressed all-zero blocks (18 bytes each). */
static void buildImage(u32 blocks, int compressed)
{
    static const u8 zeroBlock[18] = {0x1f, 0x00, 0x01, 0x00, 255, 255, 255, 255, 255, 255, 255, 238, 0x50, 0, 0, 0, 0, 0};
    ZISO_header h = {ZSO_MAGIC, sizeof(ZISO_header), (u64)blocks * 2048, 2048, 1, 0, {0, 0}};
    u32 *index = (u32 *)(image + sizeof(h));
    u32 pos = sizeof(h) + (blocks + 1) * 4;

    memset(image, 0, sizeof(image));
    memcpy(image, &h, sizeof(h));
    for (u32 b = 0; b < blocks; b++) {
        if (compressed) {
            index[b] = pos;
            memcpy(image + pos, zeroBlock, sizeof(zeroBlock));
            pos += sizeof(zeroBlock);
        } else {
            index[b] = pos | 0x80000000;
            for (u32 i = 0; i < 2048; i++)
                image[pos + i] = expected(b, i, 0);
            pos += 2048;
        }
    }
    index[blocks] = pos;
    imageSize = pos;
    ziso_init((ZISO_header *)image, index[0]);
}

static int matches(const u8 *buf, u32 first, u32 count, int zeros)
{
    for (u32 b = 0; b < count; b++)
        for (u32 i = 0; i < 2048; i++)
            if (buf[b * 2048 + i] != expected(first + b, i, zeros))
                return 0;
    return 1;
}
'''

BLOCK_DEVICE = r'''
/* A block device: whole 2048-byte sectors of the image file. Like bd_defrag, a read that runs past
   the file's last sector fills what it can and then fails. inject > 0 fails (and poisons) that many calls. */
static int inject;
int DeviceReadSectors(u64 lsn, void *buffer, unsigned int sectors)
{
    u32 physical = (imageSize + 2047) / 2048;
    u8 *out = buffer;

    if (inject > 0) {
        inject--;
        memset(buffer, 0xEE, sectors * 2048);
        return SCECdErREAD;
    }
    for (unsigned int i = 0; i < sectors; i++, lsn++, out += 2048) {
        if (lsn >= physical)
            return SCECdErREAD;
        memcpy(out, image + lsn * 2048, 2048);
    }
    return SCECdErNO;
}
'''

SMB_DEVICE = r'''
#define SMB_DEVICE 1
#define CLIENT_MAX_RECV_SIZE 8192
#define WAITIOSEMA(x) ((void)(x))
#define SIGNALIOSEMA(x) ((void)(x))
static int smb_io_sema;
static struct { struct { int NumParts; } common; u16 FIDs[4]; } cdvdman_settings = {{1}, {0}};

/* The server answers SMB1 READ_ANDX from the file: what it holds from the offset, up to the request,
   and zero bytes at or past its end (MS-CIFS 3.3.5.36). File 0 is the ZSO image; files 1 and 2 are
   the 1 GiB parts of a split image, generated rather than stored. inject > 0 fails (and poisons)
   that many calls. */
#define PART_BYTES (0x80000ull * 2048)
static int inject;
static u8 partByte(u16 FID, u64 off) { return (u8)(FID * 13 + (off >> 11) * 7 + off); }
static int smb_ReadAndX(u16 FID, u32 offsetlow, u32 offsethigh, void *readbuf, int nbytes)
{
    u64 off = ((u64)offsethigh << 32) | offsetlow;
    u64 size = FID == 0 ? imageSize : PART_BYTES;
    u8 *out = readbuf;

    if (inject > 0) {
        inject--;
        memset(readbuf, 0xEE, nbytes);
        return -5;
    }
    if (off >= size)
        return 0;
    if ((u64)nbytes > size - off)
        nbytes = (int)(size - off);
    for (int i = 0; i < nbytes; i++)
        out[i] = FID == 0 ? image[off + i] : partByte(FID, off + i);
    return nbytes;
}

@SMB@

static int partMatches(const u8 *buf, u16 FID, u32 lsn, u32 sectors)
{
    for (u64 i = 0; i < sectors * 2048ull; i++)
        if (buf[i] != partByte(FID, lsn * 2048ull + i))
            return 0;
    return 1;
}
'''

INGAME_MAIN = r'''
#define SCECdErNO 0x00
#define SCECdErREAD 0x30
#define SCECdErTRMOPN 0x31
#define SCECdErEOM 0x32
@CACHE_STATICS@

@DEVICE@

@FUNCTIONS@

static u8 buf[16 * 2048];
static void cacheOn(u8 size)
{
    static u8 *window;
    free(window);
    window = size ? malloc(size * 2048) : NULL;
    sector_cache = window;
    MAX_SECTOR_CACHE = size;
    cur_sector = 0xffffffffffffffff;
}

int main(void)
{
    const u32 blocks = 40;
    buildImage(blocks, 0);
    assert(imageSize % 2048); /* the image ends inside its last sector, as most ZSO files do */

    for (int cached = 0; cached < 2; cached++) {
        cacheOn(cached ? 8 : 0);
        ziso_idx_start_block = -1;
        int ok = 1;
        for (u32 lsn = 0; lsn < blocks; lsn += 3) {
            u32 n = blocks - lsn < 3 ? blocks - lsn : 3;
            memset(buf, 0, sizeof(buf));
            ok &= DeviceReadSectorsCompressed(lsn, buf, n) == SCECdErNO && matches(buf, lsn, n, 0);
        }
        CHECK(ok, cached ? "cached: every sector decodes" : "uncached: every sector decodes");
        CHECK(DeviceReadSectorsCompressed(blocks, buf, 1) == SCECdErEOM, "a sector past the image is still end-of-media");

        /* A cache window wider than what is left of the file fails past its last sector only. */
        ziso_idx_start_block = -1;
        cur_sector = 0xffffffffffffffff;
        memset(buf, 0, sizeof(buf));
        CHECK(DeviceReadSectorsCompressed(blocks - 1, buf, 1) == SCECdErNO && matches(buf, blocks - 1, 1, 0),
              "the last sector still reads when the cache window runs past the end of the image");

        /* Persistent device failure: an error, never a sector. */
        ziso_idx_start_block = -1;
        cur_sector = 0xffffffffffffffff;
        inject = 1000;
        CHECK(DeviceReadSectorsCompressed(5, buf, 2) == SCECdErREAD, "a failing device must report SCECdErREAD");
        inject = 0;
        CHECK(DeviceReadSectorsCompressed(5, buf, 2) == SCECdErNO && matches(buf, 5, 2, 0),
              "the read after a failed index read decodes from a fresh index, not a poisoned one");

        /* One-shot failure of the index read on a fresh reader. */
        ziso_idx_start_block = -1;
        inject = 1;
        CHECK(DeviceReadSectorsCompressed(9, buf, 1) != SCECdErNO, "a failed index read is not success");
        CHECK(DeviceReadSectorsCompressed(9, buf, 1) == SCECdErNO && matches(buf, 9, 1, 0),
              "the retry after a failed index read returns the right sector");

        /* Persistent failure of the data read while the index is cached: through the cache when it is on. */
        CHECK(DeviceReadSectorsCompressed(10, buf, 1) == SCECdErNO, "index cached");
        cur_sector = 0xffffffffffffffff;
        inject = 1000;
        CHECK(DeviceReadSectorsCompressed(11, buf, 1) == SCECdErREAD, "a failing device must report SCECdErREAD for a data read");
        inject = 0;

        /* One-shot failure of the data read while the index is cached. */
        cur_sector = 0xffffffffffffffff;
        inject = 1;
        int r = DeviceReadSectorsCompressed(11, buf, 1);
        if (cached) {
            /* The failed window fill is retried as a direct read of just the request. */
            CHECK(r == SCECdErNO && matches(buf, 11, 1, 0), "cached: a failed window fill falls back to a direct read");
            memset(buf, 0, sizeof(buf));
            CHECK(DeviceReadSectorsCompressed(12, buf, 1) == SCECdErNO && matches(buf, 12, 1, 0),
                  "cached: a failed window is never served on the next hit");
        } else {
            CHECK(r == SCECdErREAD, "uncached: a failed data read must report SCECdErREAD");
            CHECK(DeviceReadSectorsCompressed(11, buf, 1) == SCECdErNO && matches(buf, 11, 1, 0),
                  "uncached: the retry returns the right sector");
        }

        /* A valid window, then a tail read whose window fill fails past the end of the image and
           overwrites part of the cache: a later read inside the old window must not be served from it. */
        cur_sector = 0xffffffffffffffff;
        CHECK(DeviceReadSectorsCompressed(20, buf, 1) == SCECdErNO && matches(buf, 20, 1, 0), "a window at sector 20");
        CHECK(DeviceReadSectorsCompressed(blocks - 2, buf, 1) == SCECdErNO && matches(buf, blocks - 2, 1, 0),
              "a tail read after it");
        memset(buf, 0, sizeof(buf));
        CHECK(DeviceReadSectorsCompressed(21, buf, 1) == SCECdErNO && matches(buf, 21, 1, 0),
              "a window overwritten by a failed fill is never served again");
    }

#ifdef SMB_DEVICE
    /* The ZSO file ends inside its last sector: that sector reads, padded with zeros (image[] is zero
       past imageSize). A read that starts at the end of the file, or runs a whole sector past it, fails. */
    u32 last = imageSize / 2048;
    memset(buf, 0xAA, sizeof(buf));
    CHECK(DeviceReadSectors(last, buf, 1) == SCECdErNO && !memcmp(buf, image + last * 2048, 2048),
          "SMB: the last, partial sector of the file reads, padded with zeros");
    CHECK(DeviceReadSectors(last + 1, buf, 1) == SCECdErREAD, "SMB: a sector past the end of the file fails");
    CHECK(DeviceReadSectors(last - 1, buf, 3) == SCECdErREAD, "SMB: a read a whole sector past the end of the file fails");
    inject = 1;
    CHECK(DeviceReadSectors(0, buf, 1) == SCECdErREAD, "SMB: a failed READ_ANDX fails the read");
    inject = 0;

    /* A split (ul.*) image in two 1 GiB parts: a read that ends exactly at the part boundary, and one that crosses it. */
    cdvdman_settings.common.NumParts = 2;
    cdvdman_settings.FIDs[0] = 1;
    cdvdman_settings.FIDs[1] = 2;
    CHECK(DeviceReadSectors(0x7FFF8, buf, 8) == SCECdErNO && partMatches(buf, 1, 0x7FFF8, 8),
          "SMB split image: a read that ends exactly at a part boundary");
    CHECK(DeviceReadSectors(0x7FFF8, buf, 16) == SCECdErNO && partMatches(buf, 1, 0x7FFF8, 8) && partMatches(buf + 8 * 2048, 2, 0, 8),
          "SMB split image: a read across a part boundary");
#endif

    if (failures)
        return 1;
    puts("in-game ZSO reader: device errors are reported, caches recover, tail reads still work");
    return 0;
}
'''

MENU_MAIN = r'''
int probed_fd = -1;
u32 probed_lba = 0;
#define HDD_BASE 1000

/* HDD: 512-byte sectors of the image starting at HDD_BASE. inject > 0 fails that many calls;
   failAt > 0 fails exactly the failAt-th call. fileShort > 0 cuts the next read() to that many bytes. */
static int inject, failAt, hddCalls, fileFail;
static u32 filePos, fileShort;
static int hddReadSectors(u32 lba, u32 nsectors, void *buf)
{
    assert(nsectors == 1 && lba >= HDD_BASE);
    hddCalls++;
    if (inject > 0 || hddCalls == failAt) {
        if (inject > 0)
            inject--;
        memset(buf, 0xEE, 512);
        return -1;
    }
    u32 off = (lba - HDD_BASE) * 512;
    memset(buf, 0, 512);
    if (off < imageSize)
        memcpy(buf, image + off, imageSize - off < 512 ? imageSize - off : 512);
    return 0;
}
static int lseek(int fd, unsigned int offset, int whence)
{
    assert(fd == probed_fd);
    filePos = whence == SEEK_SET ? offset : filePos + offset;
    return (int)filePos;
}
static int read(int fd, void *out, unsigned int bytes)
{
    assert(fd == probed_fd);
    if (fileFail)
        return -1;
    u32 left = filePos < imageSize ? imageSize - filePos : 0;
    u32 n = bytes < left ? bytes : left;
    if (fileShort && n > fileShort)
        n = fileShort;
    fileShort = 0;
    memcpy(out, image + filePos, n);
    filePos += n;
    return (int)n;
}

@FUNCTIONS@

static u8 buf[16 * 2048];
int main(void)
{
    buildImage(40, 0);
    probed_fd = 0;
    probed_lba = HDD_BASE;

    CHECK(ziso_read_sector(buf, 16, 1) == 1 && matches(buf, 16, 1, 0), "HDD: sector 16 decodes");
    inject = 1000;
    CHECK(ziso_read_sector(buf, 17, 1) != 1, "HDD: a failing disk must not return a sector");
    inject = 0;
    CHECK(ziso_read_sector(buf, 17, 1) == 1 && matches(buf, 17, 1, 0), "HDD: the retry returns the right sector");

    ziso_idx_start_block = -1;
    inject = 1;
    CHECK(ziso_read_sector(buf, 16, 1) != 1, "HDD: a failed index read is not success");
    CHECK(ziso_read_sector(buf, 16, 1) == 1 && matches(buf, 16, 1, 0), "HDD: the retry rebuilds the index");

    hddCalls = 0;
    failAt = 3; /* one 512-byte sector in the middle of the data read */
    CHECK(ziso_read_sector(buf, 20, 2) != 2, "HDD: one failed 512-byte sector fails the whole read");
    failAt = 0;
    CHECK(ziso_read_sector(buf, 20, 2) == 2 && matches(buf, 20, 2, 0), "HDD: the retry returns the right sectors");

    /* File-backed probe (fd 3): a failed read() is an error. */
    probed_fd = 3;
    probed_lba = 0;
    ziso_idx_start_block = -1;
    fileFail = 1;
    CHECK(ziso_read_sector(buf, 16, 1) != 1, "file: a failed read() must not return a sector");
    fileFail = 0;
    CHECK(ziso_read_sector(buf, 16, 1) == 1 && matches(buf, 16, 1, 0), "file: the retry returns the right sector");

    /* A short index read(): only the entries it returned are used, never what an earlier window left
       in the rest of the cache. */
    ziso_idx_start_block = -1;
    fileShort = 4; /* one entry; a sector needs two */
    CHECK(ziso_read_sector(buf, 16, 1) == -1, "file: an index read too short for the request is a failed read");
    CHECK(ziso_read_sector(buf, 16, 1) == 1 && matches(buf, 16, 1, 0), "file: the retry reads a whole index");
    ziso_idx_start_block = -1;
    CHECK(ziso_read_sector(buf, 15, 1) == 1 && matches(buf, 15, 1, 0), "file: an index window at sector 15");
    ziso_idx_start_block = -1;
    fileShort = 8; /* exactly the two entries sector 16 needs; the rest still holds the window at 15 */
    CHECK(ziso_read_sector(buf, 16, 1) == 1 && matches(buf, 16, 1, 0), "file: a short index read that covers the request decodes");
    memset(buf, 0xAA, sizeof(buf));
    CHECK(ziso_read_sector(buf, 17, 1) == 1 && matches(buf, 17, 1, 0), "file: the next sector re-reads the index past the short read");

    /* A tiny compressed image: the index read ends early at EOF but holds every entry needed. */
    buildImage(3, 1);
    memset(buf, 0xAA, sizeof(buf));
    CHECK(ziso_read_sector(buf, 0, 3) == 3 && matches(buf, 0, 3, 1), "tiny image: all sectors decode in one read");
    CHECK(ziso_read_sector(buf, 2, 1) == 1 && matches(buf, 2, 1, 1), "tiny image: the last sector decodes");
    CHECK(ziso_read_sector(buf, 1, 1) == 1 && matches(buf, 1, 1, 1), "tiny image: a cached index entry decodes");

    if (failures)
        return 1;
    puts("menu ZSO reader: HDD and file read errors are reported, retries recover, short index reads are not trusted");
    return 0;
}
'''

failed = False
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    (temp / 'tamtypes.h').write_text(TAMTYPES)
    lz4 = temp / 'lz4.o'
    subprocess.run(['gcc', '-std=gnu99', '-O1', '-w', '-I', str(temp), '-c', str(ROOT / 'modules/isofs/lz4.c'),
                    '-o', str(lz4)], check=True)
    ingame = INGAME_MAIN.replace('@CACHE_STATICS@', cache_statics).replace('@FUNCTIONS@', INGAME)
    for name, program in (('ingame, block device', ingame.replace('@DEVICE@', BLOCK_DEVICE)),
                          ('ingame, SMB', ingame.replace('@DEVICE@', SMB_DEVICE.replace('@SMB@', SMB))),
                          ('menu', MENU_MAIN.replace('@FUNCTIONS@', MENU))):
        stem = re.sub(r'\W+', '_', name)
        c, exe = temp / (stem + '.c'), temp / (stem + '.exe')
        c.write_text(COMMON + program)
        subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
                        '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast', '-Wno-unused-function', '-Wno-unused-parameter',
                        '-I', str(temp), '-I', str(ROOT / 'modules/isofs'), str(c), str(lz4), '-o', str(exe)],
                       check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        sys.stdout.write('[%s] %s%s' % (name, run.stdout, run.stderr))
        failed |= run.returncode != 0
sys.exit(1 if failed else 0)
