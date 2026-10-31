#ifndef __THEMES_H
#define __THEMES_H

#include "include/textures.h"
#include "include/texcache.h"
#include "include/menusys.h"

#define THM_MAX_FILES 64
#define THM_MAX_FONTS 16

typedef struct
{
    // optional, only for overlays
    int upperLeft_x;
    int upperLeft_y;
    int upperRight_x;
    int upperRight_y;
    int lowerLeft_x;
    int lowerLeft_y;
    int lowerRight_x;
    int lowerRight_y;

    // basic texture information
    char *name;
    GSTEXTURE source;
} image_texture_t;

typedef struct
{
    // AttributeImage cache identity. Both fields persist so genuine absence is
    // memoized rather than reopened every frame.
    int currentCacheId;
    int currentUid;
    u32 currentConfigId;
    char *currentValue;

    // Attributes  for: AttributeImage & GameImage
    image_cache_t *cache;
    int cacheLinked;

    // Attributes for: AttributeImage & GameImage & StaticImage
    image_texture_t *defaultTexture;
    int defaultTextureLinked;

    image_texture_t *overlayTexture;
    int overlayTextureLinked;

    // Second overlay layer drawn ON TOP of overlayTexture (the cover composite): the "foliage"
    // pass over the "plastic" frame, so a box needs no off-centre window shift (graphics-team FR).
    image_texture_t *overlayTexture2;
    int overlayTexture2Linked;
#ifdef RETROACHIEVEMENTS
    int raIsCover; // RA: this element shows the cover, so it gets the RA mark (set in initGameImage)
#endif

    // Background: the cache entry of the last game art it drew, kept on screen while the next game's art loads
    int lastCacheId;
    int lastUid;
} mutable_image_t;

typedef struct
{
    // Attributes for: AttributeText & StaticText
    char *value;
    int sizingMode;

    // Attributes for: AttributeText
    char *alias;
    int displayMode;

    u32 currentConfigId;
    char *currentValue;
    char *wrappedValue; // owned, word-wrapped copy of currentValue for SIZING_WRAP (issue #44)
} mutable_text_t;

typedef struct
{
    int displayedItems;

    const char *decorator;
    mutable_image_t *decoratorImage;
    // Non-owning link to the family's COV game-image element, set at theme validation for
    // Lists WITHOUT a decorator: lets drawItemsList warm the visible page's covers through
    // the normal cache path instead of loading them one highlight at a time (#296).
    struct theme_element *coverElem;
} items_list_t;

// Forward declaration: an element carries a back-pointer to the family it was parsed into (see
// theme_element_t::family), and theme_elems_t itself is defined below, after the element.
struct theme_elems;

typedef struct theme_element
{
    int type;
    int posX;
    int posY;
    short aligned;
    int width;
    int height;
    short scaled;
    u64 color;
    int font;
    int reflection;
    int reflectionOffset; // Coverflow: vertical px shift of the mirror (theme key reflection_offset; -up / +down)
    int showRun;          // InfoHintText: draw the Run hint (theme key <name>_show_run; default 1)
    // Per-device element filter (theme key devices=usb,hdd,...): bitmask over the thmDeviceVocab
    // table indices in themes.c. 0 = unfiltered (the pre-existing behavior). deviceCoverage is
    // filled at theme-load validation for UNFILTERED MenuIcon/ItemsList/HintText elements: the
    // union of their family's filtered same-type masks, so an unfiltered element can skip the
    // devices a filtered sibling covers without needing to know its family at draw time.
    int deviceFilter;
    int deviceCoverage;
    // Text elements (and ItemsList rows): how wide their text may run before it reaches another element
    // of the same screen or the screen edge, computed once at theme load (thmComputeTextRooms). Longer
    // text scrolls inside that width instead of drawing over the neighbour. 0 = not computed / not a text
    // element / too small to trust -> drawn exactly as before.
    int textRoom;

    // The family this element was parsed into (main/info x games/apps/favs/vcd). Non-owning, set
    // once at parse time. The per-row cover redirect (thmGetElemForItem) uses it to stay on the
    // SAME screen half: an info-screen cover must resolve to another INFO element, never to the
    // browse page's, whose coordinates belong to a different screen. NULL for the few elements
    // built outside addGUIElem (the auto-added background, the loading icon), none of which is
    // ever a redirect target -- the lookup matches GameImage/Coverflow by cover-cache suffix.
    struct theme_elems *family;

    // 1 when the element came from a FALLBACK block while parsing an opt-in Favorites per-kind family
    // (favsVcd* / favsApps*): the theme did not declare that slot, the parser copied the slot it would
    // otherwise have used. The per-row cover redirect only takes a cover the theme actually declared in
    // those families, so an inherited copy (e.g. favsAppsMain's copy of the portrait favsMain cover)
    // never replaces today's appsMain/vcdMain cover; likewise an inherited ItemsList leaves navigation on
    // the list that view used before (thmFamilyItemsList). Always 0 for every other family.
    unsigned char inherited;

    void *extended;

    void (*drawElem)(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem);
    void (*endElem)(struct theme_element *elem);

    struct theme_element *next;
} theme_element_t;

