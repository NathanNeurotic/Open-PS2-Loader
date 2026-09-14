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
    memcpy(hdr + 0x16, "junk", 4); /* padding after the terminator is not part of the id */
    seal();
    assert(apaFenceWriteAllowed(0, 2, hdr, TOTAL));
    make_mbr(0x40000, 0x7FC0000);
    memcpy(hdr + 0x10, "__mb", 4);
    hdr[0x14] = 0;
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

    # A corrupt on-disk sub-partition count must never index past the 64-entry subs array.
    open_body = function_body(fio, 'static int apaOpen(')
    check(open_body is not None and re.search(r'nsub > APA_MAXSUB.*?return -EIO;.*?fileSlot->parts\[0\]', open_body, re.S),
          'hdd_fio.c: apaOpen no longer rejects an out-of-range sub-partition count before using it')
    stat_body = function_body(fio, 'static void fioGetStatFiller(')
    check(stat_body is not None and 'i < APA_MAXSUB' in stat_body,
          'hdd_fio.c: fioGetStatFiller walks subs[] without the APA_MAXSUB bound')
    remove_body = function_body(fio, 'static int apaRemove(')
    if remove_body is None:
        failures.append('hdd_fio.c: apaRemove not found')
    else:
        first_edit = remove_body.find('clink->header->nsub = 0;')
        proof = remove_body.find('sub->header->main == clink->header->start')
        check(first_edit != -1 and proof != -1 and proof < first_edit and 'nsub > APA_MAXSUB' in remove_body[:first_edit],
              'hdd_fio.c: apaRemove modifies the table before proving every sub-partition belongs to it')

    # The probe classifies a GPT/APA hybrid as GPT before it ever looks for an APA header.
    probe = function_body(text(root / 'src/hddsupport.c'), 'int hddDetectNonSonyFileSystem(')
    check(probe is not None and 0 <= probe.find('"EFI PART"') < probe.find('"APA", 3'),
          'hddsupport.c: the probe no longer classifies GPT/APA hybrids before the APA header check')


BD_HARNESS_PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define ATA_DIR_READ 0
static unsigned char disk_lba0[512];
static int reads, read_fails;
static int ata_device_sector_io64(int device, void *buf, u64 lba, u32 nsectors, int dir)
{
    (void)device;
    assert(dir == ATA_DIR_READ && lba == 0 && nsectors == 1);
    reads++;
    if (read_fails)
        return -5;
    memcpy(buf, disk_lba0, 512);
    return 0;
}
'''

BD_HARNESS_MAIN = r'''
int main(void)
{
    /* An APA disk: nothing below the first user partition, including the whole table sector. */
    memset(disk_lba0, 0, sizeof(disk_lba0));
    memcpy(disk_lba0 + 4, "APA", 4);
    assert(ata_bd_write_hits_apa_reserved(0, 0, 1));
    assert(ata_bd_write_hits_apa_reserved(0, 7, 1));
    assert(ata_bd_write_hits_apa_reserved(0, 0x3FFFF, 1));
    assert(ata_bd_write_hits_apa_reserved(0, 2048, 64));
    assert(!ata_bd_write_hits_apa_reserved(0, 0x40000, 1));
    assert(!ata_bd_write_hits_apa_reserved(0, 0x12345678, 8));

    /* A plain MBR/exFAT disk (or a superfloppy) keeps full write access. */
    memset(disk_lba0, 0, sizeof(disk_lba0));
    memcpy(disk_lba0 + 3, "EXFAT   ", 8);
    disk_lba0[510] = 0x55;
    disk_lba0[511] = 0xAA;
    assert(!ata_bd_write_hits_apa_reserved(0, 1, 1));
    assert(!ata_bd_write_hits_apa_reserved(0, 2048, 8));

    /* LBA 0 unreadable: the disk cannot be proven non-APA, so low writes are refused. */
    read_fails = 1;
    assert(ata_bd_write_hits_apa_reserved(0, 6, 1));

    /* Writes above the reserved area never pay for the probe read, and zero-length writes do nothing. */
    reads = 0;
    assert(!ata_bd_write_hits_apa_reserved(0, 0x40000, 1));
    assert(!ata_bd_write_hits_apa_reserved(0, 0, 0));
    assert(reads == 0);

    puts("bdm fence: all cases passed");
    return 0;
}
'''

RANGE_HARNESS_PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { u32 exists, has_packet, total_sectors, security_status, lba48, total_sectors_lba48; } ata_devinfo_t;
'''

