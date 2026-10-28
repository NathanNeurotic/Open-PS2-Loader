"""GUI items ported from RIPPS2 (akilluminati47/RIPPS2), Group G.

1. Dialog polish (builds 89, 91, 96 and 108): a row that cannot be changed reads at half strength; a row whose
   controls are all hidden takes no line; a long page has a scroll bar and the right stick slides it; backing out of
   a submenu lands on the button that opened it. A remembered row that is hidden or switched off now starts on the
   first control instead of leaving the dialog at once (a fix over RIPPS2).
2. Font weight (build 114): <font>_weight=100..900 in a theme draws that font heavier: a variable face along its wght
   axis, a static one with its outlines grown. Checked against the host's FreeType when its headers are there.
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


dia = read(DIA)
check_rows(dia)
check_wiring(dia, read(PAD))
check_weight(read(FNT), read(THM))
print('ripps2 gui port ok')
