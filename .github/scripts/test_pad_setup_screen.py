"""Settings > Controllers > My Pads and Set Up A USB Pad (RIPPS2 builds 126 and 129, akilluminati47), on the host.

1. Source: both rows, their IDs, their handlers and the code behind them are built with PADEMU only; the setup screen's
   frame takes the GUI lock just before rmStartFrame and lets it go just after rmEndFrame, and reads no input, calls no
   driver and opens no file in between; it keeps no translated string from one frame to the next; a failed learn-on
   returns before the loop; an old profile is put aside with fmRename, never rename(); the new file is opened with a
   mode. include/padprofiles.h holds the contract's declarations and libds34usb.h the driver's two new calls. Every new
   string is appended after the last one, so no string ID moves.
2. The setup screen's finder, cut out of src/gui.c by RIPPS2's own markers, on RIPPS2's made-up pad (its checks 1-14 in
   test_ripps2_pad129.py): a button, an active-low button, a hat, an analog trigger, a stick (inverted too), a counter
   left alone, and the text the screen writes read back and decoded.
3. guiSetUpUsbPad run whole on the PC: a fake menu driver and USB pad, a scripted PS2 pad and a temporary PADS folder.
   Every button and stick is found and the file written is exactly what is expected; one already there is put aside
   as .bak, then .b01; a write that fails removes the new file and keeps the old one aside; a profile that cannot be put
   aside is left as it was; a close that fails removes the new file too; cancelling, skipping everything, a failed
   learn-on, no usable settings folder and no pad that works the menu without a profile each end as they should; a
   button brushed for less than a hold is not what is taken, and another pad's reports in the same port are never taken
   for this one's; a pad in a port as the screen opens is taken only after it has been out, a new pad in the other
   port is read there and only there, even with the same ID; a profile saved past the block's four says it is not used.
   Throughout: input, the driver, sounds, message boxes and files are only touched outside the GUI lock, the driver is
   polled only while learning, and every message box comes after the driver is let go.
4. guiShowMyPads run whole on the PC against temporary PADS folders: each profile's name and OK, or why a game does not
   get it, in the order the launcher's packer meets them (the fifth good profile is past the block); game maps counted;
   a long list stops with "and N more" inside 480 bytes and 10 lines, at the first row that does not fit, whether bytes
   or lines run out first; no PADS folder says "None yet" and makes nothing.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

root = Path(__file__).resolve().parents[2]
fail = []


def text(rel):
    p = root / rel
    if not p.exists():
        fail.append(rel + ' missing')
        return ''
    return p.read_text(encoding='utf-8', errors='replace')


gui = text('src/gui.c')
dialogs_c = text('src/dialogs.c')
dialogs_h = text('include/dialogs.h')
header = text('include/padprofiles.h')
libds34usb = text('modules/ds34usb/ee/libds34usb.h')
base_text = text('lng_tmpl/_base.yml')


def check(ok, what):
    if not ok:
        fail.append(what)


def code(src):
    """src without its comments, so a check reads only what runs."""
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', src, flags=re.S)


def body(src, start):
    """The function that starts with start, to its closing brace at column 0."""
    i = src.find(start)
    if i < 0:
        fail.append('gui.c: ' + start + ' not found')
        return ''
    return src[i:src.index('\n}\n', i) + 3]


def pademu_only(src, needle, what):
    """Each line holding needle sits between an #ifdef PADEMU and its #else/#endif."""
    depth = []
    lines = src.split('\n')
    found = False
    for line in lines:
        s = line.strip()
        conditional = s.startswith(('#if', '#else', '#elif', '#endif'))
        if s.startswith('#if'):
            depth.append(s == '#ifdef PADEMU')
        elif s.startswith(('#else', '#elif')):
            if depth:
                depth[-1] = False
        elif s.startswith('#endif'):
            if depth:
                depth.pop()
        if needle in line and not conditional:
            found = True
            if True not in depth:
                fail.append('%s: %s outside #ifdef PADEMU' % (what, needle))
                return
    if not found:
        fail.append('%s: %s not found' % (what, needle))


# 1: the source
for needle in ('MY_PADS_BUTTON,', 'PAD_SETUP_BUTTON,'):
    pademu_only(dialogs_h, needle, 'include/dialogs.h')
for needle in ('MY_PADS_BUTTON', 'PAD_SETUP_BUTTON'):
    pademu_only(dialogs_c, needle, 'src/dialogs.c')
for needle in ('guiShowMyPads', 'guiSetUpUsbPad', 'padSetupDraw', 'padSetupFind', 'MY_PADS_BUTTON', 'PAD_SETUP_BUTTON',
               'ds34usb_get_raw', 'padProfilesMenuLearn', 'fmRename', '<libds34usb.h>', '"include/padprofiles.h"'):
    pademu_only(gui, needle, 'src/gui.c')
check(re.search(r'result == MY_PADS_BUTTON\) \{\s*guiShowMyPads\(\);\s*goto reshow_controller;', gui),
      'gui.c: My Pads opens from Controllers and comes back to it')
check(re.search(r'result == PAD_SETUP_BUTTON\) \{\s*guiSetUpUsbPad\(\);\s*goto reshow_controller;', gui),
      'gui.c: Set Up A USB Pad opens from Controllers and comes back to it')
check(re.search(r'\{UI_BUTTON, MY_PADS_BUTTON, 1, 1, _STR_HINT_MY_PADS, 0, 0, \{\.label = \{NULL, _STR_MY_PADS\}\}\}', dialogs_c),
      'dialogs.c: the My Pads row')
check(re.search(r'\{UI_BUTTON, PAD_SETUP_BUTTON, 1, 1, _STR_HINT_PAD_SETUP, 0, 0, \{\.label = \{NULL, _STR_PAD_SETUP\}\}\}',
                dialogs_c), 'dialogs.c: the Set Up A USB Pad row')

draw = code(body(gui, 'static void padSetupDraw('))
setup = code(body(gui, 'static void guiSetUpUsbPad(void)\n{'))
mypads = code(body(gui, 'static void guiShowMyPads(void)\n{'))
check('    guiLock();\n    rmStartFrame();\n' in draw, 'padSetupDraw: guiLock() right before rmStartFrame()')
check('    rmEndFrame();\n    guiUnlock();\n' in draw, 'padSetupDraw: guiUnlock() right after rmEndFrame()')
if 'rmStartFrame();' in draw and 'rmEndFrame();' in draw:
    inside = draw[draw.index('rmStartFrame();'):draw.index('rmEndFrame();')]
    for bad in ('readPads', 'getKey', 'ds34usb_', 'padSetupPoll', 'sfxPlay', 'guiMsgBox', 'open(', 'read(', 'write(',
                'mkdir(', 'fmRename', 'fmExists', 'padProfiles'):
        check(bad not in inside, 'padSetupDraw: %s inside the frame' % bad)
    outside = draw[:draw.index('rmStartFrame();')] + draw[draw.index('rmEndFrame();'):]
    check('_l(' not in outside, 'padSetupDraw: a string looked up outside the frame')
for name, fn in (('guiSetUpUsbPad', setup), ('guiShowMyPads', mypads)):
    for bad in ('guiLock', 'guiUnlock', 'guiStartFrame', 'guiEndFrame', 'rmStartFrame'):
        check(bad not in fn, '%s: takes the GUI lock or a frame itself (%s)' % (name, bad))
    for line in fn.split('\n'):
        if '_l(' in line and not re.search(r'snprintf\(|guiMsgBox\(|guiMyPadsAdd\(', line):
            fail.append('%s: a translated string kept past its call: %s' % (name, line.strip()))
check(re.search(r'if \(padProfilesMenuLearn\(1\) < 0\) \{[^}]*guiMsgBox\(_l\(_STR_PAD_SETUP_NO_DRIVER\), 0, NULL\);\s*return;\s*\}',
                setup), 'guiSetUpUsbPad: a failed learn-on says so and returns before the loop')