typedef struct theme_elems
{
    theme_element_t *first;
    theme_element_t *last;
    unsigned char needsItemConfig;
    // Set only when this family contains ItemText, the element that consumes the optional deep
    // VCD display ID. Keeps cosmetic disc-image inspection completely demand-driven.
    unsigned char needsVcdDisplayId;
    // Set when this family contains a SaveIcon, which reads the row's per-game VMC names: the
    // per-game config is then fetched for it, but only while 3D Save Icons is switched on.
    unsigned char needsSaveIconConfig;
    // Set when this family contains a Grid: Left/Right and Up/Down follow the grid on its pages only.
    unsigned char hasGrid;
} theme_elems_t;

typedef struct
{
    char *filePath;
    char *name;
} theme_file_t;

// The hints a theme names in hints_hide and hints_order (RIPPS2 build 90, akilluminati47)
enum {
    THM_HINT_MENU = 0,
    THM_HINT_RUN,
    THM_HINT_INFO,
    THM_HINT_OPTIONS,
    THM_HINT_REFRESH,
    THM_HINT_STAR,
    THM_HINT_VIEW,
    THM_HINT_COUNT
};

typedef struct theme
{
    int useDefault;
    int usedHeight;

    unsigned char bgColor[3];
    unsigned char plasBlendColor[3]; // plasma gradient LOW end (theme key plasma_blend_color); default black = historical look
    u64 textColor;
    u64 uiTextColor;
    u64 selTextColor;
    u64 titleColor; // game-list titles, so they can differ from general text (#464)

    theme_elems_t mainElems;
    theme_elems_t infoElems;
    theme_element_t *gamesItemsList;

    theme_elems_t appsMainElems;
    theme_elems_t appsInfoElems;
    theme_element_t *appsItemsList;

    // Favourites view: a third element family parsed exactly like appsMain*/appsInfo* (favsMain<N> /
    // favsInfo<N>, each falling back to main<N>/info<N>). The FAV screen renders these via menusys.
    theme_elems_t favsMainElems;
    theme_elems_t favsInfoElems;
    theme_element_t *favsItemsList;

    // VCD/PS1 view: a fourth element family parsed like favsMain*/favsInfo* (vcdMain<N> /
    // vcdInfo<N>, each falling back to main<N>/info<N>). Rendered when a device is in the L3
    // VCD view. Has its OWN optional ItemsList slot (vcdItemsList, the 4th) so the VCD list keeps a
    // SEPARATE cover cache from the games list -- the L3 toggle reuses the device's own game list
    // (same item ids), so a shared cache would thrash every toggle. Falls back to gamesItemsList at
    // render when the theme defines no 4th ItemsList.
    theme_elems_t vcdMainElems;
    theme_elems_t vcdInfoElems;
    theme_element_t *vcdItemsList;

    // Favourites per-kind families (opt-in): favsVcdMain<N>/favsVcdInfo<N> style the Favourites PS1
    // view and the PS1 covers on the All shelf; favsAppsMain<N>/favsAppsInfo<N> style the Favourites
    // ELF view and the app covers on the All shelf. Each is built ONLY when the theme declares at least
    // one block of it, so a theme without them leaves these empty and every consumer falls through to
    // today's families (vcd*, favs*/apps*). Undeclared slots of a built family fall back to the blocks
    // those views use today. They claim NO global ItemsList slot: an ItemsList parsed into them is a
    // slot-free element resolved per page (thmFamilyItemsList), like a devices=-filtered one.
    theme_elems_t favsVcdMainElems;
    theme_elems_t favsVcdInfoElems;
    theme_elems_t favsAppsMainElems;
    theme_elems_t favsAppsInfoElems;
    int parsingFavKindFamily; // parse-time only: addGUIElem must not claim an ItemsList slot

    // Multi-view themes (include/themeviews.h): the THM_VIEW_* this theme was built for, and the views it
    // offers as a (1 << THM_VIEW_*) mask.
    int view;
    unsigned int viewMask;
    int defaultView; // the view thmLoad picks when the request is -1 or not offered

    // SD/HD layouts (thmApplyDisplayLayout): the Widescreen setting this theme was built for, and whether
    // it looks different in the other mode (any _sd/_hd/_wsX key, or hd_autofit) -- then a change of the
    // setting reloads it (thmRefreshDisplayLayout).
    int layoutWide;
    int layoutDependsOnWide;

    theme_element_t *coverflow;
    theme_element_t *psbbnFlow;
    theme_element_t *grid; // first Grid element: Left/Right step a cover, Up/Down a row (themes.c)
    int gridRows, gridColumns, gridSpacing;
    int gridCounter;           // the "12/40" position under the grid (<block>_counter, default on)
    int gridTitle, gridTitleY; // the selected title under the grid at gridTitleY (<block>_title, default off)
    int gridTitleFont;         // ... in this font handle (<block>_title_font)
    int gridDevices;           // the device sidebar on the grid's left (<block>_devices, default on)
    int gridVignette;          // the other covers' vignette: 0 off, 1 weak, 2 full (<block>_vignette, default 1)
    int gridCoverless;         // a cover with no art: 0 the default art, 1 its name, 2 its serial (<block>_coverless)
    int gridFlip;              // the right stick turns the selected case to its back cover (<block>_flip, default on)
    int gridCellW, gridCellH;  // Grid Layout's cell, 0 for the element's own size
    int coverflowCoverOffset;

    int gameCacheCount;

    theme_element_t *itemsList;
    theme_element_t *loadingIcon;
    int loadingIconCount;
    int bdmIndexFixed;  // has its own five-dot BdmIndex pictures (Index_0) but none for fewer devices
    int logoFrameCount; // count of contiguous animated boot-logo frames (0 = use single LOGO_PICTURE)

    GSTEXTURE textures[TEXTURES_COUNT];
    int fonts[THM_MAX_FONTS]; //!< Storage of font handles for removal once not needed

    int glyphSetDef;     // the theme's glyph_set key (GLYPH_SET_*; THEME: its own PNGs)
    int glyphSetLoaded;  // the set its glyph textures hold now
    char glyphPath[256]; // the theme's folder, to load its own glyphs back ("" for the built-in theme)

    // The hint bar (RIPPS2 build 90): hints_hide, hints_order, hints_labels, hints_layout, hints_spacing
    int hintsHide;                  // 1 << THM_HINT_* for each hint the theme leaves off
    int hintsOrder[THM_HINT_COUNT]; // the hints named first, in this order
    int hintsOrderCount;
    int hintsLabels;  // 1 glyph and label (the default), 0 the glyph alone
    int hintsColumn;  // 1 one hint a line from the element's x/y down; 0 one row (the default)
    int hintsSpacing; // a column's line pitch
} theme_t;

