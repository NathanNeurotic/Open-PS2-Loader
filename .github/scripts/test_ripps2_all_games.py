"""All Games list ported from RIPPS2 (akilluminati47/RIPPS2, builds 114-116), group C2.

1. Gathering: every started source's PS2 rows, PS1 rows (core from the row) and apps, folders and
   share pickers skipped, a source that has not started left out, and each shelf on its own.
2. A title on two sources is listed twice, each tagged with its source; a lone title is not tagged.
3. Stars: a row is starred when favourites.bin holds it (BDM slots lenient, apps by title).
4. R3 on an All Games row adds or removes the favourite and flips the star only when saved.
5. L3 ring: All -> PS2 -> PS1 -> APP -> Favourites -> Recent; device pages read both lists.
6. Tabs: a started device or Apps page steps aside, a Manual one and a share picker stay.
7. Turning All Games off: a Favourites page left hidden sends the user to the startup page; a
   device tab that hides for a poll keeps the user (#806).
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
fav = (root / 'src/favsupport.c').read_text()


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start) + 3]


block = fav[fav.index('static const int favAllGamesModes[]'):fav.index('item_list_t *favGetObject(int initOnly)')]

program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
#define FAV_TEXT_MAX 256
enum { BDM_MODE = 0, BDM_MODE1, BDM_MODE2, BDM_MODE3, BDM_MODE4, BDM_MODE5, BDM_MODE6, BDM_MODE7,
       ETH_MODE, HDD_MODE, APP_MODE, MMCE_MODE, FAV_MODE, UDPFS_MODE, HTTP_MODE, MODE_COUNT };
#define BDM_MODE_LAST BDM_MODE7
enum { LIB_VIEW_ISO = 0, LIB_VIEW_PS1, LIB_VIEW_ELF, LIB_VIEW_ALL };
enum { FAV_KIND_ISO = 0, FAV_KIND_VCD, FAV_KIND_CUE, FAV_KIND_ELF };
static int gShowHidden;
static int hiddenHas(int mode, int ps1, const char *name) { (void)mode; (void)ps1; return !gShowHidden && (!strcmp(name, "Hidden") || (mode == ETH_MODE && !strcmp(name, "Rez"))); }
#define ITEM_VIEW_FORCE_ISO 1
#define ITEM_VIEW_FORCE_PS1 2
#define GAME_FORMAT_FOLDER 9
#define START_MODE_DISABLED 0
typedef struct { char name[64]; int format; int cue; } base_game_info_t;
typedef struct item_list item_list_t;
struct item_list {
    int mode, enabled, viewOverride;
    int (*itemGetCount)(item_list_t *);
    char *(*itemGetName)(item_list_t *, int);
    void *(*itemGet)(item_list_t *, int);
    int (*itemTextId)(item_list_t *);
    void *itemLaunchVcd, *itemLaunchCue;
    base_game_info_t iso[8], ps1[8];
    int isoCount, ps1Count;
};
typedef struct { item_list_t *support; struct { int visible; } menuItem; } opl_io_module_t;
typedef struct { item_list_t *owner; int mode, id, icon_id, text_id, kind; char *text, *display; int starred; } fav_rec_t;
typedef struct { int mode, id, icon_id, text_id, kind; char text[FAV_TEXT_MAX]; } fav_raw_t;

static fav_rec_t *favArray;
static int favCount, gAPPStartMode = 1, armed, adds, removes, saveOk = 1;
static char gPCShareName[32] = "games";
static item_list_t *modules[MODE_COUNT];
static opl_io_module_t mods[MODE_COUNT];
static int gone[MODE_COUNT]; /* the page is hidden: device removed or its start mode switched Off */
static opl_io_module_t *oplGetModule(int m) { mods[m].support = modules[m]; mods[m].menuItem.visible = !gone[m]; return &mods[m]; }
static int folderModeSupported(int mode) { return mode != HTTP_MODE; }
static int cueIsCueEntry(const base_game_info_t *g) { return g->cue; }
static const char *labels[] = {"USB Games", "HDD Games", "Apps", "SMB Games"};
static const char *_l(int id) { return labels[id]; }
static void favArmAppsScan(void) { armed++; }
static char *favStrdup(const char *s) { char *p = malloc(strlen(s) + 1); strcpy(p, s); return p; }
static int favValidIndex(int id) { return favArray != NULL && id >= 0 && id < favCount; }
static int favSupportLaunches(const item_list_t *s, int needCue) { return needCue ? s->itemLaunchCue != NULL : s->itemLaunchVcd != NULL; }
static int listCount(item_list_t *l) { return l->viewOverride == ITEM_VIEW_FORCE_PS1 ? l->ps1Count : l->isoCount; }
static base_game_info_t *row(item_list_t *l, int i) { return l->viewOverride == ITEM_VIEW_FORCE_PS1 ? &l->ps1[i] : &l->iso[i]; }
static char *listName(item_list_t *l, int i) { return row(l, i)->name; }
static void *listGet(item_list_t *l, int i) { return row(l, i); }
static int textUsb(item_list_t *l) { (void)l; return 0; }
static int textHdd(item_list_t *l) { (void)l; return 1; }
static int textApps(item_list_t *l) { (void)l; return 2; }
static int textSmb(item_list_t *l) { (void)l; return 3; }
static int favResolveStoredId(item_list_t *s, int id, const char *text, int kind, int *out)
{
    item_list_t v = *s;
    (void)kind;
    v.viewOverride = ITEM_VIEW_FORCE_ISO;
    if (id < 0 || id >= listCount(&v) || strcmp(listName(&v, id), text) != 0)
        return 0;
    *out = id;
    return 1;
}
static int addFavouriteItem(int mode, int id, int icon, int tid, const char *text, int kind)
{ (void)mode; (void)id; (void)icon; (void)tid; (void)text; (void)kind; adds++; return saveOk; }
static int removeFavouriteByIdAndText(int mode, int id, const char *text, int kind)
{ (void)mode; (void)id; (void)text; (void)kind; removes++; return saveOk; }
''' + function(fav, 'int favKindView(') + function(fav, 'static int favKindIsNameAddressed(') + \
    function(fav, 'static int favIdsMatchForMode(') + function(fav, 'static int favModesMatch(') + block + r'''
static item_list_t usb, hdd, apps, smb, mmce;
static void game(item_list_t *l, int ps1, const char *name, int format, int cue)
{
    base_game_info_t *g = ps1 ? &l->ps1[l->ps1Count++] : &l->iso[l->isoCount++];
    snprintf(g->name, sizeof(g->name), "%s", name);
    g->format = format;
    g->cue = cue;
}
static void setup(item_list_t *l, int mode, int (*text)(item_list_t *))
{
    l->mode = mode;
    l->enabled = 1;
    l->itemGetCount = listCount;
    l->itemGetName = listName;
    l->itemGet = listGet;
    l->itemTextId = text;
    modules[mode] = l;
}
static int find(const char *display, int kind)
{
    for (int i = 0; i < favCount; i++)
        if (!strcmp(favGetItemDisplay(i), display) && favArray[i].kind == kind)
            return i;
    return -1;
}
static void freeArray(void)
{
    for (int i = 0; i < favCount; i++) { free(favArray[i].text); free(favArray[i].display); }
    free(favArray);
    favArray = NULL;
    favCount = 0;
}
int main(void)
{
    setup(&usb, BDM_MODE, textUsb);
    usb.itemLaunchVcd = usb.itemLaunchCue = (void *)1;
    game(&usb, 0, "Ico", 0, 0);
    game(&usb, 0, "Saves", GAME_FORMAT_FOLDER, 0);
    game(&usb, 0, "Okami", 0, 0);
    game(&usb, 0, "Rez", 0, 0);
    game(&usb, 1, "SLUS_000.01.Crash", 0, 0);
    game(&usb, 1, "Spyro", 0, 1);
    setup(&hdd, HDD_MODE, textHdd);
    hdd.itemLaunchVcd = (void *)1; /* POPSTARTER only: an Ember row cannot launch here */
    game(&hdd, 0, "Ico", 0, 0);
    game(&hdd, 0, "Hidden", 0, 0); /* hidden: never gathered */
    game(&hdd, 1, "Spyro", 0, 1);
    game(&hdd, 1, "Tekken", 0, 0);
    setup(&apps, APP_MODE, textApps);
    game(&apps, 0, "uLE", 0, 0);
    setup(&smb, ETH_MODE, textSmb);
    game(&smb, 0, "Okami", 0, 0);
    game(&smb, 0, "Rez", 0, 0); /* hidden here: never gathered, and tags no other copy */
    setup(&mmce, MMCE_MODE, textUsb);
    mmce.enabled = 0; /* on Manual and not started */
    game(&mmce, 0, "Shadow", 0, 0);

    fav_raw_t favs[3] = {{BDM_MODE3, 2, 0, 0, FAV_KIND_ISO, "Okami"}, {APP_MODE, 99, 0, 0, FAV_KIND_ELF, "uLE"},
                         {HDD_MODE, 0, 0, 0, FAV_KIND_CUE, "Spyro"}};
    assert(favGatherAllGames(LIB_VIEW_ALL, favs, 3) == 9);
    assert(find("Hidden", FAV_KIND_ISO) < 0 && find("Hidden (HDD Games)", FAV_KIND_ISO) < 0);
    assert(find("Rez", FAV_KIND_ISO) >= 0 && find("Rez (USB Games)", FAV_KIND_ISO) < 0); /* the hidden copy tags nothing */
    assert(find("Ico (USB Games)", FAV_KIND_ISO) >= 0 && find("Ico (HDD Games)", FAV_KIND_ISO) >= 0);
    assert(find("Okami (USB Games)", FAV_KIND_ISO) >= 0 && find("Okami (SMB Games)", FAV_KIND_ISO) >= 0);
    assert(find("Saves", FAV_KIND_ISO) < 0 && find("Shadow", FAV_KIND_ISO) < 0); /* folder, unstarted source */
    assert(find("SLUS_000.01.Crash", FAV_KIND_VCD) >= 0 && find("Tekken", FAV_KIND_VCD) >= 0); /* lone titles: untagged */
    assert(find("Spyro", FAV_KIND_CUE) >= 0 && favArray[find("Spyro", FAV_KIND_CUE)].owner == &usb); /* HDD cannot run Ember */
    assert(find("uLE", FAV_KIND_ELF) >= 0);
    /* stars: Okami on USB (BDM slot moved), the app by title; not the SMB copy, not the HDD-recorded CUE */
    assert(favArray[find("Okami (USB Games)", FAV_KIND_ISO)].starred && !favArray[find("Okami (SMB Games)", FAV_KIND_ISO)].starred);
    assert(favArray[find("uLE", FAV_KIND_ELF)].starred && !favArray[find("Spyro", FAV_KIND_CUE)].starred);
    assert(favArray[find("Okami (USB Games)", FAV_KIND_ISO)].id == 2); /* the source's own id, folder included */

    /* R3: remove a star, add one, and keep the star when the save fails */
    int okami = find("Okami (USB Games)", FAV_KIND_ISO), ico = find("Ico (HDD Games)", FAV_KIND_ISO);
    assert(favToggleByIndex(okami) == 0 && removes == 1 && !favArray[okami].starred);
    assert(favToggleByIndex(ico) == 1 && adds == 1 && favArray[ico].starred);
    saveOk = 0;
    assert(favToggleByIndex(ico) == -1 && favArray[ico].starred);
    assert(favToggleByIndex(-1) == -1 && favToggleByIndex(favCount) == -1);
    freeArray();

    /* shelves */
    assert(favGatherAllGames(LIB_VIEW_ISO, NULL, 0) == 5 && find("uLE", FAV_KIND_ELF) < 0);
    freeArray();
    assert(favGatherAllGames(LIB_VIEW_PS1, NULL, 0) == 3);
    freeArray();
    assert(favGatherAllGames(LIB_VIEW_ELF, NULL, 0) == 1);
    freeArray();
    gPCShareName[0] = 0; /* the share picker lists shares, not games */
    assert(favGatherAllGames(LIB_VIEW_ISO, NULL, 0) == 4 && find("Okami", FAV_KIND_ISO) >= 0);
    freeArray();
    apps.enabled = 0;
    assert(favGatherAllGames(LIB_VIEW_ALL, NULL, 0) == 7 && armed > 0); /* apps on Manual: scan armed (no SMB share) */
    freeArray();
    gone[BDM_MODE] = 1; /* the stick is pulled: its rows leave with its tab, though the list is kept */
    assert(favGatherAllGames(LIB_VIEW_ISO, NULL, 0) == 1 && find("Ico", FAV_KIND_ISO) >= 0 && find("Ico (USB Games)", FAV_KIND_ISO) < 0);
    freeArray();
    gone[BDM_MODE] = 0;
    usb.enabled = hdd.enabled = smb.enabled = 0;
    assert(favGatherAllGames(LIB_VIEW_ALL, NULL, 0) == 0 && favArray == NULL);
    return 0;
}
'''

menusys = (root / 'src/menusys.c').read_text()
tabs = r'''
#include <assert.h>
#include <stddef.h>
enum { BDM_MODE = 0, BDM_MODE7 = 7, ETH_MODE, HDD_MODE, APP_MODE, MMCE_MODE, FAV_MODE, UDPFS_MODE, HTTP_MODE };
#define BDM_MODE_LAST BDM_MODE7
typedef struct { int mode, enabled; } item_list_t;
typedef struct menu_item { int visible; void *userdata; } menu_item_t;
static int gAllGames;
static char gPCShareName[32];
''' + function(menusys, 'int menuItemShown(const menu_item_t *item)') + r'''
int main(void)
{
    item_list_t usb = {BDM_MODE + 2, 1}, hdd = {HDD_MODE, 1}, eth = {ETH_MODE, 1}, apps = {APP_MODE, 1}, fav = {FAV_MODE, 1}, manual = {MMCE_MODE, 0},
                manualApps = {APP_MODE, 0};
    menu_item_t tUsb = {1, &usb}, tHdd = {1, &hdd}, tEth = {1, &eth}, tApps = {1, &apps}, tFav = {1, &fav}, tManual = {1, &manual}, gone = {0, &fav},
                tManualApps = {1, &manualApps};
    assert(menuItemShown(&tUsb) && menuItemShown(&tHdd) && menuItemShown(&tApps) && !menuItemShown(&gone) && !menuItemShown(NULL));
    gAllGames = 1;
    assert(!menuItemShown(&tUsb) && !menuItemShown(&tHdd));       /* started devices step aside */
    assert(!menuItemShown(&tApps));                                /* started apps are on the list too */
    assert(menuItemShown(&tFav) && menuItemShown(&tManual) && menuItemShown(&tManualApps));
    assert(menuItemShown(&tEth));                                  /* share picker stays */
    gPCShareName[0] = 'g';
    assert(!menuItemShown(&tEth) && !menuItemShown(&gone));
    gAllGames = 0;                                                 /* switched off: every tab is back */
    assert(menuItemShown(&tUsb) && menuItemShown(&tHdd) && menuItemShown(&tApps) && menuItemShown(&tEth));
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='ripps2-allgames-') as temp:
    for name, source in (('gather', program), ('tabs', tabs)):
        src = Path(temp) / (name + '.c')
        src.write_text(source)
        exe = Path(temp) / (name + '.exe')
        subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter',
                        '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
print('ok   All Games gathers every started source, tags duplicates, stars favourites, R3 toggles')
print('ok   started device and Apps tabs step aside; Manual ones, share pickers and the page stay')

assert ('if (selected_item != NULL && !menuItemShown(selected_item->item) && (gAllGames || menuIsFavPage(selected_item)))\n'
        '        refreshMenuPosition();') in menusys, 'the main page must leave a hidden All Games/Favourites page'
rehome = r"""
#include <assert.h>
#include <stddef.h>
enum { BDM_MODE = 0, BDM_MODE7 = 7, ETH_MODE, HDD_MODE, APP_MODE, MMCE_MODE, FAV_MODE, UDPFS_MODE, HTTP_MODE };
#define BDM_MODE_LAST BDM_MODE7
typedef struct { int mode, enabled; } item_list_t;
typedef struct menu_item { int visible; void *userdata; } menu_item_t;
typedef struct menu_list { menu_item_t *item; struct menu_list *next, *prev; } menu_list_t;
static int gAllGames, gDefaultDevice = HDD_MODE;
static char gPCShareName[32];
static menu_list_t *menu, *selected_item;
""" + function(menusys, 'int menuItemShown(const menu_item_t *item)') + \
    function(menusys, 'static int menuIsFavPage(const menu_list_t *page)') + \
    function(menusys, 'static void refreshMenuPosition(void)') + r"""
