/*
  gamemanage.c -- Hide Game and Delete everything.

  Ported from RIPPS2 by Akilluminati47 (akilluminati47/RIPPS2, build 114: SHROUD and LAST RITES).

  Hide Game: a hidden game leaves every list (its device's page, All Games, Favourites, Recent,
  Random Game) until it is shown again. Each device keeps its own list, hidden.txt in its prefix
  beside CFG/ and ART/, so the list goes where the drive goes. One line a game: "0" (PS2) or "1"
  (PS1), a tab, then the game's name. Settings > Show hidden games lists them anyway, so they can be
  shown again from the game's menu.

  Delete everything: the game's parts through the source's own delete (which also rebuilds ul.cfg),
  then its CFG, art and cheats, unless another copy of the game on the same page uses them. VMC
  saves are kept. The APA HDD has no delete here: removing a partition is not taken.
*/

#include "include/opl.h"
#include "include/gamemanage.h"
#include "include/iosupport.h"
#include "include/supportbase.h"
#include "include/ioman.h"
#include "include/libview.h"
#include "include/favsupport.h"
#include "include/folderbrowse.h"

#include <dirent.h>
#include <strings.h>

int gShowHidden;

typedef struct
{
    char prefix[160]; // the prefix the list was read from; another prefix reads it again
    int loaded, count;
    char *names[HIDDEN_MAX];
    unsigned char ps1[HIDDEN_MAX];
} hidden_list_t;

static hidden_list_t hiddenLists[MODE_COUNT];
static int hiddenSema = -1;

void hiddenInit(void)
{
    if (hiddenSema < 0) {
        ee_sema_t sema;
        sema.init_count = 1;
        sema.max_count = 1;
        sema.option = 0;
        sema.attr = 0;
        hiddenSema = CreateSema(&sema);
    }
}

static void hiddenLock(void)
{
    if (hiddenSema >= 0)
        WaitSema(hiddenSema);
}

static void hiddenUnlock(void)
{
    if (hiddenSema >= 0)
        SignalSema(hiddenSema);
}

// The prefix a source keeps its list in; NULL when it keeps none (the network catalogue, apps).
static const char *hiddenPrefix(int mode, char *out, int size)
{
    if (mode < 0 || mode >= MODE_COUNT || mode == HTTP_MODE || mode == APP_MODE || mode == FAV_MODE)
        return NULL;
    opl_io_module_t *mod = oplGetModule(mode);
    if (mod == NULL || mod->support == NULL || mod->support->itemGetPrefix == NULL)
        return NULL;
    const char *prefix = mod->support->itemGetPrefix(mod->support);
    if (prefix == NULL || prefix[0] == '\0' || (int)strlen(prefix) >= size)
        return NULL;
    snprintf(out, size, "%s", prefix);
    return out;
}

static void hiddenClear(hidden_list_t *list)
{
    for (int i = 0; i < list->count; i++)
        free(list->names[i]);
    list->count = 0;
}

static int hiddenAppend(hidden_list_t *list, int ps1, const char *name)
{
    if (list->count >= HIDDEN_MAX || name[0] == '\0')
        return 0;
    char *copy = malloc(strlen(name) + 1);
    if (copy == NULL)
        return 0;
    strcpy(copy, name);
    list->ps1[list->count] = ps1 != 0;
    list->names[list->count++] = copy;
    return 1;
}

