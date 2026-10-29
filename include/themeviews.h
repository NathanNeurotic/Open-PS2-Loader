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
#define THM_VIEW_KEY_VIEWS   "views"        // views=list,coverflow -- the views the theme supports (L3 order is fixed)
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
    int native;              // the view the base blocks draw (PSBBNFlow / Coverflow / Grid element, else List)
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

// SD (4:3) and HD (16:9) layouts in one conf_theme.cfg (ideas: KrahJohlito's uOPL/wOPL wsX key and Berion's
// _sd/_hd suffixes). Any key may carry a display-mode variant: "<key>_hd" is used while the Widescreen
// display setting is on, "<key>_sd" while it is off, and the plain "<key>" otherwise -- so a theme without
// them loads exactly as before. "<name>_wsX" (the uOPL/wOPL element key) is read as "<name>_x_hd" unless
// the theme also gives that key. The chosen variants are copied over their plain keys once, right after the
// cfg is read, so every lookup (element blocks, "<view>." keys, theme globals) sees them without changes.
#define THM_LAYOUT_SUFFIX_SD   "_sd"
#define THM_LAYOUT_SUFFIX_HD   "_hd"
#define THM_LAYOUT_KEY_WSX     "_wsX"
#define THM_LAYOUT_KEY_AUTOFIT "hd_autofit" // hd_autofit=1: keep the 4:3 layout's proportions in 16:9 (thmLayoutAutoFitX)

// Apply the variants for wide (non-zero = 16:9). Returns 1 when the theme declares any _sd/_hd/_wsX key,
// i.e. when it looks different in the other mode and must be reloaded if the Widescreen setting changes.
int thmApplyDisplayLayout(config_set_t *themeConfig, int wide);

// hd_autofit: where an x on the 640-wide 4:3 grid lands in 16:9 so the whole 4:3 composition keeps its
// shape. Widescreen draws aspect-scaled widths at 3/4 but leaves positions alone, which opens gaps between
// neighbours; scaling each position by the same 3/4 about the screen centre closes them exactly, whatever
// the alignment (left edge, centre and right edge all move by the same rule).
int thmLayoutAutoFitX(int x, int screenWidth);

#endif
