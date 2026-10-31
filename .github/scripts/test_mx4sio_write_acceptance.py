"""Exercise the actual transmit ISR -> write count -> retry chain.

A rejected data token or programming timeout must leave the sector uncounted,
including the last sector. Host simulation does not validate SIO2 timing.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "modules/mx4sio_bd/src"


def function(source, name):
    start = re.search(r"^(?:static )?(?:inline )?(?:int|void) " + name + r"\(", source, re.M).start()
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
#include "mx4sio.h"
typedef uint32_t u32;
struct block_device { int unused; };
#define SECTOR_SIZE 512
#define MAX_RETRIES 4
#define SPISD_RESULT_OK 0
#define M_DEBUG(...) do {} while (0)
dma_command_t cmd;
int sio2_event_flag = 7;
static struct { int used; } sdcard;
static unsigned char disk[32*512], buffer[8*512], before[32*512], caller[8*512];
static uint8_t *pending, *active;
static int locked, complete, mode, failed_index, failures, starts, accepted;
static int card_sector, token, programming;
static unsigned inl_sio2_stat_get(void) { return 0; }
static void inl_sio2_stat_set(unsigned value) { (void)value; }
static unsigned inl_sio2_stat6c_get(void) { return 1 << 12; }
uint8_t mx_sio2_write_dummy(void) { return 0xff; }
uint8_t mx_sio2_write_byte(uint8_t value) { assert(value == 0xfc); return 0; }
void mx_sio2_lock(uint8_t intr) { assert(intr == INTR_TX && !locked); locked = 1; }
void mx_sio2_unlock(uint8_t intr) { assert(intr == INTR_TX && locked); locked = 0; }
@REVERSE@
static uint8_t wire_byte(uint8_t v) {
    uint8_t out = 0;
    for (int i=0; i<8; i++) { out=(out<<1)|(v&1); v>>=1; }
    return out;
}
void mx_sio2_start_tx_dma(uint8_t *p) { assert(!pending); pending = p; }
uint8_t mx_sio2_wait_equal_masked(uint8_t value, uint8_t mask, uint32_t count) {
    assert(value == 5 && mask == 0x1f && count == 10);
    assert(active == buffer + (card_sector - 9)*512);
    int fail = mode && card_sector == 9 + failed_index && (mode >= 4 || failures == 0);
    token = 5;
    programming = 0;
    if (fail) {
        failures++;
        int kind = (mode - 1) % 3;
        if (kind == 0) token = 0x0b; /* CRC rejection */
        else if (kind == 1) token = 0x0d; /* write rejection */
        else programming = 1; /* accepted token, programming timed out */
    }
    return token;
}
uint8_t mx_sio2_wait_equal(uint8_t value, uint32_t count) {
    assert(value == 0xff && count == 0x80000);
    if (token == 5 && !programming) {
        assert(card_sector == 9 + accepted);
        for (int i=0; i<512; i++) disk[card_sector*512+i] = wire_byte(active[i]);
        accepted++;
        card_sector++;
    }
    return programming;
}
static int iSetEventFlag(int ef, int flags) {
    assert(ef == 7 && flags == EF_SIO2_INTR_COMPLETE);
    complete = 1;
    return 0;
}
@ISR@
static int WaitEventFlag(int ef, unsigned bits, int flags, u32 *resbits) {
    assert(ef == 7 && bits == EF_SIO2_INTR_COMPLETE && flags == 1);
    int budget = 9;
    while (!complete) {
        assert(pending && budget-- > 0);
        active = pending;
        pending = NULL;
        assert(mx_sio2_dma_isr_tx(&ef) == 1);
    }
    *resbits = EF_SIO2_INTR_COMPLETE;
    return 0;
}
static int ClearEventFlag(int ef, unsigned bits) {
    assert(ef == 7 && bits == (unsigned)~EF_SIO2_INTR_COMPLETE);
    complete = 0;
    return 0;
}
static int spisd_write_multi_begin(uint32_t sector, uint16_t count) {
    assert(locked && !pending && !complete);
    assert(sector == (uint32_t)(9 + accepted));
    assert(count == 8 - accepted);
    card_sector = sector;
    starts++;
    return 0;
}
static int spisd_write_multi_end(void) { assert(!pending); return 0; }
@WRITE_DO@
@WRITE@
static void run(int failure_mode, int index) {
    mode = failure_mode; failed_index = index;
    locked = complete = failures = starts = accepted = sdcard.used = 0;
    pending = active = NULL;
    memset(disk, 0xa5, sizeof(disk));
    memcpy(before, disk, sizeof(disk));
    for (unsigned i = 0; i < sizeof(buffer); ++i) buffer[i] = (unsigned char)(i/512*11 + i);
    memcpy(caller, buffer, sizeof(caller));
    int expected = mode >= 4 ? index : 8;
    int result = spisd_write(NULL,9,buffer,8);
    assert(result == expected && accepted == expected);
    assert(memcmp(buffer, caller, sizeof(buffer)) == 0);
    assert(!locked && !pending && !complete && sdcard.used);
    assert(memcmp(disk, before, 9*512) == 0);
    assert(memcmp(disk+9*512,buffer,expected*512) == 0);
    assert(memcmp(disk+(9+expected)*512,before+(9+expected)*512,(32-9-expected)*512) == 0);
    assert(starts == (mode >= 4 ? 4 : mode ? 2 : 1));
    assert(failures == (mode >= 4 ? 4 : mode ? 1 : 0));
}
int main(void) {
    run(0,0);
    for (int mode = 1; mode <= 6; ++mode) {
        run(mode,0); /* first sector rejected */
        run(mode,3); /* middle sector rejected */
        run(mode,7); /* last sector must never yield false full success */
    }
    puts("MX4SIO: 19 production ISR/retry acceptance cases passed (host only)");
}
"""



