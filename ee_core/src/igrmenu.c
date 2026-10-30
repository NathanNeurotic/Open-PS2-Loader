/*
  igrmenu.c the in-game menu

  Copyright 2026, RIPPS2 contributors (akilluminati47)
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Ported from RIPPS2 (akilluminati47/RIPPS2, ee_core/src/igrmenu.c, builds 87 to 108), without RIPSHOT and the
  achievements pages, plus a CHEATS page. With In-Game Menu on, L1+L2+R1+R2+SELECT+START pauses the game under a
  plain panel instead of leaving it: RESUME, CHEATS (when the launch brought the game's cheats), EXIT GAME and
  POWER OFF. EXIT GAME and POWER OFF take a second press. No animation: the panel is drawn when it opens and when
  the choice moves, and nothing in between.

  The method is ORBIT's in-game menu for its Neutrino fork (danielnuld/ps2-launcher, third_party/neutrino-igr/menu.c
  and igr.c, AFL-3.0), as RIPPS2 brought it to OPL's core. The game's GS drawing state is write-only, so it is never
  touched: the panel is rendered here in the shown frame's own pixel format and uploaded into that frame with image
  transfers through VIF1 DIRECT (PATH2), after a FLUSHA, leaving the game's PATH3 mask alone. The pixels under it are
  not saved; the game's next frames draw over them. Which frame is shown comes from GSM's record of the game's PMODE,
  SMODE2, DISPFB and DISPLAY writes (gsm_engine.S; the passive tracker when GSM itself is off).

  CHEATS: every cheat of the game's file, ON or OFF, changed with the confirm button and applied on RESUME through
  the engine's second code set (cheat_api.c CheatLiveApply). OFF stops a cheat writing; what it wrote stays until the
  game changes it.

  IGR_MENU_HOST_TEST builds only the renderer, for tests/ (a picture of the panel on the PC).
*/

#if defined(IGR_MENU) || defined(IGR_MENU_HOST_TEST) // RetroAchievements builds leave it out: ee_core has no room
#ifndef IGR_MENU_HOST_TEST
#include "ee_core.h"
#include "coreconfig.h"
#include "padhook.h"
#include "cheat_api.h"
#endif
#include "../include/igrcheats.h"
#include "../include/igrmenu.h"

// ---- the panel, in its own units (one font pixel at scale 1): 160 x 126, or 320 x 252 at scale 2
#define PW             160
#define PH             126
#define ROW_TITLE      4
#define ROW_SEP1       14
#define ROW_ITEM0      18
#define ITEM_STEP      10
#define ROW_SEP2       69
#define ROW_INFO0      73
#define INFO_STEP      10
#define ROW_HINT       115
#define IGRM_ITEMS_MAX 4 // RESUME, CHEATS, EXIT GAME, POWER OFF
#define TEXT_X         8
#define ITEM_X         20
#define TEXT_CHARS     24 // (PW - 2 * TEXT_X) / 6
#define CHEAT_ROWS     9  // the CHEATS page's rows, ITEM_STEP apart from ROW_ITEM0
#define CHEAT_CHARS    18 // a cheat's name on its row, before ON / OFF

enum { C_PANEL,
       C_BORDER,
       C_SEP,
       C_BAR,
       C_TITLE,
       C_DIM,
       C_ITEM,
       C_SEL,
       C_TEXT,
       C_GOLD,
       C_WARN,
       C_CROSS,
       C_CIRCLE,
       C_COUNT };
static const u8 igrmRgb[C_COUNT][3] = {
    {12, 16, 36},    // panel
    {72, 96, 168},   // border
    {36, 46, 88},    // separators
    {30, 44, 100},   // the selected row's bar
    {232, 236, 250}, // title
    {112, 122, 152}, // quiet text
    {150, 160, 190}, // items
    {255, 255, 255}, // the selected item
    {196, 204, 226}, // page text
    {255, 204, 96},  // a cheat that is on
    {255, 150, 120}, // what EXIT GAME costs
    {124, 178, 240}, // the pad's cross
    {240, 110, 110}, // the pad's circle
};

#define IGRM_FONT_DATA
#include "../include/igrmfont.h"

// what the pages say, gathered by IGR_MenuRun (or a test)
typedef struct
{
    int confirmCircle;    // the launcher's confirm button is Circle
    const char *gameId;   // "" = none
    const char *exitPath; // "" = the browser
    int canPowerOff;      // not a disc game (the ROM's CDVDMAN keeps the power button)
    igr_cheats_t *cheats; // the CHEATS page's list, or NULL (no page)
    int cheatsBusy;       // a change could not be applied (the engine was walking the set): try again later
    int cheatsIdle;       // the engine's hook has not run once this game: no cheat is being applied
} igrm_info_t;