if 'out:' in setup:
    before, after = setup.split('out:', 1)
    learn = before[before.find('padProfilesMenuLearn(1)'):]
    check('return;' not in learn[learn.find('sfxPlay'):], 'guiSetUpUsbPad: every way out after learn-on goes through out:')
    check('guiMsgBox' not in learn[learn.find('sfxPlay'):], 'guiSetUpUsbPad: no message box while the driver is learning')
    check(re.search(r'padProfilesMenuLoad\(\);\s*padProfilesMenuLearn\(0\);\s*(?:if \(saved && !padProfilesMenuHas\(vid, pid\)\)\s*'
                    r'snprintf\(msg, sizeof\(msg\), _l\(_STR_PAD_SETUP_SAVED_UNUSED\), path, PAD_DEFS_MAX\);\s*)?'
                    r'if \(msg\[0\] != .\\0.\)\s*guiMsgBox\(msg, 0, NULL\);', after),
          'guiSetUpUsbPad: out: reads PADS again, lets the driver go, then shows the message')
    check(re.search(r'if \(!padReadyWithoutProfile\(\)\) \{[^}]*guiMsgBox\(_l\(_STR_PAD_SETUP_NO_PAD\), 0, NULL\);\s*return;\s*\}'
                    r'\s*if \(padProfilesMenuLearn\(1\) < 0\)', setup),
          'guiSetUpUsbPad: with no pad that works the menu without a profile, it says so and returns before learn-on')
else:
    fail.append('guiSetUpUsbPad: no out: label')
check(not re.search(r'(?<![A-Za-z])rename\(', setup), 'guiSetUpUsbPad: an old profile is put aside with fmRename, not rename()')
for m in re.finditer(r'open\(([^;]*O_CREAT[^;]*)\);', setup):
    check(m.group(1).count(',') == 2, 'guiSetUpUsbPad: open with O_CREAT and no mode: ' + m.group(0))
check('unlink(path);' in setup, 'guiSetUpUsbPad: a failed write removes the new file')

for decl in ('int padProfilesPrepare(const char *gameId);', 'const unsigned char *padProfilesBlock(void);',
             'void padProfilesMenuLoad(void);', 'void padProfilesMenuTick(void);', 'int padProfilesMenuLearn(int on);',
             'int padProfilesDir(char *out, int size);', 'int padProfilesRead(const char *path, char *buf, int size);',
             'int padProfilesLeftOut(const pad_def_t *def);'):
    check(decl in header, 'include/padprofiles.h: ' + decl)
for decl in ('int ds34usb_set_profiles(const u8 *block, int size, int learn);', 'int ds34usb_get_raw(int port, u8 *out);'):
    check(decl in libds34usb, 'libds34usb.h: ' + decl)

base = yaml.safe_load(base_text) if base_text else {'gui_strings': []}
entries = [e for e in base['gui_strings'] if isinstance(e, dict) and 'label' in e]
labels = [e['label'] for e in entries]
english = {e['label']: str(e['string']) for e in entries}
used = set(re.findall(r'_STR_([A-Z0-9_]+)', mypads + body(gui, 'static void padSetupDraw(') + setup +
                       gui[gui.find('padSetupSteps[] = {'):gui.find('#define PAD_SETUP_STEPS')] +
                       dialogs_c[dialogs_c.find('MY_PADS_BUTTON') - 200:dialogs_c.find('PAD_SETUP_BUTTON') + 200]))
for name in sorted(used):
    check(name in english, '_base.yml: %s is used but missing' % name)
new = [l for l in labels if l in ('MY_PADS', 'HINT_MY_PADS', 'PAD_SETUP', 'HINT_PAD_SETUP') or l.startswith(('MY_PADS_', 'PAD_SETUP_'))]
check(len(new) == 48, '_base.yml: %d My Pads and Set Up A USB Pad strings, want 48' % len(new))
if 'PS1_DUPLICATES_BOTH' in labels and new:
    check(min(labels.index(l) for l in new) > labels.index('PS1_DUPLICATES_BOTH'),
          '_base.yml: the new strings come after the last one before them, so no string ID moves')
for l in ('HINT_MY_PADS', 'HINT_PAD_SETUP'):
    check(len(english.get(l, '').encode()) <= 172, '_base.yml: %s is short (at most the 90th percentile of hints)' % l)

cc = shutil.which('gcc') or shutil.which('cc')
if cc is None:
    print('\n'.join(fail) or 'pad setup screen: no host C compiler, programs skipped')
    sys.exit(1 if fail else 0)


def grab(src, start, end_marker='\n}\n'):
    i = src.find(start)
    if i < 0:
        fail.append('gui.c: ' + start + ' not found')
        return ''
    return src[i:src.index(end_marker, i) + len(end_marker)]


# 2: RIPPS2's finder checks, on the code cut out by RIPPS2's markers
finder = '\n'.join([
    grab(gui, 'typedef struct\n{\n    int port, len, seq;', '} pad_setup_raw_t;\n'),
    grab(gui, 'static int padSetupBits('),
    grab(gui, 'static int padSetupFind('),
    grab(gui, 'static int padSetupAtRest('),
])

FINDER = r'''
#include <stdio.h>
#include <string.h>
#include "include/padfile.h"
#define PAD_SETUP_SWING 0x50
''' + finder + r'''
int main(void)
{
    /* a made-up pad: byte 0 face buttons, byte 1 the rest (bit 3 set at rest: pressed is 0), byte 2 a hat (8 = centre),
       bytes 3-6 sticks round 0x80, byte 7 an analog L2, byte 8 a counter */
    unsigned char rest[16] = {0x00, 0x08, 0x08, 0x80, 0x7F, 0x80, 0x81, 0x00, 0x00};
    unsigned char noise[16] = {0, 0, 0, 3, 2, 3, 2, 0, 0xFF};
    unsigned char usedBits[16] = {0}, usedAxis[16] = {0};
    pad_setup_raw_t p;
    unsigned short buttons;
    unsigned char axes[4];
    int at = -1, bit = -1, low = -1;
    pad_def_t d;
    char err[96];
    const char *made = "[Device]\nformat=1\ndecoder=generic\n[Buttons]\ncross=b0.1\nselect=!b1.3\nl2=a7\nup=none\n[Axes]\n"
                       "dpad=hat2\nlx=a3\nly=a4-\ndeadzone=12\n";

    memset(&p, 0, sizeof(p));
    p.len = 9;
    memcpy(p.r, rest, 16);
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0) return 1; /* nothing moved */
    p.r[0] = 0x02;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 1 || at != 0 || bit != 1 || low) return 2;
    if (padSetupAtRest(rest, noise, usedAxis, &p)) return 3;
    usedBits[0] |= 2;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0) return 4; /* a used bit is not found again */
    memcpy(p.r, rest, 16);
    p.r[1] = 0x00;
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 1 || at != 1 || bit != 3 || !low) return 5;
    memcpy(p.r, rest, 16);
    p.r[2] = 0x00; /* Up on the hat: one bit drops, but on a d-pad step it is the hat */
    if (padSetupFind(rest, noise, &p, 0, 1, 0, usedBits, usedAxis, &at, &bit, &low) != 2 || at != 2) return 6;
    memcpy(p.r, rest, 16);
    p.r[7] = 0xFF; /* L2, an analog trigger */
    if (padSetupFind(rest, noise, &p, 0, 0, 1, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 7) return 7;
    p.r[7] = 0x01; /* its first step down is one bit: not yet anything on a trigger step */
    if (padSetupFind(rest, noise, &p, 0, 0, 1, usedBits, usedAxis, &at, &bit, &low) == 3) return 8;
    memcpy(p.r, rest, 16);
    p.r[3] = 0xFF; /* the left stick to the right */
    if (padSetupFind(rest, noise, &p, 1, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 3 || low) return 9;
    p.r[3] = 0x80;
    p.r[4] = 0x00; /* "down" ran the other way: inverted */
    if (padSetupFind(rest, noise, &p, 1, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 3 || at != 4 || !low) return 10;
    memcpy(p.r, rest, 16);
    p.r[8] = 0x55; /* the counter moved: not a press, and still at rest */
    if (padSetupFind(rest, noise, &p, 0, 0, 0, usedBits, usedAxis, &at, &bit, &low) != 0 || !padSetupAtRest(rest, noise, usedAxis, &p)) return 11;
    usedAxis[3] = 1;
    p.r[3] = 0x90; /* an axis a little off rest is at rest */
    if (!padSetupAtRest(rest, noise, usedAxis, &p)) return 12;
    /* what the screen writes, read back and run */
    if (padDefParse(made, strlen(made), 0x1234, 0x5678, &d, err, sizeof(err))) { printf("%s\n", err); return 13; }
    memcpy(p.r, rest, 16);
    p.r[0] = 0x02; p.r[1] = 0x00; p.r[2] = 0x06; p.r[7] = 0xC0; p.r[4] = 0x00;
    padTranslate(&d, p.r, p.len, &buttons, axes);
    if (buttons != (unsigned short)~(1u << PAD_B_CROSS | 1u << PAD_B_SELECT | 1u << PAD_B_L2 | 1u << PAD_B_LEFT) || axes[PAD_AX_LY] != 255)
        { printf("buttons %04x ly %d\n", buttons, axes[PAD_AX_LY]); return 14; }
    printf("finder ok\n");
    return 0;
}
'''

