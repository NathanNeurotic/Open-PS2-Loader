"""Dialogs draw under the GUI lock, and the IO thread runs queued list operations under it.

The IO thread swaps a theme or language found on a device, and frees the old one, under guiLock
(thmAddElements, lngAddLanguages, lngSetGuiValue). The main loop's frames hold that lock
(guiStartFrame..guiEndFrame), but the settings dialogs, the on-screen keyboard, the number pad and
the colour picker drive their own rmStartFrame/rmEndFrame loops, which did not: a dialog open while a
USB stick, SMB share or HDD with the configured theme or language came up could draw freed strings,
icons and font slots (garbled text or a freeze). Ported from YAOPL ce6323f (Roman Kelesidis).

The same thread also ran guiExecDeferredOps() from updateMenuFromGameList without the lock, so the
queued row appends, clears and sorts changed the menu while the GUI thread drew it (YAOPL 4c713a3).

Checks, on the source:
1. Every rmStartFrame() in the dialog files is preceded by guiLock() with no rmEndFrame() between
   them, and the matching rmEndFrame() is followed by guiUnlock() before the next readPads() or
   getKey() (input handling and the dialog updaters run unlocked, as they may open dialogs and do IO).
2. The keyboard looks its command texts and icons up inside the locked frame, not once before it.
3. Each guiExecDeferredOps() the IO thread calls (updateMenuFromGameList, menuDeferredUpdate) sits
   between guiLock() and guiUnlock().
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


CPP = (root / 'src' / 'ui' / 'dia.cpp').exists()
DIALOG_FILES = ['src/ui/dia.cpp', 'src/ui/diaeditors.cpp'] if CPP else ['src/dia.c']
OPL_FILE = 'src/app/opl.cpp' if CPP else 'src/opl.c'
KEYB_FILE = 'src/ui/diaeditors.cpp' if CPP else 'src/dia.c'

CALL = re.compile(r'\b(guiLock|guiUnlock|rmStartFrame|rmEndFrame|readPads|getKey)\s*\(')


def check_frames(rel):
    src = read(rel)
    events = [(m.start(), m.group(1)) for m in CALL.finditer(src)]
    locked = False
    frame = False
    for pos, name in events:
        line = src.count('\n', 0, pos) + 1
        if name == 'guiLock':
            locked = True
        elif name == 'guiUnlock':
            locked = False
        elif name == 'rmStartFrame':
            if not locked:
                failures.append('%s:%d rmStartFrame() without guiLock() before it' % (rel, line))
            frame = True
        elif name == 'rmEndFrame':
            frame = False
        elif name in ('readPads', 'getKey'):
            if locked and not frame:
                failures.append('%s:%d %s() while the frame lock is still held (guiUnlock() must follow rmEndFrame())' % (rel, line, name))
    if frame or locked:
        failures.append('%s: a frame or lock is left open at the end of the file' % rel)


def check_keyboard():
    src = read(KEYB_FILE)
    pos = src.find('int diaShowKeyb(')
    if pos < 0:
        failures.append('diaShowKeyb not found in ' + KEYB_FILE)
        return
    body = src[pos:src.find('\n}\n', pos)]
    first_frame = body.find('rmStartFrame()')
    for sym in ('_l(_STR_BACKSPACE)', 'thmGetTexture(SQUARE_ICON)'):
        at = body.find(sym)
        if at < 0 or at > first_frame:
            failures.append('diaShowKeyb: %s is not looked up inside the frame loop' % sym)
        if body.find(sym, 0, first_frame) >= 0 and body.find('guiLock()', 0, at) < 0:
            failures.append('diaShowKeyb: %s is looked up before the first guiLock()' % sym)
    if body.find('char *commands[KEYB_HEIGHT] = {') >= 0:
        failures.append('diaShowKeyb: command texts are still looked up once, before the first frame')


def check_deferred():
    src = read(OPL_FILE)
    for fn in ('static void updateMenuFromGameList(', 'void menuDeferredUpdate('):
        pos = src.find(fn)
        if pos < 0:
            failures.append(fn + ' not found in ' + OPL_FILE)
            continue
        body = src[pos:src.find('\n}\n', pos)]
        for m in re.finditer(r'guiExecDeferredOps\(\);', body):
            before = body[:m.start()]
            if before.rfind('guiLock();') < before.rfind('guiUnlock();') or 'guiLock();' not in before:
                failures.append('%s: guiExecDeferredOps() in %s runs without guiLock()' % (OPL_FILE, fn.split('(')[0].split()[-1]))
            after = body[m.end():]
            if 'guiUnlock();' not in after or (after.find('guiLock();') >= 0 and after.find('guiLock();') < after.find('guiUnlock();')):
                failures.append('%s: guiExecDeferredOps() in %s is not followed by guiUnlock()' % (OPL_FILE, fn.split('(')[0].split()[-1]))


for rel in DIALOG_FILES:
    check_frames(rel)
check_keyboard()
check_deferred()

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok: dialogs draw under the GUI lock; IO-thread list operations run under it')