#define IGRM_LINES 24
#define IGRM_CHARS (TEXT_CHARS + 2)
typedef struct
{
    short y, x, len;
    u8 colour;
    u8 glyph[IGRM_CHARS];
} igrm_line_t;
static igrm_line_t *igrmLine; // on the IGR thread's stack while the menu is open
static int igrmLines;
static int igrmBarY;                // the selected row's bar, in panel units
static int igrmSep2 = ROW_SEP2;     // the second separator's row (-1: none, as the CHEATS page has)
static int igrmSx, igrmSy, igrmBpp; // scale, and the shown frame's bytes per pixel

static int igrmGlyph(unsigned char c)
{
    if (c >= 1 && c <= 3)
        return G_CROSS + c - 1;
    if (c == '~')
        return G_TILDE;
    if (c >= 'a' && c <= 'z')
        c -= 'a' - 'A';
    if (c < 32 || c > 95)
        c = '?';
    return c - 32;
}

static int igrmLen(const char *s)
{
    int n = 0;
    while (s[n])
        n++;
    return n;
}

static void igrmTextN(int y, int x, int colour, const char *s, int max)
{
    igrm_line_t *l;
    int i;

    if (igrmLines >= IGRM_LINES)
        return;
    l = &igrmLine[igrmLines++];
    l->y = y;
    l->x = x;
    l->colour = colour;
    for (i = 0; i < IGRM_CHARS && i < max && s[i]; i++)
        l->glyph[i] = igrmGlyph((unsigned char)s[i]);
    l->len = i;
}

static void igrmText(int y, int x, int colour, const char *s)
{
    igrmTextN(y, x, colour, s, IGRM_CHARS);
}

static void igrmRight(int y, int colour, const char *s) // ends at the panel's right margin
{
    igrmText(y, PW - TEXT_X - (igrmLen(s) * 6 - 1), colour, s);
}

static char *igrmCat(char *d, const char *s)
{
    while (*s)
        *d++ = *s++;
    *d = '\0';
    return d;
}

static char *igrmNum(char *d, int n)
{
    char t[12];
    int i = 0;

    if (n < 0)
        n = 0;
    do {
        t[i++] = '0' + n % 10;
        n /= 10;
    } while (n && i < 11);
    while (i)
        *d++ = t[--i];
    *d = '\0';
    return d;
}

static int igrmEndsWith(const char *s, const char *tail) // case-insensitive
{
    int n = igrmLen(s), m = igrmLen(tail), i;

    if (n < m)
        return 0;
    for (i = 0; i < m; i++) {
        char a = s[n - m + i], b = tail[i];
        if (a >= 'a' && a <= 'z')
            a -= 'a' - 'A';
        if (a != b)
            return 0;
    }
    return 1;
}

// a path in two lines of the page at most, broken after a '/' or a space when one is near the end of the
// first; a longer one keeps its end, after "..."
static void igrmPath(int y, const char *path)
{
    char a[TEXT_CHARS + 1], b[TEXT_CHARS + 1];
    int n = igrmLen(path), i, cut = TEXT_CHARS, start = 0, rest;

    if (n > 2 * TEXT_CHARS - 3) {
        path += n - (2 * TEXT_CHARS - 6);
        igrmCat(a, "...");
        start = 3;
    }
    rest = igrmLen(path);
    if (rest + start > TEXT_CHARS) // i: the path's characters on the first line; the second holds the rest
        for (i = TEXT_CHARS - start; i >= rest - TEXT_CHARS && i > 4; i--)
            if (path[i - 1] == '/' || path[i - 1] == ' ') {
                cut = start + i;
                break;
            }
    for (i = start; i < cut && *path; i++)
        a[i] = *path++;
    a[i] = '\0';
    if (*path == ' ')
        path++;
    for (i = 0; i < TEXT_CHARS && *path; i++)
        b[i] = *path++;
    b[i] = '\0';
    igrmText(y, TEXT_X, C_TITLE, a);
    if (b[0])
        igrmText(y + INFO_STEP, TEXT_X, C_TITLE, b);
}

// ---- the pages

enum { IT_RESUME,
       IT_CHEATS,
       IT_EXIT,
       IT_POWER };
static const char *const igrmName[4] = {"RESUME", "CHEATS", "EXIT GAME", "POWER OFF"};
static u8 igrmIds[IGRM_ITEMS_MAX];
static int igrmItems;

static void igrmListItems(const igrm_info_t *in)
{
    int i;

    igrmItems = 0;
    for (i = IT_RESUME; i <= IT_POWER; i++)
        if (i != IT_CHEATS || in->cheats != NULL)
            igrmIds[igrmItems++] = i;
}