# 3 and 4: the two screens run whole. The PADEMU block of gui.c, cut in three: My Pads, the setup screen up to its frame
# (renamed, so a wrapper can play the user each frame), and the rest of the setup screen
block_start = gui.find('#define MY_PADS_MSG')
setup_start = gui.find('#define PAD_SETUP_SWING')
draw_start = gui.find('// One frame. Only drawing happens inside the lock')
draw_end = gui.find('\n}\n', gui.find('static void padSetupDraw(')) + 3
setup_end = gui.find('\n}\n', gui.find('static void guiSetUpUsbPad(void)\n{')) + 3
pieces_ok = min(block_start, setup_start, draw_start) >= 0 and block_start < setup_start < draw_start < draw_end < setup_end
check(pieces_ok, 'gui.c: My Pads and the setup screen not found in the order the host harness cuts them')
MYPADS_SRC = gui[block_start:gui.rfind('/*', block_start, setup_start)] if pieces_ok else ''
PIECE1 = gui[setup_start:draw_start] if pieces_ok else ''
RAW_SIZE = re.search(r'^#define\s+DS34USB_RAW_SIZE\s+(\d+)\b', libds34usb, re.M)
TYPE_GENERIC = re.search(r'^#define\s+DS34USB_TYPE_GENERIC\s+(\d+)\b', libds34usb, re.M)
check(RAW_SIZE and TYPE_GENERIC, 'libds34usb.h: DS34USB_RAW_SIZE or DS34USB_TYPE_GENERIC not defined')
check('PAD_SETUP_GENERIC' not in gui, 'gui.c: PAD_SETUP_GENERIC is back; the screen reads DS34USB_TYPE_GENERIC')
DRAW = gui[draw_start:draw_end].replace('static void padSetupDraw(', 'static void padSetupDrawReal(') if pieces_ok else ''
PIECE2 = gui[draw_end:setup_end] if pieces_ok else ''
STRINGS = 'enum {\n' + ''.join('    _STR_%s = %d,\n' % (l, i) for i, l in enumerate(labels)) + '};\n' + \
          'static const char *const lngEnglish[] = {\n' + \
          ''.join('    %s,\n' % json.dumps(english[l], ensure_ascii=False) for l in labels) + '};\n'

HARNESS = r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdarg.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "include/padfile.h"
#include "include/padprofiles.h"

typedef unsigned long long u64;
''' + STRINGS + r'''
static char *_l(int id) { return (char *)lngEnglish[id]; }

static int hFailed = 0;
#define H_FAIL(...) do { printf(__VA_ARGS__); printf("\n"); hFailed = 1; } while (0)

/* the GUI lock and the frame */
static int hLocked = 0, hInFrame = 0, hFrames = 0;
static void guiLock(void) { if (hLocked) H_FAIL("guiLock taken twice (it does not nest)"); hLocked = 1; }
static void guiUnlock(void) { if (!hLocked) H_FAIL("guiUnlock without guiLock"); hLocked = 0; }
static void rmStartFrame(void) { if (!hLocked) H_FAIL("rmStartFrame without the GUI lock"); hInFrame = 1; }
static void rmEndFrame(void) { if (!hInFrame) H_FAIL("rmEndFrame outside a frame"); hInFrame = 0; hFrames++; }
#define H_DRAWING(what) do { if (!hInFrame) H_FAIL("%s drawn outside a frame", what); } while (0)
#define H_OUTSIDE(what) do { if (hLocked) H_FAIL("%s inside the GUI lock", what); } while (0)

static int screenWidth = 640, screenHeight = 448;
static struct { int fonts[1]; u64 textColor, selTextColor; } hTheme, *gTheme = &hTheme;
static const u64 gColDarker = 1, gColWhite = 2;
#define ALIGN_CENTER 0
#define SELECT_ICON 1
#define KEY_SELECT 8
#define H_KEY_CANCEL 1
#define H_KEY_CONFIRM 2
enum { SFX_CANCEL, SFX_CONFIRM, SFX_CURSOR, SFX_MESSAGE };
#define DS34USB_STATE_RUNNING 0x08
#define DS34USB_RAW_SIZE ''' + (RAW_SIZE.group(1) if RAW_SIZE else '72') + r'''
#define DS34USB_TYPE_GENERIC ''' + (TYPE_GENERIC.group(1) if TYPE_GENERIC else '4') + r'''

static char hShown[1024]; /* the text the last frame drew */
static int guiDrawBGSettings(void) { H_DRAWING("the background"); return 0; }
static void guiDrawBGPlasma(void) { H_DRAWING("the plasma"); }
static void rmDrawRect(int x, int y, int w, int h, u64 c) { (void)x; (void)y; (void)w; (void)h; (void)c; H_DRAWING("a rectangle"); }
static void rmDrawLine(int x, int y, int x1, int y1, u64 c) { (void)x; (void)y; (void)x1; (void)y1; (void)c; H_DRAWING("a line"); }
static int fntRenderString(int f, int x, int y, short a, size_t w, size_t h, const char *s, u64 c)
{
    (void)f; (void)y; (void)a; (void)w; (void)h; (void)s; (void)c;
    H_DRAWING("text");
    return x;
}
static int guiDrawIconAndText(int icon, int textId, int font, int x, int y, u64 color)
{
    (void)icon; (void)textId; (void)font; (void)y; (void)color;
    H_DRAWING("a hint");
    return x;
}
static int guiConfirmIcon(void) { return 2; }
static int guiCancelIcon(void) { return 3; }
static int guiConfirmKey(void) { return H_KEY_CONFIRM; }
static int guiCancelKey(void) { return H_KEY_CANCEL; }

/* fntWrapText at 60 characters a line: enough to count lines */
static int guiWrapText(const char *text, int innerW, char *out, int outSize)
{
    int lines = 0, col = 0;
    const char *p;
    (void)innerW;
    snprintf(out, outSize, "%s", text);
    for (p = text;; p++) {
        if (*p == '\n' || *p == '\0') {
            lines += col == 0 ? 1 : (col + 59) / 60;
            col = 0;
            if (*p == '\0')
                break;
        } else
            col++;
    }
    return lines;
}
static int guiDrawWrappedLines(const char *wrapped, int lines)
{
    (void)lines;
    H_DRAWING("the message");
    snprintf(hShown, sizeof(hShown), "%s", wrapped);
    return 0;
}

/* the PS2 pad: the keys the scripted user holds this frame */
static int hKeys = 0;
static int readPads(void) { H_OUTSIDE("readPads"); return 1; }
static int getKeyOn(int key) { H_OUTSIDE("getKeyOn"); return (hKeys & (1 << key)) != 0; }
static int hSounds = 0;
static void sfxPlay(int id) { (void)id; H_OUTSIDE("sfxPlay"); hSounds++; }

