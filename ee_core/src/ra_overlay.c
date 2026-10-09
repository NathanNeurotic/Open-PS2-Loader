#ifdef RETROACHIEVEMENTS
/* Adapted from Rian6/caduceus-opl, commit 2a98a9d (AFL-3.0). */
/*
  Caduceus RetroAchievements in-game card.
  RAU1 is received by raudp and DMA'd here as struct ra_event. Unlocks are
  rasterized once into a loader-owned IMAGE packet. No texture or additional
  VRAM is allocated; drawing contexts and display configuration stay intact.
  The passive display tracker observes writes only. Never intercept the game's
  GS status polling or inject primitives into its persistent drawing contexts.
*/
#include "ee_core.h"
#include "coreconfig.h"
#include "ra_overlay.h"
#include "padhook.h"
#include "../../modules/network/common/ra_snap.h"
#define GIF_D2_CHCR         (*(volatile u32 *)0x1000A000)
#define GIF_D2_MADR         (*(volatile u32 *)0x1000A010)
#define GIF_D2_QWC          (*(volatile u32 *)0x1000A020)
#define GIF_STAT            (*(volatile u32 *)0x10003020)
#define RA_GIF_BUSY         ((7u << 6) | (1u << 9) | (3u << 10) | (31u << 24))
#define GS_REG_BITBLTBUF    0x50
#define GS_REG_TRXPOS       0x51
#define GS_REG_TRXREG       0x52
#define GS_REG_TRXDIR       0x53
#define GS_GIF_AD           0x0E
#define RA_CARD_FRAMES      210
#define RA_CARD_W           192
#define RA_CARD_H           40
#define RA_CARD_MARGIN      16
#define RA_BUILD_ROWS       4
#define RA_PACKET_HEADER_QW 6
#define RA_PACKET_BYTES     (RA_PACKET_HEADER_QW * 16 + RA_CARD_W * RA_CARD_H * 4)
/* The GS privileged display registers are write-only/unreliable to read back
   on retail hardware. GSM already has a write breakpoint that records every
   value a game sends there. RA enables that tracker in pass-through mode when
   GSM is disabled, and consumes the recorded values here. Keep this layout in
   sync with struct GSMSourceGSRegs in igs_api.h / gsm_engine.S. */
struct ra_gs_source_regs
{
    u64 pmode;
    u64 smode1;
    u64 smode2;
    u64 srfsh;
    u64 synch1;
    u64 synch2;
    u64 syncv;
    u64 dispfb1;
    u64 display1;
    u64 dispfb2;
    u64 display2;
};
extern struct ra_gs_source_regs GSMSourceGSRegs;
static struct ra_event ra_ovl_event __attribute__((aligned(64)));
static unsigned int ra_ovl_seen;
static unsigned int ra_ovl_start;
static unsigned int ra_ovl_id;
static unsigned int ra_ovl_points;
static char ra_ovl_title[64];
static int ra_dirty = 1;
static int ra_build_row, ra_build_active;
static int ra_ovl_running;
/* Transfer header plus IMAGE pixel payload. */
static u64 *ra_pkt = NULL; /* packet lives in module storage, not ee_core .bss */
static int ra_pixel_bytes;
static unsigned int ra_packet_qwc;
static const unsigned short ra_font[67] = {
    /* A-Z, digits, punctuation, a-z; 3x5, row-major. */
    0x5bea, 0x3aeb, 0x624e, 0x3b6b, 0x72cf, 0x12cf, 0x6b4e, 0x5bed, 0x7497, 0x2b24, 0x5aed, 0x7249, 0x5bfd, 0x5ffd, 0x2b6a, 0x12eb, 0x6f6a, 0x5aeb, 0x388e, 0x2497, 0x7b6d, 0x2b6d, 0x5fed, 0x5aad, 0x24ad, 0x72a7, 0x7b6f, 0x749a, 0x72a3, 0x38a3, 0x49ed, 0x38cf, 0x2ace, 0x24a7, 0x2aaa, 0x39aa, 0x5d0, 0x1c0, 0x2000,
    0x7b70, 0x3ac9, 0x6270, 0x6ba4, 0x6750, 0x25d6, 0x3d70, 0x5ac9, 0x2482, 0x2b04, 0x56e9, 0x7493, 0x5fd8, 0x5b58, 0x2b50, 0x1758, 0x4d70, 0x1270, 0x3cf0, 0x64ba, 0x6b68, 0x2b68, 0x2fe8, 0x54a8, 0x39a8, 0x7538, 0x2092, 0x12};
/* IMAGE transfer changes no PRIM, TEST, FRAME, ZBUF or drawing context.
   Pixel storage is loader-owned; no allocation occurs in the game. */
