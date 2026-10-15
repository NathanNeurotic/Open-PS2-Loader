/*
 * Experimental PSX DESR DVR filesystem game source.
 * The PS2 APA (hdd0:) and DVRP (dvr_hdd0:) namespaces are NOT interchangeable.
 * All enumeration and mounting performed by this source are read-only.
 * DVRP backend: pcm720/neutrino bsd-dvr; reference: Launchstation's DVRP stack.
 */
#include "sys/fcntl.h"
#include "include/opl.h"
#include "include/dvrsupport.h"
#include "include/hddsupport.h"
#include "include/supportbase.h"
#include "include/system.h"
#include "include/extern_irx.h"
#include "include/ioman.h" // LOG uses the common, release-safe output macro.
#include "include/menusys.h"
#include "include/lang.h"
#include "include/gui.h"
#include "include/mmcesupport.h"
#include "include/texcache.h"
#include "include/textures.h"
#include "include/util.h"
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h>
#include <io_common.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

#define DVR_GAME_LIMIT         256
#define DVR_PARTITION_NAME_MAX 32
#define DVR_FILENAME_MAX       161

typedef struct
{
    base_game_info_t game;
    char imagePath[256];
} dvr_game_t;

static dvr_game_t *dvrGames;
static int dvrGameCount;
static int dvrDrvLoaded;
static int dvrFileLoaded;
static int dvrDev9Owned;
static int dvrKeepMountOnHandoff;
static int dvrPfsOwned;
static char dvrMountedPartition[DVR_PARTITION_NAME_MAX + 1];
static int dvrReady;
static item_list_t dvrGameList;
static char dvrPrefix[] = "dvr_pfs0:";
static char dvrConfigPrefix[256];

static int dvrIsDesr(void)
{
    int fd = open("rom0:PSXVER", O_RDONLY);
    if (fd < 0)
        return 0;
    close(fd);
    return 1;
}

int dvrIsAvailable(void)
{
    return dvrIsDesr();
}

/* A partition label, never a user-supplied path. No slash, colon, dot-dot or
 * device prefix is allowed to escape the DVRP namespace. */
