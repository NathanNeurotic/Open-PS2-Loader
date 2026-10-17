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


# Verify the snapshot/recovery path is still available for BDM, and that a
# failed equal-length write compares bytes rather than guessing from the size.
save = function(config, "int configWrite(config_set_t *configSet)")
assert "singleOpenDevice ? -1 : openFile" in save, "MC single-open policy changed"
assert "memcmp(chunk, original + at, count)" in save, "lost equal-length corruption check"
assert "if (!intact)" in save, "lost restore-if-damaged gate"
assert "if (written == originalLen && closeResult == 0)" in save, "restore claims success on short write"

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
static int fail_open, fail_write, fail_close;

static void reset(void)
{
    memset(disk, 0, sizeof(disk));
    memcpy(disk, "OLD", 3);
    length = 3;
    alloc_calls = alloc_failure = opens = closes = writes = 0;
    fail_open = fail_write = fail_close = 0;
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
        errno = ENXIO;
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

int main(void)
{
    file_buffer_t *b;

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

    puts("PASS: config writes allocate before truncation and retain first I/O errno");
    return 0;
}
"""

c_code = HARNESS.replace("@STRUCT@", file_buffer_type(util_header))
c_code = c_code.replace("@FUNCTIONS@", "\n\n".join([
    function(util, "file_buffer_t *openFileBuffer(char *fpath, int mode, short allocResult, unsigned int size)"),
    function(util, "void writeFileBuffer(file_buffer_t *fileBuffer, char *inBuf, int size)"),
    function(util, "int closeFileBuffer(file_buffer_t *fileBuffer)"),
]))

with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / "config_save_integrity.c"
    binary = Path(folder) / ("config_save_integrity.exe" if os.name == "nt" else "config_save_integrity")
    source.write_text(c_code, encoding="utf-8")
    cc = os.environ.get("CC", "gcc")
    subprocess.run([cc, "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