static void sprite(int x0, int y0, int x1, int y1, unsigned int c)
{
    int x, y;
    u8 *pixels = (u8 *)ra_pkt + RA_PACKET_HEADER_QW * 16;
    unsigned int pixel = (c & 0xffffff) | 0x80000000u;
    if (ra_pixel_bytes == 2)
        pixel = ((c & 0xf8) >> 3) | ((c & 0xf800) >> 6) | ((c & 0xf80000) >> 9) | 0x8000;
    if (x0 < 0)
        x0 = 0;
    if (y0 < 0)
        y0 = 0;
    if (x1 > RA_CARD_W)
        x1 = RA_CARD_W;
    if (y1 > RA_CARD_H)
        y1 = RA_CARD_H;
    if (ra_build_active) {
        if (y0 < ra_build_row)
            y0 = ra_build_row;
        if (y1 > ra_build_row + RA_BUILD_ROWS)
            y1 = ra_build_row + RA_BUILD_ROWS;
    }
    for (y = y0; y < y1; y++)
        for (x = x0; x < x1; x++) {
            int index = y * RA_CARD_W + x;
            if (ra_pixel_bytes == 2)
                ((unsigned short *)pixels)[index] = pixel;
            else
                ((u32 *)pixels)[index] = pixel;
        }
}
static int glyph_index(char c)
{
    if (c >= 'a' && c <= 'z')
        return 39 + c - 'a';
    if (c >= 'A' && c <= 'Z')
        return c - 'A';
    if (c >= '0' && c <= '9')
        return 26 + c - '0';
    if (c == '+')
        return 36;
    if (c == '-')
        return 37;
    if (c == '!')
        return 65;
    if (c == '\'')
        return 66;
    if (c == '.')
        return 38;
    if (c == ',')
        return 38;
    return -1;
}
static void text3x5(int x, int y, const char *s, int scale, unsigned int c)
{
    int i, row, col, gi;
    unsigned short bits;
    if (ra_build_active && (y >= ra_build_row + RA_BUILD_ROWS || y + 5 * scale <= ra_build_row))
        return;
    for (i = 0; s[i]; i++) {
        gi = glyph_index(s[i]);
        if (gi >= 0) {
            bits = ra_font[gi];
            for (row = 0; row < 5; row++) {
                for (col = 0; col < 3;) {
                    int start = col;
                    if (!(bits & (1u << (row * 3 + col)))) {
                        col++;
                        continue;
                    }
                    while (col < 3 && (bits & (1u << (row * 3 + col))))
                        col++;
                    sprite(x + start * scale, y + row * scale,
                           x + col * scale, y + (row + 1) * scale, c);
                }
            }
        }
        x += 4 * scale;
    }
}
static void u32dec(char *dst, unsigned int v)
{
    char tmp[11];
    int n = 0, i;
    if (!v) {
        dst[0] = '0';
        dst[1] = 0;
        return;
    }
    while (v && n < 10) {
        tmp[n++] = '0' + v % 10;
        v /= 10;
    }
    for (i = 0; i < n; i++)
        dst[i] = tmp[n - i - 1];
    dst[n] = 0;
}
static int valid_display_fb(u64 fb)
{
    unsigned int fbw = (fb >> 9) & 0x3F;
    unsigned int psm = (fb >> 15) & 0x1F;
    return fbw != 0 && (psm == 0 || psm == 1 || psm == 2 || psm == 10);
}
/* Select the same display circuit the game enabled. Some titles keep both
   enabled while switching, so prefer a valid enabled circuit and then a valid
   alternate circuit. Unsupported framebuffer formats skip the card. */
