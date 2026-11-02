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
5. One theme switch and one language switch at a time. thmLoad and lngLoadFromFile read the current theme or
   strings before they take the GUI lock, so two loads at once (the IO thread bringing up a device with the
   saved theme while the GUI thread changes the view, say) would both free the same one. Every thmLoad,
   setGuiValueLocked and thmSetViewLocked call sits where the theme switch lock is held, and every
   lngLoadFromFile call where the language switch lock is held; the functions that take a lock are never
   called with it already held (it is not recursive), the C edition releases it on every way out, and both
   locks exist before the IO thread starts. A reload of the current theme reads the id under the lock
   (thmReload), never as thmSetGuiValue(thmGetGuiValue(), 1), which can reload a theme the IO thread has
   just replaced. Theme code never switches language, so the lock order stays language, theme, GUI.
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


def blank_literals(text):
    """text with the inside of every string and character literal blanked (quotes and newlines kept)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == '\\' else 1
            out.append(c + re.sub(r'[^\n]', ' ', text[i + 1:j]) + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


DEFINITION = re.compile(r'^(?![\s#/])[^\n;{}=]*?([\w:~]+)\s*\([^;{}]*\)\s*(?:const\s*)?\n\{', re.M)


def functions(code):
    """(name, signature start, body start, body end) of every top-level function definition in code."""
    found = []
    for m in DEFINITION.finditer(code):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(code)):
            if code[i] == '{':
                depth += 1
            elif code[i] == '}':
                depth -= 1
                if depth == 0:
                    found.append((m.group(1).split('::')[-1], m.start(), start, i))
                    break
    return found


def block_end(code, pos):
    """Position of the '}' that closes the innermost block holding pos."""
    depth = 0
    for i in range(pos, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            if depth == 0:
                return i
            depth -= 1
    return len(code)


class SwitchLock:
    def __init__(self, rel, take, drop, raii):
        self.rel = rel
        self.code = blank_literals(strip_comments(read(rel)))
        self.funcs = functions(self.code)
        self.take = take
        self.drop = drop
        self.raii = raii

    def where(self, pos):
        return '%s:%d' % (self.rel, self.code.count('\n', 0, pos) + 1)

    def enclosing(self, pos):
        for f in self.funcs:
            if f[2] < pos < f[3]:
                return f
        return None

    def defined_at(self, pos):
        return any(f[1] <= pos < f[2] for f in self.funcs)

    def held(self, pos):
        f = self.enclosing(pos)
        if f is None:
            return False
        for t in re.finditer(re.escape(self.take), self.code[:pos]):
            if t.start() < f[2]:
                continue
            # A C-style lock lasts to its unlock; a scoped one also ends with the block that holds it.
            end = block_end(self.code, t.end()) if self.raii else f[3]
            drop = self.code.find(self.drop, t.end(), end)
            end = drop if drop >= 0 else end
            if pos < end:
                return True
        return False

    def calls(self, name):
        for m in re.finditer(r'\b%s\s*\(' % re.escape(name), self.code):
            if not self.defined_at(m.start()):
                yield m.start()

    def body(self, name):
        for f in self.funcs:
            if f[0] == name:
                return f
        failures.append('%s: %s() not found' % (self.rel, name))
        return None


def check_switch_lock(lock, takers, locked_only):
    for name in takers:
        f = lock.body(name)
        if f is None:
            continue
        body = lock.code[f[2]:f[3]]
        takes = body.count(lock.take)
        if takes != 1:
            failures.append('%s: %s() takes the switch lock %d times, not once' % (lock.rel, name, takes))
            continue
        if not lock.raii:
            t = body.find(lock.take)
            d = body.find(lock.drop, t)
            if d < 0 or body.count(lock.drop) != 1:
                failures.append('%s: %s() must release the switch lock exactly once, after taking it' % (lock.rel, name))
            elif re.search(r'\breturn\b', body[t:d]):
                failures.append('%s: %s() returns while it still holds the switch lock' % (lock.rel, name))
    for name in locked_only:
        for pos in lock.calls(name):
            f = lock.enclosing(pos)
            if f is None:
                continue  # a prototype
            if f[0] not in locked_only and not lock.held(pos):
                failures.append('%s %s() called from %s() without the switch lock held' % (lock.where(pos), name, f[0]))
    for name in takers:
        for pos in lock.calls(name):
            if lock.held(pos) or (lock.enclosing(pos) or ('',))[0] in locked_only:
                failures.append('%s %s() takes the switch lock, but its caller already holds it (not recursive)'
                                % (lock.where(pos), name))


def check_created_first(rel, init, sema, first_use):
    code = blank_literals(strip_comments(read(rel)))
    body = function_body(code, init)
    if body is None:
        failures.append(init + ' not found in ' + rel)
        return
    # RiptOPL's themes and language code sit below the device layer, so they make the lock with the kernel call
    # (semaCreateBinary in include/sema_lock.h); the C edition uses sbCreateSemaphore.
    made = body.find('%s = %s();' % (sema, 'semaCreateBinary' if CPP else 'sbCreateSemaphore'))
    used = body.find(first_use)
    if made < 0 or used < 0 or made > used:
        failures.append('%s: %s...) must create %s before %s' % (rel, init, sema, first_use))


def check_switch_locks():
    if CPP:
        theme = SwitchLock(THEMES_FILE, 'raii::SemaLock lock(thmSwitchSema);', 'lock.unlock();', True)
        lang = SwitchLock(LANG_FILE, 'raii::SemaLock lock(lngSwitchSema);', 'lock.unlock();', True)
        theme_takers = ('addElements', 'reinit', 'setGuiValue', 'thmSetView', 'thmCycleView',
                        'thmRefreshDisplayLayout', 'thmRefreshGridLayout', 'thmReload', 'thmInit')
        lang_locked = ('lngLoadFromFile',)
    else:
        theme = SwitchLock(THEMES_FILE, 'thmSwitchLock();', 'thmSwitchUnlock();', False)
        lang = SwitchLock(LANG_FILE, 'lngSwitchLock();', 'lngSwitchUnlock();', False)
        theme_takers = ('thmAddElements', 'thmReinit', 'thmSetGuiValue', 'thmSetView', 'thmCycleView',
                        'thmRefreshDisplayLayout', 'thmRefreshGridLayout', 'thmReload', 'thmInit')
        lang_locked = ('lngLoadFromFile', 'lngSetGuiValueLocked')
    check_switch_lock(theme, theme_takers, ('thmLoad', 'setGuiValueLocked', 'thmSetGuiValueLocked',
                                            'thmSetViewLocked', 'thmCycleViewLocked'))
    check_switch_lock(lang, ('lngSetGuiValue',), lang_locked)
    for name in ('thmLoad', 'lngLoadFromFile'):
        lock = theme if name == 'thmLoad' else lang
        if not list(lock.calls(name)):
            failures.append('%s: %s() is never called' % (lock.rel, name))

    check_created_first(THEMES_FILE, 'void thmInit(', 'thmSwitchSema', 'thmLoad(NULL);')
    check_created_first(LANG_FILE, 'void lngInit(', 'lngSwitchSema', 'lngAddLanguages(')
    boot = blank_literals(strip_comments(read(OPL_FILE)))
    first = {}
    for name in ('ioInit', 'lngInit', 'thmInit'):
        m = re.search(r'\b%s\(\);' % name, boot)  # \b: audioInit() is not ioInit()
        first[name] = m.start() if m else -1
    for name in ('lngInit', 'thmInit'):
        if first[name] < 0 or first['ioInit'] < 0 or first[name] > first['ioInit']:
            failures.append('%s: %s() must run before ioInit(), which starts the IO thread' % (OPL_FILE, name))

    stale = re.compile(r'\b(?:thmSetGuiValue|setGuiValue)\s*\(\s*(?:thmGetGuiValue\(\)|(?:gCatalog\.)?guiValue\(\)|guiThemeID)(?!\w)')
    for path in sorted((root / 'src').rglob('*')):
        if path.suffix not in ('.c', '.cpp'):
            continue
        text = blank_literals(strip_comments(path.read_text(encoding='utf-8', errors='replace')))
        for m in stale.finditer(text):
            failures.append('%s:%d reloads the theme by an id read outside the theme switch lock: use thmReload()'
                            % (path.relative_to(root), text.count('\n', 0, m.start()) + 1))
    if re.search(r'\blngSetGuiValue\s*\(', theme.code):
        failures.append('%s: theme code switches the language; the lock order is language, then theme' % THEMES_FILE)


for rel in DIALOG_FILES:
    check_frames(rel)
check_keyboard()
check_deferred()
check_swap(THEMES_FILE, 'static int thmLoad(', 'gTheme = newT;', 'thmFree(curT);')
check_swap(LANG_FILE, 'static int lngLoadFromFile(', 'lang_strs = newL;', 'lngFreeFromFile(curL);')
check_swap(LANG_FILE, 'int lngSetGuiValue(' if CPP else 'static int lngSetGuiValueLocked(', 'lang_strs = internalEnglish;',
           'lngFreeFromFile(oldL);')
check_switch_locks()

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok: dialogs draw under the GUI lock; the IO thread swaps the theme, the language and the menu rows under it; '
      'one theme switch and one language switch at a time')