static int igrmCheatsOn(const igr_cheats_t *b)
{
    const igr_cheat_t *row = IGR_CHEATS_ROWS(b);
    int n = 0, i;

    for (i = 0; i < (int)b->count; i++)
        n += row[i].on != 0;
    return n;
}

static void igrmTitle(const char *left, const char *right)
{
    igrmSep2 = ROW_SEP2;
    igrmText(ROW_TITLE, TEXT_X, C_TITLE, left);
    igrmRight(ROW_TITLE, C_DIM, right);
}

static void igrmCompose(const igrm_info_t *in, int sel, int armed)
{
    char s[40], *p, ok[2] = {(char)(in->confirmCircle ? 2 : 1), 0}, back[2] = {(char)(in->confirmCircle ? 1 : 2), 0};
    int i, y = ROW_INFO0, id;

    igrmLines = 0;
    igrmTitle("PAUSED", in->gameId);
    igrmListItems(in);
    igrmBarY = ROW_ITEM0 + sel * ITEM_STEP - 2;
    for (i = 0; i < igrmItems; i++) {
        if (i == sel)
            igrmText(ROW_ITEM0 + i * ITEM_STEP, TEXT_X, C_SEL, "\x03");
        igrmText(ROW_ITEM0 + i * ITEM_STEP, ITEM_X, i == sel ? C_SEL : C_ITEM, igrmName[igrmIds[i]]);
    }
    id = igrmIds[sel];

    switch (id) {
        case IT_RESUME:
            igrmText(y, TEXT_X, C_TEXT, "BACK TO THE GAME");
            igrmText(y + 2 * INFO_STEP, TEXT_X, C_DIM, "L1+L2+R1+R2+SELECT+START");
            igrmText(y + 3 * INFO_STEP, TEXT_X, C_DIM, "OPENS THIS MENU AGAIN");
            break;
        case IT_CHEATS:
            p = igrmNum(s, igrmCheatsOn(in->cheats));
            p = igrmCat(p, " OF ");
            igrmCat(igrmNum(p, in->cheats->count), " ON");
            igrmText(y, TEXT_X, C_TEXT, s);
            if (in->cheatsIdle) {
                igrmText(y + INFO_STEP, TEXT_X, C_WARN, "THE CHEAT ENGINE HAS NOT");
                igrmText(y + 2 * INFO_STEP, TEXT_X, C_WARN, "RUN IN THIS GAME YET");
                igrmText(y + 3 * INFO_STEP, TEXT_X, C_DIM, "(CHECK THE MASTER CODE)");
            } else if (in->cheatsBusy) {
                igrmText(y + INFO_STEP, TEXT_X, C_WARN, "NOT APPLIED YET:");
                igrmText(y + 2 * INFO_STEP, TEXT_X, C_WARN, "RESUME, THEN TRY AGAIN");
            } else {
                igrmText(y + INFO_STEP, TEXT_X, C_DIM, "CHANGES APPLY ON RESUME");
                igrmText(y + 2 * INFO_STEP, TEXT_X, C_DIM, "OFF STOPS NEW WRITES,");
                igrmText(y + 3 * INFO_STEP, TEXT_X, C_DIM, "WRITTEN VALUES STAY");
            }
            break;
        case IT_POWER:
            if (!in->canPowerOff) {
                igrmText(y, TEXT_X, C_TEXT, "A DISC GAME TURNS OFF");
                igrmText(y + INFO_STEP, TEXT_X, C_TEXT, "WITH THE POWER BUTTON");
                break;
            }
            if (armed) {
                igrmCat(igrmCat(igrmCat(s, "PRESS "), ok), " AGAIN");
                igrmText(y, TEXT_X, C_WARN, s);
                igrmText(y + INFO_STEP, TEXT_X, C_WARN, "TO TURN THE PS2 OFF");
            } else
                igrmText(y, TEXT_X, C_TEXT, "TURN THE PS2 OFF HERE");
            igrmText(y + 3 * INFO_STEP, TEXT_X, C_WARN, "UNSAVED PROGRESS IS LOST");
            break;
        default: // EXIT GAME
            if (armed) {
                igrmCat(igrmCat(igrmCat(s, "PRESS "), ok), " AGAIN TO LEAVE");
                igrmText(y, TEXT_X, C_WARN, s);
            } else
                igrmText(y, TEXT_X, C_TEXT, "LEAVE THE GAME FOR");
            if (!in->exitPath[0])
                igrmText(y + INFO_STEP, TEXT_X, C_TITLE, "THE PS2 BROWSER");
            else if (igrmEndsWith(in->exitPath, "RIPTOPL.ELF") || igrmEndsWith(in->exitPath, "OPNPS2LD.ELF"))
                igrmText(y + INFO_STEP, TEXT_X, C_TITLE, "THE LOADER");
            else
                igrmPath(y + INFO_STEP, in->exitPath);
            igrmText(y + 3 * INFO_STEP, TEXT_X, C_WARN, "UNSAVED PROGRESS IS LOST");
            break;
    }

    igrmCat(igrmCat(igrmCat(igrmCat(s, ok), " SELECT   "), back), " RESUME");
    igrmText(ROW_HINT, TEXT_X, C_DIM, s);
}

