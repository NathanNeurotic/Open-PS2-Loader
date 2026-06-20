/*
  Copyright 2024, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  VCD (PS1-via-POPSTARTER) scan + path resolution. See include/vcdsupport.h. POSIX directory IO
  only -- the newlib port rejects direct fileXio use (same rule as favsupport.c), and the stock
  game scan (supportbase.c) already uses opendir/readdir on device prefixes.
*/

#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>

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

int vcdResolvePopstarter(const char *devPrefix, char *out, int outSize)
{
    if (devPrefix == NULL || out == NULL || outSize <= 0)
        return 0;
    snprintf(out, outSize, "%s%s/POPSTARTER.ELF", devPrefix, POPS_FOLDER);
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
    snprintf(out, outSize, "%s%s/%s%s.ELF", devPrefix ? devPrefix : "", POPS_FOLDER, prefix ? prefix : "", name ? name : "");
}
