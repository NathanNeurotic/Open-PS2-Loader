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
    // Attributes for: AttributeImage
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

    int lastSelectedItemId;
    char lastSelectedStartup[256];
} items_list_t;

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

    void *extended;

    void (*drawElem)(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem);
    void (*endElem)(struct theme_element *elem);

    struct theme_element *next;
} theme_element_t;

typedef struct
{
    theme_element_t *first;
    theme_element_t *last;
    unsigned char needsItemConfig;
} theme_elems_t;

typedef struct
{
    char *filePath;
    char *name;
} theme_file_t;

typedef struct theme
{
    int useDefault;
    int usedHeight;

    unsigned char bgColor[3];
    u64 textColor;
    u64 uiTextColor;
    u64 selTextColor;

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

    theme_element_t *coverflow;
    int coverflowCoverOffset;

    int gameCacheCount;

    theme_element_t *itemsList;
    theme_element_t *loadingIcon;
    int loadingIconCount;
    int logoFrameCount; // count of contiguous animated boot-logo frames (0 = use single LOGO_PICTURE)

    GSTEXTURE textures[TEXTURES_COUNT];
    int fonts[THM_MAX_FONTS]; //!< Storage of font handles for removal once not needed
} theme_t;

extern theme_t *gTheme;

extern int gCoverflowCount, gCoverflowCenterScale, gCoverflowAnimSpeed, gCoverflowDimCovers;
void thmTriggerCoverflowAnim(int dir);

void thmInit(void);
void thmReinit(const char *path);
void thmReloadScreenExtents(void);
int thmAddElements(char *path, const char *separator, int forceRefresh);
const char *thmGetValue(void);
GSTEXTURE *thmGetTexture(unsigned int id);
void thmEnd(void);

// Indices are shifted in GUI, as we add the internal default theme at 0
int thmSetGuiValue(int themeID, int reload);
int thmGetGuiValue(void);
int thmFindGuiID(const char *theme);
const char **thmGetGuiList(void);
char *thmGetFilePath(int themeID);

#endif