static int tracked_display(u64 *fb, u64 *display, u64 *pmode)
{
    u64 p = GSMSourceGSRegs.pmode;
    u64 f1 = GSMSourceGSRegs.dispfb1;
    u64 f2 = GSMSourceGSRegs.dispfb2;
    u64 d1 = GSMSourceGSRegs.display1;
    u64 d2 = GSMSourceGSRegs.display2;
    if ((p & 1) && valid_display_fb(f1)) {
        *fb = f1;
        *display = d1;
    } else if ((p & 2) && valid_display_fb(f2)) {
        *fb = f2;
        *display = d2;
    } else if (valid_display_fb(f1)) {
        *fb = f1;
        *display = d1;
    } else if (valid_display_fb(f2)) {
        *fb = f2;
        *display = d2;
    } else {
        return 0;
    }
    if (pmode != NULL)
        *pmode = p;
    return 1;
}
static int draw_card(void)
{
    u64 fb, display;
    unsigned int fbp, fbw, psm, dbx, dby;
    int width, visible_width, visible_height, x, y, pixel_dirty, header_dirty;
    u64 transfer_fb, transfer_pos;
    char id[12], pts[12], line[20];
    int i, j;
    if (ra_pkt == NULL)
        return 0;
    if (!tracked_display(&fb, &display, NULL))
        return 0;
    /* Never modify a packet still owned by the GIF DMA channel. */
    if ((GIF_D2_CHCR & 0x100) || (GIF_STAT & RA_GIF_BUSY))
        return 1;
    fbp = fb & 0x1FF;
    fbw = (fb >> 9) & 0x3F;
    psm = (fb >> 15) & 0x1F;
    dbx = (fb >> 32) & 0x7FF;
    dby = (fb >> 43) & 0x7FF;
    /* GS FRAME supports the four formats the PCRTC can normally display. */
    if (!valid_display_fb(fb))
        return 0;
    width = fbw * 64;
    if (width < RA_CARD_W + 8 || width > 2048)
        return 0;
    /* FBW is the VRAM stride, not necessarily the visible width. DISPLAY's
       DW/MAGH gives the visible pixel count; using it keeps the card on-screen
       in games whose render target is wider than their output area. */
    visible_width = (int)(((display >> 32) & 0xFFF) + 1);
    visible_width /= (int)(((display >> 23) & 0xF) + 1);
    if (visible_width < RA_CARD_W + 8 || visible_width > width)
        visible_width = width;
    visible_height = (int)(((display >> 44) & 0x7FF) + 1) / (int)(((display >> 27) & 3) + 1);
    if (visible_height < RA_CARD_H + 18)
        return 0;
    x = (int)dbx + visible_width - RA_CARD_W - RA_CARD_MARGIN;
    y = (int)dby + 18;
    if (x < (int)dbx)
        x = dbx + 8;
    if (x < 0 || y < 0 || x + RA_CARD_W > width || y + RA_CARD_H > 2048)
        return 0;
    pixel_dirty = ra_dirty || ra_pixel_bytes != ((psm == 2 || psm == 10) ? 2 : 4);
    if (pixel_dirty) {
        ra_dirty = 1; /* format-only rebuilds also stay pending until the last slice */
        if (ra_pixel_bytes != ((psm == 2 || psm == 10) ? 2 : 4))
            ra_build_row = 0;
        ra_pixel_bytes = (psm == 2 || psm == 10) ? 2 : 4;
        ra_build_active = 1;
        /* Raster coordinates are local to the card; position is in TRXPOS. */
        {
            int pixel_x = x, pixel_y = y;
            x = 0;
            y = 0;
            /* Compact layout adapted from the reference card renderer. */
            sprite(0, 0, RA_CARD_W, RA_CARD_H, 0x10140F);
            sprite(0, 0, 3, RA_CARD_H, 0x72F2D3);
            sprite(8, 10, 12, 18, 0x58C8F4);
            sprite(23, 10, 27, 18, 0x58C8F4);
            sprite(11, 8, 24, 20, 0x58C8F4);
            sprite(15, 21, 21, 24, 0x58C8F4);
            sprite(16, 24, 20, 29, 0x58C8F4);
            sprite(12, 29, 24, 32, 0x58C8F4);
            text3x5(32, 6, "ACHIEVEMENT UNLOCKED", 1, 0x72F2D3);
            if (ra_ovl_title[0]) {
                char title[20];
                for (i = 0; i < 19 && ra_ovl_title[i]; i++)
                    title[i] = ra_ovl_title[i];
                title[i] = 0;
                if (i == 19 && ra_ovl_title[i])
                    title[16] = title[17] = title[18] = '.';
                text3x5(32, 16, title, 2, 0xE8F0E5);
            } else {
                u32dec(id, ra_ovl_id);
                line[0] = 'I';
                line[1] = 'D';
                line[2] = ' ';
                i = 3;
                for (j = 0; id[j] && i < 18; j++)
                    line[i++] = id[j];
                line[i] = 0;
                text3x5(32, 16, line, 2, 0xE8F0E5);
            }
            u32dec(pts, ra_ovl_points);
            line[0] = '+';
            i = 1;
            for (j = 0; pts[j] && i < 11; j++)
                line[i++] = pts[j];
            line[i++] = ' ';
            line[i++] = 'P';
            line[i++] = 'O';
            line[i++] = 'I';
            line[i++] = 'N';
            line[i++] = 'T';
            if (ra_ovl_points != 1)
                line[i++] = 'S';
            line[i] = 0;
            text3x5(32, 31, line, 1, 0x72F2D3);
            x = pixel_x;
            y = pixel_y;
        }
        ra_build_active = 0;
        /* Bounded work per interrupt; never submit an incomplete IMAGE packet. */
        {
            u8 *pixels = (u8 *)ra_pkt + RA_PACKET_HEADER_QW * 16;
            int end = ra_build_row + RA_BUILD_ROWS;
            if (end > RA_CARD_H)
                end = RA_CARD_H;
            iSyncDCache(pixels + ra_build_row * RA_CARD_W * ra_pixel_bytes,
                        pixels + end * RA_CARD_W * ra_pixel_bytes);
            ra_build_row = end;
            if (end < RA_CARD_H)
                return 1;
            ra_build_row = 0;
        }
        ra_packet_qwc = RA_PACKET_HEADER_QW + RA_CARD_W * RA_CARD_H * ra_pixel_bytes / 16;
        ra_pkt[0] = 4 | ((u64)1 << 60); /* four packed AD entries, followed by IMAGE */
        ra_pkt[1] = GS_GIF_AD;
        ra_pkt[10] = (u64)(ra_packet_qwc - RA_PACKET_HEADER_QW) | ((u64)1 << 15) | ((u64)2 << 58);
        ra_pkt[11] = 0;
        ra_dirty = 0;
    }
    /* Setup host-to-local transfer. Geometry can change without rebuilding pixels. */
    transfer_fb = ((u64)(fbp << 5) << 32) | ((u64)fbw << 48) | ((u64)(psm == 1 ? 0 : psm) << 56);
    transfer_pos = ((u64)x << 32) | ((u64)y << 48);
    header_dirty = pixel_dirty || ra_pkt[2] != transfer_fb || ra_pkt[4] != transfer_pos;
    if (header_dirty) {
        ra_pkt[2] = transfer_fb;
        ra_pkt[3] = GS_REG_BITBLTBUF;
        ra_pkt[4] = transfer_pos;
        ra_pkt[5] = GS_REG_TRXPOS;
        ra_pkt[6] = RA_CARD_W | ((u64)RA_CARD_H << 32);
        ra_pkt[7] = GS_REG_TRXREG;
        ra_pkt[8] = 0;
        ra_pkt[9] = GS_REG_TRXDIR;
    }
    if (header_dirty)
        iSyncDCache(ra_pkt, ra_pkt + 16);
    if ((GIF_D2_CHCR & 0x100) || (GIF_STAT & RA_GIF_BUSY))
        return 1;
    GIF_D2_QWC = ra_packet_qwc;
    GIF_D2_MADR = (u32)ra_pkt;
    GIF_D2_CHCR = 0x101;
    return 1;
}
void RA_OverlaySetPacketBuffer(void *buffer)
{
    ra_pkt = (u64 *)buffer;
    ra_dirty = 1;
    ra_build_row = 0;
    ra_pixel_bytes = 0;
    ra_ovl_running = 0;
}
void *RA_OverlayEventBuffer(void)
{
    struct ra_event *e = (struct ra_event *)UNCACHED_SEG(&ra_ovl_event);
    e->magic = e->seq = e->kind = e->arg = e->commit = 0;
    ra_ovl_seen = 0;
    if (g_ee_core_config.raClientMode == 0)
        return RA_PulseEventBuffer();
    return &ra_ovl_event;
}
void RA_OverlayOnVblank(unsigned int frames)
{
    const volatile struct ra_event *e = (const volatile struct ra_event *)UNCACHED_SEG(&ra_ovl_event);
    unsigned int kind;
    if (g_ee_core_config.raClientMode == 0) {
        RA_PulseOnVblank(frames);
        return;
    }
    if (e->magic == RA_EVENT_MAGIC && e->seq != ra_ovl_seen && e->commit == e->seq) {
        struct ra_event notice = *e;
        if (e->seq != notice.seq || e->commit != notice.seq)
            return;
        kind = notice.kind & RA_EVENT_KIND_MASK;
        ra_ovl_seen = notice.seq;
        if (kind == RA_EVENT_RESET) {
            IGR_RequestReset();
            return;
        }
        if (kind == RA_EVENT_UNLOCK) {
            int i;
            for (i = 0; i < 63; i++) {
                ra_ovl_title[i] = notice.title[i];
                if (!ra_ovl_title[i])
                    break;
            }
            ra_ovl_title[63] = 0;
            ra_dirty = 1;
            ra_build_row = 0;
            ra_ovl_id = notice.arg;
            ra_ovl_points = RA_EVENT_POINTS(notice.kind);
            ra_ovl_start = frames;
            ra_ovl_running = 1;
        }
    }
    if (!ra_ovl_running)
        return;
    if (frames - ra_ovl_start >= RA_CARD_FRAMES) {
        ra_ovl_running = 0;
        return;
    }
    /* Unavailable display/path: retry later without changing PMODE/BGCOLOR. */
    draw_card();
}
#endif
