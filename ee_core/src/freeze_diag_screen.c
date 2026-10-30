/*
  In-game freeze report on the TV (INGAMEDIAG flavour only).

  The memory-card report needs the IOP: the RPC that fetches its record, the reboot, MCMAN. A game whose IOP is
  stuck gets none of that, and the IGR path stops at the first SIF call with nothing written. So before any of it,
  ee_core draws the report itself: its own 640x448 frame at FBP 0 (the game's frame is gone: the VBLANK handler has
  reset the GS), the font of the in-game menu at twice its size, uploaded through GIF PATH3. The player takes a photo
  of the screen, then taps the power button to go on to the memory-card report as before.

  Everything shown is read from EE memory and IOP RAM (KSEG1), never asked of the IOP.

  FREEZE_DIAG_SCREEN_HOST_TEST builds only the page composer, for tests/.
*/

#ifndef FREEZE_DIAG_SCREEN_HOST_TEST
#include "ee_core.h"
#include "padhook.h"
#include "freeze_diag_core.h"
#endif
#include "freeze_diag_report.h"
#include "freeze_diag_screen.h"

static void fds_put(fds_page_t *p, int row, int colour, const char *s)
{
    int i;

    if (row < 0 || row >= FDS_LINES)
        return;
    p->colour[row] = (unsigned char)colour;
    for (i = 0; i < FDS_CHARS && s[i] != '\0'; i++)
        p->text[row][i] = s[i];
    for (; i <= FDS_CHARS; i++)
        p->text[row][i] = '\0';
}

typedef struct
{
    char s[FDS_CHARS + 1];
    int n;
} fds_line_t;

static void ln_str(fds_line_t *l, const char *s)
{
    while (*s != '\0' && l->n < FDS_CHARS)
        l->s[l->n++] = *s++;
    l->s[l->n] = '\0';
}

static void ln_dec(fds_line_t *l, unsigned int v)
{
    char d[10];
    int n = 0;

    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v != 0);
    while (n > 0 && l->n < FDS_CHARS)
        l->s[l->n++] = d[--n];
    l->s[l->n] = '\0';
}

static void ln_hex(fds_line_t *l, unsigned int v, int digits) // digits 0: as few as it takes
{
    static const char hex[] = "0123456789ABCDEF";
    int i;

    if (digits == 0)
        for (digits = 1; digits < 8 && (v >> (4 * digits)) != 0; digits++)
            ;
    for (i = digits - 1; i >= 0 && l->n < FDS_CHARS; i--)
        l->s[l->n++] = hex[(v >> (4 * i)) & 0xF];
    l->s[l->n] = '\0';
}

static void ln_where(fds_line_t *l, const heap_diag_iop_t *h, unsigned int addr)
{
    unsigned int i, n = h->module_count < HEAP_DIAG_MODULES ? h->module_count : HEAP_DIAG_MODULES;
    int c;

    for (i = 0; i < n; i++) {
        const heap_diag_module_t *m = &h->modules[i];

        if (m->text_start != 0 && addr >= m->text_start && addr - m->text_start < m->size) {
            for (c = 0; c < 8 && m->name[c] != '\0' && l->n < FDS_CHARS; c++)
                l->s[l->n++] = m->name[c];
            l->s[l->n] = '\0';
            ln_str(l, "+");
            ln_hex(l, addr - m->text_start, 0);
            return;
        }
    }
    ln_hex(l, addr, 8);
}

static const char *fds_trigger(unsigned int t)
{
    switch (t) {
        case FREEZE_DIAG_TRIGGER_STALL:
            return "PAD DATA STOPPED (IOP STUCK?)";
        case FREEZE_DIAG_TRIGGER_POWER:
            return "POWER BUTTON";
        default:
            return "IGR COMBO";
    }
}

