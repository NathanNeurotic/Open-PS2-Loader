"""GUI items ported from RIPPS2 (akilluminati47/RIPPS2), Group G.

1. Dialog polish (builds 89, 91, 96 and 108): a row that cannot be changed reads at half strength; a row whose
   controls are all hidden takes no line; a long page has a scroll bar and the right stick slides it; backing out of
   a submenu lands on the button that opened it. A remembered row that is hidden or switched off now starts on the
   first control instead of leaving the dialog at once (a fix over RIPPS2).
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
DIA = 'src/dia.c'
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


dia = read(DIA)
check_rows(dia)
check_wiring(dia, read(PAD))
print('ripps2 gui port ok')
