"""Optional CFG Titles in game lists (#918): display only, off by default, read on the I/O thread.

With "Show CFG Titles in Game Lists" on, every list rebuild reads each game's per-game CFG once
(itemGetConfig, the same loader the info page uses) and keeps its UTF-8 Title. Rows then show and
sort by that title; identity (item.text, startup, file name, Favorites, art, rename, launch) is never
touched. Off (the default) reads nothing. src/cfgtitle.c is compiled against stubs.
"""
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/cfgtitle.c").read_text(encoding="utf-8")
source = re.sub(r"^#include.*\n", "", source, flags=re.M)

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MODE_COUNT 8
enum { BDM_MODE, ETH_MODE, HDD_MODE, APP_MODE, FAV_MODE };
#define GAME_FORMAT_FOLDER 9
#define CFG_TITLE_MAX 64
typedef struct { const char *title; int present; } config_set_t;
typedef struct { int format; } base_game_info_t;
typedef struct item_list item_list_t;
struct item_list {
    int mode;
    char *(*itemGetName)(item_list_t *, int);
    void *(*itemGet)(item_list_t *, int);
    config_set_t *(*itemGetConfig)(item_list_t *, int);
};
static int gCfgTitlesInLists, configReads, configFrees, locks, unlocks, mallocFailAt = -1, mallocs;
static const char *titles[8];
static base_game_info_t games[8];
static char *names[8] = {"Dragon Quest VIII", "SLPM_655.55", "Game C", "Folder", "Game E", "Game F", "Game G", "Game H"};
static config_set_t configs[8];
static char *getName(item_list_t *l, int i) { (void)l; return names[i]; }
static void *getGame(item_list_t *l, int i) { (void)l; return &games[i]; }
static config_set_t *getConfig(item_list_t *l, int i) { (void)l; configReads++; configs[i].title = titles[i]; return &configs[i]; }
static int configGetStr(config_set_t *c, const char *key, const char **out) { assert(!strcmp(key, "Title")); *out = c->title; return c->title != NULL; }
static void configFree(config_set_t *c) { (void)c; configFrees++; }
static void guiLock(void) { locks++; }
static void guiUnlock(void) { unlocks++; }
static int folderModeSupported(int mode) { return mode == BDM_MODE; }
static int hideVcdPrefix;
static const char *vcdDisplayNameForRow(item_list_t *l, int id, const char *text) {
    (void)l; (void)id;
    return hideVcdPrefix && !strncmp(text, "SLUS_012.15.", 12) ? text + 12 : text;
}
static int favSource[8];
static int favGetItemSourceMode(int id) { return favSource[id]; }
#ifdef RETROACHIEVEMENTS
static const char *badges[8];
static const char *raBadgeText(item_list_t *l, int id) { (void)l; return badges[id]; }
#endif
static void *testMalloc(size_t n) { if (mallocs++ == mallocFailAt) return NULL; return malloc(n); }
#define malloc testMalloc
'''

tests = r'''
int main(void)
{
    item_list_t bdm = {BDM_MODE, getName, getGame, getConfig};
    item_list_t app = {APP_MODE, getName, getGame, getConfig};
    char clean[CFG_TITLE_MAX];

    /* off_reads_nothing: the default costs no CFG reads and shows names unchanged. */
    titles[0] = "ドラゴンクエストVIII";
    cfgTitleRefresh(&bdm, 3);
    assert(configReads == 0 && cfgTitleForRow(&bdm, 0) == NULL);
    assert(!strcmp(cfgTitleDisplayName(&bdm, 0, names[0]), "Dragon Quest VIII"));

    /* on_shows_title: one read per game, freed, title shown; identity untouched. */
    gCfgTitlesInLists = 1;
    titles[1] = "  Kingdom Hearts  ";
    titles[2] = "";
    games[3].format = GAME_FORMAT_FOLDER;
    titles[3] = "Never read";
    cfgTitleRefresh(&bdm, 4);
    assert(configReads == 3 && configFrees == 3); /* the folder row is skipped */
    assert(!strcmp(cfgTitleDisplayName(&bdm, 0, names[0]), "ドラゴンクエストVIII"));
    assert(!strcmp(cfgTitleDisplayName(&bdm, 1, names[1]), "Kingdom Hearts")); /* trimmed */
    assert(!strcmp(cfgTitleDisplayName(&bdm, 2, names[2]), "Game C"));        /* empty: name */
    assert(!strcmp(cfgTitleDisplayName(&bdm, 3, names[3]), "Folder"));
    assert(!strcmp(names[0], "Dragon Quest VIII"));
    assert(locks == unlocks && locks >= 1); /* swapped under the GUI lock */
    assert(cfgTitleForRow(&bdm, 99) == NULL && cfgTitleForRow(&bdm, -1) == NULL);

    /* apps_skipped: Apps are executables, not library games. */
    configReads = 0;
    cfgTitleRefresh(&app, 3);
    assert(configReads == 0 && cfgTitleForRow(&app, 0) == NULL);

    /* clean: invalid UTF-8 and control characters fall back; long titles cut on a character. */
    assert(!cfgTitleClean("\xff\xfe broken", clean, sizeof(clean)));
    assert(!cfgTitleClean("bad\x01ctrl", clean, sizeof(clean)));
    assert(!cfgTitleClean("\xe3\x83", clean, sizeof(clean))); /* truncated sequence */
    assert(!cfgTitleClean("   ", clean, sizeof(clean)));
    assert(cfgTitleClean("ファイナルファンタジーファイナルファンタジーファイナルファンタジー", clean, sizeof(clean)));
    assert(strlen(clean) < CFG_TITLE_MAX && (strlen(clean) % 3) == 0); /* whole 3-byte characters */
    assert(cfgTitleClean("Ok", clean, sizeof(clean)) && !strcmp(clean, "Ok"));
    /* strict UTF-8: overlong, surrogate, beyond U+10FFFF and C1 controls fall back. */
    assert(!cfgTitleClean("\xe0\x80\x80", clean, sizeof(clean)));
    assert(!cfgTitleClean("\xed\xa0\x80", clean, sizeof(clean)));
    assert(!cfgTitleClean("\xf4\x90\x80\x80", clean, sizeof(clean)));
    assert(!cfgTitleClean("\xf0\x80\x80\x80", clean, sizeof(clean)));
    assert(!cfgTitleClean("a\xc2\x85" "b", clean, sizeof(clean)));
    assert(cfgTitleClean("Caf\xc3\xa9", clean, sizeof(clean)));

    /* off_is_immediate: switching off shows file names at once, before any rebuild. */
    gCfgTitlesInLists = 0;
    assert(cfgTitleForRow(&bdm, 0) == NULL);
    assert(!strcmp(cfgTitleDisplayName(&bdm, 0, names[0]), "Dragon Quest VIII"));
    gCfgTitlesInLists = 1;
    assert(cfgTitleForRow(&bdm, 0) != NULL);

    /* forget: a rebuild drops the old table before new rows appear (no stale-index titles). */
    cfgTitleForget(&bdm);
    assert(cfgTitleForRow(&bdm, 0) == NULL);
    assert(cfgTitleForRow(NULL, 0) == NULL);

    /* turned_off_clears: switching off drops the titles on the next rebuild. */
    gCfgTitlesInLists = 0;
    cfgTitleRefresh(&bdm, 4);
    assert(cfgTitleForRow(&bdm, 0) == NULL);

    /* fav_apps_skipped: a Favorite whose source is the Apps tab is an app, never titled. */
    {
        item_list_t fav = {FAV_MODE, getName, getGame, getConfig};
        gCfgTitlesInLists = 1;
        favSource[0] = APP_MODE;
        favSource[1] = BDM_MODE;
        configReads = 0;
        cfgTitleRefresh(&fav, 2);
        assert(configReads == 1 && cfgTitleForRow(&fav, 0) == NULL && cfgTitleForRow(&fav, 1) != NULL);
        gCfgTitlesInLists = 0;
        cfgTitleRefresh(&fav, 2);
    }

#ifdef RETROACHIEVEMENTS
    /* ra_badge_prefix: a tracked game keeps its badge in front of the title. */
    gCfgTitlesInLists = 1;
    badges[0] = "RA Dragon Quest VIII";
    badges[1] = "RA something else";
    titles[1] = "Kingdom Hearts";
    cfgTitleRefresh(&bdm, 2);
    assert(!strcmp(cfgTitleForRow(&bdm, 0), "RA ドラゴンクエストVIII"));
    assert(!strcmp(cfgTitleForRow(&bdm, 1), "Kingdom Hearts")); /* badge does not end with the name */
    assert(!strcmp(cfgTitleSortName(&bdm, 0, names[0]), "ドラゴンクエストVIII"));
    badges[0] = "Dragon Quest VIII [RA]";
    badges[1] = "SLPM_655.55 [RA]";
    cfgTitleRefresh(&bdm, 2);
    assert(!strcmp(cfgTitleForRow(&bdm, 0), "ドラゴンクエストVIII [RA]"));
    assert(!strcmp(cfgTitleForRow(&bdm, 1), "Kingdom Hearts [RA]"));
    assert(!strcmp(cfgTitleSortName(&bdm, 1, names[1]), "Kingdom Hearts"));
    names[0] = "[RA]";
    badges[0] = "[RA] [RA]";
    cfgTitleRefresh(&bdm, 1);
    assert(!strcmp(cfgTitleForRow(&bdm, 0), "ドラゴンクエストVIII [RA]"));
    names[0] = "SLUS_012.15.Dragon Quest VIII";
    hideVcdPrefix = 1;
    badges[0] = "RA Dragon Quest VIII";
    cfgTitleRefresh(&bdm, 1);
    assert(!strncmp(cfgTitleForRow(&bdm, 0), "RA ", 3));
    badges[0] = "Dragon Quest VIII [RA]";
    cfgTitleRefresh(&bdm, 1);
    assert(strstr(cfgTitleForRow(&bdm, 0), " [RA]") != NULL);
    hideVcdPrefix = 0;
    names[0] = "Dragon Quest VIII";
    gCfgTitlesInLists = 0;
    cfgTitleRefresh(&bdm, 2);
#endif

    /* alloc_failure: no table means names, never a crash. */
    gCfgTitlesInLists = 1;
    mallocs = 0;
    mallocFailAt = 0;
    cfgTitleRefresh(&bdm, 4);
    assert(cfgTitleForRow(&bdm, 0) == NULL);
    assert(!strcmp(cfgTitleDisplayName(&bdm, 0, names[0]), "Dragon Quest VIII"));
    mallocFailAt = -1;

    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "titles.c"
    src.write_text(harness + source + tests, encoding="utf-8")
    for flags in ([], ["-DRETROACHIEVEMENTS"]):  # standard and RA builds (badge prefix)
        exe = Path(tmp) / ("titles%s.exe" % ("_ra" if flags else ""))
        subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function", *flags, str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

# Wiring: refresh after each scan; rows and sorting draw through the display name; off by default.
opl = (ROOT / "src/opl.c").read_text(encoding="utf-8")
update = opl[opl.index("static void updateMenuFromGameList("):]
update = update[:update.index("\n}\n")]
# Rows appear with file names at once; the CFG pass runs after them and the sort follows it.
assert update.index("itemUpdate(mdl->support)") < update.index("cfgTitleForget(mdl->support);") < update.index("guiDeferUpdate(gup);")
assert update.index("guiDeferUpdate(gup);") < update.index("cfgTitleRefresh(mdl->support, count);") < update.index("GUI_OP_SORT")
assert update.index("libViewFinishPending(") < update.index("cfgTitleRefresh(mdl->support, count);")
assert "gup->submenu.text = mdl->support->mode == FAV_MODE ? (char *)favGetItemDisplay(i) : mdl->support->itemGetName(mdl->support, i);" in update  # identity unchanged; All Games rows draw their source tag
menusys = (ROOT / "src/menusys.c").read_text(encoding="utf-8")
sort = menusys[menusys.index("static int submenuSortCompare("):]
sort = sort[:sort.index("\n}\n")]
assert "cfgTitleSortName(support, a->item.id, txt1)" in sort and "vcdDisplayNameForRow" not in sort
themes = (ROOT / "src/themes.c").read_text(encoding="utf-8")
assert "cfgTitleDisplayName(list, ps->item.id, submenuItemGetText(&ps->item))" in themes
assert menusys.count("cfgTitleDisplayName(") >= 2  # both game-menu headers
assert "gCfgTitlesInLists = 0;" in opl
assert "CONFIG_OPL_CFG_TITLES, &gCfgTitlesInLists" in opl and "CONFIG_OPL_CFG_TITLES, gCfgTitlesInLists" in opl
dialogs = (ROOT / "src/dialogs.c").read_text(encoding="utf-8")
assert "UICFG_CFG_TITLES, 1, 1, _STR_HINT_CFG_TITLES" in dialogs
gui = (ROOT / "src/gui.c").read_text(encoding="utf-8")
assert gui.count("diaGetInt(ui, UICFG_CFG_TITLES") == 1
# A flip must rebuild every game list: mark the pages dirty (each NeedsUpdate consumes it) and
# queue HTTP too, which oplQueueLibraryDeviceUpdates leaves out.
refresh = gui[gui.index("static void guiRefreshCfgTitles(void)\n{"):]
refresh = refresh[:refresh.index("\n}\n")]
assert "libViewMarkAllDirty();" in refresh and "guiRefreshGameViews();" in refresh and "httpGetObject(0)" in refresh
assert gui.count("guiRefreshCfgTitles();") == 3  # the Interface page, the All Games switch, the Show Hidden Games flip
base = (ROOT / "lng_tmpl/_base.yml").read_text(encoding="utf-8")
assert base.index("- label: CFG_TITLES") > base.index("- label: CAD_UDPFS_IMG")
print("PASS: CFG titles in game lists are opt-in, display-only and read once per rebuild")
