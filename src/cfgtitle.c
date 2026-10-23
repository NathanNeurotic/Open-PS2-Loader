/*
  cfgtitle.c -- optional CFG Titles in the game lists (#918).

  "Show CFG Titles in Game Lists" (off by default) lets a row show the Title
  written in the game's per-game CFG -- typically a proper Japanese title
  from OPL Manager -- instead of its file name, and sort by it.

  Display only. The row's identity text (item.text, which rename, Favorites,
  art, configs and launching key on) is never changed; drawing and sorting
  ask cfgTitleDisplayName() instead, the same way the PS1 game-ID hiding works
  (vcdDisplayNameForRow).

  Cost, which is why it is opt-in: each list rebuild reads every game's CFG
  once, on the I/O thread, through the same loader the info page uses
  (itemGetConfig). Reading them all is what lets the list sort by what it
  shows. The rows appear with their file names first; the CFG pass runs after
  them and the sort follows it. The table of kept titles is swapped in under
  the GUI frame lock, so a frame never sees it half built or freed.
*/

#include "include/opl.h" // first: the PS2 types every other header needs
#include "include/cfgtitle.h"
#include "include/config.h"
#include "include/gui.h"
#include "include/vcdsupport.h"
#include "include/folderbrowse.h"
#include "include/favsupport.h" /* favGetItemSourceMode: Favorites from the Apps tab are apps */
#ifdef RETROACHIEVEMENTS
#include "include/rabadge.h"
#endif

#include <stdlib.h>
#include <string.h>

typedef struct
{
    item_list_t *support;
    int count;
    char **title;
} cfg_title_slot_t;

static cfg_title_slot_t g_titleSlots[MODE_COUNT];

static cfg_title_slot_t *findSlot(item_list_t *support)
{
    int i;
    if (support == NULL)
        return NULL; /* an unclaimed slot also has support == NULL */
    for (i = 0; i < MODE_COUNT; i++)
        if (g_titleSlots[i].support == support)
            return &g_titleSlots[i];
    return NULL;
}

static cfg_title_slot_t *claimSlot(item_list_t *support)
{
    cfg_title_slot_t *slot = findSlot(support);
    int i;

    if (slot != NULL)
        return slot;
    for (i = 0; i < MODE_COUNT; i++)
        if (g_titleSlots[i].support == NULL) {
            g_titleSlots[i].support = support;
            return &g_titleSlots[i];
        }
    return NULL;
}

/* Length of the UTF-8 character at p (within n bytes), or 0 if it is not valid strict UTF-8:
   no overlong forms, surrogates, code points past U+10FFFF or C1 control characters. */
static int utf8Length(const unsigned char *p, int n)
{
    int len, i;

    if (p[0] < 0x80)
        len = 1;
    else if ((p[0] & 0xE0) == 0xC0 && p[0] >= 0xC2)
        len = 2;
    else if ((p[0] & 0xF0) == 0xE0)
        len = 3;
    else if ((p[0] & 0xF8) == 0xF0 && p[0] <= 0xF4)
        len = 4;
    else
        return 0;
    if (len > n)
        return 0;
    for (i = 1; i < len; i++)
        if ((p[i] & 0xC0) != 0x80)
            return 0;
    if ((p[0] == 0xC2 && p[1] < 0xA0) || /* U+0080..U+009F: C1 controls */
        (p[0] == 0xE0 && p[1] < 0xA0) || /* overlong */
        (p[0] == 0xED && p[1] > 0x9F) || /* surrogates */
        (p[0] == 0xF0 && p[1] < 0x90) || /* overlong */
        (p[0] == 0xF4 && p[1] > 0x8F))   /* past U+10FFFF */
        return 0;
    return len;
}

int cfgTitleClean(const char *in, char *out, int size)
{
    const unsigned char *p, *end;
    int at = 0, n;

    if (out == NULL || size < 2)
        return 0;
    out[0] = '\0';
    if (in == NULL)
        return 0;
    p = (const unsigned char *)in;
    end = p + strlen(in);
    while (p < end && (*p == ' ' || *p == '\t'))
        p++;
    while (end > p && (end[-1] == ' ' || end[-1] == '\t'))
        end--;
    if (p == end)
        return 0;

    while (p < end) {
        n = utf8Length(p, (int)(end - p));
        if (n == 0 || (n == 1 && (*p < 0x20 || *p == 0x7F)))
            return 0; /* not text: show the file name */
        if (at + n > size - 1)
            break; /* cut on a character boundary */
        memcpy(out + at, p, n);
        at += n;
        p += n;
    }
    out[at] = '\0';
    return at > 0;
}

static int isFolderRow(item_list_t *support, int id)
{
    base_game_info_t *game;

    if (!folderModeSupported(support->mode) || support->itemGet == NULL)
        return 0;
    game = (base_game_info_t *)support->itemGet(support, id);
    return game != NULL && game->format == GAME_FORMAT_FOLDER;
}

