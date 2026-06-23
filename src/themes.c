#include "include/opl.h"
#include "include/themes.h"
#include "include/util.h"
#include "include/gui.h"
#include "include/renderman.h"
#include "include/textures.h"
#include "include/ioman.h"
#include "include/fntsys.h"
#include "include/lang.h"
#include "include/pad.h"
#include "include/sound.h"
#include "include/texcache.h"
#include "include/favsupport.h"

#include <time.h>
#include <math.h>

#define MENU_POS_V               50
#define HINT_HEIGHT              32
#define DECORATOR_SIZE           20
#define APP_PREFETCH_IDLE_FRAMES 10

extern const char conf_theme_OPL_cfg;
extern u16 size_conf_theme_OPL_cfg;
extern const char theme_coverflow_cfg;
extern u16 size_theme_coverflow_cfg;

theme_t *gTheme;

// Set transiently around thmLoad(NULL) to load the embedded coverflow theme instead of
// the default OPL theme (the built-in "<Coverflow>" entry in the theme list).
static int gLoadCoverflowBuiltin = 0;

static int screenWidth;
static int screenHeight;
static int guiThemeID = 0;

static int nThemes = 0;
static theme_file_t themes[THM_MAX_FILES];
static const char **guiThemesNames = NULL;

// Coverflow render-mode state (externs in themes.h; defaults match wOPL 3/30/200/0).
#define COVERFLOW_MAX 5
int gCoverflowCount = 3;        // 3 or 5 only (clamped on load AND at draw)
int gCoverflowCenterScale = 30; // px added to the center cover (UI 0/15/30/45)
int gCoverflowAnimSpeed = 200;  // ms (UI 0/100/200/400; 0 = instant, no anim)
int gCoverflowDimCovers = 0;    // bool

// Coverflow slide animation (cubic ease-out); armed by thmTriggerCoverflowAnim().
static int cfIsAnimating = 0;
static int cfAnimDirection = 0;
static clock_t cfAnimStartTime = 0;

enum ELEM_ATTRIBUTE_TYPE {
    ELEM_TYPE_ATTRIBUTE_TEXT = 0,
    ELEM_TYPE_STATIC_TEXT,
    ELEM_TYPE_ATTRIBUTE_IMAGE,
    ELEM_TYPE_GAME_IMAGE,
    ELEM_TYPE_STATIC_IMAGE,
    ELEM_TYPE_BACKGROUND, // A static image can be specified as the background. Otherwise, the plasma background will be drawn.
    ELEM_TYPE_MENU_ICON,
    ELEM_TYPE_MENU_TEXT,
    ELEM_TYPE_ITEMS_LIST,
    ELEM_TYPE_ITEM_ICON,
    ELEM_TYPE_ITEM_COVER,
    ELEM_TYPE_ITEM_TEXT,
    ELEM_TYPE_HINT_TEXT,
    ELEM_TYPE_INFO_HINT_TEXT,
    ELEM_TYPE_LOADING_ICON,
    ELEM_TYPE_BDM_INDEX,
    ELEM_TYPE_GAME_COUNT_TEXT,
    ELEM_TYPE_COVERFLOW,
    ELEM_TYPE_COUNT
};

#define DISPLAY_ALWAYS  0
#define DISPLAY_DEFINED 1
#define DISPLAY_NEVER   2

#define SIZING_NONE -1
#define SIZING_CLIP 0
#define SIZING_WRAP 1

static const char *elementsType[ELEM_TYPE_COUNT] = {
    "AttributeText",
    "StaticText",
    "AttributeImage",
    "GameImage",
    "StaticImage",
    "Background",
    "MenuIcon",
    "MenuText",
    "ItemsList",
    "ItemIcon",
    "ItemCover",
    "ItemText",
    "HintText",
    "InfoHintText",
    "LoadingIcon",
    "BdmIndex",
    "GameCountText",
    "Coverflow"};

// Common functions for Text ////////////////////////////////////////////////////////////////////////////////////////////////

static void endMutableText(theme_element_t *elem)
{
    mutable_text_t *mutableText = (mutable_text_t *)elem->extended;
    if (mutableText) {
        if (mutableText->value)
            free(mutableText->value);

        if (mutableText->alias)
            free(mutableText->alias);

        if (mutableText->wrappedValue)
            free(mutableText->wrappedValue);

        free(mutableText);
    }

    free(elem);
}

static mutable_text_t *initMutableText(const char *themePath, config_set_t *themeConfig, theme_t *theme, const char *name, int type, struct theme_element *elem, const char *value, const char *alias, int displayMode, int sizingMode)
{
    mutable_text_t *mutableText = (mutable_text_t *)malloc(sizeof(mutable_text_t));
    mutableText->currentConfigId = 0;
    mutableText->currentValue = NULL;
    mutableText->wrappedValue = NULL;
    mutableText->alias = NULL;

    char elemProp[64];

    snprintf(elemProp, sizeof(elemProp), "%s_display", name);
    configGetInt(themeConfig, elemProp, &displayMode);
    mutableText->displayMode = displayMode;

    int length = strlen(value) + 1;
    mutableText->value = (char *)malloc(length * sizeof(char));
    memcpy(mutableText->value, value, length);

    snprintf(elemProp, sizeof(elemProp), "%s_wrap", name);
    if (configGetInt(themeConfig, elemProp, &sizingMode)) {
        if (sizingMode > 0)
            sizingMode = SIZING_WRAP;
    }

    if ((elem->width != DIM_UNDEF) || (elem->height != DIM_UNDEF)) {
        if (sizingMode == SIZING_NONE)
            sizingMode = SIZING_CLIP;

        if (elem->width == DIM_UNDEF)
            elem->width = screenWidth;

        if (elem->height == DIM_UNDEF)
            elem->height = screenHeight;
    } else
        sizingMode = SIZING_NONE;
    mutableText->sizingMode = sizingMode;

    if (type == ELEM_TYPE_ATTRIBUTE_TEXT) {
        snprintf(elemProp, sizeof(elemProp), "%s_title", name);
        configGetStr(themeConfig, elemProp, &alias);
        if (!alias) {
            if (value[0] == '#')
                alias = &value[1];
            else
                alias = value;
        }

        char *temp;
        if (!strncmp(alias, "Title", 5))
            temp = _l(_STR_INFO_TITLE);
        else if (!strncmp(alias, "Genre", 5))
            temp = _l(_STR_INFO_GENRE);
        else if (!strncmp(alias, "Release", 7))
            temp = _l(_STR_INFO_RELEASE);
        else if (!strncmp(alias, "Developer", 9))
            temp = _l(_STR_INFO_DEVELOPER);
        else if (!strncmp(alias, "Size", 4))
            temp = _l(_STR_SIZE);
        else if (!strncmp(alias, "Description", 11))
            temp = _l(_STR_INFO_DESCRIPTION);
        else
            temp = (char *)alias;

        length = strlen(temp) + 1 + 2;
        mutableText->alias = (char *)calloc(length, sizeof(char));
        if (mutableText->sizingMode == SIZING_WRAP)
            snprintf(mutableText->alias, length, "%s:\n", temp);
        else
            snprintf(mutableText->alias, length, "%s: ", temp);
    } else {
        if (mutableText->sizingMode == SIZING_WRAP)
            fntFitString(elem->font, mutableText->value, elem->width);
    }

    return mutableText;
}

// StaticText ///////////////////////////////////////////////////////////////////////////////////////////////////////////////

static void drawStaticText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    mutable_text_t *mutableText = (mutable_text_t *)elem->extended;
    if (mutableText->sizingMode == SIZING_NONE)
        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, mutableText->value, elem->color);
    else
        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, mutableText->value, elem->color);
}

static void initStaticText(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name)
{
    const char *value = NULL; // configGetStr leaves this untouched if the key is absent
    char elemProp[64];

    snprintf(elemProp, sizeof(elemProp), "%s_value", name);
    configGetStr(themeConfig, elemProp, &value);
    if (value) {
        elem->extended = initMutableText(themePath, themeConfig, theme, name, ELEM_TYPE_STATIC_TEXT, elem, value, NULL, DISPLAY_ALWAYS, SIZING_NONE);
        elem->endElem = &endMutableText;
        elem->drawElem = &drawStaticText;
    } else
        LOG("THEMES StaticText %s: NO value, elem disabled !!\n", name);
}

// GameCountText ////////////////////////////////////////////////////////////////////////////////////////////////////////////

static int getGameCount(void *support)
{
    item_list_t *list = (item_list_t *)support;
    return list->itemGetCount(list);
}

static void drawGameCountText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    mutable_text_t *mutableText = (mutable_text_t *)elem->extended;

    if (config) {
        if (mutableText->currentConfigId != config->uid) {
            // force refresh
            mutableText->currentConfigId = config->uid;

            int count = getGameCount(menu->item->userdata);
            snprintf(mutableText->value, sizeof(char) * 60, _l(_STR_FILE_COUNT), count);
        }
    }

    fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, mutableText->value, elem->color);
}

static void initGameCountText(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name)
{
    /* drawGameCountText() snprintf()s up to 60 bytes into mutableText->value.
     * initMutableText() sizes value from strlen(seed)+1, so seeding with an
     * empty string previously produced a 1-byte buffer that the 60-byte
     * snprintf overran (and the separate 60-byte countStr was leaked).  Seed
     * with "" then replace value with a correctly sized 60-byte buffer. */
    mutable_text_t *mutableText = initMutableText(themePath, themeConfig, theme, name, ELEM_TYPE_ATTRIBUTE_TEXT, elem, "", NULL, DISPLAY_ALWAYS, SIZING_NONE);
    elem->extended = mutableText;

    if (mutableText != NULL) {
        char *countStr = (char *)malloc(60);
        if (countStr != NULL) {
            countStr[0] = '\0';
            free(mutableText->value);
            mutableText->value = countStr;
        }
    }

    elem->endElem = &endMutableText;
    elem->drawElem = &drawGameCountText;
}

// AttributeText ////////////////////////////////////////////////////////////////////////////////////////////////////////////

static void drawAttributeText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    // No current item (e.g. the last favourite was removed -> empty list): clear, don't redraw the
    // stale cached value. Mirrors drawGameImage's `if (item)` guard so the description clears (#48).
    if (item == NULL)
        return;
    mutable_text_t *mutableText = (mutable_text_t *)elem->extended;
    if (config) {
        if (mutableText->currentConfigId != config->uid) {
            // force refresh
            mutableText->currentConfigId = config->uid;
            mutableText->currentValue = NULL;
            if (configGetStr(config, mutableText->value, (const char **)&mutableText->currentValue)) {
                if ((mutableText->sizingMode == SIZING_WRAP) && mutableText->currentValue) {
                    // Word-wrap a private copy, not the config's own stored string.
                    // configGetStr() hands back a pointer straight into the config
                    // buffer (it->val); fntFitString() inserts '\n's in place, so
                    // wrapping currentValue directly would bake the line breaks into
                    // the stored value. Those then get written back to the .cfg on the
                    // next settings save, corrupting the field (issue #44). Copying
                    // first keeps the on-screen wrapping while leaving the value intact.
                    free(mutableText->wrappedValue);
                    mutableText->wrappedValue = NULL;
                    size_t len = strlen(mutableText->currentValue) + 1;
                    char *wrapped = (char *)malloc(len);
                    if (wrapped) {
                        memcpy(wrapped, mutableText->currentValue, len);
                        fntFitString(elem->font, wrapped, elem->width);
                        mutableText->wrappedValue = wrapped;
                        mutableText->currentValue = wrapped;
                    }
                }
            }
        }
        if (mutableText->currentValue) {
            char result[300];
            if (mutableText->displayMode == DISPLAY_NEVER) {
                if (!strncmp(mutableText->alias, _l(_STR_SIZE), strlen(_l(_STR_SIZE)))) {
                    snprintf(result, sizeof(result), "%s MiB", mutableText->currentValue);
                    if (mutableText->sizingMode == SIZING_NONE)
                        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, result, elem->color);
                    else
                        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, result, elem->color);
                } else {
                    if (mutableText->sizingMode == SIZING_NONE)
                        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, mutableText->currentValue, elem->color);
                    else
                        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, mutableText->currentValue, elem->color);
                }
            } else {
                if (!strncmp(mutableText->alias, _l(_STR_SIZE), strlen(_l(_STR_SIZE))))
                    snprintf(result, sizeof(result), "%s%s MiB", mutableText->alias, mutableText->currentValue);
                else
                    snprintf(result, sizeof(result), "%s%s", mutableText->alias, mutableText->currentValue);
                if (mutableText->sizingMode == SIZING_NONE)
                    fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, result, elem->color);
                else
                    fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, result, elem->color);
            }
            return;
        }
    }
    if (mutableText->displayMode == DISPLAY_ALWAYS) {
        if (mutableText->sizingMode == SIZING_NONE)
            fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, mutableText->alias, elem->color);
        else
            fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, mutableText->alias, elem->color);
    }
}

