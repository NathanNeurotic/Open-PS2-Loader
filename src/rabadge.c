/*
  RA: the badge in the game list that marks a checked, tracked game.

  After a check the console stores the watch list next to the game as
  `<device>RA/<serial>.wl`. That file's presence is the whole record of
  RA support; there is no separate registry to drift out of sync.

  We look in the same places and in the same order as the loader does
  before launch (`sbLoadWatchList`): the game's own device first, then
  the share. Otherwise the badge would lie, showing what the launch
  cannot find or hiding lists prepared on the PC.

  Recomputed whenever the game list is refreshed, which happens on the
  I/O thread where file operations are safe. It must not be called from
  the menu handler, for the same reason mounting must not.

  Upstream design and implementation: hacan359. Port note: upstream keys
  the slot table on RA_BADGE_SLOTS=4 ("OPL has exactly this many devices"),
  which is not true of this fork -- MODE_COUNT is 14 (eight BDM slots, ETH,
  HDD, APP, MMCE, FAV, UDPFS). With four slots the badge cache silently
  mis-attributes lists across devices.

  This file compiles to nothing unless RETROACHIEVEMENTS=1.
*/

#ifdef RETROACHIEVEMENTS

#include "include/opl.h"
#include "include/util.h"
#include "include/supportbase.h"
#include "include/rabadge.h"
#include "include/rahash.h"
#include "include/bdmsupport.h"
#include "include/favsupport.h"
#include "include/libview.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#define RA_BADGE      "RA " /* prefix before the name; ASCII only, the stock \
                               theme font has no other glyphs */
#define RA_BADGE_TEXT (ISO_GAME_NAME_MAX + 8)

struct ra_badge_slot
{
    item_list_t *support;
    int count;
    char *text; /* count strings of RA_BADGE_TEXT each, or NULL */
};

static struct ra_badge_slot g_slots[MODE_COUNT];

static struct ra_badge_slot *slotFor(item_list_t *support)
{
    int i;

    for (i = 0; i < MODE_COUNT; i++)
        if (g_slots[i].support == support)
            return &g_slots[i];

    for (i = 0; i < MODE_COUNT; i++) {
        if (g_slots[i].support == NULL) {
            g_slots[i].support = support;
            return &g_slots[i];
        }
    }

    return NULL;
}

/* PS1 VCD artwork/config identity remains its filename. RA identity differs:
   the PS1 watch list and POPStarter telemetry use a per-image key derived
   from the full VCD path. Resolve it here, on the existing I/O refresh worker,
   without reading any VCD sectors or changing the game's display identity.
   Returns 1 for tracked-eligible VCD, 0 for a normal PS2/non-VCD row,
   -1 for an unsupported PS1 row that must not show an RA badge. */
static int badgeVcdKey(item_list_t *support, int idx, const char *prefix, char *out, int outSize)
{
    char path[256];
    const char *colon;
    const char *name;
    int isVcd, sourceMode, n;

    if (libListRowView(support, idx) != LIB_VIEW_PS1)
        return 0;

    if (support->mode == FAV_MODE) {
        isVcd = favGetItemKind(idx) == FAV_KIND_VCD;
        sourceMode = favGetItemSourceMode(idx);
    } else {
        const base_game_info_t *game = support->itemGet ? support->itemGet(support, idx) : NULL;
        isVcd = game != NULL && !strcasecmp(game->extension, ".VCD");
        sourceMode = support->mode;
    }

    if (!isVcd || !bdmModeIsUSB(sourceMode) || !prefix)
        return -1;
    colon = strchr(prefix, ':');
    name = support->itemGetName(support, idx);
    if (!colon || !name || !name[0])
        return -1;

    n = (int)(colon - prefix) + 1;
    if (snprintf(path, sizeof(path), "%.*s/POPS/%s.VCD", n, prefix, name) >= (int)sizeof(path))
        return -1;
    return raVcdWatchKey(path, out, outSize) == 0 ? 1 : -1;
}

static int watchListExists(const char *prefix, const char *serial)
{
    char path[256];
    struct stat st;

    if (prefix == NULL || serial == NULL || serial[0] == '\0')
        return 0;

    snprintf(path, sizeof(path), "%sRA/%s.wl", prefix, serial);
    if (stat(path, &st) == 0 && st.st_size > 0)
        return 1;

    /* The same fallback the loader uses: lists prepared on the PC live
       on the share. */
    if (strncmp(prefix, "smb0:", 5) != 0) {
        snprintf(path, sizeof(path), "smb0:RA/%s.wl", serial);
        if (stat(path, &st) == 0 && st.st_size > 0)
            return 1;
    }

    return 0;
}

void raBadgeRefresh(item_list_t *support, int count)
{
    struct ra_badge_slot *slot;
    const char *prefix;
    int i;

    if (support == NULL || support->itemGetName == NULL ||
        support->itemGetStartup == NULL ||
        (support->itemGetPrefix == NULL && support->mode != FAV_MODE))
        return;

    slot = slotFor(support);
    if (slot == NULL)
        return;

    if (slot->text != NULL) {
        free(slot->text);
        slot->text = NULL;
    }
    slot->count = 0;

    /* Switched off: return AFTER the clear above, never before it, so turning badges off
       drops the cache on the next list rebuild instead of freezing the last one on screen.
       raBadgeText reads this slot, and the cover mark rides on the same answer. */
    if (!gRATelemetry || !gRABadges)
        return;

    if (count <= 0)
        return;

    prefix = support->mode == FAV_MODE ? NULL : support->itemGetPrefix(support);
    if (support->mode != FAV_MODE && prefix == NULL)
        return;

    slot->text = malloc((size_t)count * RA_BADGE_TEXT);
    if (slot->text == NULL)
        return;

    slot->count = count;

    for (i = 0; i < count; i++) {
        char *dst = slot->text + (size_t)i * RA_BADGE_TEXT;
        const char *serial = support->itemGetStartup(support, i);
        const char *rowPrefix = support->mode == FAV_MODE ? favGetItemPrefix(i) : prefix;
        char ps1Key[16];
        int ps1 = badgeVcdKey(support, i, rowPrefix, ps1Key, sizeof(ps1Key));

        if (ps1 > 0)
            serial = ps1Key;
        else if (ps1 < 0)
            serial = NULL;

        if (watchListExists(rowPrefix, serial))
            snprintf(dst, RA_BADGE_TEXT, "%s%s", RA_BADGE,
                     support->itemGetName(support, i));
        else
            dst[0] = '\0'; /* empty means show the plain name */
    }
}

const char *raBadgeText(item_list_t *support, int idx)
{
    struct ra_badge_slot *slot = NULL;
    char *text;
    int i;

    for (i = 0; i < MODE_COUNT; i++)
        if (g_slots[i].support == support)
            slot = &g_slots[i];

    if (slot == NULL || slot->text == NULL || idx < 0 || idx >= slot->count)
        return NULL;

    text = slot->text + (size_t)idx * RA_BADGE_TEXT;

    return text[0] ? text : NULL;
}

#endif /* RETROACHIEVEMENTS */