// Button glyph sets (RIPPS2 build 90, akilluminati47): the theme's own PNGs, OPL's built-in ones, or one of two
// sets built in from RIPPS2 (Standard, drawn from its Adapt theme; White, from its Grunge theme). The order is the
// Interface page's and the saved setting's.
enum {
    GLYPH_SET_THEME = 0,
    GLYPH_SET_BUILTIN,
    GLYPH_SET_STANDARD,
    GLYPH_SET_WHITE,
    GLYPH_SET_COUNT
};

int thmGlyphSetParse(const char *name); // glyph_set=theme|builtin|standard|white; anything else is THEME
int thmGlyphSetFor(int themeSet);       // the set drawn: the user's pick, else the theme's
void thmGlyphSetRefresh(void);
int thmHintToken(int iconId);                          // THM_HINT_* of a hint, by its button
int thmHintParse(const char *list, int *out, int max); // "run,info menu" -> tokens, each once; returns the count
int thmHintRank(const theme_t *theme, int token);      // its place in hints_order; every unnamed hint shares the last          // GUI thread, under guiLock: swap the glyphs when the pick changed

extern theme_t *gTheme;

// The view the user asked for (THM_VIEW_*), -1 = the theme's default. Applied by the next theme load.
extern int gThemeViewRequest;