static void initAttributeText(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name)
{
    const char *attribute = NULL; // configGetStr leaves this untouched if the key is absent
    char elemProp[64];

    snprintf(elemProp, sizeof(elemProp), "%s_attribute", name);
    configGetStr(themeConfig, elemProp, &attribute);
    if (attribute) {
        elem->extended = initMutableText(themePath, themeConfig, theme, name, ELEM_TYPE_ATTRIBUTE_TEXT, elem, attribute, NULL, DISPLAY_ALWAYS, SIZING_NONE);
        elem->endElem = &endMutableText;
        elem->drawElem = &drawAttributeText;
    } else
        LOG("THEMES AttributeText %s: NO attribute, elem disabled !!\n", name);
}

// Common functions for Image ///////////////////////////////////////////////////////////////////////////////////////////////

static void findDuplicate(theme_element_t *first, const char *cachePattern, const char *defaultTexture, const char *overlayTexture, const char *overlayTexture2, mutable_image_t *target)
{
    theme_element_t *elem = first;
    while (elem) {
        if ((elem->type == ELEM_TYPE_STATIC_IMAGE) || (elem->type == ELEM_TYPE_ATTRIBUTE_IMAGE) || (elem->type == ELEM_TYPE_GAME_IMAGE) || (elem->type == ELEM_TYPE_BACKGROUND)) {
            mutable_image_t *source = (mutable_image_t *)elem->extended;

            if (cachePattern && source->cache && !strcmp(cachePattern, source->cache->suffix)) {
                target->cache = source->cache;
                target->cacheLinked = 1;
                LOG("THEMES Re-using a cache for pattern %s\n", cachePattern);
            }

            if (defaultTexture && source->defaultTexture && !strcmp(defaultTexture, source->defaultTexture->name)) {
                target->defaultTexture = source->defaultTexture;
                target->defaultTextureLinked = 1;
                LOG("THEMES Re-using the default texture for %s\n", defaultTexture);
            }

            if (overlayTexture && source->overlayTexture && !strcmp(overlayTexture, source->overlayTexture->name)) {
                target->overlayTexture = source->overlayTexture;
                target->overlayTextureLinked = 1;
                LOG("THEMES Re-using the overlay texture for %s\n", overlayTexture);
            }

            if (overlayTexture2 && source->overlayTexture2 && !strcmp(overlayTexture2, source->overlayTexture2->name)) {
                target->overlayTexture2 = source->overlayTexture2;
                target->overlayTexture2Linked = 1;
                LOG("THEMES Re-using the overlay2 texture for %s\n", overlayTexture2);
            }
        }

        elem = elem->next;
    }
}

static void freeImageTexture(image_texture_t *texture)
{
    if (texture) {
        if (texture->source.Mem) {
            rmUnloadTexture(&texture->source);
            free(texture->source.Mem);
            texture->source.Mem = NULL;
        }
        if (texture->source.Clut) {
            free(texture->source.Clut);
            texture->source.Clut = NULL;
        }
        if (texture->name) {
            free(texture->name);
            texture->name = NULL;
        }
        free(texture);
    }
}

static image_texture_t *initImageTexture(const char *themePath, config_set_t *themeConfig, const char *name, const char *imgName, int isOverlay)
{
    // calloc so omitted overlay coordinate keys default to 0 instead of
    // uninitialized heap garbage that would feed rmDrawOverlayPixmap.
    image_texture_t *texture = (image_texture_t *)calloc(1, sizeof(image_texture_t));
    texture->name = NULL;

    int texId = -1;
    int result = 0;

    // Propagate the actual load result so a missing/corrupt texture takes the
    // free-and-return-NULL path below instead of becoming a live element whose
    // source.Mem is NULL (the empty `if (...) ;` previously discarded it).
    if (themePath) {
        char path[256];
        snprintf(path, sizeof(path), "%s%s", themePath, imgName);
        result = (texDiscoverLoad(&texture->source, path, texId) >= 0);
    } else {
        texId = texLookupInternalTexId(imgName);
        result = (texLoadInternal(&texture->source, texId) >= 0);
    }

    if (result) {
        int length = strlen(imgName) + 1;
        texture->name = (char *)malloc(length * sizeof(char));
        memcpy(texture->name, imgName, length);

        if (isOverlay) {
            int intValue;
            char elemProp[64];
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_ulx", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->upperLeft_x = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_uly", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->upperLeft_y = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_urx", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->upperRight_x = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_ury", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->upperRight_y = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_llx", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->lowerLeft_x = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_lly", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->lowerLeft_y = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_lrx", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->lowerRight_x = intValue;
            snprintf(elemProp, sizeof(elemProp), "%s_overlay_lry", name);
            if (configGetInt(themeConfig, elemProp, &intValue))
                texture->lowerRight_y = intValue;
        }
    } else {
        freeImageTexture(texture);
        texture = NULL;
    }

    return texture;
}

static image_texture_t *initImageInternalTexture(config_set_t *themeConfig, const char *name)
{
    // calloc so the embedded source GSTEXTURE is zeroed: if texLookupInternalTexId
    // fails below, freeImageTexture() reads texture->source.Mem/.Clut and must not
    // see uninitialized garbage (which it would rmUnloadTexture()/free()).
    image_texture_t *texture = (image_texture_t *)calloc(1, sizeof(image_texture_t));
    texture->name = NULL;
    int result;

    if ((result = texLookupInternalTexId(name)) >= 0) {
        result = texLoadInternal(&texture->source, result);
        int length = strlen(name) + 1;
        texture->name = (char *)malloc(length * sizeof(char));
        memcpy(texture->name, name, length);
    }

    if (result < 0) {
        freeImageTexture(texture);
        texture = NULL;
    }

    return texture;
}

static void endMutableImage(struct theme_element *elem)
{
    mutable_image_t *mutableImage = (mutable_image_t *)elem->extended;
    if (mutableImage) {
        if (mutableImage->cache && !mutableImage->cacheLinked)
            cacheDestroyCache(mutableImage->cache);

        if (mutableImage->defaultTexture && !mutableImage->defaultTextureLinked)
            freeImageTexture(mutableImage->defaultTexture);

        if (mutableImage->overlayTexture && !mutableImage->overlayTextureLinked)
            freeImageTexture(mutableImage->overlayTexture);

        if (mutableImage->overlayTexture2 && !mutableImage->overlayTexture2Linked)
            freeImageTexture(mutableImage->overlayTexture2);

        free(mutableImage);
    }

    free(elem);
}

static mutable_image_t *initMutableImage(const char *themePath, config_set_t *themeConfig, theme_t *theme, const char *name, int type, const char *cachePattern, int cacheCount, const char *defaultTexture, const char *overlayTexture)
{
    mutable_image_t *mutableImage = (mutable_image_t *)malloc(sizeof(mutable_image_t));
    mutableImage->currentUid = -1;
    mutableImage->currentConfigId = 0;
    mutableImage->currentValue = NULL;
    mutableImage->cache = NULL;
    mutableImage->cacheLinked = 0;
    mutableImage->defaultTexture = NULL;
    mutableImage->defaultTextureLinked = 0;
    mutableImage->overlayTexture = NULL;
    mutableImage->overlayTextureLinked = 0;
    mutableImage->overlayTexture2 = NULL;
    mutableImage->overlayTexture2Linked = 0;

    char elemProp[64];

    if (type == ELEM_TYPE_ATTRIBUTE_IMAGE) {
        snprintf(elemProp, sizeof(elemProp), "%s_attribute", name);
        configGetStr(themeConfig, elemProp, &cachePattern);
        LOG("THEMES MutableImage %s: type: %s using cache pattern: %s\n", name, elementsType[type], cachePattern);
    } else if ((type == ELEM_TYPE_GAME_IMAGE) || (type == ELEM_TYPE_BACKGROUND)) {
        snprintf(elemProp, sizeof(elemProp), "%s_pattern", name);
        configGetStr(themeConfig, elemProp, &cachePattern);
        snprintf(elemProp, sizeof(elemProp), "%s_count", name);
        configGetInt(themeConfig, elemProp, &cacheCount);
        if (cachePattern != NULL && strcmp(cachePattern, "COV") == 0 && cacheCount < 2)
            cacheCount = 2;
        LOG("THEMES MutableImage %s: type: %s using cache pattern: %s count: %d\n", name, elementsType[type], cachePattern, cacheCount);
    }

    snprintf(elemProp, sizeof(elemProp), "%s_default", name);
    configGetStr(themeConfig, elemProp, &defaultTexture);

    if (type != ELEM_TYPE_BACKGROUND) {
        snprintf(elemProp, sizeof(elemProp), "%s_overlay", name);
        configGetStr(themeConfig, elemProp, &overlayTexture);
    }

    const char *overlayTexture2 = NULL;
    if (type != ELEM_TYPE_BACKGROUND) {
        snprintf(elemProp, sizeof(elemProp), "%s_overlay2", name);
        configGetStr(themeConfig, elemProp, &overlayTexture2);
    }

    findDuplicate(theme->mainElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->infoElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->appsMainElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->appsInfoElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->favsMainElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->favsInfoElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->vcdMainElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);
    findDuplicate(theme->vcdInfoElems.first, cachePattern, defaultTexture, overlayTexture, overlayTexture2, mutableImage);

    if (cachePattern && !mutableImage->cache) {
        if (type == ELEM_TYPE_ATTRIBUTE_IMAGE)
            mutableImage->cache = cacheInitCache(-1, themePath, 0, cachePattern, 1);
        else
            mutableImage->cache = cacheInitCache(theme->gameCacheCount++, "ART", 1, cachePattern, cacheCount);
    }

    if (!themePath)
        if (defaultTexture && !mutableImage->defaultTexture)
            mutableImage->defaultTexture = initImageInternalTexture(themeConfig, defaultTexture);

    if (defaultTexture && !mutableImage->defaultTexture)
        mutableImage->defaultTexture = initImageTexture(themePath, themeConfig, name, defaultTexture, 0);

    if (overlayTexture && !mutableImage->overlayTexture)
        mutableImage->overlayTexture = initImageTexture(themePath, themeConfig, name, overlayTexture, 1);

    // overlay2 is drawn over the cover composite (plain rmDrawPixmap), so it needs no cover-window
    // corners -- load it as a plain texture (isOverlay=0).
    if (overlayTexture2 && !mutableImage->overlayTexture2)
        mutableImage->overlayTexture2 = initImageTexture(themePath, themeConfig, name, overlayTexture2, 0);

    return mutableImage;
}

// StaticImage //////////////////////////////////////////////////////////////////////////////////////////////////////////////