/* the menu's USB pad driver and the profiles module */
static int hLearn = 0, hLearnCalls[8], hLearnCount = 0, hLearnFails = 0, hLoads = 0, hLoadsBeforeOff = 0, hPolls = 0;
static int hPresent = 0, hStranger = 0, hPort = 0, hOld = 0, hOldSameId = 0, hNoPlainPad = 0, hUnused = 0, hHasCalls = 0;
static unsigned char hRep[64], hSeq = 0;
static void hRest(unsigned char *r);
int padProfilesMenuLearn(int on)
{
    H_OUTSIDE("padProfilesMenuLearn");
    if (hLearnCount < 8)
        hLearnCalls[hLearnCount++] = on;
    if (on && hLearnFails)
        return -1; /* and undone, as the module does */
    if (!on)
        hLoadsBeforeOff = hLoads;
    hLearn = on;
    return 0;
}
void padProfilesMenuLoad(void) { H_OUTSIDE("padProfilesMenuLoad"); hLoads++; }
int padProfilesMenuHas(unsigned vid, unsigned pid)
{
    H_OUTSIDE("padProfilesMenuHas");
    hHasCalls++;
    if (hLearn || hLoadsBeforeOff == 0)
        H_FAIL("padProfilesMenuHas asked before PADS was read again and the driver let go");
    if (vid != 0x1234 || pid != 0x5678)
        H_FAIL("padProfilesMenuHas asked about %04X:%04X", vid, pid);
    return !hUnused;
}
static int padReadyWithoutProfile(void) { H_OUTSIDE("padReadyWithoutProfile"); return !hNoPlainPad; }
static int ds34usb_get_raw(int port, unsigned char *out)
{
    H_OUTSIDE("ds34usb_get_raw");
    if (!hLearn)
        H_FAIL("the driver polled while it is not learning");
    if (port < 0 || port > 1)
        H_FAIL("port %d polled", port);
    hPolls++;
    memset(out, 0, DS34USB_RAW_SIZE);
    if (hOld && port == 0) { /* a HID pad there as the screen opened (its profile off), 0E6F:0213: Cross held throughout */
        out[0] = 0x01 | 0x02 | 0x04 | DS34USB_STATE_RUNNING;
        out[1] = DS34USB_TYPE_GENERIC;
        out[2] = hOldSameId ? 0x34 : 0x6F; out[3] = hOldSameId ? 0x12 : 0x0E;
        out[4] = hOldSameId ? 0x78 : 0x13; out[5] = hOldSameId ? 0x56 : 0x02;
        out[6] = 9;
        out[7] = hSeq++;
        hRest(out + 8);
        out[8] |= 0x02;
        return 1;
    }
    if (port != hPort || !hPresent)
        return 1;
    out[0] = 0x01 | 0x02 | 0x04 | DS34USB_STATE_RUNNING;
    out[1] = DS34USB_TYPE_GENERIC;
    out[2] = 0x34; out[3] = 0x12; out[4] = 0x78; out[5] = 0x56;
    out[6] = 9;
    out[7] = hSeq++;
    memcpy(out + 8, hRep, 64);
    if (hStranger) { /* another HID pad in that port now, ABCD:EF01: its own report, at rest but for Circle's bit */
        out[2] = 0xCD; out[3] = 0xAB; out[4] = 0x01; out[5] = 0xEF;
        hRest(out + 8);
        out[8] |= 0x04;
    }
    return 1;
}

/* the settings folder */
static char hHome[300];
static int hNoHome = 0;
int padProfilesDir(char *out, int size)
{
    if (hNoHome)
        return -1;
    snprintf(out, size, "%s/PADS", hHome);
    return 0;
}

/* files: the host's, only outside the lock; a write can be made to fail */
static int hWriteFails = 0, hWriteLies = 0, hCloseFails = 0, hRenameFails = 0, hUnlinks = 0, hMsgBoxes = 0;
static int h_open(const char *path, int flags, ...)
{
    int mode = 0;
    H_OUTSIDE("open");
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
        if (mode != 0666)
            H_FAIL("a file made with mode %o", mode);
    }
    return open(path, flags, mode);
}
static ssize_t h_read(int fd, void *buf, size_t n) { H_OUTSIDE("read"); return read(fd, buf, n); }
static ssize_t h_write(int fd, const void *buf, size_t n)
{
    H_OUTSIDE("write");
    if (hWriteFails) { /* a card or stick that takes part of it, then fails */
        if (write(fd, buf, n / 2) < 0)
            return -1;
        return -1;
    }
    if (hWriteLies) { /* one that answers all of it and keeps half */
        if (write(fd, buf, n / 2) < 0)
            return -1;
        return n;
    }
    return write(fd, buf, n);
}
static int h_close(int fd)
{
    H_OUTSIDE("close");
    if (hCloseFails) { /* one that takes all of it and reports the error only at close: the next close fails, once */
        hCloseFails = 0;
        close(fd);
        return -1;
    }
    return close(fd);
}
static int h_unlink(const char *p) { H_OUTSIDE("unlink"); hUnlinks++; return unlink(p); }
static int h_mkdir(const char *p, mode_t m) { H_OUTSIDE("mkdir"); return mkdir(p, m); }
typedef struct
{
    struct dirent **list;
    int n, i;
} H_DIR;
static H_DIR *h_opendir(const char *p) /* sorted, so the packer's order is the same on every host */
{
    H_DIR *d = calloc(1, sizeof(*d));
    H_OUTSIDE("opendir");
    d->n = scandir(p, &d->list, NULL, alphasort);
    if (d->n < 0) {
        free(d);
        return NULL;
    }
    return d;
}
static struct dirent *h_readdir(H_DIR *d) { return d->i < d->n ? d->list[d->i++] : NULL; }
static int h_closedir(H_DIR *d)
{
    int i;
    for (i = 0; i < d->n; i++)
        free(d->list[i]);
    free(d->list);
    free(d);
    return 0;
}
static int fmExists(const char *path) { H_OUTSIDE("fmExists"); return access(path, F_OK) == 0; }
static int fmRename(const char *path, const char *newName) /* filemgr.c's: the same folder, never onto a name there */
{
    char dst[400];
    const char *slash = strrchr(path, '/');
    H_OUTSIDE("fmRename");
    if (hRenameFails || slash == NULL)
        return 0;
    snprintf(dst, sizeof(dst), "%.*s/%s", (int)(slash - path), path, newName);
    if (access(dst, F_OK) == 0)
        return 0;
    return rename(path, dst) == 0;
}
#define open h_open
#define read h_read
#define write h_write
#define close h_close
#define unlink h_unlink
#define mkdir h_mkdir
#define DIR H_DIR
#define opendir h_opendir
#define readdir h_readdir
#define closedir h_closedir

/* what the launcher's packer reads and leaves out (the reference the launch piece implements) */
int padProfilesRead(const char *path, char *buf, int size)
{
    int fd, n = 0, r = 0, big = 0;
    char more;
    if ((fd = open(path, O_RDONLY)) < 0)
        return -1;
    while (n < size - 1 && (r = read(fd, buf + n, size - 1 - n)) > 0)
        n += r;
    if (r >= 0 && n == size - 1)
        big = read(fd, &more, 1) > 0;
    close(fd);
    if (r < 0)
        return -1;
    if (big)
        return -2;
    buf[n] = '\0';
    return n;
}
int padProfilesLeftOut(const pad_def_t *def)
{
    if (def->vid == 0x054C || def->vid == 0x12BA || (def->vid == 0x2563 && def->pid == 0x0575))
        return PAD_PROFILE_BUILT_IN;
    return def->decoder != PAD_DEC_GENERIC ? PAD_PROFILE_NOT_GENERIC : PAD_PROFILE_USED;
}

