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
static const char *vcdDisplayNameForRow(item_list_t *l, int id, const char *text) { (void)l; (void)id; return text; }
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

    /* turned_off_clears: switching off drops the titles on the next rebuild. */
    gCfgTitlesInLists = 0;
    cfgTitleRefresh(&bdm, 4);
    assert(cfgTitleForRow(&bdm, 0) == NULL);

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
    exe = Path(tmp) / "titles.exe"
    src.write_text(harness + source + tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# Wiring: refresh after each scan; rows and sorting draw through the display name; off by default.
opl = (ROOT / "src/opl.c").read_text(encoding="utf-8")
update = opl[opl.index("static void updateMenuFromGameList("):]
update = update[:update.index("\n}\n")]
assert update.index("itemUpdate(mdl->support)") < update.index("cfgTitleRefresh(mdl->support, count);")
assert "gup->submenu.text = mdl->support->itemGetName(mdl->support, i);" in update  # identity unchanged
menusys = (ROOT / "src/menusys.c").read_text(encoding="utf-8")
sort = menusys[menusys.index("static int submenuSortCompare("):]
sort = sort[:sort.index("\n}\n")]
assert "cfgTitleDisplayName(support, a->item.id, txt1)" in sort and "vcdDisplayNameForRow" not in sort
themes = (ROOT / "src/themes.c").read_text(encoding="utf-8")
assert "cfgTitleDisplayName(list, ps->item.id, submenuItemGetText(&ps->item))" in themes
assert menusys.count("cfgTitleDisplayName(") >= 3  # sort + both game-menu headers
assert "gCfgTitlesInLists = 0;" in opl
assert "CONFIG_OPL_CFG_TITLES, &gCfgTitlesInLists" in opl and "CONFIG_OPL_CFG_TITLES, gCfgTitlesInLists" in opl
dialogs = (ROOT / "src/dialogs.c").read_text(encoding="utf-8")
assert "UICFG_CFG_TITLES, 1, 1, _STR_HINT_CFG_TITLES" in dialogs
gui = (ROOT / "src/gui.c").read_text(encoding="utf-8")
assert gui.count("diaGetInt(diaUIConfig, UICFG_CFG_TITLES") + gui.count("diaGetInt(ui, UICFG_CFG_TITLES") == 2
base = (ROOT / "lng_tmpl/_base.yml").read_text(encoding="utf-8")
assert base.index("- label: CFG_TITLES") > base.index("- label: CAD_UDPFS_IMG")
print("PASS: CFG titles in game lists are opt-in, display-only and read once per rebuild")
