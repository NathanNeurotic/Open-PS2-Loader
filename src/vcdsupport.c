/*
  Copyright 2024, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  VCD (PS1-via-POPSTARTER) scan + path resolution. See include/vcdsupport.h. POSIX directory IO
  only -- the newlib port rejects direct fileXio use (same rule as favsupport.c), and the stock
  game scan (supportbase.c) already uses opendir/readdir on device prefixes.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h> // mkdir (POSIX, used like util.c / OSDHistory.c)

#include "include/opl.h"         // pulls <dirent.h> (opendir/readdir/DIR) + strcasecmp, like supportbase.c
#include "include/system.h"      // POPS_FOLDER
#include "include/textures.h"    // texDiscoverLoad (VCD cover-art fallback)
#include "include/ioman.h"       // LOG (BDMA equip probe trace)
#include "include/bdmsupport.h"  // BDM_TYPE_* + bdmGetDeviceRootByType (BDMA source differentiation)
#include "include/mmcesupport.h" // mmceLoadModules (ensure mmceman for the MMCE BDMA source)
#include "include/vcdsupport.h"

// Extract the PS1 disc ID (SXXX_NNN.NN) from a VCD basename matching "SXXX_NNN.NN.Title"
// (name[4]=='_', name[8]=='.', name[11]=='.'); leave empty otherwise. Keys cover-art / per-game cfg.
static void vcdExtractGameId(const char *name, char *idOut, int idSize)
{
    idOut[0] = '\0';
    if ((int)strlen(name) >= 12 && name[4] == '_' && name[8] == '.' && name[11] == '.') {
        int n = (11 < idSize - 1) ? 11 : (idSize - 1); // "SXXX_NNN.NN" = 11 chars
        memcpy(idOut, name, n);
        idOut[n] = '\0';
    }
}

// Core scan: opendir `dirPath` and collect *.VCD basenames into a fresh vcd_entry_t list. POSIX dir
// IO only (newlib-port rule). Shared by vcdScanDir (POPS subfolder) and vcdScanDirRoot (path as-is).
static int vcdScanOpenDir(const char *dirPath, vcd_entry_t **outList)
{
    DIR *dir = opendir(dirPath);
    if (dir == NULL)
        return 0; // no such folder -> no VCDs

    vcd_entry_t *list = (vcd_entry_t *)calloc(VCD_MAX_ITEMS, sizeof(vcd_entry_t));
    if (list == NULL) {
        closedir(dir);
        return 0;
    }

    int count = 0;
    struct dirent *de;
    while (count < VCD_MAX_ITEMS && (de = readdir(dir)) != NULL) {
        int len = (int)strlen(de->d_name);
        if (len < 5 || strcasecmp(de->d_name + len - 4, ".VCD") != 0)
            continue;          // keep only "*.VCD" (case-insensitive)
        int baseLen = len - 4; // strip ".VCD"
        if (baseLen > VCD_NAME_MAX - 1)
            baseLen = VCD_NAME_MAX - 1;
        memcpy(list[count].name, de->d_name, baseLen);
        list[count].name[baseLen] = '\0';
        vcdExtractGameId(list[count].name, list[count].gameId, sizeof(list[count].gameId));
        count++;
    }
    closedir(dir);

    if (count == 0) {
        free(list);
        return 0;
    }
    *outList = list;
    return count;
}

int vcdScanDir(const char *devPrefix, vcd_entry_t **outList)
{
    if (outList == NULL)
        return 0;
    *outList = NULL;
    if (devPrefix == NULL)
        return 0;

    char dirPath[256];
    snprintf(dirPath, sizeof(dirPath), "%s%s", devPrefix, POPS_FOLDER); // "<prefix>POPS" (prefix ends in '/')

    return vcdScanOpenDir(dirPath, outList);
}

// Scan a directory path DIRECTLY (no POPS/ subfolder) for *.VCD -- used for the APA/PFS HDD, where
// each __.POPS* partition holds its .VCD at the mounted root (caller passes e.g. "pfs0:/").
int vcdScanDirRoot(const char *dirPath, vcd_entry_t **outList)
{
    if (outList == NULL)
        return 0;
    *outList = NULL;
    if (dirPath == NULL)
        return 0;

    return vcdScanOpenDir(dirPath, outList);
}

// POPStarter path separator for a device prefix: '\\' for SMB (ethPrefix ends in '\\'), else '/'.
// Auto-detected from the prefix's trailing char so one code path serves both mass/mmce and SMB.
static char vcdSep(const char *devPrefix)
{
    int n = (devPrefix != NULL) ? (int)strlen(devPrefix) : 0;
    return (n > 0 && devPrefix[n - 1] == '\\') ? '\\' : '/';
}

int vcdResolvePopstarter(const char *devPrefix, char *out, int outSize)
{
    if (out == NULL || outSize <= 0)
        return 0;

    // A custom POPSTARTER.ELF path from General Settings wins -- but ONLY if it actually exists;
    // otherwise we quietly fall back to the per-device <dev>/POPS/POPSTARTER.ELF.
    if (gPopstarterPath[0] != '\0') {
        int cfd = open(gPopstarterPath, O_RDONLY);
        if (cfd >= 0) {
            close(cfd);
            snprintf(out, outSize, "%s", gPopstarterPath);
            return 1;
        }
    }

    if (devPrefix == NULL)
        return 0;
    snprintf(out, outSize, "%s%s%cPOPSTARTER.ELF", devPrefix, POPS_FOLDER, vcdSep(devPrefix));
    int fd = open(out, O_RDONLY);
    if (fd < 0)
        return 0;
    close(fd);
    return 1;
}

void vcdBuildSelector(const char *devPrefix, const char *prefix, const char *name, char *out, int outSize)
{
    if (out == NULL || outSize <= 0)
        return;
    const char *dp = devPrefix ? devPrefix : "";
    snprintf(out, outSize, "%s%s%c%s%s.ELF", dp, POPS_FOLDER, vcdSep(dp), prefix ? prefix : "", name ? name : "");
}

// ---- per-device VCD view state ------------------------------------------------

static unsigned char vcdView[MODE_COUNT];  // 1 = this mode is showing its VCD list
static unsigned char vcdDirty[MODE_COUNT]; // 1 = view just toggled -> force one rescan

int vcdModeSupported(int mode)
{
    // FAV_MODE has its own L3 ISO<->VCD view too: the Favourites tab swaps between disc favourites and
    // PS1/.VCD favourites (favsupport filters its list by vcdViewActive(FAV_MODE)). Its vcdView slot is
    // independent of any device's, so toggling Favourites never disturbs a device page's view.
    return (mode >= BDM_MODE && mode <= BDM_MODE_LAST) || mode == MMCE_MODE || mode == ETH_MODE || mode == HDD_MODE || mode == FAV_MODE;
}

int vcdViewActive(int mode)
{
    if (mode < 0 || mode >= MODE_COUNT || !vcdModeSupported(mode))
        return 0;
    // The global default-view setting overrides the per-device L3 toggle when locked to one type.
    if (gDefaultGameView == GAME_VIEW_ISO)
        return 0; // locked to the ISO/disc list
    if (gDefaultGameView == GAME_VIEW_VCD)
        return 1;         // locked to the VCD (PS1) list
    return vcdView[mode]; // GAME_VIEW_BOTH: per-device L3 toggle (defaults to ISO)
}

void vcdToggleView(int mode)
{
    if (mode < 0 || mode >= MODE_COUNT)
        return;
    if (gDefaultGameView != GAME_VIEW_BOTH)
        return; // globally locked to one type -> the L3 toggle is disabled
    vcdView[mode] = vcdView[mode] ? 0 : 1;
    vcdDirty[mode] = 1;
}

int vcdConsumeDirty(int mode)
{
    if (mode < 0 || mode >= MODE_COUNT || !vcdDirty[mode])
        return 0;
    vcdDirty[mode] = 0;
    return 1;
}

// Mark every VCD-capable mode for one rescan -- call after the global default-view setting changes so
// each device page rebuilds its list (ISO <-> VCD) on its next refresh.
void vcdMarkAllDirty(void)
{
    for (int m = 0; m < MODE_COUNT; m++)
        if (vcdModeSupported(m))
            vcdDirty[m] = 1;
}

// 3-level cover/icon fallback for VCD (PS1) games, so one art file can serve OPL and POPSLoader:
//   (1) OPL ART keyed by the PS1 disc id  -> <dev>ART/<SXXX_NNN.NN>_<suffix>.png  (interoperable serial)
//   (2) OPL ART keyed by the VCD basename -> <dev>ART/<name>_<suffix>.png         (long-standing behaviour)
//   (3) POPSLoader layout next to the .VCD -> <dev><popsDir>/<name>.png            (no _suffix; POPSLoader's)
// Returns the first texDiscoverLoad hit (>= 0), else the last miss. popsDir == NULL skips step (3).
// `sep` is '/' for local/MMCE/HDD prefixes and '\\' for SMB (ethPrefix) -- mirror the caller's getImage.
int vcdLoadArt(const char *devPrefix, char sep, const char *artFolder, const char *value, const char *suffix, const char *popsDir, GSTEXTURE *tex)
{
    char path[256];
    char discId[VCD_ID_MAX];
    int r = -1;

    vcdExtractGameId(value, discId, sizeof(discId));
    if (discId[0] != '\0') {
        snprintf(path, sizeof(path), "%s%s%c%s_%s", devPrefix, artFolder, sep, discId, suffix);
        if ((r = texDiscoverLoad(tex, path, -1)) >= 0)
            return r;
    }
    snprintf(path, sizeof(path), "%s%s%c%s_%s", devPrefix, artFolder, sep, value, suffix);
    r = texDiscoverLoad(tex, path, -1);
    if (r >= 0 || popsDir == NULL)
        return r;
    snprintf(path, sizeof(path), "%s%s%c%s", devPrefix, popsDir, sep, value);
    return texDiscoverLoad(tex, path, -1);
}

int vcdFillGameList(const char *devPrefix, base_game_info_t **outGames)
{
    if (outGames == NULL)
        return 0;
    free(*outGames); // symmetric with sbReadList: free the old list before reallocating
    *outGames = NULL;

    vcd_entry_t *vcds = NULL;
    int n = vcdScanDir(devPrefix, &vcds);
    if (n <= 0)
        return 0;

    base_game_info_t *games = (base_game_info_t *)memalign(64, n * sizeof(base_game_info_t));
    if (games == NULL) {
        free(vcds);
        return 0;
    }
    memset(games, 0, n * sizeof(base_game_info_t));
    for (int i = 0; i < n; i++) {
        snprintf(games[i].name, sizeof(games[i].name), "%s", vcds[i].name);
        snprintf(games[i].startup, sizeof(games[i].startup), "%s", vcds[i].gameId); // "" -> no art lookup
        snprintf(games[i].extension, sizeof(games[i].extension), ".VCD");
        games[i].parts = 1;
        games[i].format = GAME_FORMAT_ISO; // harmless; the per-mode VCD flag gates the launch path
    }
    free(vcds);
    *outGames = games;
    return n;
}

// ---- safe memory-card copy (free-space gated) ---------------------------------------
// Equipping BDMA / SMB modules COPIES files onto mc?:/POPSTARTER/, and writing the small config
// markers (bdma_config.txt, IPCONFIG.DAT, SMBCONFIG.DAT) does the same. Filling a card to zero or
// leaving a half-written module there can wreck a user's POPSTARTER setup, so EVERY such write goes
// through these helpers: we refuse up front unless the destination card reports enough free space
// (plus a margin), and we delete any partially-written file on a short write. POSIX IO only.

#define VCD_MC_CLUSTER  1024        // PS2 memory-card cluster size; mcGetInfo "free" is in clusters
#define VCD_COPY_MARGIN (16 * 1024) // leave >=16 KiB head-room so we never pack the card to 0
#define VCD_COPY_CHUNK  (16 * 1024) // copy buffer (heap, not stack)

// Free bytes on the memory card backing `path` ("mc0:"/"mc1:"), or -1 if it isn't a usable PS2 MC.
static int vcdMcFreeBytes(const char *path)
{
    if (path == NULL || (path[0] != 'm' && path[0] != 'M') || (path[1] != 'c' && path[1] != 'C'))
        return -1;                       // not a memory-card path
    int port = (path[2] == '1') ? 1 : 0; // "mc1:" -> slot 1, anything else -> slot 0
    int type = 0, freeClusters = -1, format = 0, result = -1;
    mcGetInfo(port, 0, &type, &freeClusters, &format);
    mcSync(0, NULL, &result); // mcGetInfo is async; the vars are valid after the sync
    if (type != sceMcTypePS2 || format != MC_FORMATTED || freeClusters < 0)
        return -1; // no PS2 card / unformatted / query failed
    return freeClusters * VCD_MC_CLUSTER;
}

// Room for `needBytes` (+ margin) on `path`'s card? 1 = yes, 0 = no, -1 = not an MC / can't tell.
// Callers writing to an MC must treat 0 as "do NOT write"; -1 means the gate doesn't apply.
int vcdMcHasSpace(const char *path, int needBytes)
{
    int freeB = vcdMcFreeBytes(path);
    if (freeB < 0)
        return -1;
    return (freeB >= needBytes + VCD_COPY_MARGIN) ? 1 : 0;
}

// Copy srcPath -> dstPath, but only after confirming the destination card can hold it.
//   0  success      -1  source missing/unreadable
//  -2  MC too full (NOTHING written)   -3  write/IO error (partial dst removed)
int vcdSafeCopyFile(const char *srcPath, const char *dstPath)
{
    if (srcPath == NULL || dstPath == NULL)
        return -1;

    int sfd = open(srcPath, O_RDONLY);
    if (sfd < 0)
        return -1;

    // Probe source file size for the MC free-space pre-check. MMCE newlib does not support SEEK_END
    // (mirrors textures.c lines 402-403: it returns -1, causing every MMCE equip to abort here).
    // If SEEK_END fails, fall back to srcSize=0 -- the pre-check becomes conservative (always passes)
    // and the write-loop + unlink safety net still catches any actual out-of-space error.
    int srcSize = 0;
    {
        int sz = lseek(sfd, 0, SEEK_END);
        if (sz >= 0) {
            if (lseek(sfd, 0, SEEK_SET) < 0) {
                close(sfd);
                return -1;
            }
            srcSize = sz;
        }
        // SEEK_END failed (e.g. MMCE source): leave srcSize=0, no rewind needed (still at start).
    }

    // Free-space gate: only blocks when the destination IS a memory card and it won't fit.
    if (vcdMcHasSpace(dstPath, srcSize) == 0) {
        close(sfd);
        return -2;
    }

    char *buf = (char *)malloc(VCD_COPY_CHUNK);
    if (buf == NULL) {
        close(sfd);
        return -3;
    }
    int dfd = open(dstPath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (dfd < 0) {
        free(buf);
        close(sfd);
        return -3;
    }

    int rc = 0, r;
    while ((r = read(sfd, buf, VCD_COPY_CHUNK)) > 0) {
        int off = 0;
        while (off < r) {
            int w = write(dfd, buf + off, r - off);
            if (w <= 0) {
                rc = -3;
                break;
            }
            off += w;
        }
        if (rc != 0)
            break;
    }
    if (r < 0)
        rc = -3;

    close(dfd);
    close(sfd);
    free(buf);
    if (rc != 0)
        unlink(dstPath); // never leave a truncated module/config behind
    return rc;
}

// Write `len` bytes from `buf` to dstPath, gated by the same MC free-space check.
//   0 success   -2 MC too full (nothing written)   -3 write/IO error (partial dst removed)
int vcdSafeWriteFile(const char *dstPath, const void *buf, int len)
{
    if (dstPath == NULL || len < 0 || (buf == NULL && len > 0))
        return -3;
    if (vcdMcHasSpace(dstPath, len) == 0)
        return -2;

    int dfd = open(dstPath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (dfd < 0)
        return -3;
    const char *p = (const char *)buf;
    int off = 0, rc = 0;
    while (off < len) {
        int w = write(dfd, p + off, len - off);
        if (w <= 0) {
            rc = -3;
            break;
        }
        off += w;
    }
    close(dfd);
    if (rc != 0)
        unlink(dstPath);
    return rc;
}

// ---- BDMA (BDMAssault exFAT driver) equip -------------------------------------------
// POPStarter loads its block-device driver from mc?:/POPSTARTER/{usbd.irx,usbhdfsd.irx}. We let the
// user EQUIP one of three exFAT variants (or FAT32 = none) by copying THEIR OWN files from a source
// device's POPS/ folder -- RiptOPL embeds nothing. "BDMA MODE" picks the variant; "BDMA SOURCE"
// picks which device family to read the loose variant files from (named usbd.irx.<suffix>, the
// POPSLoader convention). The equip fires when either setting changes (opl.c), goes through the
// free-space-gated safe-copy, and records the equipped variant in mc?:/POPSTARTER/bdma_config.txt so
// the settings UI can reflect what's actually installed. (POPSLoader itself is a Lua loader that
// embeds its modules; there's no shared marker file to mirror, so we use the user's release-spec
// name bdma_config.txt with the variant suffix as its single-token contents.)

// MODE -> variant suffix on the loose source files (usbd.irx.<suffix>) AND the marker token.
static const char *vcdBdmaSuffix[VCD_BDMA_MODE_COUNT] = {"fat32", "usbexfat", "mx4sio", "mmce", "ata"};
// The two driver files POPStarter loads, equipped onto the MC WITHOUT the .<suffix>.
static const char *vcdBdmaModule[2] = {"usbd.irx", "usbhdfsd.irx"};

#define VCD_BDMA_MARKER "bdma_config.txt"

// Resolve the memory-card POPSTARTER folder (where the modules live). Prefer an existing
// mc?:/POPSTARTER; if neither card has one, default to mc0 and create it. Always returns 1.
static int vcdResolvePopstarterMc(char *out, int outSize)
{
    static const char *cards[2] = {"mc0:/POPSTARTER", "mc1:/POPSTARTER"};
    for (int i = 0; i < 2; i++) {
        DIR *d = opendir(cards[i]);
        if (d != NULL) {
            closedir(d);
            snprintf(out, outSize, "%s", cards[i]);
            return 1;
        }
    }
    snprintf(out, outSize, "%s", cards[0]);
    mkdir(out, 0777); // first-time setup: create mc0:/POPSTARTER
    return 1;
}

// Write the equipped-state marker mc?:/POPSTARTER/bdma_config.txt = the variant token.
// Returns 0 on success, or the vcdSafeWriteFile error code (-2 card full / -3 IO).
static int vcdWriteBdmaMarker(const char *mcDir, int mode)
{
    if (mode < 0 || mode >= VCD_BDMA_MODE_COUNT)
        return -1;
    char path[96];
    snprintf(path, sizeof(path), "%s/%s", mcDir, VCD_BDMA_MARKER);
    const char *tok = vcdBdmaSuffix[mode];
    return vcdSafeWriteFile(path, tok, (int)strlen(tok));
}

int vcdReadBdmaMode(void)
{
    char mcDir[64];
    vcdResolvePopstarterMc(mcDir, sizeof(mcDir));
    char path[96];
    snprintf(path, sizeof(path), "%s/%s", mcDir, VCD_BDMA_MARKER);
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return VCD_BDMA_FAT32; // no marker -> no exFAT modules -> FAT32 is the safe default
    char buf[32];
    int r = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (r <= 0)
        return VCD_BDMA_FAT32;
    buf[r] = '\0';
    while (r > 0 && (buf[r - 1] == '\n' || buf[r - 1] == '\r' || buf[r - 1] == ' ' || buf[r - 1] == '\t'))
        buf[--r] = '\0'; // trim trailing whitespace/newline
    for (int m = 0; m < VCD_BDMA_MODE_COUNT; m++) {
        if (strcmp(buf, vcdBdmaSuffix[m]) == 0)
            return m;
    }
    return VCD_BDMA_FAT32;
}

int vcdEquipBdma(int source, int mode, char *diag, int diagSize)
{
    if (diag != NULL && diagSize > 0)
        diag[0] = '\0';

    if (mode < 0 || mode >= VCD_BDMA_MODE_COUNT || source < 0 || source >= VCD_BDMA_SRC_COUNT)
        return -1;

    char mcDir[64];
    vcdResolvePopstarterMc(mcDir, sizeof(mcDir));

    char dst0[96], dst1[96];
    snprintf(dst0, sizeof(dst0), "%s/%s", mcDir, vcdBdmaModule[0]);
    snprintf(dst1, sizeof(dst1), "%s/%s", mcDir, vcdBdmaModule[1]);

    if (mode == VCD_BDMA_FAT32) {
        // FAT32 fallback: remove the exFAT modules so POPStarter uses its built-in driver.
        unlink(dst0);
        unlink(dst1);
        int mr = vcdWriteBdmaMarker(mcDir, mode);
        return (mr != 0) ? mr : 0;
    }

    // Resolve the SOURCE device(s) to read the variant files from. BDM sources are DIFFERENTIATED by
    // driver: find EVERY mounted device whose driver matches the chosen type (USB / MX4SIO / internal
    // exFAT HDD) and read from its massN: FILESYSTEM root -- the same path the device pages browse. OPL
    // never mounts a typed ata0:/usb0:/mx4sio0: filesystem (those are block-device identities used only
    // for launch binding), so the readable source path is always massN:/. Searching ALL matching slots,
    // not just the first, covers a source family with two same-type devices when the variant files sit
    // on the second one. MMCE has its own mmce0:/mmce1: slots.
    const char *cands[MAX_BDM_DEVICES];
    char bdmRoots[MAX_BDM_DEVICES][BDM_DEVICE_ROOT_MAX + 2];
    int nc = 0;
    if (source == VCD_BDMA_SRC_MMCE) {
        // Ensure mmceman is loaded even when MMCE games are off / Manual-not-started -- otherwise mmce0:/
        // mmce1:/ are dead and nothing can be read. Then offer only slots that actually have a card, so
        // the not-found diagnostic is honest ("no device" vs "device found, files missing").
        mmceLoadModules();
        DIR *m0 = opendir("mmce0:/");
        if (m0 != NULL) {
            closedir(m0);
            cands[nc++] = "mmce0:/";
        }
        DIR *m1 = opendir("mmce1:/");
        if (m1 != NULL) {
            closedir(m1);
            cands[nc++] = "mmce1:/";
        }
    } else {
        int wantType = (source == VCD_BDMA_SRC_MX4SIO) ? BDM_TYPE_SDC : (source == VCD_BDMA_SRC_HDD) ? BDM_TYPE_ATA :
                                                                                                       BDM_TYPE_USB;
        // The source's transport driver may not be loaded if its device family is OFF for games (you can
        // keep the BDMA module files on a device you never browse). Force-load it + wait for the device
        // to mount -- otherwise the source path is dead and nothing can be read from it.
        bdmEnsureSourceModules(wantType, 2000);
        int slots[MAX_BDM_DEVICES];
        int ns = bdmGetDeviceSlotsByType(wantType, slots, MAX_BDM_DEVICES);
        for (int j = 0; j < ns && nc < (int)(sizeof(cands) / sizeof(cands[0])); j++) {
            snprintf(bdmRoots[nc], sizeof(bdmRoots[nc]), "mass%d:/", slots[j]);
            cands[nc] = bdmRoots[nc];
            nc++;
        }
    }

    const char *suffix = vcdBdmaSuffix[mode];
    char src0[96], src1[96];
    int found = 0;
    for (int i = 0; i < nc; i++) {
        snprintf(src0, sizeof(src0), "%s" POPS_FOLDER "/%s.%s", cands[i], vcdBdmaModule[0], suffix);
        snprintf(src1, sizeof(src1), "%s" POPS_FOLDER "/%s.%s", cands[i], vcdBdmaModule[1], suffix);
        int f0 = open(src0, O_RDONLY);
        LOG("[BDMA] probe %s -> %d\n", src0, f0);
        if (f0 < 0)
            continue;
        close(f0);
        int f1 = open(src1, O_RDONLY);
        LOG("[BDMA] probe %s -> %d\n", src1, f1);
        if (f1 < 0)
            continue;
        close(f1);
        found = 1;
        break;
    }
    if (!found) {
        LOG("[BDMA] %s.%s + %s.%s not found; source device root: %s\n",
            vcdBdmaModule[0], suffix, vcdBdmaModule[1], suffix, nc ? cands[0] : "(no matching device)");
        if (diag != NULL && diagSize > 0) {
            if (nc == 0)
                snprintf(diag, diagSize, "No device matching the selected BDMA source is connected.");
            else
                snprintf(diag, diagSize, "Source device %s has no %s.%s + %s.%s in its POPS folder.",
                         cands[0], vcdBdmaModule[0], suffix, vcdBdmaModule[1], suffix);
        }
        return -4; // the matched SOURCE device had no variant files in its POPS/ (or none matched)
    }

    // Copy both through the free-space-gated safe-copy (each write is space-gated + truncation-safe, so
    // a failure never corrupts an individual file).
    int r = vcdSafeCopyFile(src0, dst0);
    if (r != 0)
        return r; // -2 (no space) / -3 (IO); dst0 not yet replaced
    r = vcdSafeCopyFile(src1, dst1);
    if (r != 0) {
        // First module is now the NEW variant but the second failed -> the card holds a mismatched,
        // half-equipped pair. Roll back to a clean FAT32/no-modules state (drop the lone new module +
        // write the FAT32 marker) so the marker readback (vcdReadBdmaMode) stays truthful and POPSTARTER
        // falls back to its built-in driver instead of loading a mismatched pair.
        unlink(dst0);
        vcdWriteBdmaMarker(mcDir, VCD_BDMA_FAT32);
        return r;
    }

    int mr = vcdWriteBdmaMarker(mcDir, mode);
    return (mr != 0) ? mr : 0;
}

// Auto-equip the device-matching BDMA driver on the VCD launch path (POPSLoader's ApplyBdmaMode parity).
// POPSTARTER does its OWN SifIopReset, then reloads its block-device drivers from the FIXED memory-card
// files mc?:/POPSTARTER/usbd.irx + usbhdfsd.irx -- RiptOPL's live mx4sio_bd/ata_bd modules die at that
// reset. For an exFAT game those two files MUST be the device-matching BDMAssault variant or POPSTARTER
// can't mount the drive and drops to OSDSYS (the reported MX4SIO failure). `source`/`mode` are the game
// device's BDMA family. Idempotent: skips the copy when the matching variant is already equipped. If the
// device has no exFAT variant (FAT32, or none provided) the equip fails -> fall back to FAT32 so POPSTARTER
// uses its built-in driver instead of a stale/mismatched exFAT pair. Best-effort -- never blocks the launch.
void vcdEnsureBdmaForLaunch(int source, int mode)
{
    char diag[160];

    if (!gBdmaApplyOnLaunch)
        return; // user opted to manage the BDMA driver manually (General Settings -> BDMA Source/Mode)
    if (mode <= VCD_BDMA_FAT32 || mode >= VCD_BDMA_MODE_COUNT)
        return; // FAT32 / invalid -> POPSTARTER's built-in driver, nothing to equip
    if (vcdReadBdmaMode() == mode)
        return; // the matching variant is already on the card

    if (vcdEquipBdma(source, mode, diag, sizeof(diag)) != 0) {
        if (vcdReadBdmaMode() != VCD_BDMA_FAT32)
            vcdEquipBdma(source, VCD_BDMA_FAT32, diag, sizeof(diag)); // no variant -> clean FAT32 state
    }
}

// ---- SMB requirements guard ---------------------------------------------------------
// Launching a VCD over SMB needs POPSTARTER's network IRX in mc?:/POPSTARTER/. We don't install
// these from the ELF (they ship in the release POPSTARTER/ folder for the user to copy), so before
// an SMB/ETH VCD launch we confirm they're present and soft-refuse otherwise.
static const char *vcdSmbModule[4] = {"smbman.irx", "ps2ip.irx", "ps2smap.irx", "ps2dev9.irx"};

int vcdSmbModulesPresent(void)
{
    static const char *cards[2] = {"mc0:/POPSTARTER", "mc1:/POPSTARTER"};
    for (int c = 0; c < 2; c++) {
        int all = 1;
        for (int i = 0; i < 4; i++) {
            char path[96];
            snprintf(path, sizeof(path), "%s/%s", cards[c], vcdSmbModule[i]);
            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                all = 0;
                break;
            }
            close(fd);
        }
        if (all)
            return 1; // this card has the complete SMB stack
    }
    return 0;
}

int vcdWritePopstarterNet(const char *ipconfig, const char *smbconfig)
{
    char mcDir[64];
    vcdResolvePopstarterMc(mcDir, sizeof(mcDir)); // creates mc0:/POPSTARTER if neither card has it
    char path[96];
    int r1 = 0, r2 = 0;
    if (ipconfig != NULL) {
        snprintf(path, sizeof(path), "%s/IPCONFIG.DAT", mcDir);
        r1 = vcdSafeWriteFile(path, ipconfig, (int)strlen(ipconfig));
    }
    if (smbconfig != NULL) {
        snprintf(path, sizeof(path), "%s/SMBCONFIG.DAT", mcDir);
        r2 = vcdSafeWriteFile(path, smbconfig, (int)strlen(smbconfig));
    }
    return (r1 != 0) ? r1 : r2; // surface the first failure (-2 card full / -3 IO)
}
