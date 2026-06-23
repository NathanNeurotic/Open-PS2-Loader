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

// favourites.bin lives next to the master config in the SHARED OPL config dir (not renamed to
// riptopl) so favourites carry across OPL / uOPL / wOPL -- only our settings file is private.
static void favGetFilePath(char *out, int outSize)
{
    config_set_t *cfg = configGetByType(CONFIG_OPL);
    const char *fn = (cfg != NULL && cfg->filename != NULL) ? cfg->filename : "mc0:OPL/" CONFIG_OPL_FILENAME;
    const char *base = CONFIG_OPL_FILENAME;
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

// Little-endian signed 32-bit from a byte buffer (for the foreign-format import below).
static int rdS32le(const u8 *b)
{
    return (int)((u32)b[0] | ((u32)b[1] << 8) | ((u32)b[2] << 16) | ((u32)b[3] << 24));
}

// Translate a uOPL/wOPL IO_MODES value to ours. Their enum differs: they have only 5 BDM slots
// (0..4) then ETH=5, HDD=6, APP=7, FAV=8, MMCE=9; we have 8 BDM slots then ETH=8, HDD=9,
// APP=10, MMCE=11, FAV=12. Without this, a foreign ETH/HDD/APP favourite (5/6/7) would be read
// as one of OUR BDM slots and silently fail to resolve. BDM slots pass through unchanged --
// favResolve re-matches a BDM favourite across all of our slots by id+text anyway.
static int favMapWoplMode(int m)
{
    switch (m) {
        case 5:
            return ETH_MODE;
        case 6:
            return HDD_MODE;
        case 7:
            return APP_MODE;
        case 8:
            return FAV_MODE; // favourite of the FAV tab itself; favResolve will reject it
        case 9:
            return MMCE_MODE;
        default:
            return m; // 0..4 are BDM slots in both schemes; anything else passes through
    }
}

// Import a uOPL/wOPL favourites.bin (read-only). Their format is a header-less stream of
// records, each = a raw 32-byte submenu_item_t (we trust only icon_id@0, text_id@8, id@12; the
// on-disk text/cache/owner POINTERS are garbage and ignored), then int text_len, then the text
// bytes, then a short owner-mode. uOPL and wOPL share this exact layout. We never WRITE it --
// our own writes use the hardened OFAV format -- so this is a one-way carry-over that lets
// favourites set in those builds appear in RiptOPL. Returns NULL on empty/corrupt input.
#define WOPL_FAV_STRUCT_SIZE 32 // sizeof(submenu_item_t) on the EE: 8 x 4-byte fields
static fav_raw_t *favReadWoplFile(int fd, int *outCount)
{
    *outCount = 0;
    fav_raw_t *recs = (fav_raw_t *)calloc(FAV_MAX_ITEMS, sizeof(fav_raw_t));
    if (recs == NULL)
        return NULL;

    int got = 0;
    while (got < FAV_MAX_ITEMS) {
        u8 st[WOPL_FAV_STRUCT_SIZE];
        u32 tlen = 0;
        u16 mode = 0;
        if (!rdBytes(fd, st, WOPL_FAV_STRUCT_SIZE))
            break; // clean EOF (or short tail) -> stop, keep what we have
        if (!rdU32(fd, &tlen))
            break;
        if (tlen == 0 || tlen > FAV_TEXT_MAX) {
            LOG("FAV import: bad text_len=%u (not uOPL/wOPL format?), aborting\n", (unsigned)tlen);
            break; // desync / foreign struct size / corruption -> stop
        }
        if (!rdBytes(fd, recs[got].text, tlen))
            break;
        recs[got].text[tlen - 1] = '\0'; // tlen includes the NUL; force-terminate
        if (!rdU16(fd, &mode))
            break;
        recs[got].icon_id = rdS32le(st + 0);
        recs[got].text_id = rdS32le(st + 8);
        recs[got].id = rdS32le(st + 12);
        recs[got].mode = favMapWoplMode((int)(short)mode); // owner mode (signed short on disk) -> our IO_MODES
        got++;
    }

    if (got == 0) {
        free(recs);
        return NULL;
    }
    LOG("FAV imported %d favourite(s) from uOPL/wOPL format\n", got);
    *outCount = got;
    return recs;
}

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
    int hdrOk = rdU32(fd, &magic) && rdU16(fd, &ver) && rdU16(fd, &cnt);
    if (!hdrOk || magic != FAV_MAGIC) {
        // No OFAV header -> this may be a uOPL/wOPL favourites.bin in the shared OPL dir.
        // Rewind and import it read-only so favourites carry over from those builds.
        LOG("FAV: no OFAV header (magic=%08x) -- attempting uOPL/wOPL import\n", (unsigned)magic);
        lseek(fd, 0, SEEK_SET);
        fav_raw_t *imported = favReadWoplFile(fd, outCount);
        close(fd);
        return imported;
    }
    if (ver != FAV_VERSION) {
        LOG("FAV reject: unsupported OFAV version %d\n", ver);
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
static int favWriteFile(fav_raw_t *recs, int count)
{
    char path[256];
    favGetFilePath(path, sizeof(path));

    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        LOG("FAV write open failed: %s\n", path);
        return 0;
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
    return ok;
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

// The FAV list is rebuilt on demand only. favForceUpdate is raised by loadFavourites (initial
// boot, every source-list change, and each R3 toggle) and consumed exactly once here, so the
// deferred-update driver (menuDeferredUpdate -> updateMenuFromGameList) actually runs
// favUpdateItemList. Starting at 1 makes the FIRST deferred pass populate the tab; a
// self-clearing one-shot -- never a constant 1 -- avoids a per-frame rebuild storm.
static int favForceUpdate = 1;

static int favNeedsUpdate(item_list_t *itemList)
{
    if (favForceUpdate) {
        favForceUpdate = 0;
        return 1;
    }
    return 0;
}

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

// Source device mode (APP_MODE / HDD_MODE / BDM range / ...) of the FAV item at FAV-list index
// id, or -1 if id is out of range. Lets the theme engine redirect e.g. an APP favourite to the
// apps element (correct art folder + case overlay) instead of the game cover element.
int favGetItemSourceMode(int id)
{
    return favValidIndex(id) ? favArray[id].mode : -1;
}

// Guard the stored source id against the owner's CURRENT count -- the source list may have
// shrunk / re-scanned since the favourite was validated, so re-check before every proxy call
// to avoid indexing the owner's game array out of bounds.
static int favOwnerHasId(item_list_t *o, int id)
{
    return (o != NULL && o->itemGetCount != NULL && id >= 0 && id < o->itemGetCount(o));
}

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
    if (o == NULL || o->itemGetStartup == NULL || !favOwnerHasId(o, favArray[id].id))
        return "";
    return o->itemGetStartup(o, favArray[id].id);
}

static config_set_t *favGetConfig(item_list_t *itemList, int id)
{
    if (!favValidIndex(id))
        return NULL;
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemGetConfig == NULL || !favOwnerHasId(o, favArray[id].id))
        return NULL;
    return o->itemGetConfig(o, favArray[id].id);
}

static void favLaunchItem(item_list_t *itemList, int id, config_set_t *configSet)
{
    if (!favValidIndex(id))
        return;
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemLaunch == NULL || !favOwnerHasId(o, favArray[id].id))
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
        if (o == NULL || o->itemGetStartup == NULL || o->itemGetImage == NULL || !favOwnerHasId(o, favArray[i].id))
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
    // Prefer the SOURCE list's live flags so dynamic capabilities are forwarded -- e.g. a BDM
    // device backed by ATA only sets MODE_FLAG_COMPAT_DMA on itemList->flags after its scan, so
    // re-deriving from mode alone would hide the DMA compat option for ATA-backed favourites.
    item_list_t *o = favArray[id].owner;
    if (o != NULL)
        return o->flags;
    // Fallback by resolved mode if the owner pointer is somehow absent.
    int m = favArray[id].mode;
    if (m == APP_MODE)
        return MODE_FLAG_NO_COMPAT | MODE_FLAG_NO_UPDATE;
    if (m == HDD_MODE)
        return MODE_FLAG_COMPAT_DMA;
    return 0;
}

