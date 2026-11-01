"""A settings file that is not there is opened once, not twice.

configRead() and its fallbacks (wOPL name, legacy name, carry-over home) each try a path with the
single-shot reader and then the buffered reader. Both start with the same openFile(path, O_RDONLY), so
on a missing file the second open could only fail again. On an MMCE every failed open is a round trip
over SIO2, and a settings load from mmce0 makes many of them.

This compiles the real configOpenSingleShot() and configOpenForRead() (src/config.c) on the host
against a counting openFile() and checks:

- a missing file (the device says ENOENT): exactly one open, NULL result;
- a first open that fails for another reason (EIO: a timeout or a busy bus) and then succeeds: the
  buffered reader retries and reads the file;
- a small file: one open, read single-shot, the buffered reader is not used;
- an oversized file (> 4 KB): the single-shot path gives up and the buffered reader still opens it;
- every read-only open in configRead() and configOpenCarryOver() goes through configOpenForRead.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'src/config.c').read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise SystemExit(f'unterminated {signature}')


single = function_text(src, 'static file_buffer_t *configOpenSingleShot(const char *path, int *missing)')
for_read = function_text(src, 'static file_buffer_t *configOpenForRead(const char *path)')

# Static check: no read-only fallback pair is left that opens the same path twice.
read_fn = function_text(src, 'int configRead(config_set_t *configSet)')
carry = function_text(src, 'static file_buffer_t *configOpenCarryOver(const char *name)')
failures = []
for name, body in (('configRead', read_fn), ('configOpenCarryOver', carry)):
    if re.search(r'openFileBuffer\([^;]*O_RDONLY', body):
        failures.append(f'{name} still calls openFileBuffer(..., O_RDONLY) directly')
    if 'configOpenSingleShot(' in body:
        failures.append(f'{name} still calls configOpenSingleShot directly')
    if 'configOpenForRead(' not in body:
        failures.append(f'{name} does not use configOpenForRead')

program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define O_RDONLY 0
typedef struct { int size; } file_buffer_t;

static int opens, bufferedOpens, fileExists, fileSize, failFirstWith;
static int openFile(char *path, int mode)
{
    (void)path; (void)mode;
    opens++;
    if (opens == 1 && failFirstWith) { errno = failFirstWith; return -1; }
    if (!fileExists) { errno = ENOENT; return -1; }
    return 3;
}
static int getFileSize(int fd) { (void)fd; return fileSize; }
static int read(int fd, void *buf, int n) { (void)fd; memset(buf, 'a', n); return n; }
static int close(int fd) { (void)fd; return 0; }
static file_buffer_t storeSingle, storeBuffered;
static file_buffer_t *openFileBufferBuffer(short a, const void *b, unsigned int n) { (void)a; (void)b; storeSingle.size = n; return &storeSingle; }
static file_buffer_t *openFileBuffer(char *p, int mode, short a, unsigned int s)
{
    (void)a; (void)s; (void)mode;
    bufferedOpens++;
    if (openFile(p, O_RDONLY) < 0)
        return NULL;
    storeBuffered.size = fileSize;
    return &storeBuffered;
}

@SINGLE@
@FOR_READ@

static int failures;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); failures++; } } while (0)

int main()
{
    char path[] = "mmce0:/APP_RIPTOPL/settings_riptopl.cfg";
    file_buffer_t *fb;

    opens = bufferedOpens = 0; fileExists = 0; fileSize = 0;
    fb = configOpenForRead(path);
    CHECK(fb == NULL, "missing file returned a buffer");
    CHECK(opens == 1, "missing file opened %d times, want 1", opens);
    CHECK(bufferedOpens == 0, "missing file retried with the buffered reader");

    opens = bufferedOpens = 0; fileExists = 1; fileSize = 900;
    fb = configOpenForRead(path);
    CHECK(fb == &storeSingle, "small file not read single-shot");
    CHECK(opens == 1 && bufferedOpens == 0, "small file: %d opens, %d buffered", opens, bufferedOpens);

    opens = bufferedOpens = 0; fileExists = 1; fileSize = 900; failFirstWith = EIO;
    fb = configOpenForRead(path);
    CHECK(fb == &storeBuffered, "a transient first-open failure did not get the buffered retry");
    CHECK(opens == 2 && bufferedOpens == 1, "transient failure: %d opens, %d buffered", opens, bufferedOpens);
    failFirstWith = 0;

    opens = bufferedOpens = 0; fileExists = 1; fileSize = 9000;
    fb = configOpenForRead(path);
    CHECK(fb == &storeBuffered, "oversized file not handed to the buffered reader");
    CHECK(bufferedOpens == 1, "oversized file: buffered reader called %d times", bufferedOpens);

    if (failures)
        return 1;
    printf("config missing file opened once: ok\n");
    return 0;
}
'''
program = program.replace('@SINGLE@', single).replace('@FOR_READ@', for_read)

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'config_open_once.c'
    exe = Path(tmp) / 'config_open_once'
    c.write_text(program, encoding='utf-8')
    built = subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wno-unused-function', str(c), '-o', str(exe)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr)
        sys.exit('FAIL: could not build the config open harness')
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    print(ran.stdout, end='')
    if ran.returncode != 0:
        failures.append('harness failed')

for f in failures:
    print('FAIL:', f)
if failures:
    sys.exit(1)