// The CHEATS page: CHEAT_ROWS rows from `top`, the cursor on `sel`; `full`: the last confirm could not turn a cheat
// on because the ticked ones fill the engine's code set
static void igrmComposeCheats(const igrm_info_t *in, int top, int sel, int full)
{
    const igr_cheat_t *row = IGR_CHEATS_ROWS(in->cheats);
    char s[40], *p, ok[2] = {(char)(in->confirmCircle ? 2 : 1), 0}, back[2] = {(char)(in->confirmCircle ? 1 : 2), 0};
    int i, y;

    igrmLines = 0;
    p = igrmNum(s, sel + 1);
    p = igrmCat(p, "/");
    igrmNum(p, in->cheats->count);
    igrmTitle("CHEATS", s);
    igrmSep2 = -1;
    igrmBarY = ROW_ITEM0 + (sel - top) * ITEM_STEP - 2;
    for (i = 0; i < CHEAT_ROWS && top + i < (int)in->cheats->count; i++) {
        const igr_cheat_t *c = &row[top + i];
        y = ROW_ITEM0 + i * ITEM_STEP;
        if (top + i == sel)
            igrmText(y, TEXT_X, C_SEL, "\x03");
        igrmTextN(y, ITEM_X, top + i == sel ? C_SEL : C_ITEM, c->name, CHEAT_CHARS);
        igrmRight(y, c->on ? C_GOLD : C_DIM, c->on ? "ON" : "OFF");
    }
    if (full)
        igrmText(ROW_HINT, TEXT_X, C_WARN, "FULL: TURN ONE OFF FIRST");
    else {
        igrmCat(igrmCat(igrmCat(igrmCat(s, ok), " ON/OFF   "), back), " BACK");
        igrmText(ROW_HINT, TEXT_X, C_DIM, s);
    }
}

static int igrmBase(int ux, int uy)
{
    if (ux == 0 || uy == 0 || ux == PW - 1 || uy == PH - 1)
        return C_BORDER;
    if (ux < 4 || ux >= PW - 4)
        return C_PANEL;
    if (uy == ROW_SEP1 || uy == igrmSep2)
        return C_SEP;
    if (uy >= igrmBarY && uy < igrmBarY + 11)
        return C_BAR;
    return C_PANEL;
}

static void igrmPut(u8 *d, int colour)
{
    const u8 *c = igrmRgb[colour];

    if (igrmBpp == 2) { // CT16 / CT16S: A1 B5 G5 R5
        u32 p = (c[0] >> 3) | ((c[1] >> 3) << 5) | ((c[2] >> 3) << 10) | 0x8000;
        d[0] = p;
        d[1] = p >> 8;
    } else {
        d[0] = c[0];
        d[1] = c[1];
        d[2] = c[2];
        if (igrmBpp == 4)
            d[3] = 0x80;
    }
}

// line y of the panel (frame lines) into d, in the frame's format
static void igrmRenderLine(u8 *d, int y)
{
    const igrm_line_t *act[4];
    int uy = y >> (igrmSy - 1), w = PW * igrmSx, n = 0, i, x;

    for (i = 0; i < igrmLines && n < 4; i++)
        if (uy >= igrmLine[i].y && uy < igrmLine[i].y + 7)
            act[n++] = &igrmLine[i];
    for (x = 0; x < w; x++, d += igrmBpp) {
        int ux = x >> (igrmSx - 1), colour = -1, k;
        for (k = 0; k < n && colour < 0; k++) {
            const igrm_line_t *l = act[k];
            int gx = ux - l->x, c, g;
            if (gx < 0)
                continue;
            c = gx / 6;
            gx -= c * 6;
            if (c >= l->len || gx == 5)
                continue;
            g = l->glyph[c];
            if (igrmFontData[g][uy - l->y] & (0x10 >> gx))
                colour = g == G_CROSS ? (int)C_CROSS : g == G_CIRCLE ? (int)C_CIRCLE :
                                                                       l->colour;
        }
        igrmPut(d, colour >= 0 ? colour : igrmBase(ux, uy));
    }
}

