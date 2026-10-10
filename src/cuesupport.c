/*
  Copyright 2026, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  CUE (PS1-via-Ember) scan, path resolution and argument validation, plus the union that makes one
  PS1 list out of both cores' libraries. See include/cuesupport.h for the measured Ember contract
  this implements, and docs/EMBER-INTEGRATION-PLAN.md for its derivation.

  POSIX IO only -- the newlib port rejects direct fileXio use here, same rule as vcdsupport.c.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>  // errno/ENOENT in the absent-vs-contended split, mirroring vcdScanOpenDir
#include <malloc.h> // memalign -- the published list matches sbReadList's alignment

#include "include/opl.h"        // pulls <dirent.h> (opendir/readdir/DIR) + strcasecmp, like vcdsupport.c
#include "include/ioman.h"      // LOG
#include "include/textures.h"   // texDiscoverLoad + ERR_BAD_FILE (folder cover fallback)
#include "include/vcdsupport.h" // vcdFillGameList + vcdSortKey -- the POPSTARTER half of the union
#include "include/cuesupport.h"
#include "include/retrogem.h"

// Path separator for a device prefix: '\\' for SMB (its prefix ends in a backslash), else '/'.
// Auto-detected from the trailing character so one code path serves mass/mmce/pfs and SMB alike.
// Same rule as vcdsupport.c's vcdSep(); kept local rather than shared so neither file's separator
// behaviour can be changed from under the other.
static char cueSep(const char *devPrefix)
{
    int n = (devPrefix != NULL) ? (int)strlen(devPrefix) : 0;
    return (n > 0 && devPrefix[n - 1] == '\\') ? '\\' : '/';
}

const char *cueEmberFolder(void)
{
    // A configurable folder name can arrive later as a setting. Resolving it through this accessor
    // from the start keeps that change to one line and keeps every caller honest about the fact
    // that the folder NAME is not part of Ember's contract -- the ember.elf's DIRECTORY is.
    return EMBER_FOLDER_DEFAULT;
}

// Shared body for the two file probes: compose "<devPrefix><folder><sep><file>" and open() it.
static int cueResolveEmberFile(const char *devPrefix, const char *fileName, char *out, int outSize)
{
    int fd;

    if (out == NULL || outSize <= 0 || devPrefix == NULL || fileName == NULL)
        return 0;

    snprintf(out, outSize, "%s%s%c%s", devPrefix, cueEmberFolder(), cueSep(devPrefix), fileName);

    fd = open(out, O_RDONLY);
    if (fd < 0)
        return 0;
    close(fd);
    return 1;
}

int cueResolveEmber(const char *devPrefix, char *out, int outSize)
{
    return cueResolveEmberFile(devPrefix, EMBER_ELF_NAME, out, outSize);
}

int cueResolveEmberBios(const char *devPrefix, char *out, int outSize)
{
    return cueResolveEmberFile(devPrefix, EMBER_BIOS_NAME, out, outSize);
}

void cueBuildGamesDir(const char *devPrefix, char *out, int outSize)
{
    if (out == NULL || outSize <= 0)
        return;
    if (devPrefix == NULL) {
        out[0] = '\0';
        return;
    }

    snprintf(out, outSize, "%s%s%c%s", devPrefix, cueEmberFolder(), cueSep(devPrefix), EMBER_GAMES_FOLDER);
}

int cueNameLaunchable(const char *name)
{
    if (name == NULL || name[0] == '\0')
        return 0;

    // Ember refuses any argument STARTING with ".." -- it compares buf[0] and buf[1] and never looks
    // further, so "..", "../x" and "..foo" are all refused. Match that, not the tidier "== ..".
    if (name[0] == '.' && name[1] == '.')
        return 0;

    // Scanner artefact: the current-directory entry is never a game.
    if (!strcmp(name, "."))
        return 0;

    // Ember's char scan refuses '/', ':' and '\\' ANYWHERE in the argument. On FAT/exFAT these
    // cannot appear in a directory entry, so in practice this fires only on a hand-typed argument
    // -- but it is the difference between a clear message and Ember dropping to the PS1 BIOS shell.
    if (strpbrk(name, "/:\\") != NULL)
        return 0;

    // Longer than Ember's own buffers can carry (see CUE_NAME_LAUNCH_MAX).
    if ((int)strlen(name) > CUE_NAME_LAUNCH_MAX)
        return 0;

    return 1;
}

// The extensions Ember's io_find_disc accepts, in ITS priority order (.cue beats .exe beats .bin).
// We only test presence, so the order is documentation rather than logic -- but it is the reason a
// folder holding just a .bin is still a valid game. Case-insensitive, as io_find_disc's own
// strcasecmp is.
static const char *const cueDiscExts[] = {".cue", ".exe", ".bin"};

// 1 when d_name (length len) carries one of Ember's launchable image extensions.
static int cueNameIsDiscImage(const char *name, int len)
{
    unsigned int i;

    if (len < 5)
        return 0; // shortest possible match is "x.cue"
    for (i = 0; i < sizeof(cueDiscExts) / sizeof(cueDiscExts[0]); i++) {
        if (strcasecmp(name + len - 4, cueDiscExts[i]) == 0)
            return 1;
    }
    return 0;
}

// Is this directory entry a game folder? Settled by opening it, never by d_type: d_type is not
// dependable across this project's drivers (the MMCE theme scan learned that the hard way --
// mmceman on some clones reports a d_type that does not describe the entry), and a driver that
// mislabels a FILE as DT_DIR would put a stray file in the PS1 list with an X button that cannot
// work. The probe costs one opendir per entry, bounded by the number of folders.
//
// And being a folder is not enough. An Ember game is a folder holding a *.cue / *.exe / *.bin at
// its TOP level -- io_find_disc does not recurse -- so a folder without one is a row whose X button
// cannot work: an empty folder, or the group-VMC folders game installers drop into EMBER/games/
// (reported by CosmicScale, October 2026). The image test rides the same opendir the dir probe
// already pays for and stops at the first match, so the scan costs no extra directory opens.
static int cueEntryIsGame(const char *devPrefix, const char *gamesDir, const struct dirent *de)
{
    char probe[320];
    struct dirent *sub;
    DIR *d;
    int found = 0;

    // Separator comes from the DEVICE, not a hardcoded slash. cueBuildGamesDir already builds
    // gamesDir with cueSep(), so a prefix ending in a backslash would otherwise be probed as
    // "smb0:\\EMBER\\games/NAME" -- mixed, and rejected by any handler that cares. Latent today
    // (no backslash device lists Ember yet) and load-bearing the moment one does.
    snprintf(probe, sizeof(probe), "%s%c%s", gamesDir, cueSep(devPrefix), de->d_name);
    d = opendir(probe);
    if (d == NULL)
        return 0;

    while (!found && (sub = readdir(d)) != NULL)
        found = cueNameIsDiscImage(sub->d_name, (int)strlen(sub->d_name));
    closedir(d);

    if (!found)
        LOG("[CUE] skip (folder holds no .cue/.exe/.bin): %s\n", de->d_name);
    return found;
}

int cueScanDir(const char *devPrefix, cue_entry_t **outList)
{
    char gamesDir[288];
    cue_entry_t *list = NULL;
    struct dirent *de;
    DIR *dir;
    int count = 0;
    int capacity = 0;

    if (outList == NULL)
        return 0;
    *outList = NULL;
    if (devPrefix == NULL)
        return 0;

    // NO EMBER CORE, NO EMBER LIBRARY -- and settle that with an open(), not with opendir's errno.
    //
    // The absent-vs-contended split below reads errno to tell "this folder isn't here" (fine, 0 rows)
    // from "this device wouldn't answer" (a failure the caller must not mistake for emptiness). That
    // works only on drivers that actually report ENOENT, and this very file documents one that does
    // not: mmceman collapses every failure, including the card's own not-found reply, into a bare -1.
    // There was never any reason to assume other block drivers are better behaved.
    //
    // The cost of getting it wrong is severe and was reported from hardware (FifthFox, iLink): a
    // device with a POPS library and NO EMBER folder returned -1 from this scan, ps1FillGameList
    // treated that as "device unreadable", and the ENTIRE PS1 list -- including the POPSTARTER
    // titles that had scanned perfectly -- stayed empty. USB and APA were fine because their driver
    // does report ENOENT.
    //
    // A plain open() of ember.elf has none of that ambiguity, so the core decides how a games
    // directory that will not open is read. With the core present, the errno split below applies.
    // Without it, an unopenable games directory is ALWAYS "nothing here" (0), never -1, whatever
    // errno the driver reports -- the FifthFox guarantee above, on every driver.
    //
    // A missing core no longer hides a games directory that DOES open (Aislinn, October 2026). It
    // used to return 0 straight away, so a missing or misnamed ember.elf made every Ember game
    // vanish with no message anywhere. Now the folders still list, and launching one says
    // "Missing ember.elf" and names the path it looked for -- the one place it can be explained.
    // gamesDir is scratch for the probe here -- cueResolveEmber writes the ELF path into it and we
    // discard that, then rebuild it as the games directory below. One buffer, not two, on a stack
    // this platform keeps small.
    int coreReadable = cueResolveEmber(devPrefix, gamesDir, sizeof(gamesDir));
    if (!coreReadable)
        LOG("[CUE] no readable ember.elf at '%s' -- listing games anyway, launch will say so\n", gamesDir);

    cueBuildGamesDir(devPrefix, gamesDir, sizeof(gamesDir));
    if (gamesDir[0] == '\0')
        return 0;

    errno = 0; // clear BEFORE opendir so the NULL branch reads THIS call's errno, not a stale one
    dir = opendir(gamesDir);
    if (dir == NULL) {
        // Absent-vs-contended split, identical in spirit to vcdScanOpenDir. A device with a POPS
        // folder and no EMBER folder is the ordinary case and MUST report 0 ("readable, nothing
        // here"), not a failure -- ps1FillGameList treats a failure from either half as a reason to
        // keep the whole last-good list, so getting this wrong would freeze the PS1 page of every
        // device that only uses one core. Without a core there is no library to preserve.
        if (!coreReadable || errno == ENOENT)
            return 0;
        // Anything else: the directory could not be READ (bus contended, device mid-detach). Signal
        // failure so the caller preserves its last-good list rather than blanking the page.
        // MMCE caveat, same as the VCD scan: mmceman's dopen collapses every failure into a bare -1
        // (EE sees EPERM, not ENOENT) unless the paired mmceman patch is in the build, so on mmceN:
        // an absent EMBER folder lands here. That costs a preserved list, never a wrong one.
        LOG("[CUE] cannot read '%s' (errno %d)\n", gamesDir, errno);
        return -1;
    }

    // Do not reserve CUE_MAX_ITEMS * 192 bytes (384 KiB) for every scan, including
    // a one-game USB stick. On a memory-constrained EE build that allocation can
    // fail and silently leave a never-scanned PS1 page empty. Grow geometrically
    // instead, retaining the same 2,048-game ceiling and last-good-list semantics.
    while (count < CUE_MAX_ITEMS && (de = readdir(dir)) != NULL) {
        if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, ".."))
            continue;

        // Refuse here what Ember would refuse at launch, so the list never offers a row whose X
        // button cannot work. A name with a separator cannot occur on FAT/exFAT; an over-long one
        // is a user mistake worth a log line rather than a silent dead row.
        if (!cueNameLaunchable(de->d_name)) {
            LOG("[CUE] skip (unlaunchable name): %s\n", de->d_name);
            continue;
        }
        // The row store caps names at ISO_GAME_NAME_MAX; a longer one would be truncated and then
        // resolve to a folder that does not exist.
        if ((int)strlen(de->d_name) > ISO_GAME_NAME_MAX) {
            LOG("[CUE] skip (name > %d chars): %s\n", ISO_GAME_NAME_MAX, de->d_name);
            continue;
        }
        if (!cueEntryIsGame(devPrefix, gamesDir, de))
            continue; // loose files, and folders holding nothing Ember can mount, are not games

        if (count == capacity) {
            int nextCapacity = capacity ? capacity * 2 : 8;
            if (nextCapacity > CUE_MAX_ITEMS)
                nextCapacity = CUE_MAX_ITEMS;
            cue_entry_t *grown = (cue_entry_t *)realloc(list, (size_t)nextCapacity * sizeof(cue_entry_t));
            if (grown == NULL) {
                LOG("[CUE] out of memory growing list to %d entries for '%s'\n", nextCapacity, gamesDir);
                free(list);
                closedir(dir);
                return -1; // OOM: preserve the caller's current PS1 list
            }
            list = grown;
            capacity = nextCapacity;
        }
        snprintf(list[count].name, sizeof(list[count].name), "%s", de->d_name);
        count++;
    }
    closedir(dir);
    LOG("[CUE] scanned '%s': found %d entries\n", gamesDir, count);

    if (count == 0) {
        free(list);
        return 0;
    }

    *outList = list;
    return count;
}

typedef struct
{
    const char *key;
    const char *value;
} cue_setting_t;

#define CUE_SETTINGS_MAX 8191

static int cueLineSetsKey(const char *line, int lineLen, const char *key)
{
    int i = 0;
    int keyLen;

    if (line == NULL || key == NULL || lineLen <= 0)
        return 0;

    while (i < lineLen && (line[i] == ' ' || line[i] == '\t'))
        i++;
    if (i >= lineLen || line[i] == '#' || line[i] == ';')
        return 0;

    keyLen = (int)strlen(key);
    if (keyLen <= 0 || i + keyLen > lineLen || strncasecmp(&line[i], key, keyLen) != 0)
        return 0;

    i += keyLen;
    while (i < lineLen && (line[i] == ' ' || line[i] == '\t'))
        i++;

    return i < lineLen && line[i] == ':';
}

int cueRewriteSettings(const char *before, int len, const cue_setting_t *want, int wantCount, char *after, int afterSize)
{
    int out = 0;
    int lineStart;
    int j;

    if (before == NULL || after == NULL || len < 0 || afterSize < 0 || wantCount < 0)
        return -1;
    if (wantCount > 0 && want == NULL)
        return -1;

    if (wantCount == 0) {
        if (len > afterSize)
            return -1;
        if (len > 0)
            memcpy(after, before, len);
        return len;
    }

    lineStart = 0;
    while (lineStart < len) {
        int lineEnd = lineStart;
        int lineLen;
        int managed = 0;

        while (lineEnd < len && before[lineEnd] != '\n')
            lineEnd++;

        lineLen = lineEnd - lineStart;
        if (lineLen > 0 && before[lineStart + lineLen - 1] == '\r')
            lineLen--;

        for (j = 0; j < wantCount; j++) {
            if (cueLineSetsKey(&before[lineStart], lineLen, want[j].key)) {
                managed = 1;
                break;
            }
        }

        if (!managed) {
            if (out + lineLen + 1 > afterSize)
                return -1;
            if (lineLen > 0) {
                memcpy(&after[out], &before[lineStart], lineLen);
                out += lineLen;
            }
            after[out++] = '\n';
        }

        lineStart = (lineEnd < len) ? lineEnd + 1 : len;
    }

    for (j = 0; j < wantCount; j++) {
        int keyLen;
        int valueLen;

        if (want[j].value == NULL)
            continue;

        keyLen = (int)strlen(want[j].key);
        valueLen = (int)strlen(want[j].value);
        if (out + keyLen + 1 + valueLen + 1 > afterSize)
            return -1;

        memcpy(&after[out], want[j].key, keyLen);
        out += keyLen;
        after[out++] = ':';
        memcpy(&after[out], want[j].value, valueLen);
        out += valueLen;
        after[out++] = '\n';
    }

    return out;
}

static void cueWantSetting(cue_setting_t *list, int *count, const char *key, int setting, const char *const *values, int valueCount)
{
    if (list == NULL || count == NULL || key == NULL || values == NULL)
        return;
    if (setting < 0 || setting >= valueCount)
        return;

    list[*count].key = key;
    list[*count].value = (setting == 0) ? NULL : values[setting];
    (*count)++;
}

static int cueSettingsHaveValue(const cue_setting_t *want, int wantCount)
{
    int i;

    for (i = 0; i < wantCount; i++) {
        if (want[i].value != NULL)
            return 1;
    }
    return 0;
}

static int cueWriteAll(int fd, const char *data, int len)
{
    int done = 0;

    while (done < len) {
        int wrote = write(fd, &data[done], len - done);
        if (wrote <= 0)
            return 0;
        done += wrote;
    }
    return 1;
}

static int cueRewriteSettingsFile(const char *path, const cue_setting_t *want, int wantCount)
{
    char *before;
    char *after;
    int fd;
    int len = 0;
    int out;
    int existed = 0;

    if (path == NULL || want == NULL || wantCount <= 0)
        return 0;

    before = (char *)malloc(CUE_SETTINGS_MAX + 1);
    after = (char *)malloc(CUE_SETTINGS_MAX + 1);
    if (before == NULL || after == NULL) {
        free(before);
        free(after);
        LOG("[CUE] no memory to update %s -- left untouched\n", path);
        return 0;
    }

    fd = open(path, O_RDONLY);
    if (fd >= 0) {
        existed = 1;
        len = read(fd, before, CUE_SETTINGS_MAX + 1);
        close(fd);
        if (len < 0) {
            LOG("[CUE] cannot read %s -- left untouched\n", path);
            free(before);
            free(after);
            return 0;
        }
        if (len > CUE_SETTINGS_MAX) {
            LOG("[CUE] %s is larger than Ember's settings buffer -- left untouched\n", path);
            free(before);
            free(after);
            return 0;
        }
    } else if (!cueSettingsHaveValue(want, wantCount)) {
        free(before);
        free(after);
        return 1;
    }

    out = cueRewriteSettings(before, len, want, wantCount, after, CUE_SETTINGS_MAX);
    if (out < 0) {
        LOG("[CUE] rewritten settings would not fit in %s -- left untouched\n", path);
        free(before);
        free(after);
        return 0;
    }

    if (out == len && (out == 0 || memcmp(after, before, out) == 0)) {
        free(before);
        free(after);
        return 1;
    }

    if (out == 0) {
        int removed = 1;
        if (existed && len > 0) {
            if (unlink(path) == 0)
                LOG("[CUE] nothing left to keep in %s -- removed\n", path);
            else {
                LOG("[CUE] cannot remove %s -- previous settings remain\n", path);
                removed = 0;
            }
        }
        free(before);
        free(after);
        return removed;
    }

    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        LOG("[CUE] cannot write %s -- previous Ember settings remain\n", path);
        free(before);
        free(after);
        return 0;
    }

    if (!cueWriteAll(fd, after, out)) {
        close(fd);
        if (existed) {
            fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
            if (fd >= 0) {
                int restored = (len == 0) || cueWriteAll(fd, before, len);
                close(fd);
                LOG("[CUE] write failed on %s -- original %s\n", path,
                    restored ? "restored" : "COULD NOT be restored");
            } else {
                LOG("[CUE] write failed on %s -- original COULD NOT be restored\n", path);
            }
        } else {
            unlink(path);
            LOG("[CUE] write failed on new %s -- partial file removed\n", path);
        }
        free(before);
        free(after);
        return 0;
    }

    out = close(fd);
    free(before);
    free(after);
    if (out < 0)
        LOG("[CUE] cannot close %s -- Ember settings save unconfirmed\n", path);
    return out >= 0;
}

int cueSaveGameSettings(const char *devPrefix, const char *name, config_set_t *configSet)
{
    static const char *const timingValues[] = {NULL, "auto", "ntsc", "pal"};
    static const char *const ditherValues[] = {NULL, "on", "off"};
    static const char *const shadingValues[] = {NULL, "15", "24"};
    static const char *const controllerValues[] = {NULL, "auto", "analog", "d2a"};
    cue_setting_t game[4];
    int nGame = 0;
    int value, n;
    char path[768];
    char sep;

    if (devPrefix == NULL || name == NULL || name[0] == '\0' ||
        !cueNameLaunchable(name) || configSet == NULL)
        return 0;

    if (configGetInt(configSet, CONFIG_ITEM_EMBER_TIMING, &value))
        cueWantSetting(game, &nGame, "timing", value, timingValues, EMBER_TIMING_COUNT);
    if (configGetInt(configSet, CONFIG_ITEM_EMBER_DITHER, &value))
        cueWantSetting(game, &nGame, "dither", value, ditherValues, EMBER_DITHER_COUNT);
    if (configGetInt(configSet, CONFIG_ITEM_EMBER_SHADING, &value))
        cueWantSetting(game, &nGame, "shading", value, shadingValues, EMBER_SHADING_COUNT);
    if (configGetInt(configSet, CONFIG_ITEM_EMBER_CONTROLLER, &value))
        cueWantSetting(game, &nGame, "controller", value, controllerValues, EMBER_CONTROLLER_COUNT);
    if (nGame == 0)
        return 1;

    sep = cueSep(devPrefix);
    n = snprintf(path, sizeof(path), "%s%s%c%s%c%s%c%s", devPrefix, cueEmberFolder(), sep,
                 EMBER_GAMES_FOLDER, sep, name, sep, EMBER_SETTINGS_NAME);
    if (n <= 0 || n >= (int)sizeof(path)) {
        LOG("[CUE] Ember game settings path is too long -- per-game settings left untouched\n");
        return 0;
    }
    return cueRewriteSettingsFile(path, game, nGame);
}

void cueApplySettings(const char *devPrefix, const char *name, config_set_t *configSet)
{
    static const char *const displayValues[] = {NULL, "240", "480", "480p"};
    static const char *const timingValues[] = {NULL, "auto", "ntsc", "pal"};
    static const char *const ditherValues[] = {NULL, "on", "off"};
    static const char *const shadingValues[] = {NULL, "15", "24"};
    static const char *const controllerValues[] = {NULL, "auto", "analog", "d2a"};
    cue_setting_t global[5];
    int nGlobal = 0;
    int n;
    char path[768];

    if (devPrefix == NULL)
        return;

    cueWantSetting(global, &nGlobal, "display", gEmberDisplay, displayValues, EMBER_DISPLAY_COUNT);
    cueWantSetting(global, &nGlobal, "timing", gEmberTiming, timingValues, EMBER_TIMING_COUNT);
    cueWantSetting(global, &nGlobal, "dither", gEmberDither, ditherValues, EMBER_DITHER_COUNT);
    cueWantSetting(global, &nGlobal, "shading", gEmberShading, shadingValues, EMBER_SHADING_COUNT);
    cueWantSetting(global, &nGlobal, "controller", gEmberController, controllerValues, EMBER_CONTROLLER_COUNT);

    if (nGlobal > 0) {
        n = snprintf(path, sizeof(path), "%s%s%c%s", devPrefix, cueEmberFolder(), cueSep(devPrefix), EMBER_SETTINGS_NAME);
        if (n > 0 && n < (int)sizeof(path))
            cueRewriteSettingsFile(path, global, nGlobal);
        else
            LOG("[CUE] Ember settings path is too long -- global settings left untouched\n");
    }
    if (configSet != NULL && name != NULL && name[0] != '\0' && cueNameLaunchable(name))
        cueSaveGameSettings(devPrefix, name, configSet);
}

int cueResolveGameImage(const char *devPrefix, const char *name, char *out, int outSize)
{
    char gamesDir[288];
    char gameDir[320];
    struct dirent *de;
    DIR *dir;
    int best = (int)(sizeof(cueDiscExts) / sizeof(cueDiscExts[0]));
    int found = 0;

    if (out == NULL || outSize <= 0)
        return 0;
    out[0] = '\0';
    if (devPrefix == NULL || name == NULL || name[0] == '\0')
        return 0;

    cueBuildGamesDir(devPrefix, gamesDir, sizeof(gamesDir));
    if (gamesDir[0] == '\0')
        return 0;
    snprintf(gameDir, sizeof(gameDir), "%s%c%s", gamesDir, cueSep(devPrefix), name);

    dir = opendir(gameDir);
    if (dir == NULL) {
        LOG("[CUE] cannot probe '%s' while resolving Ember disc image\n", gameDir);
        return -1;
    }

    while ((de = readdir(dir)) != NULL) {
        int len = (int)strlen(de->d_name);
        unsigned int i;

        if (len < 5)
            continue;
        for (i = 0; i < sizeof(cueDiscExts) / sizeof(cueDiscExts[0]); i++) {
            if (strcasecmp(de->d_name + len - 4, cueDiscExts[i]) == 0 && (int)i < best) {
                int n = snprintf(out, outSize, "%s%c%s", gameDir, cueSep(devPrefix), de->d_name);
                if (n > 0 && n < outSize) {
                    best = (int)i; // Ember priority: .cue, then .exe, then .bin.
                    found = 1;
                }
                break;
            }
        }
    }
    closedir(dir);

    return found;
}

int cueGameHasImage(const char *devPrefix, const char *name)
{
    char imagePath[640];
    int result = cueResolveGameImage(devPrefix, name, imagePath, sizeof(imagePath));

    if (result < 0) {
        // Never let a failed probe block a launch. Ember may still be able to read the folder.
        return 1;
    }
    if (!result)
        LOG("[CUE] game folder holds no .cue/.bin/.exe\n");
    return result;
}

void cuePrepareRetroGemBarcode(const char *devPrefix, const char *name)
{
    char imagePath[640];
    char gameID[RETROGEM_GAMEID_MAX];

    if (!gPopstarterRetroGemGameID || devPrefix == NULL || name == NULL || name[0] == '\0')
        return;

    // Best-effort metadata only. A transient read failure must never turn GameID into a launch gate.
    if (cueResolveGameImage(devPrefix, name, imagePath, sizeof(imagePath)) != 1)
        return;

    if (retrogemGetPs1ImageGameID(imagePath, gameID, sizeof(gameID)) && gameID[0] != '\0')
        displayRetroGemGameID(gameID, 2);
}


int cueRenameGame(const char *devPrefix, const char *oldName, const char *newName)
{
    char gamesDir[288];
    char oldPath[320];
    char newPath[320];
    DIR *probe;

    // The NEW name has to satisfy Ember's argument rules, or the rename would succeed on disk and
    // leave behind a row that can never be launched.
    if (devPrefix == NULL || oldName == NULL || newName == NULL)
        return -1;
    if (!cueNameLaunchable(oldName) || !cueNameLaunchable(newName))
        return -1;
    if (!strcmp(oldName, newName))
        return 0;

    cueBuildGamesDir(devPrefix, gamesDir, sizeof(gamesDir));
    if (gamesDir[0] == '\0')
        return -1;
    if (snprintf(oldPath, sizeof(oldPath), "%s%c%s", gamesDir, cueSep(devPrefix), oldName) >= (int)sizeof(oldPath))
        return -1;
    if (snprintf(newPath, sizeof(newPath), "%s%c%s", gamesDir, cueSep(devPrefix), newName) >= (int)sizeof(newPath))
        return -1;

    // Refuse to clobber an existing folder. rename() over a non-empty directory is not portable
    // across the filesystems here, and silently merging two libraries would be worse than refusing.
    probe = opendir(newPath);
    if (probe != NULL) {
        closedir(probe);
        LOG("[CUE] rename refused, target exists: %s\n", newPath);
        return -1;
    }

    if (rename(oldPath, newPath) != 0) {
        LOG("[CUE] rename failed: %s -> %s (%d)\n", oldPath, newPath, errno);
        return -1;
    }
    return 0;
}

int cueIsCueEntry(const base_game_info_t *game)
{
    return (game != NULL && strcasecmp(game->extension, CUE_ROW_EXTENSION) == 0);
}

int cueRowIsCueByName(const base_game_info_t *games, int count, const char *name)
{
    int i;

    if (games == NULL || name == NULL)
        return -1;

    for (i = 0; i < count; i++) {
        if (strcmp(games[i].name, name) == 0)
            return cueIsCueEntry(&games[i]) ? 1 : 0;
    }
    return -1;
}

// Merged-list comparator. Sorts by the same visible key the VCD-only scan always used, so turning
// on Ember cannot reorder anyone's existing PS1 list. The extension tie-break is not cosmetic: two
// rows CAN share a display name (the same game held for both cores is the expected case), and
// without a deterministic tie-break qsort would be free to swap them between rescans, making rows
// appear to jump around on every refresh.
static int ps1RowCmp(const void *a, const void *b)
{
    const base_game_info_t *ga = (const base_game_info_t *)a;
    const base_game_info_t *gb = (const base_game_info_t *)b;
    int r = strcasecmp(vcdSortKey(ga->name), vcdSortKey(gb->name));

    if (r != 0)
        return r;
    return strcasecmp(ga->extension, gb->extension);
}

// Build the Ember half without sorting it yet. The merged PS1 path sorts the final union once;
// standalone UDPFS/UDPBD callers go through cueFillGameList below, which sorts this list directly.
static int cueFillGameListUnsorted(const char *devPrefix, base_game_info_t **outGames)
{
    cue_entry_t *entries = NULL;
    base_game_info_t *games;
    int n, i;

    if (outGames == NULL)
        return 0;

    n = cueScanDir(devPrefix, &entries);
    if (n < 0)
        return -1; // could not read the device -> caller preserves its list
    if (n == 0) {
        free(entries);
        free(*outGames);
        *outGames = NULL;
        return 0;
    }

    games = (base_game_info_t *)memalign(64, n * sizeof(base_game_info_t));
    if (games == NULL) {
        free(entries);
        return -1;
    }
    memset(games, 0, n * sizeof(base_game_info_t));

    for (i = 0; i < n; i++) {
        // IDENTITY is the folder name, and it stays the folder name: it is Ember's launch argument,
        // and art / per-game CFG / favourites all key off it. Exactly the discipline the VCD rows
        // use with their filename.
        snprintf(games[i].name, sizeof(games[i].name), "%s", entries[i].name);
        snprintf(games[i].startup, sizeof(games[i].startup), "%s", entries[i].name);
        snprintf(games[i].extension, sizeof(games[i].extension), "%s", CUE_ROW_EXTENSION);
        games[i].parts = 1;
        games[i].format = GAME_FORMAT_ISO; // harmless; the row's extension gates the launch path
    }

    free(entries);
    // The replacement is complete: only now release the published last-good list. On allocation or
    // scan failure above it remains untouched for the caller to keep displaying.
    free(*outGames);
    *outGames = games;
    return n;
}

int cueFillGameList(const char *devPrefix, base_game_info_t **outGames)
{
    int count = cueFillGameListUnsorted(devPrefix, outGames);

    if (count > 1 && gAutosort)
        qsort(*outGames, count, sizeof(base_game_info_t), &ps1RowCmp);
    return count;
}

int ps1FillGameList(const char *devPrefix, base_game_info_t **outGames)
{
    base_game_info_t *vcdGames = NULL, *cueGames = NULL, *merged = NULL;
    int vcdCount, cueCount, total;

    if (outGames == NULL)
        return 0;

    vcdCount = vcdFillGameList(devPrefix, &vcdGames);
    cueCount = cueFillGameListUnsorted(devPrefix, &cueGames);

    // ONLY BOTH halves failing means the device could not be read. This used to fail the whole scan
    // when EITHER half did, on the reasoning that publishing half a list looks like a user's titles
    // disappearing. That reasoning was wrong in the direction that matters: one half failing then
    // hid the OTHER half too, so a device holding a perfectly readable POPS library showed NOTHING
    // because its (absent) Ember half reported a failure. Hardware-reported on iLink.
    //
    // Half a list beats no list. A half that failed contributes no rows this pass and is retried on
    // the next refresh; the half that succeeded is published, because it is real.
    if (vcdCount < 0 && cueCount < 0) {
        free(vcdGames);
        free(cueGames);
        LOG("[PS1] both scans failed -- keeping last-good list\n");
        return -1;
    }
    if (vcdCount < 0) {
        LOG("[PS1] POPS scan failed -- publishing the Ember half alone this pass\n");
        free(vcdGames);
        vcdGames = NULL;
        vcdCount = 0;
    }
    if (cueCount < 0) {
        LOG("[PS1] EMBER scan failed -- publishing the POPSTARTER half alone this pass\n");
        free(cueGames);
        cueGames = NULL;
        cueCount = 0;
    }

    total = vcdCount + cueCount;

    if (total == 0) {
        // Both scans reached the device and it genuinely holds no PS1 titles: publishing empty is
        // the correct answer, so release the old list here.
        free(*outGames);
        *outGames = NULL;
        free(vcdGames);
        free(cueGames);
        return 0;
    }

    // ALLOCATE BEFORE RELEASING. Freeing the published list first and then failing to allocate its
    // replacement turns a transient out-of-memory into a permanently blank PS1 page -- the caller is
    // told 0 ("readable, nothing here") and has nothing left to fall back on. Failing to allocate is
    // exactly the case where the last-good list is most worth keeping, so report it like any other
    // scan failure and leave *outGames untouched.
    merged = (base_game_info_t *)memalign(64, total * sizeof(base_game_info_t));
    if (merged == NULL) {
        free(vcdGames);
        free(cueGames);
        LOG("[PS1] merge alloc failed (%d rows) -- keeping last-good list\n", total);
        return -1;
    }

    // The replacement exists: only NOW is it safe to drop the old one.
    free(*outGames);
    *outGames = NULL;

    if (vcdCount > 0)
        memcpy(merged, vcdGames, vcdCount * sizeof(base_game_info_t));
    if (cueCount > 0)
        memcpy(merged + vcdCount, cueGames, cueCount * sizeof(base_game_info_t));

    free(vcdGames);
    free(cueGames);

    // Gated on the same Automatic Sorting switch every other list honours. With it off the halves
    // stay concatenated in scan order, which is the "raw directory order" the setting promises.
    if (gAutosort && total > 1)
        qsort(merged, total, sizeof(base_game_info_t), &ps1RowCmp);

    *outGames = merged;
    return total;
}
