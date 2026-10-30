/*
  Host test for the in-game freeze report formatter (INGAMEDIAG flavour).
  Build: cc -std=gnu99 -Wall -Wextra -Werror -Iee_core/include ee_core/tests/test_freeze_diag_format.c
         ee_core/src/freeze_diag_format.c -o /tmp/test_freeze_diag_format
*/

#include <stdio.h>
#include <string.h>

#include "freeze_diag_report.h"

static int failures = 0;

#define CHECK(cond, what)                                   \
    do {                                                    \
        if (!(cond)) {                                      \
            printf("FAIL: %s (line %d)\n", what, __LINE__); \
            failures++;                                     \
        }                                                   \
    } while (0)

static char out[16384];

static void base_report(freeze_diag_report_t *r)
{
    memset(r, 0, sizeof(*r));
    strcpy(r->game_id, "SLUS_210.00");
    r->game_mode = 3;
    r->compat = 0x0A;
    r->cheats = 1;
    r->iop_resets = 2;
    r->igr_polls = 4321;
    r->padopen_hooked = 1;
    r->libpad = 1;
    r->iop_status = FREEZE_DIAG_IOP_ANSWERED;
    r->iop.magic = FREEZE_DIAG_MAGIC;
    r->iop.version = FREEZE_DIAG_VERSION;
    r->iop.reads = 1000;
    r->iop.last_lsn = 123456;
    r->iop.last_sectors = 16;
    r->iop.media_lsn_count = 2000000;
    r->iop.now_hi = 1;
    r->iop.now_lo = 0;
}

static int contains(const char *needle)
{
    return strstr(out, needle) != NULL;
}