static void drawStaticImage(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    mutable_image_t *staticImage = (mutable_image_t *)elem->extended;
    if (staticImage->overlayTexture) {
        rmDrawOverlayPixmap(&staticImage->overlayTexture->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol,
                            &staticImage->defaultTexture->source, staticImage->overlayTexture->upperLeft_x, staticImage->overlayTexture->upperLeft_y, staticImage->overlayTexture->upperRight_x, staticImage->overlayTexture->upperRight_y,
                            staticImage->overlayTexture->lowerLeft_x, staticImage->overlayTexture->lowerLeft_y, staticImage->overlayTexture->lowerRight_x, staticImage->overlayTexture->lowerRight_y, 0);
        if (staticImage->overlayTexture2)
            rmDrawPixmap(&staticImage->overlayTexture2->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
    } else
        rmDrawPixmap(&staticImage->defaultTexture->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
}

static void initStaticImage(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name, const char *imageName)
{
    mutable_image_t *mutableImage = initMutableImage(themePath, themeConfig, theme, name, elem->type, NULL, 0, imageName, NULL);
    elem->extended = mutableImage;
    elem->endElem = &endMutableImage;

    if (mutableImage->defaultTexture)
        elem->drawElem = &drawStaticImage;
    else
        LOG("THEMES StaticImage %s: NO image name, elem disabled !!\n", name);
}

// GameImage ////////////////////////////////////////////////////////////////////////////////////////////////////////////////

static GSTEXTURE *getGameImageTexture(image_cache_t *cache, void *support, struct submenu_item *item)
{
    if (gEnableArt) {
        item_list_t *list = (item_list_t *)support;
        char *startup = list->itemGetStartup(list, item->id);
        return cacheGetTexture(cache, list, &item->cache_id[cache->userId], &item->cache_uid[cache->userId], startup);
    }

    return NULL;
}

static int canPrefetchAdjacentGameImages(image_cache_t *cache, item_list_t *list, GSTEXTURE *selectedTexture)
{
    if (cache == NULL || list == NULL || selectedTexture == NULL || selectedTexture->Mem == NULL)
        return 0;

    if (list->mode == MMCE_MODE)
        return 0;

    if (list->mode == APP_MODE) {
        if (guiInactiveFrames < APP_PREFETCH_IDLE_FRAMES || cacheHasPendingInteractiveArt())
            return 0;
    }

    return 1;
}

static void prefetchGameImageTexture(image_cache_t *cache, void *support, struct submenu_list *item, int minInactiveFrames)
{
    item_list_t *list;
    char *startup;

    if (cache == NULL || item == NULL || guiInactiveFrames < minInactiveFrames)
        return;

    list = (item_list_t *)support;
    if (list == NULL)
        return;

    startup = list->itemGetStartup(list, item->item.id);
    cachePrefetchTexture(cache, list, &item->item.cache_id[cache->userId], &item->item.cache_uid[cache->userId], startup);
}

static void prefetchAdjacentGameImages(image_cache_t *cache, void *support, struct submenu_list *item, int distance, int minInactiveFrames)
{
    struct submenu_list *nextItem = item;
    struct submenu_list *prevItem = item;

    if (item == NULL || distance <= 0)
        return;

    for (int i = 0; i < distance; i++) {
        if (nextItem != NULL)
            nextItem = nextItem->next;
        if (prevItem != NULL)
            prevItem = prevItem->prev;

        prefetchGameImageTexture(cache, support, nextItem, minInactiveFrames);
        prefetchGameImageTexture(cache, support, prevItem, minInactiveFrames);
    }
}

// Favourites element redirection (defined in the Coverflow section below; used by both draw
// paths so an APP favourite renders with the apps element, not the game cover element).
static theme_element_t *thmGetElemForItem(struct menu_list *menu, struct submenu_list *item, theme_element_t *elem);

static void drawGameImage(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    if (item) {
        item_list_t *list = (item_list_t *)menu->item->userdata;

        // On the Favourites tab an APP favourite draws with the theme's apps element (its own
        // dimensions, case overlay and art folder); games and every other tab use elem as-is.
        // The texture lookup stays on menu->item->userdata (favList) so favGetImage proxies by
        // the FAV index -- only the element (geometry + cache + overlay) is redirected.
        struct theme_element *drawElem = thmGetElemForItem(menu, item, elem);
        mutable_image_t *gameImage = (mutable_image_t *)drawElem->extended;
        if (gameImage == NULL)
            return;

        GSTEXTURE *texture = getGameImageTexture(gameImage->cache, menu->item->userdata, &item->item);

        if (gameImage->cache != NULL && gameImage->cache->suffix != NULL && strcmp(gameImage->cache->suffix, "COV") == 0 &&
            canPrefetchAdjacentGameImages(gameImage->cache, list, texture)) {
            int prefetchInactiveFrames = (list != NULL && list->mode == APP_MODE) ? APP_PREFETCH_IDLE_FRAMES : MENU_MIN_INACTIVE_FRAMES;
            prefetchAdjacentGameImages(gameImage->cache, menu->item->userdata, item, 1, prefetchInactiveFrames);
        }

        if (!texture || !texture->Mem) {
            if (gameImage->defaultTexture)
                texture = &gameImage->defaultTexture->source;
            else {
                if (elem->type == ELEM_TYPE_BACKGROUND)
                    guiDrawBGPlasma();
                return;
            }
        }

        if (gameImage->overlayTexture) {
            rmDrawOverlayPixmap(&gameImage->overlayTexture->source, drawElem->posX, drawElem->posY, drawElem->aligned, drawElem->width, drawElem->height, drawElem->scaled, gDefaultCol,
                                texture, gameImage->overlayTexture->upperLeft_x, gameImage->overlayTexture->upperLeft_y, gameImage->overlayTexture->upperRight_x, gameImage->overlayTexture->upperRight_y,
                                gameImage->overlayTexture->lowerLeft_x, gameImage->overlayTexture->lowerLeft_y, gameImage->overlayTexture->lowerRight_x, gameImage->overlayTexture->lowerRight_y, 0);
            if (gameImage->overlayTexture2)
                rmDrawPixmap(&gameImage->overlayTexture2->source, drawElem->posX, drawElem->posY, drawElem->aligned, drawElem->width, drawElem->height, drawElem->scaled, gDefaultCol, 0);
        } else
            rmDrawPixmap(texture, drawElem->posX, drawElem->posY, drawElem->aligned, drawElem->width, drawElem->height, drawElem->scaled, gDefaultCol, 0);

    } else if (elem->type == ELEM_TYPE_BACKGROUND) {
        mutable_image_t *gameImage = (mutable_image_t *)elem->extended;
        if (gameImage->defaultTexture)
            rmDrawPixmap(&gameImage->defaultTexture->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
        else
            guiDrawBGPlasma();
    }
}

static void initGameImage(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name, const char *pattern, int count, const char *texture, const char *overlay)
{
    mutable_image_t *mutableImage = initMutableImage(themePath, themeConfig, theme, name, elem->type, pattern, count, texture, overlay);
    elem->extended = mutableImage;
    elem->endElem = &endMutableImage;

    if (mutableImage->cache)
        elem->drawElem = &drawGameImage;
    else
        LOG("THEMES GameImage %s: NO pattern, elem disabled !!\n", name);
}

// Coverflow ////////////////////////////////////////////////////////////////////////////////////////////////////////////////

// Source list used for a submenu item's TEXTURE lookup. Always the active menu's userdata --
// including the Favourites tab: our FAV items carry a FAV-array index (not the source id), and
// favGetImage / favGetItemStartup proxy by that index, so the lookup must stay on favList.
static void *thmGetItemSource(struct menu_list *menu, struct submenu_list *item)
{
    return menu->item->userdata;
}

// Find a game-image / coverflow element in a list by its cover-cache suffix (e.g. "COV").
static theme_element_t *thmFindElemBySuffix(theme_elems_t *elems, const char *suffix)
{
    if (suffix == NULL)
        return NULL;
    for (theme_element_t *e = elems->first; e != NULL; e = e->next) {
        if (e->type != ELEM_TYPE_GAME_IMAGE && e->type != ELEM_TYPE_COVERFLOW)
            continue;
        mutable_image_t *eimg = (mutable_image_t *)e->extended;
        if (eimg != NULL && eimg->cache != NULL && eimg->cache->suffix != NULL && strcmp(eimg->cache->suffix, suffix) == 0)
            return e;
    }
    return NULL;
}

// Element to DRAW a submenu item with. The Favourites screen as a whole renders with the theme's
// favs family (menuRenderMain switches the element set per mode); the VCD view and the Apps tab
// render with the apps family the same way. This per-item hook adds ONE extra redirect on top: an
// APP-source favourite redirects its COVER to the apps element (matched by cache suffix) so a
// favourited app keeps its app box even when the theme defines no distinct favsMain cover. Non-app
// favourites and every other screen pass through unchanged -- the element already comes from the
// correct family. Single chokepoint for both drawGameImage and the coverflow carousel.
static theme_element_t *thmGetElemForItem(struct menu_list *menu, struct submenu_list *item, theme_element_t *elem)
{
    if (item == NULL || elem == NULL)
        return elem;
    item_list_t *menuList = (item_list_t *)menu->item->userdata;
    if (menuList == NULL || menuList->mode != FAV_MODE)
        return elem;
    if (favGetItemSourceMode(item->item.id) != APP_MODE)
        return elem;
    mutable_image_t *img = (mutable_image_t *)elem->extended;
    if (img == NULL || img->cache == NULL)
        return elem;
    theme_element_t *appsElem = thmFindElemBySuffix(&gTheme->appsMainElems, img->cache->suffix);
    return (appsElem != NULL) ? appsElem : elem;
}

// Arms a slide animation in direction dir (+1 next / -1 prev). No-op (instant move) when
// animation speed is 0. Called from menusys.c via the themes.h extern.
void thmTriggerCoverflowAnim(int dir)
{
    if (gCoverflowAnimSpeed <= 0)
        return;
    cfIsAnimating = 1;
    cfAnimDirection = dir;
    cfAnimStartTime = clock();
}

static void drawCoverFlow(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    if (!item)
        return; // empty list -> nothing to draw

    if (elem->extended == NULL)
        return; // coverflow element disabled (no cover cache)
    item_list_t *sourceList = (item_list_t *)thmGetItemSource(menu, item);

    // Defensive clamp: never trust the global at the draw site (conf.cfg may be hand-edited
    // to e.g. 7 -> covers[] OOB). coverCount is the ONLY index bound below.
    int coverCount = (gCoverflowCount == 5) ? 5 : 3;
    int centerIndex = coverCount / 2;

    // Layout in virtual 640x480 space (div-guarded). SCALING_RATIO + the panel apply
    // the widescreen/PAR correction at draw time (rmSetupQuad: w * iAspectWidth >> 2),
    // exactly like the stock ItemCover path. We must NOT pre-apply rmWideScale here or
    // the cover gets the aspect factor twice and warps when widescreen is toggled.
    int origCoverWidth = elem->width;
    int coverWidth = elem->width;
    int maxCoverWidth = (screenWidth - (coverCount - 1) * 10) / coverCount;
    // Widescreen draws each cover at 3/4 width (SCALING_RATIO), leaving spare screen, so
    // allow ~10% larger covers in 16:9. This scales SIZE only -- the cover's authored W:H
    // is untouched, so aspect immunity holds; 4:3 keeps the tight 3-up maximum.
    if (gWideScreen)
        maxCoverWidth = maxCoverWidth * 11 / 10;
    if (coverWidth > maxCoverWidth)
        coverWidth = maxCoverWidth;
    if (coverWidth <= 0)
        return;
    int coverHeight = (origCoverWidth > 0) ? (elem->height * coverWidth / origCoverWidth) : elem->height;

    int coverSpacing = (screenWidth - coverCount * coverWidth) / (coverCount + 1);
    if (coverSpacing < 0)
        coverSpacing = 0;
    int coverDistance = coverWidth + coverSpacing;
    int basePosX = (screenWidth - (coverCount * coverWidth + (coverCount - 1) * coverSpacing)) / 2 + coverWidth / 2 + coverWidth * gTheme->coverflowCoverOffset / 256;

    // Carousel cover SIZE/aspect comes from the coverflow element (uniform across covers). The
    // per-cover frame-inset recenter is computed inside the loop from each cover's OWN element +
    // overlay -- the Favourites tab can mix game and app cases (different frame insets), so a
    // single shared recenter would shift the odd one out.

    // Build the visible window: covers[centerIndex] is the selection; fan out both sides,
    // wrapping last<->first. The left wrap reads menu->item->last (full lifecycle wired in
    // Commit E) -- single-game/exhausted lists break out before dereferencing a stale ptr.
    struct submenu_list *covers[COVERFLOW_MAX];
    int i;
    for (i = 0; i < COVERFLOW_MAX; i++)
        covers[i] = NULL;
    covers[centerIndex] = item;

    struct submenu_list *walk = item;
    for (i = centerIndex - 1; i >= 0; i--) {
        struct submenu_list *prev = walk->prev ? walk->prev : menu->item->last;
        if (!prev || prev == walk || prev == item)
            break;
        covers[i] = prev;
        walk = prev;
    }

    walk = item;
    for (i = centerIndex + 1; i < coverCount; i++) {
        struct submenu_list *next = walk->next ? walk->next : menu->item->submenu;
        if (!next || next == walk || next == item)
            break;
        covers[i] = next;
        walk = next;
    }

    // Slide animation (cubic ease-out). clock() wrap is clamped to snap-complete.
    // NOTE: the slide/shrink sign convention is HW-tunable polish (one sign flip).
    float eased = 1.0f;
    int animOffset = 0;
    if (gCoverflowAnimSpeed <= 0) {
        cfIsAnimating = 0;
    } else if (cfIsAnimating) {
        clock_t durTicks = (clock_t)(gCoverflowAnimSpeed * (CLOCKS_PER_SEC / 1000.0f));
        if (durTicks <= 0)
            durTicks = 1;
        clock_t elapsed = clock() - cfAnimStartTime;
        if (elapsed < 0)
            elapsed = durTicks; // clock wrap -> finish now
        float t = (float)elapsed / (float)durTicks;
        if (t >= 1.0f) {
            t = 1.0f;
            cfIsAnimating = 0;
        }
        eased = 1.0f - powf(1.0f - t, 3.0f);
        animOffset = (int)(cfAnimDirection * coverDistance * (eased - 1.0f));
    }
    int leavingIndex = centerIndex + cfAnimDirection; // neighbour swapping with center

    rmSetReflectionYOffset(elem->reflectionOffset); // theme reflection_offset; reset after the loop

    for (i = 0; i < coverCount; i++) {
        if (!covers[i])
            continue;

        // Per-cover element redirect: on the FAV tab an APP favourite uses the apps element (art
        // folder + case overlay); games and other tabs pass through to the coverflow element. The
        // texture lookup stays on sourceList (favList) so favGetImage proxies by the FAV index --
        // only the cache + overlay are redirected; frame-inset math uses THIS cover's own dims.
        theme_element_t *coverElem = thmGetElemForItem(menu, covers[i], elem);
        mutable_image_t *cimg = (mutable_image_t *)coverElem->extended;
        if (!cimg)
            continue;
        int csw = (coverElem->width > 0) ? coverElem->width : 1;   // div-guard
        int csh = (coverElem->height > 0) ? coverElem->height : 1; // div-guard

        GSTEXTURE *texture = getGameImageTexture(cimg->cache, sourceList, &covers[i]->item);
        if (!texture || !texture->Mem)
            texture = cimg->defaultTexture ? &cimg->defaultTexture->source : thmGetTexture(COVER_DEFAULT);
        if (!texture || !texture->Mem)
            continue;

        // Center grows; the leaving neighbour shrinks. leavingIndex is bounds-checked into
        // [0,coverCount) BEFORE it indexes covers[] (audit fix).
        int scaleAdd = 0;
        if (i == centerIndex)
            scaleAdd = (int)(gCoverflowCenterScale * eased);
        else if (cfIsAnimating && leavingIndex >= 0 && leavingIndex < coverCount && i == leavingIndex)
            scaleAdd = (int)(gCoverflowCenterScale * (1.0f - eased));

        int drawW = coverWidth + scaleAdd;
        int drawH = (coverWidth > 0) ? (coverHeight * drawW / coverWidth) : coverHeight;

        // Auto-center the VISIBLE cover (case frame box) from THIS cover's overlay corners: the
        // frame can sit off-center (e.g. apps_case = top-left 186 of 256). No overlay => no shift.
        int recenterX = 0, recenterY = 0;
        if (cimg->overlayTexture) {
            image_texture_t *ovc = cimg->overlayTexture;
            recenterX = csw / 2 - (ovc->upperLeft_x + ovc->upperRight_x) / 2;
            recenterY = csh / 2 - (ovc->upperLeft_y + ovc->lowerLeft_y) / 2;
        }

        int posX = basePosX + i * coverDistance + animOffset + recenterX * drawW / csw;
        int posY = elem->posY + recenterY * drawH / csh;

        u64 coverColor = (gCoverflowDimCovers && i != centerIndex) ? GS_SETREG_RGBA(0x80, 0x80, 0x80, 0x40) : gDefaultCol;

        if (cimg->overlayTexture) {
            // Scale the inlay (cover) corner offsets to the drawn overlay size so the case
            // window tracks the cover at every scale. HW-verify alignment with real case art.
            image_texture_t *ov = cimg->overlayTexture;
            rmDrawOverlayPixmap(&ov->source, posX, posY, ALIGN_CENTER, drawW, drawH, SCALING_RATIO, coverColor,
                                texture, ov->upperLeft_x * drawW / csw, ov->upperLeft_y * drawH / csh, ov->upperRight_x * drawW / csw, ov->upperRight_y * drawH / csh,
                                ov->lowerLeft_x * drawW / csw, ov->lowerLeft_y * drawH / csh, ov->lowerRight_x * drawW / csw, ov->lowerRight_y * drawH / csh, elem->reflection);
            if (cimg->overlayTexture2)
                rmDrawPixmap(&cimg->overlayTexture2->source, posX, posY, ALIGN_CENTER, drawW, drawH, SCALING_RATIO, coverColor, elem->reflection);
        } else {
            rmDrawPixmap(texture, posX, posY, ALIGN_CENTER, drawW, drawH, SCALING_RATIO, coverColor, elem->reflection);
        }
    }

    rmSetReflectionYOffset(0); // don't leak the offset to any other reflection draw
}

static void initCoverflow(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name)
{
    mutable_image_t *mutableImage = initMutableImage(themePath, themeConfig, theme, name, elem->type, "COV", 10, NULL, NULL);
    elem->extended = mutableImage;
    elem->endElem = &endMutableImage;

    if (mutableImage && mutableImage->cache) {
        elem->drawElem = &drawCoverFlow;
        if (!theme->coverflow)
            theme->coverflow = elem; // first coverflow element = the "coverflow active" flag
    } else
        LOG("THEMES Coverflow %s: NO cache, elem disabled !!\n", name);
}

// AttributeImage ///////////////////////////////////////////////////////////////////////////////////////////////////////////

static void drawAttributeImage(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    // No current item (empty list): clear, don't redraw the stale cached image -- same guard as
    // drawAttributeText/drawGameImage (#48). Also correct for the per-game #Media icon.
    if (item == NULL)
        return;
    mutable_image_t *attributeImage = (mutable_image_t *)elem->extended;
    if (config) {
        if (attributeImage->currentConfigId != config->uid) {
            // force refresh
            attributeImage->currentUid = -1;
            attributeImage->currentConfigId = config->uid;
            attributeImage->currentValue = NULL;
            configGetStr(config, attributeImage->cache->suffix, (const char **)&attributeImage->currentValue);
        }
        if (attributeImage->currentValue) {
            if (thmGetGuiValue() == 0) {
                int texId;
                char *seppos = strchr(attributeImage->currentValue, '/');
                if (!seppos)
                    texId = texLookupInternalTexId(attributeImage->currentValue);
                else {
                    char imgName[32];
                    snprintf(imgName, sizeof(imgName), "%s_%s", attributeImage->cache->suffix, &seppos[1]);
                    texId = texLookupInternalTexId(&imgName[0]);
                }
                GSTEXTURE *texture = thmGetTexture(texId);
                if (texture && texture->Mem)
                    rmDrawPixmap(texture, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);

                return;
            } else {
                int posZ = 0;
                GSTEXTURE *texture = cacheGetTexture(attributeImage->cache, menu->item->userdata, &posZ, &attributeImage->currentUid, attributeImage->currentValue);
                if (texture && texture->Mem) {
                    if (attributeImage->overlayTexture) {
                        rmDrawOverlayPixmap(&attributeImage->overlayTexture->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol,
                                            texture, attributeImage->overlayTexture->upperLeft_x, attributeImage->overlayTexture->upperLeft_y, attributeImage->overlayTexture->upperRight_x, attributeImage->overlayTexture->upperRight_y,
                                            attributeImage->overlayTexture->lowerLeft_x, attributeImage->overlayTexture->lowerLeft_y, attributeImage->overlayTexture->lowerRight_x, attributeImage->overlayTexture->lowerRight_y, 0);
                        if (attributeImage->overlayTexture2)
                            rmDrawPixmap(&attributeImage->overlayTexture2->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
                    } else
                        rmDrawPixmap(texture, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);

                    return;
                }
            }
        }
    }
    if (attributeImage->defaultTexture)
        rmDrawPixmap(&attributeImage->defaultTexture->source, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
}

static void initAttributeImage(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name)
{
    mutable_image_t *mutableImage = initMutableImage(themePath, themeConfig, theme, name, elem->type, NULL, 1, NULL, NULL);
    elem->extended = mutableImage;
    elem->endElem = &endMutableImage;

    if (mutableImage->cache)
        elem->drawElem = &drawAttributeImage;
    else
        LOG("THEMES AttributeImage %s: NO attribute, elem disabled !!\n", name);
}

// BasicElement /////////////////////////////////////////////////////////////////////////////////////////////////////////////

static void endBasic(theme_element_t *elem)
{
    if (elem->extended)
        free(elem->extended);

    free(elem);
}

static theme_element_t *initBasic(const char *themePath, config_set_t *themeConfig, theme_t *theme, const char *name, int type, int x, int y, short aligned, int w, int h, short scaled, u64 color, int font)
{
    int intValue;
    unsigned char charColor[3];
    const char *temp;
    char elemProp[64];

    theme_element_t *elem = (theme_element_t *)malloc(sizeof(theme_element_t));

    elem->type = type;
    elem->reflection = 0;
    elem->reflectionOffset = 0;
    elem->extended = NULL;
    elem->drawElem = NULL;
    elem->endElem = &endBasic;
    elem->next = NULL;

    snprintf(elemProp, sizeof(elemProp), "%s_x", name);
    if (configGetStr(themeConfig, elemProp, &temp)) {
        if (!strncmp(temp, "POS_MID", 7))
            x = screenWidth >> 1;
        else
            x = atoi(temp);
    }
    if (x < 0)
        elem->posX = screenWidth + x;
    else
        elem->posX = x;

    snprintf(elemProp, sizeof(elemProp), "%s_y", name);
    if (configGetStr(themeConfig, elemProp, &temp)) {
        if (!strncmp(temp, "POS_MID", 7))
            y = screenHeight >> 1;
        else
            y = atoi(temp);
    }
    if (y < 0)
        elem->posY = ceil((screenHeight + y) * theme->usedHeight / screenHeight);
    else
        elem->posY = y;

    snprintf(elemProp, sizeof(elemProp), "%s_width", name);
    if (configGetStr(themeConfig, elemProp, &temp)) {
        if (!strncmp(temp, "DIM_INF", 7))
            elem->width = screenWidth;
        else
            elem->width = atoi(temp);
    } else
        elem->width = w;

    snprintf(elemProp, sizeof(elemProp), "%s_height", name);
    if (configGetStr(themeConfig, elemProp, &temp)) {
        if (!strncmp(temp, "DIM_INF", 7))
            elem->height = screenHeight;
        else
            elem->height = atoi(temp);
    } else
        elem->height = h;

    snprintf(elemProp, sizeof(elemProp), "%s_aligned", name);
    if (configGetInt(themeConfig, elemProp, &intValue))
        elem->aligned = (intValue == 0) ? ALIGN_NONE : ALIGN_CENTER;
    else
        elem->aligned = aligned;

    snprintf(elemProp, sizeof(elemProp), "%s_scaled", name);
    if (configGetInt(themeConfig, elemProp, &intValue))
        elem->scaled = (intValue == 0) ? SCALING_NONE : SCALING_RATIO;
    else
        elem->scaled = scaled;

    snprintf(elemProp, sizeof(elemProp), "%s_color", name);
    if (configGetColor(themeConfig, elemProp, charColor))
        elem->color = GS_SETREG_RGBA(charColor[0], charColor[1], charColor[2], 0x80);
    else
        elem->color = color;

    elem->font = font;
    snprintf(elemProp, sizeof(elemProp), "%s_font", name);
    if (configGetInt(themeConfig, elemProp, &intValue)) {
        if (intValue > 0 && intValue < THM_MAX_FONTS)
            elem->font = theme->fonts[intValue];
    }

    snprintf(elemProp, sizeof(elemProp), "%s_reflection", name);
    if (configGetInt(themeConfig, elemProp, &intValue))
        elem->reflection = intValue ? 1 : 0;

    snprintf(elemProp, sizeof(elemProp), "%s_reflection_offset", name);
    if (configGetInt(themeConfig, elemProp, &intValue)) {
        // Clamp to a sane band: an offset beyond a screen height only draws strips off-canvas
        // (wasted work), and a hand-edited extreme should not push the reflection into nowhere.
        if (intValue < -1024)
            intValue = -1024;
        else if (intValue > 1024)
            intValue = 1024;
        elem->reflectionOffset = intValue;
    }

    return elem;
}

// Internal elements ////////////////////////////////////////////////////////////////////////////////////////////////////////
static void drawBackground(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    guiDrawBGPlasma();
}

static void initBackground(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name, const char *pattern, int count, const char *texture)
{
    mutable_image_t *mutableImage = initMutableImage(themePath, themeConfig, theme, name, elem->type, pattern, count, texture, NULL);
    elem->extended = mutableImage;
    elem->endElem = &endMutableImage;

    if (mutableImage->cache)
        elem->drawElem = &drawGameImage;
    else if (mutableImage->defaultTexture)
        elem->drawElem = &drawStaticImage;
    else
        elem->drawElem = &drawBackground;
}

static void drawMenuIcon(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    GSTEXTURE *menuIconTex = thmGetTexture(menu->item->icon_id);
    if (menuIconTex && menuIconTex->Mem)
        rmDrawPixmap(menuIconTex, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
}

static int findMenuNext(struct menu_list *menu)
{
    struct menu_list *next = menu->next;
    while (next != NULL && next->item->visible == 0)
        next = next->next;

    return next == NULL ? 0 : next->item->visible;
}

static int findMenuPrev(struct menu_list *menu)
{
    struct menu_list *prev = menu->prev;
    while (prev != NULL && prev->item->visible == 0)
        prev = prev->prev;

    return prev == NULL ? 0 : prev->item->visible;
}

static void drawMenuText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    GSTEXTURE *leftIconTex = NULL, *rightIconTex = NULL;
    if (findMenuPrev(menu) != 0)
        leftIconTex = thmGetTexture(LEFT_ICON);
    if (findMenuNext(menu) != 0)
        rightIconTex = thmGetTexture(RIGHT_ICON);

    if (elem->aligned) {
        int offset = elem->width >> 1;
        if (leftIconTex && leftIconTex->Mem)
            rmDrawPixmap(leftIconTex, elem->posX - offset, elem->posY, elem->aligned, 20, 20, elem->scaled, gDefaultCol, 0);
        if (rightIconTex && rightIconTex->Mem)
            rmDrawPixmap(rightIconTex, elem->posX + offset, elem->posY, elem->aligned, 20, 20, elem->scaled, gDefaultCol, 0);
    } else {
        if (leftIconTex && leftIconTex->Mem)
            rmDrawPixmap(leftIconTex, elem->posX - leftIconTex->Width, elem->posY, elem->aligned, 20, 20, elem->scaled, gDefaultCol, 0);
        if (rightIconTex && rightIconTex->Mem)
            rmDrawPixmap(rightIconTex, elem->posX + elem->width, elem->posY, elem->aligned, 20, 20, elem->scaled, gDefaultCol, 0);
    }
    fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, menuItemGetText(menu->item), elem->color);
}

static void drawBDMIndex(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    item_list_t *itemList = menu->item->userdata;
    // Only render for bdm modes and if current mode is visible
    if (itemList->mode >= ETH_MODE || menu->item->visible == 0)
        return;

    // Only render if multiple mass devices are connected
    if (itemList->mode == 0 && menu->next->item->visible == 0)
        return;

    char imgName[32];
    snprintf(imgName, sizeof(imgName), "Index_%d", itemList->mode);

    GSTEXTURE *indexTex = thmGetTexture(texLookupInternalTexId(&imgName[0]));
    if (indexTex && indexTex->Mem)
        rmDrawPixmap(indexTex, elem->posX, elem->posY, elem->aligned, elem->width, elem->height, elem->scaled, gDefaultCol, 0);
}

static void drawItemsList(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    if (item) {
        items_list_t *itemsList = (items_list_t *)elem->extended;
        item_list_t *list = menu->item->userdata;
        int mmceSelectionChanged = 0;
        char *selectedStartup = NULL;

        if (list != NULL && list->mode == MMCE_MODE && itemsList->decoratorImage != NULL && itemsList->decoratorImage->cache != NULL) {
            selectedStartup = list->itemGetStartup(list, item->item.id);
            if (selectedStartup == NULL)
                selectedStartup = "";

            if (itemsList->lastSelectedItemId != item->item.id || strcmp(itemsList->lastSelectedStartup, selectedStartup) != 0) {
                mmceSelectionChanged = 1;
                itemsList->lastSelectedItemId = item->item.id;
                snprintf(itemsList->lastSelectedStartup, sizeof(itemsList->lastSelectedStartup), "%s", selectedStartup);
            }
        }

        int posX = elem->posX, posY = elem->posY;
        if (elem->aligned) {
            posX -= elem->width >> 1;
            posY -= elem->height >> 1;
        }

        submenu_list_t *ps = menu->item->pagestart;
        int others = 0;
        u64 color;
        int textEndX = 0;
        while (ps && (others++ < itemsList->displayedItems)) {
            if (ps == item)
                color = gTheme->selTextColor;
            else
                color = elem->color;

            if (itemsList->decoratorImage) {
                GSTEXTURE *itemIconTex;

                if (list != NULL && list->mode == MMCE_MODE && itemsList->decoratorImage->cache != NULL) {
                    image_cache_t *cache = itemsList->decoratorImage->cache;

                    if (mmceSelectionChanged && ps == item)
                        itemIconTex = getGameImageTexture(cache, menu->item->userdata, &ps->item);
                    else
                        itemIconTex = cacheGetTextureIfReady(cache, &ps->item.cache_id[cache->userId], &ps->item.cache_uid[cache->userId]);
                } else
                    itemIconTex = getGameImageTexture(itemsList->decoratorImage->cache, menu->item->userdata, &ps->item);

                if (itemIconTex && itemIconTex->Mem)
                    rmDrawPixmap(itemIconTex, posX, posY, elem->aligned, DECORATOR_SIZE, DECORATOR_SIZE, elem->scaled, gDefaultCol, 0);
                else {
                    if (itemsList->decoratorImage->defaultTexture)
                        rmDrawPixmap(&itemsList->decoratorImage->defaultTexture->source, posX, posY, elem->aligned, DECORATOR_SIZE, DECORATOR_SIZE, elem->scaled, gDefaultCol, 0);
                }
                textEndX = fntRenderString(elem->font, elem->posX + DECORATOR_SIZE, posY, elem->aligned, elem->width, elem->height, submenuItemGetText(&ps->item), color);
            } else
                textEndX = fntRenderString(elem->font, elem->posX, posY, elem->aligned, elem->width, elem->height, submenuItemGetText(&ps->item), color);

            // Favourites: draw a small star just after the item text.
            if (ps->item.favourited) {
                GSTEXTURE *favTex = thmGetTexture(FAV_MARK);
                if (favTex != NULL && favTex->Mem != NULL)
                    rmDrawPixmap(favTex, textEndX + 4, posY, elem->aligned, MENU_ITEM_HEIGHT, MENU_ITEM_HEIGHT, elem->scaled, gDefaultCol, 0);
            }

            posY += MENU_ITEM_HEIGHT;
            ps = ps->next;
        }
    }
}

static void initItemsList(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *elem, const char *name, const char *decorator)
{
    char elemProp[64];

    items_list_t *itemsList = (items_list_t *)malloc(sizeof(items_list_t));

    if (elem->width == DIM_UNDEF)
        elem->width = screenWidth;

    if (elem->height == DIM_UNDEF)
        elem->height = theme->usedHeight - (MENU_POS_V + HINT_HEIGHT);

    itemsList->displayedItems = elem->height / MENU_ITEM_HEIGHT;
    LOG("THEMES ItemsList %s: displaying %d elems, item height: %d\n", name, itemsList->displayedItems, elem->height);

    itemsList->decorator = NULL;
    snprintf(elemProp, sizeof(elemProp), "%s_decorator", name);
    configGetStr(themeConfig, elemProp, &decorator);
    if (decorator)
        itemsList->decorator = decorator; // Will be used later (thmValidate)

    itemsList->decoratorImage = NULL;
    itemsList->lastSelectedItemId = -1;
    itemsList->lastSelectedStartup[0] = '\0';

    elem->extended = itemsList;
    // elem->endElem = &endBasic; does the job

    elem->drawElem = &drawItemsList;
}

static void drawItemText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    if (item) {
        item_list_t *support = menu->item->userdata;
        fntRenderString(elem->font, elem->posX, elem->posY, elem->aligned, 0, 0, support->itemGetStartup(support, item->item.id), elem->color);
    }
}

static void drawHintText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    menu_hint_item_t *hint = menu->item->hints;
    if (hint) {
        int x = elem->posX;

        if (elem->aligned)
            x = guiAlignMenuHints(hint, elem->font, elem->width);

        for (; hint; hint = hint->next) {
            x = guiDrawIconAndText(hint->icon_id, hint->text_id, elem->font, x, elem->posY, elem->color);
            x += elem->width;
        }
    }
}

static void drawInfoHintText(struct menu_list *menu, struct submenu_list *item, config_set_t *config, struct theme_element *elem)
{
    int infoHints[2] = {_STR_RUN, _STR_BACK};
    int infoIcons[2] = {CIRCLE_ICON, CROSS_ICON};
    int x = elem->posX;

    if (elem->aligned)
        x = guiAlignSubMenuHints(2, infoHints, infoIcons, elem->font, elem->width, 1);

    x = guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? infoIcons[0] : infoIcons[1], infoHints[0], elem->font, x, elem->posY, elem->color);
    x += elem->width;
    x = guiDrawIconAndText(gSelectButton == KEY_CIRCLE ? infoIcons[1] : infoIcons[0], infoHints[1], elem->font, x, elem->posY, elem->color);
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

static void validateBackgroundElems(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_elems_t *mainElems, theme_elems_t *infoElems)
{
    if (!mainElems->first || (mainElems->first->type != ELEM_TYPE_BACKGROUND)) {
        LOG("THEMES No valid background found for main, add default BG_ART\n");
        theme_element_t *backgroundElem = initBasic(themePath, themeConfig, theme, "bg", ELEM_TYPE_BACKGROUND, 0, 0, ALIGN_NONE, screenWidth, screenHeight, SCALING_NONE, gDefaultCol, theme->fonts[0]);
        initBackground(themePath, themeConfig, theme, backgroundElem, "bg", "BG", 1, NULL);
        backgroundElem->next = mainElems->first;
        mainElems->first = backgroundElem;
    }

    if (infoElems->first) {
        if (infoElems->first->type != ELEM_TYPE_BACKGROUND) {
            LOG("THEMES No valid background found for info, add default BG_ART\n");
            theme_element_t *backgroundElem = initBasic(themePath, themeConfig, theme, "bg", ELEM_TYPE_BACKGROUND, 0, 0, ALIGN_NONE, screenWidth, screenHeight, SCALING_NONE, gDefaultCol, theme->fonts[0]);
            initBackground(themePath, themeConfig, theme, backgroundElem, "bg", "BG", 1, NULL);
            backgroundElem->next = infoElems->first;
            infoElems->first = backgroundElem;
        }
    }
}

static void validateItemsList(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_element_t *list, theme_elems_t *mainElems)
{
    if (list) {
        items_list_t *itemsList = (items_list_t *)list->extended;
        if (itemsList->decorator) {
            // Second pass to find the decorator
            theme_element_t *decoratorElem = mainElems->first;
            while (decoratorElem) {
                if (decoratorElem->type == ELEM_TYPE_GAME_IMAGE) {
                    mutable_image_t *gameImage = (mutable_image_t *)decoratorElem->extended;
                    // A GAME_IMAGE element can have cache == NULL (no _pattern); guard before
                    // dereferencing ->suffix, matching drawGameImage and the other cache users.
                    if (gameImage->cache && !strcmp(itemsList->decorator, gameImage->cache->suffix)) {
                        // if user want to cache less than displayed items, then disable itemslist icons, if not would load constantly
                        if (gameImage->cache->count >= itemsList->displayedItems)
                            itemsList->decoratorImage = gameImage;
                        break;
                    }
                }

                decoratorElem = decoratorElem->next;
            }
            itemsList->decorator = NULL;
        }
    } else {
        LOG("THEMES No itemsList found, adding a default one\n");
        list = initBasic(themePath, themeConfig, theme, "il", ELEM_TYPE_ITEMS_LIST, 42, 42, ALIGN_NONE, 373, 316, SCALING_RATIO, theme->textColor, theme->fonts[0]);
        initItemsList(themePath, themeConfig, theme, list, "il", NULL);
        list->next = mainElems->first->next; // Position the itemsList as second element (right after the Background)
        mainElems->first->next = list;
    }
}

static int isDecoratorCoverCache(theme_element_t *list, image_cache_t *cache)
{
    items_list_t *itemsList;

    if (list == NULL || list->extended == NULL || cache == NULL)
        return 0;

    itemsList = (items_list_t *)list->extended;
    return itemsList->decoratorImage != NULL && itemsList->decoratorImage->cache == cache;
}

static int isDecoratorCoverImage(theme_t *theme, mutable_image_t *gameImage)
{
    items_list_t *itemsList;

    if (theme == NULL || gameImage == NULL)
        return 0;

    if (theme->gamesItemsList != NULL && theme->gamesItemsList->extended != NULL) {
        itemsList = (items_list_t *)theme->gamesItemsList->extended;
        if (itemsList->decoratorImage == gameImage)
            return 1;
    }

    if (theme->appsItemsList != NULL && theme->appsItemsList->extended != NULL) {
        itemsList = (items_list_t *)theme->appsItemsList->extended;
        if (itemsList->decoratorImage == gameImage)
            return 1;
    }

    if (theme->favsItemsList != NULL && theme->favsItemsList->extended != NULL) {
        itemsList = (items_list_t *)theme->favsItemsList->extended;
        if (itemsList->decoratorImage == gameImage)
            return 1;
    }

    if (theme->vcdItemsList != NULL && theme->vcdItemsList->extended != NULL) {
        itemsList = (items_list_t *)theme->vcdItemsList->extended;
        if (itemsList->decoratorImage == gameImage)
            return 1;
    }

    return 0;
}

static image_cache_t *cloneImageCache(theme_t *theme, image_cache_t *source)
{
    image_cache_t *cache;

    if (theme == NULL || source == NULL)
        return NULL;

    cache = cacheInitCache(theme->gameCacheCount++, source->prefix, source->isPrefixRelative, source->suffix, source->count);
    if (cache != NULL)
        cache->allowPrime = source->allowPrime;

    return cache;
}

static void replaceSharedCoverCache(theme_t *theme, theme_elems_t *elems, image_cache_t *sourceCache, image_cache_t *replacementCache, int *replacementAssigned)
{
    theme_element_t *elem;

    if (theme == NULL || elems == NULL || sourceCache == NULL || replacementCache == NULL || replacementAssigned == NULL)
        return;

    elem = elems->first;
    while (elem != NULL) {
        if (elem->type == ELEM_TYPE_GAME_IMAGE) {
            mutable_image_t *gameImage = (mutable_image_t *)elem->extended;

            if (gameImage != NULL && !isDecoratorCoverImage(theme, gameImage) && gameImage->cache == sourceCache) {
                gameImage->cache = replacementCache;
                gameImage->cacheLinked = *replacementAssigned ? 1 : 0;
                *replacementAssigned = 1;
            }
        }

        elem = elem->next;
    }
}

static void splitDecoratorCoverCache(theme_t *theme, theme_element_t *list)
{
    items_list_t *itemsList;
    image_cache_t *sourceCache;
    image_cache_t *replacementCache;
    int replacementAssigned;

    if (theme == NULL || list == NULL || list->extended == NULL)
        return;

    itemsList = (items_list_t *)list->extended;
    if (itemsList->decoratorImage == NULL || itemsList->decoratorImage->cache == NULL)
        return;

    sourceCache = itemsList->decoratorImage->cache;
    if (sourceCache->suffix == NULL || strcmp(sourceCache->suffix, "COV") != 0)
        return;

    replacementCache = cloneImageCache(theme, sourceCache);
    if (replacementCache == NULL)
        return;

    replacementAssigned = 0;
    replaceSharedCoverCache(theme, &theme->mainElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->infoElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->appsMainElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->appsInfoElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->favsMainElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->favsInfoElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->vcdMainElems, sourceCache, replacementCache, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->vcdInfoElems, sourceCache, replacementCache, &replacementAssigned);

    if (!replacementAssigned)
        cacheDestroyCache(replacementCache);
}

static void clampSelectedCoverCaches(theme_t *theme, theme_elems_t *elems)
{
    theme_element_t *elem = elems->first;

    while (elem != NULL) {
        if (elem->type == ELEM_TYPE_GAME_IMAGE) {
            mutable_image_t *gameImage = (mutable_image_t *)elem->extended;

            if (gameImage != NULL && gameImage->cache != NULL && gameImage->cache->suffix != NULL && strcmp(gameImage->cache->suffix, "COV") == 0 &&
                !isDecoratorCoverCache(theme->gamesItemsList, gameImage->cache) && !isDecoratorCoverCache(theme->appsItemsList, gameImage->cache) &&
                !isDecoratorCoverCache(theme->favsItemsList, gameImage->cache) && !isDecoratorCoverCache(theme->vcdItemsList, gameImage->cache)) {
                gameImage->cache->allowPrime = 0;
            }
        }

        elem = elem->next;
    }
}

// True if `cache` is referenced by a COV GAME_IMAGE OUTSIDE the vcd family (games/apps/favs main+info).
// separateVcdCoverCache only acts when the vcd covers' cache is genuinely SHARED with a non-vcd family;
// if the cache is vcd-private (e.g. a theme with vcd COV covers but no games COV cover), cloning and
// re-pointing the vcd covers would leave the original cache unreferenced -> a one-time leak. Skip then.
static int vcdCoverCacheSharedOutsideVcd(theme_t *theme, image_cache_t *cache)
{
    theme_elems_t *groups[6] = {&theme->mainElems, &theme->infoElems, &theme->appsMainElems,
                                &theme->appsInfoElems, &theme->favsMainElems, &theme->favsInfoElems};
    for (int g = 0; g < 6; g++) {
        theme_element_t *e = groups[g]->first;
        while (e != NULL) {
            if (e->type == ELEM_TYPE_GAME_IMAGE) {
                mutable_image_t *gi = (mutable_image_t *)e->extended;
                if (gi != NULL && gi->cache == cache)
                    return 1;
            }
            e = e->next;
        }
    }
    return 0;
}

// Give the L3 VCD/PS1 view its OWN COV cover cache so it never shares cache slots with the games view.
// The VCD list reuses the device's own game list (identical submenu item ids), and findDuplicate unifies
// every "COV" GAME_IMAGE cache by suffix -- so without this the VCD covers and the ISO covers collide in
// one (cache userId, item id)-keyed cache and thrash on every L3 toggle (eliminator1403's no-covers /
// flash-then-wrong-cover hardware report). splitDecoratorCoverCache only separates DECORATOR covers and
// no-ops on themes whose items list has no decorator (e.g. the default Coverflow theme), so the selected/
// carousel cover (vcdMain2) would still share the games cache; this handles that case unconditionally.
// Clones the COV cache used by the vcd family and re-points its non-decorator COV game-images onto it.
static void separateVcdCoverCache(theme_t *theme)
{
    if (theme == NULL)
        return;

    image_cache_t *source = NULL;
    theme_element_t *elem = theme->vcdMainElems.first;
    while (elem != NULL) {
        if (elem->type == ELEM_TYPE_GAME_IMAGE) {
            mutable_image_t *gameImage = (mutable_image_t *)elem->extended;
            if (gameImage != NULL && gameImage->cache != NULL && gameImage->cache->suffix != NULL &&
                strcmp(gameImage->cache->suffix, "COV") == 0 && !isDecoratorCoverImage(theme, gameImage)) {
                source = gameImage->cache; // the COV cache shared with the games view (via findDuplicate)
                break;
            }
        }
        elem = elem->next;
    }
    // Only separate when the cache is genuinely shared with a non-vcd family. If it is vcd-private there
    // is nothing to separate, and cloning + re-pointing would orphan (leak) the original cache.
    if (source == NULL || !vcdCoverCacheSharedOutsideVcd(theme, source))
        return;

    image_cache_t *replacement = cloneImageCache(theme, source);
    if (replacement == NULL)
        return;

    int replacementAssigned = 0;
    replaceSharedCoverCache(theme, &theme->vcdMainElems, source, replacement, &replacementAssigned);
    replaceSharedCoverCache(theme, &theme->vcdInfoElems, source, replacement, &replacementAssigned);

    if (!replacementAssigned)
        cacheDestroyCache(replacement);
}

static void validateGUIElems(const char *themePath, config_set_t *themeConfig, theme_t *theme)
{
    // 1. check we have a valid Background elements
    validateBackgroundElems(themePath, themeConfig, theme, &theme->mainElems, &theme->infoElems);
    validateBackgroundElems(themePath, themeConfig, theme, &theme->appsMainElems, &theme->appsInfoElems);
    validateBackgroundElems(themePath, themeConfig, theme, &theme->favsMainElems, &theme->favsInfoElems);
    validateBackgroundElems(themePath, themeConfig, theme, &theme->vcdMainElems, &theme->vcdInfoElems);

    // 2. check we have a valid ItemsList element, and link its decorator to the target element
    validateItemsList(themePath, themeConfig, theme, theme->gamesItemsList, &theme->mainElems);
    validateItemsList(themePath, themeConfig, theme, theme->appsItemsList, &theme->appsMainElems);
    validateItemsList(themePath, themeConfig, theme, theme->favsItemsList, &theme->favsMainElems);
    validateItemsList(themePath, themeConfig, theme, theme->vcdItemsList, &theme->vcdMainElems);

    // Items-list decorator covers need their own cache; sharing with selected covers defeats MMCE cover clamping.
    splitDecoratorCoverCache(theme, theme->gamesItemsList);
    splitDecoratorCoverCache(theme, theme->appsItemsList);
    splitDecoratorCoverCache(theme, theme->favsItemsList);
    splitDecoratorCoverCache(theme, theme->vcdItemsList);

    // The L3 VCD view reuses the device's own game list (same item ids), so its selected/carousel covers
    // must not share a COV cache with the ISO list -- otherwise toggling thrashes the same cache slots.
    separateVcdCoverCache(theme);

    // Selected-cover caches do not need history unless a real items list decorator uses them.
    clampSelectedCoverCaches(theme, &theme->mainElems);
    clampSelectedCoverCaches(theme, &theme->infoElems);
    clampSelectedCoverCaches(theme, &theme->appsMainElems);
    clampSelectedCoverCaches(theme, &theme->appsInfoElems);
    clampSelectedCoverCaches(theme, &theme->favsMainElems);
    clampSelectedCoverCaches(theme, &theme->favsInfoElems);
    clampSelectedCoverCaches(theme, &theme->vcdMainElems);
    clampSelectedCoverCaches(theme, &theme->vcdInfoElems);
}

static int addGUIElem(const char *themePath, config_set_t *themeConfig, theme_t *theme, theme_elems_t *elems, const char *type, const char *name)
{
    int enabled = 1;
    char elemProp[64];
    theme_element_t *elem = NULL;

    snprintf(elemProp, sizeof(elemProp), "%s_enabled", name);
    configGetInt(themeConfig, elemProp, &enabled);

    if (enabled) {
        snprintf(elemProp, sizeof(elemProp), "%s_type", name);
        configGetStr(themeConfig, elemProp, &type);
        if (type) {
            if (!strcmp(elementsType[ELEM_TYPE_ATTRIBUTE_TEXT], type)) {
                elems->needsItemConfig = 1;
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ATTRIBUTE_TEXT, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                initAttributeText(themePath, themeConfig, theme, elem, name);
            } else if (!strcmp(elementsType[ELEM_TYPE_STATIC_TEXT], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_STATIC_TEXT, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                initStaticText(themePath, themeConfig, theme, elem, name);
            } else if (!strcmp(elementsType[ELEM_TYPE_GAME_COUNT_TEXT], type)) {
                elems->needsItemConfig = 1;
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_STATIC_TEXT, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                initGameCountText(themePath, themeConfig, theme, elem, name);
            } else if (!strcmp(elementsType[ELEM_TYPE_ATTRIBUTE_IMAGE], type)) {
                elems->needsItemConfig = 1;
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ATTRIBUTE_IMAGE, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initAttributeImage(themePath, themeConfig, theme, elem, name);
            } else if (!strcmp(elementsType[ELEM_TYPE_GAME_IMAGE], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_GAME_IMAGE, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initGameImage(themePath, themeConfig, theme, elem, name, NULL, 1, NULL, NULL);
            } else if (!strcmp(elementsType[ELEM_TYPE_STATIC_IMAGE], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_STATIC_IMAGE, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initStaticImage(themePath, themeConfig, theme, elem, name, NULL);
            } else if (!strcmp(elementsType[ELEM_TYPE_BACKGROUND], type)) {
                if (!elems->first) { // Background elem can only be the first one
                    elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_BACKGROUND, 0, 0, ALIGN_NONE, screenWidth, screenHeight, SCALING_NONE, gDefaultCol, theme->fonts[0]);
                    initBackground(themePath, themeConfig, theme, elem, name, NULL, 1, NULL);
                }
            } else if (!strcmp(elementsType[ELEM_TYPE_MENU_ICON], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_MENU_ICON, screenWidth >> 1, 400, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                elem->drawElem = &drawMenuIcon;
            } else if (!strcmp(elementsType[ELEM_TYPE_MENU_TEXT], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_MENU_TEXT, screenWidth >> 1, 20, ALIGN_CENTER, 200, 20, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                elem->drawElem = &drawMenuText;
            } else if (!strcmp(elementsType[ELEM_TYPE_ITEMS_LIST], type)) {
                if (!theme->gamesItemsList) {
                    elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ITEMS_LIST, 0, 0, ALIGN_NONE, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                    initItemsList(themePath, themeConfig, theme, elem, name, NULL);
                    theme->gamesItemsList = elem;
                } else if (!theme->appsItemsList) {
                    elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ITEMS_LIST, 42, 42, ALIGN_NONE, 400, 360, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                    initItemsList(themePath, themeConfig, theme, elem, name, NULL);
                    theme->appsItemsList = elem;
                } else if (!theme->favsItemsList) {
                    elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ITEMS_LIST, 42, 42, ALIGN_NONE, 400, 360, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                    initItemsList(themePath, themeConfig, theme, elem, name, NULL);
                    theme->favsItemsList = elem;
                } else if (!theme->vcdItemsList) {
                    elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ITEMS_LIST, 42, 42, ALIGN_NONE, 400, 360, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                    initItemsList(themePath, themeConfig, theme, elem, name, NULL);
                    theme->vcdItemsList = elem; // 4th slot: the L3 VCD view's own items list (own cover cache)
                }
            } else if (!strcmp(elementsType[ELEM_TYPE_ITEM_ICON], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_GAME_IMAGE, 0, 0, ALIGN_CENTER, 64, 64, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initGameImage(themePath, themeConfig, theme, elem, name, "ICO", 20, NULL, NULL);
            } else if (!strcmp(elementsType[ELEM_TYPE_ITEM_COVER], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_GAME_IMAGE, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initGameImage(themePath, themeConfig, theme, elem, name, "COV", 10, NULL, NULL);
            } else if (!strcmp(elementsType[ELEM_TYPE_ITEM_TEXT], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_ITEM_TEXT, 0, 0, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                elem->drawElem = &drawItemText;
            } else if (!strcmp(elementsType[ELEM_TYPE_HINT_TEXT], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_HINT_TEXT, 16, -HINT_HEIGHT, ALIGN_NONE, 12, 20, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                elem->drawElem = &drawHintText;
            } else if (!strcmp(elementsType[ELEM_TYPE_INFO_HINT_TEXT], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_INFO_HINT_TEXT, 16, -HINT_HEIGHT, ALIGN_NONE, 12, 20, SCALING_RATIO, theme->textColor, theme->fonts[0]);
                elem->drawElem = &drawInfoHintText;
            } else if (!strcmp(elementsType[ELEM_TYPE_LOADING_ICON], type)) {
                if (!theme->loadingIcon)
                    theme->loadingIcon = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_LOADING_ICON, -40, -60, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
            } else if (!strcmp(elementsType[ELEM_TYPE_BDM_INDEX], type)) {
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_BDM_INDEX, screenWidth >> 1, 355, ALIGN_CENTER, DIM_UNDEF, DIM_UNDEF, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                elem->drawElem = &drawBDMIndex;
            } else if (!strcmp(elementsType[ELEM_TYPE_COVERFLOW], type)) {
                // GAME_IMAGE-backed (COV cache) so initMutableImage/findDuplicate work unchanged.
                // Allow one per list (e.g. a games "main" coverflow + an "appsMain" coverflow,
                // like wOPL); initCoverflow points gTheme->coverflow at the FIRST as the active flag.
                elem = initBasic(themePath, themeConfig, theme, name, ELEM_TYPE_GAME_IMAGE, screenWidth >> 1, screenHeight >> 1, ALIGN_CENTER, 150, 210, SCALING_RATIO, gDefaultCol, theme->fonts[0]);
                initCoverflow(themePath, themeConfig, theme, elem, name);
            }

            if (elem) {
                if (!elems->first)
                    elems->first = elem;

                if (!elems->last)
                    elems->last = elem;
                else {
                    elems->last->next = elem;
                    elems->last = elem;
                }
            }
        } else
            return 0; // ends the reading of elements
    }

    return 1;
}

static void freeGUIElems(theme_elems_t *elems)
{
    theme_element_t *elem = elems->first;
    while (elem) {
        elems->first = elem->next;
        elem->endElem(elem);
        elem = elems->first;
    }
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

GSTEXTURE *thmGetTexture(unsigned int id)
{
    if (id >= TEXTURES_COUNT)
        return NULL;
    else {
        // see if the texture is valid
        GSTEXTURE *txt = &gTheme->textures[id];

        if (txt->Mem)
            return txt;
        else
            return NULL;
    }
}

static void thmFree(theme_t *theme)
{
    if (theme) {
        // free elements
        freeGUIElems(&theme->mainElems);
        freeGUIElems(&theme->infoElems);
        freeGUIElems(&theme->appsMainElems);
        freeGUIElems(&theme->appsInfoElems);
        freeGUIElems(&theme->favsMainElems);
        freeGUIElems(&theme->favsInfoElems);
        freeGUIElems(&theme->vcdMainElems);
        freeGUIElems(&theme->vcdInfoElems);

        // free textures
        GSTEXTURE *texture;
        int id = 0;
        for (; id < TEXTURES_COUNT; id++) {
            texture = &theme->textures[id];
            if (texture->Mem != NULL) {
                rmUnloadTexture(texture);
                texFree(texture);
            }
        }

        // free fonts
        for (id = 0; id < THM_MAX_FONTS; ++id)
            fntRelease(theme->fonts[id]);

        // The loading icon is stored outside the four managed element lists, so
        // free it explicitly (endBasic) to avoid leaking it on every theme reload.
        if (theme->loadingIcon)
            theme->loadingIcon->endElem(theme->loadingIcon);

        free(theme);
    }
}

static int thmReadEntry(int index, const char *path, const char *separator, const char *name, unsigned char d_type)
{
    if (d_type == DT_DIR && strstr(name, "thm_")) {
        theme_file_t *currTheme = &themes[nThemes + index];

        int length = strlen(name) - 4 + 1;
        currTheme->name = (char *)malloc(length * sizeof(char));
        memcpy(currTheme->name, name + 4, length);
        currTheme->name[length - 1] = '\0';

        length = strlen(path) + 1 + strlen(name) + 1 + 1;
        currTheme->filePath = (char *)malloc(length * sizeof(char));
        sprintf(currTheme->filePath, "%s%s%s%s", path, separator, name, separator);

        LOG("THEMES Theme found: %s\n", currTheme->filePath);

        index++;
    }
    return index;
}

/* themePath must contains the leading separator (as it is dependent of the device, we can't know here) */
static int thmLoadResource(GSTEXTURE *texture, int texId, const char *themePath, short psm, int useDefault)
{
    int success = -1;

    if (themePath != NULL)
        success = texDiscoverLoad(texture, themePath, texId); // only set success here

    if ((success < 0) && useDefault)
        texLoadInternal(texture, texId); // we don't mind the result of "default"

    return success;
}

static void thmSetColors(theme_t *theme)
{
    memcpy(theme->bgColor, gDefaultBgColor, 3);
    theme->textColor = GS_SETREG_RGBA(gDefaultTextColor[0], gDefaultTextColor[1], gDefaultTextColor[2], 0x80);
    theme->uiTextColor = GS_SETREG_RGBA(gDefaultUITextColor[0], gDefaultUITextColor[1], gDefaultUITextColor[2], 0x80);
    theme->selTextColor = GS_SETREG_RGBA(gDefaultSelTextColor[0], gDefaultSelTextColor[1], gDefaultSelTextColor[2], 0x80);

    theme_element_t *elem = theme->mainElems.first;
    while (elem) {
        elem->color = theme->textColor;
        elem = elem->next;
    }
}

static void thmLoadFonts(config_set_t *themeConfig, const char *themePath, theme_t *theme)
{
    int fntID; // theme side font id, not the fntSys handle
    for (fntID = 0; fntID < THM_MAX_FONTS; ++fntID) {
        // does the font by the key exist?
        char fntKey[16];

        if (fntID == 0) {
            snprintf(fntKey, sizeof(fntKey), "default_font");
            theme->fonts[0] = FNT_DEFAULT;
        } else {
            snprintf(fntKey, sizeof(fntKey), "font%d", fntID);
            theme->fonts[fntID] = theme->fonts[0];
        }

        char fullPath[128];
        const char *fntFile;
        if (configGetStr(themeConfig, fntKey, &fntFile)) {
            snprintf(fullPath, sizeof(fullPath), "%s%s", themePath, fntFile);

            int fontSize;
            char sizeKey[64];
            if (fntID == 0)
                snprintf(sizeKey, sizeof(sizeKey), "default_font_size");
            else
                snprintf(sizeKey, sizeof(sizeKey), "font%d_size", fntID);

            if (!configGetInt(themeConfig, sizeKey, &fontSize) || fontSize <= 0)
                fontSize = FNTSYS_DEFAULT_SIZE;

            int fntHandle = fntLoadFile(fullPath, fontSize);
            // Do we have a valid font? Assign the font handle to the theme font slot
            if (fntHandle != FNT_ERROR)
                theme->fonts[fntID] = fntHandle;
        }
    }
}

static void thmLoad(const char *themePath)
{
    LOG("THEMES Load theme path=%s\n", themePath);
    char path[256];
    theme_t *curT = gTheme;
    theme_t *newT = (theme_t *)malloc(sizeof(theme_t));
    memset(newT, 0, sizeof(theme_t));

    newT->useDefault = 1;
    newT->usedHeight = 480;
    thmSetColors(newT);
    newT->mainElems.first = NULL;
    newT->mainElems.last = NULL;
    newT->infoElems.first = NULL;
    newT->infoElems.last = NULL;
    newT->appsMainElems.first = NULL;
    newT->appsMainElems.last = NULL;
    newT->appsInfoElems.first = NULL;
    newT->appsInfoElems.last = NULL;
    newT->favsMainElems.first = NULL;
    newT->favsMainElems.last = NULL;
    newT->favsInfoElems.first = NULL;
    newT->favsInfoElems.last = NULL;
    newT->vcdMainElems.first = NULL;
    newT->vcdMainElems.last = NULL;
    newT->vcdInfoElems.first = NULL;
    newT->vcdInfoElems.last = NULL;
    newT->gameCacheCount = 0;
    newT->itemsList = NULL;
    newT->gamesItemsList = NULL;
    newT->appsItemsList = NULL;
    newT->favsItemsList = NULL;
    newT->vcdItemsList = NULL;
    newT->coverflow = NULL;
    newT->coverflowCoverOffset = 0;
    newT->loadingIcon = NULL;
    newT->loadingIconCount = LOAD7_ICON - LOAD0_ICON + 1;

    config_set_t *themeConfig = NULL;
    if (!themePath) {
        // No theme specified. Prepare and load the default theme.
        themeConfig = configAlloc(0, NULL, NULL);
        if (gLoadCoverflowBuiltin)
            configReadBuffer(themeConfig, &theme_coverflow_cfg, size_theme_coverflow_cfg);
        else
            configReadBuffer(themeConfig, &conf_theme_OPL_cfg, size_conf_theme_OPL_cfg);
    } else {
        snprintf(path, sizeof(path), "%sconf_theme.cfg", themePath);
        themeConfig = configAlloc(0, NULL, path);
        configRead(themeConfig); // try to load the theme config file. If it does not exist, defaults will be used.
    }

    int intValue;
    if (configGetInt(themeConfig, "use_default", &intValue))
        newT->useDefault = intValue;

    if (configGetInt(themeConfig, "use_real_height", &intValue)) {
        if (intValue)
            newT->usedHeight = screenHeight;
    }

    configGetColor(themeConfig, "bg_color", newT->bgColor);

    unsigned char color[3];
    if (configGetColor(themeConfig, "text_color", color))
        newT->textColor = GS_SETREG_RGBA(color[0], color[1], color[2], 0x80);

    if (configGetColor(themeConfig, "ui_text_color", color))
        newT->uiTextColor = GS_SETREG_RGBA(color[0], color[1], color[2], 0x80);

    if (configGetColor(themeConfig, "sel_text_color", color))
        newT->selTextColor = GS_SETREG_RGBA(color[0], color[1], color[2], 0x80);

    if (configGetInt(themeConfig, "coverflow_cover_offset", &intValue)) {
        // clamp -- this feeds coverWidth * offset / 256 in drawCoverFlow; an
        // unbounded value from an untrusted theme .cfg would signed-overflow that
        // multiply (Codex audit, Low 1). The range is far wider than any real theme.
        if (intValue < -1024)
            intValue = -1024;
        else if (intValue > 1024)
            intValue = 1024;
        newT->coverflowCoverOffset = intValue;
    }

    // before loading the element definitions, we have to have the fonts prepared
    // for that, we load the fonts and a translation table
    if (themePath)
        thmLoadFonts(themeConfig, themePath, newT);

    int i = 1, j;
    snprintf(path, sizeof(path), "main0");
    while (addGUIElem(themePath, themeConfig, newT, &newT->mainElems, NULL, path))
        snprintf(path, sizeof(path), "main%d", i++);

    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "appsMain%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->appsMainElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "main%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->appsMainElems, NULL, path);
        }
    }

    // Favourites family: favsMain<j> override, else fall back to main<j> (identical to appsMain).
    // Runs after appsMain so a favsMain ItemsList claims the 3rd slot (favsItemsList), and before
    // the info passes so an info ItemsList never steals it.
    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "favsMain%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->favsMainElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "main%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->favsMainElems, NULL, path);
        }
    }

    // VCD/PS1 view main family: vcdMain<j> override, else fall back to appsMain<j> (the square box),
    // else main<j>. The apps fallback means a theme that defines no vcdMain still gets the square VCD
    // look it had before this family existed. An ItemsList reached via this fallback claims the 4th
    // slot (vcdItemsList) in addGUIElem, giving the VCD list its OWN cover cache (separateVcdCoverCache).
    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "vcdMain%d", j);
        if (addGUIElem(themePath, themeConfig, newT, &newT->vcdMainElems, NULL, path))
            continue;
        snprintf(path, sizeof(path), "appsMain%d", j);
        if (addGUIElem(themePath, themeConfig, newT, &newT->vcdMainElems, NULL, path))
            continue;
        snprintf(path, sizeof(path), "main%d", j);
        addGUIElem(themePath, themeConfig, newT, &newT->vcdMainElems, NULL, path);
    }

    i = 1;
    snprintf(path, sizeof(path), "info0");
    while (addGUIElem(themePath, themeConfig, newT, &newT->infoElems, NULL, path))
        snprintf(path, sizeof(path), "info%d", i++);

    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "appsInfo%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->appsInfoElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "info%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->appsInfoElems, NULL, path);
        }
    }

    // Favourites info family: favsInfo<j> override, else info<j> (identical to appsInfo).
    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "favsInfo%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->favsInfoElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "info%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->favsInfoElems, NULL, path);
        }
    }

    // VCD/PS1 view info family: vcdInfo<j> override, else fall back to info<j>.
    for (j = 0; j < i; j++) {
        snprintf(path, sizeof(path), "vcdInfo%d", j);

        if (addGUIElem(themePath, themeConfig, newT, &newT->vcdInfoElems, NULL, path))
            continue;
        else {
            snprintf(path, sizeof(path), "info%d", j);
            addGUIElem(themePath, themeConfig, newT, &newT->vcdInfoElems, NULL, path);
        }
    }

    validateGUIElems(themePath, themeConfig, newT);

    newT->itemsList = newT->gamesItemsList;

    // NOTE: themeConfig is freed AFTER the texture-load section below -- the use_settings_bg lookup near
    // the end still reads it. Freeing here was a use-after-free (configGetInt on freed memory).
    LOG("THEMES Number of cache: %d\n", newT->gameCacheCount);
    LOG("THEMES Used height: %d\n", newT->usedHeight);

    // default all to not loaded...
    for (i = 0; i < TEXTURES_COUNT; i++)
        newT->textures[i].Mem = NULL;

    // LOGO, loaded here to avoid flickering during startup with device in AUTO + theme set
    texLoadInternal(&newT->textures[LOGO_PICTURE], LOGO_PICTURE);

    // Optional animated boot-logo frames (embedded build assets logo0..logo6).
    // Count the contiguous frames that actually load; guiRenderGreeting() cycles
    // them on the boot splash. Zero when none are embedded -> single LOGO_PICTURE.
    newT->logoFrameCount = 0;
    for (i = LOGO0_PICTURE; i <= LOGO6_PICTURE; i++) {
        texLoadInternal(&newT->textures[i], i);
        if (newT->textures[i].Mem != NULL)
            newT->logoFrameCount++;
        else
            break;
    }

    // First start with busy icon
    const char *themePath_temp = themePath;
    int customBusy = 0;
    for (i = LOAD0_ICON; i <= LOAD7_ICON; i++) {
        if (thmLoadResource(&newT->textures[i], i, themePath_temp, GS_PSM_CT32, newT->useDefault) >= 0)
            customBusy = 1;
        else {
            if (customBusy)
                break;
            else
                themePath_temp = NULL;
        }
    }
    newT->loadingIconCount = i;

    // Customizable icons
    for (i = BDM_ICON; i <= START_ICON; i++)
        thmLoadResource(&newT->textures[i], i, themePath, GS_PSM_CT32, newT->useDefault);

    // Control-hint glyphs + Favourites tab icon/star: internal defaults only (theme-independent).
    // Contiguous L3_ICON..FAV_MARK in the enum -> the VCD L3 hint (L3_ICON), the Favourites R3 hint
    // (R3_ICON), the FAV tab icon (FAV_ICON) and the favourited-item star (FAV_MARK). Previously the
    // loop was commented out, so the R3/fav icons silently never loaded (thmGetTexture returned NULL).
    for (i = L3_ICON; i <= FAV_MARK; i++)
        thmLoadResource(&newT->textures[i], i, NULL, GS_PSM_CT32, 1);

    if (!themePath)
        for (i = ELF_FORMAT; i <= VMODE_PAL; i++)
            thmLoadResource(&newT->textures[i], i, NULL, GS_PSM_CT32, 1);

    // Optional settings/menu background (guiDrawBGSettings draws it instead of the plasma).
    // Theme-supplied only for now: a disk theme opts in with use_settings_bg=1 and ships its
    // own settings_bg.png. No embedded default yet (internalDefault[SETTINGS_BG] is NULL), so
    // the built-in <OPL>/<Coverflow> themes leave the slot empty and keep the plasma.
    if (themePath) {
        if (configGetInt(themeConfig, "use_settings_bg", &intValue) && intValue)
            thmLoadResource(&newT->textures[SETTINGS_BG], SETTINGS_BG, themePath, GS_PSM_CT32, 0);
    }

    configFree(themeConfig); // all themeConfig reads are done now (last was use_settings_bg above)

    cacheCancelPendingImageLoads();
    gTheme = newT;
    thmFree(curT);
}