static void frame(void) /* menuHandleInputMain's guard */
{
    if (selected_item != NULL && !menuItemShown(selected_item->item) && (gAllGames || menuIsFavPage(selected_item)))
        refreshMenuPosition();
}
int main(void)
{
    item_list_t usb = {BDM_MODE, 1}, hdd = {HDD_MODE, 1}, apps = {APP_MODE, 1}, fav = {FAV_MODE, 1};
    menu_item_t tUsb = {1, &usb}, tHdd = {1, &hdd}, tApps = {1, &apps}, tFav = {1, &fav};
    menu_list_t pUsb = {&tUsb, NULL, NULL}, pHdd = {&tHdd, NULL, NULL}, pApps = {&tApps, NULL, NULL}, pFav = {&tFav, NULL, NULL};
    pUsb.next = &pHdd; pHdd.prev = &pUsb; pHdd.next = &pApps; pApps.prev = &pHdd; pApps.next = &pFav; pFav.prev = &pApps;
    menu = &pUsb;

    gAllGames = 1;                    /* on: a device page steps aside, the user lands on All Games */
    selected_item = &pHdd;
    frame();
    assert(selected_item == &pFav);

    gAllGames = 0;                    /* off with Favourites Page Start Mode Off: the page hides */
    tFav.visible = 0;
    frame();
    assert(selected_item == &pHdd);   /* the startup page, every tab shown again */
    assert(menuItemShown(&tUsb) && menuItemShown(&tApps));

    selected_item = &pFav;            /* no startup page: the first visible one */
    gDefaultDevice = MMCE_MODE;
    frame();
    assert(selected_item == &pUsb);

    tFav.visible = 1;                 /* off with Favourites on: the user stays where they are */
    selected_item = &pFav;
    frame();
    assert(selected_item == &pFav);

    selected_item = &pUsb;            /* a USB page hiding for a poll keeps the user on it (#806) */
    tUsb.visible = 0;
    frame();
    assert(selected_item == &pUsb);
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='ripps2-allgames-off-') as temp:
    src = Path(temp) / 'rehome.c'
    src.write_text(rehome)
    exe = Path(temp) / 'rehome.exe'
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   All Games off: a hidden Favourites page goes to the startup page, a polling device page stays')

