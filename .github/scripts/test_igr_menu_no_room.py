"""In-Game Menu on, but no room for it in a RetroAchievements launch: Debug Colors blinks grey at the combo.

The same script runs in RiptOPL (src/platform/system.cpp) and Open-PS2-Loader (src/system.c); it finds which tree it
is in by its files.

In the RetroAchievements editions the menu is igrovl.elf, which the launcher copies to IGROVL_BASE (0xCC000) only
when the modules end below it and sit at the usual address. Without it the launcher set config->IgrMenu to 0, so the
combo left the game as with the menu off, and with Debug Colors on nothing told that apart from a combo that never
reached the menu, although docs/IGR.md gave grey for "no overlay for this launch".

1. The launcher's config lines are compiled and run: with the menu on and no overlay placed, IgrMenu is 0 and
   IgrMenuNoRoom 1; with the overlay placed, the menu off, or Mode 6, IgrMenuNoRoom stays 0.
2. ee_core's IGR_Thread lines are compiled and run: the combo (not the power button, not another combo) in such a
   launch blinks three times in the grey the menu path uses for a menu that was not there, only with Debug Colors on.
3. IgrMenuNoRoom is the last field of EECoreConfig_t, after the RA editions' other menu fields, so the overlay's
   view of the fields before it does not move; the handler still opens the menu only with IgrMenu set.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []

if (root / 'src/platform/system.cpp').exists():  # RiptOPL
    LAYOUT = dict(system='src/platform/system.cpp', host='src/app/host.cpp', ext='.c',
                  start='    config->_CompatMask = compatflags;\n', pre='config->IgrMenu = gIgrMenu; /* fillCoreConfig */')
else:  # Open-PS2-Loader
    LAYOUT = dict(system='src/system.c', host=None, ext='.c',
                  start='    config->IgrMenu = gIgrMenu && !(compatflags & COMPAT_MODE_6);', pre='')


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


system = read(LAYOUT['system'])
padhook = read('ee_core/src/padhook.c')
coreconfig = read('ee_core/include/coreconfig.h')
docs = read('docs/IGR.md')

# --- the launcher's lines, from the config's IgrMenu to the end of the IGR_OVERLAY block ---------------------------
launcher = ''
pos = system.find(LAYOUT['start'])
if pos < 0:
    failures.append('%s: %r not found' % (LAYOUT['system'], LAYOUT['start'].strip()))
else:
    overlay = system.find('#ifdef IGR_OVERLAY', pos)
    end = system.find('\n#endif', overlay)
    if overlay < 0 or end < 0 or system.find('IgrMenuNoRoom', pos, end) < 0:
        failures.append('%s: the IGR_OVERLAY config lines must set config->IgrMenuNoRoom' % LAYOUT['system'])
    else:
        launcher = system[pos:end] + '\n#endif\n'
if LAYOUT['host'] is not None:
    # RiptOPL fills config->IgrMenu in fillCoreConfig, before the lines above (Mode 6 and no overlay then clear it)
    if 'config->IgrMenu = gIgrMenu;' not in read(LAYOUT['host']):
        failures.append('%s: fillCoreConfig must set config->IgrMenu = gIgrMenu' % LAYOUT['host'])
    fill = system.find('host::launch().fillCoreConfig(config')
    if fill < 0 or pos < 0 or fill > pos:
        failures.append('%s: fillCoreConfig must run before the IgrMenu lines' % LAYOUT['system'])

# --- ee_core's lines, right after IGR_Thread's wake loop -------------------------------------------------------------
thread = re.search(r'\n(#ifdef IGR_OVERLAY\n(?:(?!#endif).*\n)*?#endif\n)\s*DPRINTF\("IGR thread woken up!\\n"\);',
                   padhook)
if thread is None:
    failures.append('padhook.c: IGR_Thread needs an IGR_OVERLAY block for IgrMenuNoRoom before "IGR thread woken up!"')
thread = thread.group(1) if thread else ''
igr_thread = padhook.find('static void IGR_Thread(void *arg)')
if thread and (igr_thread < 0 or padhook.find(thread) < igr_thread):
    failures.append('padhook.c: the IgrMenuNoRoom blink must be in IGR_Thread')

# The grey the menu path blinks for IGR_MENU_CANNOT_DRAW: a menu that was not there to run
grey = (re.search(r'why\[\][^=]*=\s*\{\s*(0x[0-9A-Fa-f]+)', padhook) or
        re.search(r'IGR_MENU_DRAW_FAILED \? 0x[0-9A-Fa-f]+ :\s*(0x[0-9A-Fa-f]+);', padhook))
if grey is None:
    failures.append('padhook.c: the menu path\'s grey for a menu that was not there was not found')
grey = grey.group(1) if grey else '0'

# --- 3. the field, appended; the handler unchanged -----------------------------------------------------------------
if not re.search(r'int IgrRaUnlocked;\s*(?:/\*(?:(?!\*/).)*\*/\s*)?int IgrMenuNoRoom;\s*#endif\s*\};', coreconfig,
                 re.S):
    failures.append('coreconfig.h: int IgrMenuNoRoom; must be the last field, after IgrRaUnlocked (RA editions)')
if 'Pad_Data.combo_type == IGR_COMBO_START_SELECT && config->IgrMenu && !Power_Button.press' not in padhook:
    failures.append('padhook.c: the handler must open the menu only with config->IgrMenu set')
if not re.search(r'\| \*\*Grey\*\* \|[^\n]*no room', docs):
    failures.append('docs/IGR.md: the grey row must name a launch with no room for the menu')

HARNESS = r'''
#include <stdio.h>
#include <stddef.h>

#define IGR_MENU
#define IGR_OVERLAY
#define COMPAT_MODE_6 0x20
#define IGR_COMBO_START_SELECT 0xF6
#define IGR_COMBO_R3_L3 0xF9
#define GREY @GREY@
typedef unsigned char u8;

struct EECoreConfig_t {
    unsigned int _CompatMask;
    int IgrMenu;
    const u8 *IgrRaHunt;
    int IgrRaHuntCount;
    int IgrRaTotal;
    int IgrRaUnlocked;
    int IgrMenuNoRoom;
};

static int gIgrMenu;

static void launcher(struct EECoreConfig_t *config, unsigned int compatflags, int igrOvlPlaced)
{
    const u8 *raHunt = NULL;
    int raHuntCount = 0, raHuntTotal = 0, raHuntUnlocked = 0;

    @PRE@
@LAUNCHER@
}

static int EnableDebug, blinks;
static unsigned int blinkColour;
static struct { int combo_type; } Pad_Data;
static struct { int press; } Power_Button;

static void blink(int count, unsigned int colour)
{
    blinks += count;
    blinkColour = colour;
}
#define DBGCOL_BLNK(count, colour, forever, type, description) blink(count, colour)

static void thread(struct EECoreConfig_t *config)
{
@THREAD@
}

static int bad;
#define CHECK(cond, ...) do { if (!(cond)) { printf(__VA_ARGS__); printf("\n"); bad = 1; } } while (0)

int main(void)
{
    static const struct { int menu; unsigned int compat; int placed, igrMenu, noRoom; } launches[] = {
        {1, 0, 1, 1, 0},               // the overlay went in: the menu opens
        {1, 0, 0, 0, 1},               // menu on, no room: the plain combo, marked
        {0, 0, 0, 0, 0},               // menu off
        {1, COMPAT_MODE_6, 0, 0, 0},   // Mode 6 turns the menu off: not a lack of room
        {0, COMPAT_MODE_6, 0, 0, 0},
    };
    static const int combos[] = {IGR_COMBO_START_SELECT, IGR_COMBO_R3_L3};
    unsigned int i, c;
    int debug, press;

    for (i = 0; i < sizeof(launches) / sizeof(launches[0]); i++) {
        struct EECoreConfig_t config = {0, 0, NULL, 0, 0, 0, 0};

        gIgrMenu = launches[i].menu;
        launcher(&config, launches[i].compat, launches[i].placed);
        CHECK(config.IgrMenu == launches[i].igrMenu && config.IgrMenuNoRoom == launches[i].noRoom,
              "launch %u (menu %d, compat 0x%x, placed %d): IgrMenu %d IgrMenuNoRoom %d, want %d %d", i,
              launches[i].menu, launches[i].compat, launches[i].placed, config.IgrMenu, config.IgrMenuNoRoom,
              launches[i].igrMenu, launches[i].noRoom);

        for (debug = 0; debug <= 1; debug++)
            for (c = 0; c < sizeof(combos) / sizeof(combos[0]); c++)
                for (press = 0; press <= 1; press++) {
                    int want = debug && config.IgrMenuNoRoom && combos[c] == IGR_COMBO_START_SELECT && !press;

                    EnableDebug = debug;
                    Pad_Data.combo_type = combos[c];
                    Power_Button.press = press;
                    blinks = 0;
                    blinkColour = 0;
                    thread(&config);
                    CHECK(want ? blinks == 3 && blinkColour == GREY : blinks == 0,
                          "launch %u, Debug Colors %d, combo 0x%X, power button %d: %d blinks of 0x%06X, want %s", i,
                          debug, combos[c], press, blinks, blinkColour, want ? "3 grey" : "none");
                }
    }
    if (bad)
        return 1;
    printf("PASS: a launch with no room for the menu blinks grey at the combo with Debug Colors on, and only then\n");
    return 0;
}
'''

if launcher and thread and not failures:
    compiler = next((c for c in map(shutil.which, ('gcc', 'clang', 'cc')) if c), None)
    if compiler is None:
        failures.append('no C compiler for the harness (tried gcc, clang, cc)')
    else:
        code = (HARNESS.replace('@GREY@', grey).replace('@PRE@', LAYOUT['pre'])
                .replace('@LAUNCHER@', launcher).replace('@THREAD@', thread))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / ('noroom' + LAYOUT['ext'])
            binary = path / ('noroom.exe' if sys.platform == 'win32' else 'noroom')
            source.write_text(code, encoding='utf-8')
            build = subprocess.run([compiler, '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(source), '-o',
                                    str(binary)], capture_output=True, text=True)
            if build.returncode != 0:
                failures.append('harness did not compile:\n' + build.stderr)
            else:
                run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if run.returncode != 0:
                    failures.append('harness failed (%d):\n%s%s' % (run.returncode, run.stdout, run.stderr))
                else:
                    print(run.stdout.strip())

if failures:
    print('In-Game Menu no-room checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('In-Game Menu no room: the launch marks it and Debug Colors shows it grey at the combo')