static void thmRebuildGuiNames(void)
{
    if (guiThemesNames)
        free(guiThemesNames);

    // build the themes name list (+1 default internal, +1 built-in coverflow, +1 NULL)
    guiThemesNames = (const char **)malloc((nThemes + 3) * sizeof(char **));

    // add default internal
    guiThemesNames[0] = "<OPL>";

    int i = 0;
    for (; i < nThemes; i++) {
        guiThemesNames[i + 1] = themes[i].name;
    }

    // built-in coverflow theme occupies the slot right after the disk themes
    guiThemesNames[nThemes + 1] = "<Coverflow>";
    guiThemesNames[nThemes + 2] = NULL;
}

int thmAddElements(char *path, const char *separator, int forceRefresh)
{
    int result, i;

    result = listDir(path, separator, THM_MAX_FILES - nThemes, &thmReadEntry);
    nThemes += result;
    thmRebuildGuiNames();

    const char *temp;
    if (configGetStr(configGetByType(CONFIG_OPL), "theme", &temp)) {
        LOG("THEMES Trying to set again theme: %s\n", temp);
        if (thmSetGuiValue(thmFindGuiID(temp), 0) && forceRefresh) {
            for (i = 0; i < MODE_COUNT; i++)
                moduleUpdateMenu(i, 1, 0);
        }
    }

    return result;
}

