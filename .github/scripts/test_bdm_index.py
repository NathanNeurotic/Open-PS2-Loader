#!/usr/bin/env python3
"""BdmIndex draws one dot per visible mass device (belomaxorka/YAOPL f84b227d).

drawBDMIndex() is compiled on the host against a scripted menu and records the picture it asks for.
It used to pick Index_<slot>, a picture of five dots: two devices showed five dots, devices in slots
0 and 2 gave the first page none, and a lone device in slot 2 still showed "3 of 5". Also checks that
the committed Index<n>_<p> pictures are exactly what tools/make_bdmindex.py draws from Index_0, and
that every build list embeds them.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP = (ROOT / 'src/gfx/themeelems.cpp').exists()
DRAW = ROOT / ('src/gfx/themeelems.cpp' if CPP else 'src/themes.c')
NAMES = ['Index%d_%d' % (n, p) for n in range(2, 5) for p in range(n)]


def function(text, name):
    match = re.search(r'\n[^\n;{}]*\b' + re.escape(name) + r'\([^;{]*\)[^;{\n]*\n\{', text)
    assert match, name
    depth, i = 0, match.end() - 1
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[match.start():i]


def modes():
    text = (ROOT / 'include/iosupport.h').read_text()
    body = re.search(r'enum IO_MODES \{(.*?)\};', text, re.S).group(1)
    body = re.sub(r'//[^\n]*', '', body)
    return 'enum IO_MODES {' + body + '};'


HARNESS = r'''
#include <stdio.h>
#include <string.h>
%(modes)s
typedef struct { int mode; } item_list_t;
struct menu_item { void *userdata; int visible; };
struct menu_list { struct menu_item *item; struct menu_list *prev, *next; };
struct submenu_list;
typedef struct config_set config_set_t;
struct theme_element { int posX, posY, aligned, width, height, scaled; };
typedef struct { void *Mem; } GSTEXTURE;
static struct { int bdmIndexFixed; } theme, *gTheme = &theme;
static int gDefaultCol;
static char drawn[32];
static GSTEXTURE tex = {&tex};
static int texLookupInternalTexId(const char *name) { strcpy(drawn, name); return 0; }
static GSTEXTURE *thmGetTexture(unsigned int id) { return &tex; }
static void rmDrawPixmap(GSTEXTURE *t, int x, int y, int a, int w, int h, int s, int c, int z) { }
%(function)s
int main(int argc, char **argv)
{
    /* argv[1]: one character per menu page: '.' hidden mass device, '#' visible one, 'e' a visible
       network page; argv[2]: the page drawn; argv[3]: 1 for a theme with its own five dots only */
    static item_list_t lists[16];
    static struct menu_item items[16];
    static struct menu_list menu[16];
    int n = (int)strlen(argv[1]), slot = 0;
    for (int i = 0; i < n; i++) {
        lists[i].mode = argv[1][i] == 'e' ? ETH_MODE : slot++;
        items[i].userdata = &lists[i];
        items[i].visible = argv[1][i] != '.';
        menu[i].item = &items[i];
        menu[i].prev = i ? &menu[i - 1] : NULL;
        menu[i].next = i + 1 < n ? &menu[i + 1] : NULL;
    }
    theme.bdmIndexFixed = argv[3][0] == '1';
    struct theme_element elem = {0};
    drawn[0] = 0;
    drawBDMIndex(&menu[argv[2][0] - '0'], NULL, NULL, &elem);
    puts(drawn[0] ? drawn : "-");
    return 0;
}
'''


def compile_draw(temp):
    source = function(DRAW.read_text(), 'drawBDMIndex')
    source = re.sub(r'^(static )?void drawBDMIndex', 'static void drawBDMIndex', source.lstrip('\n'), flags=re.M)
    source = source.replace('static_cast<item_list_t *>(menu->item->userdata)', '(item_list_t *)menu->item->userdata')
    src = temp / 'draw.c'
    src.write_text(HARNESS % {'modes': modes(), 'function': source})
    exe = temp / 'draw'
    cc = shutil.which('gcc') or shutil.which('cc')
    subprocess.run([cc, '-std=gnu99', '-w', '-o', str(exe), str(src)], check=True)
    return exe


CASES = [
    # pages, page drawn, fixed theme, picture
    ('##eee', '0', '0', 'Index2_0'),  # USB in slot 0, UDPBD in slot 1: two dots, not five
    ('##eee', '1', '0', 'Index2_1'),
    ('#.#ee', '0', '0', 'Index2_0'),  # slots 0 and 2: the first page has dots too
    ('#.#ee', '2', '0', 'Index2_1'),
    ('..#ee', '2', '0', '-'),         # one device: no dots, not "3 of 5"
    ('#....', '0', '0', '-'),
    ('###..', '1', '0', 'Index3_1'),
    ('####.', '3', '0', 'Index4_3'),
    ('#####', '4', '0', 'Index_4'),   # five devices: the five-dot picture
    ('#.####', '5', '0', 'Index_4'),  # five devices, the last in slot 5: dot 5 of 5
    ('######', '5', '0', 'Index_5'),  # more devices than dots: by slot, as before
    ('##eee', '1', '1', 'Index_1'),   # a theme with its own five dots only keeps them by slot
    ('#.#ee', '2', '1', 'Index_2'),
    ('##eee', '3', '0', '-'),         # a network page draws no dots
]


def main():
    failures = []
    if shutil.which('gcc') or shutil.which('cc'):
        with tempfile.TemporaryDirectory() as temp:
            exe = compile_draw(Path(temp))
            for pages, page, fixed, want in CASES:
                got = subprocess.run([str(exe), pages, page, fixed], capture_output=True, text=True,
                                     check=True).stdout.strip()
                if got != want:
                    failures.append('%s page %s fixed %s: drew %s, want %s' % (pages, page, fixed, got, want))
    else:
        print('SKIP: no host C compiler for the draw check')

    # The committed pictures are the generator's output, and the generator rebuilds Index_0..Index_4.
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / 'tools').mkdir()
        (temp / 'gfx').mkdir()
        shutil.copy(ROOT / 'tools/make_bdmindex.py', temp / 'tools')
        for p in range(5):
            shutil.copy(ROOT / ('gfx/Index_%d.png' % p), temp / 'gfx')
        run = subprocess.run([sys.executable, '-I', str(temp / 'tools/make_bdmindex.py')], capture_output=True, text=True)
        if run.returncode != 0:
            failures.append('make_bdmindex.py: ' + run.stderr.strip()[-500:])
        else:
            for name in NAMES:
                if (temp / 'gfx' / (name + '.png')).read_bytes() != (ROOT / 'gfx' / (name + '.png')).read_bytes():
                    failures.append('gfx/%s.png is not what tools/make_bdmindex.py draws' % name)

    lists = [ROOT / 'Makefile'] + ([ROOT / 'tools/assets.py'] if CPP else [])
    for path in lists:
        words = set(path.read_text().split())
        for name in NAMES:
            if name not in words:
                failures.append('%s does not embed %s' % (path.name, name))
    table = (ROOT / ('src/gfx/textures.cpp' if CPP else 'src/textures.c')).read_text()
    for name in NAMES:
        if '{%s, "%s", &%s_png},' % (name.upper(), name, name) not in table:
            failures.append('the texture table has no %s' % name)

    for line in failures:
        print('FAIL: ' + line)
    if failures:
        return 1
    print('BdmIndex: one dot per visible mass device, %d cases; pictures and build lists match' % len(CASES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
