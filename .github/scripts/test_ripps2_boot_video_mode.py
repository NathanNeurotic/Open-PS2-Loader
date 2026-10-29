"""The screen starts in the saved video mode (RIPPS2 build 120, akilluminati47).

rmInit() runs before the settings load, so the boot screen used to come up in Auto and switch to the
saved mode a moment later: two resyncs on a 480p or 1080i set. bootDisplayPeek() reads vmode and
wide_screen straight from the memory-card settings file before rmInit().

This compiles bootDisplayPeek() from the app source on the host against a small config stub and checks:

- vmode and wide_screen are read from the file, and nothing else changes;
- a key that only starts the same way (vmode_x=) is not taken for it, and libconfig (wOPL) syntax
  ("vmode = 4;") is read too;
- a file that is not on a memory card, an unresolved mc?: path, or a missing file leaves the defaults;
- init() calls it before rmInit(), and the START skip puts the defaults back before applyConfig().
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
cpp = (root / 'src/app/opl.cpp').exists()
OPL = root / ('src/app/opl.cpp' if cpp else 'src/opl.c')
failures = []

opl = OPL.read_text(encoding='utf-8').replace('\r\n', '\n')
start = opl.find('static int bootPeekKey(')
if start < 0:
    print('%s: bootPeekKey is missing' % OPL.relative_to(root))
    sys.exit(1)
peek = opl.find('static void bootDisplayPeek(void)')
if peek < 0:
    print('%s: bootDisplayPeek is missing' % OPL.relative_to(root))
    sys.exit(1)
block = opl[start:opl.index('\n}\n', peek) + 3]

CONFIG = r'''
struct config_set_t {
    const char *name;
    const char *filename() const { return name; }
};
''' if cpp else r'''
typedef struct { const char *filename; } config_set_t;
'''
ACCESS = 'cfg.name' if cpp else 'cfg.filename'

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CONFIG_OPL 1
#define CONFIG_OPL_VMODE "vmode"
#define CONFIG_OPL_WIDESCREEN "wide_screen"
#define LOG(...) ((void)0)
@CONFIG@
static config_set_t cfg;
static config_set_t *configGetByType(int type) { return type == CONFIG_OPL ? &cfg : NULL; }
static int gVMode, gWideScreen, gOther;

@BLOCK@

static void writeFile(const char *text)
{
    FILE *fp = fopen("mc0:/settings.cfg", "w");
    assert(fp != NULL);
    fputs(text, fp);
    fclose(fp);
}

static void run(const char *path)
{
    gVMode = 0; gWideScreen = 0; gOther = 7;
    @ACCESS@ = path;
    bootDisplayPeek();
}

int main(void)
{
    writeFile("theme=<OPL>\nvmode=5\r\nvmode_x=9\nwide_screen=1\nwide_screenx=0\nxoff=3\n");
    run("mc0:/settings.cfg");
    assert(gVMode == 5 && gWideScreen == 1 && gOther == 7);

    writeFile("vmode=2\n");
    run("mc0:/settings.cfg");
    assert(gVMode == 2 && gWideScreen == 0);

    writeFile("vmode = 4;\n  wide_screen = 1;\nvmodex = 9;\n");  /* libconfig (wOPL) syntax */
    run("mc0:/settings.cfg");
    assert(gVMode == 4 && gWideScreen == 1);

    writeFile("vmode=5\nwide_screen=1\n");
    run("mc?:/settings.cfg");     /* unresolved card wildcard: not read */
    assert(gVMode == 0 && gWideScreen == 0);
    run("mass0:/settings.cfg");   /* USB is not up yet: not read */
    assert(gVMode == 0 && gWideScreen == 0);
    run("mc0:/missing.cfg");      /* no file: the defaults */
    assert(gVMode == 0 && gWideScreen == 0);
    run(NULL);
    assert(gVMode == 0 && gWideScreen == 0);
    puts("ok");
    return 0;
}
'''

# fopen() on the host opens "mc0:/settings.cfg" as a relative path: the harness runs in a temp folder
# holding real directories named "mc0:" and "mass0:", so the path the stub reports starts with "mc".
src_text = HARNESS.replace('@CONFIG@', CONFIG).replace('@BLOCK@', block).replace('@ACCESS@', ACCESS)
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / 'mc0:').mkdir()
    (Path(tmp) / 'mass0:').mkdir()
    src = Path(tmp) / ('peek.cpp' if cpp else 'peek.c')
    src.write_text(src_text, encoding='utf-8')
    exe = Path(tmp) / 'peek'
    compiler = ['c++', '-std=gnu++17'] if cpp else ['cc', '-std=gnu99']
    build = subprocess.run(compiler + ['-Wall', '-Werror', '-o', str(exe), str(src)], capture_output=True, text=True)
    if build.returncode:
        failures.append('harness did not compile:\n' + build.stderr)
    else:
        run = subprocess.run([str(exe)], capture_output=True, text=True, cwd=tmp)
        if run.returncode or run.stdout.strip() != 'ok':
            failures.append('harness failed:\n' + run.stdout + run.stderr)

init = opl[opl.find('static void init(void)'):]
init = init[:init.index('\n}\n')]
rel = OPL.relative_to(root)
peek_at, rm_at, cfg_at = init.find('bootDisplayPeek();'), init.find('rmInit();'), init.find('configInit(')
if peek_at < 0 or rm_at < 0 or peek_at > rm_at:
    failures.append('%s: init() must call bootDisplayPeek() before rmInit()' % rel)
if cfg_at < 0 or (peek_at >= 0 and cfg_at > peek_at):
    failures.append('%s: bootDisplayPeek() needs configInit() first (it reads the CONFIG_OPL path)' % rel)
skip_at = init.find('SKIPPING OPL CONFIG LOADING')
apply_at = init.find('applyConfig(-1, -1, 0);', skip_at) if skip_at >= 0 else -1
if skip_at < 0 or apply_at < 0:
    failures.append('%s: the START skip (SKIPPING OPL CONFIG LOADING ... applyConfig(-1, -1, 0);) is missing' % rel)
else:
    skip = init[skip_at:apply_at]
    if 'gVMode = defaultVMode;' not in skip or 'gWideScreen = defaultWideScreen;' not in skip:
        failures.append('%s: the START skip must put the default video mode and widescreen back' % rel)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('boot video mode: ok')
