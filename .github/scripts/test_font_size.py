"""Compile the menu font, config and theme-layout paths with host stubs.

Changing raster size must also rebuild list geometry, preserve explicitly sized theme
fonts, invalidate every font's glyph cache, and accept the same config on both boot paths.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
font = (ROOT / 'src/fntsys.c').read_text()
opl = (ROOT / 'src/opl.c').read_text()
theme = (ROOT / 'src/themes.c').read_text()
menus = (ROOT / 'src/menusys.c').read_text()
dia = (ROOT / 'src/dia.c').read_text()
dia_header = (ROOT / 'include/dia.h').read_text()
gui = (ROOT / 'src/gui.c').read_text()
font_header = (ROOT / 'include/fntsys.h').read_text()
opl_header = (ROOT / 'include/opl.h').read_text()


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    assert match is not None, signature
    return source[match.start():source.index('\n}', match.start()) + 2]


def run(name, program):
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / (name + '.c')
        binary = Path(directory) / name
        source.write_text(program)
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-I', str(ROOT), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)


common = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned long long u64;
#include "include/fntsys.h"
static int gFontSize = FONT_SIZE_DEFAULT;
''' + function(font, 'int fntScaleFontSize(') + '\n'
common += re.search(r'^#define MENU_ITEM_HEIGHT[^\n]+', opl_header, re.M).group() + '\n'

run('font_size', common + r'''
#define FNT_MAX_COUNT 5
static const float fDPI = 72.0f;
typedef struct { int isValid, fontSize, face; } font_t;
static font_t fonts[FNT_MAX_COUNT];
static int flushes[FNT_MAX_COUNT], sizes[FNT_MAX_COUNT], nativeH = 480;
static void fntCacheFlush(font_t *font) { flushes[font - fonts]++; }
static void rmGetScreenExtents(int *w, int *h) { *w = 640; *h = 480; }
static void rmGetScreenExtentsNative(int *w, int *h) { *w = 640; *h = nativeH; }
static float rmGetPAR(void) { return 1.0f; }
static void FT_Set_Char_Size(int face, int x, int y, float dpiX, float dpiY)
{
    float delta = dpiX - 72.0f * nativeH / 480;
    assert(x == y && delta > -0.0001f && delta < 0.0001f && dpiX == dpiY);
    sizes[face] = x / 64;
}
''' + function(font, 'static void fntUpdateAspectRatioLocked(') + r'''
typedef struct { int present, value; } config_set_t;
#define CONFIG_OPL_FONT_SIZE "font_size"
static int configGetInt(config_set_t *cfg, const char *key, int *value)
{
    assert(strcmp(key, CONFIG_OPL_FONT_SIZE) == 0);
    if (cfg->present) *value = cfg->value;
    return cfg->present;
}
''' + function(opl, 'static void configReadFontSize(') + r'''
int main(void)
{
    const int expected[] = {15, 17, 19};
    /* Built-in, translated and CJK fallback slots plus two explicitly sized theme faces. */
    for (int i = 0; i < FNT_MAX_COUNT; i++) fonts[i] = (font_t){1, 17, i};
    fonts[3].fontSize = 9;
    fonts[4].fontSize = 42;
    for (int mode = 0; mode < FONT_SIZE_COUNT; mode++) {
        config_set_t cfg = {1, mode};
        configReadFontSize(&cfg);
        assert(gFontSize == mode && MENU_ITEM_HEIGHT == expected[mode] + 2);
        for (nativeH = 224; nativeH <= 1080; nativeH += 214) {
            fntUpdateAspectRatioLocked();
            for (int i = 0; i < 3; i++) assert(sizes[i] == expected[mode]);
            assert(sizes[3] == 9 && sizes[4] == 42);
            for (int i = 0; i < 3; i++) assert(fonts[i].fontSize == 17);
        }
    }
    for (int i = 0; i < FNT_MAX_COUNT; i++) assert(flushes[i] == 15);
    config_set_t absent = {0, 0};
    configReadFontSize(&absent);
    assert(gFontSize == FONT_SIZE_DEFAULT);
    for (int invalid = -1; invalid <= FONT_SIZE_COUNT; invalid += FONT_SIZE_COUNT + 1) {
        config_set_t cfg = {1, invalid};
        configReadFontSize(&cfg);
        assert(gFontSize == FONT_SIZE_DEFAULT);
    }
    puts("PASS: menu raster sizes, custom point sizes, cache invalidation and config normalization");
}
''')

run('font_layout', common + r'''
#define DIM_UNDEF -1
#define MENU_POS_V 50
#define HINT_HEIGHT 32
#define LOG(...) ((void)0)
typedef int config_set_t;
typedef struct { int displayedItems; const char *decorator; void *decoratorImage, *coverElem; } items_list_t;
typedef struct theme_element { int width, height, type; void *extended; void (*drawElem)(void); struct theme_element *next; } theme_element_t;
typedef struct { theme_element_t *first; } theme_elems_t;
typedef struct {
    int usedHeight;
    theme_elems_t mainElems, infoElems, appsMainElems, appsInfoElems, favsMainElems, favsInfoElems;
    theme_elems_t vcdMainElems, vcdInfoElems, favsVcdMainElems, favsVcdInfoElems, favsAppsMainElems, favsAppsInfoElems;
} theme_t;
static int screenWidth = 640;
static void drawItemsList(void) {}
static int configGetStr(config_set_t *cfg, const char *key, const char **value)
{ (void)cfg; (void)key; (void)value; return 0; }
''' + function(theme, 'static void initItemsList(') + r'''
static int loadedFontSize = FONT_SIZE_DEFAULT;
static theme_t *gTheme;
enum { ELEM_TYPE_ITEMS_LIST = 1 };
static int locks, rooms, resets;
static void guiLock(void) { assert(locks == 0); locks++; }
static void guiUnlock(void) { assert(locks == 1); locks--; }
static void thmComputeTextRooms(theme_elems_t *family) { assert(locks == 1 && family != NULL); rooms++; }
typedef struct { void *pagestart, *current; } menu_item_t;
typedef struct menu_list { menu_item_t *item; struct menu_list *next; } menu_list_t;
static menu_list_t *menu;
''' + function(menus, 'void menuResetPageStarts(') + r'''
static void resetAndCheckPageStarts(void) {
    int first, second;
    menu_item_t a = {NULL, &first}, b = {NULL, &second};
    menu_list_t tail = {&b, NULL}, middle = {NULL, &tail}, head = {&a, &middle};
    menu = &head;
    menuResetPageStarts();
    assert(a.pagestart == a.current && b.pagestart == b.current);
    menu = NULL;
    resets++;
}
#define menuResetPageStarts resetAndCheckPageStarts
''' + function(theme, 'void thmRefreshFontSize(') + r'''
int main(void)
{
    theme_t layout = {.usedHeight = 480};
    for (int mode = 0; mode < FONT_SIZE_COUNT; mode++) {
        gFontSize = mode;
        for (int height = 1; height <= 400; height++) {
            theme_element_t elem = {.width = 100, .height = height};
            initItemsList(NULL, NULL, &layout, &elem, "list", NULL);
            items_list_t *items = elem.extended;
            assert(items->displayedItems >= 1);
            if (height >= MENU_ITEM_HEIGHT) assert(items->displayedItems * MENU_ITEM_HEIGHT <= height);
            free(items);
        }
        theme_element_t elem = {.width = DIM_UNDEF, .height = DIM_UNDEF};
        initItemsList(NULL, NULL, &layout, &elem, "list", NULL);
        assert(elem.width == 640 && elem.height == 398);
        free(elem.extended);
    }
    /* All list families, including filtered siblings and one-row Coverflow, update in place. */
    theme_elems_t *families[] = {
        &layout.mainElems, &layout.infoElems, &layout.appsMainElems, &layout.appsInfoElems,
        &layout.favsMainElems, &layout.favsInfoElems, &layout.vcdMainElems, &layout.vcdInfoElems,
        &layout.favsVcdMainElems, &layout.favsVcdInfoElems, &layout.favsAppsMainElems, &layout.favsAppsInfoElems};
    theme_element_t lists[12][2];
    items_list_t counts[12][2];
    for (int i = 0; i < 12; i++) {
        lists[i][0] = (theme_element_t){.height = 398, .type = ELEM_TYPE_ITEMS_LIST, .extended = &counts[i][0], .next = &lists[i][1]};
        lists[i][1] = (theme_element_t){.height = 19, .type = ELEM_TYPE_ITEMS_LIST, .extended = &counts[i][1]};
        families[i]->first = &lists[i][0];
    }
    thmRefreshFontSize(); /* Safe before theme/menu initialization. */
    assert(rooms == 0 && locks == 0);
    gTheme = &layout;
    for (int mode = 0; mode < FONT_SIZE_COUNT; mode++) {
        gFontSize = mode;
        int before = rooms;
        thmRefreshFontSize();
        assert(rooms == before + 12 && locks == 0 && loadedFontSize == mode);
        for (int i = 0; i < 12; i++) {
            assert(counts[i][0].displayedItems == 398 / MENU_ITEM_HEIGHT);
            assert(counts[i][1].displayedItems == 1);
            assert(families[i]->first == &lists[i][0]);
        }
        thmRefreshFontSize();
        assert(rooms == before + 12); /* No work for unchanged geometry. */
    }
    assert(resets == FONT_SIZE_COUNT);
    puts("PASS: list extents, all 12 theme families, in-place layout changes and visible selections");
}
''')

for path in ('static void _loadConfig(', 'static void miniInit('):
    assert 'configReadFontSize(configOPL);' in function(opl, path), path
assert 'CONFIG_OPL_FONT_SIZE, gFontSize' in function(opl, 'static void _saveConfig(')
assert 'gFontSize = FONT_SIZE_DEFAULT;' in function(opl, 'static void setDefaults(')
assert 'spacingH += fntScaleFontSize(FNTSYS_DEFAULT_SIZE) - FNTSYS_DEFAULT_SIZE;' in function(dia, 'void diaRenderUI(')
assert 'guiUpdateScreenScale();' in function(gui, 'static int guiSettingsDisplayUpdater(')
assert 'thmRefreshFontSize();' in function(gui, 'void guiUpdateScreenScale(')
assert 'loadedFontSize = gFontSize;' in function(theme, 'static int thmLoad(')
assert font.count('int fontSize = fntScaleFontSize(fonts[id].fontSize);') == 2, 'LTR and RTL baselines must match raster size'
print('PASS: both config load paths, save/defaults, live preview and LTR/RTL wiring')

dialog_types = re.search(r'^typedef enum \{.*?\} UIItemType;', dia_header, re.M | re.S).group()
dialog_types += re.search(r'^struct UIItem\s*\{.*?^\};', dia_header, re.M | re.S).group()
dialog_defines = '\n'.join(re.findall(r'^#define UI_(?:SETTINGS_SPACING_H|SETTINGS_MIN_GAP|SPACING_V|SPACER_WIDTH|SPACER_MINIMAL)\s+\d+', dia, re.M))
dialog_functions = '\n'.join(function(dia, signature) for signature in (
    'static int diaShouldBreakLine(', 'static int diaShouldBreakLineAfter(', 'static int diaSpacerWidth(',
    'static int diaItemHeight(', 'static void diaRowState(', 'static int diaRowCollapses(', 'static int diaLayoutBottom(', 'static int diaSettingsFitGap(',
))
run('font_dialog', common + dialog_types + '\n' + dialog_defines + r'''
static int screenHeight = 480;
/* Label wrapping (diaWrapRoom/diaWrapExtra) has its own harness, test_dia_text_room.py: no label wraps here. */
static int diaWrapRoom(const struct UIItem *item, int x, int lead) { (void)item; (void)x; (void)lead; return 0; }
static int diaWrapExtra(struct UIItem *item, int wrapRoom) { (void)item; (void)wrapRoom; return 0; }
''' + dialog_functions + r'''
int main(void)
{
    struct UIItem page[150];
    for (int mode = 0; mode < FONT_SIZE_COUNT; mode++) {
        gFontSize = mode;
        int size = fntScaleFontSize(FNTSYS_DEFAULT_SIZE);
        int spacing = UI_SETTINGS_SPACING_H + size - FNTSYS_DEFAULT_SIZE;
        for (int rows = 5; rows <= 30; rows += 5) {
            int n = 0;
            memset(page, 0, sizeof(page));
            page[n].type = UI_HEADER; page[n++].visible = 1;
            page[n].type = UI_SPLITTER; page[n++].visible = 1;
            for (int row = 0; row < rows; row++) {
                page[n].type = UI_LABEL; page[n++].visible = 1;
                page[n].type = UI_SPACER; page[n++].visible = 1;
                page[n].type = UI_BOOL; page[n++].visible = 1;
                page[n].type = UI_BREAK; page[n++].visible = 1;
            }
            page[n].type = UI_OK; page[n++].visible = 1;
            page[n].type = UI_TERMINATOR;
            int gap = diaSettingsFitGap(page, spacing, 20, 20, 440);
            assert(spacing + gap >= size); /* Raster rows never overlap, even at minimum gap. */
            assert(gap >= UI_SETTINGS_MIN_GAP && gap <= spacing);
            if (gap > UI_SETTINGS_MIN_GAP) assert(diaLayoutBottom(page, spacing, gap, 20, 20) <= 440);
            if (rows == 30) assert(gap == UI_SETTINGS_MIN_GAP); /* Tall pages scroll. */
        }
        assert(MENU_ITEM_HEIGHT >= size + 2);
    }
    puts("PASS: dialog rows fit or scroll without overlapping at every menu font size");
}
''')
