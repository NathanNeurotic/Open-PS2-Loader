"""GUI items ported from RIPPS2 (akilluminati47/RIPPS2), Group G.

1. Dialog polish (builds 89, 91, 96 and 108): a row that cannot be changed reads at half strength; a row whose
   controls are all hidden takes no line; a long page has a scroll bar and the right stick slides it; backing out of
   a submenu lands on the button that opened it. A remembered row that is hidden or switched off now starts on the
   first control instead of leaving the dialog at once (a fix over RIPPS2).
2. Font weight (build 114): <font>_weight=100..900 in a theme draws that font heavier: a variable face along its wght
   axis, a static one with its outlines grown. Checked against the host's FreeType when its headers are there.
3. Glyph sets (build 90): glyph_set=theme|builtin|standard|white in a theme, and Settings > Interface > Button
   Glyphs over every theme, swap the hint glyphs between frames. Standard and White are RIPPS2's own pictures.
4. The hint bar's theme keys (build 90): hints_hide, hints_order (a stable sort), hints_labels=0, hints_layout=column
   and hints_spacing. A theme with none of them draws the bar as before.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
DIA = 'src/dia.c'
FNT = 'src/fntsys.c'
THM = 'src/themes.c'
TTF = 'thirdparty/PoeVeticaNew.ttf'
PAD = 'src/pad.c'
GFX = 'gfx'
GUI = 'src/gui.c'
GLYPH_PARSE = 'int thmGlyphSetParse(const char *name)'
GLYPH_FOR = 'int thmGlyphSetFor(int themeSet)'
GLYPH_LOAD = 'static void thmGlyphSetLoad(theme_t *theme, int set, int onGui)'
HINT_RANK = 'int thmHintRank(const theme_t *theme, int token)'
DRAW_HINTS = 'static void drawHintText('
DRAW = 'src/themes.c'
START_FRAME = 'void guiStartFrame('
GUI_LOCK = 'guiLock();'
GLYPH_SETTINGS = ('configSetInt(configOPL, CONFIG_OPL_GLYPH_SET, gGlyphSet);', 'configReadGlyphSet(configOPL);',
                  'diaGetInt(ui, UICFG_GLYPH_SET, &gGlyphSet);', 'diaGetInt(diaUIConfig, UICFG_GLYPH_SET, &gGlyphSet);')
SETTINGS_FILES = ('src/opl.c', 'src/gui.c')


def read(rel):
    return (root / rel).read_text(encoding='utf-8')


def function(source, signature):
    pos = source.index(signature)
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1]
    raise AssertionError('unterminated ' + signature)


def run(name, code, cwd):
    src = Path(cwd) / (name + '.c')
    exe = Path(cwd) / (name + '.exe')
    src.write_text(code)
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(src), '-o', str(exe)], check=True, cwd=cwd)
    out = subprocess.run([str(exe)], check=True, cwd=cwd, capture_output=True, text=True)
    return out.stdout


ROW_TEST = r'''
#include <stdio.h>
enum { UI_TERMINATOR, UI_BREAK, UI_SPLITTER, UI_SPACER, UI_LABEL, UI_HEADER, UI_OK, UI_BUTTON, UI_INT, UI_STRING, UI_PASSWORD, UI_BOOL };
struct UIItem { int type, visible, enabled; };
%(funcs)s

static int lines(struct UIItem *ui)
{
    int n = 0, rowHidden = 0, rowShown = 0;
    for (; ui->type != UI_TERMINATOR; ui++) {
        if (diaRowCollapses(ui, rowHidden, rowShown)) {
            rowHidden = rowShown = 0;
            continue;
        }
        if (ui->type == UI_BREAK) {
            rowHidden = rowShown = 0;
            n++;
            continue;
        }
        diaRowState(ui, &rowHidden, &rowShown);
    }
    return n;
}

int main(void)
{
    struct UIItem a[] = {{UI_LABEL, 1, 1}, {UI_SPACER, 1, 1}, {UI_BOOL, 1, 0}, {UI_BREAK, 1, 1}, {UI_TERMINATOR, 1, 1}};
    struct UIItem b[] = {{UI_LABEL, 1, 1}, {UI_SPACER, 1, 1}, {UI_BOOL, 1, 1}, {UI_BREAK, 1, 1}, {UI_TERMINATOR, 1, 1}};
    struct UIItem c[] = {{UI_LABEL, 1, 1}, {UI_SPACER, 1, 1}, {UI_BOOL, 0, 0}, {UI_BREAK, 1, 1}, {UI_TERMINATOR, 1, 1}};
    struct UIItem d[] = {{UI_BUTTON, 1, 0}, {UI_TERMINATOR, 1, 1}};
    printf("%%d %%d %%d %%d %%d\n", diaRowDisabled(&a[0]), diaRowDisabled(&a[2]), diaRowDisabled(&b[0]), diaRowDisabled(&c[0]), diaRowDisabled(&d[0]));

    /* row 1 shown, row 2 a hidden label + hidden value (collapses), row 3 shown */
    struct UIItem e[] = {{UI_LABEL, 1, 1}, {UI_BOOL, 1, 1}, {UI_BREAK, 1, 1},
                         {UI_LABEL, 0, 1}, {UI_SPACER, 1, 1}, {UI_BOOL, 0, 1}, {UI_BREAK, 1, 1},
                         {UI_LABEL, 1, 1}, {UI_BOOL, 1, 1}, {UI_BREAK, 1, 1}, {UI_TERMINATOR, 1, 1}};
    /* a row whose label still shows keeps its line, and so does one with a shown control beside a hidden one */
    struct UIItem f[] = {{UI_LABEL, 1, 1}, {UI_SPACER, 1, 1}, {UI_BOOL, 0, 1}, {UI_BREAK, 1, 1},
                         {UI_LABEL, 1, 1}, {UI_BOOL, 0, 1}, {UI_INT, 1, 1}, {UI_BREAK, 1, 1}, {UI_TERMINATOR, 1, 1}};
    printf("%%d %%d\n", lines(e), lines(f));
    return 0;
}
'''


def check_rows(dia):
    funcs = '\n'.join(function(dia, sig) for sig in (
        'static int diaRowDisabled(const struct UIItem *item)',
        'static void diaRowState(struct UIItem *ui, int *rowHidden, int *rowShown)',
        'static int diaRowCollapses(struct UIItem *ui, int rowHidden, int rowShown)'))
    with tempfile.TemporaryDirectory() as d:
        out = run('rows', ROW_TEST % {'funcs': funcs}, d).split('\n')
    # disabled: label before a switched-off value, the value, an enabled row, a hidden one, a switched-off button
    assert out[0] == '1 1 0 0 1', out[0]
    # a row of only hidden things loses its line (3 -> 2); rows with anything shown keep theirs
    assert out[1] == '2 2', out[1]
    print('rows ok')


def check_wiring(dia, pad):
    render = function(dia, 'static void diaRenderItem(')
    assert 'diaRowDisabled(item)' in render and '/ 2) << 24' in render, 'half strength'
    layout = function(dia, 'static int diaLayoutBottom(')
    ui = function(dia, 'void diaRenderUI(')
    for body, name in ((layout, 'layout'), (ui, 'render')):
        assert 'diaRowCollapses(' in body and 'diaRowState(' in body, name + ': hidden rows take no line'
    assert '(rc != cur || diaPeek) && (y < y0 || y + rowH > viewBottom)' in ui, 'a row is drawn whole or not at all'
    assert 'if (diaPeek) {' in ui and 'diaScrollOffset = (int)diaPeekPos;' in ui, 'the peek holds the view'
    assert ui.index('int maxScroll =') < ui.index('if (diaPeek) {'), 'maxScroll is known with no cursor too'
    bar = ui[ui.index('The scroll bar'):]
    assert 'maxScroll > 0' in bar and 'thumbH < 24' in bar and bar.count('rmDrawRect(') >= 2, 'scroll bar'
    exe = function(dia, 'int diaExecuteDialog(')
    assert 'diaReturnSlot(ui)' in exe and 'diaReturnUi[slot] = NULL;' in exe, 'the return slot is read once'
    assert 'if (!cur || !diaIsControllable(cur))' in exe, 'a hidden remembered row falls back to the first control'
    i = exe.index('if (cur->type == UI_BUTTON) {')
    assert 'diaReturnRemember(ui, cur->id);' in exe[i:i + 200], 'a button remembers itself'
    assert '(sy > 24 || sy < -24) && diaScrollRange > 0' in exe and 'diaScrollRange = maxScroll;' in ui, 'a page that fits never enters peek'
    assert 'padGetRightStick(&sx, &sy);' in exe and 'diaPeek = 0; // the view follows the cursor again' in exe, 'peek input'
    assert 'if (diaPeek && getKeyOn(guiConfirmKey()))' in exe, 'the first confirm after a peek only brings the row back'
    assert 'pad->readOk = ret != 0;' in pad, 'a failed read is never a fresh stick'
    assert "(pad->buttons.mode >> 4) != 0x07 || !pad->readOk" in pad, 'analog mode, fresh sample only'
    print('wiring ok')


WEIGHT_TEST = r'''
#include <stdio.h>
#include <stdint.h>
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_MULTIPLE_MASTERS_H
#include FT_TRUETYPE_TABLES_H
#include FT_OUTLINE_H
%(funcs)s

int main(int argc, char **argv)
{
    FT_Library lib;
    FT_Face face;
    (void)argc;
    if (FT_Init_FreeType(&lib) || FT_New_Face(lib, argv[1], 0, &face) || FT_Set_Pixel_Sizes(face, 0, 18))
        return 2;
    int own = fntFaceOwnWeight(face), drawn = fntFaceSetWeight(lib, face, 700);
    int e = fntEmboldenFor(700, drawn);
    if (fntLoadGlyph(face, 'W', 0))
        return 3;
    long plainAdv = face->glyph->advance.x;
    unsigned plainW = face->glyph->bitmap.width;
    if (fntLoadGlyph(face, 'W', e))
        return 4;
    printf("%%d %%d %%d %%d %%d %%d\n", own, drawn, e, fntEmboldenFor(400, 400), fntEmboldenFor(900, 100),
           face->glyph->advance.x > plainAdv && face->glyph->bitmap.width >= plainW);
    return 0;
}
'''


def check_weight(fnt, thm):
    funcs = '\n'.join(function(fnt, sig) for sig in (
        'static int fntFaceOwnWeight(FT_Face face)', 'static int fntFaceSetWeight(FT_Library library, FT_Face face, int weight)',
        'static int fntEmboldenFor(int weight, int drawn)', 'static int fntLoadGlyph(FT_Face face, uint32_t gid, int embolden)'))
    assert 'fntLoadGlyph(font->face, gid, font->embolden)' in fnt, 'glyphs load through the weight'
    assert 'font->weight = font->embolden = 0;' in fnt, 'a new slot starts at its own weight'
    load = thm[thm.index('int fntHandle = fntLoadFile(fullPath, fontSize);'):][:900]
    assert '"default_font_weight"' in load and '"font%d_weight"' in load and 'weight >= 100 && weight <= 900' in load, 'theme key'
    inc = subprocess.run(['pkg-config', '--cflags', 'freetype2'], capture_output=True, text=True)
    lib = subprocess.run(['pkg-config', '--libs', 'freetype2'], capture_output=True, text=True)
    if inc.returncode or lib.returncode:
        print('weight: wiring ok; the host has no FreeType headers, so the glyph check is SKIPPED')
        return
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'w.c'
        exe = Path(d) / 'w.exe'
        src.write_text(WEIGHT_TEST % {'funcs': funcs})
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function'] + inc.stdout.split() + [str(src), '-o', str(exe)] + lib.stdout.split(), check=True)
        out = subprocess.run([str(exe), str(root / TTF)], check=True, capture_output=True, text=True).stdout.split()
    own, drawn, e, same, cap, wider = map(int, out)
    assert 100 <= own <= 1000 and drawn == own, out  # a static face stays at its own weight
    assert e == (700 - own) * 64 // 300 if own < 700 else e == 0, out
    assert same == 0 and cap == 96, out  # nothing to grow at its own weight; growth is capped
    assert wider == 1 or e == 0, 'a heavier W is wider'
    print('weight ok')


GLYPH_TEST = r"""
#include <stdio.h>
#include <strings.h>
enum { GLYPH_SET_THEME = 0, GLYPH_SET_BUILTIN, GLYPH_SET_STANDARD, GLYPH_SET_WHITE, GLYPH_SET_COUNT };
static int gGlyphSet;
%(keys)s
%(funcs)s
int main(void)
{
    printf("%%d %%d %%d %%d %%d %%d\n", thmGlyphSetParse("theme"), thmGlyphSetParse("BuiltIn"), thmGlyphSetParse("standard"),
           thmGlyphSetParse("White"), thmGlyphSetParse("ripps2"), thmGlyphSetParse(NULL));
    gGlyphSet = GLYPH_SET_THEME;
    printf("%%d ", thmGlyphSetFor(GLYPH_SET_WHITE));
    gGlyphSet = GLYPH_SET_STANDARD;
    printf("%%d\n", thmGlyphSetFor(GLYPH_SET_WHITE));
    return 0;
}
"""
GLYPH_NAMES = ('cross', 'circle', 'square', 'triangle', 'start', 'select', 'L1', 'R1', 'L3', 'R3', 'left', 'right')


def check_glyphs(thm, gui, settings_src):
    keys = thm[thm.index('static const char *const glyphSetKeys[GLYPH_SET_COUNT]'):]
    keys = keys[:keys.index(';') + 1]
    funcs = '\n'.join(function(thm, sig) for sig in (GLYPH_PARSE, GLYPH_FOR))
    with tempfile.TemporaryDirectory() as d:
        out = run('glyphs', GLYPH_TEST % {'keys': keys, 'funcs': funcs}, d).split('\n')
    assert out[0] == '0 1 2 3 0 0', out[0]  # an unknown name or none is the theme's own
    assert out[1] == '3 2', out[1]  # Theme follows the theme's key; any other pick wins over it
    load = function(thm, GLYPH_LOAD)
    assert 'rmUnloadTexture(tex)' in load and 'texFree(tex)' in load and 'texLoadInternal(tex, glyphSlots[i])' in load
    assert 'theme->glyphPath[0] ? theme->glyphPath : NULL' in load, 'Theme loads the theme\'s own glyphs back'
    assert '"glyph_set"' in thm and 'thmGlyphSetLoad(newT, thmGlyphSetFor(newT->glyphSetDef), 0)' in thm, 'theme key'
    start = function(gui, START_FRAME)
    assert start.index(GUI_LOCK) < start.index('thmGlyphSetRefresh()'), 'the swap runs under guiLock, between frames'
    for name in GLYPH_NAMES:
        for glyph_set in ('standard', 'white'):
            png = (root / GFX / ('glyph_%s_%s.png' % (glyph_set, name))).read_bytes()
            assert png[:8] == b'\x89PNG\r\n\x1a\n', name
    for needle in GLYPH_SETTINGS:
        assert needle in settings_src, needle
    print('glyphs ok')


HINT_TEST = r"""
#include <stdio.h>
#include <string.h>
#include <strings.h>
enum { START_ICON = 1, SQUARE_ICON, TRIANGLE_ICON, SELECT_ICON, R3_ICON, L3_ICON, CROSS_ICON };
enum { THM_HINT_MENU = 0, THM_HINT_RUN, THM_HINT_INFO, THM_HINT_OPTIONS, THM_HINT_REFRESH, THM_HINT_STAR, THM_HINT_VIEW, THM_HINT_COUNT };
typedef struct theme { int hintsOrder[THM_HINT_COUNT]; int hintsOrderCount; } theme_t;
%(code)s
static void show(const char *list)
{
    int out[THM_HINT_COUNT], n = thmHintParse(list, out, THM_HINT_COUNT), i;
    for (i = 0; i < n; i++)
        printf("%%d", out[i]);
    printf("|");
}
int main(void)
{
    theme_t t;
    show("star,view");
    show(" Run , info menu,run,bogus,triangle");
    show("start select r3 l3 cross circle square");
    show("");
    show(NULL);
    printf("\n");
    t.hintsOrderCount = thmHintParse("info,run", t.hintsOrder, THM_HINT_COUNT);
    printf("%%d %%d %%d %%d %%d\n", thmHintRank(&t, THM_HINT_INFO), thmHintRank(&t, THM_HINT_RUN), thmHintRank(&t, THM_HINT_MENU),
           thmHintRank(NULL, THM_HINT_RUN), thmHintToken(CROSS_ICON) == THM_HINT_RUN && thmHintToken(L3_ICON) == THM_HINT_VIEW);
    return 0;
}
"""


def check_hints(thm, draw):
    code = thm[thm.index('static const char *const hintKeys[THM_HINT_COUNT]'):]
    code = code[:code.index(HINT_RANK)]
    code += function(thm, HINT_RANK)
    with tempfile.TemporaryDirectory() as d:
        out = run('hints', HINT_TEST % {'code': code}, d).split('\n')
    assert out[0] == '56|1203|045612|||', out[0]  # names and buttons, each once, unknown names skipped
    assert out[1] == '0 1 7 7 1', out[1]  # named hints first in their order; the rest share the last rank
    body = function(draw, DRAW_HINTS)
    assert 'menuHintsLock();' in body and body.index('menuHintsLock();') < body.index('row[n++] = hint;') < body.index('menuHintsUnlock();')
    assert '!(gTheme->hintsHide & (1 << thmHintToken(hint->icon_id)))' in body, 'hints_hide'
    assert 'thmHintRank(gTheme, thmHintToken(row[j - 1]->icon_id)) > r' in body, 'a stable sort by hints_order'
    assert 'if (gTheme->hintsColumn)' in body and 'gTheme->hintsSpacing' in body, 'hints_layout=column'
    for key in ('"hints_hide"', '"hints_order"', '"hints_labels"', '"hints_layout"', '"hints_spacing"'):
        assert key in thm, key
    assert 'newT->hintsLabels = 1;' in thm and 'newT->hintsColumn = 0;' in thm, 'no keys: the bar as before'
    print('hints ok')


dia = read(DIA)
check_rows(dia)
check_wiring(dia, read(PAD))
check_weight(read(FNT), read(THM))
check_glyphs(read(THM), read(GUI), '\n'.join(read(f) for f in SETTINGS_FILES))
check_hints(read(THM), read(DRAW))
print('ripps2 gui port ok')
