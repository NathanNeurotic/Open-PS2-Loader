"""Fault-inject production buffered-file I/O to protect RiptOPL configuration saves.

Uses the real openFileBuffer/writeFileBuffer/closeFileBuffer function bodies (not a
reimplementation). The mocked filesystem applies O_TRUNC immediately on open, just
like the device drivers do. No PS2 environment is needed to cover these invariants.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
util = (ROOT / "src/util.c").read_text(encoding="utf-8")
util_header = (ROOT / "include/util.h").read_text(encoding="utf-8")
config = (ROOT / "src/config.c").read_text(encoding="utf-8")


def function(source, signature):
    start = source.index(signature)
    end = source.index("\n}\n", start) + 2
    return source[start:end]


def file_buffer_type(header):
    match = re.search(r"typedef struct\s*\{\s*int fd;.*?\}\s*file_buffer_t;", header, re.S)
    assert match, "file_buffer_t production definition not found"
    return match.group(0)


# Keep the existing memory-card single-open rule and failure recovery unmodified.
save = function(config, "int configWrite(config_set_t *configSet)")
assert "singleOpenDevice ? -1 : openFile" in save, "MC single-open policy changed"
assert "if (curLen < originalLen)" in save, "legacy recovery unexpectedly changed"
assert "memcmp(chunk, original + at, count)" not in save, "extra readback unexpectedly reintroduced"
assert 'if (!singleOpenDevice && strncmp(configSet->filename, "pfs", 3) != 0 &&' in save, "MC/PFS should not allocate a verification snapshot they never read"

HARNESS = r"""
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 2
#define O_TRUNC 4
#define SEEK_SET 0
#define SEEK_END 2

@STRUCT@

static char disk[256];
static int length, alloc_calls, alloc_failure, opens, closes, writes;
static int fail_open, fail_write, fail_close, fail_seek;

static void reset(void)
{
    memset(disk, 0, sizeof(disk));
    memcpy(disk, "OLD", 3);
    length = 3;
    alloc_calls = alloc_failure = opens = closes = writes = 0;
    fail_open = fail_write = fail_close = fail_seek = 0;
    errno = 0;
}

static int old_unchanged(void)
{
    return length == 3 && memcmp(disk, "OLD", 3) == 0;
}

static void *limited_malloc(size_t size)
{
    alloc_calls++;
    if (alloc_calls == alloc_failure)
        return NULL;
    return malloc(size);
}

static int fake_open(char *path, int flags)
{
    (void)path;
    opens++;
    if (fail_open) {
        errno = fail_open > 1 ? fail_open : ENXIO; // > 1: the raw value the driver hands back
        return -1;
    }
    if (flags & O_TRUNC)
        length = 0;
    return 3;
}

static int fake_read(int fd, void *buf, unsigned int size)
{
    (void)fd;
    if (size > (unsigned int)length)
        size = (unsigned int)length;
    memcpy(buf, disk, size);
    return (int)size;
}

static int fake_getFileSize(int fd)
{
    (void)fd;
    if (fail_seek) {
        errno = ENXIO;
        return -1;
    }
    return length;
}

static void *fake_memalign(size_t alignment, size_t size)
{
    (void)alignment;
    return malloc(size);
}

static int fake_lseek(int fd, int offset, int whence)
{
    (void)fd;
    (void)offset;
    (void)whence;
    return 0;
}

static int fake_write(int fd, const void *buf, unsigned int size)
{
    (void)fd;
    writes++;
    if (fail_write == 1) {
        errno = ENXIO;
        return -1;
    }
    if (fail_write == 2 && size > 0)
        size--;
    assert(length + (int)size < (int)sizeof(disk));
    memcpy(disk + length, buf, size);
    length += (int)size;
    return (int)size;
}

static int fake_close(int fd)
{
    (void)fd;
    closes++;
    if (fail_close) {
        errno = ENXIO;
        return -1;
    }
    return 0;
}

#define LOG(...) ((void)0)
#define getFileSize fake_getFileSize
#define memalign fake_memalign
#define malloc limited_malloc
#define openFile fake_open
#define read fake_read
#define lseek fake_lseek
#define write fake_write
#define close fake_close
@FUNCTIONS@
#undef close
#undef write
#undef lseek
#undef read
#undef openFile
#undef malloc
#undef memalign
#undef getFileSize
#undef LOG

