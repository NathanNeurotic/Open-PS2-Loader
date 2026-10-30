/*
  Host test for the freeze report's TV page (INGAMEDIAG flavour).
  Build: cc -std=gnu99 -Wall -Wextra -Werror -DFREEZE_DIAG_SCREEN_HOST_TEST -Iee_core/include
         ee_core/tests/test_freeze_diag_screen.c ee_core/src/freeze_diag_screen.c -o /tmp/test_freeze_diag_screen
*/

#include <stdio.h>
#include <string.h>

#include "freeze_diag_screen.h"

static int failures = 0;

#define CHECK(cond, what)                                   \
    do {                                                    \
        if (!(cond)) {                                      \
            printf("FAIL: %s (line %d)\n", what, __LINE__); \
            failures++;                                     \
        }                                                   \
    } while (0)

static freeze_diag_report_t r;
static heap_diag_snapshot_t h;
static fds_page_t p;

static int find(const char *needle, int *colour)
{
    int i;

    for (i = 0; i < FDS_LINES; i++)
        if (strstr(p.text[i], needle) != NULL) {
            if (colour != NULL)
                *colour = p.colour[i];
            return i;
        }
    return -1;
}

static void dump(void)
{
    int i;

    for (i = 0; i < FDS_LINES; i++)
        printf("|%-*s|\n", FDS_CHARS, p.text[i]);
}

int main(void)
{
    int i, colour = -1, row, rows_ok = 1;

    memset(&r, 0, sizeof(r));
    memset(&h, 0, sizeof(h));
    memcpy(r.game_id, "SLUS_202.67", 11);
    r.trigger = FREEZE_DIAG_TRIGGER_STALL;
    r.pad_frame = 77;
    r.igr_polls = 123456;

    // No heap record.
    freeze_diag_screen_compose(&r, &h, &p, 0);
    CHECK(find("RIPTOPL FREEZE REPORT  SLUS_202.67", &colour) == 0 && colour == FDS_C_TITLE, "title with the game");
    CHECK(find("TRIGGER: PAD DATA STOPPED", NULL) == 1, "the watchdog named as the trigger");
    CHECK(find("POLLS 123456", NULL) > 0, "the pad and poll counts");
    CHECK(find("IOP HEAP RECORD: NOT FOUND", &colour) > 0 && colour == FDS_C_WARN, "a missing record said so");
    CHECK(find("TAP POWER ONCE TO SAVE RIPTFRZ.TXT", NULL) == FDS_LINES - 1, "the footer at the bottom");

    // A record: two overruns, one short run, one failed allocation, a module list.
    h.found = 1;
    h.iop.version = HEAP_DIAG_VERSION;
    h.iop.module_count = 2;
    memcpy(h.iop.modules[0].name, "cdvdman", 7);
    h.iop.modules[0].text_start = 0x10000;
    h.iop.modules[0].size = 0x8000;
    memcpy(h.iop.modules[1].name, "gamesnd1", 8); // 8 characters, unterminated
    h.iop.modules[1].text_start = 0x80000;
    h.iop.modules[1].size = 0x4000;
    h.iop.allocs = 40;
    h.iop.frees = 12;
    h.iop.fails = 1;
    h.iop.free_now = 300000;
    h.iop.free_min = 20000;
    h.iop.largest_min = 9000;
    h.iop.blocks[3].addr = 0x0012A400;
    h.iop.blocks[3].size = 25344;
    h.iop.blocks[3].ra = 0x80123;
    h.tail_ff[3] = 1280;
    h.iop.blocks[7].addr = 0x00140000;
    h.iop.blocks[7].size = 2304;
    h.iop.blocks[7].ra = 0x99999;
    h.tail_ff[7] = 1792;
    h.iop.blocks[9].addr = 0x00150000;
    h.iop.blocks[9].size = 64;
    h.iop.blocks[9].ra = 0x10010;
    h.tail_ff[9] = 3;
    h.iop.blocks[11].addr = 0x00160000; // no run: not listed
    h.iop.blocks[11].size = 128;
    h.iop.failed[0].size = 30000;
    h.iop.failed[0].ra = 0x10044;
    h.iop.fail_next = 1;

    freeze_diag_screen_compose(&r, &h, &p, 0);
    CHECK(find("ALLOCS 40 FREES 12 FAILS 1", NULL) > 0, "the counts");
    CHECK(find("FREE NOW 300000 MIN 20000 LARGEST 9000", NULL) > 0, "free memory");
    CHECK(find("FAILED ALLOC 30000 BY cdvdman+44", &colour) > 0 && colour == FDS_C_WARN, "the failed allocation, caller resolved (the font draws it upper case)");
    row = find("00140000 2304 FF=1792 00099999", &colour);
    CHECK(row > 0 && colour == FDS_C_WARN, "the worst overrun first, caller outside every module as an address");
    CHECK(find("0012A400 25344 FF=1280 gamesnd1+123", NULL) == row + 1, "then the next, the 8-character module name whole");
    CHECK(find("00150000 64 FF=3 cdvdman+10", &colour) == row + 2 && colour == FDS_C_TEXT, "a short run, not marked");
    CHECK(find("00160000", NULL) < 0, "a block with no run is left out");
    for (i = 0; i < FDS_LINES; i++)
        if (strlen(p.text[i]) > FDS_CHARS)
            rows_ok = 0;
    CHECK(rows_ok, "every row fits the screen");

    // A full table: the list stops above the footer.
    for (i = 0; i < HEAP_DIAG_BLOCKS; i++) {
        h.iop.blocks[i].addr = 0x100000 + i * 0x100;
        h.iop.blocks[i].size = 16;
        h.tail_ff[i] = (unsigned short)(100 + i);
    }
    freeze_diag_screen_compose(&r, &h, &p, 1);
    CHECK(strcmp(p.text[FDS_LINES - 3], "") == 0, "a blank row above the footer");
    CHECK(find("SAVING RIPTFRZ.TXT", NULL) == FDS_LINES - 2, "the saving footer");
    CHECK(find("FF=195", NULL) > 0, "the longest run of a full table shown");

    r.trigger = FREEZE_DIAG_TRIGGER_POWER;
    freeze_diag_screen_compose(&r, &h, &p, 0);
    CHECK(find("TRIGGER: POWER BUTTON", NULL) == 1, "the power button named");

    if (failures) {
        dump();
        printf("%d failure(s)\n", failures);
        return 1;
    }
    printf("test_freeze_diag_screen: all checks passed\n");
    return 0;
}
