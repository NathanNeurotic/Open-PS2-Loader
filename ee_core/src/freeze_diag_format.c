/*
  In-game freeze report formatter (INGAMEDIAG flavour only). ee_core has no printf, so this
  builds the text by hand. Plain C with no PS2 dependencies: tested on the host by
  ee_core/tests/test_freeze_diag_format.c.
*/

#include "freeze_diag_report.h"

typedef struct
{
    char *out;
    int cap;
    int len;
} fd_buf_t;

static void put_char(fd_buf_t *b, char c)
{
    if (b->len < b->cap - 1)
        b->out[b->len++] = c;
}

static void put_str(fd_buf_t *b, const char *s)
{
    while (*s != '\0')
        put_char(b, *s++);
}

static void put_dec(fd_buf_t *b, unsigned int v)
{
    char digits[10];
    int n = 0;

    do {
        digits[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v != 0);
    while (n > 0)
        put_char(b, digits[--n]);
}

static void put_hex(fd_buf_t *b, unsigned int v)
{
    static const char hex[] = "0123456789ABCDEF";
    int shift;

    put_str(b, "0x");
    for (shift = 28; shift >= 0; shift -= 4)
        put_char(b, hex[(v >> shift) & 0xF]);
}

static void put_field(fd_buf_t *b, const char *name, unsigned int v)
{
    put_char(b, ' ');
    put_str(b, name);
    put_char(b, '=');
    put_dec(b, v);
}

// Milliseconds from start to now, both IOP clock values split into hi/lo words.
static unsigned int elapsed_ms(unsigned int start_hi, unsigned int start_lo, unsigned int now_hi, unsigned int now_lo)
{
    // 32-bit only: this also runs in the IOP report writer, which has no 64-bit division.
    // One wrap of the low word (2^32 ticks) is 116508 ms.
    unsigned int hi, lo;

    if (now_hi < start_hi || (now_hi == start_hi && now_lo <= start_lo))
        return 0;
    lo = now_lo - start_lo;
    hi = now_hi - start_hi - (now_lo < start_lo ? 1 : 0);
    // 2^32 = 116508 * 36864 + 16384, so carry each wrap's 16384 leftover ticks exactly.
    return hi * 116508u + lo / FREEZE_DIAG_IOP_TICKS_PER_MS + (lo % FREEZE_DIAG_IOP_TICKS_PER_MS + hi * 16384u) / FREEZE_DIAG_IOP_TICKS_PER_MS;
}

static const char *thread_status_name(unsigned int status)
{
    switch (status) {
        case 0x01:
            return "RUN";
        case 0x02:
            return "READY";
        case 0x04:
            return "WAIT";
        case 0x08:
            return "SUSPEND";
        case 0x0C:
            return "WAITSUSPEND";
        case 0x10:
            return "DORMANT";
        default:
            return 0;
    }
}

static const char *wait_type_name(unsigned int type)
{
    switch (type) {
        case 0:
            return "-";
        case 1:
            return "SLEEP";
        case 2:
            return "SEMA";
        default:
            return 0;
    }
}

static const char *iop_status_name(unsigned int status)
{
    switch (status) {
        case FREEZE_DIAG_IOP_ANSWERED:
            return "answered";
        case FREEZE_DIAG_IOP_NO_BIND:
            return "no-bind";
        case FREEZE_DIAG_IOP_TIMEOUT:
            return "timeout";
        case FREEZE_DIAG_IOP_CALL_FAILED:
            return "call-failed";
        default:
            return "bad-record";
    }
}

static const char *shutdown_status_name(unsigned int status)
{
    switch (status) {
        case FREEZE_DIAG_SHUTDOWN_DONE:
            return "done";
        case FREEZE_DIAG_SHUTDOWN_TIMEOUT:
            return "timeout";
        default:
            return "skipped";
    }
}

static const char *vmc_op_name(unsigned int op)
{
    return op == FREEZE_DIAG_VMC_WRITE ? "write" : "read";
}

int freeze_diag_format(const freeze_diag_report_t *r, const char *build, char *out, int cap)
{
    fd_buf_t b;
    unsigned int i, iop_status, busy_ms = 0, vmc_busy_ms = 0;
    const freeze_diag_iop_t *iop = &r->iop;

    if (out == 0 || cap <= 0)
        return 0;
    b.out = out;
    b.cap = cap;
    b.len = 0;

    iop_status = r->iop_status;
    if (iop_status == FREEZE_DIAG_IOP_ANSWERED && (iop->magic != FREEZE_DIAG_MAGIC || iop->version != FREEZE_DIAG_VERSION))
        iop_status = FREEZE_DIAG_IOP_BAD_RECORD;

    put_str(&b, "RiptOPL in-game freeze report v1\n");
    put_str(&b, "build=");
    put_str(&b, build != 0 ? build : "?");
    put_char(&b, '\n');

    put_str(&b, "game=");
    for (i = 0; i < sizeof(r->game_id) && r->game_id[i] != '\0'; i++)
        put_char(&b, r->game_id[i]);
    put_char(&b, '\n');

    put_str(&b, "mode=");
    put_dec(&b, r->game_mode);
    put_str(&b, " compat=");
    put_hex(&b, r->compat);
    put_field(&b, "cheats", r->cheats);
    put_field(&b, "gsm", r->gsm);
    put_char(&b, '\n');

    put_str(&b, "iop_resets=");
    put_dec(&b, r->iop_resets);
    put_field(&b, "failed_resets", r->iop_reset_failures);
    put_field(&b, "igr_polls", r->igr_polls);
    put_field(&b, "padopen_hooked", r->padopen_hooked);
    put_field(&b, "libpad", r->libpad);
    put_field(&b, "pad_state", r->pad_state);
    put_field(&b, "pad_frame", r->pad_frame);
    put_char(&b, '\n');

    put_str(&b, "iop=");
    put_str(&b, iop_status_name(iop_status));
    put_str(&b, " shutdown=");
    put_str(&b, shutdown_status_name(r->shutdown_status));
    put_char(&b, '\n');

    if (iop_status == FREEZE_DIAG_IOP_ANSWERED) {
        if (iop->busy)
            busy_ms = elapsed_ms(iop->busy_start_hi, iop->busy_start_lo, iop->now_hi, iop->now_lo);
        if (iop->vmc_busy)
            vmc_busy_ms = elapsed_ms(iop->vmc_busy_start_hi, iop->vmc_busy_start_lo, iop->now_hi, iop->now_lo);

        put_str(&b, "disc_reads=");
        put_dec(&b, iop->reads);
        put_field(&b, "read_errors", iop->read_errors);
        put_str(&b, " last_err=");
        put_hex(&b, iop->last_err);
        put_field(&b, "eom_hits", iop->eom_hits);
        put_field(&b, "last_lsn", iop->last_lsn);
        put_field(&b, "last_sectors", iop->last_sectors);
        put_field(&b, "media_lsn", iop->media_lsn_count);
        put_char(&b, '\n');

        put_str(&b, "read_busy=");
        put_dec(&b, iop->busy);
        if (iop->busy) {
            put_field(&b, "busy_lsn", iop->busy_lsn);
            put_field(&b, "busy_sectors", iop->busy_sectors);
            put_field(&b, "busy_ms", busy_ms);
        }
        put_field(&b, "max_read_ms", iop->max_read_ms);
        put_field(&b, "slow_reads", iop->slow_reads);
        put_char(&b, '\n');

        put_str(&b, "vmc_ops=");
        put_dec(&b, iop->vmc_ops);
        if (iop->vmc_ops != 0) {
            put_str(&b, " vmc_last_op=");
            put_str(&b, vmc_op_name(iop->vmc_last_op));
            put_field(&b, "vmc_last_lba", iop->vmc_last_lba);
        }
        put_char(&b, '\n');
        put_str(&b, "vmc_busy=");
        put_dec(&b, iop->vmc_busy);
        if (iop->vmc_busy) {
            put_str(&b, " vmc_busy_op=");
            put_str(&b, vmc_op_name(iop->vmc_busy_op));
            put_field(&b, "vmc_busy_lba", iop->vmc_busy_lba);
            put_field(&b, "vmc_busy_ms", vmc_busy_ms);
        }
        put_char(&b, '\n');
    }

    // One line a person can act on. Most specific first.
    put_str(&b, "hint=");
    if (iop_status != FREEZE_DIAG_IOP_ANSWERED) {
        put_str(&b, "the IOP did not answer: the I/O processor itself is stuck");
    } else if (iop->busy) {
        put_str(&b, "a disc read started ");
        put_dec(&b, busy_ms);
        put_str(&b, " ms ago and never returned (the storage device stalled)");
    } else if (iop->vmc_busy) {
        put_str(&b, "a memory card (VMC) ");
        put_str(&b, vmc_op_name(iop->vmc_busy_op));
        put_str(&b, " started ");
        put_dec(&b, vmc_busy_ms);
        put_str(&b, " ms ago and never returned");
    } else if (r->shutdown_status == FREEZE_DIAG_SHUTDOWN_TIMEOUT) {
        put_str(&b, "the IOP answered, but OPL's shutdown on it never finished (a device or lock is held)");
    } else if (iop->read_errors != 0) {
        put_str(&b, "disc reads failed");
    } else if (iop->eom_hits != 0) {
        put_str(&b, "the game read past the measured end of the image");
    } else {
        put_str(&b, "disc and VMC idle: the game is stuck on the EE side (see threads)");
    }
    put_char(&b, '\n');

    for (i = 0; i < r->thread_count && i < FREEZE_DIAG_MAX_THREADS; i++) {
        const freeze_diag_thread_t *t = &r->threads[i];
        const char *status = thread_status_name(t->status);
        const char *wait = wait_type_name(t->wait_type);

        put_str(&b, "thread id=");
        put_dec(&b, t->id);
        put_str(&b, " status=");
        if (status != 0)
            put_str(&b, status);
        else
            put_hex(&b, t->status);
        put_field(&b, "prio", t->prio);
        put_str(&b, " wait=");
        if (wait != 0)
            put_str(&b, wait);
        else
            put_dec(&b, t->wait_type);
        put_field(&b, "wait_id", t->wait_id);
        put_field(&b, "wakeup", t->wakeup);
        put_str(&b, " entry=");
        put_hex(&b, t->entry);
        put_char(&b, '\n');
    }
    if (r->threads_total > r->thread_count) {
        put_str(&b, "threads_not_listed=");
        put_dec(&b, r->threads_total - r->thread_count);
        put_char(&b, '\n');
    }

    out[b.len] = '\0';
    return b.len;
}