int main(void)
{
    file_buffer_t *b;
    void *contents;
    int size;

    reset();
    alloc_failure = 1;
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b == NULL && errno == ENOMEM && opens == 0 && old_unchanged());

    reset();
    alloc_failure = 2;
    b = openFileBuffer("mc0:/OPL/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b == NULL && errno == ENOMEM && opens == 0 && old_unchanged());

    reset();
    fail_open = 1;
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b == NULL && errno == ENXIO && opens == 1 && old_unchanged());

    // bdmfs_fatfs leaks FR_NOT_ENABLED (12) for a mass slot with no mounted volume; it must not
    // reach the user as ENOMEM. The same 12 from a memory card is left alone.
    reset();
    fail_open = 12;
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b == NULL && errno == ENXIO && opens == 1 && old_unchanged());
    reset();
    fail_open = 12;
    b = openFileBuffer("mc0:/OPL/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b == NULL && errno == 12 && opens == 1);

    // Reads and non-truncating opens must fail fast without allocating
    // when the file cannot be opened (the historical read-path behavior).
    reset();
    fail_open = 1;
    b = openFileBuffer("mass0:/absent.cfg", O_RDONLY, 0, 8);
    assert(b == NULL && errno == ENXIO && opens == 1 && alloc_calls == 0);

    reset();
    fail_open = 1;
    b = openFileBuffer("mass0:/absent.cfg", O_WRONLY | O_CREAT, 0, 8);
    assert(b == NULL && errno == ENXIO && opens == 1 && alloc_calls == 0);

    reset();
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b && length == 0 && opens == 1);
    writeFileBuffer(b, "NEW", 3);
    assert(closeFileBuffer(b) == 0);
    assert(length == 3 && !memcmp(disk, "NEW", 3));

    reset();
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b);
    fail_write = 1;
    writeFileBuffer(b, "NEW", 3);
    assert(closeFileBuffer(b) == -1 && errno == ENXIO);

    reset();
    b = openFileBuffer("mc0:/OPL/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b);
    fail_write = 2;
    writeFileBuffer(b, "NEW", 3);
    assert(closeFileBuffer(b) == -1 && errno == EIO);

    reset();
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 8);
    assert(b);
    writeFileBuffer(b, "NEW", 3);
    fail_close = 1;
    assert(closeFileBuffer(b) == -1 && errno == ENXIO);

    // First buffered flush fails, second write and close succeed; don't lose
    // the original error just because the final close changed errno.
    reset();
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 4);
    assert(b);
    writeFileBuffer(b, "ABCD", 4);
    fail_write = 1;
    writeFileBuffer(b, "EF", 2);
    fail_write = 0;
    assert(closeFileBuffer(b) == -1 && errno == ENXIO);

    // Also cover a short POSITIVE write during the intermediate flush.
    reset();
    b = openFileBuffer("mass0:/settings.cfg", O_WRONLY | O_CREAT | O_TRUNC, 0, 4);
    assert(b);
    writeFileBuffer(b, "ABCD", 4);
    fail_write = 2;
    writeFileBuffer(b, "EF", 2);
    fail_write = 0;
    assert(closeFileBuffer(b) == -1 && errno == EIO);

    // Real readFile used by custom font loading: failed filesize must never
    // turn -1 into a huge unsigned allocation, and every opened fd is closed.
    reset();
    fail_seek = 1;
    size = -1;
    contents = readFile("mass0:/font.ttf", -1, &size);
    assert(contents == NULL && size == 0 && errno == ENXIO &&
           opens == 1 && closes == 1 && alloc_calls == 0);

    reset();
    alloc_failure = 1;
    size = -1;
    contents = readFile("mc0:/font.ttf", -1, &size);
    assert(contents == NULL && size == 0 && errno == ENOMEM &&
           opens == 1 && closes == 1);

    reset();
    size = -1;
    contents = readFile("mass0:/font.ttf", -1, &size);
    assert(contents != NULL && size == 3 && memcmp(contents, "OLD", 3) == 0);
    assert(opens == 1 && closes == 1);
    free(contents);

    reset();
    fail_open = 1;
    size = -1;
    contents = readFile("mass0:/missing.ttf", -1, &size);
    assert(contents == NULL && opens == 1 && closes == 0 && alloc_calls == 0);

    puts("PASS: config saves preserve files and errno; failed file reads never leak descriptors");
    return 0;
}
"""

c_code = HARNESS.replace("@STRUCT@", file_buffer_type(util_header))
c_code = c_code.replace("@FUNCTIONS@", "\n\n".join([
    function(util, "int bdmFatfsOpenErrno(const char *path, int err)"),
    function(util, "file_buffer_t *openFileBuffer(char *fpath, int mode, short allocResult, unsigned int size)"),
    function(util, "void writeFileBuffer(file_buffer_t *fileBuffer, char *inBuf, int size)"),
    function(util, "int closeFileBuffer(file_buffer_t *fileBuffer)"),
    function(util, "void *readFile(char *path, int align, int *size)"),
]))

with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / "config_save_integrity.c"
    binary = Path(folder) / ("config_save_integrity.exe" if os.name == "nt" else "config_save_integrity")
    source.write_text(c_code, encoding="utf-8")
    cc = os.environ.get("CC", "gcc")
    subprocess.run([cc, "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)

