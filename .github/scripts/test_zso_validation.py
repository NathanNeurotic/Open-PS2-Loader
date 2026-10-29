#!/usr/bin/env python3
"""ZSO headers the reader cannot read are refused, a corrupt index never places data outside the
buffer, and reads larger than the index cache go in slices (belomaxorka/YAOPL 0253f98b, 9ad4afeb,
147e2493, 4baf5921).

Compiles the real ziso_init()/ziso_read_sector() and LZ4 decoder, with AddressSanitizer when the
host compiler has it, against an in-memory image. Checks: align above 11 and block sizes other
than 2048 are refused (both used to be read: a divide by zero, and a 16 KiB block decoded into a
2 KiB buffer); an index whose offsets go backwards, or whose blocks are larger than the sectors
they decode to, gives a failed read; reads of 256+ sectors return the right data (they used to
fail every time); a device failure in a later slice is a read error, not a short read. Every
ziso_init() call site uses its result.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP = (ROOT / 'src/platform/util.cpp').exists()

TAMTYPES = r'''
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;
'''

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zso.c"

void *ziso_alloc(u32 size) { void *p = NULL; return posix_memalign(&p, 64, size) ? NULL : p; }

#define BLOCKS 700
static u8 image[sizeof(ZISO_header) + (BLOCKS + 1) * 4 + BLOCKS * 2048];
static u32 imageSize;
static int failAfter = -1; /* fail every device read after this many (-1: never) */
static int reads, failures;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); failures++; } } while (0)

int read_raw_data(u8 *addr, u32 size, u32 offset, u32 shift)
{
    unsigned long long at = (unsigned long long)offset << shift;
    if (failAfter >= 0 && reads++ >= failAfter)
        return -1;
    if (at >= imageSize)
        return 0;
    if (at + size > imageSize)
        size = imageSize - (u32)at;
    memcpy(addr, image + at, size);
    return (int)size;
}

static u8 expected(u32 block, u32 byte) { return (u8)(block * 31 + byte * 7 + 1); }
static u32 *index_(void) { return (u32 *)(image + sizeof(ZISO_header)); }

/* Raw (top bit set) patterned blocks. */
static int build(u8 align, u32 blockSize)
{
    ZISO_header h = {ZSO_MAGIC, sizeof(ZISO_header), (u64)BLOCKS * 2048, blockSize, 1, align, {0, 0}};
    u32 pos = sizeof(h) + (BLOCKS + 1) * 4;

    memset(image, 0, sizeof(image));
    memcpy(image, &h, sizeof(h));
    for (u32 b = 0; b < BLOCKS; b++) {
        index_()[b] = pos | 0x80000000;
        for (u32 i = 0; i < 2048; i++)
            image[pos + i] = expected(b, i);
        pos += 2048;
    }
    index_()[BLOCKS] = pos;
    imageSize = pos;
    failAfter = -1;
    reads = 0;
    return ziso_init((ZISO_header *)image, index_()[0]);
}

static int matches(const u8 *buf, u32 first, u32 count)
{
    for (u32 b = 0; b < count; b++)
        for (u32 i = 0; i < 2048; i++)
            if (buf[b * 2048 + i] != expected(first + b, i))
                return 0;
    return 1;
}

int main(void)
{
    static u8 buf[BLOCKS * 2048];

    /* Headers */
    CHECK(build(12, 2048) == -1, "align 12 is refused");
    CHECK(build(255, 2048) == -1, "align 255 is refused");
    CHECK(build(0, 16384) == -1, "16 KiB blocks are refused");
    CHECK(build(0, 0) == -1, "block size 0 is refused");
    CHECK(build(0, 2048) == 0, "align 0, 2048-byte blocks are read");
    CHECK(build(11, 2048) == 0, "align 11 is accepted");

    /* Large reads go in slices */
    build(0, 2048);
    memset(buf, 0, sizeof(buf));
    CHECK(ziso_read_sector(buf, 100, 300) == 300 && matches(buf, 100, 300), "300 sectors from 100");
    CHECK(ziso_read_sector(buf, 0, BLOCKS) == BLOCKS && matches(buf, 0, BLOCKS), "the whole image in one read");
    CHECK(ziso_read_sector(buf, 600, 300) == 100 && matches(buf, 600, 100), "a large read past the end stops at it");
    CHECK(ziso_read_sector(buf, 5, 256) == 256 && matches(buf, 5, 256), "256 sectors");
    CHECK(ziso_read_sector(buf, 5, 257) == 257 && matches(buf, 5, 257), "257 sectors");

    /* A device failure in a later slice is a read error */
    build(0, 2048);
    failAfter = 2; /* first slice: index + data, then the second slice's index read fails */
    CHECK(ziso_read_sector(buf, 0, 400) == -1, "a failure in the second slice is a read error");
    failAfter = -1;
    CHECK(ziso_read_sector(buf, 0, 400) == 400 && matches(buf, 0, 400), "the next read recovers");

    /* A corrupt index */
    build(0, 2048);
    u32 t = index_()[3]; index_()[3] = index_()[4]; index_()[4] = t; /* offsets go backwards */
    memset(buf, 0, sizeof(buf));
    CHECK(ziso_read_sector(buf, 0, 2) == 2 && matches(buf, 0, 2), "sectors before the damage read");
    CHECK(ziso_read_sector(buf, 3, 1) == 0, "an index going backwards is a failed read");
    CHECK(ziso_read_sector(buf, 0, 10) == 0, "a read across it fails");
    build(0, 2048);
    index_()[11] = 0x00000010; /* end before start: a huge unsigned size */
    CHECK(ziso_read_sector(buf, 10, 1) == 0, "an end offset before the start is a failed read");
    build(0, 2048);
    index_()[21] = (index_()[20] & 0x7FFFFFFF) + 4096; /* block 20 claims 4 KiB */
    index_()[22] = index_()[21] + 2048;
    CHECK(ziso_read_sector(buf, 20, 1) == 0, "a block larger than the sector is a failed read");

    if (failures)
        return 1;
    puts("ZSO validation: headers, slices, device failures and corrupt indexes behave");
    return 0;
}
'''


def call_sites():
    files = ['modules/isofs/isofs.c', 'modules/iopcore/cdvdman/cdvdman.c']
    files += (['src/platform/util.cpp', 'src/sources/hddsupport.cpp', 'src/sources/supportbase.cpp'] if CPP
              else ['src/util.c', 'src/hddsupport.c', 'src/supportbase.c'])
    bad = []
    for rel in files:
        text = (ROOT / rel).read_text()
        calls = re.findall(r'[^\n]*\bziso_init\([^\n]*', text)
        if not calls:
            bad.append(rel + ': no ziso_init() call')
        for line in calls:
            if '== 0' not in line:
                bad.append(rel + ': ' + line.strip())
    header = (ROOT / 'modules/isofs/zso.h').read_text()
    if 'int ziso_init(ZISO_header *header, u32 first_block);' not in header:
        bad.append('zso.h: ziso_init() does not return int')
    return bad


def main():
    bad = call_sites()
    for line in bad:
        print('FAIL: ziso_init() result unused: ' + line)
    cc = shutil.which('gcc') or shutil.which('cc')
    if cc is None:
        print('SKIP: no host C compiler')
        return 1 if bad else 0
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / 'tamtypes.h').write_text(TAMTYPES)
        (temp / 'h.c').write_text(HARNESS)
        warn = ['-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-Wno-pointer-to-int-cast',
                '-Wno-int-to-pointer-cast', '-Wno-unused-function', '-Wno-unused-parameter']
        inc = ['-I', str(temp), '-I', str(ROOT / 'modules/isofs')]
        for san in (['-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []):
            built = subprocess.run([cc, '-std=gnu99', '-g', '-O1', '-w', *san, *inc, '-c',
                                    str(ROOT / 'modules/isofs/lz4.c'), '-o', str(temp / 'lz4.o')],
                                   capture_output=True, text=True)
            if built.returncode == 0:
                built = subprocess.run([cc, '-std=gnu99', '-g', '-O1', *san, *warn, *inc, str(temp / 'h.c'),
                                        str(temp / 'lz4.o'), '-o', str(temp / 'h')], capture_output=True, text=True)
            if built.returncode == 0:
                break
        if built.returncode != 0:
            print(built.stderr)
            return 1
        try:
            run = subprocess.run([str(temp / 'h')], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            print('FAIL: the reader did not finish')
            return 1
        sys.stdout.write(run.stdout + run.stderr[-3000:])
        return 1 if bad or run.returncode != 0 else 0


if __name__ == '__main__':
    sys.exit(main())