#ifdef IGR_MENU_HOST_TEST
// tests/: a page as RGB rows at the scale given; returns its height. page 0: the menu, 1: the CHEATS page (sel the
// cursor, armed the top row, -1 armed: the FULL hint)
int igrmTestPage(const igrm_info_t *in, int page, int sel, int armed, int sx, int sy, u8 *rgb)
{
    static igrm_line_t lines[IGRM_LINES];
    int y;

    igrmLine = lines;
    igrmSx = sx;
    igrmSy = sy;
    igrmBpp = 3;
    igrmListItems(in);
    if (page == 1)
        igrmComposeCheats(in, armed < 0 ? 0 : armed, sel, armed < 0);
    else
        igrmCompose(in, sel, armed);
    for (y = 0; y < PH * sy; y++)
        igrmRenderLine(rgb + y * PW * sx * 3, y);
    return PH * sy;
}
#else

// ---- on the console

// the game's own GS writes as GSM recorded them (gsm_engine.S, gsm_defines.h Source_*): 0 = none seen
extern u64 GSMSourceGSRegs[11];
extern u16 GSMSourceSetGsCrt[3]; // the game's last SetGsCrt: interlace, mode, ffmd (Hook_SetGsCrt records it always)
#define SRC_PMODE    0
#define SRC_SMODE2   2
#define SRC_DISPFB1  7
#define SRC_DISPLAY1 8
#define SRC_DISPFB2  9
#define SRC_DISPLAY2 10

#define IGRM_D1_CHCR   ((vu32 *)0x10009000)
#define IGRM_D1_MADR   ((vu32 *)0x10009010)
#define IGRM_D1_QWC    ((vu32 *)0x10009020)
#define IGRM_D1_TADR   ((vu32 *)0x10009030)
#define IGRM_D2_CHCR   ((vu32 *)0x1000a000)
#define IGRM_D_STAT    ((vu32 *)0x1000e010)
#define IGRM_GIF_STAT  ((vu32 *)0x10003020)
#define IGRM_VIF1_STAT ((vu32 *)0x10003c00)
#define CHCR_STR       0x100
#define VIF_FQC        0x1f000000
#define VIF_STALLED    0x00800f00 // FDR (the FIFO turned towards the EE), VSS, VFS, VIS, INT
#define GIF_BUSY       0x1f000c00 // FQC and APATH

#define VIF_NOP                       0
#define VIF_FLUSHA                    (0x13 << 24)
#define VIF_DIRECT(n)                 ((0x50 << 24) | (n))
#define GIFTAG(nloop, eop, flg, nreg) ((u64)(nloop) | (u64)(eop) << 15 | (u64)(flg) << 58 | (u64)(nreg) << 60)
#define GIF_AD                        0xe
#define GS_BITBLTBUF                  0x50
#define GS_TRXPOS                     0x51
#define GS_TRXREG                     0x52
#define GS_TRXDIR                     0x53

#define PAD_START  0x0008
#define PAD_UP     0x0010
#define PAD_DOWN   0x0040
#define PAD_CIRCLE 0x2000
#define PAD_CROSS  0x4000

#define IGRM_SECOND 294912000u // COP0 Count ticks: the EE's clock

static u32 igrmBp, igrmBw, igrmPsm, igrmX, igrmY;
static int igrmPending; // ticks the engine has not taken yet (CheatLiveApply was busy): tried again at every open

static inline u32 igrmCount(void)
{
    u32 c;
    __asm__ __volatile__("mfc0 %0, $9"
                         : "=r"(c));
    return c;
}

static int igrmWaitClear(vu32 *reg, u32 bits) // bounded: a stuck path must not hold the pause forever
{
    int i;
    for (i = 0; i < 10000000; i++)
        if (!(*reg & bits))
            return 1;
    return 0;
}

