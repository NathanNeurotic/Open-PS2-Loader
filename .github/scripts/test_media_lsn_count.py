"""The media size handed to CDVDMAN (upstream OPL #1763) is exact or unknown, never a guess.

CDVDMAN refuses reads past settings->common.mediaLsnCount, and 0 tells it to keep the ISO9660 PVD
bound it used before #1763. So a count that is too small breaks valid reads, while 0 is always safe.

Compiles the real ProbeZISO and sbGetMediaLsnCount from src/supportbase.c against a fake file table:
a plain ISO, a ZSO (header count, not its compressed size), a ZSO whose header cannot be read, a
missing file and an unknown total all behave. Then checks the BDM, SMB and MMCE launchers pass 0
instead of a partial or unchecked total when a part cannot be opened or sized.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/supportbase.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function(src, signature):
    match = re.search(signature, src, re.M)
    if match is None:
        sys.exit('src/supportbase.c: %s not found' % signature)
    return src[match.start():src.index('\n}', match.start()) + 3]


probe = function(source, r'^static int ProbeZISO\(int fd\)\s*\{')
count = function(source, r'^u32 sbGetMediaLsnCount\(const char \*path, u64 totalBytes\)\s*\{')

# Every launcher that sums its parts must hand over "unknown" when any part was not measured. BDM
# aborts the launch on a part it cannot open, so only its seek can fail here; SMB and MMCE measure in
# a loop of their own, where an unopened part must count as unmeasured -- never be skipped.
SIZED = r'if \(partBytes > 0\)\n\s+isoTotalBytes \+= \(u64\)partBytes;\n\s+else\n\s+isoSizeKnown = 0;'
LOOPS = {
    'bdmsupport.c': r's64 partBytes = lseek64\(fd, 0, SEEK_END\);\n\s+' + SIZED,
    'ethsupport.c': (r'int fd = open\(partname, O_RDONLY, 0666\);\n\s+s64 partBytes = -1;\n\s+if \(fd >= 0\) \{\n'
                     r'\s+partBytes = lseek64\(fd, 0, SEEK_END\);\n\s+close\(fd\);\n\s+\}\n\s+' + SIZED),
}
LOOPS['mmcesupport.c'] = LOOPS['ethsupport.c']
for name, loop in LOOPS.items():
    text = (root / 'src' / name).read_text(encoding='utf-8').replace('\r\n', '\n')
    if 'sbGetMediaLsnCount(partname, isoSizeKnown ? isoTotalBytes : 0)' not in text:
        failures.append('%s: pass 0 to sbGetMediaLsnCount when the parts were not all measured' % name)
    if re.search(r'\+=\s*lseek64\(', text):
        failures.append('%s: a failed lseek64 (-1) added to the u64 total wraps it into a wrong bound' % name)
    if re.search(loop, text) is None:
        failures.append('%s: a part that cannot be opened or sized must mark the total unknown, not be skipped' % name)

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <strings.h>

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
#define O_RDONLY 0
#define SEEK_SET 0
#define ZSO_MAGIC 0x4F53495A
typedef struct {
    u32 magic;
    u32 header_size;
    u64 total_bytes;
    u32 block_size;
    u8 ver;
    u8 align;
    u8 rsv_06[2];
} ZISO_header;

static u32 ziso_total_block;
static int probed_fd;
static u32 probed_lba;
static void ziso_init(ZISO_header *header, u32 first_block)
{
    (void)first_block;
    ziso_total_block = (u32)(header->total_bytes >> 11);
}

/* The fake device: one file at a time, by name. */
static const char *fileName;
static unsigned char fileData[64];
static int fileSize, readFails, pos, openFiles;

static int fake_open(const char *path, int flags, int mode)
{
    (void)flags;
    (void)mode;
    if (fileName == NULL || strcmp(path, fileName) != 0)
        return -1;
    openFiles++;
    pos = 0;
    return 3;
}
static int fake_lseek(int fd, int offset, int whence)
{
    (void)fd;
    (void)whence;
    pos = offset;
    return pos;
}
static int fake_read(int fd, void *buf, int size)
{
    (void)fd;
    if (readFails)
        return -1;
    int n = (pos + size > fileSize) ? fileSize - pos : size;
    if (n < 0)
        n = 0;
    memcpy(buf, fileData + pos, n);
    pos += n;
    return n;
}
static int fake_close(int fd)
{
    (void)fd;
    openFiles--;
    return 0;
}
#define open fake_open
#define lseek fake_lseek
#define read fake_read
#define close fake_close

@PROBE@

@COUNT@

static void plainFile(const char *name)
{
    fileName = name;
    memset(fileData, 0, sizeof(fileData));
    fileSize = sizeof(fileData);
    readFails = 0;
}

static void zsoFile(const char *name, u64 imageBytes)
{
    ZISO_header header = {ZSO_MAGIC, 24, imageBytes, 2048, 1, 0, {0, 0}};
    plainFile(name);
    memcpy(fileData, &header, sizeof(header));
}

static int fails;
#define CHECK(cond, what) do { if (!(cond)) { printf("FAIL: %s\n", what); fails++; } } while (0)

int main(void)
{
    plainFile("mass0:/DVD/Game.iso");
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Game.iso", 1000ULL * 2048) == 1000, "a plain ISO is its measured size");
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Game.iso", 0) == 0, "an ISO whose parts were not all measured is unknown");

    plainFile("mass0:/ul.0A1B2C3D.SLUS_123.45.00");
    CHECK(sbGetMediaLsnCount("mass0:/ul.0A1B2C3D.SLUS_123.45.00", 7ULL * 2048) == 7, "split parts sum to the media size");

    zsoFile("mass0:/DVD/Game.zso", 5000ULL * 2048);
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Game.zso", 100ULL * 2048) == 5000,
          "a ZSO is its header's block count, not its compressed file size");

    zsoFile("mass0:/DVD/Renamed.iso", 4000ULL * 2048);
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Renamed.iso", 90ULL * 2048) == 4000, "a ZSO is found by its magic, whatever its name");

    zsoFile("mass0:/DVD/Game.zso", 5000ULL * 2048);
    readFails = 1;
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Game.zso", 100ULL * 2048) == 0,
          "a ZSO whose header cannot be read is unknown, not its compressed size");
    zsoFile("mass0:/DVD/GAME.ZSO", 5000ULL * 2048);
    readFails = 1;
    CHECK(sbGetMediaLsnCount("mass0:/DVD/GAME.ZSO", 100ULL * 2048) == 0, "the .zso test ignores case");

    zsoFile("mass0:/DVD/Empty.zso", 0);
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Empty.zso", 100ULL * 2048) == 0, "a ZSO header that reports 0 blocks stays unknown");

    fileName = NULL;
    CHECK(sbGetMediaLsnCount("mass0:/DVD/Gone.iso", 1000ULL * 2048) == 0, "a file that cannot be opened is unknown");

    CHECK(openFiles == 0, "every open is closed");
    return fails ? 1 : 0;
}
'''

if not failures:
    program = HARNESS.replace('@PROBE@', probe).replace('@COUNT@', count)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'medialsn.c'
        exe = Path(tmp) / ('medialsn' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            if run.returncode != 0:
                failures.extend(run.stdout.strip().splitlines() or ['harness exited %d' % run.returncode])

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('media size: exact (ISO, split parts, ZSO by header) or unknown (unread header, missing file, unmeasured part)')
