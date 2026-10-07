"""Settings pages fit the screen before they scroll; BDM transports are indented; RiptOPL's own plasma.

- dia.c: a Settings page a few rows too tall (General & System, Interface, Network) put its OK below the
  hint bar. diaSettingsFitGap shrinks the gap between rows just enough to fit, never below
  UI_SETTINGS_MIN_GAP, and leaves a page that already fits untouched. Compiled and run below against
  pages of 16 to 30 rows, with the real diaItemHeight / break rules.
- dialogs.c: Internal HDD (exFAT), USB, MX4SIO and iLink are indented under BDM Devices Start Mode, the
  way Protocol sits under Network Connectivity.
- opl.c/opl.h: the default plasma is near-black to deep blue, and a config that still holds exactly the
  old official-OPL pair (0x28C5F9 over black) is treated as never customised.
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
dialogs_c = read('src/dialogs.c')
dialogs_h = read('include/dialogs.h')
guigame_c = read('src/guigame.c')
themes_c = read('src/themes.c')
config_h = read('include/config.h')
lang_base = read('lng_tmpl/_base.yml')
opl_c = read('src/opl.c')
opl_h = read('include/opl.h')

# --- the fit, compiled and run ---------------------------------------------------------------------

HARNESS = r'''
#include <stdio.h>
#include <string.h>

typedef unsigned long long u64;
@TYPES@
static int screenHeight = 480;
@DEFINES@
@FUNCTIONS@

#define TOP 20
#define BOTTOM 440 /* usedHeight 480 - 40, as diaRenderUI passes it */
static struct UIItem page[400];

/* A header line, a splitter, `rows` label+spacer+value rows, and the trailing OK -- the shape every
   composed Settings page has. `hidden` of the rows are invisible, like rows an updater hides. */
static void build(int rows, int hidden)
{
    int n = 0, r;
    memset(page, 0, sizeof(page));
    page[n].type = UI_HEADER; page[n++].visible = 1;
    page[n].type = UI_SPLITTER; page[n++].visible = 1;
    for (r = 0; r < rows; r++) {
        int vis = r < rows - hidden;
        page[n].type = UI_LABEL; page[n++].visible = vis;
        page[n].type = UI_SPACER; page[n++].visible = vis;
        page[n].type = UI_BOOL; page[n++].visible = vis;
        page[n].type = UI_BREAK; page[n++].visible = 1;
    }
    page[n].type = UI_OK; page[n++].visible = 1;
    page[n].type = UI_TERMINATOR;
}

static int fails;
static void expect(const char *what, int rows, int hidden, int wantGap, int wantFits)
{
    int gap, bottom;
    build(rows, hidden);
    gap = diaSettingsFitGap(page, UI_SETTINGS_SPACING_H, TOP, BOTTOM);
    bottom = diaLayoutBottom(page, UI_SETTINGS_SPACING_H, gap, TOP);
    if ((wantGap >= 0 && gap != wantGap) || (bottom <= BOTTOM) != wantFits) {
        printf("FAIL %s: gap %d, bottom %d (want gap %d, fits %d)\n", what, gap, bottom, wantGap, wantFits);
        fails++;
    }
}

int main(void)
{
    int rows;
    expect("Game Sources-sized page (fits already)", 14, 0, UI_SETTINGS_SPACING_H, 1);
    /* the tallest page that fits at the normal gap keeps it; one row more starts to tighten */
    for (rows = 14; rows < 40; rows++) {
        build(rows, 0);
        if (diaLayoutBottom(page, UI_SETTINGS_SPACING_H, UI_SETTINGS_SPACING_H, TOP) > BOTTOM)
            break;
    }
    expect("one row more than fits: tightens, and fits", rows, 0, -1, 1);
    build(rows, 0);
    if (diaSettingsFitGap(page, UI_SETTINGS_SPACING_H, TOP, BOTTOM) >= UI_SETTINGS_SPACING_H) {
        printf("FAIL an overflowing page kept the full gap\n");
        fails++;
    }
    expect("23 rows (General/Interface-sized): fits", 21, 0, -1, 1);
    expect("far too tall: stops at the minimum and scrolls", 30, 0, UI_SETTINGS_MIN_GAP, 0);
    /* The tallest page that still fits at the normal gap must keep it: tightening is only for overflow. */
    expect("the tallest page that already fits keeps its gap", rows - 1, 0, UI_SETTINGS_SPACING_H, 1);
    if (!fails)
        printf("settings fit: pages that fit keep their gap; taller ones tighten to fit, down to the floor\n");
    return fails ? 1 : 0;
}
'''

item_enum = re.search(r'^typedef enum \{.*?\} UIItemType;', dia_h, re.M | re.S)
item_struct = re.search(r'^struct UIItem\s*\{.*?^\};', dia_h, re.M | re.S)
defines = '\n'.join(re.findall(r'^#define UI_SETTINGS_(?:SPACING_H|MIN_GAP)\s+\d+', dia_c, re.M))
functions = ''.join(function_text(dia_c, 'src/dia.c', sig) for sig in (
    'static int diaShouldBreakLine(',
    'static int diaShouldBreakLineAfter(',
    'static int diaItemHeight(',
    'static int diaLayoutBottom(',
    'static int diaSettingsFitGap(',
))
if item_enum is None or item_struct is None:
    failures.append('include/dia.h: UIItemType / struct UIItem not found')
elif defines.count('#define') != 2:
    failures.append('src/dia.c: UI_SETTINGS_SPACING_H / UI_SETTINGS_MIN_GAP not found')
elif not failures:
    program = (HARNESS.replace('@TYPES@', item_enum.group(0) + '\n' + item_struct.group(0))
               .replace('@DEFINES@', defines).replace('@FUNCTIONS@', functions))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'fit.c'
        exe = Path(tmp) / ('fit' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('settings fit harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('settings fit harness reported failures')

render = function_text(dia_c, 'src/dia.c', 'void diaRenderUI(')
if render:
    if 'int gapH = settingsContext ? diaSettingsFitGap(ui, spacingH, y0, gTheme->usedHeight - 40) : spacingH;' not in render:
        failures.append('diaRenderUI: Settings pages must take their row gap from diaSettingsFitGap')
    if render.count('y += hmax + gapH;') != 2 or 'y += hmax + spacingH;' in render:
        failures.append('diaRenderUI: both line advances must use gapH (rows keep spacingH as their height)')

# --- BDM transports indented under BDM ----------------------------------------------------------------

for label in ('Internal HDD (exFAT)', 'USB', 'MX4SIO', 'iLink'):
    if '{.label = {"      %s", -1}}' % label not in dialogs_c:
        failures.append('dialogs.c: "%s" must be indented under BDM Devices Start Mode' % label)

# --- per-game DNAS ID clarity --------------------------------------------------------------------

if '{UI_LABEL, 0, 1, 1, -1, -30, 0, {.label = {NULL, _STR_DNAS_ID}}},' not in dialogs_c:
    failures.append('dialogs.c: the per-game DNAS field must be labelled DNAS ID, not generic Game ID')
if '- label: DNAS_ID\n  string: DNAS ID' not in lang_base:
    failures.append('lng_tmpl/_base.yml: DNAS ID needs an internal-English fallback')
core_aware = function_text(guigame_c, 'src/guigame.c', 'static void guiGameSetCoreAwareState(')
if core_aware and ('diaSetEnabled(diaCompatConfig, COMPAT_GAMEID, !neutrino);' not in core_aware or
                   'diaSetEnabled(diaCompatConfig, COMPAT_LOADFROMDISC, !neutrino);' not in core_aware):
    failures.append('guiGameSetCoreAwareState: DNAS entry/read controls must disable under Neutrino')

# --- plasma defaults and the old-pair migration ----------------------------------------------------

for name, value in (('BG_R', '0x0C'), ('BG_G', '0x3A'), ('BG_B', '0xA8'),
                    ('BLEND_R', '0x00'), ('BLEND_G', '0x02'), ('BLEND_B', '0x0A')):
    if not re.search(r'^#define RIPTOPL_PLASMA_%s\s+%s\b' % (name, value), opl_h, re.M):
        failures.append('opl.h: RIPTOPL_PLASMA_%s must be %s' % (name, value))
colors = function_text(opl_c, 'src/opl.c', 'void setDefaultColors(')
if colors and 'gDefaultBgColor[0] = RIPTOPL_PLASMA_BG_R;' not in colors:
    failures.append('setDefaultColors: the default plasma must be RiptOPL\'s, not official OPL\'s cyan')
defaults = function_text(opl_c, 'src/opl.c', 'static void setDefaults(')
if defaults and 'gDefaultPlasBlendColor[2] = RIPTOPL_PLASMA_BLEND_B;' not in defaults:
    failures.append('setDefaults: the default plasma blend must be RiptOPL\'s near-black')
load = function_text(opl_c, 'src/opl.c', 'static void _loadConfig(')
old_pair = ('gDefaultBgColor[0] == 0x28 && gDefaultBgColor[1] == 0xC5 && gDefaultBgColor[2] == 0xF9 &&\n'
            '                gDefaultPlasBlendColor[0] == 0x00 && gDefaultPlasBlendColor[1] == 0x00 && gDefaultPlasBlendColor[2] == 0x00')
if load and old_pair not in load:
    failures.append('_loadConfig: a config holding exactly the old default pair must get the new plasma')

# --- optional PS1/PS2 labels ----------------------------------------------------------------------

if 'UICFG_GAME_TYPE_LABELS' not in dialogs_h:
    failures.append('dialogs.h: game type labels need a stable dialog id')
if '_STR_GAME_TYPE_LABELS' not in dialogs_c or 'UICFG_GAME_TYPE_LABELS' not in dialogs_c:
    failures.append('dialogs.c: Interface settings must expose the game type labels toggle')
if '#define CONFIG_OPL_GAME_TYPE_LABELS' not in config_h:
    failures.append('config.h: game type labels must have a persisted master-config key')
if 'gGameTypeLabels = 0;' not in defaults:
    failures.append('setDefaults: [PS1]/[PS2] list labels must default Off')
if ('CONFIG_OPL_GAME_TYPE_LABELS, &gGameTypeLabels' not in load or
        'CONFIG_OPL_GAME_TYPE_LABELS, gGameTypeLabels' not in opl_c):
    failures.append('opl.c: game type labels preference must load and save')
draw_items = function_text(themes_c, 'src/themes.c', 'static void drawItemsList(')
if draw_items and not ('gGameTypeLabels' in draw_items and
                       '"[PS1] %s"' in draw_items and '"[PS2] %s"' in draw_items and
                       'list->mode != APP_MODE' in draw_items):
    failures.append('drawItemsList: opt-in labels must distinguish PS1/PS2 without labelling Apps')
if '- label: GAME_TYPE_LABELS\n  string: Show [PS1]/[PS2] Labels' not in lang_base:
    failures.append('lng_tmpl/_base.yml: game type labels setting needs an internal-English fallback')

if failures:
    print('Settings fit / plasma checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
