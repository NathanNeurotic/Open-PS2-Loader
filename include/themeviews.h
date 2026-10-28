#ifndef __THEMEVIEWS_H
#define __THEMEVIEWS_H

// Multi-view themes (design: KrahJohlito; plan: docs/MULTI-VIEW-THEMES-PLAN.md). One conf_theme.cfg can
// describe several views of the main and info pages. Unprefixed blocks (main<N>, appsInfo<N>, ...) are the
// base; a block named "<view>.<block>" (coverflow.main2) replaces that block in that view only, and
// "<view>.<key>" overrides a theme-wide key. Everything here is config-only, so it is host-testable.

#include <stddef.h>

#include "config.h"

enum ThemeView {
    THM_VIEW_LIST = 0,
    THM_VIEW_COVERFLOW,
    THM_VIEW_PSBBN,
    THM_VIEW_GRID,
    THM_VIEW_COUNT
};

// Longest "<view>." prefix plus a block name such as favsVcdInfo12.
#define THM_VIEW_BLOCK_NAME_LEN 40

// Theme keys.
#define THM_VIEW_KEY_VIEWS   "views"        // views=list,coverflow -- the views the theme supports, in ring order
#define THM_VIEW_KEY_DEFAULT "default_view" // default_view=coverflow -- used until the user picks one

const char *thmViewName(int view);
// THM_VIEW_* for a name ("list", "coverflow", "psbbn", "grid"; case-insensitive), -1 if unknown.
int thmViewFromName(const char *name);

// The view behind a theme name saved before views existed: "<Coverflow>" and "<PSBBN Flow>" were
// separate built-in themes and are now views of <OPL>. -1 for any other name.
int thmViewFromLegacyTheme(const char *themeName);

// Same presence rule as addGUIElem: a block is present when it has a _type or is switched off with
// <name>_enabled=0. An absent block lets a fallback chain move on.
int thmViewBlockPresent(config_set_t *themeConfig, const char *name);

// What a loaded theme offers, worked out once per load.
typedef struct
{
    int native;              // the view the base blocks draw (PSBBNFlow / Coverflow element, else List)
    unsigned int mask;       // views the user can pick: bit (1 << THM_VIEW_*)
    unsigned int blocksMask; // views the theme declares at least one "<view>." key for
    unsigned int ownMask;    // views with <view>.inherit=0: their blocks do not fall back to the base
    int defaultView;         // default_view= if the theme offers it, else native
} thm_view_info_t;

void thmViewScan(config_set_t *themeConfig, thm_view_info_t *info);

// The view to load: the requested one if the theme offers it, else its default.
int thmViewChoose(const thm_view_info_t *info, int requested);

// The block prefix for a chosen view: the view's name when the theme declares keys for it, else "" (the
// base), so themes without views pay no extra lookups.
const char *thmViewPrefix(const thm_view_info_t *info, int view);

// 1 when the chosen view's blocks fall back to the base blocks (the default), 0 for <view>.inherit=0: a
// view that brings its whole main/info layout (the built-in PSBBN Flow view does), so it needs no long
// list of <view>.main<N>_enabled=0 lines to hide base blocks it does not use.
int thmViewInheritsBase(const thm_view_info_t *info, int view);

// Block j of a family, resolved through its fallback chain: "<prefix>.<chain[0]><j>" ... then, when
// inheritBase is set, "<chain[0]><j>" ... -- the first present block wins. Writes its name to out; 0 when
// none is present.
int thmViewResolveSlot(config_set_t *themeConfig, const char *prefix, int inheritBase, const char *const *chain, int chainLen, int j, char *out, size_t outSize);

// Theme-wide keys with a per-view override: "<prefix>.<key>" first, then "<key>".
int thmViewGetInt(config_set_t *themeConfig, const char *prefix, const char *key, int *value);
int thmViewGetColor(config_set_t *themeConfig, const char *prefix, const char *key, unsigned char *color);

#endif
