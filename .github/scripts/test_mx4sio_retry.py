"""Compile the actual MX4SIO retry loops over a fault-injected sector device.

Exercises partial/zero progress, retry exhaustion, recovery/begin/end failures,
buffer offsets, remaining ACMD23 counts and buffers that are not word aligned. No SIO2/DMA or console acceptance.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "modules/mx4sio_bd/src/spi_sdcard_driver.c"


def function(source, name):
    start = source.index("int " + name + "(")
    brace = source.index("{", start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct block_device { int unused; };
#define SECTOR_SIZE 512
#define SPISD_RESULT_OK 0
#define CMD_ABORT_NO_READ_TOKEN 1
#define INTR_RX 0
#define INTR_TX 1
#define M_DEBUG(...) do {} while (0)
#define MAX_RETRIES @RETRIES@
static struct { int abort; } cmd;
static struct { int used; } sdcard;
static unsigned char disk[32 * 512], buffer[8 * 512], before[32 * 512];
static int schedule[4], attempt, done, locked, fail_begin, fail_end, recover_mode;
static uint32_t current;
static void mx_sio2_lock(int mode) { (void)mode; assert(!locked); locked = 1; }
static void mx_sio2_unlock(int mode) { (void)mode; assert(locked); locked = 0; }
/* Bit reversal is outside the retry contract: keep bytes readable in this model. */
static void reverse_buffer(void *p, unsigned n) { assert(p == buffer && n == 8 * 512 / 4); }
static int begin(uint32_t sector) {
    assert(locked);
    /* Every retry must resume at the same byte and sector offset. */
    assert(sector == (uint32_t)(9 + done));
    current = sector;
    return attempt == fail_begin ? 1 : 0;
}
static int spisd_read_multi_begin(uint32_t sector) { return begin(sector); }
static int spisd_write_multi_begin(uint32_t sector, uint16_t count) {
    assert(count == 8 - done); /* remaining ACMD23 pre-erase hint */
    return begin(sector);
}
static int transfer(void *p, uint16_t count, int write) {
    assert(p == buffer + done * 512);
    assert(count == 8 - done);
    int n = schedule[attempt++];
    assert(n >= 0 && n <= count && current + n <= 32);
    if (write) memcpy(disk + current * 512, p, n * 512);
    else memcpy(p, disk + current * 512, n * 512);
    done += n;
    cmd.abort = recover_mode ? CMD_ABORT_NO_READ_TOKEN : 0;
    return n;
}
static int spisd_read_multi_do(void *p, uint16_t count) { return transfer(p, count, 0); }
static int spisd_write_multi_do(void *p, uint16_t count) { return transfer(p, count, 1); }
static void spisd_read_multi_end(void) {}
static int spisd_write_multi_end(void) { return attempt == fail_end ? 1 : 0; }
static int spisd_recover(void) { return recover_mode == 2 ? 1 : 0; }

static uint32_t bounce[SECTOR_SIZE / 4]; /* the driver's file-scope bounce buffer */
@READ@
@WRITE@

static void run(int write, int a, int b, int c, int d, int expected,
                int begin_failure, int end_failure, int recovery) {
    int seq[] = {a,b,c,d};
    memcpy(schedule, seq, sizeof(seq));
    attempt = done = locked = sdcard.used = 0;
    cmd.abort = 0;
    fail_begin = begin_failure; fail_end = end_failure; recover_mode = recovery;
    for (unsigned i = 0; i < sizeof(disk); ++i) disk[i] = (unsigned char)(i / 512 * 7 + i);
    memcpy(before, disk, sizeof(disk));
    memset(buffer, 0xa5, sizeof(buffer));
    if (write) for (unsigned i = 0; i < sizeof(buffer); ++i) buffer[i] = (unsigned char)(i / 512 * 11 + i);
    int result = write ? spisd_write(NULL, 9, buffer, 8) : spisd_read(NULL, 9, buffer, 8);
    assert(result == expected && done == expected);
    assert(!locked && sdcard.used);
    if (write) {
        assert(memcmp(disk, before, 9 * 512) == 0);
        assert(memcmp(disk + 9 * 512, buffer, done * 512) == 0);
        assert(memcmp(disk + (9 + done) * 512, before + (9 + done) * 512, (32 - 9 - done) * 512) == 0);
    } else {
        assert(memcmp(buffer, disk + 9 * 512, done * 512) == 0);
        for (unsigned i = done * 512; i < sizeof(buffer); ++i) assert(buffer[i] == 0xa5);
        assert(memcmp(disk, before, sizeof(disk)) == 0);
    }
}
int main(void) {
    for (int write = 0; write <= 1; ++write) {
        run(write,8,0,0,0,8,-1,-1,0); /* full success */
        run(write,2,3,3,0,8,-1,-1,0); /* repeated partial progress */
        run(write,0,2,0,6,8,-1,-1,0); /* zero progress does not advance offsets */
        run(write,1,1,1,1,4,-1,-1,0); /* retry budget returns a short count */
        run(write,0,0,0,0,0,-1,-1,0);
        run(write,2,6,0,0,0,0,-1,0); /* begin failure before any transfer */
        run(write,2,6,0,0,2,1,-1,0); /* begin failure after partial progress */
    }
    run(0,2,6,0,0,8,-1,-1,1); /* card recovery, correct next sector */
    run(0,2,6,0,0,2,-1,-1,2); /* failed recovery reports short read */
    run(1,2,6,0,0,2,-1,1,0); /* failed write-stop after partial progress */
    locked = attempt = sdcard.used = 0;
    assert(spisd_read(NULL,9,buffer,0) == 0);
    assert(spisd_write(NULL,9,buffer,0) == 0);
    assert(!locked && !attempt && !sdcard.used);
    puts("MX4SIO: 19 retry/error/zero-count scenarios passed (host only)");
}
"""


