"""Dialogs draw under the GUI lock, and the IO thread changes what they draw only under it.

The GUI thread draws the theme, the language strings and the menus between guiStartFrame() and
guiEndFrame(), which hold guiLock. Three gaps, all found and fixed in YAOPL by Roman Kelesidis:
- the settings dialogs, the on-screen keyboard, the number pad and the colour picker drive their own
  rmStartFrame/rmEndFrame loops, which did not take the lock (ce6323f);
- the IO thread ran guiExecDeferredOps() from updateMenuFromGameList without it, so the queued row
  appends, clears and sorts changed the menu while the GUI thread drew it (4c713a3);
- thmLoad and lngLoadFromFile published a new theme or language and freed the old one without it. They run
  on the IO thread when a device with the saved theme or language comes up, so a frame drawn meanwhile read
  freed strings, icons and font slots: garbled text, or a freeze (b45a592d).

guiLock is a semaphore, not a recursive mutex: a thread that takes it twice waits for itself forever.

Checks, on the source:
1. Every rmStartFrame() in the dialog files is preceded by guiLock() with no rmEndFrame() between them.
   guiUnlock() comes only after the matching rmEndFrame(), and before the next readPads() or getKey()
   (input handling and the dialog updaters run unlocked, as they may open dialogs and do IO). guiLock()
   is never taken while it is already held.
2. The keyboard looks up its title, command texts and icons inside its loop while the lock is held, never
   before the loop. It takes the title as a string id, and no caller hands it a translated pointer or NULL:
   a pointer kept for as long as the keyboard is open is freed by a language swap.
3. Each guiExecDeferredOps() the IO thread calls (updateMenuFromGameList, menuDeferredUpdate) sits between
   guiLock() and guiUnlock(). guiExecDeferredOps itself does not take the lock: menuRowBeginEdit already
   holds it when it calls in.
4. thmLoad publishes the new theme and frees the old one under the lock; lngLoadFromFile and the switch
   back to English do the same for the strings.
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
GUI_FILE = 'src/ui/gui.cpp' if CPP else 'src/gui.c'
THEMES_FILE = 'src/gfx/themes.cpp' if CPP else 'src/themes.c'
LANG_FILE = 'src/core/lang.cpp' if CPP else 'src/lang.c'

CALL = re.compile(r'\b(guiLock|guiUnlock|rmStartFrame|rmEndFrame|readPads|getKey)\s*\(')
# Both spellings take the same semaphore (RiptOPL's host::ui().lock() calls guiLock()).
LOCKING = re.compile(r'\bguiLock\(\);|\bhost::ui\(\)\.lock\(\);')
UNLOCKING = re.compile(r'\bguiUnlock\(\);|\bhost::ui\(\)\.unlock\(\);')


def function_body(src, signature):
    """The text between the braces of the function whose definition starts with signature, or None."""
    at = src.find(signature)
    if at < 0:
        return None
    start = src.find('{', at)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return None


def held_at(body, pos):
    """True when the last lock call before pos is a guiLock, not a guiUnlock."""
    last_lock = max((m.start() for m in LOCKING.finditer(body, 0, pos)), default=-1)
    last_unlock = max((m.start() for m in UNLOCKING.finditer(body, 0, pos)), default=-1)
    return last_lock > last_unlock


def released_after(body, pos):
    """True when the next lock call after pos is a guiUnlock."""
    next_lock = min((m.start() for m in LOCKING.finditer(body, pos)), default=len(body))
    next_unlock = min((m.start() for m in UNLOCKING.finditer(body, pos)), default=len(body))
    return next_unlock < next_lock


def call_args(src, open_paren):
    """The top-level arguments of the call whose '(' is at open_paren."""
    depth = 0
    args = []
    start = open_paren + 1
    for i in range(open_paren, len(src)):
        c = src[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                args.append(src[start:i].strip())
                return args
        elif c == ',' and depth == 1:
            args.append(src[start:i].strip())
            start = i + 1
    return args


def strip_comments(text):
    """text with every comment blanked out (newlines kept, so line numbers still match)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def check_frames(rel):
    src = read(rel)
    locked = False
    frame = False
    for m in CALL.finditer(src):
        name = m.group(1)
        where = '%s:%d' % (rel, src.count('\n', 0, m.start()) + 1)
        if name == 'guiLock':
            if locked:
                failures.append(where + ' guiLock() while the lock is already held (it is not recursive)')
            locked = True
        elif name == 'guiUnlock':
            if frame:
                failures.append(where + ' guiUnlock() before rmEndFrame(): the rest of the frame would draw unlocked')
            locked = False
        elif name == 'rmStartFrame':
            if not locked:
                failures.append(where + ' rmStartFrame() without guiLock() before it')
            frame = True
        elif name == 'rmEndFrame':
            frame = False
        elif locked and not frame:  # readPads, getKey
            failures.append(where + ' %s() while the frame lock is still held (guiUnlock() must follow rmEndFrame())' % name)
    if frame or locked:
        failures.append(rel + ': a frame or lock is left open at the end of the file')


