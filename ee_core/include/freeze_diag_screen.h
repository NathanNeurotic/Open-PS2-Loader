/*
  In-game freeze report on the TV (INGAMEDIAG flavour only): see ee_core/src/freeze_diag_screen.c. The page composer
  is plain C, tested on the host (ee_core/tests/test_freeze_diag_screen.c).
*/

#ifndef FREEZE_DIAG_SCREEN_H
#define FREEZE_DIAG_SCREEN_H

#include "freeze_diag_report.h"

#define FDS_CHARS 49 // 53 cells across 640 pixels, two kept clear on each side
#define FDS_LINES 26 // 28 rows down 448 lines, one kept clear at the top and bottom

// A run of 0xFF this long after a block is shown as an overrun (as the memory-card report marks it).
#define FDS_OVERRUN_MIN 64

enum {
    FDS_C_TEXT = 0,
    FDS_C_TITLE,
    FDS_C_WARN,
    FDS_C_DIM,
    FDS_C_COUNT,
};

typedef struct fds_page
{
    char text[FDS_LINES][FDS_CHARS + 1];
    unsigned char colour[FDS_LINES];
} fds_page_t;

// The page as text. saving: the footer says the memory-card report is being written.
void freeze_diag_screen_compose(const freeze_diag_report_t *r, const heap_diag_snapshot_t *h, fds_page_t *p, int saving);

#ifndef FREEZE_DIAG_SCREEN_HOST_TEST
// Draws the page in a frame of its own and waits for a tap of the power button.
void FreezeDiag_Screen(const freeze_diag_report_t *r, const heap_diag_snapshot_t *h);
#endif

#endif