CARD_HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "spi_sdcard_driver.h"
#define CMD9 0x49
#define CMD10 0x4a
#define M_PRINTF(...) do {} while (0)
spisd_t sdcard;
struct block_device bd;
static int mode, reads;
static unsigned char response[18];
static uint8_t spisd_send_cmd(uint8_t cmd, uint32_t arg) {
    (void)arg;
    if (mode == 1 && cmd == CMD9) return 5;
    if (mode == 3 && cmd == CMD10) return 5;
    return 0;
}
static uint8_t spisd_read_register(uint8_t *dest, uint32_t len) {
    assert(len == 18);
    reads++;
    memcpy(dest, response, len);
    return (mode == 2 && reads == 1) || (mode == 4 && reads == 2) ? 1 : 0;
}
static uint8_t mx_sio2_write_dummy(void) { return 0xff; }
@INFO@
int main(void) {
    for (mode=0; mode<5; mode++) {
        memset(&sdcard, 0xa5, sizeof(sdcard));
        spisd_t before = sdcard;
        reads = 0;
        for (unsigned i=0; i<sizeof(response); i++) response[i] = i+1;
        int result = spisd_get_card_info();
        assert(result == (mode == 1 ? 5 : mode ? 1 : 0));
        if (mode == 1 || mode == 2) assert(memcmp(sdcard.csd, before.csd, 16) == 0);
        else assert(memcmp(sdcard.csd, response, 16) == 0);
        if (mode) assert(memcmp(&sdcard.cid, &before.cid, sizeof(sdcard.cid)) == 0);
        else {
            assert(sdcard.cid.ManufacturerID == 1);
            assert(sdcard.cid.ProdName1 == 0x04050607);
        }
    }
    puts("MX4SIO: five CSD/CID initialization and error cases passed (host only)");
}
"""


def check_card_info(source, flags, path):
    # Use the actual card structures; only the host block-device header is stubbed.
    (path / "bdm.h").write_text(
        "#include <stdint.h>\n"
        "typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;\n"
        "struct block_device { uint64_t sectorCount; uint32_t sectorSize; };\n",
        encoding="utf-8")
    c, binary = path / "card.c", path / "card.exe"
    harness = CARD_HARNESS.replace("@INFO@", function(source, "spisd_get_card_info"))
    c.write_text(harness, encoding="utf-8")
    subprocess.run([os.environ.get("CC", "gcc"), *flags, "-I"+str(path), str(c), "-o", str(binary)], check=True, timeout=120)
    subprocess.run([str(binary)], check=True, timeout=30)
    mutant = harness.replace("spisd_read_register(reg_data, sizeof(reg_data))",
                             "spisd_read_register(sdcard.csd, sizeof(reg_data))", 1)
    assert mutant != harness
    c.write_text(mutant, encoding="utf-8")
    subprocess.run([os.environ.get("CC", "gcc"), *flags, "-I"+str(path), str(c), "-o", str(binary)], check=True, timeout=120)
    result = subprocess.run([str(binary)], capture_output=True, timeout=30)
    assert result.returncode != 0, "CSD response overwrite was not detected"
    print("PASS: CSD response overwrite is detected")


def main():
    source = (DRIVER / "spi_sdcard_driver.c").read_text(encoding="utf-8")
    isr = function((DRIVER / "mx4sio.c").read_text(encoding="utf-8"), "mx_sio2_dma_isr_tx")
    harness = (HARNESS.replace("@ISR@", isr).replace("@REVERSE@", function((DRIVER / "mx4sio.c").read_text(encoding="utf-8"), "reverse_buffer").replace("inline void", "void"))
               .replace("@WRITE_DO@", function(source, "spisd_write_multi_do"))
               .replace("@WRITE@", function(source, "spisd_write")))
    flags = ["-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare", "-I" + str(DRIVER)]
    if os.name != "nt":
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    with tempfile.TemporaryDirectory() as tmp:
        c, binary = Path(tmp) / "accept.c", Path(tmp) / "accept.exe"
        c.write_text(harness, encoding="utf-8")
        subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
        subprocess.run([str(binary)], check=True, timeout=30)
        # Restore the upstream counting order: the executable must reject it.
        mutant = harness.replace(
            "    if (cmd.abort == 0)\n        cmd.sectors_transferred++;", "")
        mutant = mutant.replace("    /* get data response token */",
                                "    cmd.sectors_transferred++;\n    /* get data response token */")
        assert mutant != harness
        c.write_text(mutant, encoding="utf-8")
        subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
        result = subprocess.run([str(binary)], capture_output=True, timeout=30)
        assert result.returncode != 0, "premature ISR write accounting was not detected"
        print("PASS: premature ISR write accounting is detected")
        mutant = harness.replace("reverse_buffer((uint32_t *)buffer, ((count * SECTOR_SIZE) / 4));", "")
        assert mutant != harness
        c.write_text(mutant, encoding="utf-8")
        subprocess.run([os.environ.get("CC", "gcc"), *flags, str(c), "-o", str(binary)], check=True, timeout=120)
        result = subprocess.run([str(binary)], capture_output=True, timeout=30)
        assert result.returncode != 0, "caller buffer mutation was not detected"
        print("PASS: caller buffer mutation is detected")
        check_card_info(source, flags, Path(tmp))


if __name__ == "__main__":
    main()

