/*
  Copyright 2024, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Favourites (FAV_MODE): a virtual tab that aggregates favourited items from every loaded
  device list. Each favourite proxies launch / config / art / flags to its source list.
  Persistence uses a versioned, bounds-checked binary store (favourites.bin) written with
  explicit scalar fields -- never a raw-struct fwrite -- so a corrupt file can never index
  or allocate out of bounds.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>

#include "include/opl.h"
#include "include/iosupport.h"
#include "include/menusys.h"
#include "include/ioman.h"
#include "include/lang.h"
#include "include/textures.h"
#include "include/config.h"
#include "include/favsupport.h"

int gFAVStartMode;

// Forward declaration; the initialised definition is at the bottom of this file.
static item_list_t favItemList;

// In-memory, validated favourites. Rebuilt by favUpdateItemList from favourites.bin; each
// entry's owner/id are confirmed present in the source submenu, so proxying never goes OOB.
typedef struct
{
    item_list_t *owner; // resolved source list
    int mode;           // resolved source mode (BDM re-matched across slots)
    int id;             // source item id (validated present in owner's submenu)
    int icon_id;
    int text_id;
    char *text; // heap copy; owned here
} fav_rec_t;

static fav_rec_t *favArray = NULL;
static int favCount = 0;

static char *favStrdup(const char *s)
{
    int n = (int)strlen(s) + 1;
    char *p = (char *)malloc(n);
    if (p != NULL)
        memcpy(p, s, n);
    return p;
}

// ---- on-disk path -------------------------------------------------------------

// favourites.bin lives next to conf_opl.cfg (same OPL config dir, whatever device that is).
static void favGetFilePath(char *out, int outSize)
{
    config_set_t *cfg = configGetByType(CONFIG_OPL);
    const char *fn = (cfg != NULL && cfg->filename != NULL) ? cfg->filename : "mc0:OPL/conf_opl.cfg";
    const char *base = "conf_opl.cfg";
    int len = (int)strlen(fn);
    int blen = (int)strlen(base);
    if (len >= blen && strcmp(fn + len - blen, base) == 0) {
        int dirLen = len - blen;
        if (dirLen > outSize - 1)
            dirLen = outSize - 1;
        memcpy(out, fn, dirLen);
        out[dirLen] = '\0';
        strncat(out, "favourites.bin", outSize - strlen(out) - 1);
    } else {
        snprintf(out, outSize, "mc0:OPL/favourites.bin");
    }
}

// ---- explicit little-endian scalar IO (never raw-struct) ----------------------

static int rdBytes(int fd, void *buf, int n) { return read(fd, buf, n) == n; }
static int wrBytes(int fd, const void *buf, int n) { return write(fd, (void *)buf, n) == n; }

static int rdU16(int fd, u16 *v)
{
    u8 b[2];
    if (!rdBytes(fd, b, 2))
        return 0;
    *v = (u16)(b[0] | (b[1] << 8));
    return 1;
}
static int rdU32(int fd, u32 *v)
{
    u8 b[4];
    if (!rdBytes(fd, b, 4))
        return 0;
    *v = (u32)b[0] | ((u32)b[1] << 8) | ((u32)b[2] << 16) | ((u32)b[3] << 24);
    return 1;
}
static int wrU16(int fd, u16 v)
{
    u8 b[2] = {(u8)(v & 0xff), (u8)((v >> 8) & 0xff)};
    return wrBytes(fd, b, 2);
}
static int wrU32(int fd, u32 v)
{
    u8 b[4] = {(u8)(v & 0xff), (u8)((v >> 8) & 0xff), (u8)((v >> 16) & 0xff), (u8)((v >> 24) & 0xff)};
    return wrBytes(fd, b, 4);
}

// ---- raw on-disk record (pre-validation) --------------------------------------

typedef struct
{
    int mode;
    int id;
    int icon_id;
    int text_id;
    char text[FAV_TEXT_MAX];
} fav_raw_t;

// Read + bounds-check the whole file into a heap array of raw records. Returns NULL (and
// *outCount = 0) on any error/corruption. Caller frees the array.
static fav_raw_t *favReadFile(int *outCount)
{
    char path[256];
    *outCount = 0;
    favGetFilePath(path, sizeof(path));

    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return NULL;

    u32 magic = 0;
    u16 ver = 0, cnt = 0;
    if (!rdU32(fd, &magic) || !rdU16(fd, &ver) || !rdU16(fd, &cnt) || magic != FAV_MAGIC || ver != FAV_VERSION) {
        LOG("FAV reject header magic=%08x ver=%d\n", (unsigned)magic, ver);
        close(fd);
        return NULL;
    }
    if (cnt == 0) {
        close(fd);
        return NULL;
    }
    if (cnt > FAV_MAX_ITEMS)
        cnt = FAV_MAX_ITEMS; // never trust the stored count beyond the hard cap

    fav_raw_t *recs = (fav_raw_t *)calloc(cnt, sizeof(fav_raw_t));
    if (recs == NULL) {
        close(fd);
        return NULL;
    }

    int got = 0;
    for (int i = 0; i < (int)cnt; i++) {
        u16 mode = 0, tlen = 0;
        u32 id = 0, icon = 0, tid = 0;
        if (!rdU16(fd, &mode) || !rdU32(fd, &id) || !rdU32(fd, &icon) || !rdU32(fd, &tid) || !rdU16(fd, &tlen))
            break; // short read -> stop, keep what we have
        if (tlen == 0 || tlen > FAV_TEXT_MAX) {
            LOG("FAV bad text_len=%d, aborting parse\n", tlen);
            break; // cannot resync past an unknown-length field -> stop
        }
        if (!rdBytes(fd, recs[got].text, tlen))
            break;                       // short read on text -> stop
        recs[got].text[tlen - 1] = '\0'; // tlen includes the NUL; force-terminate
        recs[got].mode = (int)mode;
        recs[got].id = (int)id;
        recs[got].icon_id = (int)icon;
        recs[got].text_id = (int)tid;
        got++;
    }
    close(fd);

    if (got == 0) {
        free(recs);
        return NULL;
    }
    *outCount = got;
    return recs;
}

// Write a raw-record array back out (explicit scalar fields; pointers never persisted).
static void favWriteFile(fav_raw_t *recs, int count)
{
    char path[256];
    favGetFilePath(path, sizeof(path));

    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        LOG("FAV write open failed: %s\n", path);
        return;
    }
    if (count > FAV_MAX_ITEMS)
        count = FAV_MAX_ITEMS;

    int ok = wrU32(fd, FAV_MAGIC) && wrU16(fd, FAV_VERSION) && wrU16(fd, (u16)count);
    for (int i = 0; ok && i < count; i++) {
        int tlen = (int)strlen(recs[i].text) + 1;
        if (tlen > FAV_TEXT_MAX)
            tlen = FAV_TEXT_MAX;
        ok = wrU16(fd, (u16)recs[i].mode) && wrU32(fd, (u32)recs[i].id) && wrU32(fd, (u32)recs[i].icon_id) &&
             wrU32(fd, (u32)recs[i].text_id) && wrU16(fd, (u16)tlen) && wrBytes(fd, recs[i].text, tlen);
    }
    close(fd);
    if (!ok)
        LOG("FAV write incomplete\n");
}

// ---- in-memory array lifecycle ------------------------------------------------

static void favFreeArray(void)
{
    if (favArray != NULL) {
        for (int i = 0; i < favCount; i++)
            free(favArray[i].text);
        free(favArray);
        favArray = NULL;
    }
    favCount = 0;
}

// Resolve a stored record to a live source list + mark the source item favourited. BDM-range
// modes are re-matched across all 8 slots (hotplug / different bus). Returns the resolved
// owner (or NULL if the source isn't loaded / the item is absent).
static item_list_t *favResolve(int mode, int id, const char *text, int *outMode)
{
    *outMode = mode;
    if (mode >= BDM_MODE && mode <= BDM_MODE_LAST) {
        for (int m = BDM_MODE; m <= BDM_MODE_LAST; m++) {
            opl_io_module_t *mod = oplGetModule(m);
            if (mod == NULL || mod->support == NULL)
                continue;
            submenu_list_t *src = submenuFindItemByIdAndText(mod->subMenu, id, text);
            if (src != NULL) {
                src->item.favourited = 1;
                *outMode = m;
                return mod->support;
            }
        }
        return NULL;
    }
    if (mode < 0 || mode >= MODE_COUNT)
        return NULL;
    opl_io_module_t *mod = oplGetModule(mode);
    if (mod == NULL || mod->support == NULL)
        return NULL;
    submenu_list_t *src = submenuFindItemByIdAndText(mod->subMenu, id, text);
    if (src == NULL)
        return NULL;
    src->item.favourited = 1;
    return mod->support;
}

// ---- item_list_t callbacks ----------------------------------------------------

static int favGetTextId(item_list_t *itemList) { return _STR_FAV; }
static int favGetIconId(item_list_t *itemList) { return FAV_ICON; }
static int favNeedsUpdate(item_list_t *itemList) { return 0; }

static void favInit(item_list_t *itemList)
{
    itemList->enabled = 1;
}

// MUST drive a single append pass: rebuild the validated in-memory array and return its
// count. updateMenuFromGameList does the clear + append from this count -- we never clear or
// append the submenu here (that would double-drive the list).
static int favUpdateItemList(item_list_t *itemList)
{
    favFreeArray();

    int rawCount = 0;
    fav_raw_t *recs = favReadFile(&rawCount);
    if (recs == NULL)
        return 0;

    favArray = (fav_rec_t *)calloc(rawCount, sizeof(fav_rec_t));
    if (favArray == NULL) {
        free(recs);
        return 0;
    }

    for (int i = 0; i < rawCount; i++) {
        int resolvedMode = recs[i].mode;
        item_list_t *owner = favResolve(recs[i].mode, recs[i].id, recs[i].text, &resolvedMode);
        if (owner == NULL)
            continue; // device not loaded / item absent -> hidden (kept in the file)

        char *txt = favStrdup(recs[i].text);
        if (txt == NULL)
            continue; // OOM -> skip this record rather than store a NULL name

        favArray[favCount].owner = owner;
        favArray[favCount].mode = resolvedMode;
        favArray[favCount].id = recs[i].id;
        favArray[favCount].icon_id = recs[i].icon_id;
        favArray[favCount].text_id = recs[i].text_id;
        favArray[favCount].text = txt;
        favCount++;
    }

    free(recs);
    return favCount;
}

static int favGetItemCount(item_list_t *itemList) { return favCount; }

static int favValidIndex(int id) { return (favArray != NULL && id >= 0 && id < favCount); }

static char *favGetItemName(item_list_t *itemList, int id)
{
    return favValidIndex(id) ? favArray[id].text : "";
}

static int favGetItemNameLength(item_list_t *itemList, int id)
{
    return favValidIndex(id) ? ((int)strlen(favArray[id].text) + 1) : 0;
}

static char *favGetItemStartup(item_list_t *itemList, int id)
{
    if (!favValidIndex(id))
        return "";
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemGetStartup == NULL)
        return "";
    return o->itemGetStartup(o, favArray[id].id);
}

static config_set_t *favGetConfig(item_list_t *itemList, int id)
{
    if (!favValidIndex(id))
        return NULL;
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemGetConfig == NULL)
        return NULL;
    return o->itemGetConfig(o, favArray[id].id);
}

static void favLaunchItem(item_list_t *itemList, int id, config_set_t *configSet)
{
    if (!favValidIndex(id))
        return;
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemLaunch == NULL)
        return;
    o->itemLaunch(o, favArray[id].id, configSet);
}

// Art proxy: the cache passes the source item's startup as `value`. Find the favourite whose
// source startup matches and forward to its owner's image lookup.
static int favGetImage(item_list_t *itemList, char *folder, int isRelative, char *value, char *suffix, GSTEXTURE *resultTex, short psm)
{
    if (favArray == NULL || value == NULL)
        return -1;
    for (int i = 0; i < favCount; i++) {
        item_list_t *o = favArray[i].owner;
        if (o == NULL || o->itemGetStartup == NULL || o->itemGetImage == NULL)
            continue;
        char *s = o->itemGetStartup(o, favArray[i].id);
        if (s != NULL && strcmp(s, value) == 0)
            return o->itemGetImage(o, folder, isRelative, value, suffix, resultTex, psm);
    }
    return -1;
}

// Rename/Delete are blocked for favourites (also guarded at the menu level).
static void favDeleteItem(item_list_t *itemList, int id) {}
static void favRenameItem(item_list_t *itemList, int id, char *newName) {}

static void favCleanUp(item_list_t *itemList, int exception)
{
    // Intentionally does NOT free favArray: the FAV submenu's item.text aliases favArray
    // text, and the array is freed/rebuilt only by favUpdateItemList (after the submenu has
    // been cleared) or favShutdown. Freeing here could dangle a live submenu's text.
}

static void favShutdown(item_list_t *itemList)
{
    favFreeArray();
}

unsigned char favGetFlags(item_list_t *itemList)
{
    opl_io_module_t *mod = oplGetModule(FAV_MODE);
    if (mod == NULL || mod->menuItem.current == NULL)
        return 0;
    int id = mod->menuItem.current->item.id;
    if (!favValidIndex(id))
        return 0;
    int m = favArray[id].mode;
    if (m == APP_MODE)
        return MODE_FLAG_NO_COMPAT | MODE_FLAG_NO_UPDATE;
    if (m == HDD_MODE)
        return MODE_FLAG_COMPAT_DMA;
    return 0;
}

// ---- public toggle / refresh API ----------------------------------------------

void addFavouriteItem(int mode, int id, int icon_id, int text_id, const char *text)
{
    if (text == NULL || text[0] == '\0')
        return;

    int count = 0;
    fav_raw_t *recs = favReadFile(&count); // may be NULL (empty / new file)

    // Skip if already present (same mode + id + text).
    for (int i = 0; i < count; i++) {
        if (recs[i].mode == mode && recs[i].id == id && strcmp(recs[i].text, text) == 0) {
            free(recs);
            return;
        }
    }

    int newCount = count + 1;
    if (newCount > FAV_MAX_ITEMS) {
        free(recs);
        return;
    }
    fav_raw_t *out = (fav_raw_t *)calloc(newCount, sizeof(fav_raw_t));
    if (out == NULL) {
        free(recs);
        return;
    }
    for (int i = 0; i < count; i++)
        out[i] = recs[i];
    out[count].mode = mode;
    out[count].id = id;
    out[count].icon_id = icon_id;
    out[count].text_id = text_id;
    snprintf(out[count].text, FAV_TEXT_MAX, "%s", text);

    favWriteFile(out, newCount);
    free(out);
    free(recs);
}

void removeFavouriteByIdAndText(int id, const char *text)
{
    int count = 0;
    fav_raw_t *recs = favReadFile(&count);
    if (recs == NULL)
        return;

    int survivors = 0;
    for (int i = 0; i < count; i++) {
        if (!(recs[i].id == id && text != NULL && strcmp(recs[i].text, text) == 0))
            recs[survivors++] = recs[i]; // compact in place (single buffer)
    }
    favWriteFile(recs, survivors); // survivors may be 0 -> writes a header-only (empty) file
    free(recs);
}

void favRemoveByIndex(int favIndex)
{
    if (!favValidIndex(favIndex))
        return;
    int srcMode = favArray[favIndex].mode;
    int srcId = favArray[favIndex].id;
    char *txt = favArray[favIndex].text;

    // Clear the star on the source-list copy, then drop the record from the store.
    opl_io_module_t *mod = oplGetModule(srcMode);
    if (mod != NULL) {
        submenu_list_t *src = submenuFindItemByIdAndText(mod->subMenu, srcId, txt);
        if (src != NULL)
            src->item.favourited = 0;
    }
    removeFavouriteByIdAndText(srcId, txt);
}

void loadFavourites(void)
{
    // Cheap + idempotent: clear the FAV list and schedule the single canonical rebuild.
    // The actual file read happens once, inside favUpdateItemList.
    menuClearGameList(oplGetModule(FAV_MODE));
    ioPutRequest(IO_MENU_UPDATE_DEFFERED, &favItemList.mode);
}

item_list_t *favGetObject(int initOnly)
{
    if (initOnly && !favItemList.enabled)
        return NULL;
    return &favItemList;
}

static item_list_t favItemList = {
    FAV_MODE, -1, 0, 0, MENU_MIN_INACTIVE_FRAMES, FAV_MODE_UPDATE_DELAY, NULL, NULL, &favGetTextId, NULL, &favInit, &favNeedsUpdate, &favUpdateItemList,
    &favGetItemCount, NULL, &favGetItemName, &favGetItemNameLength, &favGetItemStartup, &favDeleteItem, &favRenameItem, &favLaunchItem,
    &favGetConfig, &favGetImage, &favCleanUp, &favShutdown, NULL, &favGetIconId};
