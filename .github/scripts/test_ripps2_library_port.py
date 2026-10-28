"""Library features ported from RIPPS2 (akilluminati47/RIPPS2, build 115), group C1.

1. Recents: recentRecord keeps recents.bin newest first, at most RECENT_MAX_ITEMS, one row per game
   (BDM slots count as one device, apps match by title), and never replaces a file it cannot read.
2. Favourites L3 ring: PS2 -> PS1 -> ELF -> All -> Recent -> PS2.
3. Random Game: lands only on games (never a folder row), reaches every game, and reports an empty page.
4. A launch records the game only when something reads recents.bin, right before the handoff.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start) + 3]


fav = (root / 'src/favsupport.c').read_text()
recents = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
#define FAV_TEXT_MAX 256
#define RECENT_MAX_ITEMS 10
enum { BDM_MODE = 0, BDM_MODE_LAST = 7, HDD = 10, APP_MODE = 20 };
typedef struct { int mode, id, icon_id, text_id, kind; char text[FAV_TEXT_MAX]; } fav_raw_t;
static fav_raw_t disk[64];
static int diskCount, favLoadError, unreadable, writes, invalidations;
static void favGetNamedPath(char *out, int size, const char *name)
{
    assert(!strcmp(name, "recents.bin"));
    snprintf(out, size, "mass0:OPL/%s", name);
}
static fav_raw_t *recentReadFile(int *count)
{
    favLoadError = unreadable;
    *count = diskCount;
    if (diskCount == 0)
        return NULL;
    fav_raw_t *p = calloc(diskCount, sizeof(fav_raw_t));
    memcpy(p, disk, diskCount * sizeof(fav_raw_t));
    return p;
}
static u8 *favBuildImage(const fav_raw_t *recs, int count, int *len)
{
    assert(count <= RECENT_MAX_ITEMS);
    *len = count * (int)sizeof(fav_raw_t);
    u8 *img = malloc(*len + 1);
    memcpy(img, recs, *len);
    return img;
}
static int favWriteWhole(const char *path, const u8 *buf, int len)
{
    assert(!strcmp(path, "mass0:OPL/recents.bin"));
    writes++;
    diskCount = len / (int)sizeof(fav_raw_t);
    memcpy(disk, buf, len);
    return 1;
}
static void recentInvalidate(void) { invalidations++; }
''' + function(fav, 'static int favModesMatch(') + \
    function(fav, 'int recentRecord(') + r'''
static const char *order(void)
{
    static char s[512];
    s[0] = 0;
    for (int i = 0; i < diskCount; i++) {
        strcat(s, disk[i].text);
        strcat(s, " ");
    }
    return s;
}
int main(void)
{
    assert(recentRecord(HDD, 3, 0, 0, "A", 0) && recentRecord(BDM_MODE + 1, 4, 0, 0, "B", 0) && recentRecord(HDD, 5, 0, 0, "C", 0));
    assert(!strcmp(order(), "C B A ") && invalidations == 3);
    assert(recentRecord(HDD, 8, 0, 0, "A", 0) && !strcmp(order(), "A C B "));          /* replayed (id moved): to the front */
    assert(recentRecord(HDD, 3, 0, 0, "A", 1) && !strcmp(order(), "A A C B "));        /* PS1 kind is another game */
    assert(recentRecord(BDM_MODE + 2, 9, 0, 0, "B", 0) && !strcmp(order(), "B A A C ")); /* BDM slots: one device */
    assert(recentRecord(HDD + 1, 9, 0, 0, "B", 0) && !strcmp(order(), "B B A A C "));  /* another device: its own row */
    assert(disk[1].mode == BDM_MODE + 2 && disk[1].id == 9);                            /* the newest launch is kept */
    assert(recentRecord(APP_MODE, 1, 0, 0, "App", 3) && recentRecord(APP_MODE, 7, 0, 0, "App", 3));
    assert(!strcmp(order(), "App B B A A C "));                                         /* apps match by title */
    char name[8];
    for (int i = 0; i < 12; i++) {
        snprintf(name, sizeof(name), "G%d", i);
        assert(recentRecord(HDD, i, 0, 0, name, 0));
    }
    assert(diskCount == RECENT_MAX_ITEMS && !strcmp(disk[0].text, "G11") && !strcmp(disk[9].text, "G2"));
    int before = writes;
    assert(!recentRecord(1, 1, 0, 0, "", 0) && writes == before);   /* nothing to record */
    assert(!recentRecord(1, 1, 0, 0, NULL, 0) && writes == before);
    unreadable = 1;
    assert(!recentRecord(1, 1, 0, 0, "X", 0) && writes == before);  /* unreadable file is kept */
    return 0;
}
'''

menusys = (root / 'src/menusys.c').read_text()
random_game = r'''
#include <assert.h>
#include <stdlib.h>
#include <time.h>
struct submenu_item { int isFolder; int id; };
typedef struct submenu_list { struct submenu_item item; struct submenu_list *prev, *next; } submenu_list_t;
typedef struct { int visible; submenu_list_t *submenu, *current, *pagestart; } menu_item_t;
typedef struct { menu_item_t *item; } menu_list_t;
static menu_list_t *selected_item;
''' + function(menusys, 'static int menuRandomGame(void)') + r'''
int main(void)
{
    submenu_list_t rows[8] = {0};
    for (int i = 0; i < 8; i++) {
        rows[i].item.id = i;
        rows[i].item.isFolder = i < 2; /* two folder rows first, as folder browsing emits them */
        rows[i].prev = i ? &rows[i - 1] : NULL;
        rows[i].next = i < 7 ? &rows[i + 1] : NULL;
    }
    menu_item_t page = {1, &rows[0], &rows[0], &rows[0]};
    menu_list_t list = {&page};
    assert(!menuRandomGame()); /* no page yet */
    selected_item = &list;
    int seen[8] = {0};
    for (int i = 0; i < 600; i++) {
        assert(menuRandomGame() && page.current && page.current == page.pagestart && !page.current->item.isFolder);
        seen[page.current->item.id]++;
    }
    for (int i = 2; i < 8; i++)
        assert(seen[i] > 0); /* every game can come up */
    for (int i = 2; i < 8; i++)
        rows[i].item.isFolder = 1;
    page.current = &rows[0];
    assert(!menuRandomGame() && page.current == &rows[0]); /* only folders: nothing picked */
    page.submenu = NULL;
    assert(!menuRandomGame());
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='ripps2-library-') as temp:
    for name, program in (('recents', recents), ('random', random_game)):
        src = Path(temp) / (name + '.c')
        src.write_text(program)
        exe = Path(temp) / (name + '.exe')
        subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
print('ok   recents.bin: newest first, last 10, one row per game, unreadable file kept')
assert 'guiLock(); // the IO worker replaces a device\'s list under this lock; the pick walks it twice\n            int picked = menuRandomGame();\n            guiUnlock();' in menusys, 'Random Game picks under guiLock'
print('ok   Random Game: games only, every game reachable, empty page reported')

libview = (root / 'src/libview.c').read_text()
ring = libview[libview.index('if (mode == FAV_MODE) {\n        // Explicit order'):]
ring = ring[:ring.index('} else if (mode == APP_MODE)')]
stops = re.findall(r'\(cur == (LIB_VIEW_\w+)\) \? (LIB_VIEW_\w+)', ring)
assert stops == [('LIB_VIEW_ISO', 'LIB_VIEW_PS1'), ('LIB_VIEW_PS1', 'LIB_VIEW_ELF'), ('LIB_VIEW_ELF', 'LIB_VIEW_ALL'),
                 ('LIB_VIEW_ALL', 'LIB_VIEW_RECENT')], stops
assert re.search(r'if \(mode == FAV_MODE\)\n\s*return gAllGames \? 6 : 5;', libview), 'Favourites ring must have five stops'
print('ok   Favourites L3: PS2 -> PS1 -> ELF -> All -> Recent')

opl = (root / 'src/opl.c').read_text()
record = function(opl, 'static void itemRecordRecent(')
assert 'if (!gFAVStartMode && !gAllGames && gAutosort != AUTOSORT_LAST_PLAYED)\n        return;' in record
assert 'curMenu->current->item.id != launchId' in record, 'record only the row being launched'
select = function(opl, 'static void itemExecSelect(')
call = 'itemRecordRecent(support, curMenu, launchId);\n                '
assert select.index('itemRecordRecent(') + len(call) == select.index('support->itemLaunch(support, launchId, configSet);')
assert 'libViewActive(FAV_MODE) == LIB_VIEW_RECENT' in function(opl, 'static void updateMenuFromGameList('), \
    'the Recent stop must keep play order'
print('ok   launches record recents only when Favourites or Sort Games: Last played use them')
