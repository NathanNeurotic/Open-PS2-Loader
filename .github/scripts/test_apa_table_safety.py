"""APA table safety: exercise the production write fence and pin the driver's write policy.

Part 1 compiles modules/hdd/apa/src/table_fence.h -- the exact header the IOP driver uses -- on the
host and drives it with real __mbr and partition headers.

Part 2 statically checks the vendored driver still refuses every partition-table edit the loader
never performs, so a careless re-vendor from ps2sdk cannot silently drop the protection. These are
text checks on purpose: the policy lives in a handful of well-known functions.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
apa = root / 'modules/hdd/apa'
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#include "table_fence.h"

static unsigned char hdr[1024];

static void put32(unsigned int ofs, u32 v)
{
    hdr[ofs] = v & 0xff;
    hdr[ofs + 1] = (v >> 8) & 0xff;
    hdr[ofs + 2] = (v >> 16) & 0xff;
    hdr[ofs + 3] = (v >> 24) & 0xff;
}

static void seal(void)
{
    u32 sum = 0;
    unsigned int i;
    for (i = 1; i < 256; i++)
        sum += apaFenceWord(hdr, i * 4);
    put32(0, sum);
}

static void make_mbr(u32 next, u32 prev)
{
    memset(hdr, 0, sizeof(hdr));
    put32(0x04, 0x00415041);
    put32(0x08, next);
    put32(0x0C, prev);
    memcpy(hdr + 0x10, "__mbr", 5);
    put32(0x40, 0);
    put32(0x44, 0x40000);
    put32(0x48, 0x0001);
    memcpy(hdr + 0x100, "Sony Computer Entertainment Inc.", 32);
    put32(0x120, 2);
    seal();
}

static void make_partition(const char *id, u32 start)
{
    memset(hdr, 0, sizeof(hdr));
    put32(0x04, 0x00415041);
    memcpy(hdr + 0x10, id, strlen(id));
    put32(0x40, start);
    put32(0x44, 0x40000);
    put32(0x48, 0x0100);
    seal();
}

#define TOTAL 0x08000000u

int main(void)
{
    /* A legitimate table edit: a whole, checksummed __mbr header at LBA 0. */
    make_mbr(0x40000, 0x7FC0000);
    assert(apaFenceIsValidMbrHeader(hdr, TOTAL));
    assert(apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    assert(apaFenceWriteAllowed(0, 2, hdr, 0)); /* capacity unknown: links are not range-checked */

    /* ...but not a partial one, an oversized one, or none at all. */
    assert(!apaFenceWriteAllowed(0, 1, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(0, 3, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(0, 8, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(0, 2, 0, TOTAL));

    /* A valid header shifted into the table sector is still a misdirected write. */
    assert(!apaFenceWriteAllowed(1, 2, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(6, 2, hdr, TOTAL));

    /* Every field the driver itself validates, and every formatter invariant, is enforced. */
    make_mbr(0x40000, 0x7FC0000);
    hdr[0x200] = 1; /* payload changed after sealing: checksum no longer matches */
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    put32(0x04, 0x00415042);
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    hdr[0x100] = 'X';
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    memcpy(hdr + 0x10, "__mbrX", 6);
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    put32(0x40, 0x40000);
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    put32(0x48, 0x0100);
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    put32(0x4C, 1);
    seal();
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(TOTAL, 0x7FC0000);
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, TOTAL + 5);
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));

    /* A real partition's header can never land at LBA 0. */
    make_partition("+OPL", 0x40000);
    assert(!apaFenceWriteAllowed(0, 2, hdr, TOTAL));

    /* The SDK error records (LBA 6 and 7) and anything else in the physical sector are refused. */
    memset(hdr, 0, sizeof(hdr));
    put32(0, 0x12345678);
    assert(!apaFenceWriteAllowed(6, 1, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(7, 1, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(2, 4, hdr, TOTAL));
    assert(!apaFenceWriteAllowed(7, 2, hdr, TOTAL)); /* straddles the boundary */

    /* Outside the physical sector: the journal, partition headers and data all pass untouched. */
    assert(apaFenceWriteAllowed(8, 1, hdr, TOTAL));
    assert(apaFenceWriteAllowed(10, 2, hdr, TOTAL));
    assert(apaFenceWriteAllowed(0x40000, 2, hdr, TOTAL));
    assert(apaFenceWriteAllowed(3, 0, hdr, TOTAL)); /* zero-length: no I/O happens */

    /* HDIOC_WRITESECTOR: an absolute EE-supplied LBA. Only above the __mbr partition, in range. */
    assert(!apaFenceRawWriteAllowed(0, 2, TOTAL));
    assert(!apaFenceRawWriteAllowed(6, 1, TOTAL));
    assert(!apaFenceRawWriteAllowed(0x3FFFF, 2, TOTAL));
    assert(apaFenceRawWriteAllowed(0x40000, 2, TOTAL));
    assert(apaFenceRawWriteAllowed(0x40000 + 0x808, 2, TOTAL));
    assert(!apaFenceRawWriteAllowed(TOTAL - 1, 2, TOTAL));
    assert(!apaFenceRawWriteAllowed(TOTAL, 1, TOTAL));
    assert(!apaFenceRawWriteAllowed(0xFFFFFFFFu, 2, TOTAL));
    assert(apaFenceRawWriteAllowed(0xFFFFFFF0u, 2, 0)); /* capacity unknown: floor still applies */
    assert(apaFenceRawWriteAllowed(5, 0, TOTAL));

    puts("fence: all cases passed");
    return 0;
}
'''


def run_fence_harness():
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'fence_test.c'
        exe = Path(tmp) / 'fence_test'
        c_file.write_text(HARNESS)
        compile_cmd = ['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-I', str(apa / 'src'),
                       str(c_file), '-o', str(exe)]
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('fence harness failed to compile:\n' + result.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('fence harness failed:\n' + result.stdout + result.stderr)


def text(path):
    # Windows checkouts carry CRLF; the checks below match on LF.
    return path.read_text().replace('\r\n', '\n')


def function_body(source, signature):
    # Definitions only (a prototype ends in ';'); parameter lists may wrap onto several lines.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        return None
    end = source.index('\n}', match.start())
    return source[match.start():end]


def case_body(source, function_signature, case_label):
    body = function_body(source, function_signature)
    if body is None:
        return None
    # The live dispatch starts under fioSema; skip the APA_SUPPORT_BHDD pre-filter above it, which
    # also lists these labels.
    live = body.find('WaitSema(fioSema);')
    if live < 0:
        return None
    match = re.search(r'case ' + case_label + r':(.*?)break;', body[live:], re.S)
    return match.group(1) if match else None


def check_driver_policy():
    fio = text(apa / 'src/hdd_fio.c')
    apa_c = text(apa / 'src/apa.c')
    blkio = text(apa / 'src/hdd_blkio.h')
    fence_c = text(apa / 'src/table_fence.c')
    makefile = text(apa / 'Makefile')
    top_makefile = text(root / 'Makefile')

    check('table_fence.o' in makefile, 'modules/hdd/apa/Makefile no longer builds table_fence.o')
    check(re.search(r'static inline int blkIoDmaTransfer\([^)]*\)\s*\{\s*return apaFencedDmaTransfer\(', blkio),
          'hdd_blkio.h: blkIoDmaTransfer no longer routes through the fence')
    check('apaFenceWriteAllowed' in fence_c and 'sceAtaDmaTransfer' in fence_c,
          'table_fence.c: fenced transfer is missing its check or its transfer')
    check(re.search(r'modules/hdd/apa/ps2hdd-osd\.irx', top_makefile) and
          not re.search(r'ps2hdd\.c:\s*\$\(PS2SDK\)', top_makefile),
          'top-level Makefile embeds the SDK prebuilt ps2hdd-osd.irx instead of the fenced build')

    save_error = function_body(apa_c, 'void apaSaveError(')
    check(save_error is not None and 'blkIoDmaTransfer' not in save_error and 'blkIoFlushCache' not in save_error,
          'apa.c: apaSaveError writes error records again')
    set_part = function_body(apa_c, 'void apaSetPartErrorSector(')
    check(set_part is not None and 'apaCacheAlloc' not in set_part,
          'apa.c: apaSetPartErrorSector allocates again (NULL dereference on an exhausted cache)')

    fmt = function_body(fio, 'int hddFormat(')
    check(fmt is not None and re.search(r'return -EACCES;.*clear all errors', fmt, re.S),
          'hdd_fio.c: hddFormat no longer refuses before its first write')
    open_body = function_body(fio, 'static int apaOpen(')
    check(open_body is not None and 'hddAddPartitionHere(' not in open_body and 'rv = -EACCES' in open_body,
          'hdd_fio.c: apaOpen can create partitions again')
    for label in ('HIOCADDSUB', 'HIOCDELSUB'):
        body = case_body(fio, 'int hddIoctl2(', label)
        check(body is not None and '-EACCES' in body and 'ioctl2' not in body,
              'hdd_fio.c: %s is reachable again' % label)
    for label in ('HDIOC_SWAPTMP', 'HDIOC_SETOSDMBR'):
        body = case_body(fio, 'int hddDevctl(', label)
        check(body is not None and '-EACCES' in body and 'devctl' not in body,
              'hdd_fio.c: %s is reachable again' % label)
    body = case_body(fio, 'int hddDevctl(', 'HDIOC_WRITESECTOR')
    check(body is not None and 'apaFenceRawWriteAllowed' in body,
          'hdd_fio.c: HDIOC_WRITESECTOR lost its raw LBA bound')
    transfer = function_body(fio, 'static int ioctl2Transfer(')
    check(transfer is not None and 'arg->sector + arg->size' not in transfer,
          'hdd_fio.c: ioctl2Transfer bounds check can wrap again')


run_fence_harness()
check_driver_policy()

if failures:
    print('\nAPA table safety checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('APA table safety: fence and driver policy OK')