static char hMsg[1024];
static int guiMsgBox(const char *text, int addAccept, void *ui)
{
    (void)addAccept; (void)ui;
    H_OUTSIDE("guiMsgBox");
    if (hLearn)
        H_FAIL("a message box while the driver is learning: %s", text);
    hMsgBoxes++;
    snprintf(hMsg, sizeof(hMsg), "%s", text);
    return 0;
}
''' + MYPADS_SRC + PIECE1 + DRAW + r'''
/* The user: what the screen asks for each frame is what they do, on the USB pad or the PS2 pad */
static int hCancelView = -1, hCancelFrame = 3, hSkip = 0, hBrush = -1, hSlide = -1, hStrangerView = -1, hStrangerFrom = 0,
           hViewFrames = 0, hLastView = -1, hLastStep = -1, hReplug = 0;
static char hTry[1024];

static void hRest(unsigned char *r)
{
    memset(r, 0, 64);
    r[1] = 0x08;                     /* R1, active low */
    r[2] = 0x08;                     /* the hat, centred */
    r[3] = 0x80 + (hFrames & 1);     /* sticks, with a little jitter */
    r[4] = 0x80;
    r[5] = 0x80;
    r[6] = 0x81 - (hFrames & 1);
    r[8] = hFrames & 63;             /* a counter */
}

static void hPress(int axis, int id, unsigned char *r)
{
    if (axis) {
        if (id == PAD_AX_LX) r[3] = 0xFF;
        if (id == PAD_AX_LY) r[4] = 0xFF;
        if (id == PAD_AX_RX) r[5] = 0xFF;
        if (id == PAD_AX_RY) r[6] = 0x00; /* this stick's Y runs the other way */
        return;
    }
    switch (id) {
        case PAD_B_SQUARE: r[0] |= 0x01; break;
        case PAD_B_CROSS: r[0] |= 0x02; break;
        case PAD_B_CIRCLE: r[0] |= 0x04; break;
        case PAD_B_TRIANGLE: r[0] |= 0x08; break;
        case PAD_B_L1: r[0] |= 0x10; break;
        case PAD_B_SELECT: r[0] |= 0x40; break;
        case PAD_B_START: r[0] |= 0x80; break;
        case PAD_B_L3: r[1] |= 0x01; break;
        case PAD_B_R3: r[1] |= 0x02; break;
        case PAD_B_R1: r[1] &= ~0x08; break;
        case PAD_B_R2: r[1] |= 0x10; break;
        case PAD_B_L2: r[7] = 0xFF; break;
        case PAD_B_UP: r[2] = 0; break;
        case PAD_B_RIGHT: r[2] = 2; break;
        case PAD_B_DOWN: r[2] = 4; break;
        case PAD_B_LEFT: r[2] = 6; break;
    }
}

static void padSetupDraw(const pad_setup_view_t *v)
{
    H_OUTSIDE("padSetupDraw's caller holding the lock:");
    padSetupDrawReal(v);
    if (hLocked || hInFrame)
        H_FAIL("a frame left the GUI lock or the frame open");
    if (hFrames > 50000) {
        printf("the screen never finished (view %d step %d)\n", v->view, v->step);
        exit(90);
    }
    if (v->view != hLastView || v->step != hLastStep)
        hViewFrames = 0;
    hViewFrames++;
    hLastView = v->view;
    hLastStep = v->step;
    hKeys = 0;
    hRest(hRep);
    hStranger = v->view == hStrangerView && (v->view != PAD_SETUP_VIEW_STEP || v->step == 0) &&
                hViewFrames >= hStrangerFrom && hViewFrames < hStrangerFrom + 8;
    if (v->view == hCancelView && hViewFrames == hCancelFrame) {
        hKeys = 1 << H_KEY_CANCEL;
        return;
    }
    switch (v->view) {
        case PAD_SETUP_VIEW_PLUG:
            if (hReplug) /* in as the screen opened: out for three frames, then in again */
                hPresent = hViewFrames < 3 || hViewFrames >= 6;
            else if (hViewFrames >= 3)
                hPresent = 1;
            break;
        case PAD_SETUP_VIEW_STEP:
            if (hSkip & (1 << v->step)) {
                if (hViewFrames == 2)
                    hKeys = 1 << KEY_SELECT;
            } else if (v->step == hBrush && hViewFrames < PAD_SETUP_HOLD)
                hPress(0, PAD_B_CIRCLE, hRep); /* the thumb brushes Circle first, for less than a hold */
            else if (v->step == hSlide && hViewFrames > PAD_SETUP_HOLD && hViewFrames <= PAD_SETUP_HOLD + 3) {
                /* held for a hold, then the thumb slides for less than one: Circle, in Cross's byte, or the left
                   stick the other way */
                if (padSetupSteps[v->step].axis)
                    hRep[3] = 0x00;
                else
                    hPress(0, PAD_B_CIRCLE, hRep);
            }
            else
                hPress(padSetupSteps[v->step].axis, padSetupSteps[v->step].id, hRep);
            break;
        case PAD_SETUP_VIEW_TRY:
            hPress(0, PAD_B_CROSS, hRep);
            hPress(0, PAD_B_LEFT, hRep);
            hPress(0, PAD_B_L2, hRep);
            hPress(1, PAD_AX_LX, hRep);
            if (hViewFrames == 6)
                snprintf(hTry, sizeof(hTry), "%s", hShown);
            if (hViewFrames == 8)
                hKeys = 1 << H_KEY_CONFIRM;
            break;
        default:
            break;
    }
}
''' + PIECE2 + r'''
static const char *const hMade =
    "# Set up on the PS2 by RiptOPL (Controllers > Set Up A USB Pad, from RIPPS2 build 129)\n[Device]\nformat=1\n"
    "name=USB pad 1234:5678\ndecoder=generic\n[Buttons]\ncross=b0.1\ncircle=b0.2\nsquare=b0.0\ntriangle=b0.3\nl1=b0.4\n"
    "r1=!b1.3\nl2=a7\nr2=b1.4\nselect=b0.6\nstart=b0.7\nl3=b1.0\nr3=b1.1\n[Axes]\ndpad=hat2\nlx=a3\nly=a4\nrx=a5\n"
    "ry=a6-\ndeadzone=12\n[Rumble]\nrumble=off\nled=off\ninit=off\n";

static char hPads[400], hFile[420];

static void hReset(const char *tmp, const char *name)
{
    char cmd[600];
    snprintf(hHome, sizeof(hHome), "%s/%s", tmp, name);
    snprintf(cmd, sizeof(cmd), "rm -rf '%s' && mkdir -p '%s'", hHome, hHome);
    if (system(cmd) != 0)
        H_FAIL("cannot make %s", hHome);
    snprintf(hPads, sizeof(hPads), "%s/PADS", hHome);
    snprintf(hFile, sizeof(hFile), "%s/1234_5678.pad", hPads);
    hNoHome = hLearn = hLearnCount = hLearnFails = hLoads = hLoadsBeforeOff = hPolls = hPresent = 0;
    hPort = hOld = hOldSameId = hNoPlainPad = hUnused = hHasCalls = hReplug = 0;
    hWriteFails = hWriteLies = hCloseFails = hRenameFails = hUnlinks = hMsgBoxes = hKeys = hSkip = 0;
    hCancelView = hBrush = hSlide = hStrangerView = hLastView = hLastStep = -1;
    hCancelFrame = 3;
    hStranger = hStrangerFrom = 0;
    hMsg[0] = hTry[0] = '\0';
}

static int hReadFile(const char *path, char *buf, int size)
{
    int fd = open(path, O_RDONLY), n = 0, r;
    if (fd < 0)
        return -1;
    while (n < size - 1 && (r = read(fd, buf + n, size - 1 - n)) > 0)
        n += r;
    close(fd);
    buf[n] = '\0';
    return n;
}

static void hWriteFile(const char *path, const char *t)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0 || write(fd, t, strlen(t)) != (ssize_t)strlen(t))
        H_FAIL("cannot write %s", path);
    if (fd >= 0)
        close(fd);
}

static void hExpectLearn(const char *what, int calls, int first, int second)
{
    if (hLearnCount != calls || (calls > 0 && hLearnCalls[0] != first) || (calls > 1 && hLearnCalls[1] != second))
        H_FAIL("%s: learn calls %d (%d, %d)", what, hLearnCount, hLearnCount > 0 ? hLearnCalls[0] : -1,
               hLearnCount > 1 ? hLearnCalls[1] : -1);
    if (calls == 2 && hLoadsBeforeOff != 1)
        H_FAIL("%s: PADS not read again before the driver was let go", what);
}