// (with the lock held)
static hidden_list_t *hiddenLoad(int mode, int force)
{
    char prefix[160], path[200], line[HIDDEN_NAME_MAX + 8];
    hidden_list_t *list = &hiddenLists[mode];

    if (hiddenPrefix(mode, prefix, sizeof(prefix)) == NULL) {
        hiddenClear(list);
        list->loaded = 0;
        return NULL;
    }
    if (list->loaded && !force && !strcmp(list->prefix, prefix))
        return list;
    hiddenClear(list);
    snprintf(list->prefix, sizeof(list->prefix), "%s", prefix);
    list->loaded = 1;
    snprintf(path, sizeof(path), "%s%s", prefix, HIDDEN_FILE);
    FILE *f = fopen(path, "r");
    if (f == NULL)
        return list;
    while (fgets(line, sizeof(line), f) != NULL) {
        char *end = line + strlen(line);
        while (end > line && (end[-1] == '\n' || end[-1] == '\r'))
            *--end = '\0';
        // "0<tab>name" or "1<tab>name"; a bare name is a PS2 game, '#' starts a comment
        if (line[0] == '\0' || line[0] == '#')
            continue;
        if ((line[0] == '0' || line[0] == '1') && line[1] == '\t')
            hiddenAppend(list, line[0] == '1', line + 2);
        else
            hiddenAppend(list, 0, line);
    }
    fclose(f);
    return list;
}

static int hiddenFind(const hidden_list_t *list, int ps1, const char *name)
{
    for (int i = 0; i < list->count; i++)
        if (list->ps1[i] == (ps1 != 0) && !strcmp(list->names[i], name))
            return i;
    return -1;
}

void hiddenReload(int mode)
{
    if (mode < 0 || mode >= MODE_COUNT)
        return;
    hiddenLock();
    hiddenLoad(mode, 1);
    hiddenUnlock();
}

int hiddenHas(int mode, int ps1, const char *name)
{
    int has = 0;
    if (mode < 0 || mode >= MODE_COUNT || name == NULL || name[0] == '\0')
        return 0;
    hiddenLock();
    hidden_list_t *list = hiddenLoad(mode, 0);
    if (list != NULL)
        has = hiddenFind(list, ps1, name) >= 0;
    hiddenUnlock();
    return has;
}

int hiddenRowSource(item_list_t *support, int id, int *mode, int *ps1, const char **name)
{
    int m, p1;
    if (support == NULL || support->itemGetName == NULL || id < 0)
        return 0;
    if (support->mode == FAV_MODE) {
        int kind = favGetItemKind(id);
        if (kind < 0 || kind == FAV_KIND_ELF)
            return 0;
        m = favGetItemSourceMode(id);
        p1 = favKindView(kind) == LIB_VIEW_PS1;
    } else {
        if (support->mode == APP_MODE || support->mode == HTTP_MODE)
            return 0;
        if (folderModeSupported(support->mode) && support->itemGet != NULL) {
            base_game_info_t *game = (base_game_info_t *)support->itemGet(support, id);
            if (game == NULL || game->format == GAME_FORMAT_FOLDER)
                return 0;
        }
        int view = support->itemGetView != NULL ? support->itemGetView(support, id) : libViewActive(support->mode);
        if (view == LIB_VIEW_ELF)
            return 0;
        m = support->mode;
        p1 = view == LIB_VIEW_PS1;
    }
    if (m < 0 || m >= MODE_COUNT || m == HTTP_MODE || m == APP_MODE || m == FAV_MODE)
        return 0;
    const char *n = support->itemGetName(support, id);
    if (n == NULL || n[0] == '\0')
        return 0;
    *mode = m;
    *ps1 = p1;
    *name = n;
    return 1;
}

int hiddenRow(item_list_t *support, int id)
{
    int mode, ps1;
    const char *name;
    return hiddenRowSource(support, id, &mode, &ps1, &name) && hiddenHas(mode, ps1, name);
}

static int hiddenSave(const hidden_list_t *list)
{
    char path[200];
    snprintf(path, sizeof(path), "%s%s", list->prefix, HIDDEN_FILE);
    if (list->count == 0) {
        int fd = open(path, O_RDONLY);
        if (fd < 0)
            return 1;
        close(fd);
        return unlink(path) == 0;
    }
    FILE *f = fopen(path, "w");
    if (f == NULL)
        return 0;
    int ok = 1;
    for (int i = 0; i < list->count && ok; i++)
        ok = fprintf(f, "%d\t%s\n", list->ps1[i], list->names[i]) > 0;
    return (fclose(f) == 0) && ok;
}