int main(void)
{
    freeze_diag_report_t r;
    int len;

    CHECK(sizeof(freeze_diag_iop_t) == FREEZE_DIAG_IOP_SIZE, "IOP record size matches FREEZE_DIAG_IOP_SIZE");
    CHECK(sizeof(freeze_diag_iop_t) % 16 == 0, "IOP record is a whole number of SIF DMA blocks");

    // Idle disc, IOP answered: the freeze is on the EE side.
    base_report(&r);
    r.thread_count = 2;
    r.threads_total = 2;
    r.threads[0].id = 1;
    r.threads[0].status = 0x04;
    r.threads[0].wait_type = 2;
    r.threads[0].wait_id = 7;
    r.threads[0].prio = 64;
    r.threads[0].entry = 0x00100008;
    r.threads[1].id = 5;
    r.threads[1].status = 0x02;
    r.threads[1].prio = 30;
    len = freeze_diag_format(&r, "v1.2.0-Beta-1-abc-OFFICIALROLLING-FREEZEDIAG", out, sizeof(out));
    CHECK(len > 0 && len == (int)strlen(out), "returns the string length");
    CHECK(contains("RiptOPL in-game freeze report v2"), "title");
    CHECK(contains("build=v1.2.0-Beta-1-abc-OFFICIALROLLING-FREEZEDIAG"), "build line");
    CHECK(contains("game=SLUS_210.00"), "game id");
    CHECK(contains("compat=0x0000000A"), "compat mask in hex");
    CHECK(contains("cheats=1"), "cheats flag");
    CHECK(contains("iop=answered"), "IOP answered");
    CHECK(contains("disc_reads=1000"), "read count");
    CHECK(contains("last_lsn=123456"), "last lsn");
    CHECK(contains("hint=disc and VMC idle"), "EE-side hint");
    CHECK(contains("thread id=1 status=WAIT prio=64 wait=SEMA wait_id=7"), "waiting thread line");
    CHECK(contains("entry=0x00100008"), "thread entry in hex");
    CHECK(contains("thread id=5 status=READY prio=30"), "ready thread line");

    // A device read started 5 s before the report and never returned.
    base_report(&r);
    r.iop.busy = 1;
    r.iop.busy_lsn = 777;
    r.iop.busy_sectors = 32;
    r.iop.busy_start_hi = 0;
    r.iop.busy_start_lo = 0xFFFFFFFFu - (5u * FREEZE_DIAG_IOP_TICKS_PER_MS * 1000u) + 1u; // crosses the lo-word wrap
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("read_busy=1 busy_lsn=777 busy_sectors=32 busy_ms=5000"), "stalled read with 64-bit duration");
    CHECK(contains("hint=a disc read started 5000 ms ago and never returned"), "stalled-read hint");

    // A VMC operation that never returned.
    base_report(&r);
    r.iop.vmc_busy = 1;
    r.iop.vmc_busy_op = FREEZE_DIAG_VMC_WRITE;
    r.iop.vmc_busy_lba = 4242;
    r.iop.vmc_busy_start_hi = 1;
    r.iop.vmc_busy_start_lo = 0;
    r.iop.now_hi = 1;
    r.iop.now_lo = 2u * FREEZE_DIAG_IOP_TICKS_PER_MS * 1000u;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("vmc_busy=1 vmc_busy_op=write vmc_busy_lba=4242 vmc_busy_ms=2000"), "stalled VMC op");
    CHECK(contains("hint=a memory card (VMC) write started 2000 ms ago and never returned"), "stalled-VMC hint");

    // A stall longer than one 32-bit tick wrap (~116 s): 200 s exactly.
    base_report(&r);
    r.iop.busy = 1;
    r.iop.busy_start_hi = 0;
    r.iop.busy_start_lo = 0;
    {
        unsigned long long now = 200ull * FREEZE_DIAG_IOP_TICKS_PER_MS * 1000ull;
        r.iop.now_hi = (unsigned int)(now >> 32);
        r.iop.now_lo = (unsigned int)now;
    }
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("busy_ms=200000"), "duration beyond the low-word wrap");

    // Failed reads, no stall.
    base_report(&r);
    r.iop.read_errors = 3;
    r.iop.last_err = 0x30;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("read_errors=3"), "read error count");
    CHECK(contains("hint=disc reads failed"), "read-failure hint");

    // Reads cut off by the media size.
    base_report(&r);
    r.iop.eom_hits = 2;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("hint=the game read past the measured end of the image"), "end-of-media hint");

    // The normal case records that OPL's shutdown finished.
    base_report(&r);
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("shutdown=done"), "shutdown finished");

    // The IOP answered, but OPL's shutdown never finished: something on the IOP is held.
    base_report(&r);
    r.shutdown_status = FREEZE_DIAG_SHUTDOWN_TIMEOUT;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("shutdown=timeout"), "shutdown timeout recorded");
    CHECK(contains("hint=the IOP answered, but OPL's shutdown on it never finished"), "shutdown-timeout hint");

    // A stalled read explains a stalled shutdown: the read is the more specific hint.
    base_report(&r);
    r.shutdown_status = FREEZE_DIAG_SHUTDOWN_TIMEOUT;
    r.iop.busy = 1;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("hint=a disc read started"), "stalled read outranks stalled shutdown");

    // IOP never answered: nothing from the IOP record may be trusted or printed as data.
    base_report(&r);
    r.iop_status = FREEZE_DIAG_IOP_TIMEOUT;
    r.shutdown_status = FREEZE_DIAG_SHUTDOWN_SKIPPED;
    r.iop.reads = 99999;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("iop=timeout"), "IOP timeout");
    CHECK(contains("shutdown=skipped"), "shutdown skipped when the IOP did not answer");
    CHECK(contains("hint=the IOP did not answer"), "IOP hint");
    CHECK(!contains("disc_reads=99999"), "no IOP data printed when it did not answer");

    // A record with the wrong magic is treated as no answer.
    base_report(&r);
    r.iop.magic = 0;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("iop=bad-record"), "bad record reported");

    // More threads than fit: say how many were left out.
    base_report(&r);
    r.thread_count = FREEZE_DIAG_MAX_THREADS;
    r.threads_total = FREEZE_DIAG_MAX_THREADS + 5;
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("threads_not_listed=5"), "thread overflow count");

    // Truncation: never writes past cap, always terminates.
    {
        char small[40];
        memset(small, 'X', sizeof(small));
        base_report(&r);
        len = freeze_diag_format(&r, "b", small, 32);
        CHECK(len == 31, "truncated length is cap - 1");
        CHECK(small[31] == '\0', "truncated output terminated");
        CHECK(small[32] == 'X', "nothing written past cap");
    }

    // A game id without a terminator stays inside its field.
    base_report(&r);
    memset(r.game_id, 'A', sizeof(r.game_id));
    freeze_diag_format(&r, "b", out, sizeof(out));
    CHECK(contains("game=AAAAAAAAAAAAAAAA\n"), "unterminated game id bounded");

    // IOP heap record: sizes the EE copies by, module lookup, address order, the overrun flag.
    {
        static heap_diag_snapshot_t h;

        CHECK(sizeof(heap_diag_iop_t) == HEAP_DIAG_IOP_SIZE, "heap record size matches HEAP_DIAG_IOP_SIZE");
        CHECK(sizeof(heap_diag_iop_t) % 16 == 0, "heap record is a whole number of 16-byte blocks");
        CHECK(sizeof(heap_diag_snapshot_t) == HEAP_DIAG_SNAPSHOT_SIZE, "snapshot size matches HEAP_DIAG_SNAPSHOT_SIZE");
        CHECK(sizeof(heap_diag_snapshot_t) % 16 == 0, "snapshot is a whole number of SIF DMA blocks");

        memset(&h, 0, sizeof(h));
        len = freeze_diag_format_heap(&h, out, sizeof(out));
        CHECK(len > 0 && contains("heap=none"), "no record found");

        h.found = 1;
        h.found_at = 0x1A2B0;
        h.iop.version = HEAP_DIAG_VERSION;
        h.iop.allocs = 40;
        h.iop.free_now = 300000;
        h.iop.free_min = 120000;
        h.iop.module_count = 2;
        memcpy(h.iop.modules[0].name, "cdvdman", 7);
        h.iop.modules[0].text_start = 0x20000;
        h.iop.modules[0].size = 0x8000;
        memcpy(h.iop.modules[1].name, "sounddrv", 8); // exactly 8: no terminator
        h.iop.modules[1].text_start = 0x60000;
        h.iop.modules[1].size = 0x4000;
        h.iop.blocks[3].addr = 0x90000; // listed out of order on purpose
        h.iop.blocks[3].size = 2304;
        h.iop.blocks[3].ra = 0x60123;
        h.iop.blocks[3].seq = 7;
        h.tail_ff[3] = 1792;
        h.iop.blocks[5].addr = 0x80000;
        h.iop.blocks[5].size = 25344;
        h.iop.blocks[5].ra = 0x123456; // in no module
        h.iop.blocks[5].seq = 3;
        h.tail_ff[5] = 12; // too short to call an overrun
        len = freeze_diag_format_heap(&h, out, sizeof(out));
        CHECK(len > 0 && len == (int)strlen(out), "heap returns the string length");
        CHECK(contains("heap=found at=0x0001A2B0 allocs=40"), "heap summary");
        CHECK(contains("heap_free now=300000 lowest=120000"), "free memory");
        CHECK(contains("module name=sounddrv text=0x00060000"), "8-character module name bounded");
        CHECK(contains("by=sounddrv+0x00000123"), "caller resolved to module+offset");
        CHECK(contains("by=0x00123456"), "caller outside every module stays an address");
        CHECK(strstr(out, "addr=0x00080000") < strstr(out, "addr=0x00090000"), "blocks listed by address");
        CHECK(contains("size=2304 by=sounddrv+0x00000123 seq=7 ff_after=1792 OVERRUN?"), "long 0xFF run flagged");
        CHECK(!contains("ff_after=12 OVERRUN?"), "short 0xFF run not flagged");
        CHECK(contains("heap_hint=the 2304-byte block from sounddrv+0x00000123 is followed by 1792 bytes of 0xFF"), "overrun hint");

        h.iop.fails = 1;
        h.iop.failed[0].size = 65536;
        h.iop.failed[0].ra = 0x60010;
        len = freeze_diag_format_heap(&h, out, sizeof(out));
        CHECK(contains("failed_alloc size=65536 mode=0 by=sounddrv+0x00000010"), "failed allocation listed");
        CHECK(contains("heap_hint=1 IOP allocation(s) failed"), "failed-allocation hint first");
    }

    if (failures == 0)
        printf("test_freeze_diag_format: all checks passed\n");
    return failures != 0;
}
