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
static const char *vcdBdmaSuffix[VCD_BDMA_MODE_COUNT] = {"fat32", "usbexfat", "mx4sio", "mmce"};
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
static void vcdWriteBdmaMarker(const char *mcDir, int mode)
{
    if (mode < 0 || mode >= VCD_BDMA_MODE_COUNT)
        return;
    char path[96];
    snprintf(path, sizeof(path), "%s/%s", mcDir, VCD_BDMA_MARKER);
    const char *tok = vcdBdmaSuffix[mode];
    vcdSafeWriteFile(path, tok, (int)strlen(tok));
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

// Candidate source device prefixes for a BDMA SOURCE family (each ends in '/'). USB and MX4SIO both
// live in the BDM massN namespace (OPL can't split them by path); MMCE has its own.
static int vcdBdmaSourcePrefixes(int source, const char *out[], int maxOut)
{
    static const char *mass[8] = {"mass0:/", "mass1:/", "mass2:/", "mass3:/",
                                  "mass4:/", "mass5:/", "mass6:/", "mass7:/"};
    static const char *mmce[2] = {"mmce0:/", "mmce1:/"};
    int n = 0;
    if (source == VCD_BDMA_SRC_MMCE) {
        for (int i = 0; i < 2 && n < maxOut; i++)
            out[n++] = mmce[i];
    } else { // USB or MX4SIO -> the mass namespace
        for (int i = 0; i < 8 && n < maxOut; i++)
            out[n++] = mass[i];
    }
    return n;
}

int vcdEquipBdma(int source, int mode)
{
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
        vcdWriteBdmaMarker(mcDir, mode);
        return 0;
    }

    // Find the source device whose POPS/ holds BOTH variant files for this mode.
    const char *cands[8];
    int nc = vcdBdmaSourcePrefixes(source, cands, 8);
    const char *suffix = vcdBdmaSuffix[mode];
    char src0[96], src1[96];
    int found = 0;
    for (int i = 0; i < nc; i++) {
        snprintf(src0, sizeof(src0), "%sPOPS/%s.%s", cands[i], vcdBdmaModule[0], suffix);
        snprintf(src1, sizeof(src1), "%sPOPS/%s.%s", cands[i], vcdBdmaModule[1], suffix);
        int f0 = open(src0, O_RDONLY);
        if (f0 < 0)
            continue;
        close(f0);
        int f1 = open(src1, O_RDONLY);
        if (f1 < 0)
            continue;
        close(f1);
        found = 1;
        break;
    }
    if (!found)
        return -4; // the chosen SOURCE has neither variant file in its POPS/

    // Copy both through the free-space-gated safe-copy. If usbd.irx fits but usbhdfsd.irx won't,
    // we've already replaced usbd.irx -- acceptable (re-equip fixes it) and the card is never
    // corrupted (each write is space-gated + truncation-safe).
    int r = vcdSafeCopyFile(src0, dst0);
    if (r != 0)
        return r; // -2 (no space) / -3 (IO)
    r = vcdSafeCopyFile(src1, dst1);
    if (r != 0)
        return r;

    vcdWriteBdmaMarker(mcDir, mode);
    return 0;
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