// The frame the PCRTC shows, from the game's own PMODE, SMODE2, DISPFB and DISPLAY writes (RIPPS2's rsFrame), and
// where the panel goes in it
static int igrmFindFrame(void)
{
    const u64 *regs = GSMSourceGSRegs;
    // SMODE2 INT (bit 0) and FFMD (bit 1): the game's own write, or else its SetGsCrt call, which sets the same
    u32 smode2 = (u32)regs[SRC_SMODE2];
    if (!smode2)
        smode2 = (GSMSourceSetGsCrt[0] & 1) | ((GSMSourceSetGsCrt[2] & 1) << 1);
    u64 pmode = regs[SRC_PMODE], fb1 = regs[SRC_DISPFB1], fb2 = regs[SRC_DISPFB2];
    int c1 = (pmode & 1) || (!(pmode & 2) && fb1 != 0); // circuit 1 is on top
    u64 fb = c1 ? fb1 : fb2, disp = regs[c1 ? SRC_DISPLAY1 : SRC_DISPLAY2];
    u32 w, h, x, y;

#ifdef IGR_MENU_TEST
    // PCSX2 has no data breakpoints, so GSM never sees a DISPFB there: show a frame of our own, FBP 0 as
    // 640 wide CT32 on both circuits. The game's next flip puts its own back
    if (fb1 == 0 && fb2 == 0) {
        fb = (u64)10 << 9;
        disp = 0;
        *(vu64 *)0x12000070 = fb; // DISPFB1
        *(vu64 *)0x12000090 = fb; // DISPFB2
    }
#endif
    if (fb == 0)
        return 0; // no DISPFB write seen (the game turned the breakpoint off, or wrote it some other way)
    igrmPsm = (fb >> 15) & 0x1f;
    igrmBpp = igrmPsm == 0 ? 4 : igrmPsm == 1                ? 3 :
                             (igrmPsm == 2 || igrmPsm == 10) ? 2 :
                                                               0;
    igrmBw = (fb >> 9) & 0x3f;
    if (!igrmBpp || !igrmBw)
        return 0;
    igrmBp = (fb & 0x1ff) * 32; // pages of 2048 words, in BITBLTBUF's 64-word blocks
    w = igrmBw * 64;
    h = 224;
    if (disp) { // shown size: DW over MAGH, DH over MAGV (u32: a u64 divide pulls in libgcc)
        u32 dw = (((u32)(disp >> 32) & 0xfff) + 1) / (((u32)(disp >> 23) & 0xf) + 1);
        u32 dh = (((u32)(disp >> 44) & 0x7ff) + 1) / (((u32)(disp >> 27) & 3) + 1);
        if (dw > 0 && dw < w)
            w = dw;
        // interlaced, the TV shows its raster and no more, whatever DH asks (a game writing DH 959 shows 480 lines on
        // NTSC); a PAL picture starts lower (DY 72 against NTSC's 50)
        if ((smode2 & 1) && dh > ((((u32)(disp >> 12) & 0x7ff) >= 64) ? 576u : 480u))
            dh = (((u32)(disp >> 12) & 0x7ff) >= 64) ? 576 : 480;
        if (dh > 0 && dh <= 1024)
            h = dh;
    }
    if ((smode2 & 3) == 3) // interlaced FRAME mode: the buffer holds one field
        h /= 2;
    x = (fb >> 32) & 0x7ff;
    y = (fb >> 43) & 0x7ff;
    if (w < PW + 8 || h < PH + 4)
        return 0;
    igrmSx = w >= PW * 2 + 16 ? 2 : 1;
    igrmSy = h >= PH * 2 + 16 ? 2 : 1;
    igrmX = x + (w - PW * igrmSx) / 2;
    igrmY = y + (h - PH * igrmSy) / 2;
    return 1;
}

// One line into the frame from the pixels at pkt + 28: VIF codes, the GIF A+D setup of a host -> local transfer
static int igrmSendLine(u32 *pkt, int line)
{
    u32 qw = PW * igrmSx * igrmBpp / 16; // a whole number for every format: PW * igrmSx is a multiple of 16
    u64 *q = (u64 *)(pkt + 4);

    pkt[0] = VIF_NOP;
    pkt[1] = VIF_NOP; // no MSKPATH3: the game's PATH3 mask is its own state (its GIF DMA is idle; FLUSHA waits)
    pkt[2] = VIF_FLUSHA;
    pkt[3] = VIF_DIRECT(6 + qw);
    q[0] = GIFTAG(4, 0, 0, 1);
    q[1] = GIF_AD;
    q[2] = (u64)igrmBp << 32 | (u64)igrmBw << 48 | (u64)igrmPsm << 56;
    q[3] = GS_BITBLTBUF;
    q[4] = (u64)igrmX << 32 | (u64)(igrmY + line) << 48; // TRXPOS: destination
    q[5] = GS_TRXPOS;
    q[6] = (u64)(PW * igrmSx) | (u64)1 << 32;
    q[7] = GS_TRXREG;
    q[8] = 0; // host -> local
    q[9] = GS_TRXDIR;
    q[10] = GIFTAG(qw, 1, 2, 0); // IMAGE
    q[11] = 0;

    FlushCache(0);
    *IGRM_D1_QWC = 7 + qw;
    *IGRM_D1_MADR = (u32)pkt;
    *IGRM_D1_CHCR = 0x101; // from memory, normal mode, start
    asm volatile("sync.l");
    return igrmWaitClear(IGRM_D1_CHCR, CHCR_STR);
}