static int dvrValidPartition(const char *name)
{
    int i;
    if (!name || !name[0])
        return 0;
    for (i = 0; name[i]; i++) {
        char c = name[i];
        if (i >= DVR_PARTITION_NAME_MAX || c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' || c == '"' || c == '<' || c == '>' || c == '|')
            return 0;
    }
    return i > 0 && strcmp(name, ".") != 0 && strcmp(name, "..") != 0;
}

static int dvrLoadModules(void)
{
    int fd;
    if (dvrReady)
        return 1;
    if (!dvrIsDesr()) {
        LOG("[DVR] non-DESR hardware; DVR source disabled\n");
        return 0;
    }
    /*
     * pcm720/neutrino bsd-dvr requires DEV9 + dvrdrv + dvrfile, NOT PS2HDD,
     * PS2FS or an APA home. Probe neither the DVR disk's APA table nor its
     * configuration partition: those are unrelated to the DVRP filesystem.
     * The traditional HDD initialization can modify non-APA media.
     */
    if (!dvrDev9Owned) {
        if (!sysInitDev9()) {
            sysShutdownDev9(); /* sysInitDev9 acquires a ref even on failure */
            LOG("[DVR] DEV9 could not start; DVRP source unavailable\n");
            return 0;
        }
        dvrDev9Owned = 1;
    }
    if (!dvrDrvLoaded) {
        if (sysLoadModuleBuffer(&dvrdrv_irx, size_dvrdrv_irx, 0, NULL) < 0) {
            LOG("[DVR] cannot load PS2SDK dvrdrv.irx\n");
            return 0;
        }
        dvrDrvLoaded = 1;
    }
    if (!dvrFileLoaded) {
        if (sysLoadModuleBuffer(&dvrfile_irx, size_dvrfile_irx, 0, NULL) < 0) {
            LOG("[DVR] cannot load PS2SDK dvrfile.irx\n");
            return 0;
        }
        dvrFileLoaded = 1;
    }
    /* Check the actual DVR directory driver rather than inferring readiness
     * from the two module-load return codes. */
    fd = fileXioDopen("dvr_hdd0:");
    if (fd < 0) {
        LOG("[DVR] no accessible dvr_hdd0: (%d)\n", fd);
        return 0;
    }
    fileXioDclose(fd);
    dvrReady = 1;
    return 1;
}

static int dvrMountReadOnly(void)
{
    char partition[64];
    int fd;
    if (!dvrLoadModules() || !dvrValidPartition(gDVRPartition))
        return 0;

    /* Re-apply a changed partition selection safely. Only unmount the slot
     * acquired by this source, never one owned by Launchstation or PSX OS. */
    if (dvrPfsOwned && strcmp(dvrMountedPartition, gDVRPartition) != 0) {
        fileXioUmount(dvrPrefix);
        dvrPfsOwned = 0;
        dvrMountedPartition[0] = '\0';
        /* A selected partition change invalidates row IDs and image paths.
         * Preserve neither stale covers nor launch candidates from the old
         * mount when a new partition fails its scan. */
        free(dvrGames);
        dvrGames = NULL;
        dvrGameCount = 0;
    }
    if (!dvrPfsOwned) {
        snprintf(partition, sizeof(partition), "dvr_hdd0:%s", gDVRPartition);
        if (fileXioMount(dvrPrefix, partition, FIO_MT_RDONLY) == 0) {
            dvrPfsOwned = 1;
            snprintf(dvrMountedPartition, sizeof(dvrMountedPartition), "%s", gDVRPartition);
            LOG("[DVR] read-only mount %s -> %s\n", partition, dvrPrefix);
        } else {
            /*
             * Launchstation or the PSX firmware may already own dvr_pfs0.
             * Such a mount is read-only *to us*, and may have a different
             * partition identity. Refuse to relabel/remount an occupied slot.
             */
            fd = fileXioDopen("dvr_pfs0:/");
            if (fd >= 0) {
                fileXioDclose(fd);
                LOG("[DVR] dvr_pfs0 already mounted by another program; partition identity unknown\n");
            }
            return 0;
        }
    }

    fd = fileXioDopen("dvr_pfs0:/");
    if (fd < 0) {
        LOG("[DVR] mounted partition not readable (%d)\n", fd);
        return 0;
    }
    fileXioDclose(fd);
    return 1;
}

static unsigned int dvrPathHash(const char *path)
{
    unsigned int h = 2166136261u;
    while (*path) {
        h ^= (unsigned char)*path++;
        h *= 16777619u;
    }
    return h;
}

static int dvrFileNameIsIso(const char *name, int *baseLen)
{
    int n = 0;
    if (!name)
        return 0;
    while (n < DVR_FILENAME_MAX && name[n])
        n++;
    if (n < 5 || n >= DVR_FILENAME_MAX || strcasecmp(name + n - 4, ".iso"))
        return 0;
    *baseLen = n - 4;
    return 1;
}

static void dvrSetStartup(char *out, const char *filename, const char *path)
{
    /* Use the actual 11-byte disc ID only when the filename starts with it.
     * Otherwise create a stable local CFG identity, not a fake retail GameID:
     * Neutrino will inspect SYSTEM.CNF itself. */
    int i, shape = filename[4] == '_' && filename[8] == '.';
    for (i = 0; i < 4 && shape; i++)
        if (!((filename[i] >= 'A' && filename[i] <= 'Z') || (filename[i] >= '0' && filename[i] <= '9')))
            shape = 0;
    for (i = 5; i < 11 && shape; i++)
        if (i != 8 && !(filename[i] >= '0' && filename[i] <= '9'))
            shape = 0;
    if (shape)
        snprintf(out, GAME_STARTUP_MAX + 1, "%.11s", filename);
    else
        snprintf(out, GAME_STARTUP_MAX + 1, "DVR%08X", dvrPathHash(path));
}

/* Scan only root ISO files and the conventional CD/DVD directories. No
 * recursive walk of a recording/system partition, no edits, no cache writes. */
static int dvrScanDirectory(const char *dir, dvr_game_t **games, int *count)
{
    int fd, ret;
    iox_dirent_t item;
    fd = fileXioDopen(dir);
    if (fd < 0) {
        LOG("[DVR] optional directory unavailable: %s (%d)\n", dir, fd);
        return -1;
    }
    while ((ret = fileXioDread(fd, &item)) > 0) {
        int nameLen, pathLen;
        dvr_game_t *slot, *array;
        char path[256];
        if (!(item.stat.mode & FIO_S_IFREG) || !dvrFileNameIsIso(item.name, &nameLen))
            continue;
        if (*count >= DVR_GAME_LIMIT) {
            LOG("[DVR] listing capped at %d ISO entries\n", DVR_GAME_LIMIT);
            break;
        }
        pathLen = snprintf(path, sizeof(path), "%s%s", dir, item.name);
        if (pathLen < 0 || pathLen >= (int)sizeof(path))
            continue;
        array = (dvr_game_t *)realloc(*games, (size_t)(*count + 1) * sizeof(dvr_game_t));
        if (!array) {
            fileXioDclose(fd);
            return -2;
        }
        *games = array;
        slot = &array[*count];
        memset(slot, 0, sizeof(*slot));
        snprintf(slot->imagePath, sizeof(slot->imagePath), "%s", path);
        snprintf(slot->game.name, sizeof(slot->game.name), "%.*s", nameLen, item.name);
        dvrSetStartup(slot->game.startup, slot->game.name, path);
        strcpy(slot->game.extension, ".iso");
        slot->game.format = GAME_FORMAT_ISO;
        slot->game.media = !strcmp(dir, "dvr_pfs0:/CD/") ? SCECdPS2CD : SCECdPS2DVD;
        slot->game.sizeMB = (u32)((((u64)item.stat.hisize << 32) | item.stat.size) >> 20);
        ++*count;
    }
    fileXioDclose(fd);
    return ret < 0 ? -1 : 0;
}

static void dvrInit(item_list_t *list)
{
    (void)list;
    dvrGameList.enabled = 1;
    dvrGameList.delay = gArtDelay;
    const char *home = configGetHomePath();
    snprintf(dvrConfigPrefix, sizeof(dvrConfigPrefix), "%s", home ? home : "");
    /* Never use the DVR device itself as a writable CFG or ART home, even
     * if an unusual boot/config override resolved to a DVRP path. */
    if (!strncasecmp(dvrConfigPrefix, "dvr_pfs", 7) || !strncasecmp(dvrConfigPrefix, "dvr_hdd", 7))
        snprintf(dvrConfigPrefix, sizeof(dvrConfigPrefix), "mc0:/OPL/");
    size_t n = strlen(dvrConfigPrefix);
    if (n && n < sizeof(dvrConfigPrefix) - 2 && dvrConfigPrefix[n - 1] != '/')
        strcat(dvrConfigPrefix, "/");
}

static int dvrNeedsUpdate(item_list_t *list)
{
    (void)list;
    return 1; /* Manual refresh only (updateDelay = -1). */
}

static int dvrUpdate(item_list_t *list)
{
    dvr_game_t *next = NULL;
    int count = 0, root;
    (void)list;
    if (!dvrMountReadOnly())
        return dvrGameCount; /* preserve last known list on temporary failure */

    root = dvrScanDirectory("dvr_pfs0:/", &next, &count);
    if (root != 0 || dvrScanDirectory("dvr_pfs0:/DVD/", &next, &count) == -2 || dvrScanDirectory("dvr_pfs0:/CD/", &next, &count) == -2) {
        free(next);
        LOG("[DVR] refresh incomplete; retaining %d previously found games\n", dvrGameCount);
        return dvrGameCount;
    }
    free(dvrGames);
    dvrGames = next;
    dvrGameCount = count;
    LOG("[DVR] found %d ISO(s), read-only\n", count);
    return count;
}

static int dvrCount(item_list_t *list)
{
    (void)list;
    return dvrGameCount;
}
static void *dvrGet(item_list_t *list, int id)
{
    (void)list;
    return (id >= 0 && id < dvrGameCount && dvrGames) ? (void *)&dvrGames[id].game : NULL;
}
static char *dvrName(item_list_t *list, int id)
{
    base_game_info_t *g = dvrGet(list, id);
    return g ? g->name : NULL;
}
static int dvrNameLength(item_list_t *list, int id)
{
    (void)list;
    (void)id;
    return ISO_GAME_NAME_MAX + 1;
}
static char *dvrStartup(item_list_t *list, int id)
{
    base_game_info_t *g = dvrGet(list, id);
    return g ? g->startup : NULL;
}
static char *dvrGetPrefix(item_list_t *list)
{
    (void)list;
    return dvrPrefix;
}
static int dvrText(item_list_t *list)
{
    (void)list;
    return _STR_HDD_GAMES;
}
static int dvrIcon(item_list_t *list)
{
    (void)list;
    return HDD_ICON;
}

static config_set_t *dvrGetConfig(item_list_t *list, int id)
{
    base_game_info_t *g = dvrGet(list, id);
    if (!g)
        return NULL;
    /* Game settings and artwork are LOCAL. DVR PFS is always read-only. */
    if (dvrConfigPrefix[0])
        return sbPopulateConfig(g, dvrConfigPrefix, "/");
    return configAlloc(0, NULL, NULL);
}

static int dvrGetImage(item_list_t *list, char *folder, int isRelative,
                       char *value, char *suffix, GSTEXTURE *texture, short psm)
{
    char file[256];
    (void)list;
    (void)psm;
    if (isRelative)
        snprintf(file, sizeof(file), "%s%s/%s_%s", dvrConfigPrefix, folder, value, suffix);
    else
        snprintf(file, sizeof(file), "%s%s_%s", folder, value, suffix);
    return texDiscoverLoad(texture, file, -1);
}

static int dvrNeutrinoComplete(const char *elf)
{
    const char *sep;
    char file[320];
    static const char *needed[] = {"config/bsd-dvr.toml", "modules/dvrdrv.irx", "modules/dvrfile.irx", "modules/dvrfile_fhi.irx"};
    unsigned int i;
    if (!elf || !(sep = strrchr(elf, '/')))
        return 0;
    /*
     * The external loader must not reside in the DVR mount whose ownership
     * changes across Neutrino's PSX-mode transition. Prefer mc:/ or mass:/.
     */
    if (!strncasecmp(elf, "dvr_pfs", 7) || !strncasecmp(elf, "dvr_hdd", 7))
        return 0;
    for (i = 0; i < sizeof(needed) / sizeof(needed[0]); i++) {
        int fd;
        int n = snprintf(file, sizeof(file), "%.*s%s", (int)(sep - elf) + 1, elf, needed[i]);
        if (n < 0 || n >= (int)sizeof(file))
            return 0;
        fd = open(file, O_RDONLY);
        if (fd < 0) {
            LOG("[DVR] Neutrino installation missing %s\n", file);
            return 0;
        }
        close(fd);
    }
    return 1;
}

static void dvrLaunch(item_list_t *list, int id, config_set_t *cfg)
{
    const char *resolved;
    char elf[320], image[256], startup[GAME_STARTUP_MAX + 1], extra[256] = "";
    int video = gNeutrinoVideoDefault, gsm = gNeutrinoGsmCompDefault, compat;
    (void)list;
    if (id < 0 || id >= dvrGameCount || !dvrGames || !cfg || !dvrIsDesr() || !dvrMountReadOnly())
        return;
    /* dvrMountReadOnly may invalidate all rows when the user changed DVR
     * partition in settings. Do not dereference the previously selected ID. */
    if (id >= dvrGameCount || !dvrGames)
        return;
    resolved = sbResolveNeutrinoPath(dvrPrefix);
    if (!resolved || !dvrNeutrinoComplete(resolved)) {
        guiMsgBox("DESR DVR requires pcm720's complete bsd-dvr Neutrino installation (ELF, config and modules).", 0, NULL);
        return;
    }
    snprintf(elf, sizeof(elf), "%s", resolved);
    snprintf(image, sizeof(image), "%s", dvrGames[id].imagePath);
    snprintf(startup, sizeof(startup), "%s", dvrGames[id].game.startup);
    configGetStrCopy(cfg, CONFIG_ITEM_NEUTRINO_ARGS, extra, sizeof(extra));
    configGetInt(cfg, CONFIG_ITEM_NEUTRINO_VIDEO, &video);
    configGetInt(cfg, CONFIG_ITEM_NEUTRINO_GSMCOMP, &gsm);
    compat = sbGetCompatModes(cfg);
    if (sysNeutrinoPreflight("dvr", elf, 0, extra, -1) < 0)
        return;
    if (sysNeutrinoArgsPreflight("dvr", image, startup, compat, 0, elf, extra, video, gsm, 0, -1, NULL) < 0)
        return;
    sysNeutrinoWarnPadEmu(cfg);
    /* The DVR branch restarts the IOP into PSX mode. No -qb, no OPL-core
     * DVD path, and no unverified VMC/RA backend dependencies. */
    mmceSendGameID(startup, elf, 0);
    /*
     * CRITICAL: pcm720's dvrfile FHI opens the ISO after Neutrino resets
     * into its Load Environment. Unmounting here closes the DVRP-side PFS
     * namespace before Neutrino has opened the image. Keep ONLY our own
     * explicitly selected mount alive across this handoff; the next IOP
     * generation is managed by Neutrino itself.
     */
    dvrKeepMountOnHandoff = 1;
    deinitEx(sbNeutrinoDeinitException(elf), DVR_MODE, oplPath2Mode(elf));
    sysLaunchNeutrino("dvr", image, startup, compat, 0, elf, extra, video, gsm, 0, -1, NULL);
}

static void dvrClean(item_list_t *list, int exception)
{
    (void)list;
    (void)exception;
    free(dvrGames);
    dvrGames = NULL;
    dvrGameCount = 0;
    if (dvrPfsOwned && !dvrKeepMountOnHandoff) {
        fileXioUmount(dvrPrefix);
        dvrPfsOwned = 0;
        dvrMountedPartition[0] = '\0';
    }
}
static void dvrShutdown(item_list_t *list)
{
    dvrClean(list, 0);
    dvrReady = 0;
    if (dvrDev9Owned) {
        sysShutdownDev9();
        dvrDev9Owned = 0;
    }
}
static int dvrVmc(item_list_t *list, char *name, int createSize)
{
    (void)list;
    (void)name;
    (void)createSize;
    return -1; /* No DVR VMC support is claimed. */
}
item_list_t *dvrGetObject(int initOnly)
{
    if (initOnly && !dvrGameList.enabled)
        return NULL;
    return &dvrGameList;
}

static item_list_t dvrGameList = {
    DVR_MODE, -1, 0, 0, MENU_MIN_INACTIVE_FRAMES,
    MENU_UPD_DELAY_NOUPDATE, NULL, NULL, &dvrText, &dvrGetPrefix, &dvrInit,
    &dvrNeedsUpdate, &dvrUpdate, &dvrCount, &dvrGet, &dvrName, &dvrNameLength,
    &dvrStartup, NULL, NULL, &dvrLaunch, &dvrGetConfig, &dvrGetImage,
    &dvrClean, &dvrShutdown, &dvrVmc, &dvrIcon};