// VMC check proxy: itemCheckVMC is device-context (no id), so forward to the current FAV
// item's SOURCE device. Without this, the game-Options VMC menu would call a NULL callback.
static int favCheckVMC(item_list_t *itemList, char *name, int createSize)
{
    opl_io_module_t *mod = oplGetModule(FAV_MODE);
    if (mod == NULL || mod->menuItem.current == NULL)
        return -1;
    int id = mod->menuItem.current->item.id;
    if (!favValidIndex(id))
        return -1;
    item_list_t *o = favArray[id].owner;
    if (o == NULL || o->itemCheckVMC == NULL)
        return -1;
    return o->itemCheckVMC(o, name, createSize);
}

// Two modes "match" for favourite identity if equal, OR both in the BDM range
// (USB/iLink/MX4SIO/ATA slots are interchangeable -- a BDM favourite can move slots).
static int favModesMatch(int a, int b)
{
    int aBdm = (a >= BDM_MODE && a <= BDM_MODE_LAST);
    int bBdm = (b >= BDM_MODE && b <= BDM_MODE_LAST);
    if (aBdm && bBdm)
        return 1;
    return a == b;
}

// ---- public toggle / refresh API ----------------------------------------------

int addFavouriteItem(int mode, int id, int icon_id, int text_id, const char *text)
{
    if (text == NULL || text[0] == '\0')
        return 0;

    int count = 0;
    fav_raw_t *recs = favReadFile(&count); // may be NULL (empty / new file)

    // Already present (same mode + id + text) -> treat as success (the star stays set).
    // Use favModesMatch so a BDM favourite that moved slots (e.g. BDM_MODE -> BDM_MODE1) is
    // recognised as already-present, matching the BDM-lenient logic in removeFavouriteByIdAndText.
    for (int i = 0; i < count; i++) {
        if (favModesMatch(recs[i].mode, mode) && recs[i].id == id && strcmp(recs[i].text, text) == 0) {
            free(recs);
            return 1;
        }
    }

    int newCount = count + 1;
    if (newCount > FAV_MAX_ITEMS) {
        free(recs);
        return 0;
    }
    fav_raw_t *out = (fav_raw_t *)calloc(newCount, sizeof(fav_raw_t));
    if (out == NULL) {
        free(recs);
        return 0;
    }
    for (int i = 0; i < count; i++)
        out[i] = recs[i];
    out[count].mode = mode;
    out[count].id = id;
    out[count].icon_id = icon_id;
    out[count].text_id = text_id;
    snprintf(out[count].text, FAV_TEXT_MAX, "%s", text);

    int ok = favWriteFile(out, newCount);
    free(out);
    free(recs);
    return ok;
}