// The page composed last, from igrmY
static int igrmDraw(u32 *pkt)
{
    int line;

    for (line = 0; line < PH * igrmSy; line++) {
        igrmRenderLine((u8 *)(pkt + 28), line);
        if (!igrmSendLine(pkt, line)) {
            *IGRM_D1_CHCR = 0; // stop it: a VIF1 that will not take data must not keep our transfer
            return 0;
        }
    }
    return 1;
}

// GSM's data breakpoint (the passive tracker, or GSM itself) traps stores to GS registers. While the game is paused
// nothing of the game's needs it, so it is off from the menu's first step to its last and BPC is put back as it was
// (RIPPS2 build 108).
static u32 igrmBpcOff(void)
{
    u32 bpc;

    ee_kmode_enter();
    asm volatile("sync.l\n\tmfbpc %0\n\tsync.p"
                 : "=r"(bpc));
    asm volatile("mtbpc %0\n\tsync.p" ::"r"(0x8000)); // BED: all breakpoints off
    ee_kmode_exit();
    return bpc;
}

static void igrmBpcBack(u32 bpc)
{
    ee_kmode_enter();
    asm volatile("sync.l\n\tmtbpc %0\n\tsync.p" ::"r"(bpc));
    ee_kmode_exit();
}

// The power button, read as the VBLANK handler reads it (that handler is held while the game is paused): the
// power-off request is latched, so a press counts once, when it appears, and is cancelled then. Returns 1 for a
// new press.
static int igrmPowerButton(int *latched)
{
    int pending, pressed;

    ee_kmode_enter();
    pending = (*CDVD_R_NDIN & 0x20) && (*CDVD_R_POFF & 0x04);
    pressed = pending && !*latched;
    if (pressed) {
        *CDVD_R_SDIN = 0x00;
        *CDVD_R_SCMD = 0x1B; // cancel the power off, to catch a second press
    }
    ee_kmode_exit();
    *latched = pending;
    return pressed;
}