RANGE_HARNESS_MAIN = r'''
int main(void)
{
    ata_devinfo_t small = {1, 0, 0x0FFFFFFF, 0, 0, 0x0FFFFFFF};   /* 137 GB, no LBA48 */
    ata_devinfo_t tiny = {1, 0, 1000000, 0, 0, 1000000};           /* no LBA48, exact size known */
    ata_devinfo_t big = {1, 0, 0x0FFFFFFF, 0, 1, 0x74706DB0};      /* 1 TB, LBA48 */
    ata_devinfo_t huge = {1, 0, 0x0FFFFFFF, 0, 1, 0xFFFFFFFF};     /* > 2 TiB: the u32 saturates */

    /* Without LBA48, a request that would wrap past 2^28 (or past the end) is refused. */
    assert(ata_request_in_range(&small, 0, 8));
    assert(ata_request_in_range(&small, 0x0FFFFFFE, 1));
    assert(!ata_request_in_range(&small, 0x0FFFFFFF, 1));
    assert(!ata_request_in_range(&small, 0x10000000, 1));
    assert(!ata_request_in_range(&small, 0x0FFFFF00, 0x200));
    assert(ata_request_in_range(&tiny, 999999, 1));
    assert(!ata_request_in_range(&tiny, 999999, 2));

    /* With LBA48 and a real capacity, the capacity is the limit. */
    assert(ata_request_in_range(&big, 0x74706DAF, 1));
    assert(!ata_request_in_range(&big, 0x74706DB0, 1));
    assert(!ata_request_in_range(&big, 0xFFFFFFFFFFFFull, 1));

    /* Past 2 TiB the reported capacity is saturated: stay usable beyond it, but never past 2^48. */
    assert(ata_request_in_range(&huge, 0x1FFFFFFFFull, 8));
    assert(ata_request_in_range(&huge, (1ull << 48) - 8, 8));
    assert(!ata_request_in_range(&huge, (1ull << 48) - 8, 9));
    assert(!ata_request_in_range(&huge, 0xFFFFFFFFFFFFFFFFull, 1));

    /* Zero-length requests do no I/O and are never refused. */
    assert(ata_request_in_range(&small, 0x20000000, 0));

    puts("ata range: all cases passed");
    return 0;
}
'''


def run_range_harness():
    atad = text(root / 'modules/hdd/atad/src/ps2atad.c')
    match = re.search(r'static int ata_request_in_range\(.*?\n\}\n', atad, re.S)
    if match is None:
        failures.append('ps2atad.c: the ATA addressable-range check is missing')
        return
    io_body = function_body(atad, 'int ata_device_sector_io64(')
    check(io_body is not None and 0 <= io_body.find('ata_request_in_range(') < io_body.find('while (res == 0'),
          'ps2atad.c: ata_device_sector_io64 no longer checks the addressable range before its first command')
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'range_test.c'
        exe = Path(tmp) / 'range_test'
        c_file.write_text(RANGE_HARNESS_PREFIX + match.group(0) + RANGE_HARNESS_MAIN)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(c_file), '-o', str(exe)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('ata range harness failed to compile:\n' + result.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('ata range harness failed:\n' + result.stdout + result.stderr)


def run_bd_harness():
    atad = text(root / 'modules/hdd/atad/src/ps2atad.c')
    check('lba += chunk;' in atad and 'nsectors -= chunk;' in atad,
          'ps2atad.c: the 65536-sector zero-progress loop fix (upstream f30f05eba) is gone')
    match = re.search(r'#define ATA_BD_APA_RESERVED_SECTORS[^\n]*\n\s*static int ata_bd_write_hits_apa_reserved\(.*?\n\}\n',
                      atad, re.S)
    if match is None:
        failures.append('ps2atad.c: the BDM APA reserved-area guard is missing')
        return
    write_body = function_body(atad, 'static int ata_bd_write(')
    check(write_body is not None and
          write_body.find('ata_bd_write_hits_apa_reserved(') != -1 and
          write_body.find('ata_bd_write_hits_apa_reserved(') < write_body.find('ATA_DIR_WRITE'),
          'ps2atad.c: ata_bd_write no longer checks the APA reserved area before writing')
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / 'bd_test.c'
        exe = Path(tmp) / 'bd_test'
        c_file.write_text(BD_HARNESS_PREFIX + match.group(0) + BD_HARNESS_MAIN)
        result = subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(c_file), '-o', str(exe)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append('bdm fence harness failed to compile:\n' + result.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append('bdm fence harness failed:\n' + result.stdout + result.stderr)


# hdd0:/hdd1: is the raw APA partition namespace, not a filesystem: there, mkdir/open(O_CREAT) means
# "create a partition" and remove means "delete one". Only the three files that own APA handling may
# spell it. Everything else reaches the HDD through the mounted pfs0: data home. (The driver refuses
# creation regardless; this keeps new code from even trying, as the RA launch log and the tar device
# table once did.)
RAW_APA_LITERAL = re.compile(r'"hdd(?:[0-9]|%[a-z])?:')
RAW_APA_ALLOWED = {'src/hdd.c', 'src/hddsupport.c', 'src/opl.c'}


def check_raw_apa_namespace():
    for directory in ('src', 'ee_core/src', 'include'):
        for path in sorted((root / directory).rglob('*.[ch]')):
            rel = path.relative_to(root).as_posix()
            source = text(path)
            if rel not in RAW_APA_ALLOWED:
                for number, line in enumerate(source.split('\n'), 1):
                    if RAW_APA_LITERAL.search(line):
                        failures.append('%s:%d spells the raw APA namespace (use the pfs0: data home): %s'
                                        % (rel, number, line.strip()))
            if re.search(r'\bfileXioFormat\s*\(', source):
                failures.append('%s calls fileXioFormat; the loader never formats a drive' % rel)


run_fence_harness()
check_driver_policy()
run_bd_harness()
run_range_harness()
check_raw_apa_namespace()

if failures:
    print('\nAPA table safety checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('APA table safety: fence and driver policy OK')
