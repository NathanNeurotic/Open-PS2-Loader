"""Ember Beta 2 settings (docs/EMBER-INTEGRATION-PLAN.md, Part 10).

The rule under test: RiptOPL only touches an Ember setting the user has CHANGED in RiptOPL. A setting
never changed here is EMBER_SETTING_UNSET, is never written or removed, and so a settings.txt somebody
wrote by hand keeps working. Changing one back to Default removes that key, so Ember's own default
applies again.

Everything below is compiled from the production source text, not a copy of it.
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


def ember_enums(source):
    blocks = re.findall(r'^enum \{[^}]*\bEMBER_[A-Z0-9_]+[^}]*\};', source, re.M)
    if len(blocks) < 4:
        failures.append('include/opl.h: expected the four Ember setting enums, found %d' % len(blocks))
    return '\n'.join(blocks) + '\n'


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


opl_c = read('src/opl.c')
opl_h = read('include/opl.h')
config_h = read('include/config.h')
cuesupport_h = read('include/cuesupport.h')

# --- Global settings: load, migration, save (src/opl.c) ------------------------------------------

CONFIG_KEYS = ('CONFIG_OPL_EMBER_DISPLAY', 'CONFIG_OPL_EMBER_DISPLAY_MODE', 'CONFIG_OPL_EMBER_DITHER',
               'CONFIG_OPL_EMBER_SHADING', 'CONFIG_OPL_EMBER_CONTROLLER')

GLOBALS_HARNESS = r'''
#include <stdio.h>
#include <string.h>

typedef struct config_set { int unused; } config_set_t;

/* A tiny config store: enough of configGetInt/configSetInt/configRemoveKey to run the real code. */
static struct { char key[64]; int value; int used; } store[16];
static config_set_t cfg;

static int configGetInt(config_set_t *c, const char *key, int *value)
{
    int i;
    (void)c;
    for (i = 0; i < 16; i++)
        if (store[i].used && strcmp(store[i].key, key) == 0) {
            *value = store[i].value;
            return 1;
        }
    return 0;
}
static int configSetInt(config_set_t *c, const char *key, const int value)
{
    int i, freeSlot = -1;
    (void)c;
    for (i = 0; i < 16; i++) {
        if (store[i].used && strcmp(store[i].key, key) == 0) {
            store[i].value = value;
            return 1;
        }
        if (!store[i].used && freeSlot < 0)
            freeSlot = i;
    }
    snprintf(store[freeSlot].key, sizeof(store[freeSlot].key), "%s", key);
    store[freeSlot].value = value;
    store[freeSlot].used = 1;
    return 1;
}
static int configRemoveKey(config_set_t *c, const char *key)
{
    int i;
    (void)c;
    for (i = 0; i < 16; i++)
        if (store[i].used && strcmp(store[i].key, key) == 0)
            store[i].used = 0;
    return 1;
}
static void clearStore(void) { memset(store, 0, sizeof(store)); }
static int has(const char *key, int *value) { return configGetInt(&cfg, key, value); }

@DEFINES@
@ENUMS@
int gEmberDisplay = 99, gEmberDither = 99, gEmberShading = 99, gEmberController = 99;

@FUNCTIONS@

static int fails;
static void expect4(const char *what, int d, int di, int s, int c)
{
    if (gEmberDisplay != d || gEmberDither != di || gEmberShading != s || gEmberController != c) {
        printf("FAIL %s: got display %d dither %d shading %d controller %d, want %d %d %d %d\n", what,
               gEmberDisplay, gEmberDither, gEmberShading, gEmberController, d, di, s, c);
        fails++;
    }
}

int main(void)
{
    int v;
    const int U = EMBER_SETTING_UNSET;

    /* A config that never saw these keys: nothing is set, so no settings.txt is ever touched. */
    clearStore();
    emberLoadSettings(&cfg);
    expect4("fresh config", U, U, U, U);

    /* Each key keeps every value in its range, including 0 (= changed back to Default). */
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY_MODE, EMBER_DISPLAY_480P);
    configSetInt(&cfg, CONFIG_OPL_EMBER_DITHER, EMBER_DITHER_OFF);
    configSetInt(&cfg, CONFIG_OPL_EMBER_SHADING, EMBER_SHADING_24);
    configSetInt(&cfg, CONFIG_OPL_EMBER_CONTROLLER, EMBER_CONTROLLER_D2A);
    emberLoadSettings(&cfg);
    expect4("every top value", EMBER_DISPLAY_480P, EMBER_DITHER_OFF, EMBER_SHADING_24, EMBER_CONTROLLER_D2A);
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY_MODE, 0);
    configSetInt(&cfg, CONFIG_OPL_EMBER_DITHER, 0);
    configSetInt(&cfg, CONFIG_OPL_EMBER_SHADING, 0);
    configSetInt(&cfg, CONFIG_OPL_EMBER_CONTROLLER, 0);
    emberLoadSettings(&cfg);
    expect4("changed back to Default", 0, 0, 0, 0);

    /* Out of range reads as never set -- a hand-edited or future value must not be written. */
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY_MODE, EMBER_DISPLAY_COUNT);
    configSetInt(&cfg, CONFIG_OPL_EMBER_DITHER, -3);
    configSetInt(&cfg, CONFIG_OPL_EMBER_SHADING, 7);
    configSetInt(&cfg, CONFIG_OPL_EMBER_CONTROLLER, EMBER_CONTROLLER_COUNT);
    emberLoadSettings(&cfg);
    expect4("out of range", U, U, U, U);

    /* Migration from the old key. It was written on every save, so its 0 cannot be told from "never
       touched" and reads as unset; 1 (240) and 2 (480i -- it always was) were chosen and carry over. */
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 2);
    emberLoadSettings(&cfg);
    expect4("legacy ember_display=2", EMBER_DISPLAY_480, U, U, U);
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 1);
    emberLoadSettings(&cfg);
    expect4("legacy ember_display=1", EMBER_DISPLAY_240, U, U, U);
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 0);
    emberLoadSettings(&cfg);
    expect4("legacy ember_display=0", U, U, U, U);
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 3); /* the old build never wrote 3 */
    emberLoadSettings(&cfg);
    expect4("legacy ember_display=3", U, U, U, U);

    /* The new key wins whenever it is present, even at 0. */
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 1);
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY_MODE, 0);
    emberLoadSettings(&cfg);
    expect4("new key beats legacy", 0, U, U, U);

    /* Save writes only what was changed, and always drops the legacy key after migrating it. */
    clearStore();
    configSetInt(&cfg, CONFIG_OPL_EMBER_DISPLAY, 2);
    emberLoadSettings(&cfg);
    gEmberDither = EMBER_DITHER_DEFAULT; /* changed back to Default: stored, so its key gets removed */
    emberSaveSettings(&cfg);
    if (!has(CONFIG_OPL_EMBER_DISPLAY_MODE, &v) || v != EMBER_DISPLAY_480) {
        printf("FAIL save: ember_display_mode must hold the migrated 480i (2)\n");
        fails++;
    }
    if (has(CONFIG_OPL_EMBER_DISPLAY, &v)) {
        printf("FAIL save: the legacy ember_display key must be dropped once migrated\n");
        fails++;
    }
    if (!has(CONFIG_OPL_EMBER_DITHER, &v) || v != 0) {
        printf("FAIL save: a setting changed back to Default must be stored as 0\n");
        fails++;
    }
    if (has(CONFIG_OPL_EMBER_SHADING, &v) || has(CONFIG_OPL_EMBER_CONTROLLER, &v)) {
        printf("FAIL save: a setting never changed in RiptOPL must not be written\n");
        fails++;
    }
    gEmberShading = U; /* and an unset one must be removed if an old value was stored */
    configSetInt(&cfg, CONFIG_OPL_EMBER_SHADING, EMBER_SHADING_24);
    emberSaveSettings(&cfg);
    if (has(CONFIG_OPL_EMBER_SHADING, &v)) {
        printf("FAIL save: an unset setting must remove its stored key\n");
        fails++;
    }

    if (!fails)
        printf("ember settings: global load, legacy migration and changed-only save verified\n");
    return fails ? 1 : 0;
}
'''

global_functions = ''.join(function_text(opl_c, 'src/opl.c', sig) for sig in (
    'static int emberSettingGet(',
    'static void emberSettingSet(',
    'static void emberLoadSettings(',
    'static void emberSaveSettings(',
))
global_defines = defines(config_h, 'include/config.h', CONFIG_KEYS) + \
    defines(opl_h, 'include/opl.h', ('EMBER_SETTING_UNSET',))
global_enums = ember_enums(opl_h)

if not failures:
    compile_and_run('ember_globals', GLOBALS_HARNESS.replace('@DEFINES@', global_defines)
                    .replace('@ENUMS@', global_enums).replace('@FUNCTIONS@', global_functions))

# The load and save must actually be called from the config load/save paths.
config_paths = re.sub(r'/\*.*?\*/|//[^\n]*', '', opl_c, flags=re.S)
load_config = function_text(config_paths, 'src/opl.c', 'static void _loadConfig(')
save_config = function_text(config_paths, 'src/opl.c', 'static void _saveConfig(')
if 'emberLoadSettings(configOPL);' not in load_config:
    failures.append('src/opl.c: _loadConfig does not call emberLoadSettings(configOPL)')
if 'emberSaveSettings(configOPL);' not in save_config:
    failures.append('src/opl.c: the settings save does not call emberSaveSettings(configOPL)')
if re.search(r'configSetInt\(configOPL, CONFIG_OPL_EMBER_DISPLAY,', opl_c):
    failures.append('src/opl.c: the legacy ember_display key is still written directly')

# --- A settings row stores a value only when the user actually changed it (src/gui.c) ------------

gui_c = read('src/gui.c')

ROW_HARNESS = r'''
#include <stdio.h>

struct UIItem { int unused; };
#define EMBER_SETTING_UNSET -1
static int picked;
static int diaGetInt(struct UIItem *ui, int id, int *value) { (void)ui; (void)id; *value = picked; return 1; }

@FUNCTIONS@

static int fails;
static void expect(const char *what, int shown, int current, int pick, int want)
{
    int got;
    struct UIItem ui;
    picked = pick;
    got = emberSettingFromRow(&ui, 1, shown, current);
    if (got != want) {
        printf("FAIL %s: got %d, want %d\n", what, got, want);
        fails++;
    }
}

int main(void)
{
    expect("never set, left at Default", 0, EMBER_SETTING_UNSET, 0, EMBER_SETTING_UNSET);
    expect("never set, a value picked", 0, EMBER_SETTING_UNSET, 2, 2);
    expect("set, left alone", 1, 1, 1, 1);
    expect("set, changed back to Default", 1, 1, 0, 0);
    expect("stored Default, left alone", 0, 0, 0, 0);
    if (!fails)
        printf("ember settings: a row stores a value only when it was changed\n");
    return fails ? 1 : 0;
}
'''

row_function = function_text(gui_c, 'src/gui.c', 'static int emberSettingFromRow(')
if row_function:
    compile_and_run('ember_row', ROW_HARNESS.replace('@FUNCTIONS@', row_function))

# --- The settings.txt rewrite (src/cuesupport.c) ------------------------------------------------

cue_c = read('src/cuesupport.c')

REWRITE_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <strings.h>

#define EMBER_SETTING_UNSET -1
typedef struct
{
    const char *key;
    const char *value;
} cue_setting_t;

@FUNCTIONS@

static int fails;
static void expect(const char *what, const char *before, const cue_setting_t *want, int n, const char *wantOut)
{
    char out[256];
    int len = cueRewriteSettings(before, (int)strlen(before), want, n, out, sizeof(out));
    if (len < 0 || len != (int)strlen(wantOut) || memcmp(out, wantOut, len) != 0) {
        printf("FAIL %s: got [%.*s] (%d), want [%s]\n", what, len < 0 ? 0 : len, out, len, wantOut);
        fails++;
    }
}

int main(void)
{
    const cue_setting_t ditherOff[] = {{"dither", "off"}};
    const cue_setting_t dropDisplay[] = {{"display", NULL}};
    const cue_setting_t dropBoth[] = {{"display", NULL}, {"dither", NULL}};
    const cue_setting_t two[] = {{"display", "480p"}, {"dither", "on"}};
    char small[5];

    expect("new key into an empty file", "", ditherOff, 1, "dither:off\n");
    expect("replace, keeping comments and other keys", "Dither : on\r\n# my notes\nfoo: 1\n", ditherOff, 1,
           "# my notes\nfoo: 1\ndither:off\n");
    expect("remove one key, keep the rest", "display: 240\ncontroller: d2a\n", dropDisplay, 1, "controller: d2a\n");
    expect("a key not asked about is left alone", "shading: 24\n", ditherOff, 1, "shading: 24\ndither:off\n");
    expect("leading blanks and upper case still match", "  DISPLAY:480\n", dropDisplay, 1, "");
    expect("comment lines are never keys", "# display: 240\n; dither: off\n", dropBoth, 2, "# display: 240\n; dither: off\n");
    expect("a longer key is not ours", "displayx: 1\n", dropDisplay, 1, "displayx: 1\n");
    expect("several keys, written in order", "", two, 2, "display:480p\ndither:on\n");
    expect("every line of the key goes, once written", "dither:on\ndither:off\n", ditherOff, 1, "dither:off\n");
    expect("no final newline", "foo:1", ditherOff, 1, "foo:1\ndither:off\n");
    expect("nothing asked: file kept as is", "foo: 1\n# x\n", ditherOff, 0, "foo: 1\n# x\n");
    if (cueRewriteSettings("", 0, ditherOff, 1, small, sizeof(small)) != -1) {
        printf("FAIL a result that does not fit must return -1\n");
        fails++;
    }

    /* Unset settings produce no work at all, so a hand-written file is never opened for writing. */
    {
        cue_setting_t list[4];
        int n = 0;
        static const char *const values[] = {NULL, "on", "off"};
        cueWantSetting(list, &n, "dither", EMBER_SETTING_UNSET, values, 3);
        cueWantSetting(list, &n, "dither", 7, values, 3);
        if (n != 0) {
            printf("FAIL an unset or out-of-range setting must add nothing (added %d)\n", n);
            fails++;
        }
        cueWantSetting(list, &n, "dither", 0, values, 3);
        cueWantSetting(list, &n, "dither", 2, values, 3);
        if (n != 2 || list[0].value != NULL || strcmp(list[1].value, "off") != 0) {
            printf("FAIL Default must mean remove (NULL) and 2 must mean off\n");
            fails++;
        }
    }

    if (!fails)
        printf("ember settings: settings.txt rewrite keeps every line it was not asked about\n");
    return fails ? 1 : 0;
}
'''

rewrite_functions = ''.join(function_text(cue_c, 'src/cuesupport.c', sig) for sig in (
    'static int cueLineSetsKey(',
    'int cueRewriteSettings(',
    'static void cueWantSetting(',
))
if rewrite_functions.count('{') >= 3:
    compile_and_run('ember_rewrite', REWRITE_HARNESS.replace('@FUNCTIONS@', rewrite_functions))

# cueApplySettings only opens a file when it has something to do there.
apply_fn = function_text(cue_c, 'src/cuesupport.c', 'void cueApplySettings(')
if apply_fn and not re.search(r'if \(nGlobal > 0\)', apply_fn):
    failures.append('cueApplySettings: the main settings.txt must only be touched when a global setting is set')
if apply_fn and not re.search(r'if \(nGame > 0\)', apply_fn):
    failures.append('cueApplySettings: a game\'s settings.txt must only be touched when that game has a setting')

APPLY_HARNESS = r'''
#include <stdio.h>
#include <string.h>

typedef struct
{
    int controllerPresent, controller;
    int shadingPresent, shading;
} config_set_t;

typedef struct
{
    const char *key;
    const char *value;
} cue_setting_t;

#define EMBER_GAMES_FOLDER "games"
#define EMBER_SETTINGS_NAME "settings.txt"
#define LOG(...) ((void)0)
@DEFINES@
@ENUMS@

int gEmberDisplay = EMBER_SETTING_UNSET;
int gEmberDither = EMBER_SETTING_UNSET;
int gEmberShading = EMBER_SETTING_UNSET;
int gEmberController = EMBER_SETTING_UNSET;

static int globalTouches, gameTouches;

static int configGetInt(config_set_t *cfg, const char *key, int *value)
{
    if (strcmp(key, CONFIG_ITEM_EMBER_CONTROLLER) == 0 && cfg->controllerPresent) {
        *value = cfg->controller;
        return 1;
    }
    if (strcmp(key, CONFIG_ITEM_EMBER_SHADING) == 0 && cfg->shadingPresent) {
        *value = cfg->shading;
        return 1;
    }
    return 0;
}
static const char *cueEmberFolder(void) { return "EMBER"; }
static char cueSep(const char *prefix) { (void)prefix; return '/'; }
static void cueRewriteSettingsFile(const char *path, const cue_setting_t *want, int count)
{
    (void)want;
    (void)count;
    if (strstr(path, "/games/") != NULL)
        gameTouches++;
    else
        globalTouches++;
}

@FUNCTIONS@

static int fails;
static void reset(config_set_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    gEmberDisplay = EMBER_SETTING_UNSET;
    gEmberDither = EMBER_SETTING_UNSET;
    gEmberShading = EMBER_SETTING_UNSET;
    gEmberController = EMBER_SETTING_UNSET;
    globalTouches = gameTouches = 0;
}
static void expect(const char *what, int globalWant, int gameWant)
{
    if (globalTouches != globalWant || gameTouches != gameWant) {
        printf("FAIL %s: touched global=%d game=%d, want %d %d\n", what,
               globalTouches, gameTouches, globalWant, gameWant);
        fails++;
    }
}

int main(void)
{
    config_set_t cfg;

    reset(&cfg);
    cueApplySettings("mass0:/", "Game", &cfg);
    expect("empty global and game lists do no file I/O", 0, 0);

    reset(&cfg);
    gEmberDisplay = EMBER_DISPLAY_240;
    cueApplySettings("mass0:/", "Game", &cfg);
    expect("one global setting touches only main settings", 1, 0);

    reset(&cfg);
    cfg.shadingPresent = 1;
    cfg.shading = EMBER_SHADING_24;
    cueApplySettings("mass0:/", "Game", &cfg);
    expect("one game setting touches only game settings", 0, 1);

    reset(&cfg);
    cfg.controllerPresent = 1;
    cfg.controller = EMBER_CONTROLLER_DEFAULT;
    cueApplySettings("mass0:/", "Game", &cfg);
    expect("per-game Default touches game settings to remove its key", 0, 1);

    reset(&cfg);
    cfg.controllerPresent = 1;
    cfg.controller = EMBER_CONTROLLER_D2A;
    cueApplySettings("mass0:/", NULL, &cfg);
    expect("no game identity means no game file access", 0, 0);

    reset(&cfg);
    cfg.shadingPresent = 1;
    cfg.shading = EMBER_SHADING_24;
    cueApplySettings("mass0:/", "../x", &cfg);
    expect("path-like game names do not touch game settings", 0, 0);

    if (!fails)
        printf("ember settings: apply guards prevent file access for empty setting lists\n");
    return fails ? 1 : 0;
}
'''

if apply_fn:
    apply_functions = (function_text(cue_c, 'src/cuesupport.c', 'int cueNameLaunchable(') +
                       function_text(cue_c, 'src/cuesupport.c', 'static void cueWantSetting(') +
                       apply_fn)
    apply_defines = (defines(config_h, 'include/config.h',
                             ('CONFIG_ITEM_EMBER_CONTROLLER', 'CONFIG_ITEM_EMBER_SHADING')) +
                     defines(cuesupport_h, 'include/cuesupport.h', ('CUE_NAME_LAUNCH_MAX',)) +
                     defines(opl_h, 'include/opl.h', ('EMBER_SETTING_UNSET',)))
    if apply_functions.count('{') >= 3:
        compile_and_run('ember_apply', APPLY_HARNESS.replace('@DEFINES@', apply_defines)
                        .replace('@ENUMS@', ember_enums(opl_h)).replace('@FUNCTIONS@', apply_functions))

# All five Ember launch legs call cueApplySettings with the game name and configSet.
for rel in ('src/bdmsupport.c', 'src/ethsupport.c', 'src/hddsupport.c', 'src/mmcesupport.c', 'src/udpfssupport.c'):
    content = read(rel)
    if 'cueApplySettings(' not in content:
        failures.append('%s: does not call cueApplySettings' % rel)
    if 'cueApplyDisplaySetting(' in content:
        failures.append('%s: still calls the legacy cueApplyDisplaySetting' % rel)
if 'cueApplyDisplaySetting(' in read('src/cuesupport.c'):
    failures.append('src/cuesupport.c: legacy cueApplyDisplaySetting is still present')

if failures:
    print('Ember settings checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