int hiddenSet(int mode, int ps1, const char *name, int hide)
{
    char copy[HIDDEN_NAME_MAX];
    int result;

    if (mode < 0 || mode >= MODE_COUNT || name == NULL || name[0] == '\0')
        return -1;
    snprintf(copy, sizeof(copy), "%s", name); // name may be a row of the page the refresh rebuilds
    hiddenLock();
    hidden_list_t *list = hiddenLoad(mode, 1);
    if (list == NULL) {
        result = -1;
    } else {
        int at = hiddenFind(list, ps1, copy);
        if (hide ? at >= 0 : at < 0) {
            result = 1; // already as asked
        } else if (hide) {
            result = hiddenAppend(list, ps1, copy) && hiddenSave(list);
            if (!result && hiddenFind(list, ps1, copy) >= 0) {
                free(list->names[--list->count]); // not saved: not hidden
            }
        } else {
            char *gone = list->names[at];
            unsigned char gonePs1 = list->ps1[at];
            for (int i = at; i + 1 < list->count; i++) {
                list->names[i] = list->names[i + 1];
                list->ps1[i] = list->ps1[i + 1];
            }
            list->count--;
            result = hiddenSave(list);
            if (result) {
                free(gone);
            } else { // not saved: still hidden
                for (int i = list->count; i > at; i--) {
                    list->names[i] = list->names[i - 1];
                    list->ps1[i] = list->ps1[i - 1];
                }
                list->names[at] = gone;
                list->ps1[at] = gonePs1;
                list->count++;
            }
        }
    }
    hiddenUnlock();
    if (result == 1)
        hiddenRefresh(mode);
    return result;
}

void hiddenRefresh(int mode)
{
    opl_io_module_t *mod = oplGetModule(mode);
    if (mod != NULL && mod->support != NULL && mod->support->enabled) {
        libViewMarkDirty(mode);
        ioPutRequest(IO_MENU_UPDATE_DEFFERED, &mod->support->mode);
    }
    if (gFAVStartMode || gAllGames)
        loadFavourites();
}

// ---- Delete everything ----

static void gmAdd(gm_delete_plan_t *plan, int what, const char *dir, char sep, const char *name)
{
    if (plan->count >= GM_MAX_FILES)
        return;
    if (snprintf(plan->files[plan->count].path, sizeof(plan->files[0].path), "%s%c%s", dir, sep, name) >=
        (int)sizeof(plan->files[0].path))
        return;
    plan->files[plan->count++].what = what;
    if (what == GM_FILE_CFG)
        plan->cfg++;
    else if (what == GM_FILE_ART)
        plan->art++;
    else
        plan->cht++;
}

static int gmIsArt(const char *name, const char *startup)
{
    static const char *const exts[] = {".png", ".jpg", ".jpeg"};
    size_t n = strlen(startup), len = strlen(name);
    if (len <= n + 1 || strncasecmp(name, startup, n) != 0 || name[n] != '_')
        return 0;
    for (unsigned int i = 0; i < sizeof(exts) / sizeof(exts[0]); i++) {
        size_t e = strlen(exts[i]);
        if (len > n + 1 + e && !strcasecmp(name + len - e, exts[i]))
            return 1;
    }
    return 0;
}

