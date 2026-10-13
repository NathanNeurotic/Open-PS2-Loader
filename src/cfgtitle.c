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
  shows. The table of kept titles is swapped in under the GUI frame lock, so
  a frame never sees it half built or freed.
*/

#include "include/cfgtitle.h"
#include "include/opl.h"
#include "include/config.h"
#include "include/gui.h"
#include "include/vcdsupport.h"
#include "include/folderbrowse.h"
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

/* Length of the UTF-8 character at p (within n bytes), or 0 if it is not valid. */
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

/* The title as the row should show it: in RA builds a tracked game's badge prefix stays in front. */
static char *keepTitle(item_list_t *support, int id, const char *clean)
{
    const char *prefix = "";
    size_t prefixLen = 0, len;
    char *kept;

#ifdef RETROACHIEVEMENTS
    {
        const char *badge = raBadgeText(support, id);
        const char *name = support->itemGetName != NULL ? support->itemGetName(support, id) : NULL;
        if (badge != NULL && name != NULL) {
            size_t badgeLen = strlen(badge), nameLen = strlen(name);
            if (badgeLen > nameLen && !strcmp(badge + badgeLen - nameLen, name)) {
                prefix = badge;
                prefixLen = badgeLen - nameLen;
            }
        }
    }
#else
    (void)support;
    (void)id;
#endif
    len = strlen(clean);
    kept = malloc(prefixLen + len + 1);
    if (kept == NULL)
        return NULL;
    memcpy(kept, prefix, prefixLen);
    memcpy(kept + prefixLen, clean, len + 1);
    return kept;
}

void cfgTitleRefresh(item_list_t *support, int count)
{
    cfg_title_slot_t *slot;
    char **fresh = NULL, **old;
    int i, freshCount = 0, oldCount;

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
                config = support->itemGetConfig(support, i);
                if (config == NULL)
                    continue;
                if (configGetStr(config, "Title", &title) && cfgTitleClean(title, clean, sizeof(clean)))
                    fresh[i] = keepTitle(support, i, clean);
                configFree(config);
            }
        }
    }

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

const char *cfgTitleForRow(item_list_t *support, int id)
{
    cfg_title_slot_t *slot = findSlot(support);

    if (slot == NULL || slot->title == NULL || id < 0 || id >= slot->count)
        return NULL;
    return slot->title[id];
}

const char *cfgTitleDisplayName(item_list_t *support, int id, const char *text)
{
    const char *title = cfgTitleForRow(support, id);
    return title != NULL ? title : vcdDisplayNameForRow(support, id, text);
}