/* Preserve the cached mark around the CFG title. Match the complete known affix
   so a filename such as "[RA]" cannot be mistaken for part of the mark. */
static char *keepTitle(item_list_t *support, int id, const char *clean)
{
    const char *prefix = "", *suffix = "";
    size_t prefixLen = 0, suffixLen = 0, len;
    char *kept;

#ifdef RETROACHIEVEMENTS
    {
        const char *badge = raBadgeText(support, id);
        const char *name = support->itemGetName != NULL ? support->itemGetName(support, id) : NULL;
        if (badge != NULL && name != NULL) {
            size_t badgeLen = strlen(badge), nameLen = strlen(name);
            if (badgeLen == nameLen + 3 && !strncmp(badge, "RA ", 3) && !strcmp(badge + 3, name)) {
                prefix = badge;
                prefixLen = badgeLen - nameLen;
            } else if (badgeLen == nameLen + 5 && !strncmp(badge, name, nameLen) && !strcmp(badge + nameLen, " [RA]")) {
                suffix = badge + nameLen;
                suffixLen = badgeLen - nameLen;
            }
        }
    }
#else
    (void)support;
    (void)id;
#endif
    len = strlen(clean);
#ifdef RETROACHIEVEMENTS
    kept = malloc(prefixLen + len + suffixLen + 1 + len + 1);
#else
    kept = malloc(len + 1);
#endif
    if (kept == NULL)
        return NULL;
    memcpy(kept, prefix, prefixLen);
    memcpy(kept + prefixLen, clean, len);
    memcpy(kept + prefixLen + len, suffix, suffixLen + 1);
#ifdef RETROACHIEVEMENTS
    // Keep the clean title in the same allocation for badge-independent sorting.
    memcpy(kept + prefixLen + len + suffixLen + 1, clean, len + 1);
#endif
    return kept;
}

/* Swaps a new table in under the GUI frame lock and frees the old one after it. */
static void swapTable(cfg_title_slot_t *slot, char **fresh, int freshCount)
{
    char **old;
    int i, oldCount;

    guiLock();
    old = slot->title;
    oldCount = slot->count;
    slot->title = fresh;
    slot->count = freshCount;
    guiUnlock();

    if (old != NULL) {
        for (i = 0; i < oldCount; i++)
            free(old[i]);
        free(old);
    }
}

void cfgTitleForget(item_list_t *support)
{
    cfg_title_slot_t *slot = findSlot(support);

    if (slot != NULL && slot->title != NULL)
        swapTable(slot, NULL, 0);
}

void cfgTitleRefresh(item_list_t *support, int count)
{
    cfg_title_slot_t *slot;
    char **fresh = NULL;
    int i, freshCount = 0;

    if (support == NULL || (slot = claimSlot(support)) == NULL)
        return;

    if (gCfgTitlesInLists && support->mode != APP_MODE && support->itemGetConfig != NULL && count > 0) {
        fresh = malloc((size_t)count * sizeof(char *));
        if (fresh != NULL) {
            char clean[CFG_TITLE_MAX];

            memset(fresh, 0, (size_t)count * sizeof(char *));
            freshCount = count;
            for (i = 0; i < count; i++) {
                config_set_t *config;
                const char *title = NULL;

                if (isFolderRow(support, i))
                    continue;
                if (support->mode == FAV_MODE && favGetItemSourceMode(i) == APP_MODE)
                    continue; /* a Favorite from the Apps tab is an app: the Apps list shows no titles */
                config = support->itemGetConfig(support, i);
                if (config == NULL)
                    continue;
                if (configGetStr(config, "Title", &title) && cfgTitleClean(title, clean, sizeof(clean)))
                    fresh[i] = keepTitle(support, i, clean);
                configFree(config);
            }
        }
    }

    swapTable(slot, fresh, freshCount);
}

const char *cfgTitleForRow(item_list_t *support, int id)
{
    cfg_title_slot_t *slot;

    if (!gCfgTitlesInLists)
        return NULL; /* switched off: file names at once, before the lists rebuild */
    slot = findSlot(support);
    if (slot == NULL || slot->title == NULL || id < 0 || id >= slot->count)
        return NULL;
    return slot->title[id];
}

const char *cfgTitleDisplayName(item_list_t *support, int id, const char *text)
{
    const char *title = cfgTitleForRow(support, id);
    return title != NULL ? title : vcdDisplayNameForRow(support, id, text);
}

const char *cfgTitleSortName(item_list_t *support, int id, const char *text)
{
    const char *title = cfgTitleForRow(support, id);
#ifdef RETROACHIEVEMENTS
    if (title != NULL)
        title += strlen(title) + 1;
#endif
    return title != NULL ? title : vcdDisplayNameForRow(support, id, text);
}
