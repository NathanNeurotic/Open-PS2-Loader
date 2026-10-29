// Multi-view theme resolution: which views a theme offers and which block each family slot uses in the
// active view. See include/themeviews.h and docs/MULTI-VIEW-THEMES-PLAN.md. Design: KrahJohlito.

#include "include/opl.h"
#include "include/themeviews.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>

static const char *const viewNames[THM_VIEW_COUNT] = {"list", "coverflow", "psbbn", "grid"};

const char *thmViewName(int view)
{
    return (view >= 0 && view < THM_VIEW_COUNT) ? viewNames[view] : "";
}

int thmViewFromName(const char *name)
{
    if (name == NULL)
        return -1;
    for (int v = 0; v < THM_VIEW_COUNT; v++) {
        if (strcasecmp(name, viewNames[v]) == 0)
            return v;
    }
    return -1;
}

// Key prefixes match exactly: the loader looks blocks up as "<lowercase view>.<key>" and config lookups are
// case-sensitive, so "Coverflow.main2" must not count as a coverflow block.
static int thmViewFromPrefix(const char *word)
{
    for (int v = 0; v < THM_VIEW_COUNT; v++) {
        if (strcmp(word, viewNames[v]) == 0)
            return v;
    }
    return -1;
}

int thmViewFromLegacyTheme(const char *themeName)
{
    if (themeName == NULL)
        return -1;
    if (strcasecmp(themeName, "<Coverflow>") == 0)
        return THM_VIEW_COVERFLOW;
    if (strcasecmp(themeName, "<PSBBN Flow>") == 0)
        return THM_VIEW_PSBBN;
    return -1;
}

int thmViewBlockPresent(config_set_t *themeConfig, const char *name)
{
    char key[CONFIG_KEY_NAME_LEN];
    const char *type = NULL;
    int enabled = 1;

    snprintf(key, sizeof(key), "%s_enabled", name);
    configGetInt(themeConfig, key, &enabled);
    if (!enabled)
        return 1;
    snprintf(key, sizeof(key), "%s_type", name);
    return configGetStr(themeConfig, key, &type) && type != NULL;
}

// The view the base blocks draw: the first main<j> that is a flow element decides, as the built-in
// <Coverflow> and <PSBBN Flow> themes did when they were separate themes.
static int thmViewNative(config_set_t *themeConfig)
{
    char key[CONFIG_KEY_NAME_LEN], name[THM_VIEW_BLOCK_NAME_LEN];
    const char *type;

    for (int j = 0;; j++) {
        snprintf(name, sizeof(name), "main%d", j);
        if (!thmViewBlockPresent(themeConfig, name))
            break;
        snprintf(key, sizeof(key), "%s_type", name);
        type = NULL;
        if (!configGetStr(themeConfig, key, &type) || type == NULL)
            continue; // switched off
        if (strcmp(type, "PSBBNFlow") == 0)
            return THM_VIEW_PSBBN;
        if (strcmp(type, "Coverflow") == 0)
            return THM_VIEW_COVERFLOW;
        if (strcmp(type, "Grid") == 0)
            return THM_VIEW_GRID;
    }
    return THM_VIEW_LIST;
}

// views=list, coverflow -> bits. Unknown names are skipped.
static unsigned int thmViewParseList(const char *value)
{
    char word[16];
    unsigned int mask = 0;
    size_t n;

    while (value != NULL && *value != '\0') {
        while (*value == ',' || *value == ' ' || *value == '\t')
            value++;
        n = strcspn(value, ", \t");
        if (n > 0 && n < sizeof(word)) {
            memcpy(word, value, n);
            word[n] = '\0';
            int v = thmViewFromName(word);
            if (v >= 0)
                mask |= 1u << v;
        }
        value += n;
    }
    return mask;
}

void thmViewScan(config_set_t *themeConfig, thm_view_info_t *info)
{
    const char *value = NULL;

    info->native = thmViewNative(themeConfig);
    info->blocksMask = 0;
    info->ownMask = 0;
    if (themeConfig != NULL) {
        for (const struct config_value_t *it = themeConfig->head; it != NULL; it = it->next) {
            const char *dot = strchr(it->key, '.');
            if (dot == NULL || dot == it->key || (size_t)(dot - it->key) >= 16)
                continue;
            char word[16];
            memcpy(word, it->key, dot - it->key);
            word[dot - it->key] = '\0';
            int v = thmViewFromPrefix(word);
            if (v < 0)
                continue;
            info->blocksMask |= 1u << v;
            if (strcmp(dot + 1, "inherit") == 0 && strcmp(it->val, "0") == 0)
                info->ownMask |= 1u << v;
        }
    }

    // views= is authoritative when it names at least one view we know. Without it, the theme offers its
    // native view plus every view it declares keys for.
    info->mask = 0;
    if (configGetStr(themeConfig, THM_VIEW_KEY_VIEWS, &value))
        info->mask = thmViewParseList(value);
    if (info->mask == 0)
        info->mask = (1u << info->native) | info->blocksMask;

    info->defaultView = -1;
    value = NULL;
    if (configGetStr(themeConfig, THM_VIEW_KEY_DEFAULT, &value)) {
        int v = thmViewFromName(value);
        if (v >= 0 && (info->mask & (1u << v)))
            info->defaultView = v;
    }
    if (info->defaultView < 0) {
        if (info->mask & (1u << info->native))
            info->defaultView = info->native;
        else {
            for (int v = 0; v < THM_VIEW_COUNT; v++) {
                if (info->mask & (1u << v)) {
                    info->defaultView = v;
                    break;
                }
            }
        }
    }
}

