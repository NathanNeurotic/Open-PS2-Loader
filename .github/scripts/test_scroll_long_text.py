"""Theme text that does not fit its space scrolls instead of running off (Nathan, 09-29).

- fntRenderMarquee (src/fntsys.c): text that fits draws exactly as before; text that does not fit
  scrolls one character per step, holding at each end, restarting whenever the text changes. A
  centred scrolling line fills its whole box. fntRenderEllipsis ends a too-long line in "...".
- thmTextRoom (src/themes.c): the theme's width when it sets one, never past the screen; otherwise the
  widest box that stays on screen from the anchor (centred text gets equal room both sides).
- thmCaptionName (src/themes.c): a path shows only its file name -- an app's ItemText caption is its
  ELF name, not "mass0:/APPS/APP_WLE/WLE.ELF".
- The game list scrolls the selected title and ends the others in "..."; ItemText and single-line
  AttributeText scroll.

Everything is compiled from the production source, with the font measured as 10 px per character.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def defines(source, where, names):
    out = []
    for name in names:
        match = re.search(r'^#define ' + name + r'\s+(\S+)', source, re.M)
        if match is None:
            failures.append('%s: #define %s not found' % (where, name))
            continue
        out.append('#define %s %s' % (name, match.group(1)))
    return '\n'.join(out) + '\n'


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / (name + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            lines = [line for line in run.stdout.splitlines() if line.startswith('FAIL')]
            failures.extend(lines or ['%s harness exited %d' % (name, run.returncode)])


fnt_c = read('src/fntsys.c')
fnt_h = read('include/fntsys.h')
themes_c = read('src/themes.c')
themes_h = read('include/themes.h')

# --- fntRenderMarquee / fntRenderEllipsis ---------------------------------------------------------

marquee_type = re.search(r'^typedef struct\s*\{[^}]*\} fnt_marquee_t;', fnt_h, re.M)
if marquee_type is None:
    failures.append('include/fntsys.h: typedef fnt_marquee_t not found')

FONT_HARNESS = r'''
#include <stdio.h>
#include <string.h>

typedef long clock_t;
typedef unsigned long long u64;
#define CLOCKS_PER_SEC 1000
#define ALIGN_VCENTER (2 << 0)
#define ALIGN_HCENTER (2 << 2)
#define ALIGN_NONE 0
#define ALIGN_CENTER (ALIGN_VCENTER | ALIGN_HCENTER)

static clock_t nowMs;
static clock_t clock(void) { return nowMs; }
static int rmUnScaleX(int x) { return x; }
static int fntCalcDimensions(int id, const char *s)
{
    int n = 0;
    (void)id;
    for (; *s; s++)
        if ((*s & 0xC0) != 0x80)
            n++;
    return n * 10;
}
static int drawnX, drawnAligned, drawnWidth;
static char drawn[256];
static int fntRenderString(int id, int x, int y, short aligned, int width, int height, const char *s, u64 colour)
{
    (void)id; (void)y; (void)height; (void)colour;
    drawnX = x;
    drawnAligned = aligned;
    drawnWidth = width;
    snprintf(drawn, sizeof(drawn), "%s", s);
    return x + fntCalcDimensions(0, s);
}

@DEFINES@
@TYPE@
@FUNCTIONS@

static int fails;
#define CHECK(cond, ...)                 \
    do {                                 \
        if (!(cond)) {                   \
            printf("FAIL " __VA_ARGS__); \
            printf("\n");                \
            fails++;                     \
        }                                \
    } while (0)

int main(void)
{
    fnt_marquee_t m;
    const char *longText = "ABCDEFGHIJKLMNOP"; /* 160 px; from 'G' on the rest is 100 px */
    const int step = FNT_MARQUEE_STEP_MS, pause = FNT_MARQUEE_PAUSE;

    memset(&m, 0, sizeof(m));
    nowMs = 1000;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, "SHORT", 0, &m);
    CHECK(strcmp(drawn, "SHORT") == 0 && drawnX == 40, "text that fits draws whole, where it always did (%s at %d)", drawn, drawnX);

    memset(&m, 0, sizeof(m));
    nowMs = 5000;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, longText, 0, &m);
    CHECK(strcmp(drawn, longText) == 0 && drawnWidth == 100, "a too-long line starts at its beginning, clipped to its room (%s w%d)", drawn, drawnWidth);
    nowMs = 5000 + (pause + 3) * step;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, longText, 0, &m);
    CHECK(strcmp(drawn, "DEFGHIJKLMNOP") == 0, "three steps past the pause it has scrolled three characters (%s)", drawn);
    nowMs = 5000 + (pause + 6 + 2) * step;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, longText, 0, &m);
    CHECK(strcmp(drawn, "GHIJKLMNOP") == 0, "it holds at the end once the rest fits (%s)", drawn);
    nowMs = 5000 + (pause + 6 + pause) * step;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, longText, 0, &m);
    CHECK(strcmp(drawn, longText) == 0, "after the end pause it starts again from the top (%s)", drawn);

    nowMs = 5000 + (pause + 3) * step;
    fntRenderMarquee(0, 40, 0, ALIGN_NONE, 100, "abcdefghijklmnopqrst", 0, &m);
    CHECK(strcmp(drawn, "abcdefghijklmnopqrst") == 0, "a new text restarts from its beginning (%s)", drawn);

    memset(&m, 0, sizeof(m));
    fntRenderMarquee(0, 300, 0, ALIGN_CENTER, 100, longText, 0, &m);
    CHECK(drawnX == 250 && !(drawnAligned & ALIGN_HCENTER), "a centred scrolling line fills its box from the left edge (x %d)", drawnX);

    fntRenderEllipsis(0, 40, 0, ALIGN_NONE, 100, longText, 0);
    CHECK(strcmp(drawn, "ABCDEFG...") == 0, "a too-long line ends in ... inside its room (%s)", drawn);
    fntRenderEllipsis(0, 40, 0, ALIGN_NONE, 100, "SHORT", 0);
    CHECK(strcmp(drawn, "SHORT") == 0, "a line that fits gets no ... (%s)", drawn);

    if (!fails)
        printf("scroll long text: fits unchanged, scrolls with end pauses, restarts on change, centred box, ellipsis\n");
    return fails ? 1 : 0;
}
'''

font_functions = ''.join(function_text(fnt_c, 'src/fntsys.c', sig) for sig in (
    'int fntMarqueeOffset(',
    'int fntMarqueeElapsed(',
    'int fntRenderMarquee(',
    'int fntRenderEllipsis(',
))
if marquee_type is not None and font_functions.count('{') >= 4:
    compile_and_run('marquee', FONT_HARNESS.replace('@DEFINES@', defines(fnt_c, 'src/fntsys.c', ('FNT_MARQUEE_STEP_MS', 'FNT_MARQUEE_PAUSE')))
                    .replace('@TYPE@', marquee_type.group(0)).replace('@FUNCTIONS@', font_functions))

# --- thmTextRoom / thmCaptionName ------------------------------------------------------------------

THEMES_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#define ALIGN_VCENTER (2 << 0)
#define ALIGN_HCENTER (2 << 2)
#define ALIGN_NONE 0
#define ALIGN_CENTER (ALIGN_VCENTER | ALIGN_HCENTER)
static int screenWidth = 640;
@DEFINES@
@FUNCTIONS@

static int fails;
static void room(const char *what, int x, short aligned, int width, int want)
{
    int got = thmTextRoom(x, aligned, width);
    if (got != want) {
        printf("FAIL room %s: got %d, want %d\n", what, got, want);
        fails++;
    }
}
static void caption(const char *in, const char *want)
{
    const char *got = thmCaptionName(in);
    if (strcmp(got, want) != 0) {
        printf("FAIL caption %s: got %s, want %s\n", in, got, want);
        fails++;
    }
}

int main(void)
{
    const int m = THM_TEXT_MARGIN;
    room("left-anchored, no theme width", 100, ALIGN_NONE, -1, 640 - m - 100);
    room("centred mid-screen", 320, ALIGN_CENTER, -1, 2 * (320 - m));
    room("centred near the left edge", 100, ALIGN_CENTER, -1, 2 * (100 - m));
    room("theme width inside the screen", 100, ALIGN_NONE, 200, 200);
    room("theme width past the screen", 100, ALIGN_NONE, 900, 640 - m - 100);
    room("anchored off the right edge", 700, ALIGN_NONE, -1, 0);

    caption("mass0:/APPS/APP_WLE/WLE.ELF", "WLE.ELF");
    caption("smb0:\\APPS\\uLE.elf", "uLE.elf");
    caption("mc0:BOOT.ELF", "BOOT.ELF");
    caption("SLUS_123.45", "SLUS_123.45");
    caption("Crash Bandicoot (USA)", "Crash Bandicoot (USA)");
    caption("mass0:/APPS/", "mass0:/APPS/");
    caption("", "");

    if (!fails)
        printf("scroll long text: text room and app captions verified\n");
    return fails ? 1 : 0;
}
'''

theme_functions = ''.join(function_text(themes_c, 'src/themes.c', sig) for sig in (
    'static int thmTextRoom(',
    'static const char *thmCaptionName(',
))
if theme_functions.count('{') >= 2:
    compile_and_run('text_room', THEMES_HARNESS.replace('@DEFINES@', defines(themes_c, 'src/themes.c', ('THM_TEXT_MARGIN',)))
                    .replace('@FUNCTIONS@', theme_functions))

# --- the theme elements use it ---------------------------------------------------------------------

items_list = function_text(themes_c, 'src/themes.c', 'static void drawItemsList(')
if items_list:
    if not re.search(r'if \(ps == item\)\s*\n\s*textEndX = fntRenderMarquee\(', items_list):
        failures.append('drawItemsList: the selected title must scroll (fntRenderMarquee)')
    if 'fntRenderEllipsis(' not in items_list:
        failures.append('drawItemsList: the other titles must end in ... (fntRenderEllipsis)')
item_text = function_text(themes_c, 'src/themes.c', 'static void drawItemText(')
if item_text and ('thmCaptionName(' not in item_text or 'fntRenderMarquee(' not in item_text):
    failures.append('drawItemText: the caption must be the file name of a path, and scroll')
attr_text = function_text(themes_c, 'src/themes.c', 'static void drawAttributeText(')
if attr_text and 'fntRender' in attr_text.replace('thmDrawAttributeLine', ''):
    failures.append('drawAttributeText: every line must go through thmDrawAttributeLine')
if 'fnt_marquee_t titleMarquee;' not in themes_h or 'fnt_marquee_t marquee;' not in themes_h:
    failures.append('include/themes.h: items_list_t.titleMarquee and mutable_text_t.marquee are needed')
if 'memset(&itemsList->titleMarquee, 0' not in themes_c or 'memset(&mutableText->marquee, 0' not in themes_c:
    failures.append('src/themes.c: both scroll memories must start zeroed (the structs are malloc\'d)')

if failures:
    print('Scroll long text checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