def check_keyboard():
    src = read(KEYB_FILE)
    m = re.search(r'^int diaShowKeyb\(([^)]*)\)\n\{', src, re.M)
    if not m:
        failures.append('diaShowKeyb not found in ' + KEYB_FILE)
        return
    if m.group(1) != 'char *text, int maxLen, int hide_text, int titleId':
        failures.append('diaShowKeyb(%s): the title must come in as a string id (int titleId)' % m.group(1))
    body = function_body(src, m.group(0))
    loop = body.find('while (1) {')
    lock = body.find('guiLock();', loop) if loop >= 0 else -1
    unlock = body.find('guiUnlock();', lock) if lock >= 0 else -1
    if unlock < 0:
        failures.append('diaShowKeyb: no guiLock()..guiUnlock() frame inside a while (1) loop')
        return
    for sym in ('_l(titleId)', '_l(_STR_BACKSPACE)', 'thmGetTexture(SQUARE_ICON)', 'thmGetTexture(L1_ICON)'):
        spots = [s.start() for s in re.finditer(re.escape(sym), body)]
        if not spots:
            failures.append('diaShowKeyb: %s is never looked up' % sym)
        for at in spots:
            if not lock < at < unlock:
                failures.append('diaShowKeyb: %s is looked up outside the locked part of the frame loop' % sym)
    if 'char *commands[KEYB_HEIGHT] = {' in body:
        failures.append('diaShowKeyb: command texts are still looked up once, before the first frame')

    for path in sorted((root / 'src').rglob('*')):
        if path.suffix not in ('.c', '.cpp'):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'diaShowKeyb' not in text:
            continue
        text = strip_comments(text)
        for call in re.finditer(r'\bdiaShowKeyb\s*\(', text):
            if text.startswith('int diaShowKeyb(', call.start()):
                continue  # the definition
            args = call_args(text, call.end() - 1)
            title = args[-1] if args else ''
            if len(args) != 4 or '_l(' in title or title == 'NULL':
                where = '%s:%d' % (path.relative_to(root), text.count('\n', 0, call.start()) + 1)
                failures.append(where + ' diaShowKeyb title "%s": pass a _STR_ id, or -1 for none' % title)


def check_deferred():
    src = read(OPL_FILE)
    for fn in ('static void updateMenuFromGameList(', 'void menuDeferredUpdate('):
        body = function_body(src, fn)
        if body is None:
            failures.append(fn + ' not found in ' + OPL_FILE)
            continue
        name = fn.split('(')[0].split()[-1]
        drains = [d.start() for d in re.finditer(r'guiExecDeferredOps\(\);', body)]
        if not drains:
            failures.append('%s: %s no longer drains the queued operations' % (OPL_FILE, name))
        for at in drains:
            if not held_at(body, at):
                failures.append('%s: guiExecDeferredOps() in %s runs without guiLock()' % (OPL_FILE, name))
            if not released_after(body, at):
                failures.append('%s: guiExecDeferredOps() in %s is not followed by guiUnlock()' % (OPL_FILE, name))

    gui = read(GUI_FILE)
    for fn in (('void Gui::execDeferred(', 'void guiExecDeferredOps(') if CPP else ('void guiExecDeferredOps(',)):
        body = function_body(gui, fn)
        if body is None:
            failures.append(fn + ' not found in ' + GUI_FILE)
        elif re.search(r'\b(?:guiLock|lock)\s*\(', body):
            failures.append('%s: %s...) takes the GUI lock itself, but menuRowBeginEdit calls it with the lock held'
                            % (GUI_FILE, fn))


def check_swap(rel, signature, publish, free):
    body = function_body(read(rel), signature)
    if body is None:
        failures.append(signature + ' not found in ' + rel)
        return
    at = body.find(publish)
    end = body.find(free, at) if at >= 0 else -1
    if end < 0:
        failures.append('%s: %s no longer does "%s" then "%s"' % (rel, signature, publish, free))
        return
    if not held_at(body, at) or not held_at(body, end) or not released_after(body, end):
        failures.append('%s: "%s" and "%s" in %s...) must sit in one locked section' % (rel, publish, free, signature))


for rel in DIALOG_FILES:
    check_frames(rel)
check_keyboard()
check_deferred()
check_swap(THEMES_FILE, 'static int thmLoad(', 'gTheme = newT;', 'thmFree(curT);')
check_swap(LANG_FILE, 'static int lngLoadFromFile(', 'lang_strs = newL;', 'lngFreeFromFile(curL);')
check_swap(LANG_FILE, 'int lngSetGuiValue(', 'lang_strs = internalEnglish;', 'lngFreeFromFile(oldL);')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok: dialogs draw under the GUI lock; the IO thread swaps the theme, the language and the menu rows under it')
