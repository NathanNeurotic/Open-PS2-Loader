"""Settings text stays on screen (dia.c).

A dialog drew labels, buttons, On/Off, numbers and OK wherever their row put them, with nothing stopping them at the
right edge; only enum and string values were fitted (#732). Measured with the menu font on a 4:3 SD screen: the
POPStarter network notice ran about 900 wide, "POPSTARTER network configuration already exists..." and the Neutrino
arguments note about 680, three About credit rows 650-665, and long translations pushed On/Off past the edge.

1. A label or header alone on its row (nothing but spacers before it, nothing after) wraps onto more lines, and the
   layout (diaItemHeight via diaWrapExtra, diaLayoutBottom) gives the row exactly the height the lines take.
   Compiled and run below with the real functions and the real fntWrapText, a fixed 8-wide font.
2. Any other label leaves the rest of its row room (diaRowTailWidth) and ends in "..." when it would not.
3. Every value and button fits the room left (diaRenderValue), so nothing a dialog draws runs past the margin.
4. The keyboard's title stops at its separating line.
5. A dialog whose only control sits below the hints (About, its rows wrapped at a large font) follows the cursor
   instead of snapping to the top with the OK out of view.
6. The About credit rows each fit 4:3 SD at the default font size.
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


def function(source, signature):
    pos = source.find(signature)
    if pos < 0:
        failures.append('%s not found' % signature)
        return ''
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1] + '\n'
    raise AssertionError('unterminated ' + signature)


dia = read('src/dia.c')
dia_h = read('include/dia.h')
fnt = read('src/fntsys.c')
dialogs = read('src/dialogs.c')

types = (re.search(r'^typedef enum \{.*?\} UIItemType;', dia_h, re.M | re.S).group(0) + '\n' +
         re.search(r'^struct UIItem\s*\{.*?^\};', dia_h, re.M | re.S).group(0))
defines = '\n'.join(re.findall(r'^#define (?:UI_\w+|DIA_VALUE_MARGIN|DIA_WRAP_MAX|DIA_TAIL_VALUE_W)\s+\d+', dia, re.M))
functions = ''.join(function(dia, sig) for sig in (
    'static const char *diaGetLocalisedText(',
    'static int diaShouldBreakLine(',
    'static int diaShouldBreakLineAfter(',
    'static int diaSpacerWidth(',
    'static const char *diaLabelText(',
    'static int diaMeasure(',
    'static int diaWrapRoom(',
    'static int diaWrapLines(',
    'static int diaWrapExtra(',
    'static const char *diaEnumText(',
    'static int diaRowTailWidth(',
    'static int diaItemHeight(',
    'static void diaRowState(',
    'static int diaRowCollapses(',
    'static int diaLayoutBottom(',
))
wrap = function(fnt, 'static int fntWrapPut(') + function(fnt, 'int fntWrapText(')

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef unsigned long long u64;
@TYPES@
@DEFINES@
#define MENU_ITEM_HEIGHT 19
enum { _STR_NOT_SET, _STR_ON, _STR_OFF, _STR_NO_ITEMS };
static const char *strings[] = {"<not set>", "On", "Off", "<no values>"};
static const char *_l(int id) { return strings[id]; }
static struct { int fonts[1]; } theme, *gTheme = &theme;
static int screenWidth = 640, screenHeight = 480;
/* A fixed 8-wide font: every character, a space included, is 8 */
static int fntCalcDimensions(int id, const char *s) { (void)id; int n = 0; for (; *s; s++) n += ((*s & 0xC0) != 0x80); return 8 * n; }
static int rmUnScaleX(int x) { return x; }
static int rmWideScale(int x) { return x; }
static int txtNext(const char *s, uint32_t *cp) { *cp = (unsigned char)*s; return 1; }
static int txtNoSpaceScript(const char *s, int len) { (void)s; (void)len; return 0; }
static int txtBreakAt(const char *start, const char *s) { (void)start; (void)s; return 1; }
@WRAP@
static char diaWrapBuf[DIA_WRAP_MAX];
@FUNCTIONS@

static struct UIItem page[16];
static int n;
static void add(UIItemType type, const char *text)
{
    memset(&page[n], 0, sizeof(page[n]));
    page[n].type = type;
    page[n].visible = page[n].enabled = 1;
    page[n].label.text = text;
    page[n].label.stringId = -1;
    n++;
    page[n].type = UI_TERMINATOR;
}

int main(void)
{
    /* 100 characters = 800 wide: alone on its row at x0 = 20 it has 600 (to the 20 margin) and wraps to 2 lines */
    const char *note = "No existing POPStarter SMB configuration was detected. Enter the correct network settings first.";
    int lines;

    n = 0;
    add(UI_HEADER, "Title");
    add(UI_SPLITTER, NULL);
    add(UI_LABEL, note);
    add(UI_BREAK, NULL);
    add(UI_OK, NULL);
    assert(diaWrapRoom(&page[2], 20, 1) == 600);
    lines = diaWrapLines(note, 600);
    assert(lines == 2);
    for (char *p = diaWrapBuf, *q; *p; p = q + (*q != 0)) { /* every wrapped line fits */
        q = strchr(p, '\n');
        if (!q)
            q = p + strlen(p);
        assert((q - p) * 8 <= 600);
    }
    assert(diaWrapExtra(&page[2], 600) == MENU_ITEM_HEIGHT);
    assert(diaItemHeight(&page[2], 10, diaWrapExtra(&page[2], 600)) == 10 + MENU_ITEM_HEIGHT);
    /* The layout gives the row its extra line. Header, splitter, note, the break's own row and OK: 5 rows 10 high
       and 10 apart from y = 20, one line taller */
    int plain = 20 + 4 * (10 + 10) + 10;
    assert(diaLayoutBottom(page, 10, 10, 20, 20) == plain + MENU_ITEM_HEIGHT);
    /* A short label alone on its row takes one line, and a short header too */
    page[2].label.text = "Short";
    assert(diaLayoutBottom(page, 10, 10, 20, 20) == plain);
    assert(diaWrapExtra(&page[0], diaWrapRoom(&page[0], 20, 1)) == 0);

    /* After a spacer (the About credit rows) the room starts where the spacer ends: 20 + 30 + 2 = 52 */
    n = 0;
    add(UI_SPACER, NULL);
    add(UI_LABEL, note);
    add(UI_BREAK, NULL);
    assert(diaSpacerWidth(20) == 30);
    assert(diaWrapRoom(&page[1], 52, 1) == 640 - 20 - 52);
    assert(diaLayoutBottom(page, 10, 10, 20, 20) == 20 + (10 + MENU_ITEM_HEIGHT) + 10 + 10);

    /* A label with a control after it, or after another label, does not wrap: it is fitted instead */
    n = 0;
    add(UI_LABEL, note);
    add(UI_SPACER, NULL);
    add(UI_BOOL, NULL);
    add(UI_BREAK, NULL);
    assert(diaWrapRoom(&page[0], 20, 1) == 0);
    assert(diaWrapRoom(&page[0], 20, 0) == 0);
    assert(diaLayoutBottom(page, 10, 10, 20, 20) == 20 + 10 + 10 + 10);
    /* ... and leaves its row the spacer (50 + 2) and the On/Off (3 * 8 + 2) */
    assert(diaRowTailWidth(&page[0]) == 52 + 26);
    page[2].intvalue.current = 1;
    assert(diaRowTailWidth(&page[0]) == 52 + 18);
    /* a hidden control asks for nothing; a self-fitting value no more than DIA_TAIL_VALUE_W */
    page[2].visible = 0;
    assert(diaRowTailWidth(&page[0]) == 52);
    page[2].visible = 1;
    page[2].type = UI_STRING;
    strcpy(page[2].stringvalue.text, "A string far wider than 100");
    assert(diaRowTailWidth(&page[0]) == 52 + DIA_TAIL_VALUE_W + 2);

    /* a hidden label wraps nothing and takes no height */
    n = 0;
    add(UI_LABEL, note);
    add(UI_BREAK, NULL);
    page[0].visible = 0;
    assert(diaWrapRoom(&page[0], 20, 1) == 0);

    puts("PASS: lone labels wrap and the layout gives them their lines; others leave their row room");
    return 0;
}
'''

if not failures:
    program = (HARNESS.replace('@TYPES@', types).replace('@DEFINES@', defines)
               .replace('@WRAP@', wrap).replace('@FUNCTIONS@', functions))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'room.c'
        exe = Path(tmp) / ('room' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('harness failed (exit %d):\n%s' % (run.returncode, run.stderr))

# --- what diaRenderItem draws -------------------------------------------------------------------------------------

render = function(dia, 'static void diaRenderItem(')
for kind, call in (('UI_OK', 'diaRenderValue(x, y, txt, txtcol, selected)'),
                   ('UI_INT', 'diaRenderValue(x, y, tmp, txtcol, selected)'),
                   ('UI_BOOL', 'diaRenderValue(x, y, txtval, txtcol, selected)'),
                   ('UI_PASSWORD', 'diaRenderValue(x, y, stars, txtcol, selected)'),
                   ('UI_BUTTON', 'diaRenderValue(x, y, diaLabelText(item), txtcol, selected)'),
                   ('UI_ENUM', 'diaRenderValue(x, y, diaEnumText(item), txtcol, selected)')):
    if call not in render:
        failures.append('diaRenderItem: %s must fit the room left (%s)' % (kind, call))
# The one unbounded draw left is a label already known to end by mid-screen
if render.count('fntRenderString(gTheme->fonts[0], x, y, ALIGN_NONE, 0, 0,') != 1 or \
        'x + diaMeasure(txt) <= screenWidth / 2' not in render:
    failures.append('diaRenderItem: only a label that ends by mid-screen may draw without a bound')
if 'screenWidth - DIA_VALUE_MARGIN - x - diaRowTailWidth(item)' not in render or \
        'fntRenderStringFit(gTheme->fonts[0], x, y, ALIGN_NONE, room, txt, txtcol, 0)' not in render:
    failures.append('diaRenderItem: a long label must leave its row room and end in "..."')
if 'diaWrapBuf' not in render or '*h = spacingH + (lines - 1) * MENU_ITEM_HEIGHT;' not in render:
    failures.append('diaRenderItem: a lone long label must draw its wrapped lines and report their height')

ui = function(dia, 'void diaRenderUI(')
if 'int wrapRoom = diaWrapRoom(rc, x, lead);' not in ui or \
        'int rowH = diaItemHeight(rc, spacingH, diaWrapExtra(rc, wrapRoom));' not in ui:
    failures.append('diaRenderUI: a skipped row must advance by the same wrapped height it would draw')
if "w = rc->type == UI_SPACER ? diaSpacerWidth(x) : 0;" not in ui:
    failures.append('diaRenderUI: a skipped spacer must still move x, or a label after it wraps differently')
if 'cur == diaGetFirstControl(ui) && curBot + diaScrollOffset <= visibleBottom' not in ui:
    failures.append('diaRenderUI: a first control below the hints must not be snapped out of view')
if 'diaSpacerWidth(x)' not in function(dia, 'static int diaLayoutBottom('):
    failures.append('diaLayoutBottom: spacers must move x the way diaRenderItem does')

keyb = function(dia, 'int diaShowKeyb(')
if 'fntRenderStringFit(gTheme->fonts[0], 25, 20, ALIGN_NONE, 615 - 25, title, gTheme->textColor, 0);' not in keyb:
    failures.append('diaShowKeyb: the title must stop at its separating line')

# --- About credit rows --------------------------------------------------------------------------------------------
# Measured with the menu font (PoeVeticaNew 17 px, 4:3 SD) the rows below are 348-516 wide against 568 of room; the
# old ones ran 599-611. Keep every coder row to at most 64 characters as a cheap guard against regrowing them.
about = dialogs[dialogs.index('struct UIItem diaAbout[]'):]
about = about[:about.index('{UI_TERMINATOR}};')]
rows = re.findall(r'\{UI_LABEL, 0, 1, 1, -1, 0, 15, \{\.label = \{"([^"]+)", -1\}\}\}', about)
if not [row for row in rows if ' - ' in row]:
    failures.append('diaAbout: no coder rows matched; the row pattern no longer fits diaAbout')
for row in rows:
    if ' - ' in row and len(row) > 64:
        failures.append('diaAbout: coder row too long for 4:3 SD (%d characters): %s' % (len(row), row))

if failures:
    print('dia text room checks FAILED:')
    for f in failures:
        print(' - ' + f)
    sys.exit(1)
print('dia text room: values, buttons, On/Off and numbers fit; long labels wrap or leave room; About rows fit')
