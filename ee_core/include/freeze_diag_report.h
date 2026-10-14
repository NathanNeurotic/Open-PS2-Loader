/*
  In-game freeze report (INGAMEDIAG flavour only): what ee_core collects when the IGR combo is
  pressed after a freeze, and the text formatter that turns it into the memory-card report.
  The formatter is plain C with no PS2 dependencies, so it is tested on the host
  (ee_core/tests/test_freeze_diag_format.c).
*/

#ifndef FREEZE_DIAG_REPORT_H
#define FREEZE_DIAG_REPORT_H

#include "../../modules/iopcore/common/freeze_diag.h"

#define FREEZE_DIAG_MAX_THREADS 16

// How the IOP answered the request for its record.
enum {
    FREEZE_DIAG_IOP_ANSWERED = 0,
    FREEZE_DIAG_IOP_NO_BIND,     // the IGR RPC server never bound
    FREEZE_DIAG_IOP_TIMEOUT,     // bound, but no answer within the budget
    FREEZE_DIAG_IOP_CALL_FAILED, // SifCallRpc refused the request
    FREEZE_DIAG_IOP_BAD_RECORD,  // answered with something that is not the record
};

// What became of OPL's IGR shutdown request (CDVDMAN flushes and stops its device).
enum {
    FREEZE_DIAG_SHUTDOWN_DONE = 0,
    FREEZE_DIAG_SHUTDOWN_TIMEOUT, // sent, never finished within the budget
    FREEZE_DIAG_SHUTDOWN_SKIPPED, // not sent: the IOP did not answer the report request
};

typedef struct freeze_diag_thread
{
    unsigned int id;
    unsigned int status; // kernel THS_* bits
    unsigned int prio;
    unsigned int wait_type; // 0 none, 1 sleep, 2 semaphore
    unsigned int wait_id;
    unsigned int wakeup;
    unsigned int entry;
} freeze_diag_thread_t;

typedef struct freeze_diag_report
{
    char game_id[16]; // not necessarily terminated
    unsigned int game_mode;
    unsigned int compat;
    unsigned int cheats;
    unsigned int gsm;
    unsigned int iop_resets;
    unsigned int iop_reset_failures;
    unsigned int igr_polls;
    unsigned int padopen_hooked;
    unsigned int libpad;
    unsigned int pad_state;
    unsigned int pad_frame;
    unsigned int iop_status;
    unsigned int shutdown_status;
    unsigned int thread_count;  // entries filled in threads[]
    unsigned int threads_total; // threads that existed
    freeze_diag_thread_t threads[FREEZE_DIAG_MAX_THREADS];
    freeze_diag_iop_t iop;
} freeze_diag_report_t;

// Writes the report as text into out (at most cap - 1 characters, always terminated) and returns
// the number of characters written.
int freeze_diag_format(const freeze_diag_report_t *r, const char *build, char *out, int cap);

#endif
