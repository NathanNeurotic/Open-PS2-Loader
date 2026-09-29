"""Collision-aware theme text: long text stops at the next theme element and scrolls instead (09-29).

Theme text used to draw straight over its neighbours -- a List title across the cover, an attribute
value across the next label. themes.c now gives each text element a room at load (thmComputeTextRooms,
geometry in thmTextRoom) and draws through fntRenderStringFit (fntsys.c), the scroller the settings
dialogs already used for #732.

This compiles the real thmTextRoom and fntRenderStringFit on the host against stubs and checks:
- room runs to the nearest element on the same row, or the screen edge;
- an element the text STARTS inside (a banner/panel) is a backdrop, not an obstacle;
- elements on other rows and to the left don't limit left-anchored text;
- centred text gets twice the nearer side;
- text that fits is drawn untouched; longer text either scrolls (holding at each end) inside the room or
  is cut to end in "...", never splitting a UTF-8 character;
and pins the wiring: every theme family gets rooms, the highlighted list row scrolls, and the settings
dialogs use the shared scroller.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
themes = (root / 'src/themes.c').read_text(encoding='utf-8').replace('\r\n', '\n')
fntsys = (root / 'src/fntsys.c').read_text(encoding='utf-8').replace('\r\n', '\n')
dia = (root / 'src/dia.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature, where):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def define(source, name):
    match = re.search(r'^#define ' + name + r'\s+(\d+)', source, re.M)
    if match is None:
        failures.append('#define %s not found' % name)
        return '0'
    return match.group(1)


room_fn = function_text(themes, 'static int thmTextRoom(', 'src/themes.c')
fit_fn = function_text(fntsys, 'int fntRenderStringFit(', 'src/fntsys.c')
width_fn = function_text(fntsys, 'static int fntTextWidth(', 'src/fntsys.c')

HARNESS = r'''
#include <stdio.h>
#include <string.h>

#define ALIGN_NONE    0
#define ALIGN_VCENTER (2 << 0)
#define ALIGN_RIGHT   (1 << 2)
#define ALIGN_HCENTER (2 << 2)
#define THM_TEXT_GAP @GAP@
#define FNT_MARQUEE_STEP_MS @STEP@
#define FNT_MARQUEE_PAUSE @PAUSE@
#define CLOCKS_PER_SEC 1000
typedef unsigned long long u64;
typedef struct { int x0, y0, x1, y1; } thm_box_t;

/* 10 units per character (UTF-8 continuation bytes are part of the previous character). */
static int fntCalcDimensions(int id, const char *str)
{
    int n = 0;
    (void)id;
    for (; *str; str++)
        if ((*str & 0xC0) != 0x80)
            n++;
    return n * 10;
}
static int rmUnScaleX(int x) { return x; }
static long fakeClock;
static long clock(void) { return fakeClock; }

static int drawnX, drawnWidth, drawnAligned;
static char drawn[512];
static int fntRenderString(int id, int x, int y, short aligned, int width, int height, const char *s, u64 colour)
{
    (void)id; (void)y; (void)height; (void)colour;
    drawnX = x; drawnWidth = width; drawnAligned = aligned;
    snprintf(drawn, sizeof(drawn), "%s", s);
    return x + fntCalcDimensions(0, s);
}

@FUNCTIONS@

static int fails;
static void expectInt(const char *what, int got, int want)
{
    if (got != want) {
        printf("FAIL %s: got %d, want %d\n", what, got, want);
        fails++;
    }
}
static void expectStr(const char *what, const char *got, const char *want)
{
    if (strcmp(got, want) != 0) {
        printf("FAIL %s: got [%s], want [%s]\n", what, got, want);
        fails++;
    }
}

int main(void)
{
    /* Room geometry: screen 640 wide, text row y 100..119. */
    thm_box_t cover = {400, 60, 540, 260};   /* a cover to the right, spanning the row */
    thm_box_t panel = {20, 90, 620, 130};    /* a banner the text is drawn on */
    thm_box_t below = {300, 200, 400, 300};  /* something on another row */
    thm_box_t leftBox = {0, 90, 50, 130};    /* something to the left */

    expectInt("screen edge only", thmTextRoom(40, 100, 119, 0, NULL, 0, 640), 640 - 40 - THM_TEXT_GAP);
    expectInt("stops before the cover", thmTextRoom(40, 100, 119, 0, &cover, 1, 640), 400 - 40 - THM_TEXT_GAP);
    expectInt("panel it starts on is a backdrop", thmTextRoom(40, 100, 119, 0, &panel, 1, 640), 640 - 40 - THM_TEXT_GAP);
    expectInt("other rows do not count", thmTextRoom(40, 100, 119, 0, &below, 1, 640), 640 - 40 - THM_TEXT_GAP);
    expectInt("boxes to the left do not limit left text", thmTextRoom(60, 100, 119, 0, &leftBox, 1, 640), 640 - 60 - THM_TEXT_GAP);
    {
        thm_box_t both[2] = {{100, 90, 150, 130}, {500, 90, 560, 130}};
        /* centred at 320: 170 to the left box's edge, 180 to the right one -> twice the nearer */
        expectInt("centred takes twice the nearer side", thmTextRoom(320, 100, 119, 1, both, 2, 640), 2 * (170 - THM_TEXT_GAP));
    }
    /* Centred text on a banner: the banner straddles both sides of the start, so without the backdrop
       rule it would leave a negative room and the text would never draw. */
    expectInt("centred text on a banner is not blocked by it", thmTextRoom(320, 100, 119, 1, &panel, 1, 640), 2 * (320 - THM_TEXT_GAP));
    {
        thm_box_t mix[3] = {panel, cover, below};
        expectInt("backdrop + obstacle together", thmTextRoom(40, 100, 119, 0, mix, 3, 640), 400 - 40 - THM_TEXT_GAP);
    }

    /* Fit: room 100 = 10 characters. */
    expectInt("fits: drawn whole", fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "short", 0, 1), 50 + 50);
    expectStr("fits: text untouched", drawn, "short");
    expectInt("fits: no clip width", drawnWidth, 0);

    fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "ABCDEFGHIJKLMNOP", 0, 0);
    expectStr("not selected: ends in ...", drawn, "ABCDEFG...");

    fakeClock = 0; /* holding at the start */
    fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "ABCDEFGHIJKLMNOP", 0, 1);
    expectStr("scroll: starts at the beginning", drawn, "ABCDEFGHIJKLMNOP");
    expectInt("scroll: clipped to the room", drawnWidth, 100);
    fakeClock = (long)(FNT_MARQUEE_PAUSE + 3) * FNT_MARQUEE_STEP_MS; /* 3 steps in */
    fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "ABCDEFGHIJKLMNOP", 0, 1);
    expectStr("scroll: moves one character per step", drawn, "DEFGHIJKLMNOP");
    /* The last stop is 6 characters in ("GHIJKLMNOP" fits); two steps past it is inside the end pause,
       which holds there before the cycle loops back to the start. */
    fakeClock = (long)(FNT_MARQUEE_PAUSE + 6 + 2) * FNT_MARQUEE_STEP_MS;
    fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "ABCDEFGHIJKLMNOP", 0, 1);
    expectStr("scroll: holds on the last window", drawn, "GHIJKLMNOP");
    fakeClock = (long)(6 + 2 * FNT_MARQUEE_PAUSE) * FNT_MARQUEE_STEP_MS; /* one full cycle: back to the start */
    fntRenderStringFit(0, 50, 0, ALIGN_NONE, 100, "ABCDEFGHIJKLMNOP", 0, 1);
    expectStr("scroll: loops back to the start", drawn, "ABCDEFGHIJKLMNOP");

    fntRenderStringFit(0, 320, 0, ALIGN_HCENTER, 100, "ABCDEFGHIJKLMNOP", 0, 0);
    expectInt("centred: the window is centred on x", drawnX, 320 - 50);
    expectInt("centred: drawn left to right inside it", drawnAligned & ALIGN_HCENTER, 0);

    /* UTF-8: "é" is two bytes but one character; the cut must not split it. */
    fntRenderStringFit(0, 0, 0, ALIGN_NONE, 100, "\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9", 0, 0);
    expectStr("utf-8 cut on a character boundary", drawn, "\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9...");

    /* Four-byte UTF-8 can hit the 256-byte scratch buffer before the 255-character index cap.
       The prefix must stay whole and leave three bytes for the ellipsis. */
    {
        char longUtf8[70 * 4 + 1];
        int j;
        for (j = 0; j < 70; j++)
            memcpy(&longUtf8[j * 4], "\xf0\x9f\x98\x80", 4);
        longUtf8[70 * 4] = '\0';
        fntRenderStringFit(0, 0, 0, ALIGN_NONE, 680, longUtf8, 0, 0);
        expectInt("long utf-8 stays within scratch buffer", (int)strlen(drawn), 255);
        expectStr("long utf-8 keeps ellipsis", &drawn[252], "...");
    }

    expectInt("no room: draws nothing", fntRenderStringFit(0, 50, 0, ALIGN_NONE, 0, "x", 0, 1), 50);

    if (!fails)
        printf("theme text room: stops at neighbours, ignores backdrops, scrolls or ends in ... inside the room\n");
    return fails ? 1 : 0;
}
'''

if room_fn and fit_fn and width_fn:
    program = (HARNESS.replace('@GAP@', define(themes, 'THM_TEXT_GAP'))
               .replace('@STEP@', define(fntsys, 'FNT_MARQUEE_STEP_MS'))
               .replace('@PAUSE@', define(fntsys, 'FNT_MARQUEE_PAUSE'))
               .replace('@FUNCTIONS@', room_fn + width_fn + fit_fn))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'room.c'
        exe = Path(tmp) / ('room.exe' if sys.platform == 'win32' else 'room')
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('room/scroll behaviour failed')

# Wiring.
validate = function_text(themes, 'static void validateGUIElems(', 'src/themes.c')
for family in ('mainElems', 'infoElems', 'appsMainElems', 'appsInfoElems', 'favsMainElems', 'favsInfoElems',
               'vcdMainElems', 'vcdInfoElems', 'favsVcdMainElems', 'favsVcdInfoElems', 'favsAppsMainElems',
               'favsAppsInfoElems'):
    if validate and 'thmComputeTextRooms(&theme->%s);' % family not in validate:
        failures.append('validateGUIElems: %s gets no text rooms' % family)
items = function_text(themes, 'static void drawItemsList(', 'src/themes.c')
if items and items.count('elem->textRoom, dispText, color, ps == item);') != 2:
    failures.append('drawItemsList: the highlighted row (and only it) must scroll inside the room, with and without a decorator')
if 'fntRenderStringFit(' not in function_text(dia, 'static int diaRenderValue(', 'src/dia.c'):
    failures.append('dia.c: settings values no longer use the shared scroller')
if 'diaTextWidth' in dia or 'DIA_MARQUEE' in dia:
    failures.append('dia.c: a private copy of the scroller is back')

# A devices=-filtered element is on one page only; counting it everywhere boxed the built-in Coverflow
# title into 196 units because of the Favorites icon (zackcage6, Beta-3335).
rooms = function_text(themes, 'static void thmComputeTextRooms(', 'src/themes.c')
if rooms and 'if (other->deviceFilter)\n                continue;' not in rooms:
    failures.append('thmComputeTextRooms: a device-specific element must not limit text on every page')
# ...and the built-in Coverflow title spans the top instead of a 400-unit box.
coverflow = (root / 'misc/theme_coverflow.cfg').read_text(encoding='utf-8').replace('\r\n', '\n')
if not re.search(r'^main15:\n\ttype=ItemsList\n(?:\t.*\n)*?\twidth=DIM_INF\n', coverflow, re.M):
    failures.append('misc/theme_coverflow.cfg: the Coverflow title list must span the top (width=DIM_INF)')

if failures:
    for failure in failures:
        print(failure)
    sys.exit(1)