static void hExpectMsg(const char *what, const char *want)
{
    if (strcmp(hMsg, want) != 0)
        H_FAIL("%s: message\n  '%s'\nwant\n  '%s'", what, hMsg, want);
}

static void setupChecks(const char *tmp)
{
    char want[1024], got[4096], path[500];
    pad_def_t d;
    int i;
    char err[96];

    /* the whole way through, no profile there before */
    hReset(tmp, "s1");
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("written:\n%s\nwant:\n%s", got, hMade);
    if (padDefParse(got, strlen(got), 0x1234, 0x5678, &d, err, sizeof(err)) != 0)
        H_FAIL("what was written does not read: %s", err);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_SAVED), hFile);
    hExpectMsg("saved", want);
    hExpectLearn("saved", 2, 1, 0);
    if (hMsgBoxes != 1 || hHasCalls != 1)
        H_FAIL("saved: %d message boxes, the block asked %d times", hMsgBoxes, hHasCalls);
    if (!strstr(hTry, "Cross") || !strstr(hTry, "Left") || !strstr(hTry, "L2") || !strstr(hTry, "L 255 128"))
        H_FAIL("tried live: the screen showed '%s'", hTry);
    snprintf(path, sizeof(path), "%s/1234_5678.bak", hPads);
    if (access(path, F_OK) == 0)
        H_FAIL("a .bak with nothing to put aside");

    /* one there already: put aside as .bak; with .bak there too, as .b01 */
    hReset(tmp, "s2");
    mkdir(hPads, 0777);
    hWriteFile(hFile, "old one\n");
    guiSetUpUsbPad();
    snprintf(path, sizeof(path), "%s/1234_5678.bak", hPads);
    if (hReadFile(path, got, sizeof(got)) < 0 || strcmp(got, "old one\n") != 0)
        H_FAIL(".bak: '%s'", got);
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("after .bak, written: '%s'", got);
    hReset(tmp, "s3");
    mkdir(hPads, 0777);
    hWriteFile(hFile, "newer\n");
    snprintf(path, sizeof(path), "%s/1234_5678.bak", hPads);
    hWriteFile(path, "oldest\n");
    guiSetUpUsbPad();
    snprintf(path, sizeof(path), "%s/1234_5678.b01", hPads);
    if (hReadFile(path, got, sizeof(got)) < 0 || strcmp(got, "newer\n") != 0)
        H_FAIL(".b01: '%s'", got);
    snprintf(path, sizeof(path), "%s/1234_5678.bak", hPads);
    if (hReadFile(path, got, sizeof(got)) < 0 || strcmp(got, "oldest\n") != 0)
        H_FAIL(".bak changed: '%s'", got);

    /* a write that fails: the new file removed, the old one kept aside and named */
    hReset(tmp, "s4");
    mkdir(hPads, 0777);
    hWriteFile(hFile, "old one\n");
    hWriteFails = 1;
    guiSetUpUsbPad();
    if (access(hFile, F_OK) == 0)
        H_FAIL("a failed write left %s", hFile);
    snprintf(path, sizeof(path), "%s/1234_5678.bak", hPads);
    if (hReadFile(path, got, sizeof(got)) < 0 || strcmp(got, "old one\n") != 0)
        H_FAIL("failed write: .bak '%s'", got);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_WRITE_FAILED_BAK), hFile, "1234_5678.bak");
    hExpectMsg("failed write, old one aside", want);
    hExpectLearn("failed write", 2, 1, 0);
    hReset(tmp, "s5");
    hWriteFails = 1;
    guiSetUpUsbPad();
    if (access(hFile, F_OK) == 0 || hUnlinks != 1)
        H_FAIL("failed write, none before: file left or not removed (%d)", hUnlinks);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_WRITE_FAILED), hFile);
    hExpectMsg("failed write", want);

    /* a write that says it is done and is not: read back, found short, removed */
    hReset(tmp, "s5b");
    hWriteLies = 1;
    guiSetUpUsbPad();
    if (access(hFile, F_OK) == 0 || hUnlinks != 1)
        H_FAIL("short write: file left or not removed (%d)", hUnlinks);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_WRITE_FAILED), hFile);
    hExpectMsg("short write", want);

    /* one there that cannot be put aside: left as it was, nothing written */
    hReset(tmp, "s6");
    mkdir(hPads, 0777);
    hWriteFile(hFile, "keep me\n");
    hRenameFails = 1;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, "keep me\n") != 0 || hUnlinks != 0)
        H_FAIL("kept: '%s' (%d removed)", got, hUnlinks);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_KEPT), hFile);
    hExpectMsg("kept", want);

    /* the driver did not take learn mode: said, and nothing else */
    hReset(tmp, "s7");
    hLearnFails = 1;
    guiSetUpUsbPad();
    hExpectMsg("no driver", _l(_STR_PAD_SETUP_NO_DRIVER));
    hExpectLearn("no driver", 1, 1, 0);
    if (hPolls != 0)
        H_FAIL("no driver: %d polls", hPolls);

    /* no settings folder to put PADS beside */
    hReset(tmp, "s8");
    hNoHome = 1;
    guiSetUpUsbPad();
    hExpectMsg("no home", _l(_STR_MY_PADS_NO_HOME));
    hExpectLearn("no home", 0, 0, 0);

    /* backed out while waiting for the pad, and at the very end: no file, no message, the driver let go */
    hReset(tmp, "s9");
    hCancelView = PAD_SETUP_VIEW_PLUG;
    guiSetUpUsbPad();
    hExpectLearn("cancel at plug", 2, 1, 0);
    if (hMsgBoxes != 0 || access(hFile, F_OK) == 0)
        H_FAIL("cancel at plug: a message or a file");
    hReset(tmp, "s10");
    hCancelView = PAD_SETUP_VIEW_TRY;
    guiSetUpUsbPad();
    hExpectLearn("cancel at try", 2, 1, 0);
    if (hMsgBoxes != 0 || access(hFile, F_OK) == 0)
        H_FAIL("cancel at try: a message or a file");

    /* every step skipped: nothing to write */
    hReset(tmp, "s11");
    hSkip = -1;
    guiSetUpUsbPad();
    hExpectMsg("all skipped", _l(_STR_PAD_SETUP_NOTHING));
    hExpectLearn("all skipped", 2, 1, 0);
    if (access(hFile, F_OK) == 0)
        H_FAIL("all skipped: a file was written");

    /* L3, R3 and the right stick skipped: written as none */
    hReset(tmp, "s12");
    hSkip = 1 << 10 | 1 << 11 | 1 << 18 | 1 << 19;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || !strstr(got, "\nl3=none\n") || !strstr(got, "\nr3=none\n") ||
        !strstr(got, "\nrx=none\n") || !strstr(got, "\nry=none\n") || !strstr(got, "\nlx=a3\n"))
        H_FAIL("skipped: written\n%s", got);

    /* Circle brushed on the way to Cross, for less than a hold: Cross is what is taken, and Circle is still free */
    hReset(tmp, "s13");
    hBrush = 0;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("brushed: written\n%s\nwant:\n%s", got, hMade);

    /* Cross held for a hold, then the thumb slides to Circle, a bit in the same byte, for less than one: the count
       starts again, so Circle is not taken for Cross. The same for the left stick swung the other way */
    hReset(tmp, "s13b");
    hSlide = 0;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("slid to Circle: written\n%s\nwant:\n%s", got, hMade);
    hReset(tmp, "s13c");
    for (i = 0; i < PAD_SETUP_STEPS; i++)
        if (padSetupSteps[i].axis && padSetupSteps[i].id == PAD_AX_LX)
            hSlide = i;
    guiSetUpUsbPad();
    if (hSlide < 0 || hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("left stick swung back: written\n%s\nwant:\n%s", got, hMade);

    /* another pad's reports in that port, while this one is measured at rest (past the first half second) and while
       Cross is asked for: never taken for this pad's */
    hReset(tmp, "s14");
    hStrangerView = PAD_SETUP_VIEW_REST;
    hStrangerFrom = 41;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("another pad at rest: written\n%s", got);
    hReset(tmp, "s15");
    hStrangerView = PAD_SETUP_VIEW_STEP;
    hStrangerFrom = 1;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("another pad on Cross: written\n%s", got);

    /* saved, but past the block's four: the file stays, and the box says it is not used */
    hReset(tmp, "s16");
    hUnused = 1;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("not used: written\n%s", got);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_SAVED_UNUSED), hFile, PAD_DEFS_MAX);
    hExpectMsg("not used", want);
    hExpectLearn("not used", 2, 1, 0);

    /* a close that fails, on a device that then reads it back whole from its cache: removed all the same */
    hReset(tmp, "s17");
    hCloseFails = 1;
    guiSetUpUsbPad();
    if (access(hFile, F_OK) == 0 || hUnlinks != 1)
        H_FAIL("failed close: file left or not removed (%d)", hUnlinks);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_WRITE_FAILED), hFile);
    hExpectMsg("failed close", want);
    hExpectLearn("failed close", 2, 1, 0);

    /* no pad that works the menu without a profile: said, before the driver is touched */
    hReset(tmp, "s18");
    hNoPlainPad = 1;
    guiSetUpUsbPad();
    hExpectMsg("no plain pad", _l(_STR_PAD_SETUP_NO_PAD));
    hExpectLearn("no plain pad", 0, 0, 0);
    if (hPolls != 0)
        H_FAIL("no plain pad: %d polls", hPolls);

    /* a profiled pad in port 0 as the screen opens, never taken out: never taken; cancelled while it waits */
    hReset(tmp, "s19");
    hOld = 1;
    hCancelView = PAD_SETUP_VIEW_PLUG;
    hCancelFrame = 30;
    guiSetUpUsbPad();
    hExpectLearn("old pad stays", 2, 1, 0);
    snprintf(path, sizeof(path), "%s/0E6F_0213.pad", hPads);
    if (hMsgBoxes != 0 || access(hFile, F_OK) == 0 || access(path, F_OK) == 0)
        H_FAIL("old pad stays: a message or a file");

    /* the same, and the pad to set up, with the same ID, plugged into port 1: that one is read, there only */
    hReset(tmp, "s20");
    hOld = hOldSameId = 1;
    hPort = 1;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("new pad in port 1: written\n%s", got);
    snprintf(want, sizeof(want), _l(_STR_PAD_SETUP_SAVED), hFile);
    hExpectMsg("new pad in port 1", want);

    /* the pad to set up in port 0 as the screen opens: taken once it has been out and in again */
    hReset(tmp, "s21");
    hPresent = hReplug = 1;
    guiSetUpUsbPad();
    if (hReadFile(hFile, got, sizeof(got)) < 0 || strcmp(got, hMade) != 0)
        H_FAIL("replugged: written\n%s", got);
}

