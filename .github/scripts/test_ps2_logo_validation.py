#!/usr/bin/env python3
"""Exercise actual native-logo validation using synthetic, non-game logo bytes."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/util.c').read_text(encoding='utf-8')
if len(sys.argv) > 1:
    source = subprocess.check_output(['git', 'show', sys.argv[1] + ':src/util.c'], text=True)
start = source.index('int CheckPS2Logo(')
function = source[start:source.index('\n}', start) + 2]
program = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define ALIGNED(n) __attribute__((aligned(n)))
#define CONSOLE_REGION_EUROPE 2
#define ZSO_MAGIC 0x4f53495a
typedef struct { u32 magic; } ZISO_header;
static int ConsoleRegion, gEnableDebug, probed_fd, probed_lba;
static int reads, sectors, seekCalls, shortRead;
static unsigned char image[12 * 2048];
static void guiWarning(const char *text, int frames) { (void)text; (void)frames; }
static int ziso_init(ZISO_header *, u32) { assert(0); return 0; }
static int ziso_read_sector(void *, int, int) { assert(0); return 0; }
static long mockSeek(int fd, long offset, int whence) {
    assert(fd >= 0 && offset == 0 && whence == SEEK_SET);
    seekCalls++; return 0;
}
static long mockRead(int fd, void *out, unsigned long length) {
    assert(fd >= 0 && length == sizeof(image));
    reads++; memcpy(out, image, length); return shortRead ? length - 1 : length;
}
static int hddReadSectors(u32 lba, int count, void *out) {
    assert(lba == 100u + sectors && count == 1);
    memcpy(out, image + sectors * 512, 512); sectors++; return 0;
}
#define lseek mockSeek
#define read mockRead
''' + function + r'''
static void makeLogo(u32 checksum) {
    unsigned char plain[sizeof(image)] = {0};
    for (unsigned i = 1; checksum && i < sizeof(image); i++) {
        unsigned value = checksum > 255 ? 255 : checksum;
        plain[i] = value; checksum -= value;
    }
    assert(checksum == 0);
    for (unsigned i = 0; i < sizeof(image); i++)
        image[i] = ((plain[i] >> 3) | (plain[i] << 5)) ^ 0xa5;
}
int main() {
    makeLogo(0x120519); ConsoleRegion = 0;
    assert(CheckPS2Logo(3, 0) == 1 && reads == 1);
    reads = seekCalls = 0;
    assert(CheckPS2Logo(0, 0) == 1 && reads == 1 && seekCalls == 1);
    assert(CheckPS2Logo(-1, 0) == 0 && reads == 1);
    sectors = 0;
    assert(CheckPS2Logo(0, 100) == 1 && sectors == 48);
    ConsoleRegion = CONSOLE_REGION_EUROPE;
    assert(CheckPS2Logo(0, 0) == 0);
    makeLogo(0x1555ab);
    assert(CheckPS2Logo(0, 0) == 1);
    shortRead = 1;
    assert(CheckPS2Logo(0, 0) == 0);
    puts("native logo: fd0, normal fd, invalid fd, HDD bound, region and short read passed");
}
'''
with tempfile.TemporaryDirectory() as temp:
    cpp = Path(temp) / 'logo.c'
    exe = Path(temp) / 'logo'
    cpp.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                    str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)