int thmViewChoose(const thm_view_info_t *info, int requested)
{
    if (requested >= 0 && requested < THM_VIEW_COUNT && (info->mask & (1u << requested)))
        return requested;
    return info->defaultView;
}

const char *thmViewPrefix(const thm_view_info_t *info, int view)
{
    if (view < 0 || view >= THM_VIEW_COUNT || !(info->blocksMask & (1u << view)))
        return "";
    return viewNames[view];
}

int thmViewInheritsBase(const thm_view_info_t *info, int view)
{
    return view < 0 || view >= THM_VIEW_COUNT || !(info->ownMask & (1u << view));
}

int thmViewResolveSlot(config_set_t *themeConfig, const char *prefix, int inheritBase, const char *const *chain, int chainLen, int j, char *out, size_t outSize)
{
    int c;

    if (prefix != NULL && prefix[0] != '\0') {
        for (c = 0; c < chainLen; c++) {
            snprintf(out, outSize, "%s.%s%d", prefix, chain[c], j);
            if (thmViewBlockPresent(themeConfig, out))
                return 1;
        }
        if (!inheritBase) {
            out[0] = '\0';
            return 0;
        }
    }
    for (c = 0; c < chainLen; c++) {
        snprintf(out, outSize, "%s%d", chain[c], j);
        if (thmViewBlockPresent(themeConfig, out))
            return 1;
    }
    out[0] = '\0';
    return 0;
}

int thmViewGetInt(config_set_t *themeConfig, const char *prefix, const char *key, int *value)
{
    if (prefix != NULL && prefix[0] != '\0') {
        char viewKey[CONFIG_KEY_NAME_LEN];
        snprintf(viewKey, sizeof(viewKey), "%s.%s", prefix, key);
        if (configGetInt(themeConfig, viewKey, value))
            return 1;
    }
    return configGetInt(themeConfig, key, value);
}

int thmViewGetColor(config_set_t *themeConfig, const char *prefix, const char *key, unsigned char *color)
{
    if (prefix != NULL && prefix[0] != '\0') {
        char viewKey[CONFIG_KEY_NAME_LEN];
        snprintf(viewKey, sizeof(viewKey), "%s.%s", prefix, key);
        if (configGetColor(themeConfig, viewKey, color))
            return 1;
    }
    return configGetColor(themeConfig, key, color);
}

static int thmKeyEndsWith(const char *key, size_t len, const char *suffix)
{
    size_t n = strlen(suffix);
    return len > n && strcmp(key + len - n, suffix) == 0;
}

int thmApplyDisplayLayout(config_set_t *themeConfig, int wide)
{
    char base[CONFIG_KEY_NAME_LEN], value[CONFIG_KEY_VALUE_LEN];
    const size_t wsxLen = strlen(THM_LAYOUT_KEY_WSX);
    int declared = 0;

    if (themeConfig == NULL)
        return 0;

    // Two passes so the outcome does not depend on the order of the lines: <name>_wsX first, then the
    // _sd/_hd variants, which therefore win over a _wsX for the same element. A copied key never ends in
    // a suffix itself, so the entries appended while walking are skipped by the same tests.
    for (int pass = 0; pass < 2; pass++) {
        for (const struct config_value_t *it = themeConfig->head; it != NULL; it = it->next) {
            size_t len = strlen(it->key);
            if (pass == 0) {
                if (!thmKeyEndsWith(it->key, len, THM_LAYOUT_KEY_WSX))
                    continue;
                declared = 1;
                if (!wide)
                    continue;
                snprintf(base, sizeof(base), "%.*s_x", (int)(len - wsxLen), it->key);
            } else {
                int hd = thmKeyEndsWith(it->key, len, THM_LAYOUT_SUFFIX_HD);
                if (!hd && !thmKeyEndsWith(it->key, len, THM_LAYOUT_SUFFIX_SD))
                    continue;
                declared = 1;
                if (hd != (wide != 0))
                    continue;
                snprintf(base, sizeof(base), "%.*s", (int)(len - strlen(THM_LAYOUT_SUFFIX_HD)), it->key);
            }
            // Copy first: setStr may append to the list being walked (never moves an existing entry).
            snprintf(value, sizeof(value), "%s", it->val);
            configSetStr(themeConfig, base, value);
        }
    }
    return declared;
}

int thmLayoutAutoFitX(int x, int screenWidth)
{
    int centre = screenWidth / 2;
    return centre + (x - centre) * 3 / 4;
}
