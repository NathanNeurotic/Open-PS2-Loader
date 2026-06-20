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

#include "include/opl.h"    // pulls <dirent.h> (opendir/readdir/DIR) + strcasecmp, like supportbase.c
#include "include/system.h" // POPS_FOLDER
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

int vcdScanDir(const char *devPrefix, vcd_entry_t **outList)
{
    if (outList == NULL)
        return 0;
    *outList = NULL;
    if (devPrefix == NULL)
        return 0;

    char dirPath[256];
    snprintf(dirPath, sizeof(dirPath), "%s%s", devPrefix, POPS_FOLDER); // "<prefix>POPS" (prefix ends in '/')

    DIR *dir = opendir(dirPath);
    if (dir == NULL)
        return 0; // no POPS folder on this device -> no VCDs

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
    return (mode >= BDM_MODE && mode <= BDM_MODE_LAST) || mode == MMCE_MODE || mode == ETH_MODE;
}

int vcdViewActive(int mode)
{
    return (mode >= 0 && mode < MODE_COUNT) ? vcdView[mode] : 0;
}

void vcdToggleView(int mode)
{
    if (mode < 0 || mode >= MODE_COUNT)
        return;
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
    int srcSize = lseek(sfd, 0, SEEK_END);
    lseek(sfd, 0, SEEK_SET);
    if (srcSize < 0) {
        close(sfd);
        return -1;
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