void freeze_diag_screen_compose(const freeze_diag_report_t *r, const heap_diag_snapshot_t *h, fds_page_t *p, int saving)
{
    unsigned char used[HEAP_DIAG_BLOCKS];
    fds_line_t l;
    int row = 0, last = FDS_LINES - 3, i, j;

    for (i = 0; i < FDS_LINES; i++)
        fds_put(p, i, FDS_C_TEXT, "");

    l.n = 0;
    ln_str(&l, "RIPTOPL FREEZE REPORT  ");
    for (i = 0; i < (int)sizeof(r->game_id) && r->game_id[i] != '\0'; i++) {
        char c[2] = {r->game_id[i], '\0'};
        ln_str(&l, c);
    }
    fds_put(p, row++, FDS_C_TITLE, l.s);

    l.n = 0;
    ln_str(&l, "TRIGGER: ");
    ln_str(&l, fds_trigger(r->trigger));
    fds_put(p, row++, FDS_C_TEXT, l.s);

    l.n = 0;
    ln_str(&l, "PAD FRAME ");
    ln_dec(&l, r->pad_frame);
    ln_str(&l, " STATE ");
    ln_dec(&l, r->pad_state);
    ln_str(&l, " POLLS ");
    ln_dec(&l, r->igr_polls);
    ln_str(&l, " RESETS ");
    ln_dec(&l, r->iop_resets);
    fds_put(p, row++, FDS_C_TEXT, l.s);

    l.n = 0;
    ln_str(&l, "MODE ");
    ln_dec(&l, r->game_mode);
    ln_str(&l, " COMPAT ");
    ln_hex(&l, r->compat, 0);
    ln_str(&l, " PADEMU ");
    ln_dec(&l, r->pademu);
    ln_str(&l, " GSM ");
    ln_dec(&l, r->gsm);
    ln_str(&l, " CHEATS ");
    ln_dec(&l, r->cheats);
    fds_put(p, row++, FDS_C_TEXT, l.s);

    if (!h->found || h->iop.version != HEAP_DIAG_VERSION) {
        fds_put(p, row++, FDS_C_WARN, "IOP HEAP RECORD: NOT FOUND");
    } else {
        const heap_diag_iop_t *iop = &h->iop;
        int shown = 0;

        l.n = 0;
        ln_str(&l, "ALLOCS ");
        ln_dec(&l, iop->allocs);
        ln_str(&l, " FREES ");
        ln_dec(&l, iop->frees);
        ln_str(&l, " FAILS ");
        ln_dec(&l, iop->fails);
        ln_str(&l, " EVICTED ");
        ln_dec(&l, iop->evicted);
        fds_put(p, row++, FDS_C_TEXT, l.s);

        l.n = 0;
        ln_str(&l, "FREE NOW ");
        ln_dec(&l, iop->free_now);
        ln_str(&l, " MIN ");
        ln_dec(&l, iop->free_min);
        ln_str(&l, " LARGEST ");
        ln_dec(&l, iop->largest_min);
        fds_put(p, row++, FDS_C_TEXT, l.s);

        // The failed allocations first: the newest first, as the ring keeps them.
        for (i = 0; i < HEAP_DIAG_FAILS && row < last; i++) {
            const heap_diag_block_t *f = &iop->failed[(iop->fail_next + HEAP_DIAG_FAILS - 1 - i) % HEAP_DIAG_FAILS];

            if (f->size == 0 && f->ra == 0)
                continue;
            l.n = 0;
            ln_str(&l, "FAILED ALLOC ");
            ln_dec(&l, f->size);
            ln_str(&l, " BY ");
            ln_where(&l, iop, f->ra);
            fds_put(p, row++, FDS_C_WARN, l.s);
        }

        // Then the live blocks with the longest 0xFF run after their end: the overruns.
        fds_put(p, row++, FDS_C_DIM, "BLOCK    SIZE  FF AFTER  CALLER");
        for (i = 0; i < HEAP_DIAG_BLOCKS; i++)
            used[i] = 0;
        while (row < last) {
            int best = -1;

            for (j = 0; j < HEAP_DIAG_BLOCKS; j++)
                if (!used[j] && iop->blocks[j].addr != 0 && h->tail_ff[j] != 0 && (best < 0 || h->tail_ff[j] > h->tail_ff[best]))
                    best = j;
            if (best < 0)
                break;
            used[best] = 1;
            l.n = 0;
            ln_hex(&l, iop->blocks[best].addr, 8);
            ln_str(&l, " ");
            ln_dec(&l, iop->blocks[best].size);
            ln_str(&l, " FF=");
            ln_dec(&l, h->tail_ff[best]);
            ln_str(&l, " ");
            ln_where(&l, iop, iop->blocks[best].ra);
            fds_put(p, row++, h->tail_ff[best] >= FDS_OVERRUN_MIN ? FDS_C_WARN : FDS_C_TEXT, l.s);
            shown++;
        }
        if (shown == 0 && row < last)
            fds_put(p, row++, FDS_C_TEXT, "NO 0XFF RUN AFTER ANY LIVE BLOCK");
    }

    if (saving) {
        fds_put(p, FDS_LINES - 2, FDS_C_TITLE, "SAVING RIPTFRZ.TXT TO MEMORY CARD 1...");
        fds_put(p, FDS_LINES - 1, FDS_C_DIM, "STILL HERE AFTER A MINUTE: HOLD POWER");
    } else {
        fds_put(p, FDS_LINES - 2, FDS_C_TITLE, "TAKE A PHOTO OF THIS SCREEN, THEN");
        fds_put(p, FDS_LINES - 1, FDS_C_TITLE, "TAP POWER ONCE TO SAVE RIPTFRZ.TXT");
    }
}

