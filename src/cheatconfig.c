/*
  Copyright 2026, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Remembered cheat picks, ported from upstream Open-PS2-Loader PR #1748 ("Persist per-game PS2RD
  cheat selections"). See include/cheatconfig.h. The picks live in the game's own CFG as numbered
  $CheatSelNNN values holding cheat NAMES, never list positions, so a .cht that gains, loses or
  reorders cheats still restores the right ones.
*/

#include "include/opl.h"
#include "include/config.h"
#include "include/cheatconfig.h"

#include <ctype.h>

// Lower case, leading and trailing spaces dropped, every inner run of spaces made one space.
static void cheatConfigNormalize(const char *source, char *out, size_t outSize)
{
    size_t len = 0;
    int pendingSpace = 0;

    if (outSize == 0)
        return;
    while (*source != NUL && isspace((unsigned char)*source))
        source++;
    while (*source != NUL && len + 1 < outSize) {
        unsigned char c = (unsigned char)*source++;
        if (isspace(c)) {
            pendingSpace = len > 0;
            continue;
        }
        if (pendingSpace) {
            out[len++] = SPACE;
            pendingSpace = 0;
        }
        out[len++] = tolower(c);
    }
    out[len] = NUL;
}

int cheatConfigIsMasterCode(const char *name)
{
    char normalized[CHEAT_NAME_MAX + 1];

    if (name == NULL)
        return 0;
    cheatConfigNormalize(name, normalized, sizeof(normalized));
    return !strcmp(normalized, "mastercode") || !strcmp(normalized, "master code") ||
           !strcmp(normalized, "enable code (must be on)");
}

static int cheatConfigNamesMatch(const char *a, const char *b)
{
    char na[CHEAT_NAME_MAX + 1], nb[CHEAT_NAME_MAX + 1];

    cheatConfigNormalize(a, na, sizeof(na));
    cheatConfigNormalize(b, nb, sizeof(nb));
    return !strcmp(na, nb);
}

void cheatConfigLoadSelections(config_set_t *configSet)
{
    char key[CONFIG_KEY_NAME_LEN];
    char saved[CONFIG_KEY_VALUE_LEN];
    int i, n;

    if (gCheats == NULL)
        return;

    // First use is safe: the master codes on, every optional cheat off.
    for (i = 0; i < MAX_CODES && gCheats[i].name[0] != NUL; i++)
        gCheats[i].enabled = cheatConfigIsMasterCode(gCheats[i].name);

    if (configSet == NULL)
        return;
    for (n = 0; n < MAX_CODES; n++) {
        snprintf(key, sizeof(key), "%s%03d", CONFIG_ITEM_CHEAT_SELECTION_PREFIX, n);
        if (!configGetStrCopy(configSet, key, saved, sizeof(saved)))
            break;
        for (i = 0; i < MAX_CODES && gCheats[i].name[0] != NUL; i++) {
            if (!cheatConfigIsMasterCode(gCheats[i].name) && cheatConfigNamesMatch(gCheats[i].name, saved)) {
                gCheats[i].enabled = 1;
                break;
            }
        }
    }
}

void cheatConfigSaveSelections(config_set_t *configSet)
{
    char key[CONFIG_KEY_NAME_LEN];
    int i, n = 0;

    if (configSet == NULL || gCheats == NULL)
        return;

    // Clear every earlier pick first: a shorter list must not leave old ones behind.
    for (i = 0; i < MAX_CODES; i++) {
        snprintf(key, sizeof(key), "%s%03d", CONFIG_ITEM_CHEAT_SELECTION_PREFIX, i);
        configRemoveKey(configSet, key);
    }
    for (i = 0; i < MAX_CODES && gCheats[i].name[0] != NUL; i++) {
        if (gCheats[i].enabled && !cheatConfigIsMasterCode(gCheats[i].name)) {
            snprintf(key, sizeof(key), "%s%03d", CONFIG_ITEM_CHEAT_SELECTION_PREFIX, n++);
            configSetStr(configSet, key, gCheats[i].name);
        }
    }
}
