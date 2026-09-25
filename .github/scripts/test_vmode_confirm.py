"""A video mode the TV cannot show must not be kept by a blind button press (zackcage6, 09-25).

guiConfirmVideoMode (src/gui.c) is the only thing between a user and a menu they cannot see: after a
mode change it asks to keep the new mode and reverts on Back or on a 10 s timeout. It used to keep the
mode on one TAP of Accept, and a user looking at a black screen taps buttons -- the dead mode was kept,
saved with the next Save, and every boot came up black until the .cfg was deleted.

This compiles guiConfirmVideoMode on the host with the pads, clock() and drawing replaced by a
scripted frame loop (60 fps), and checks:

- a tap, or a burst of taps, of Accept does NOT keep the mode (it reverts at the timeout);
- holding Accept for the full hold time keeps it, and a shorter hold does not;
- an Accept still held from the Settings dialog (no key-on edge here) never counts;
- Back reverts at once; no input reverts at the timeout;
- a hold started just before the timeout is allowed to finish.

It also pins the boot recovery combos in src/opl.c: Triangle + Cross forces 480p and Triangle +
Circle forces Auto (the region's interlaced mode) for interlaced-only TVs.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
gui = (root / 'src/gui.c').read_text(encoding='utf-8').replace('\r\n', '\n')
opl = (root / 'src/opl.c').read_text(encoding='utf-8').replace('\r\n', '\n')
opl_h = (root / 'include/opl.h').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature, where):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def define(source, name, where):
    match = re.search(r'^#define ' + name + r'\s+(\d+)', source, re.M)
    if match is None:
        failures.append('%s: #define %s not found' % (where, name))
        return '0'
    return match.group(1)


confirm = function_text(gui, 'int guiConfirmVideoMode(', 'src/gui.c')

HARNESS = r'''
#include <stdio.h>

typedef long clock_t;
typedef unsigned long long u64;
#define CLOCKS_PER_SEC 1000
#define OPL_VMODE_CHANGE_CONFIRMATION_TIMEOUT_MS @TIMEOUT@
#define VMODE_KEEP_HOLD_MS @HOLD@
#define VMODE_KEEP_BAR_WIDTH 200
#define ALIGN_CENTER 0
enum { KEY_CROSS = 1, KEY_CIRCLE = 2 };
enum { CROSS_ICON, CIRCLE_ICON };
enum { SFX_MESSAGE, SFX_CANCEL, SFX_CONFIRM };
enum { _STR_CFM_VMODE_CHG, _STR_BACK, _STR_CFM_VMODE_HOLD_KEEP };

struct theme { void *fonts[1]; int usedHeight; u64 textColor, selTextColor; };
static struct theme themeData;
static struct theme *gTheme = &themeData;
static int screenWidth = 640, screenHeight = 480, gSelectButton = KEY_CROSS;
static const u64 gColBlack = 0, gColWhite = 1;

/* Scripted input: frame f has the Accept/Back buttons down per the script. 60 fps clock. */
static int frame, acceptFrom[32], acceptTo[32], nAccept, backAt, acceptHeldAtEntry;
static int curAccept, prevAccept, curBack, prevBack;

static clock_t clock(void) { return (clock_t)(frame * 1000 / 60); }
static int acceptDown(int f)
{
    int i;
    if (acceptHeldAtEntry && f < acceptHeldAtEntry)
        return 1;
    for (i = 0; i < nAccept; i++)
        if (f >= acceptFrom[i] && f < acceptTo[i])
            return 1;
    return 0;
}
static void readPads(void)
{
    prevAccept = curAccept;
    prevBack = curBack;
    curAccept = acceptDown(frame);
    curBack = (backAt >= 0 && frame == backAt);
}
static int getKeyOn(int id) { return id == KEY_CROSS ? (curAccept && !prevAccept) : (curBack && !prevBack); }
static int getKeyPressed(int id) { return id == KEY_CROSS ? curAccept : curBack; }
static void guiStartFrame(void) {}
static void guiEndFrame(void) { frame++; }
static void guiShow(void) {}
static void sfxPlay(int s) { (void)s; }
static const char *_l(int id) { (void)id; return ""; }
static void rmDrawRect(int x, int y, int w, int h, u64 c) { (void)x; (void)y; (void)w; (void)h; (void)c; }
static void rmDrawLine(int a, int b, int c, int d, u64 e) { (void)a; (void)b; (void)c; (void)d; (void)e; }
static void fntRenderString(void *f, int x, int y, int a, int w, int h, const char *s, u64 c)
{ (void)f; (void)x; (void)y; (void)a; (void)w; (void)h; (void)s; (void)c; }
static void guiDrawIconAndText(int i, int s, void *f, int x, int y, u64 c)
{ (void)i; (void)s; (void)f; (void)x; (void)y; (void)c; }

@CONFIRM@

static int fails;
static void reset(void)
{
    frame = 0;
    nAccept = 0;
    backAt = -1;
    acceptHeldAtEntry = 0;
    curAccept = prevAccept = curBack = prevBack = 0;
}
/* Accept already down when the prompt opens: the Settings dialog's last poll saw it too, so the
   prompt's first readPads finds it in the OLD pad data and there is no key-on edge. */
static void carryIn(int frames)
{
    acceptHeldAtEntry = frames;
    curAccept = 1;
}
static void hold(int fromFrame, int frames)
{
    acceptFrom[nAccept] = fromFrame;
    acceptTo[nAccept] = fromFrame + frames;
    nAccept++;
}
static void expect(const char *name, int wantKeep, int wantMaxFrame)
{
    int got = guiConfirmVideoMode();
    if (got != wantKeep || (wantMaxFrame >= 0 && frame > wantMaxFrame)) {
        printf("FAIL %s: returned %d after %d frames (want %d within %d)\n", name, got, frame, wantKeep, wantMaxFrame);
        fails++;
    }
}

int main(void)
{
    const int hold60 = VMODE_KEEP_HOLD_MS * 60 / 1000, timeout60 = OPL_VMODE_CHANGE_CONFIRMATION_TIMEOUT_MS * 60 / 1000;
    int i;

    reset(); expect("no input -> revert at timeout", 0, timeout60 + 2);
    reset(); hold(30, 3); expect("one tap of Accept -> revert", 0, timeout60 + 2);
    reset(); for (i = 0; i < 20; i++) hold(20 + i * 20, 5); expect("20 blind taps -> revert", 0, timeout60 + 2);
    reset(); hold(30, hold60 + 3); expect("full hold -> keep", 1, 30 + hold60 + 3);
    reset(); hold(30, hold60 / 2); expect("half hold -> revert", 0, timeout60 + 2);
    reset(); carryIn(hold60 * 3); expect("Accept held from Settings -> never keeps", 0, -1);
    reset(); backAt = 45; expect("Back -> revert at once", 0, 47);
    reset(); hold(timeout60 - 20, hold60 + 3); expect("hold started near timeout finishes", 1, timeout60 + hold60);

    return fails ? 1 : 0;
}
'''


def run_harness():
    program = (HARNESS.replace('@TIMEOUT@', define(opl_h, 'OPL_VMODE_CHANGE_CONFIRMATION_TIMEOUT_MS', 'include/opl.h'))
               .replace('@HOLD@', define(gui, 'VMODE_KEEP_HOLD_MS', 'src/gui.c'))
               .replace('@CONFIRM@', confirm))
    if failures:
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'confirm.c'
        exe = Path(tmp) / 'confirm'
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.extend(line for line in result.stdout.splitlines() if line)


def check_boot_combos():
    load = function_text(opl, 'static void _loadConfig(', 'src/opl.c')
    cross = re.search(r'if \(getKeyPressed\(KEY_TRIANGLE\) && getKeyPressed\(KEY_CROSS\)\) \{[^}]*gVMode = 3;', load)
    circle = re.search(r'else if \(getKeyPressed\(KEY_TRIANGLE\) && getKeyPressed\(KEY_CIRCLE\)\) \{[^}]*gVMode = 0;', load)
    saved = re.search(r'\} else \{\s*configGetInt\(configOPL, CONFIG_OPL_VMODE, &gVMode\);', load)
    if not (cross and circle and saved and cross.start() < circle.start() < saved.start()):
        failures.append('_loadConfig: Triangle+Cross -> 480p (3), Triangle+Circle -> Auto (0), else the saved mode')


run_harness()
check_boot_combos()

if failures:
    print('Video mode confirm checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('video mode confirm: 8 input scripts and both boot recovery combos OK')