#ifndef FREEZE_DIAG_SCREEN_HOST_TEST

#define IGRM_FONT_DATA
#include "igrmfont.h"

// Room for this lives in the game's memory, which IGR is about to drop (as the heap snapshot does, freeze_diag.c).
#define FDS_PAGE ((fds_page_t *)0x01010000)
#define FDS_PKT  ((u64 *)0x01020000)

#define FDS_W       640
#define FDS_H       448
#define FDS_CELL_W  12 // a 6x8 font cell at twice its size
#define FDS_CELL_H  16
#define FDS_LEFT    2 // cells kept clear of the TV's overscan
#define FDS_TOP     1
#define FDS_BAND_QW (FDS_W * FDS_CELL_H * 4 / 16)

#define GIF_CTRL    ((vu32 *)0x10003000)
#define GIF_MODE    ((vu32 *)0x10003010)
#define D2_CHCR     ((vu32 *)0x1000a000)
#define D2_MADR     ((vu32 *)0x1000a010)
#define D2_QWC      ((vu32 *)0x1000a020)
#define GS_PMODE    ((vu64 *)0x12000000)
#define GS_DISPFB1  ((vu64 *)0x12000070)
#define GS_DISPLAY1 ((vu64 *)0x12000080)
#define GS_BGCOLOR  ((vu64 *)0x120000e0)

#define FDS_GIFTAG(nloop, eop, flg, nreg) ((u64)(nloop) | (u64)(eop) << 15 | (u64)(flg) << 58 | (u64)(nreg) << 60)

static const u32 fds_rgb[FDS_C_COUNT] = {
    0x80E6DCD2, // text
    0x8060FFFF, // title: yellow
    0x806090FF, // warning: orange
    0x80A09080, // quiet
};
#define FDS_BG 0x80401808 // dark blue

#define EE_TICKS_PER_MS 294912

static inline u32 fds_ticks(void)
{
    u32 c;
    __asm__ __volatile__("mfc0 %0, $9"
                         : "=r"(c));
    return c;
}

static void fds_wait_ms(u32 ms)
{
    u32 start = fds_ticks();

    while ((u32)(fds_ticks() - start) < ms * EE_TICKS_PER_MS)
        ;
}

static int fds_glyph(unsigned char c)
{
    if (c >= 'a' && c <= 'z')
        c -= 'a' - 'A';
    if (c < 32 || c > 95)
        c = '?';
    return c - 32;
}

