"""Hide Game and Delete everything, ported from RIPPS2 (akilluminati47/RIPPS2, build 114), group D.

1. hidden.txt: one list per device in its prefix, "0|1<tab>name"; bare names are PS2 games and '#'
   lines are comments. Hiding and showing again round-trip through the file, an empty list removes
   it, and a list that cannot be written changes nothing in memory.
2. Rows: a device row, a Favourites/All Games row (by its source), a folder row and an app.
3. Delete everything: the CFG, art (any letter case, PNG/JPG/JPEG, OPL Manager names) and cheats of
   the game go; another game's files and VMC saves stay; a second copy on the page keeps them all.
4. Wiring: hidden rows leave the page build and the All Games gather; the delete asks twice.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
header = (root / 'include/gamemanage.h').read_text()
source = (root / 'src/gamemanage.c').read_text()
body = source[source.index('int gShowHidden;'):]

program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <strings.h>
#include <sys/stat.h>
enum { HDD_MODE = 0, ETH_MODE, APP_MODE, FAV_MODE, HTTP_MODE, MMCE_MODE, MODE_COUNT };
enum { LIB_VIEW_ISO = 0, LIB_VIEW_PS1, LIB_VIEW_ELF };
enum { FAV_KIND_ISO = 0, FAV_KIND_VCD, FAV_KIND_CUE, FAV_KIND_ELF };
enum { GAME_FORMAT_ISO = 1, GAME_FORMAT_FOLDER = 3 };
#define IO_MENU_UPDATE_DEFFERED 2
typedef struct { int init_count, max_count, option, attr; } ee_sema_t;
static int CreateSema(ee_sema_t *s) { (void)s; return 1; }
static int semaDepth;
static void WaitSema(int s) { (void)s; assert(semaDepth++ == 0); }
static void SignalSema(int s) { (void)s; assert(--semaDepth == 0); }
typedef struct { char name[64]; char startup[16]; int format, parts; } base_game_info_t;
typedef struct item_list item_list_t;
struct item_list {
    short mode;
    int enabled;
    char *(*itemGetPrefix)(item_list_t *);
    char *(*itemGetName)(item_list_t *, int);
    void *(*itemGet)(item_list_t *, int);
    int (*itemGetView)(item_list_t *, int);
    void (*itemDelete)(item_list_t *, int);
    int (*itemGetCount)(item_list_t *);
    char *(*itemGetStartup)(item_list_t *, int);
};
typedef struct { item_list_t *support; } opl_io_module_t;
static opl_io_module_t modules[MODE_COUNT];
static opl_io_module_t *oplGetModule(int mode) { return &modules[mode]; }
static int gFAVStartMode = 1, gAllGames, dirtyMarks, queued, favLoads, pageView;
static int favKind[8], favMode[8];
static int favGetItemKind(int id) { return favKind[id]; }
static int favGetItemSourceMode(int id) { return favMode[id]; }
static int favKindView(int kind) { return kind == FAV_KIND_ELF ? LIB_VIEW_ELF : kind == FAV_KIND_ISO ? LIB_VIEW_ISO : LIB_VIEW_PS1; }
static int libViewActive(int mode) { (void)mode; return pageView; }
static int folderModeSupported(int mode) { return mode == MMCE_MODE; }
static void libViewMarkDirty(int mode) { (void)mode; dirtyMarks++; }
static int ioPutRequest(int type, void *data) { assert(type == IO_MENU_UPDATE_DEFFERED && data != NULL); queued++; return 0; }
static void loadFavourites(void) { favLoads++; }
''' + header + body + r'''
static char prefix[64] = "dev/";
static base_game_info_t games[3];
static const char *names[3] = {"Alpha", "Beta", "Gamma"};
static char *getPrefix(item_list_t *l) { (void)l; return prefix; }
static char *getName(item_list_t *l, int id) { (void)l; return (char *)names[id]; }
static void *getGame(item_list_t *l, int id) { (void)l; return &games[id]; }
static int getCount(item_list_t *l) { (void)l; return 3; }
static char *getStartup(item_list_t *l, int id) { (void)l; return games[id].startup; }
static void deleteGame(item_list_t *l, int id) { (void)l; (void)id; }
static void put(const char *path) { FILE *f = fopen(path, "w"); assert(f); fputs("x", f); fclose(f); }
static int exists(const char *path) { return access(path, F_OK) == 0; }
static char *slurp(const char *path) { static char buf[512]; FILE *f = fopen(path, "r"); size_t n = f ? fread(buf, 1, sizeof(buf) - 1, f) : 0; if (f) fclose(f); buf[n] = 0; return buf; }
static int planned(const gm_delete_plan_t *p, const char *path) { for (int i = 0; i < p->count; i++) if (!strcmp(p->files[i].path, path)) return 1; return 0; }

int main(void)
{
    item_list_t dev = {MMCE_MODE, 1, getPrefix, getName, getGame, NULL, deleteGame, getCount, getStartup};
    item_list_t fav = {FAV_MODE, 1, NULL, getName, NULL, NULL, NULL, NULL, NULL};
    item_list_t app = {APP_MODE, 1, getPrefix, getName, NULL, NULL, NULL, NULL, NULL};
    modules[MMCE_MODE].support = &dev;
    hiddenInit();
    mkdir("dev", 0777);

    /* 1. the file */
    FILE *f = fopen("dev/hidden.txt", "w");
    fputs("# kept by hand\n0\tAlpha\r\n1\tBeta\nGamma\n", f);
    fclose(f);
    hiddenReload(MMCE_MODE);
    assert(hiddenHas(MMCE_MODE, 0, "Alpha") && hiddenHas(MMCE_MODE, 1, "Beta") && hiddenHas(MMCE_MODE, 0, "Gamma"));
    assert(!hiddenHas(MMCE_MODE, 1, "Alpha") && !hiddenHas(MMCE_MODE, 0, "Beta")); /* PS2 and PS1 are separate */
    assert(hiddenHas(HTTP_MODE, 0, "Alpha") == 0 && hiddenSet(HTTP_MODE, 0, "Alpha", 1) == -1); /* no list there */
    assert(hiddenSet(MMCE_MODE, 0, "Gamma", 0) == 1 && !hiddenHas(MMCE_MODE, 0, "Gamma"));
    assert(!strcmp(slurp("dev/hidden.txt"), "0\tAlpha\n1\tBeta\n"));
    assert(dirtyMarks == 1 && queued == 1 && favLoads == 1); /* its page and Favourites are rebuilt */
    assert(hiddenSet(MMCE_MODE, 0, "Delta", 1) == 1 && !strcmp(slurp("dev/hidden.txt"), "0\tAlpha\n1\tBeta\n0\tDelta\n"));
    assert(hiddenSet(MMCE_MODE, 0, "Delta", 1) == 1 && !strcmp(slurp("dev/hidden.txt"), "0\tAlpha\n1\tBeta\n0\tDelta\n"));
    assert(hiddenSet(MMCE_MODE, 0, "Alpha", 0) == 1 && hiddenSet(MMCE_MODE, 1, "Beta", 0) == 1 && hiddenSet(MMCE_MODE, 0, "Delta", 0) == 1);
    assert(!exists("dev/hidden.txt")); /* an empty list leaves no file behind */
    hiddenReload(MMCE_MODE);
    assert(!hiddenHas(MMCE_MODE, 0, "Alpha"));
    snprintf(prefix, sizeof(prefix), "missing/");                 /* a list that cannot be written */
    assert(hiddenSet(MMCE_MODE, 0, "Alpha", 1) == 0 && !hiddenHas(MMCE_MODE, 0, "Alpha"));
    snprintf(prefix, sizeof(prefix), "dev/");
    assert(hiddenSet(MMCE_MODE, 0, "Alpha", 1) == 1);

    /* 2. rows */
    int mode, ps1;
    const char *name;
    games[0].format = games[1].format = games[2].format = GAME_FORMAT_ISO;
    pageView = LIB_VIEW_ISO;
    assert(hiddenRow(&dev, 0) && !hiddenRow(&dev, 1));
    pageView = LIB_VIEW_PS1;
    assert(!hiddenRow(&dev, 0)); /* the same name in the PS1 view is another game */
    pageView = LIB_VIEW_ISO;
    games[0].format = GAME_FORMAT_FOLDER;
    assert(!hiddenRowSource(&dev, 0, &mode, &ps1, &name)); /* a folder row is never hidden */
    games[0].format = GAME_FORMAT_ISO;
    favKind[0] = FAV_KIND_ISO, favMode[0] = MMCE_MODE;
    favKind[1] = FAV_KIND_VCD, favMode[1] = MMCE_MODE;
    favKind[2] = FAV_KIND_ELF, favMode[2] = APP_MODE;
    assert(hiddenRowSource(&fav, 0, &mode, &ps1, &name) && mode == MMCE_MODE && ps1 == 0 && hiddenRow(&fav, 0));
    assert(hiddenRowSource(&fav, 1, &mode, &ps1, &name) && ps1 == 1 && !hiddenRow(&fav, 1));
    assert(!hiddenRowSource(&fav, 2, &mode, &ps1, &name) && !hiddenRowSource(&app, 0, &mode, &ps1, &name));

    /* 3. delete everything */
    strcpy(games[0].startup, "SLUS_123.45"), games[0].parts = 2;
    strcpy(games[1].startup, "SLES_555.55"), games[1].parts = 1;
    strcpy(games[2].startup, "SCUS_999.99"), games[2].parts = 1;
    mkdir("dev/CFG", 0777), mkdir("dev/ART", 0777), mkdir("dev/CHT", 0777), mkdir("dev/VMC", 0777);
    put("dev/CFG/SLUS_123.45.cfg"), put("dev/CFG/SLES_555.55.cfg");
    put("dev/ART/SLUS_123.45_COV.png"), put("dev/ART/slus_123.45_bg_00.JPG"), put("dev/ART/SLUS_123.45_SCR.jpeg");
    put("dev/ART/SLUS_123.45_COV.txt"), put("dev/ART/SLUS_123.456_COV.png"), put("dev/ART/SLES_555.55_COV.png");
    put("dev/CHT/SLUS_123.45.CHT"), put("dev/VMC/SLUS_123.45_0.bin");
    gm_delete_plan_t plan;
    assert(gmPlanDelete(&dev, 0, &plan) && plan.parts == 2 && !plan.shared);
    assert(plan.cfg == 1 && plan.art == 3 && plan.cht == 1 && plan.count == 5);
    assert(planned(&plan, "dev/CFG/SLUS_123.45.cfg") && planned(&plan, "dev/ART/slus_123.45_bg_00.JPG") && planned(&plan, "dev/CHT/SLUS_123.45.CHT"));
    assert(!planned(&plan, "dev/ART/SLUS_123.45_COV.txt") && !planned(&plan, "dev/ART/SLUS_123.456_COV.png"));
    assert(gmDeleteExtras(&plan) == 0 && gmDeleteExtras(&plan) == 5); /* already gone: each one counts */
    assert(!exists("dev/CFG/SLUS_123.45.cfg") && !exists("dev/ART/SLUS_123.45_COV.png") && !exists("dev/CHT/SLUS_123.45.CHT"));
    assert(exists("dev/VMC/SLUS_123.45_0.bin") && exists("dev/CFG/SLES_555.55.cfg") && exists("dev/ART/SLES_555.55_COV.png"));
    strcpy(games[2].startup, "SLES_555.55");                       /* a second copy of Beta */
    assert(gmPlanDelete(&dev, 1, &plan) && plan.shared && plan.count == 0);
    games[1].format = GAME_FORMAT_FOLDER;
    assert(!gmPlanDelete(&dev, 1, &plan));
    dev.mode = HDD_MODE;
    assert(!gmPlanDelete(&dev, 2, &plan));                            /* no partition delete */
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='ripps2-manage-') as temp:
    src = Path(temp) / 'manage.c'
    src.write_text(program)
    exe = Path(temp) / 'manage.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-fsanitize=address,undefined',
                    str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=temp, check=True)
print('ok   hidden.txt: per device, PS2/PS1 apart, round trip, empty list removed, failed write changes nothing')
print('ok   rows: device, Favourites/All Games by source, folders and apps never hidden')
print('ok   delete everything: CFG, art (any case) and cheats go; saves, other games and shared copies stay')

opl = (root / 'src/opl.c').read_text()
build = opl[opl.index('static void updateMenuFromGameList('):]
build = build[:build.index('\n}\n')]
assert build.index('itemUpdate(mdl->support);') < build.index('hiddenReload(mdl->support->mode);')
assert 'if (!isFolderRow && !gShowHidden && hiddenRow(mdl->support, i))\n                    continue;' in build
assert build.index('hiddenRow(mdl->support, i)') < build.index('gup = guiOpCreate(GUI_OP_APPEND_MENU);')
fav = (root / 'src/favsupport.c').read_text()
gather = fav[fav.index('static int favGatherAdd('):]
gather = gather[:gather.index('\n}\n')]
assert gather.index('hiddenHas(owner->mode') < gather.index('if (out == NULL)'), 'a hidden game must not be counted either'
menu = (root / 'src/menusys.c').read_text()
everything = menu[menu.index('static int menuDeleteEverything('):]
everything = everything[:everything.index('\n}\n')]
assert everything.count('guiMsgBox(msg, 1, NULL) != 1') == 2, 'the delete asks twice'
assert everything.index('_STR_DELETE_GAME_LAST_CHECK') < everything.index('support->itemDelete(support, id);') < everything.index('gmDeleteExtras(plan)')
assert 'for (part = 0; part < game.parts && !partLeft; part++)' in everything and everything.index('if (partLeft) {') < everything.index('gmDeleteExtras(plan)'), 'every part is gone before the extras go'
assert 'gEnableWrite' in menu[menu.index('static int menuHiddenState('):menu.index('static void menuHideGame(')]
# The list can be rebuilt while a dialog is up: each write checks the row is still the same game first.
assert everything.index('_STR_DELETE_GAME_LAST_CHECK') < everything.rindex('menuRowBeginEdit(row)') < everything.index('support->itemDelete(support, id);')
deleteGame = menu[menu.index('static void menuDeleteGame('):]
deleteGame = deleteGame[:deleteGame.index('\n}\n')]
assert deleteGame.index('menuDeleteEverything(submenu, &row)') < deleteGame.index('_STR_DELETE_WARNING') < deleteGame.index('menuRowBeginEdit(&row)') < deleteGame.index('itemDelete(support, row.id)')
rename = menu[menu.index('static void menuRenameGame('):]
rename = rename[:rename.index('\n}\n')]
assert rename.index('guiShowKeyboard(') < rename.rindex('menuRowBeginEdit(&row)') < rename.index('itemRename(support, row.id, newName)')
hide = menu[menu.index('static void menuHideGame('):menu.index('static int menuDeleteEverything(')]
assert 'selected_item' not in rename + deleteGame + everything + hide, 'the actions work from their copy of the row'
print('ok   wiring: hidden rows leave the page and the All Games gather; delete asks twice, parts first')