void thmInit(void)
{
    LOG("THEMES Init\n");
    gTheme = NULL;

    thmReloadScreenExtents();

    // initialize default internal
    thmLoad(NULL);

    thmAddElements(gBaseMCDir, "/", 0);
}

void thmReinit(const char *path)
{
    thmLoad(NULL);
    guiThemeID = 0;

    int i = 0;
    while (i < nThemes) {
        if (strncmp(themes[i].filePath, path, strlen(path)) == 0) {
            LOG("THEMES Remove theme: %s\n", themes[i].filePath);
            nThemes--;
            free(themes[i].name);
            themes[i].name = themes[nThemes].name;
            themes[nThemes].name = NULL;
            free(themes[i].filePath);
            themes[i].filePath = themes[nThemes].filePath;
            themes[nThemes].filePath = NULL;
        } else
            i++;
    }

    thmRebuildGuiNames();
}

void thmReloadScreenExtents(void)
{
    rmGetScreenExtents(&screenWidth, &screenHeight);
}

const char *thmGetValue(void)
{
    return guiThemesNames[guiThemeID];
}

int thmSetGuiValue(int themeID, int reload)
{
    if (themeID != -1) {
        if (guiThemeID != themeID || reload) {
            if (themeID == nThemes + 1) {
                // built-in coverflow theme: load the embedded buffer via thmLoad(NULL).
                // Checked BEFORE the themes[themeID - 1] access below (which would be OOB).
                gLoadCoverflowBuiltin = 1;
                thmLoad(NULL);
                gLoadCoverflowBuiltin = 0;
            } else
                thmLoad(themeID != 0 ? themes[themeID - 1].filePath : NULL);

            guiThemeID = themeID;
            return 1;
        } else if (guiThemeID == 0)
            thmSetColors(gTheme);
    }
    return 0;
}

int thmGetGuiValue(void)
{
    return guiThemeID;
}

int thmFindGuiID(const char *theme)
{
    if (theme) {
        if (strcasecmp(theme, "<Coverflow>") == 0)
            return nThemes + 1; // built-in coverflow theme
        int i = 0;
        for (; i < nThemes; i++) {
            if (strcasecmp(themes[i].name, theme) == 0)
                return i + 1;
        }
    }
    return 0;
}

const char **thmGetGuiList(void)
{
    return guiThemesNames;
}

char *thmGetFilePath(int themeID)
{
    // Disk themes occupy IDs 1..nThemes. The built-ins (<OPL> = 0, <Coverflow> = nThemes+1)
    // and any out-of-range ID have no on-disk path -> return NULL so callers fall back to
    // the default/internal assets instead of indexing themes[] out of bounds.
    if (themeID <= 0 || themeID > nThemes)
        return NULL;

    theme_file_t *currTheme = &themes[themeID - 1];
    char *path = currTheme->filePath;

    return path;
}

void thmEnd(void)
{
    thmFree(gTheme);

    int i = 0;
    for (; i < nThemes; i++) {
        free(themes[i].name);
        free(themes[i].filePath);
    }

    free(guiThemesNames);
}