int removeFavouriteByIdAndText(int mode, int id, const char *text)
{
    int count = 0;
    fav_raw_t *recs = favReadFile(&count);
    if (recs == NULL)
        return 0;

    int survivors = 0;
    for (int i = 0; i < count; i++) {
        // Match on id + text + mode (BDM-lenient) so a same-titled favourite in a different
        // device mode is NOT collaterally deleted.
        if (!(recs[i].id == id && text != NULL && strcmp(recs[i].text, text) == 0 && favModesMatch(recs[i].mode, mode)))
            recs[survivors++] = recs[i]; // compact in place (single buffer)
    }
    int ok = favWriteFile(recs, survivors); // survivors may be 0 -> writes a header-only (empty) file
    free(recs);
    return ok;
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
    removeFavouriteByIdAndText(srcMode, srcId, txt);
}

void loadFavourites(void)
{
    // Mark the FAV list stale and schedule its single canonical rebuild. The clear + re-append
    // happen together inside the deferred updateMenuFromGameList (favNeedsUpdate consumes the
    // one-shot), so we must NOT clear here: an eager clear on every source refresh would blank
    // the tab (and reset its cursor) even when the favourites set did not change.
    favForceUpdate = 1;
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
    &favGetConfig, &favGetImage, &favCleanUp, &favShutdown, &favCheckVMC, &favGetIconId};