iconSrc = (root / 'src/themes.c').read_text()
icon = r"""
#include <assert.h>
#include <stddef.h>
enum { BDM_MODE = 0, FAV_MODE = 12 };
enum { FAV_ICON = 7, USB_ICON = 3 };
typedef struct { int mode, enabled; } item_list_t;
typedef struct menu_item { int visible, icon_id; void *userdata; } menu_item_t;
struct menu_list { menu_item_t *item; };
struct submenu_list { int unused; };
typedef struct { int unused; } config_set_t;
struct theme_element { int posX, posY, aligned, width, height, scaled; };
typedef struct { void *Mem; } GSTEXTURE;
static int gAllGames, draws, gDefaultCol;
static GSTEXTURE tex = {&tex};
static int thmElemSkipsDevice(struct theme_element *e, int id) { (void)e; (void)id; return 0; }
static GSTEXTURE *thmGetTexture(int id) { (void)id; return &tex; }
static void rmDrawPixmap(GSTEXTURE *t, int x, int y, int a, int w, int h, int s, int c, int z) { (void)t; (void)x; (void)y; (void)a; (void)w; (void)h; (void)s; (void)c; (void)z; draws++; }
""" + function(iconSrc, 'static void drawMenuIcon(struct menu_list *menu') + r"""
int main(void)
{
    item_list_t fav = {FAV_MODE, 1}, usb = {BDM_MODE, 1};
    menu_item_t tFav = {1, FAV_ICON, &fav}, tUsb = {1, USB_ICON, &usb};
    struct menu_list pFav = {&tFav}, pUsb = {&tUsb};
    struct theme_element e = {0, 0, 0, 0, 0, 0};
    drawMenuIcon(&pFav, NULL, NULL, &e);
    assert(draws == 1);               /* Favourites page: its star */
    gAllGames = 1;
    drawMenuIcon(&pFav, NULL, NULL, &e);
    assert(draws == 1);               /* All Games page: no page icon */
    drawMenuIcon(&pUsb, NULL, NULL, &e);
    assert(draws == 2);               /* a tab that stays (Manual device) keeps its icon */
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='ripps2-allgames-icon-') as temp:
    src = Path(temp) / 'icon.c'
    src.write_text(icon)
    exe = Path(temp) / 'icon.exe'
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   the All Games page draws no page icon; Favourites and the tabs that stay keep theirs')

libview = (root / 'src/libview.c').read_text()
ring = libview[libview.index('if (mode == FAV_MODE && gAllGames) {'):]
ring = ring[:ring.index('} else if (mode == FAV_MODE)')]
stops = re.findall(r'\(cur == (LIB_VIEW_\w+)\)\s*\? (LIB_VIEW_\w+)', ring)
assert stops == [('LIB_VIEW_ALL', 'LIB_VIEW_ISO'), ('LIB_VIEW_ISO', 'LIB_VIEW_PS1'), ('LIB_VIEW_PS1', 'LIB_VIEW_ELF'),
                 ('LIB_VIEW_ELF', 'LIB_VIEW_FAVS'), ('LIB_VIEW_FAVS', 'LIB_VIEW_RECENT')], stops
assert 'if (gAllGames)\n        return LIB_VIEW_MIXED;' in libview, 'device pages must read both lists'
print('ok   L3: All -> PS2 -> PS1 -> APP -> Favourites -> Recent; devices read PS2 and PS1')

opl = (root / 'src/opl.c').read_text()
assert 'startMode = gAllGames ? START_MODE_AUTO : gFAVStartMode;' in opl
assert 'if (gAllGames && list_support[FAV_MODE].support != NULL)\n        bootMode = FAV_MODE;' in opl
assert '(gFAVStartMode || gAllGames) && mod->support->mode != FAV_MODE' in opl, 'source changes must rebuild the list'
assert 'if (!gFAVStartMode && !gAllGames) // Favourites and All Games both off' in opl, 'R3 must work with All Games on and Favourites off'
assert 'if (gFAVStartMode || gAllGames)\n            menuAddHint(&mod->menuItem, _STR_FAV_HINT, R3_ICON);' in opl, 'the R3 hint must show with All Games on'
print('ok   the page starts with the setting, boots first, and follows every source refresh')

bdm = (root / 'src/bdmsupport.c').read_text()
needs = function(bdm, 'static int bdmNeedsUpdate(item_list_t *itemList)')
hide = needs[needs.index('if (bdmTransportEnabled(pDeviceData->bdmDeviceType) == 0) {'):]
hide = hide[:hide.index('\n        }\n')]
assert 'if (gAllGames)\n                loadFavourites();' in hide, 'a page hidden for a switched-off transport must leave All Games'
assert 'if (gAllGames && bdmTransportEnabled(pDeviceData->bdmDeviceType) != 0)\n            loadFavourites();' in bdm, \
    'a reappearing slot rejoins All Games, unless its transport is Off'
print('ok   a BDM page hidden for a switched-off transport, or shown again, rebuilds All Games')

gui = (root / 'src/gui.c').read_text()
apply = function(gui, 'static void guiApplyAllGamesChange(void)')
assert apply.index('initSupport(favGetObject(0), FAV_MODE, 0);') < apply.index('oplGetModule(FAV_MODE)'), \
    'the All Games page must be started or hidden before it is selected'
assert gui.count('guiApplyAllGamesChange();') >= 2, 'Game Sources and Interface (Library) both apply the change'
print('ok   Library under Interface starts or hides the All Games page like Game Sources does')