static void myPadsChecks(const char *tmp)
{
    static const char *const good = "[Device]\nformat=1\ndecoder=generic\n[Buttons]\ncross=b0.1\n";
    char want[1024], path[500], big[5000];
    int i;

    /* no settings folder */
    hReset(tmp, "m0");
    hNoHome = 1;
    guiShowMyPads();
    hExpectMsg("My Pads, no home", _l(_STR_MY_PADS_NO_HOME));

    /* no PADS folder: None yet, and nothing made */
    hReset(tmp, "m1");
    guiShowMyPads();
    snprintf(want, sizeof(want), _l(_STR_MY_PADS_IN), hPads);
    snprintf(want + strlen(want), sizeof(want) - strlen(want), "\n%s\n", _l(_STR_MY_PADS_NONE));
    snprintf(want + strlen(want), sizeof(want) - strlen(want), _l(_STR_MY_PADS_GAME_MAPS), 0);
    hExpectMsg("My Pads, no PADS", want);
    if (access(hPads, F_OK) == 0)
        H_FAIL("My Pads made the PADS folder");

    /* each reason, in the packer's order: a name read the way the reader reads a key, none, a line the reader refuses */
    hReset(tmp, "m2");
    mkdir(hPads, 0777);
    snprintf(path, sizeof(path), "%s/GAMES", hPads);
    mkdir(path, 0777);
    snprintf(path, sizeof(path), "%s/GAMES/SLUS_123.45.pad", hPads);
    hWriteFile(path, "format=1\ncross=circle\n");
    snprintf(path, sizeof(path), "%s/GAMES/SCES_000.00.PAD", hPads);
    hWriteFile(path, "format=1\n");
    snprintf(path, sizeof(path), "%s/GAMES/notes.txt", hPads);
    hWriteFile(path, "x");
#define H_PAD(name, t) do { snprintf(path, sizeof(path), "%s/" name, hPads); hWriteFile(path, t); } while (0)
#define H_WANT(...) snprintf(want + strlen(want), sizeof(want) - strlen(want), __VA_ARGS__)
    H_PAD("0001_0001.pad", "[Device]\nformat=1\n  NAME =  First pad   # mine\ndecoder=generic\n[Buttons]\ncross=b0.1\n");
    H_PAD("0001_0002.pad", good);
    H_PAD("0001_0003.pad", "[Device]\nnot a line\n");
    H_PAD("readme.txt", "x");
    guiShowMyPads();
    snprintf(want, sizeof(want), _l(_STR_MY_PADS_IN), hPads);
    H_WANT("\n0001:0001 First pad - %s", _l(_STR_OK));
    H_WANT("\n0001:0002 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
    H_WANT("\n0001:0003 - line 2: not key=value\n");
    H_WANT(_l(_STR_MY_PADS_GAME_MAPS), 2);
    hExpectMsg("My Pads, names and a refused line", want);

    /* not generic, too big, unreadable */
    hReset(tmp, "m3");
    mkdir(hPads, 0777);
    H_PAD("0001_0004.pad", "[Device]\nformat=1\nname=Old DS3 copy\ndecoder=ds3\n");
    memset(big, '#', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    H_PAD("0001_0005.pad", big);
    snprintf(path, sizeof(path), "%s/0001_0006.pad", hPads);
    mkdir(path, 0777); /* it opens, and cannot be read */
    guiShowMyPads();
    snprintf(want, sizeof(want), _l(_STR_MY_PADS_IN), hPads);
    H_WANT("\n0001:0004 Old DS3 copy - %s", _l(_STR_MY_PADS_NOT_GENERIC));
    H_WANT("\n0001:0005 - ");
    H_WANT(_l(_STR_MY_PADS_TOO_BIG), PAD_PROFILE_TEXT_MAX);
    H_WANT("\n0001:0006 - %s\n", _l(_STR_MY_PADS_UNREADABLE));
    H_WANT(_l(_STR_MY_PADS_GAME_MAPS), 0);
    hExpectMsg("My Pads, left out", want);

    /* Sony and the ShanWan PS3 pad are the drivers' own; a long name is cut at a character's start */
    hReset(tmp, "m4");
    mkdir(hPads, 0777);
    H_PAD("0001_0001.pad", "[Device]\nformat=1\nname=x\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\xc3\x84\ndecoder=generic\n[Buttons]\ncross=b0.1\n");
    H_PAD("054C_0268.pad", good);
    H_PAD("2563_0575.pad", good);
    snprintf(path, sizeof(path), "%s/GAMES", hPads);
    mkdir(path, 0777);
    snprintf(path, sizeof(path), "%s/GAMES/SLUS_123.45.pad", hPads);
    hWriteFile(path, "format=1\n");
    guiShowMyPads();
    snprintf(want, sizeof(want), _l(_STR_MY_PADS_IN), hPads);
    H_WANT("\n0001:0001 x");
    for (i = 0; i < 19; i++)
        H_WANT("\xc3\x84");
    H_WANT(" - %s", _l(_STR_OK));
    H_WANT("\n054C:0268 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_MY_PADS_BUILT_IN));
    H_WANT("\n2563:0575 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_MY_PADS_BUILT_IN));
    H_WANT("\n%s", _l(_STR_MY_PADS_GAME_MAP));
    hExpectMsg("My Pads, built in", want);

    /* a game gets the first four good ones: the packer reads no further, so a broken fifth is only "left out" */
    hReset(tmp, "m5");
    mkdir(hPads, 0777);
    H_PAD("0001_0001.pad", good);
    H_PAD("0002_0002.pad", good);
    H_PAD("2563_0576.pad", good);
    H_PAD("3000_0001.pad", good);
    H_PAD("3000_0002.pad", "broken\n");
    guiShowMyPads();
    snprintf(want, sizeof(want), _l(_STR_MY_PADS_IN), hPads);
    H_WANT("\n0001:0001 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
    H_WANT("\n0002:0002 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
    H_WANT("\n2563:0576 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
    H_WANT("\n3000:0001 %s - %s", _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
    H_WANT("\n3000:0002 - ");
    H_WANT(_l(_STR_MY_PADS_FULL), PAD_DEFS_MAX);
    H_WANT("\n");
    H_WANT(_l(_STR_MY_PADS_GAME_MAPS), 0);
    hExpectMsg("My Pads, full", want);

    /* a long list: the first rows that fit, then and N more, inside one message box */
    hReset(tmp, "m6");
    mkdir(hPads, 0777);
    for (i = 0; i < 30; i++) {
        snprintf(path, sizeof(path), "%s/1000_%04X.pad", hPads, i);
        hWriteFile(path, "[Device]\nformat=1\nname=A pad with a name long enough to wrap the line it is on\ndecoder=generic\n[Buttons]\ncross=b0.1\n");
    }
    guiShowMyPads();
    {
        char wrapped[2048], more[64];
        int lines = guiWrapText(hMsg, 0, wrapped, sizeof(wrapped)), rows = 0;
        const char *p;
        for (p = hMsg; (p = strstr(p, "\n1000:")) != NULL; p++)
            rows++;
        snprintf(more, sizeof(more), _l(_STR_MY_PADS_MORE), 30 - rows);
        if (strlen(hMsg) >= 480 || lines > 10 || rows < 1 || rows >= 30 || !strstr(hMsg, more) ||
            !strstr(hMsg, "\n1000:0000 ") || strstr(hMsg, "1000:001D"))
            H_FAIL("long list: %d bytes, %d lines, %d rows:\n%s", (int)strlen(hMsg), lines, rows, hMsg);
    }

    /* the first row that does not fit ends the list: a shorter one after it is counted in "and N more", never shown out
       of order */
    hReset(tmp, "m7");
    mkdir(hPads, 0777);
    H_PAD("1000_0000.pad", "[Device]\nformat=1\nname=A pad with a name long enough to wrap the line it is on\ndecoder=generic\n[Buttons]\ncross=b0.1\n");
    H_PAD("1000_0001.pad", "[Device]\nformat=1\nname=A pad with a name long enough to wrap the line it is on\ndecoder=ds3\n");
    H_PAD("1000_0002.pad", "[Device]\nformat=1\ndecoder=ds3\n");
    H_PAD("1000_0003.pad", "[Device]\nformat=1\nname=A pad with a name long enough to wrap the line it is on\ndecoder=ds3\n");
    H_PAD("1000_0004.pad", good);
    guiShowMyPads();
    {
        char row[64], more[64], body[1024], wrapped[4096];
        const char *tail;
        int k, n;
        for (k = 0; k < 5; k++) {
            snprintf(row, sizeof(row), "\n1000:%04X ", k);
            if (!strstr(hMsg, row))
                break;
        }
        for (n = k + 1; n < 5; n++) {
            snprintf(row, sizeof(row), "\n1000:%04X ", n);
            if (strstr(hMsg, row))
                H_FAIL("row %d shown after row %d did not fit:\n%s", n, k, hMsg);
        }
        snprintf(more, sizeof(more), "\n");
        snprintf(more + 1, sizeof(more) - 1, _l(_STR_MY_PADS_MORE), 5 - k);
        if (k == 0 || k == 5 || (tail = strstr(hMsg, more)) == NULL)
            H_FAIL("stopped list: rows 0 to %d shown, no \"%s\":\n%s", k - 1, more + 1, hMsg);
        else {
            /* the last row would have fit where the list stopped, so the above checks what it says it does */
            snprintf(body, sizeof(body), "%.*s\n1000:0004 %s - %s", (int)(tail - hMsg), hMsg, _l(_STR_MY_PADS_NO_NAME), _l(_STR_OK));
            if ((int)strlen(body) >= MY_PADS_MSG - MY_PADS_TAIL || guiWrapText(body, 0, wrapped, sizeof(wrapped)) > MY_PADS_LINES - 2)
                H_FAIL("m7 checks nothing now: its last row would not fit either\n%s", hMsg);
        }
    }

    /* rows that wrap: the box's lines run out before its bytes do */
    hReset(tmp, "m8");
    mkdir(hPads, 0777);
    for (i = 0; i < 6; i++) {
        snprintf(path, sizeof(path), "%s/054C_%04X.pad", hPads, i);
        hWriteFile(path, "[Device]\nformat=1\nname=x\ndecoder=generic\n[Buttons]\ncross=b0.1\n");
    }
    guiShowMyPads();
    {
        char row[200], more[64], wrapped[4096];
        const char *p, *tail;
        int lines = guiWrapText(hMsg, 0, wrapped, sizeof(wrapped)), rows = 0;
        for (p = hMsg; (p = strstr(p, "\n054C:")) != NULL; p++)
            rows++;
        snprintf(more, sizeof(more), "\n");
        snprintf(more + 1, sizeof(more) - 1, _l(_STR_MY_PADS_MORE), 6 - rows);
        snprintf(row, sizeof(row), "054C:0000 x - %s", _l(_STR_MY_PADS_BUILT_IN));
        if (lines > MY_PADS_LINES || rows < 1 || rows >= 6 || (tail = strstr(hMsg, more)) == NULL)
            H_FAIL("wrapped rows: %d lines, %d rows:\n%s", lines, rows, hMsg);
        else if ((int)(tail - hMsg) + 1 + (int)strlen(row) >= MY_PADS_MSG - MY_PADS_TAIL)
            H_FAIL("m8 checks nothing now: the bytes ran out first\n%s", hMsg);
    }
}

int main(void)
{
    char tmp[] = "/tmp/padsetupXXXXXX";
    char cmd[100];
    if (mkdtemp(tmp) == NULL)
        return 2;
    setupChecks(tmp);
    myPadsChecks(tmp);
    snprintf(cmd, sizeof(cmd), "rm -rf '%s'", tmp);
    if (system(cmd) != 0)
        return 3;
    if (hFailed)
        return 1;
    printf("screens ok\n");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for name, prog, want in (('finder', FINDER, 'finder ok'), ('screens', HARNESS, 'screens ok')):
        if name == 'screens' and not pieces_ok:
            continue
        (td / (name + '.c')).write_text(prog, encoding='utf-8')
        r = subprocess.run([cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-format-truncation', '-I', str(root),
                            str(td / (name + '.c')), str(root / 'src/padfile.c'), '-o', str(td / name)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            fail.append('the %s program must build on the PC: %s' % (name, r.stderr[-1500:]))
            continue
        r = subprocess.run([str(td / name)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=300)
        if r.returncode or want not in r.stdout:
            fail.append('%s: check %d failed:\n%s' % (name, r.returncode, r.stdout.strip()[-3000:]))

print('\n'.join(fail) or 'pad setup screen: both rows Pad Emulator only; the frame holds the GUI lock around drawing only; '
      'the finder finds a button, an active-low button, a hat, a trigger and a stick; the screen writes, puts aside, '
      'refuses and backs out as it should, with the driver let go before every message; My Pads lists what a game '
      'gets of each profile, and why not, in the packer\'s order, inside one message box')
sys.exit(1 if fail else 0)