extern int gCoverflowCount, gCoverflowCenterScale, gCoverflowAnimSpeed, gCoverflowDimCovers;
void gridForgetItem(const void *item); // a list item is freed: drop its case-flip state (themes.c)
extern int gGridLayout;                // Grid Layout: 0 the theme's, 1..GRID_LAYOUTS RIPPS2's presets (grid.h)
void thmTriggerCoverflowAnim(int dir);
int thmCoverflowIsAnimating(void);

void thmInit(void);
void thmReinit(const char *path);
void thmReloadScreenExtents(void);
void thmRefreshFontSize(void);
int thmAddElements(char *path, const char *separator, int forceRefresh);
const char *thmGetValue(void);
GSTEXTURE *thmGetTexture(unsigned int id);
void thmEnd(void);

// Per-device ItemsList resolution (theme key devices=): returns the first ItemsList element in the
// family whose device filter matches iconId, else the given fallback -- so navigation math and the
// drawn rows always agree. fallback must follow the existing never-NULL slot chain.
theme_element_t *thmResolveItemsList(theme_elems_t *family, theme_element_t *fallback, int iconId);

// Items list for a page drawn from a Favourites per-kind family (favsVcd* / favsApps*). Those families
// own no global slot, so after the devices=-filtered match this returns the unfiltered ItemsList the
// theme declared in the family (the element actually drawn), and otherwise the given slot fallback --
// the list that view navigated with before the family existed.
theme_element_t *thmFamilyItemsList(theme_elems_t *family, theme_element_t *fallback, int iconId);

// Indices are shifted in GUI, as we add the internal default theme at 0
int thmSetGuiValue(int themeID, int reload);
int thmGetGuiValue(void);
// Ask for a view (THM_VIEW_*, -1 = the theme's default) and reload the active theme when that changes
// what is shown. Returns 1 when the theme was reloaded. GUI thread, outside a frame.
int thmSetView(int view);
// Switch to the next view the active theme offers (hold L3), Coverflow (3) and Coverflow (5) counting as
// two stops. Returns 1 when the view changed; a step between the two Coverflow stops does not reload.
int thmCycleView(void);
// Reload the active theme when the Widescreen setting no longer matches the layout it was built with (only
// for themes with SD/HD variants). Returns 1 when the theme was reloaded.
int thmRefreshDisplayLayout(void);
int thmFindGuiID(const char *theme);
int thmSavedThemePending(void); // the saved disk theme's drive has not offered it yet
const char **thmGetGuiList(void);
char *thmGetFilePath(int themeID);

#endif