// Any letter case, as the art index and the cheat loader find them. A folder that cannot be listed
// falls back to the names OPL itself looks for.
static void gmCollect(gm_delete_plan_t *plan, const char *dir, char sep, const char *startup, int what)
{
    char want[160];
    DIR *d = opendir(dir);
    if (d == NULL) {
        const char *colon = strchr(dir, ':');
        char alt[200];
        if (colon != NULL && colon[1] != '\0' && colon[1] != '/' && colon[1] != '\\' &&
            snprintf(alt, sizeof(alt), "%.*s/%s", (int)(colon - dir) + 1, dir, colon + 1) < (int)sizeof(alt))
            d = opendir(alt); // "mass0:ART" is listed as "mass0:/ART" (see artindex.c)
    }
    if (what != GM_FILE_ART)
        snprintf(want, sizeof(want), "%s.%s", startup, what == GM_FILE_CFG ? "cfg" : "cht");
    if (d != NULL) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if (what == GM_FILE_ART ? gmIsArt(e->d_name, startup) : !strcasecmp(e->d_name, want))
                gmAdd(plan, what, dir, sep, e->d_name);
        }
        closedir(d);
        return;
    }

    static const char *const art[] = {"COV", "COV2", "ICO", "LAB", "LGO", "BG", "SCR", "SCR2", "BG_00", "SCR_00", "SCR_01"};
    static const char *const artExt[] = {"png", "jpg", "jpeg"};
    char path[256];
    if (what != GM_FILE_ART) {
        const char *const ext[] = {what == GM_FILE_CFG ? "cfg" : "cht", what == GM_FILE_CFG ? NULL : "CHT"};
        for (int k = 0; k < 2 && ext[k] != NULL; k++) {
            snprintf(want, sizeof(want), "%s.%s", startup, ext[k]);
            snprintf(path, sizeof(path), "%s%c%s", dir, sep, want);
            int fd = open(path, O_RDONLY);
            if (fd >= 0) {
                close(fd);
                gmAdd(plan, what, dir, sep, want);
            }
        }
        return;
    }
    for (unsigned int i = 0; i < sizeof(art) / sizeof(art[0]); i++)
        for (unsigned int k = 0; k < sizeof(artExt) / sizeof(artExt[0]); k++) {
            snprintf(want, sizeof(want), "%s_%s.%s", startup, art[i], artExt[k]);
            snprintf(path, sizeof(path), "%s%c%s", dir, sep, want);
            int fd = open(path, O_RDONLY);
            if (fd >= 0) {
                close(fd);
                gmAdd(plan, what, dir, sep, want);
            }
        }
}

int gmPlanDelete(item_list_t *support, int id, gm_delete_plan_t *plan)
{
    static const char *const dirs[] = {"CFG", "ART", "CHT"};
    char dir[200];

    memset(plan, 0, sizeof(*plan));
    if (support == NULL || support->itemDelete == NULL || support->itemGet == NULL || support->itemGetPrefix == NULL ||
        support->itemGetCount == NULL || support->itemGetStartup == NULL || support->mode == HDD_MODE)
        return 0;
    base_game_info_t *game = (base_game_info_t *)support->itemGet(support, id);
    const char *prefix = support->itemGetPrefix(support);
    if (game == NULL || game->format == GAME_FORMAT_FOLDER || game->startup[0] == '\0' || game->parts <= 0 ||
        prefix == NULL || prefix[0] == '\0')
        return 0;
    plan->parts = game->parts;

    int count = support->itemGetCount(support);
    for (int i = 0; i < count && !plan->shared; i++) {
        const char *startup = i != id ? support->itemGetStartup(support, i) : NULL;
        plan->shared = startup != NULL && !strcmp(startup, game->startup);
    }
    if (plan->shared)
        return 1; // another copy keeps the CFG, art and cheats

    char sep = support->mode == ETH_MODE ? '\\' : '/';
    for (int what = GM_FILE_CFG; what <= GM_FILE_CHT; what++) {
        snprintf(dir, sizeof(dir), "%s%s", prefix, dirs[what]);
        gmCollect(plan, dir, sep, game->startup, what);
    }
    return 1;
}

int gmDeleteExtras(const gm_delete_plan_t *plan)
{
    int failed = 0;
    for (int i = 0; i < plan->count; i++)
        failed += unlink(plan->files[i].path) != 0;
    return failed;
}