// Text row band `band` (FDS_CELL_H frame lines) into the frame, through GIF PATH3.
static int fds_send_band(const fds_page_t *p, int band)
{
    u64 *q = FDS_PKT;
    u32 *px = (u32 *)(q + 12);
    int tr = band - FDS_TOP, y, x, i;

    for (y = 0; y < FDS_CELL_H; y++) {
        int gy = y >> 1;

        for (x = 0; x < FDS_W; x++) {
            int tc = x / FDS_CELL_W - FDS_LEFT, gx = (x % FDS_CELL_W) >> 1;
            u32 c = FDS_BG;

            if (tr >= 0 && tr < FDS_LINES && tc >= 0 && tc < FDS_CHARS && gy < 7 && gx < 5) {
                unsigned char ch = (unsigned char)p->text[tr][tc];

                if (ch != '\0' && (igrmFontData[fds_glyph(ch)][gy] & (0x10 >> gx)))
                    c = fds_rgb[p->colour[tr]];
            }
            *px++ = c;
        }
    }

    q[0] = FDS_GIFTAG(4, 0, 0, 1);
    q[1] = 0xe;                     // A+D
    q[2] = (u64)(FDS_W / 64) << 48; // BITBLTBUF: DBP 0, DBW 10, PSMCT32
    q[3] = 0x50;
    q[4] = (u64)(band * FDS_CELL_H) << 48; // TRXPOS: destination
    q[5] = 0x51;
    q[6] = (u64)FDS_W | (u64)FDS_CELL_H << 32; // TRXREG
    q[7] = 0x52;
    q[8] = 0; // TRXDIR: host -> local
    q[9] = 0x53;
    q[10] = FDS_GIFTAG(FDS_BAND_QW, 1, 2, 0); // IMAGE
    q[11] = 0;

    FlushCache(0);
    *D2_QWC = 6 + FDS_BAND_QW;
    *D2_MADR = (u32)q;
    *D2_CHCR = 0x101; // from memory, normal mode, start
    asm volatile("sync.l");
    for (i = 0; i < 10000000; i++)
        if (!(*D2_CHCR & 0x100))
            return 1;
    *D2_CHCR = 0; // a GIF that will not take data must not keep the transfer
    return 0;
}

static void fds_draw(const fds_page_t *p, int from, int to)
{
    int band;

    for (band = from; band < to; band++)
        if (!fds_send_band(p, band))
            return;
}

// The power-off request is latched until cancelled: a press counts once, when it appears (as igrmenu.c reads it).
static int fds_power_pending(void)
{
    int pending;

    ee_kmode_enter();
    pending = (*CDVD_R_NDIN & 0x20) && (*CDVD_R_POFF & 0x04);
    if (pending) {
        *CDVD_R_SDIN = 0x00;
        *CDVD_R_SCMD = 0x1B; // cancel the power off: this press asks for the memory-card report
    }
    ee_kmode_exit();
    return pending;
}

// From the IGR thread, after FreezeDiag_Begin and before anything asks the IOP. The VBLANK handler has stopped DMA,
// reset the GS and run ResetEE(0x7F): nothing of the game's can draw over this.
void FreezeDiag_Screen(const freeze_diag_report_t *r, const heap_diag_snapshot_t *h)
{
    fds_page_t *p = FDS_PAGE;
    int latched;

    freeze_diag_screen_compose(r, h, p, 0);

    *D2_CHCR = 0;
    *GIF_CTRL = 1; // reset the GIF: a game's packet cut off by the stop must not swallow ours
    *GIF_MODE = 0; // no PATH3 mask left by the game
    asm volatile("sync.l");

    // 640x448 NTSC interlaced, FIELD: every TV and capture card takes it, whatever the game used.
    SetGsCrt(1, 2, 0);
    *GS_PMODE = 0xff25;                   // circuit 1 only, alpha from ALP (0xff)
    *GS_DISPFB1 = (u64)(FDS_W / 64) << 9; // FBP 0, FBW 10, PSMCT32
    *GS_DISPLAY1 = 652 | (u64)50 << 12 | (u64)3 << 23 | (u64)(FDS_W * 4 - 1) << 32 | (u64)(FDS_H - 1) << 44;
    *GS_BGCOLOR = 0;
    fds_draw(p, 0, FDS_H / FDS_CELL_H);

    // The press that took the report may still be latched; a new one goes on.
    latched = fds_power_pending();
    for (;;) {
        int pending = fds_power_pending();

        if (pending && !latched)
            break;
        latched = pending;
        fds_wait_ms(20);
    }

    freeze_diag_screen_compose(r, h, p, 1);
    fds_draw(p, FDS_TOP + FDS_LINES - 2, FDS_TOP + FDS_LINES);
}

#endif
