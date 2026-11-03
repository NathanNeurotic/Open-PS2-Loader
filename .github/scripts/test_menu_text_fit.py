"""Menu text stays on screen: the top-right notices wrap, and long game titles and cheat names fit their room.

The same script runs in RiptOPL (src/ui/guinotify.cpp, C++) and Open-PS2-Loader (src/gui.c, C); it finds which tree it
is in by its files.

Measured with the menu font (PoeVeticaNew 17 px, 4:3 SD, the way fntCalcDimensions measures), these ran off screen:
- The top-right notices are right-aligned and nothing stopped them at the left edge. The UDPBD static-IP note is
  about 1020 wide on the 640 grid, the CF notice from the game menu about 890 and "Browse this game through the
  RetroAchievements library" about 610; at the Large font size three more, and in the translations the font can draw,
  100 notices at the default size. The RetroAchievements notice buffer (96 bytes) also cut the English CF notice
  mid-sentence.
- The game menu and app menu draw the selected title centred at the top with no width: a name can run to 160
  characters (CUE folders 191), about twice the screen.
- The cheat list drew each name from x 85 with no width: names run to 128 characters, the rule ends at 590.
Menu rows, the Settings hub and the save prompt fit in every language the built-in font draws, at every size.

1. The notice renderer is compiled and run with the real fntWrapText and a fixed 8-wide font: a notice that fits is
   drawn exactly where it was, a longer one wraps inside a box that stays on screen, the next notice moves down by
   the lines it took, and a toast that fills its whole buffer is drawn without losing a word.
2. Every caller moves to the y the renderer returns.
3. The toast and RetroAchievements buffers hold the longest translation of every message they carry.
4. The game and app menu titles scroll inside 600, and cheat names fit to the rule (the selected one scrolls).
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

root = Path(__file__).resolve().parents[2]
failures = []

if (root / 'src/ui/guinotify.cpp').exists():  # RiptOPL
    LAYOUT = dict(
        notify='src/ui/guinotify.cpp', notify_h='include/guinotify.h',
        render_sig='int Notifications::render(const char *string, int y, int yadd)', render='render',
        toast='toast_', toast_buf=r'char toast_\[(\d+)\]', ra_buf=r'char raNotice_\[2\]\[(\d+)\]',
        ra_line='raNotice_[i]', screen='gGuiScreenWidth', fnt='src/gfx/fntsys.cpp', menusys='src/ui/menusys.cpp',
        cheats='src/ui/guimodal.cpp', cheats_sig='void CheatScreen::draw()', base='lng/tmpl/_base.yml',
        fork='lng/fork', sources='*.cpp', compilers=('g++', 'clang++'), std='-std=gnu++17', ext='.cpp')
else:  # Open-PS2-Loader
    LAYOUT = dict(
        notify='src/gui.c', notify_h='src/gui.c',
        render_sig='static int guiRenderNotifications(const char *string, int y, int yadd)',
        render='guiRenderNotifications', toast='actionToast', toast_buf=r'static char actionToast\[(\d+)\]',
        ra_buf=r'static char raNotice\[2\]\[(\d+)\]', ra_line='raNotice[i]', screen='screenWidth',
        fnt='src/fntsys.c', menusys='src/menusys.c', cheats='src/gui.c',
        cheats_sig='void guiManageCheats(config_set_t *configSet)', base='lng_tmpl/_base.yml', fork='lng_fork',
        sources='*.c', compilers=('gcc', 'clang', 'cc'), std='-std=gnu99', ext='.c')
RENDER = LAYOUT['render']


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    pos = source.find(signature)
    if pos < 0:
        failures.append('%s not found' % signature)
        return ''
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1] + '\n'
    raise AssertionError('unterminated ' + signature)


notify = read(LAYOUT['notify'])
notify_h = read(LAYOUT['notify_h'])
fnt = read(LAYOUT['fnt'])
menusys = read(LAYOUT['menusys'])
cheat_source = read(LAYOUT['cheats'])
name_max = re.search(r'(?:#define HIDDEN_NAME_MAX|constexpr int HIDDEN_NAME_MAX =) (\d+)', read('include/gamemanage.h'))
if not name_max:
    failures.append('include/gamemanage.h: HIDDEN_NAME_MAX not found')
toast_size = re.search(LAYOUT['toast_buf'], notify_h)
ra_size = re.search(LAYOUT['ra_buf'], notify_h)
if not ra_size or not toast_size:
    failures.append('%s: the toast / RA notice buffers were not found' % LAYOUT['notify_h'])

# --- 1. the notice box, compiled and run --------------------------------------------------------------------------
render = function(notify, LAYOUT['render_sig'])
render = re.sub(r'^.*?\(const char \*string, int y, int yadd\)', 'static int render(const char *string, int y, int yadd)',
                render, count=1)
wrap = function(fnt, 'static int fntWrapPut(') + function(fnt, 'int fntWrapText(')

english = {e['label']: e['string'] for e in yaml.safe_load(read(LAYOUT['base']))['gui_strings']
           if 'label' in e and 'string' in e}


def c_string(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned long long u64;
#define ALIGN_NONE 0
#define MENU_ITEM_HEIGHT 19
static struct { int fonts[1]; u64 textColor; } theme, *gTheme = &theme;
static const u64 gColDarker = 7;
static int @SCREEN@ = 640;
/* A fixed 8-wide font: every character, a space included, is 8 */
static int fntCalcDimensions(int id, const char *s) { int n = 0; (void)id; for (; *s; s++) n += ((*s & 0xC0) != 0x80); return 8 * n; }
static int rmUnScaleX(int x) { return x; }
static int txtNext(const char *s, uint32_t *cp) { *cp = (unsigned char)*s; return 1; }
static int txtNoSpaceScript(const char *s, int len) { (void)s; (void)len; return 0; }
static int txtBreakAt(const char *start, const char *s) { (void)start; (void)s; return 1; }
static struct { int x, y, w, h; } box;
static struct { int x, y, w, h; char text[1024]; } drawn;
static int boxes, draws;
static void rmDrawRect(int x, int y, int w, int h, u64 colour) { assert(colour == gColDarker); box.x = x; box.y = y; box.w = w; box.h = h; boxes++; }
static int fntRenderString(int id, int x, int y, short aligned, size_t w, size_t h, const char *s, u64 colour)
{
    (void)id; (void)colour;
    assert(aligned == ALIGN_NONE);
    drawn.x = x; drawn.y = y; drawn.w = (int)w; drawn.h = (int)h;
    snprintf(drawn.text, sizeof(drawn.text), "%s", s);
    draws++;
    return x;
}
@WRAP@
@RENDER@

static int lineCount(const char *s, int *widest)
{
    int lines = 1, w = 0;
    *widest = 0;
    for (; *s; s++) {
        if (*s == '\n') { lines++; w = 0; continue; }
        if ((*s & 0xC0) != 0x80) w += 8;
        if (w > *widest) *widest = w;
    }
    return lines;
}

/* The geometry the notice had before: box from W - textW - 20, textW + 10 wide; text at W - textW - 15 */
static void checkOneLine(const char *text, int y)
{
    int textW = fntCalcDimensions(0, text), oldX = @SCREEN@ - textW - 10;
    int next;
    boxes = draws = 0;
    next = render(text, y, 35);
    assert(boxes == 1 && draws == 1);
    assert(box.x == oldX - 10 && box.y == y && box.w == @SCREEN@ - oldX && box.h == MENU_ITEM_HEIGHT + 10);
    assert(drawn.x == oldX - 5 && drawn.y == y + 5 && drawn.w == 0 && drawn.h == 0 && !strcmp(drawn.text, text));
    assert(next == y + 35);
}

static void checkWrapped(const char *text, int y, int expectLines)
{
    int widest, lines, innerW, next;
    boxes = draws = 0;
    next = render(text, y, 35);
    assert(boxes == 1 && draws == 1);
    lines = lineCount(drawn.text, &widest);
    innerW = box.w - 10;
    if (expectLines)
        assert(lines == expectLines);
    assert(lines > 1);
    assert(box.x >= 10 && box.x + box.w <= @SCREEN@ - 10);                  /* the box is on screen */
    assert(drawn.x == box.x + 5 && drawn.x >= 15);                          /* the text starts inside it */
    assert(widest <= innerW);                                               /* every line fits the box */
    assert(drawn.w == innerW + 5 && drawn.h == box.h - 5);                  /* clipped to the box, '\n' honoured */
    assert(box.h == lines * MENU_ITEM_HEIGHT + 10);
    assert(next == y + 35 + (lines - 1) * MENU_ITEM_HEIGHT);                /* the next notice clears this one */
    printf("wrapped: %d lines, widest %d of %d, box %d..%d\n", lines, widest, innerW, box.x, box.x + box.w);
}

int main(void)
{
    char path[400], edge[78], toast[@TOASTMAX@], joined[sizeof(drawn.text)];
    int i;
    checkOneLine("Theme loaded from mass:", 10);
    checkOneLine("Saved to Favorites", 45);
    /* The widest notice that still fits one line: a box at most 620 wide, 10 from either edge, holds 610 of text.
       76 characters (608) stay on one line; 77 (616) wrap. */
    memset(edge, 'x', 77);
    edge[76] = '\0';
    checkOneLine(edge, 10);
    assert(box.x == 12);
    edge[76] = 'x';
    edge[77] = '\0';
    checkWrapped(edge, 10, 2);
    /* The English UDPBD static-IP note: 976 wide in this font, two lines */
    checkWrapped(@UDPBD@, 10, 2);
    /* The CF notice from the game menu */
    checkWrapped(@PCCF@, 10, 2);
    /* One unbreakable word wider than the screen (a path) breaks between characters and stays inside */
    memset(path, 'p', sizeof(path) - 1);
    path[sizeof(path) - 1] = '\0';
    checkWrapped(path, 10, 0);
    /* A toast that fills its buffer: every word comes through the wrap, none is cut */
    for (i = 0; i < (int)sizeof(toast) - 1; i++)
        toast[i] = (i % 8 == 7) ? ' ' : (char)('a' + i % 8);
    toast[sizeof(toast) - 1] = '\0';
    if (toast[sizeof(toast) - 2] == ' ')
        toast[sizeof(toast) - 2] = 'z';
    checkWrapped(toast, 10, 0);
    snprintf(joined, sizeof(joined), "%s", drawn.text);
    for (i = 0; joined[i]; i++)
        if (joined[i] == '\n')
            joined[i] = ' ';
    assert(!strcmp(joined, toast));
    printf("PASS: notices that fit draw where they did; longer ones wrap inside the screen\n");
    return 0;
}
'''

if render and wrap and toast_size:
    compiler = next((c for c in map(shutil.which, LAYOUT['compilers']) if c), None)
    if compiler is None:
        failures.append('no compiler for the harness (tried %s)' % ', '.join(LAYOUT['compilers']))
    else:
        code = (HARNESS.replace('@WRAP@', wrap).replace('@RENDER@', render)
                .replace('@SCREEN@', LAYOUT['screen']).replace('@TOASTMAX@', toast_size.group(1))
                .replace('@UDPBD@', c_string(english['UDPBD_NEEDS_STATIC_IP']))
                .replace('@PCCF@', c_string(english['PCCF_UNSUPPORTED_GAME'])))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / ('notify' + LAYOUT['ext'])
            binary = path / ('notify.exe' if sys.platform == 'win32' else 'notify')
            source.write_text(code, encoding='utf-8')
            build = subprocess.run([compiler, LAYOUT['std'], '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)],
                                   capture_output=True, text=True)
            if build.returncode != 0:
                failures.append('harness did not compile:\n' + build.stderr)
            else:
                run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if run.returncode != 0:
                    failures.append('harness failed (%d):\n%s%s' % (run.returncode, run.stdout, run.stderr))
                else:
                    print(run.stdout.strip())

# --- 2. every caller moves to the y the renderer returns ----------------------------------------------------------
calls = re.findall(r'^[ \t]*([^\n]*\b%s\([^;{}\n]*\);)' % re.escape(RENDER), notify, re.M)
for call in calls:
    call = call.strip()
    if call == '%s(%s, 10, 0);' % (RENDER, LAYOUT['toast']):
        continue  # the toast is drawn alone
    if not re.fullmatch(r'y = %s\(.+, y, yadd\);' % re.escape(RENDER), call):
        failures.append('%s: a notice that wraps must move the next one down: %s' % (LAYOUT['notify'], call))
if re.search(r'\b%s\([^;]*\);\s*\n\s*y \+= yadd;' % re.escape(RENDER), notify):
    failures.append('%s: y += yadd after a notice ignores the lines it wrapped onto' % LAYOUT['notify'])
if len(calls) < 7 or not any(LAYOUT['ra_line'] in call for call in calls):
    failures.append('%s: expected the partition, config, theme, language, network, toast and RA notices'
                    % LAYOUT['notify'])

# --- 3. the buffers hold the longest translation ------------------------------------------------------------------
languages = {'English': english}
for path in sorted((root / LAYOUT['fork']).glob('*.yml')):
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    languages[path.stem] = data.get('translations') or {}


def longest(ids):
    best = (0, '', '')
    for lang, strings in languages.items():
        for i in ids:
            text = strings.get(i)
            if isinstance(text, str) and len(text.encode('utf-8')) > best[0]:
                best = (len(text.encode('utf-8')), lang, i)
    return best


ra_ids = set()
for path in (root / 'src').rglob(LAYOUT['sources']):
    text = path.read_text(encoding='utf-8', errors='replace')
    for call in re.finditer(r'(?:guiShowRANotice|raNotice)\(([^;]*)\);', text):
        ra_ids.update(re.findall(r'_STR_([A-Z0-9_]+)', call.group(1)))
toast_ids = ['GAME_HIDDEN', 'GAME_UNHIDDEN', 'GAME_DELETED', 'GAME_DELETED_PARTLY', 'FAV_SAVED', 'FAV_REMOVED',
             'FAV_SAVING', 'FAV_SAVE_FAILED', 'FAV_REMOVE_FAILED']
if len(ra_ids) < 10:
    failures.append('only %d RA notice strings found in src; the scan no longer sees the callers' % len(ra_ids))
if ra_size and toast_size and name_max:
    ra_need, ra_lang, ra_label = longest(sorted(ra_ids))
    if ra_need + 1 > int(ra_size.group(1)):
        failures.append('the RA notice lines hold %s bytes; %s %s needs %d' %
                        (ra_size.group(1), ra_lang, ra_label, ra_need + 1))
    template, toast_lang, toast_label = longest(toast_ids)
    # "%s" becomes the game's name, read into a HIDDEN_NAME_MAX buffer; the toast copy needs that plus its NUL
    toast_need = template - 2 + int(name_max.group(1)) - 1 + 1
    if toast_need > int(toast_size.group(1)):
        failures.append('the toast holds %s bytes; %s %s with a %s-byte name needs %d' %
                        (toast_size.group(1), toast_lang, toast_label, int(name_max.group(1)) - 1, toast_need))
    print('buffers: RA notices %s bytes (longest needs %d: %s %s), toasts %s bytes (longest needs %d: %s %s)' %
          (ra_size.group(1), ra_need + 1, ra_lang, ra_label, toast_size.group(1), toast_need, toast_lang, toast_label))

# --- 4. titles and cheat names fit their room ---------------------------------------------------------------------
title = ('fntRenderStringFit(gTheme->fonts[0], 320, 20, ALIGN_CENTER, 600, cfgTitleDisplayName((item_list_t *)'
         'selected_item->item->userdata, selected_item->item->current->item.id, submenuItemGetText(&selected_item->'
         'item->current->item)), gTheme->selTextColor, 1);')
for menu in ('void menuRenderGameMenu(', 'void menuRenderAppMenu('):
    body = ' '.join(function(menusys, menu).split())
    if title not in body:
        failures.append('%s): the title must scroll inside 600' % menu[len('void '):])
    if re.search(r'fntRenderString\(gTheme->fonts\[0\], 320, 20, ALIGN_CENTER, 0, 0,', body):
        failures.append('%s): the title is still drawn with no width' % menu[len('void '):])
cheats = ' '.join(function(cheat_source, LAYOUT['cheats_sig']).split())
if not re.search(r'fntRenderStringFit\(gTheme->fonts\[0\], textX, boxY \+ 3, ALIGN_LEFT, %s - 50 - textX, '
                 r'gCheats\[i\]\.name, textColour, i == \w+\);' % re.escape(LAYOUT['screen']), cheats):
    failures.append('%s: a cheat name must fit to the right-hand rule' % LAYOUT['cheats_sig'])
if re.search(r'fntRenderString\([^;]*gCheats\[i\]\.name', cheats):
    failures.append('%s: a cheat name is still drawn with no width' % LAYOUT['cheats_sig'])

if failures:
    print('menu text fit checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('menu text fit: notices wrap on screen, menu titles scroll, cheat names fit the rule')