int IGR_MenuRun(u16 (*buttons)(void))
{
    USE_LOCAL_EECORE_CONFIG;
    u32 raw[(112 + PW * 2 * 4 + 64) / 4]; // one line of the panel at its widest (the IGR thread's stack)
    u32 *pkt = (u32 *)(((u32)raw + 63) & ~63);
    u32 d1chcr, d1madr, d1qwc, d1tadr, gameDone, t, firstT = 0, bpc;
    u16 held, now, pressed, ok, back;
    int sel = 0, armed = 0, result = IGR_MENU_RESUME, presses = 0, power = 1, powerLatched = 0, i;
    int page = 0, csel = 0, ctop = 0, full = 0, changed = 0;
    char gameId[CORE_GAME_ID_MAX_LEN + 1];
    igrm_line_t lines[IGRM_LINES];
    igrm_info_t info;
    igr_cheat_t *row = NULL;

#if defined(__GNUC__) && !defined(__clang__) // clang has no -Wdangling-pointer
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdangling-pointer"
#endif
    igrmLine = lines; // only while this call runs: every page is composed and drawn inside it
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic pop
#endif
    if (!igrmFindFrame())
        return IGR_MENU_CANNOT_DRAW;
    // the game's own transfers finish first; a VIF1 stalled on an interrupt the pause holds cannot take ours
    if (!igrmWaitClear(IGRM_D1_CHCR, CHCR_STR) || !igrmWaitClear(IGRM_D2_CHCR, CHCR_STR) || (*IGRM_VIF1_STAT & VIF_STALLED))
        return IGR_MENU_CANNOT_DRAW;
    bpc = igrmBpcOff();
    gameDone = *IGRM_D_STAT & 2; // a channel 1 completion the game has not handled yet stays for its handler
    d1chcr = *IGRM_D1_CHCR;
    d1madr = *IGRM_D1_MADR;
    d1qwc = *IGRM_D1_QWC;
    d1tadr = *IGRM_D1_TADR;

    for (i = 0; i < CORE_GAME_ID_MAX_LEN && config->GameID[i]; i++)
        gameId[i] = config->GameID[i];
    gameId[i] = '\0';

    config->ExitPath[CORE_EXIT_PATH_MAX_LEN - 1] = '\0';
    info.confirmCircle = config->IgrConfirmCircle;
    info.gameId = gameId;
    info.exitPath = config->ExitPath;
#ifdef RETROACHIEVEMENTS
    info.canPowerOff = config->GameMode != DISC_MODE; // physical discs launch only in RA builds
#else
    info.canPowerOff = 1;
#endif
    info.cheats = NULL;
    info.cheatsBusy = info.cheatsIdle = 0;
    if (config->IgrCheats != NULL && config->gCheatList != NULL) {
        igr_cheats_t *b = (igr_cheats_t *)config->IgrCheats;
        if (b->magic == IGR_CHEATS_MAGIC && b->count > 0 && b->count <= IGR_CHEATS_MAX) {
            info.cheats = b;
            row = IGR_CHEATS_ROWS(b);
            if (igrmPending) // the game ran since: the pass that held the set has finished
                igrmPending = !CheatLiveApply(b);
            info.cheatsBusy = igrmPending;
            info.cheatsIdle = codeentry == NULL;
        }
    }
    if (info.canPowerOff == 0)
        power = 0; // the ROM's CDVDMAN keeps the power button there, as the VBLANK handler leaves it
    ok = info.confirmCircle ? PAD_CIRCLE : PAD_CROSS;
    back = info.confirmCircle ? PAD_CROSS : PAD_CIRCLE;

    igrmCompose(&info, sel, armed);
    if (!igrmDraw(pkt)) {
        result = IGR_MENU_CANNOT_DRAW;
        goto done;
    }

    held = buttons(); // the combo is still held: only new presses count
    for (;;) {
        int dirty = 0, id = igrmIds[sel];

        now = buttons();
        pressed = now & ~held;
        held = now;
        if (page) { // CHEATS
            int n = (int)info.cheats->count;
            if (pressed & (PAD_UP | PAD_DOWN)) {
                csel = (csel + ((pressed & PAD_UP) ? n - 1 : 1)) % n;
                if (csel < ctop)
                    ctop = csel;
                else if (csel >= ctop + CHEAT_ROWS)
                    ctop = csel - CHEAT_ROWS + 1;
                full = 0;
                dirty = 1;
            } else if (pressed & ok) {
                if (row[csel].on || CheatLiveFits(info.cheats, csel)) {
                    row[csel].on = !row[csel].on;
                    changed = 1;
                    full = 0;
                } else
                    full = 1;
                dirty = 1;
            } else if (pressed & back) {
                page = 0;
                dirty = 1;
            } else if (pressed & PAD_START)
                break;
        } else if (pressed & (PAD_UP | PAD_DOWN)) {
            sel = (sel + ((pressed & PAD_UP) ? igrmItems - 1 : 1)) % igrmItems;
            armed = 0;
            dirty = 1;
        } else if (pressed & ok) {
            if (id == IT_RESUME)
                break;
            if (id == IT_CHEATS) {
                page = 1;
                full = 0;
                dirty = 1;
            } else if (id == IT_EXIT || (id == IT_POWER && info.canPowerOff)) { // a second press: progress is lost
                if (armed) {
                    result = id == IT_EXIT ? IGR_MENU_EXIT : IGR_MENU_POWEROFF;
                    break;
                }
                armed = dirty = 1;
            }
        } else if (pressed & (back | PAD_START))
            break;

        if (power) { // once = power off, twice = leave, decided a second after the first press (as OPL)
            t = igrmCount();
            if (igrmPowerButton(&powerLatched) && presses++ == 0)
                firstT = t;
            if (presses && t - firstT > IGRM_SECOND) {
                result = presses == 1 ? IGR_MENU_POWEROFF : IGR_MENU_EXIT;
                break;
            }
        }

        if (dirty) {
            if (page)
                igrmComposeCheats(&info, ctop, csel, full);
            else
                igrmCompose(&info, sel, armed);
            igrmDraw(pkt); // a frame that took the first drawing takes this one; if not, the choice still works
        }
    }

    if (result == IGR_MENU_RESUME) {
        // the cheats as ticked, before any game thread runs again; when the engine was walking the set the menu
        // would write, nothing changes and the menu says so next time (the ticks stay as they are)
        if ((changed || igrmPending) && info.cheats != NULL)
            igrmPending = !CheatLiveApply(info.cheats);
        // the button that closed the menu must not reach the game
        t = igrmCount();
        while (buttons() && igrmCount() - t < 3 * IGRM_SECOND)
            ;
    }

done:
    // DMA done is not the end: the VIF1 FIFO and the GIF may still be moving the last line
    igrmWaitClear(IGRM_VIF1_STAT, VIF_FQC);
    igrmWaitClear(IGRM_GIF_STAT, GIF_BUSY);
    *IGRM_D1_MADR = d1madr;
    *IGRM_D1_QWC = d1qwc;
    *IGRM_D1_TADR = d1tadr;
    *IGRM_D1_CHCR = d1chcr;
    // our transfers flagged channel 1 done; left set, the game's VIF1 handler would run for a transfer it
    // never started. Write 1 clears it (the mask bits stay)
    if (!gameDone)
        *IGRM_D_STAT = 2;
    asm volatile("sync.l");
    igrmBpcBack(bpc);
    return result;
}
#endif
#endif
