"""The screen position (H-POS, V-POS, Overscan) is kept for each video mode (RIPPS2 build 124, akilluminati47).

1080i and 480i rarely centre the same way, so each mode keeps its own position in the settings file as
xoff_<mode>, yoff_<mode> and overscan_<mode>. The shared xoff/yoff/overscan keys are still written as the
mode in use's, so an older build reads what it always did, and a mode with no saved position takes them.

This compiles the screenPos* functions from the app source on the host against a small config stub and
checks:

- a new mode with no saved position keeps the current one (the old behaviour);
- switching back to a mode brings back the position it had;
- moving the position in the same dialog that changed the mode gives the new mode that position;
- the positions survive a save and a load, and a reset forgets them;
- both video-mode dialogs call screenPosModeChanged and put the position back when the mode is reverted;
- the settings load, save and defaults paths call screenPosLoad, screenPosSave and screenPosReset;
- the three hints say the position is kept for each video mode.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
cpp = (root / 'src/app/opl.cpp').exists()
OPL = root / ('src/app/opl.cpp' if cpp else 'src/opl.c')
LOAD = root / ('src/app/settingsio.cpp' if cpp else 'src/opl.c')
GUI = root / ('src/ui/guisettings.cpp' if cpp else 'src/gui.c')
BASE = root / ('lng/tmpl/_base.yml' if cpp else 'lng_tmpl/_base.yml')
failures = []


def read(path):
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


opl = read(OPL)
start = opl.find('#define SCREEN_POS_MODES')
reset = opl.find('void screenPosReset(void)')
if start < 0 or reset < 0:
    print('%s: the screenPos* block is missing' % OPL.relative_to(root))
    sys.exit(1)
block = opl[start:opl.index('\n}', reset) + 3]

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct { char key[32][24]; int val[32]; int n; } config_set_t;
static int configGetInt(config_set_t *c, const char *k, int *v)
{
    for (int i = 0; i < c->n; i++)
        if (!strcmp(c->key[i], k)) { *v = c->val[i]; return 1; }
    return 0;
}
static int configSetInt(config_set_t *c, const char *k, int v)
{
    for (int i = 0; i < c->n; i++)
        if (!strcmp(c->key[i], k)) { c->val[i] = v; return 1; }
    snprintf(c->key[c->n], sizeof(c->key[0]), "%s", k);
    c->val[c->n++] = v;
    return 1;
}
static int gVMode, gXOff, gYOff, gOverscan;

@BLOCK@

/* What a video-mode dialog does: note the position, let the user change things, report the change. */
static void dialog(int newMode, int x, int y, int over)
{
    int prev = gVMode, ox = gXOff, oy = gYOff, oo = gOverscan;
    gVMode = newMode;
    gXOff = x; gYOff = y; gOverscan = over;
    screenPosModeChanged(prev, ox, oy, oo);
}

int main(void)
{
    config_set_t cfg = {0};
    screenPosReset();
    gVMode = 0; gXOff = 10; gYOff = 20; gOverscan = 3;

    dialog(5, 10, 20, 3);  /* to 1080i, position untouched: no saved one, so it carries over */
    assert(gXOff == 10 && gYOff == 20 && gOverscan == 3);
    dialog(5, -4, 7, 1);   /* move it while in 1080i */
    assert(gXOff == -4 && gYOff == 7 && gOverscan == 1);
    dialog(0, -4, 7, 1);   /* back to mode 0: its own position returns */
    assert(gXOff == 10 && gYOff == 20 && gOverscan == 3);
    dialog(5, 10, 20, 3);  /* to 1080i again, untouched: its own position returns */
    assert(gXOff == -4 && gYOff == 7 && gOverscan == 1);
    dialog(2, 30, 31, 2);  /* new mode and a move in one dialog: the new mode takes the move */
    assert(gXOff == 30 && gYOff == 31 && gOverscan == 2);
    dialog(5, 30, 31, 2);  /* 1080i kept what it had, mode 2 kept the move */
    assert(gXOff == -4 && gYOff == 7 && gOverscan == 1);
    dialog(2, -4, 7, 1);
    assert(gXOff == 30 && gYOff == 31 && gOverscan == 2);

    gXOff = 31;            /* a change in the same mode is saved as that mode's */
    screenPosSave(&cfg);
    int v;
    assert(configGetInt(&cfg, "xoff_2", &v) && v == 31);
    assert(configGetInt(&cfg, "xoff_5", &v) && v == -4);
    assert(configGetInt(&cfg, "overscan_0", &v) && v == 3);
    assert(!configGetInt(&cfg, "xoff_1", &v)); /* never-used modes are not written */

    screenPosReset();
    gVMode = 5; gXOff = 99; gYOff = 99; gOverscan = 9;
    screenPosLoad(&cfg);   /* load brings back the mode in use's own position */
    assert(gXOff == -4 && gYOff == 7 && gOverscan == 1);
    dialog(1, -4, 7, 1);   /* a mode with nothing saved keeps the current position */
    assert(gXOff == -4 && gYOff == 7 && gOverscan == 1);

    screenPosReset();      /* defaults forget every mode */
    gVMode = 0; gXOff = 0; gYOff = 0; gOverscan = 0;
    dialog(5, 0, 0, 0);
    assert(gXOff == 0 && gYOff == 0 && gOverscan == 0);
    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'pos.c'
    src.write_text(HARNESS.replace('@BLOCK@', block), encoding='utf-8')
    exe = Path(tmp) / 'pos'
    build = subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                           capture_output=True, text=True)
    if build.returncode:
        failures.append('harness did not compile:\n' + build.stderr)
    else:
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode or run.stdout.strip() != 'ok':
            failures.append('harness failed:\n' + run.stdout + run.stderr)

gui = read(GUI)
if gui.count('screenPosModeChanged(previousVMode, openX, openY, openOver);') != 2:
    failures.append('%s: both video-mode dialogs must call screenPosModeChanged' % GUI.relative_to(root))
if gui.count('int openX = gXOff, openY = gYOff, openOver = gOverscan;') != 2:
    failures.append('%s: both dialogs must note the position they opened with' % GUI.relative_to(root))
if len(re.findall(r'gVMode = previousVMode;\n\s*gXOff = openX;[^\n]*\n\s*gYOff = openY;\n\s*gOverscan = openOver;', gui)) != 2:
    failures.append('%s: a reverted mode change must put the position back too' % GUI.relative_to(root))

load = read(LOAD)
for call in ('screenPosLoad(configOPL);', 'screenPosSave(configOPL);'):
    if call not in load:
        failures.append('%s: %s missing' % (LOAD.relative_to(root), call))
if 'screenPosReset();' not in opl:
    failures.append('%s: setDefaults must call screenPosReset()' % OPL.relative_to(root))

base = read(BASE)
for label in ('HINT_XOFF', 'HINT_YOFF', 'HINT_MENU_OVERSCAN'):
    m = re.search(r'- label: %s\n  string: "([^"]*)"' % label, base)
    if not m or 'Kept for each video mode.' not in m.group(1):
        failures.append('%s: %s must say it is kept for each video mode' % (BASE.relative_to(root), label))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('screen position per video mode: ok')
