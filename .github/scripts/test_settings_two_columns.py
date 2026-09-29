"""Two-column Settings pages (SPIKE, branch spike/settings-two-columns).

A Settings page that would scroll is laid out in two columns under its title. This checks the parts
that can be checked without a screen, compiled from the production source of src/dia.c:
- diaColumnSplit: one column when the rows fit; otherwise the split that makes the taller column
  shortest.
- diaMeasureRows: rows are measured exactly as the render loop commits them; the title block (rows
  up to the first splitter) is found; a page with a multi-value row (an IP address) is refused.
- diaFixedWidth: inside a column a -40 label takes 56% of the column, never squeezing the value.
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


dia_c = read('src/dia.c')
dia_h = read('include/dia.h')

types = re.search(r'typedef enum\s*\{([^}]*?UI_TERMINATOR[^}]*)\}', dia_h, re.S)
if types is None:
    failures.append('include/dia.h: the UI item type enum was not found')

defines = '\n'.join(re.findall(r'^#define (?:DIA_COL_[A-Z_]+|UI_SPACER_MINIMAL)\s+\S+', dia_c, re.M))

functions = ''.join(function_text(dia_c, 'src/dia.c', sig) for sig in (
    'static int diaShouldBreakLine(',
    'static int diaShouldBreakLineAfter(',
    'static int diaItemHeight(',
    'static int diaColumnSplit(',
    'static int diaMeasureRows(',
    'static int diaFixedWidth(',
))

HARNESS = r'''
#include <stdio.h>

enum { @TYPES@ };
struct UIItem {
    int type;
    int id;
    unsigned char enabled;
    unsigned char visible;
    short int hintId;
    short int fixedWidth;
    short int fixedHeight;
};
static int screenWidth = 640, screenHeight = 448;
static int diaColWidth;
@DEFINES@

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

static struct UIItem page[128];
static int np;
static void add(int type, int fixedWidth)
{
    struct UIItem it = {type, 0, 1, 1, -1, (short)fixedWidth, 0};
    page[np++] = it;
}
static void row(int values)
{
    add(UI_LABEL, -40);
    add(UI_SPACER, 0);
    while (values-- > 0)
        add(UI_ENUM, 0);
    add(UI_BREAK, 0);
}

int main(void)
{
    int rows[DIA_COL_MAX_ROWS], title, n, i;

    /* split: fits -> one column; else the balanced split */
    {
        int h[20];
        for (i = 0; i < 20; i++)
            h[i] = 30;
        CHECK(diaColumnSplit(h, 20, 600) == 0, "20 rows that fit must stay one column");
        CHECK(diaColumnSplit(h, 20, 300) == 10, "20 equal rows must split 10/10 (got %d)", diaColumnSplit(h, 20, 300));
        h[0] = 200; /* one tall row up front */
        CHECK(diaColumnSplit(h, 20, 300) == 7, "a tall first row pulls the split up (got %d)", diaColumnSplit(h, 20, 300));
        CHECK(diaColumnSplit(h, 1, 10) == 0, "one row cannot be split");
    }

    /* measure: title block + 18 single-value rows + OK */
    np = 0;
    add(UI_HEADER, 0);
    add(UI_SPLITTER, 0);
    for (i = 0; i < 18; i++)
        row(1);
    add(UI_OK, 0);
    add(UI_TERMINATOR, 0);
    n = diaMeasureRows(page, 10, rows, DIA_COL_MAX_ROWS, &title);
    /* 22, as the render loop draws it: a UI_BREAK has height, so the break after the last row is a
       spacing row of its own before OK -- the visible gap above the button. */
    CHECK(n == 22, "header + splitter + 18 rows + the gap + OK = 22 rows (got %d)", n);
    CHECK(title == 2, "the title block is the header and its splitter (got %d)", title);

    /* a row with four values (an IP address) keeps the page in one column */
    np = 0;
    add(UI_HEADER, 0);
    add(UI_SPLITTER, 0);
    row(1);
    row(4);
    add(UI_OK, 0);
    add(UI_TERMINATOR, 0);
    CHECK(diaMeasureRows(page, 10, rows, DIA_COL_MAX_ROWS, &title) == -1, "a multi-value row must refuse columns");

    /* fixed widths: full screen as before; inside a 290 px column a -40 label takes 56% */
    {
        struct UIItem label = {UI_LABEL, 0, 1, 1, -1, -40, 0};
        struct UIItem wide = {UI_LABEL, 0, 1, 1, -1, -60, 0}; /* wider than any label shipped today */
        diaColWidth = 0;
        CHECK(diaFixedWidth(&label) == 256, "one column: -40 is 40%% of 640 (got %d)", diaFixedWidth(&label));
        diaColWidth = 290;
        CHECK(diaFixedWidth(&label) == 162, "in a column: -40 is 56%% of 290 (got %d)", diaFixedWidth(&label));
        CHECK(diaFixedWidth(&wide) == 290 - DIA_COL_VALUE_MIN, "a label never squeezes its value below the minimum (got %d)", diaFixedWidth(&wide));
    }

    if (!fails)
        printf("settings two columns: split, row measuring, multi-value guard and column widths verified\n");
    return fails ? 1 : 0;
}
'''


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


if not failures:
    type_list = re.sub(r'//[^\n]*', '', types.group(1))
    compile_and_run('two_columns', HARNESS.replace('@TYPES@', type_list).replace('@DEFINES@', defines)
                    .replace('@FUNCTIONS@', functions))

# The render loop and the Left/Right keys must actually use it.
if 'diaColumnRowDone(&flow, &y);' not in dia_c:
    failures.append('diaRenderUI: rows do not go through diaColumnRowDone')
if 'newf = diaColumnStep(cur, ui, -1);' not in dia_c or 'newf = diaColumnStep(cur, ui, 1);' not in dia_c:
    failures.append('diaExecuteDialog: Left/Right do not try diaColumnStep first')

if failures:
    print('Two-column settings checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
