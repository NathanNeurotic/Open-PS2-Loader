"""Exercise the Grid view's shape limits, scrolling and Up/Down steps (include/grid.h).

The header is compiled as-is into a small host program. Also checks that the Grid element, the
built-in Grid view and the Up/Down row navigation stay wired up. Multi-view themes idea: KrahJohlito.
"""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / 'include/grid.h').read_text(encoding='utf-8')
THEMES = (ROOT / 'src/themes.c').read_text(encoding='utf-8')
MENUSYS = (ROOT / 'src/menusys.c').read_text(encoding='utf-8')
GUI = (ROOT / 'src/gui.c').read_text(encoding='utf-8')
MAKEFILE = (ROOT / 'Makefile').read_text(encoding='utf-8')
CFG = (ROOT / 'misc/theme_grid.cfg').read_text(encoding='utf-8')

assert '"Grid"};' in THEMES
assert 'initGrid(themePath, themeConfig, theme, elem, name);' in THEMES
assert 'configReadBuffer(themeConfig, &theme_grid_cfg, size_theme_grid_cfg);' in THEMES
assert '(1u << THM_VIEW_GRID)' in THEMES
assert 'theme_grid.o' in MAKEFILE and 'misc/theme_grid.cfg' in MAKEFILE
assert 'type=Grid' in CFG and 'type=Coverflow' not in CFG
assert 'names[4] = "Grid";' in GUI and '#define GUI_THEME_VIEW_PICKS 4' in GUI
# Up/Down step a row in the Grid view; Left/Right step a cover as in Coverflow.
assert 'gridRowStep(count, index, gTheme->gridColumns, dir)' in MENUSYS
assert MENUSYS.count('if (gTheme->coverflow || gTheme->grid)') == 2
assert MENUSYS.count('if (gTheme->grid)') == 2

program = r'''
#include <assert.h>
#include <stdio.h>
@HEADER@

int main(void)
{
    int rows = 0, columns = 0;
    gridClamp(&rows, &columns);
    assert(rows == GRID_DEFAULT_ROWS && columns == GRID_DEFAULT_COLUMNS);
    rows = 9, columns = 9;
    gridClamp(&rows, &columns);
    assert(columns == GRID_MAX_COLUMNS && rows * columns <= GRID_MAX_CELLS && rows == 2);
    rows = 4, columns = 4;
    gridClamp(&rows, &columns);
    assert(rows == 4 && columns == 4);

    // The selected row stays in the middle, never past either end.
    assert(gridTopRow(30, 0, 3, 4) == 0);
    assert(gridTopRow(30, 5, 3, 4) == 0);
    assert(gridTopRow(30, 13, 3, 4) == 2);
    assert(gridTopRow(30, 29, 3, 4) == 5);
    assert(gridTopRow(5, 4, 3, 4) == 0);
    assert(gridTopRow(1, 0, 3, 4) == 0);

    // Up/Down keep the column, a short last row takes its last cover, -1 leaves the grid.
    assert(gridRowStep(10, 1, 4, -1) == -1);
    assert(gridRowStep(10, 5, 4, -1) == 1);
    assert(gridRowStep(10, 1, 4, 1) == 5);
    assert(gridRowStep(10, 7, 4, 1) == 9);
    assert(gridRowStep(10, 9, 4, 1) == -1);
    assert(gridRowStep(10, 8, 4, -1) == 4);
    assert(gridRowStep(0, 0, 4, 1) == -1);
    assert(gridRowStep(10, 12, 4, 1) == -1);

    puts("grid: shape limits, scrolling and row steps passed");
    return 0;
}
'''.replace('@HEADER@', HEADER)

with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    source = folder / 'grid.c'
    binary = folder / ('grid' + ('.exe' if os.name == 'nt' else ''))
    source.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
