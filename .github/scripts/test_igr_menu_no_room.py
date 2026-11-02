"""In-Game Menu on, but no room for it in a RetroAchievements launch: Debug Colors blinks grey at the combo.

The same script runs in RiptOPL (src/platform/system.cpp) and Open-PS2-Loader (src/system.c); it finds which tree it
is in by its files.

In the RetroAchievements editions the menu is igrovl.elf, which the launcher copies to IGROVL_BASE (0xCC000) only
when the modules end below it and sit at the usual address. Without it the launcher set config->IgrMenu to 0, so the
combo left the game as with the menu off, and with Debug Colors on nothing told that apart from a combo that never
reached the menu, although docs/IGR.md gave grey for "no overlay for this launch".

1. The launcher's config lines are compiled and run: with the menu on and no overlay placed, IgrMenu is 0 and
   IgrMenuNoRoom 1; with the overlay placed, the menu off, or Mode 6, IgrMenuNoRoom stays 0.
2. ee_core's IGR_Thread lines are compiled and run: the combo (not the power button, not another combo, not the PC's
   reset) in such a launch blinks three times in the grey the menu path uses for a menu that was not there, only
   with Debug Colors on.
3. IgrMenuNoRoom is the last field of EECoreConfig_t, after the RA editions' other menu fields, so the overlay's
   view of the fields before it does not move; the handler still opens the menu only with IgrMenu set.
4. The PC's reset (RAR1, IGR_RequestReset) leaves the game at once, as the combo did before the menu: the VBLANK
   handler's menu lines and IGR_RequestReset are compiled and run. With the menu on they open it for the combo but
   not for the PC's request. Builds without the menu or without RetroAchievements keep no flag for it.
5. The RA watch block (RiptOPL: the RA work area) is placed right after the modules, before the menu's cheats, so the
   cheats take only the room it leaves: a long cheat file cannot push it, and with it the menu, past IGROVL_BASE.
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

# --- 3. the field, appended; the handler opens the menu only with IgrMenu set ----------------------------------------
if not re.search(r'int IgrRaUnlocked;\s*(?:/\*(?:(?!\*/).)*\*/\s*)?int IgrMenuNoRoom;\s*#endif\s*\};', coreconfig,
                 re.S):
    failures.append('coreconfig.h: int IgrMenuNoRoom; must be the last field, after IgrRaUnlocked (RA editions)')
if 'Pad_Data.combo_type == IGR_COMBO_START_SELECT && config->IgrMenu && !Power_Button.press && !IGR_FROM_PC' \
        not in padhook:
    failures.append('padhook.c: the handler must open the menu only with config->IgrMenu set, never for the PC\'s reset')
if not re.search(r'\| \*\*Grey\*\* \|[^\n]*no room', docs):
    failures.append('docs/IGR.md: the grey row must name a launch with no room for the menu')
if 'RAR1' not in docs:
    failures.append('docs/IGR.md: the menu section must say the PC\'s reset (RAR1) still leaves at once')

# --- 4. the PC's reset: its flag, IGR_RequestReset, and the handler's menu lines -------------------------------------
flag = re.search(r'\n(#if defined\(RETROACHIEVEMENTS\) && defined\(IGR_MENU\)\n(?:(?!#endif).*\n)*?#endif\n)', padhook)
if flag is None or 'static volatile int IGR_PcReset' not in flag.group(1) or '#define IGR_FROM_PC 0' not in flag.group(1):
    failures.append('padhook.c: IGR_PcReset (RA builds with the menu), and IGR_FROM_PC 0 elsewhere, were not found')
flag = flag.group(1) if flag else ''
request = re.search(r'\nvoid IGR_RequestReset\(void\)\n\{\n(?:.*\n)*?\}\n', padhook)
if request is None or 'IGR_PcReset = 1;' not in request.group(0):
    failures.append('padhook.c: IGR_RequestReset must mark the PC\'s reset (IGR_PcReset = 1)')
request = request.group(0) if request else ''
gate = re.search(r'\n(#ifdef IGR_MENU\n    // With In-Game Menu on, the reset combo pauses(?:(?!#endif).*\n)*?#endif\n)', padhook)
handler = padhook.find('static int IGR_Intc_Handler(int cause)')
if gate is None or handler < 0 or padhook.find(gate.group(1)) < handler:
    failures.append('padhook.c: the IGR_MENU lines of IGR_Intc_Handler were not found')
gate = gate.group(1) if gate else ''

# --- 5. the RA watch block before the menu's cheats --------------------------------------------------------------
if LAYOUT['host'] is not None:
    order = ('host::launch().raWorkBytes(', 'host::launch().igrCheatsPlace(at, room)', 'u8 *at = (u8 *)ModuleStorage + ModuleStorageSize;')
else:
    order = ('ModuleStorageEnd = PlaceWatchBlock(ModuleStorageEnd);', 'int bytes = igrCheatsPack(at, room);',
             'u8 *at = (u8 *)ModuleStorageEnd;')
watch_at, cheats_at = system.find(order[0]), system.find(order[1])
if watch_at < 0 or cheats_at < 0 or watch_at > cheats_at or system.count(order[0]) != 1:
    failures.append('%s: the RA watch block (%s) must be placed once, before the menu\'s cheats (%s): a long cheat file '
                    'would push it, and the menu, past IGROVL_BASE' % (LAYOUT['system'], order[0], order[1]))
elif order[2] not in system[watch_at:cheats_at]:
    failures.append('%s: the menu\'s cheats must start where the modules and the watch block end (%s)'
                    % (LAYOUT['system'], order[2]))

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
static int IGR_PcReset; // padhook.c's flag for the PC's reset (RAR1)
#define IGR_FROM_PC IGR_PcReset

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
    int debug, press, pc;

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
                for (press = 0; press <= 1; press++)
                    for (pc = 0; pc <= 1; pc++) { // pc: the request was the PC's (RAR1), not the pad's
                        int want = debug && config.IgrMenuNoRoom && combos[c] == IGR_COMBO_START_SELECT && !press && !pc;

                        EnableDebug = debug;
                        Pad_Data.combo_type = combos[c];
                        Power_Button.press = press;
                        IGR_PcReset = pc;
                        blinks = 0;
                        blinkColour = 0;
                        thread(&config);
                        CHECK(want ? blinks == 3 && blinkColour == GREY : blinks == 0,
                              "launch %u, Debug Colors %d, combo 0x%X, power button %d, PC reset %d: %d blinks of "
                              "0x%06X, want %s", i, debug, combos[c], press, pc, blinks, blinkColour,
                              want ? "3 grey" : "none");
                    }
    }
    if (bad)
        return 1;
    printf("PASS: a launch with no room for the menu blinks grey at the combo with Debug Colors on, and only then\n");
    return 0;
}
'''

# The VBLANK handler's menu lines (after IGR_CheckInputs) with padhook.c's flag and IGR_RequestReset, in a build with
# RetroAchievements and the menu, one with RA alone, and one with the menu alone. handler() returns 1 when the reset
# path that follows those lines in IGR_Intc_Handler runs this frame.
GATE_HARNESS = r'''
#include <stdio.h>

@DEFINES@
#define IGR_COMBO_START_SELECT 0xF6
#define IGR_COMBO_R3_L3 0xF9
#if defined(RETROACHIEVEMENTS) && defined(IGR_MENU)
#define HAS_PC_FLAG
#endif

static struct { unsigned char combo_type; } Pad_Data;
static __attribute__((unused)) struct { int press; } Power_Button;
static int IGR_Thread_ID = 5;
@FLAG@
@REQUEST@
#ifdef IGR_MENU
static volatile int IGR_MenuOpen;
static int IGR_MenuRearm = 1, held, wakes;
static struct { int IgrMenu; } g_config, *config = &g_config;
static void IGR_HoldInterrupts(void) { held++; }
static void iChangeThreadPriority(int id, int prio) { (void)id; (void)prio; }
static void iWakeupThread(int id) { (void)id; wakes++; }

static int handler(void)
{
@GATE@
    return Pad_Data.combo_type != 0x00;
}
#endif

static int bad;
#define CHECK(cond, ...) do { if (!(cond)) { printf(__VA_ARGS__); printf("\n"); bad = 1; } } while (0)

int main(void)
{
#ifdef IGR_MENU
    static const struct { int menu, pc, power, combo, reset, menuOpens; } frames[] = {
        {1, 0, 0, IGR_COMBO_START_SELECT, 0, 1}, // the combo, menu on: the menu
        {0, 0, 0, IGR_COMBO_START_SELECT, 1, 0}, // menu off: the combo leaves
        {1, 0, 1, IGR_COMBO_START_SELECT, 1, 0}, // the power button twice, menu on: leaves
        {1, 0, 0, IGR_COMBO_R3_L3, 1, 0},        // power off, menu on
#ifdef RETROACHIEVEMENTS
        {1, 1, 0, 0, 1, 0},                      // the PC's reset, menu on: leaves, no menu
        {0, 1, 0, 0, 1, 0},                      // the PC's reset, menu off: leaves
#endif
    };
    unsigned int i;

#ifndef RETROACHIEVEMENTS
    CHECK(IGR_FROM_PC == 0, "a build without RetroAchievements keeps no PC flag");
#endif
    for (i = 0; i < sizeof(frames) / sizeof(frames[0]); i++) {
        int reset;

        g_config.IgrMenu = frames[i].menu;
        Power_Button.press = frames[i].power;
        Pad_Data.combo_type = frames[i].combo;
        IGR_MenuOpen = 0;
        IGR_MenuRearm = 1;
        wakes = held = 0;
#ifdef HAS_PC_FLAG
        IGR_PcReset = 0;
        if (frames[i].pc)
            IGR_RequestReset();
#endif
        reset = handler();
        CHECK(reset == frames[i].reset && IGR_MenuOpen == frames[i].menuOpens && wakes == frames[i].menuOpens &&
                  held == frames[i].menuOpens,
              "frame %u (menu %d, PC reset %d, power button %d, combo 0x%X): reset %d, menu %d, wakes %d, want %d %d",
              i, frames[i].menu, frames[i].pc, frames[i].power, frames[i].combo, reset, IGR_MenuOpen, wakes,
              frames[i].reset, frames[i].menuOpens);
    }
#ifdef HAS_PC_FLAG
    // The PC's reset only fills an empty request, and only with an IGR thread (Mode 6 has none)
    Pad_Data.combo_type = IGR_COMBO_R3_L3;
    IGR_PcReset = 0;
    IGR_RequestReset();
    CHECK(Pad_Data.combo_type == IGR_COMBO_R3_L3 && !IGR_PcReset, "a request already there must stay the pad's");
    Pad_Data.combo_type = 0;
    IGR_Thread_ID = -1;
    IGR_RequestReset();
    CHECK(Pad_Data.combo_type == 0 && !IGR_PcReset, "Mode 6: no IGR thread, so the PC's reset asks nothing");
#endif
#else
    CHECK(IGR_FROM_PC == 0, "a build without the menu keeps no PC flag");
    IGR_RequestReset();
    CHECK(Pad_Data.combo_type == IGR_COMBO_START_SELECT, "without the menu the PC's reset is the combo, as before");
#endif
    if (bad)
        return 1;
    printf("PASS: @NAME@\n");
    return 0;
}
'''

compiler = next((c for c in map(shutil.which, ('gcc', 'clang', 'cc')) if c), None)


def build_and_run(name, code):
    if compiler is None:
        failures.append('no C compiler for the harness (tried gcc, clang, cc)')
        return
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        source = path / ('harness' + LAYOUT['ext'])
        binary = path / ('harness.exe' if sys.platform == 'win32' else 'harness')
        source.write_text(code, encoding='utf-8')
        build = subprocess.run([compiler, '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(source), '-o',
                                str(binary)], capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('%s: harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        if run.returncode != 0:
            failures.append('%s: harness failed (%d):\n%s%s' % (name, run.returncode, run.stdout, run.stderr))
        else:
            print(run.stdout.strip())


if launcher and thread and not failures:
    build_and_run('no room', HARNESS.replace('@GREY@', grey).replace('@PRE@', LAYOUT['pre'])
                  .replace('@LAUNCHER@', launcher).replace('@THREAD@', thread))

if flag and request and gate and not failures:
    for name, defines, req in (
            ('RA build with the menu: the combo opens it, the PC\'s reset leaves past it',
             '#define RETROACHIEVEMENTS\n#define IGR_MENU', request),
            ('RA build without the menu: the PC\'s reset is the combo, as before', '#define RETROACHIEVEMENTS', request),
            ('menu build without RA: no PC flag, the combo opens the menu', '#define IGR_MENU', '')):
        build_and_run(name, GATE_HARNESS.replace('@DEFINES@', defines).replace('@FLAG@', flag)
                      .replace('@REQUEST@', req).replace('@GATE@', gate).replace('@NAME@', name))

if failures:
    print('In-Game Menu no-room checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('In-Game Menu no room: the launch marks it and Debug Colors shows it grey at the combo; the PC\'s reset leaves')