UNALIGNED = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct block_device { int unused; };
#define SECTOR_SIZE 512
#define SPISD_RESULT_OK 0
#define CMD_ABORT_NO_READ_TOKEN 1
#define INTR_RX 0
#define INTR_TX 1
#define M_DEBUG(...) do {} while (0)
#define MAX_RETRIES 1
static struct { int abort; } cmd;
static struct { int used; } sdcard;
static unsigned char disk[16 * 512], before[16 * 512];
static uint32_t storage[8 * 512 / 4 + 1];
static uint32_t current;
static int transfers, fail_at, multi;
/* Model the hardware: word DMA and in-place word reversal fault on an odd address. */
static void word_only(const void *p) { assert(((uintptr_t)p & 3) == 0); }
static void reverse_buffer(void *p, unsigned n) { word_only(p); (void)n; }
static void mx_sio2_lock(int mode) { (void)mode; }
static void mx_sio2_unlock(int mode) { (void)mode; }
static int spisd_read_multi_begin(uint32_t sector) { current = sector; return 0; }
static int spisd_write_multi_begin(uint32_t sector, uint16_t count) { (void)count; current = sector; return 0; }
static int transfer(void *p, uint16_t count, int write) {
    word_only(p);
    if (count > 1) multi = 1;
    if (transfers++ == fail_at) return 0;
    if (write) memcpy(disk + current * 512, p, count * 512);
    else memcpy(p, disk + current * 512, count * 512);
    return count;
}
static int spisd_read_multi_do(void *p, uint16_t count) { return transfer(p, count, 0); }
static int spisd_write_multi_do(void *p, uint16_t count) { return transfer(p, count, 1); }
static void spisd_read_multi_end(void) {}
static int spisd_write_multi_end(void) { return 0; }
static int spisd_recover(void) { return 0; }
static uint32_t bounce[SECTOR_SIZE / 4];
@READ@
@WRITE@
static void run(int write, unsigned offset, int fail, int expected) {
    unsigned char *buf = (unsigned char *)storage + offset, caller[3 * 512];
    transfers = multi = 0; fail_at = fail;
    for (unsigned i = 0; i < sizeof(disk); ++i) disk[i] = (unsigned char)(i / 512 * 7 + i);
    memcpy(before, disk, sizeof(disk));
    for (unsigned i = 0; i < sizeof(caller); ++i) buf[i] = caller[i] = (unsigned char)((i / SECTOR_SIZE) * 11 + i * 13 + 5);
    int result = write ? spisd_write(NULL, 5, buf, 3) : spisd_read(NULL, 5, buf, 3);
    assert(result == expected);
    /* An aligned buffer keeps the single multi-sector transfer. */
    assert(multi == (offset == 0 && fail < 0));
    if (write) {
        assert(memcmp(disk + 5 * 512, caller, result * 512) == 0);
        assert(memcmp(disk + (5 + result) * 512, before + (5 + result) * 512, (11 - result) * 512) == 0);
        assert(memcmp(buf, caller, sizeof(caller)) == 0); /* the caller's data is untouched */
    } else {
        assert(memcmp(buf, disk + 5 * 512, result * 512) == 0);
        assert(memcmp(buf + result * 512, caller + result * 512, (3 - result) * 512) == 0);
    }
    assert(memcmp(disk, before, 5 * 512) == 0);
}
int main(void) {
    for (int write = 0; write <= 1; ++write) {
        run(write, 0, -1, 3); /* aligned: unchanged path */
        for (unsigned offset = 1; offset < 4; ++offset) {
            run(write, offset, -1, 3); /* odd address goes a sector at a time */
            run(write, offset, 1, 1); /* a failed sector stops with a short count */
        }
    }
    puts("MX4SIO: 14 unaligned-buffer scenarios passed (host only)");
}
"""


def check_unaligned(read, write, flags, path):
    c, binary = path / "unaligned.c", path / "unaligned.exe"
    harness = UNALIGNED.replace("@READ@", read).replace("@WRITE@", write)
    c.write_text(harness, encoding="utf-8")
    subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
    subprocess.run([str(binary)], check=True, timeout=30)
    # Without the bounce path an odd buffer reaches the word-only transfer.
    mutant = harness.replace("if ((uintptr_t)buffer & 3) {", "if (0) {")
    assert mutant.count("if (0) {") == 2
    c.write_text(mutant, encoding="utf-8")
    subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
    result = subprocess.run([str(binary)], capture_output=True, timeout=30)
    assert result.returncode != 0, "unaligned buffer regression was not detected"
    print("PASS: unaligned buffer regression is detected")


def main():
    source = SOURCE.read_text(encoding="utf-8")
    read, write = function(source, "spisd_read"), function(source, "spisd_write")
    retries = re.search(r"^#define MAX_RETRIES\s+(\d+)", source, re.M).group(1)
    assert retries == "4", "update fault schedules if upstream retry budget changes"
    harness = HARNESS.replace("@RETRIES@", retries).replace("@READ@", read).replace("@WRITE@", write)
    flags = ["-std=gnu99", "-Wall", "-Wextra", "-Werror"]
    if os.name != "nt":
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        c, binary = path / "retry.c", path / "retry.exe"
        c.write_text(harness, encoding="utf-8")
        subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
        subprocess.run([str(binary)], check=True, timeout=30)
        # Prove that each upstream bug is actually caught by this executable test.
        for name, mutant in (
            ("read sector", harness.replace("sector += results;", "", 1)),
            ("write sector", harness.rsplit("sector += results;", 1)),
            ("write count", harness.replace("spisd_write_multi_begin((uint32_t)sector, sectors_left)",
                                           "spisd_write_multi_begin((uint32_t)sector, count)")),
        ):
            if isinstance(mutant, list):
                mutant = "".join(mutant)
            c.write_text(mutant, encoding="utf-8")
            subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
            result = subprocess.run([str(binary)], capture_output=True, timeout=30)
            assert result.returncode != 0, name + " regression was not detected"
        print("PASS: all three unpatched retry regressions are detected")
        check_unaligned(read, write, flags, path)
    subprocess.run([sys.executable, str(Path(__file__).with_name("test_mx4sio_write_acceptance.py"))], check=True, timeout=900)


if __name__ == "__main__":
    main()

