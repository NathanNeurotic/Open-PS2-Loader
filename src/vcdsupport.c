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
    if (devPrefix == NULL || out == NULL || outSize <= 0)
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
