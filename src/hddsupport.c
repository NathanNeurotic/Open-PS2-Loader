#include "sys/fcntl.h"
#include "include/opl.h"
#include "include/lang.h"
#include "include/gui.h"
#include "include/supportbase.h"
#include "include/hddsupport.h"
#include "include/vcdsupport.h" // HDD VCD view: vcdScanDirRoot/vcdViewActive + vcd_entry_t
#include "include/util.h"
#include "include/themes.h"
#include "include/textures.h"
#include "include/ioman.h"
#include "include/texcache.h" // cache quiesce before the launch-path VCD partition rescan (freeze guard)
#include "include/system.h"
#include "include/extern_irx.h"
#include "include/cheatman.h"
#include "include/mmcesupport.h" // mmceSendGameID() cross-device game-id (#261)
#include "modules/iopcore/common/cdvd_config.h"

#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h> // fileXioFormat, fileXioMount, fileXioUmount, fileXioDevctl
#include <io_common.h>   // FIO_MT_RDWR

#include <hdd-ioctl.h>

#define OPL_HDD_MODE_PS2LOGO_OFFSET 0x17F8

#include "../modules/isofs/zso.h"

extern int probed_fd;
extern u32 probed_lba;
extern u8 IOBuffer[2048];

static unsigned char hddForceUpdate = 0;
static unsigned char hddHDProKitDetected = 0;
static unsigned char hddModulesLoadCount = 0;
static unsigned char hddModulesLoaded = 0;
static unsigned char hddSupportModulesLoaded = 0;

static char *hddPrefix = "pfs0:";
static hdl_games_list_t hddGames;

// HDD VCD view: PS1 .VCD games gathered from the __.POPS* APA partitions. hddVcdParts is index-
// parallel to hddVcdGames -- it records which partition each VCD lives on (for the launch handoff).
static base_game_info_t *hddVcdGames = NULL;
static int hddVcdGameCount = 0;
static char (*hddVcdParts)[APA_IDMAX + 1] = NULL;

// forward declaration
static item_list_t hddGameList;

static int hddLoadGameListCache(hdl_games_list_t *cache);
static int hddUpdateGameListCache(hdl_games_list_t *cache, hdl_games_list_t *game_list);

static void hddInitModules(void)
{
    hddLoadModules();
    hddLoadSupportModules();

    // update Themes
    char path[256];
    sprintf(path, "%sTHM", gHDDPrefix);
    thmAddElements(path, "/", 1);

    sprintf(path, "%sLNG", gHDDPrefix);
    lngAddLanguages(path, "/", hddGameList.mode);

    sbCreateFolders(gHDDPrefix, 0);
}

// HD Pro Kit is mapping the 1st word in ROM0 seg as a main ATA controller,
// The pseudo ATA controller registers are accessed (input/ouput) by writing
// an id to the main ATA controller
#define HDPROreg_IO8   (*(volatile unsigned char *)0xBFC00000)
#define CDVDreg_STATUS (*(volatile unsigned char *)0xBF40200A)

static int hddCheckHDProKit(void)
{
    int ret = 0;

    DIntr();
    ee_kmode_enter();
    // HD Pro IO start commands sequence
    HDPROreg_IO8 = 0x72;
    CDVDreg_STATUS = 0;
    HDPROreg_IO8 = 0x34;
    CDVDreg_STATUS = 0;
    HDPROreg_IO8 = 0x61;
    CDVDreg_STATUS = 0;
    u32 res = HDPROreg_IO8;
    CDVDreg_STATUS = 0;

    // check result
    if ((res & 0xff) == 0xe7) {
        // HD Pro IO finish commands sequence
        HDPROreg_IO8 = 0xf3;
        CDVDreg_STATUS = 0;
        ret = 1;
    }
    ee_kmode_exit();
    EIntr();

    if (ret)
        LOG("HDDSUPPORT HD Pro Kit detected!\n");

    return ret;
}

// Taken from libhdd:
#define PFS_ZONE_SIZE 8192
#define PFS_FRAGMENT  0x00000000

static void hddCheckOPLFolder(const char *mountPoint)
{
    DIR *dir;
    char path[32];

    sprintf(path, "%sOPL", mountPoint);

    dir = opendir(path);
    if (dir == NULL)
        mkdir(path, 0777);
    else
        closedir(dir);
}

static void hddFindOPLPartition(void)
{
    static config_set_t *config;
    char name[64];
    int fd, ret = 0;

    fileXioUmount(hddPrefix);

    ret = fileXioMount("pfs0:", "hdd0:__common", FIO_MT_RDWR);
    if (ret == 0) {
        fd = open("pfs0:OPL/conf_hdd.cfg", O_RDONLY);
        if (fd >= 0) {
            config = configAlloc(0, NULL, "pfs0:OPL/conf_hdd.cfg");
            configRead(config);

            configGetStrCopy(config, "hdd_partition", name, sizeof(name));
            snprintf(gOPLPart, sizeof(gOPLPart), "hdd0:%s", name);

            configFree(config);
            close(fd);

            return;
        }

        hddCheckOPLFolder(hddPrefix);

        fd = open("pfs0:OPL/conf_hdd.cfg", O_CREAT | O_TRUNC | O_WRONLY);
        if (fd >= 0) {
            config = configAlloc(0, NULL, "pfs0:OPL/conf_hdd.cfg");
            configRead(config);

            configSetStr(config, "hdd_partition", "+OPL");
            configWrite(config);

            configFree(config);
            close(fd);
        }
    }

    snprintf(gOPLPart, sizeof(gOPLPart), "hdd0:+OPL");

    return;
}

static int hddCreateOPLPartition(const char *name)
{
    int formatArg[3] = {PFS_ZONE_SIZE, 0x2d66, PFS_FRAGMENT};
    int fd, result;
    char cmd[140];

    sprintf(cmd, "%s,,,128M,PFS", name);
    if ((fd = open(cmd, O_CREAT | O_TRUNC | O_WRONLY)) >= 0) {
        close(fd);
        result = fileXioFormat(hddPrefix, name, (const char *)&formatArg, sizeof(formatArg));
    } else {
        result = fd;
    }

    return result;
}

int hddLoadModules(void)
{
    int retLoadModule;
    int retStatus = HDD_LOADMODULES_STATUS_UNK;

    LOG("HDDSUPPORT LoadModules %d\n", hddModulesLoadCount);

    if (hddModulesLoaded)
        retStatus = HDD_LOADMODULES_STATUS_ALREADYLOADED;

    if (hddModulesLoadCount == 0) {
        // Increment the load count as soon as possible to prevent thread scheduling from allowing another thread to
        // call into here and try to double load modules.
        hddModulesLoadCount = 1;

        // DEV9 must be loaded, as HDD.IRX depends on it. Even if not required by the I/F (i.e. HDPro)
        sysInitDev9();

        // try to detect HD Pro Kit (not the connected HDD),
        // if detected it loads the specific ATAD module
        hddHDProKitDetected = hddCheckHDProKit();
        if (hddHDProKitDetected) {
            LOG("[ATAD_HDPRO]:\n");
            retLoadModule = sysLoadModuleBuffer(&hdpro_atad_irx, size_hdpro_atad_irx, 0, NULL);
            LOG("[XHDD]:\n");
            sysLoadModuleBuffer(&xhdd_irx, size_xhdd_irx, 6, "-hdpro");
        } else {
            LOG("[BDM]:\n");
            sysLoadModuleBuffer(&bdm_irx, size_bdm_irx, 0, NULL);
            LOG("[ATAD]:\n");
            retLoadModule = sysLoadModuleBuffer(&ps2atad_irx, size_ps2atad_irx, 0, NULL);
            LOG("[XHDD]:\n");
            sysLoadModuleBuffer(&xhdd_irx, size_xhdd_irx, 0, NULL);
        }

        if (retLoadModule < 0) {
            LOG("HDD: No HardDisk Drive detected.\n");
            setErrorMessageWithCode(_STR_HDD_NOT_CONNECTED_ERROR, ERROR_HDD_IF_NOT_DETECTED);
            retStatus = HDD_LOADMODULES_STATUS_ERROR;
        } else {
            retStatus = HDD_LOADMODULES_STATUS_NOERROR;
            hddModulesLoaded = 1;
        }
    } else {
        hddModulesLoadCount++;
        if (!hddModulesLoaded)
            retStatus = HDD_LOADMODULES_STATUS_BUSYLOADING;
    }

    LOG("HDDSUPPORT LoadModules done\n");
    return retStatus;
}

// Returns 1 for MBR/GPT, 0 for APA, and -1 if an error occured
int hddDetectNonSonyFileSystem()
{
    int result = -1;
    // Allocate memory for storing data for the first two sectors.
    u8 *pSectorData = (u8 *)malloc(512 * 2);
    if (pSectorData == NULL) {
        LOG("hddDetectNonSonyFileSystem: failed to allocate scratch memory\n");
        return -1;
    }

    // Trying to load the APA/PFS irx modules when a non-sony formatted HDD is connected (ie: MBR/GPT  w/ exFAT) runs
    // the risk of corrupting the HDD. To avoid that get the first two sectors and perform some sanity checks. If
    // we reasonably suspect the disk is not APA formatted bail out from loading the sony fs irx modules.
    result = fileXioDevctl("xhdd0:", ATA_DEVCTL_READ_PARTITION_SECTOR, NULL, 0, pSectorData, 512 * 2);
    if (result < 0) {
        LOG("hddDetectNonSonyFileSystem: failed to read data from hdd %d\n", result);
        free(pSectorData);
        return -1;
    }

    // Check for MBR signature.
    if (pSectorData[0x1FE] == 0x55 && pSectorData[0x1FF] == 0xAA) {
        // Found MBR partition type.
        LOG("hddDetectNonSonyFileSystem: found MBR partition data\n");
        result = 1;
    } else if (strncmp((const char *)&pSectorData[0x200], "EFI PART", 8) == 0) {
        // Found GPT partition type.
        LOG("hddDetectNonSonyFileSystem: found GPT partition data\n");
        result = 1;
    } else if (strncmp((const char *)&pSectorData[4], "APA", 3) == 0) {
        // Found APA partition type.
        LOG("hddDetectNonSonyFileSystem: found APA partition data\n");
        result = 0;
    } else {
        // Even though we didn't find evidence of non-APA partition data, if we load the APA irx module
        // it will write to the drive and potentially corrupt any data that might be there.
        LOG("hddDetectNonSonyFileSystem: partition data not recognized\n");
        result = -1;
    }

    // Cleanup and return.
    free(pSectorData);
    return result;
}

void hddLoadSupportModules(void)
{
    static char hddarg[] = "-o"
                           "\0"
                           "4"
                           "\0"
                           "-n"
                           "\0"
                           "20";
    static char pfsarg[] = "\0"
                           "-o" // max open
                           "\0"
                           "10" // Default value: 2
                           "\0"
                           "-n" // Number of buffers
                           "\0"
                           "40"; // Default value: 8 | Max value: 127

    LOG("HDDSUPPORT LoadSupportModules\n");

    // Check if the drive contains MBR/GPT partition data before we load the APA/PFS modules. If the drive is not
    // APA then loading the APA irx modules can corrupt the drive as it will try to write APA partition data.
    if (hddDetectNonSonyFileSystem() != 0) {
        // Drive is MBR/GPT style, or unknown, bail out or risk corrupting the drive.
        LOG("HDDSUPPORT LoadSupportModules bailing out early...\n");
        return;
    }

    if (!hddSupportModulesLoaded) {
        LOG("[HDD]:\n");
        int ret = sysLoadModuleBuffer(&ps2hdd_irx, size_ps2hdd_irx, sizeof(hddarg), hddarg);
        if (ret < 0) {
            LOG("HDD: No HardDisk Drive detected.\n");
            setErrorMessageWithCode(_STR_HDD_NOT_CONNECTED_ERROR, ERROR_HDD_MODULE_HDD_FAILURE);
            return;
        }

        // Check if a HDD unit is connected
        if (hddCheck() < 0) {
            LOG("HDD: No HardDisk Drive detected.\n");
            setErrorMessageWithCode(_STR_HDD_NOT_CONNECTED_ERROR, ERROR_HDD_NOT_DETECTED);
            return;
        }

        LOG("[PS2FS]:\n");
        ret = sysLoadModuleBuffer(&ps2fs_irx, size_ps2fs_irx, sizeof(pfsarg), pfsarg);
        if (ret < 0) {
            LOG("HDD: HardDisk Drive not formatted (PFS).\n");
            setErrorMessageWithCode(_STR_HDD_NOT_FORMATTED_ERROR, ERROR_HDD_MODULE_PFS_FAILURE);
            return;
        }

        hddSupportModulesLoaded = 1;
        LOG("HDDSUPPORT modules loaded\n");

        if (gOPLPart[0] == '\0')
            hddFindOPLPartition();

        fileXioUmount(hddPrefix);

        ret = fileXioMount(hddPrefix, gOPLPart, FIO_MT_RDWR);
        if (ret == -ENOENT) {
            // Attempt to create the partition.
            if ((hddCreateOPLPartition(gOPLPart)) >= 0)
                fileXioMount(hddPrefix, gOPLPart, FIO_MT_RDWR);
        }

        if (gOPLPart[5] != '+') {
            hddCheckOPLFolder(hddPrefix);
            gHDDPrefix = "pfs0:OPL/";
        }
    }
}

void hddInit(item_list_t *itemList)
{
    LOG("HDDSUPPORT Init\n");
    hddForceUpdate = 0; // Use cache at initial startup.
    configGetInt(configGetByType(CONFIG_OPL), "hdd_frames_delay", &hddGameList.delay);
    ioPutRequest(IO_CUSTOM_SIMPLEACTION, &hddInitModules);
    hddGameList.enabled = 1;
}

item_list_t *hddGetObject(int initOnly)
{
    if (initOnly && !hddGameList.enabled)
        return NULL;
    return &hddGameList;
}

// ---- HDD VCD view (PS1 .VCD on the __.POPS* APA partitions) -------------------------------

static void hddFreeVcdGameList(void)
{
    free(hddVcdGames);
    hddVcdGames = NULL;
    free(hddVcdParts);
    hddVcdParts = NULL;
    hddVcdGameCount = 0;
}

// Build the HDD VCD game list by scanning every present __.POPS* APA partition. Each is mounted
// read-only on pfs0:, its root scanned for *.VCD, and the results appended to hddVcdGames, with the
// owning partition label kept index-parallel in hddVcdParts (so the launch path knows which partition
// to hand POPSTARTER). The default OPL data-partition mount is restored at the end -- pfs0: is the
// single shared slot, so the rest of HDD mode breaks if we leave it pointed elsewhere. Returns the count.
// Bounded wait (ticks, ~1ms each) for the art worker to drain before we remount pfs0:. Matches the
// MMCE art-abort budget; long enough for an in-flight pfs cover read to abort at its next row
// boundary, short enough that a truly-wedged read can't hang the view switch forever.
#define HDD_VCD_ART_DRAIN_TICKS 500

static int hddBuildVcdGameList(void)
{
    hdd_pops_list_t parts;
    int total = 0;

    hddFreeVcdGameList();

    if (hddGetPopsPartitionList(&parts) <= 0)
        return 0; // no __.POPS* partitions; pfs0: was not touched here

    // pfs0: is the single shared ps2fs slot; umounting it in the loop below while the cache art
    // worker still holds an open pfs0: cover fd is the documented HDD-freeze hazard (see hddLaunchVcd).
    // The in-view L3 toggle / background refresh / Favourites-cold path all reach here WITHOUT the
    // launch path's pre-quiesce -- FifthFox's "won't switch to VCD / crash on VCD launch on HDD",
    // which only armed with cover art ON. Quiesce here in one spot so every caller is covered: cancel
    // + DRAIN pending art (preserveLoaded=0 flags the in-flight read to abort at its next row
    // boundary) with a bounded, NONZERO wait so the worker releases its pfs0: fd before we remount.
    // (timeout 0 would return without waiting.) Runs on the IO handler thread, so no ioBlockOps here.
    (void)cacheCancelPendingImageLoadsTimed(HDD_VCD_ART_DRAIN_TICKS);

    for (int p = 0; p < parts.count; p++) {
        char mountSrc[64];
        snprintf(mountSrc, sizeof(mountSrc), "hdd0:%s", parts.names[p]);

        fileXioUmount(hddPrefix);
        if (fileXioMount(hddPrefix, mountSrc, FIO_MT_RDONLY) < 0)
            continue; // can't mount this partition -> skip it

        // PP.* single-game install: ONE IMAGE0.VCD on the partition root, displayed by the partition
        // label minus "PP." (the launch keys off the FULL label -- see hddDoLaunchVcd). __.POPS* stores
        // (handled below) hold MANY .VCD files named per game.
        if (strncmp(parts.names[p], "PP.", 3) == 0) {
            int imgfd = open("pfs0:/IMAGE0.VCD", O_RDONLY);
            fileXioUmount(hddPrefix);
            if (imgfd < 0)
                continue; // no IMAGE0.VCD here -> not a usable PP. install
            close(imgfd);

            base_game_info_t *grownGames = realloc(hddVcdGames, (total + 1) * sizeof(base_game_info_t));
            if (grownGames == NULL)
                break;
            hddVcdGames = grownGames;
            char(*grownParts)[APA_IDMAX + 1] = realloc(hddVcdParts, (total + 1) * sizeof(*hddVcdParts));
            if (grownParts == NULL)
                break;
            hddVcdParts = grownParts;

            base_game_info_t *g = &hddVcdGames[total];
            memset(g, 0, sizeof(base_game_info_t));
            snprintf(g->name, sizeof(g->name), "%s", parts.names[p] + 3); // strip "PP." -> display name
            snprintf(g->extension, sizeof(g->extension), ".VCD");
            g->parts = 1;
            g->format = GAME_FORMAT_ISO;                                       // harmless; VCD flag gates the launch
            snprintf(hddVcdParts[total], APA_IDMAX + 1, "%s", parts.names[p]); // FULL label, e.g. PP.GAME
            total += 1;
            continue;
        }

        vcd_entry_t *vcds = NULL;
        int n = vcdScanDirRoot("pfs0:/", &vcds);
        fileXioUmount(hddPrefix);
        if (n <= 0) {
            free(vcds);
            continue;
        }

        base_game_info_t *grownGames = realloc(hddVcdGames, (total + n) * sizeof(base_game_info_t));
        if (grownGames == NULL) {
            free(vcds);
            break;
        }
        hddVcdGames = grownGames;
        char(*grownParts)[APA_IDMAX + 1] = realloc(hddVcdParts, (total + n) * sizeof(*hddVcdParts));
        if (grownParts == NULL) {
            free(vcds);
            break;
        }
        hddVcdParts = grownParts;

        for (int i = 0; i < n; i++) {
            base_game_info_t *g = &hddVcdGames[total + i];
            memset(g, 0, sizeof(base_game_info_t));
            snprintf(g->name, sizeof(g->name), "%s", vcds[i].name);
            snprintf(g->startup, sizeof(g->startup), "%s", vcds[i].gameId); // PS1 id (or "" = no art)
            snprintf(g->extension, sizeof(g->extension), ".VCD");
            g->parts = 1;
            g->format = GAME_FORMAT_ISO; // harmless; the per-mode VCD flag gates the launch path
            snprintf(hddVcdParts[total + i], APA_IDMAX + 1, "%s", parts.names[p]);
        }
        free(vcds);
        total += n;
    }

    hddFreePopsPartitionList(&parts);

    // Restore the default OPL data-partition mount (the loop left pfs0: unmounted).
    fileXioUmount(hddPrefix);
    fileXioMount(hddPrefix, gOPLPart, FIO_MT_RDWR);

    hddVcdGameCount = total;
    return total;
}

static int hddNeedsUpdate(item_list_t *itemList)
{ /* Auto refresh is disabled by setting HDD_MODE_UPDATE_DELAY to MENU_UPD_DELAY_NOUPDATE, within hddsupport.h.
       Hence any update request would be issued by the user, which should be taken as an explicit request to re-scan the HDD. */
    if (vcdConsumeDirty(itemList->mode))
        return 1; // L3 toggle / default-view change -> force one rescan
    if (vcdViewActive(itemList->mode))
        return 0; // in VCD view: skip the HDL re-scan churn
    return 1;
}

static int hddUpdateGameList(item_list_t *itemList)
{
    if (vcdViewActive(itemList->mode))
        return hddBuildVcdGameList();

    hdl_games_list_t hddGamesNew;
    int ret;

    // Force a live APA scan not only when the cache fails to load (ret != 0) or a prior build asked for it
    // (hddForceUpdate), but ALSO when the cache loaded EMPTY (count 0). A missing/empty/stale games.bin
    // otherwise left the first HDD page blank until a second manual refresh (provato's HW report).
    if (((ret = hddLoadGameListCache(&hddGames)) != 0) || (hddForceUpdate) || (hddGames.count == 0)) {
        hddGamesNew.count = 0;
        hddGamesNew.games = NULL;
        ret = hddGetHDLGamelist(&hddGamesNew);
        if (ret == 0) {
            hddUpdateGameListCache(&hddGames, &hddGamesNew);
            hddFreeHDLGamelist(&hddGames);
            hddGames = hddGamesNew;
        }
    }

    hddForceUpdate = 1; // Subsequent refresh operations will cause the HDD to be scanned.

    return (ret == 0 ? hddGames.count : 0);
}

static int hddGetGameCount(item_list_t *itemList)
{
    return vcdViewActive(itemList->mode) ? hddVcdGameCount : (int)hddGames.count;
}

static void *hddGetGame(item_list_t *itemList, int id)
{
    return vcdViewActive(itemList->mode) ? (void *)&hddVcdGames[id] : (void *)&hddGames.games[id];
}

static char *hddGetGameName(item_list_t *itemList, int id)
{
    return vcdViewActive(itemList->mode) ? hddVcdGames[id].name : hddGames.games[id].name;
}

static int hddGetGameNameLength(item_list_t *itemList, int id)
{
    return vcdViewActive(itemList->mode) ? VCD_NAME_MAX : (HDL_GAME_NAME_MAX + 1);
}

static char *hddGetGameStartup(item_list_t *itemList, int id)
{
    // VCD view keys per-game CFG/art off the VCD filename (game->name), not a disc id.
    return vcdViewActive(itemList->mode) ? hddVcdGames[id].name : hddGames.games[id].startup;
}

static void hddDeleteGame(item_list_t *itemList, int id)
{
    if (vcdViewActive(itemList->mode))
        return; // a VCD is not an HDL partition -- no delete in VCD view
    hddDeleteHDLGame(&hddGames.games[id]);
    hddForceUpdate = 1;
}

static void hddRenameGame(item_list_t *itemList, int id, char *newName)
{
    if (vcdViewActive(itemList->mode))
        return; // a VCD is not an HDL partition -- no rename in VCD view
    hdl_game_info_t *game = &hddGames.games[id];
    strcpy(game->name, newName);
    hddSetHDLGameInfo(&hddGames.games[id]);
    hddForceUpdate = 1;
}

// Index of the VCD whose basename matches vcdName in the current hddVcdGames list, or -1.
static int hddFindVcdByName(const char *vcdName)
{
    for (int i = 0; i < hddVcdGameCount; i++) {
        if (strcmp(hddVcdGames[i].name, vcdName) == 0)
            return i;
    }
    return -1;
}

// Resolve POPSTARTER.ELF for an HDD VCD launch: search hdd0:__common then hdd0:+OPL, each at its ROOT
// /POPS/ (NOT the OPL/POPS/ data subfolder). On success returns 1 with elfOut = "pfs0:/POPS/POPSTARTER.ELF"
// and LEAVES pfs0: mounted on that partition so the caller can load the ELF from it; on failure returns 0
// with pfs0: restored to the OPL data partition. The CALLER must quiesce the art + IO workers first --
// this remounts the single pfs0: slot, and umounting it under a live cover read is the HDD-freeze hazard.
static int hddResolveHddPopstarter(char *elfOut, int elfLen)
{
    static const char *cands[2] = {"hdd0:__common", "hdd0:+OPL"};

    for (int i = 0; i < 2; i++) {
        fileXioUmount(hddPrefix);
        if (fileXioMount(hddPrefix, cands[i], FIO_MT_RDONLY) < 0)
            continue; // partition absent / unmountable -> try the next
        int fd = open("pfs0:/POPS/POPSTARTER.ELF", O_RDONLY);
        if (fd >= 0) {
            close(fd);
            snprintf(elfOut, elfLen, "pfs0:/POPS/POPSTARTER.ELF");
            return 1; // keep pfs0: on this partition for the ELF load
        }
    }

    // Not found: restore the default OPL data-partition mount so normal HDD IO keeps working.
    fileXioUmount(hddPrefix);
    fileXioMount(hddPrefix, gOPLPart, FIO_MT_RDWR);
    return 0;
}

// Shared POPSTARTER handoff for an HDD VCD. argv[0] differs by partition shape: a PP.* single-game
// install boots by its PARTITION LABEL (e.g. PP.GAME.ELF), a __.POPS* store entry boots by the VCD name
// (e.g. GAME.ELF). The owning partition (`part`) is passed OUT OF BAND so POPSTARTER self-mounts it after
// the IOP reset. Everything is built on stack BEFORE deinit() frees the VCD list. Used by both the
// in-view menu launch and the Favourites tab (hddLaunchVcd).
static void hddDoLaunchVcd(item_list_t *itemList, const char *name, const char *part)
{
    char vcdElf[256], vcdSelector[320], vcdPart[64];

    if (name == NULL || name[0] == '\0' || part == NULL || part[0] == '\0')
        return;

    if (strncmp(part, "PP.", 3) == 0)
        snprintf(vcdSelector, sizeof(vcdSelector), "%s.ELF", part); // PP.GAME.ELF (the partition label)
    else
        snprintf(vcdSelector, sizeof(vcdSelector), "%s.ELF", name); // GAME.ELF (the __.POPS* VCD name)
    snprintf(vcdPart, sizeof(vcdPart), "hdd0:%s:", part);           // self-mount target, hdd0:PART:

    // Resolve + keep pfs0: on the POPSTARTER.ELF partition. Quiesce art+IO first (this remounts pfs0:).
    cacheAbortMmceImageLoadsTimed(0);
    (void)cacheCancelPendingImageLoadsTimed(0);
    ioBlockOps(1);
    if (!hddResolveHddPopstarter(vcdElf, sizeof(vcdElf))) {
        ioBlockOps(0); // resolver already restored pfs0: to the OPL data partition on failure
        guiMsgBox(_l(_STR_POPSTARTER_NOT_FOUND), 0, NULL);
        return;
    }
    // Success: leave IO blocked (deinit re-blocks anyway) and pfs0: on the POPSTARTER partition for the
    // load below. sysLaunchPopstarter reboots into POPSTARTER, so there is nothing to unblock.
    deinit(UNMOUNT_EXCEPTION, itemList->mode);
    sysLaunchPopstarter(vcdElf, vcdSelector, vcdPart);
}

// Launch an HDD PS1/.VCD entry BY NAME -- the Favourites tab's view-independent entry point. The
// per-game __.POPS* partition lives in hddVcdParts, which is only populated while the HDD page is in
// its VCD view; from Favourites it may be empty/stale, so (re)scan via the SAME safe partition walk the
// VCD view uses (hddBuildVcdGameList mounts each __.POPS on pfs0:, scans, restores pfs0: to the default
// OPL partition) to resolve name -> partition, then hand off exactly as the in-view launch does.
static void hddLaunchVcd(item_list_t *itemList, const char *vcdName, config_set_t *configSet)
{
    if (vcdName == NULL || vcdName[0] == '\0' || !strcmp(vcdName, "POPSTARTER"))
        return;

    int idx = hddFindVcdByName(vcdName);
    if (idx < 0) {
        // Cold path: the per-game __.POPS partition is unknown (hddVcdGames is only built while the HDD
        // page is in VCD view). hddBuildVcdGameList remounts the single ps2fs slot (pfs0:), and
        // umounting it while the cache worker holds an open fd reading a cover from pfs0: is the
        // documented HDD-freeze hazard. The equivalent in-view rescan runs on the IO thread only when no
        // art/IO is pending (opl.c menuUpdateHook); on the launch path we enforce the same invariant by
        // quiescing the art + IO workers first, exactly as deinit() does before its own teardown IO.
        cacheAbortMmceImageLoadsTimed(0);
        (void)cacheCancelPendingImageLoadsTimed(0);
        ioBlockOps(1);
        hddBuildVcdGameList(); // restores pfs0: to the default OPL partition when done
        ioBlockOps(0);
        idx = hddFindVcdByName(vcdName);
    }
    if (idx < 0) {
        guiMsgBox(_l(_STR_POPSTARTER_NOT_FOUND), 0, NULL);
        return;
    }
    hddDoLaunchVcd(itemList, hddVcdGames[idx].name, hddVcdParts[idx]);
}

// Δ8 (NHDDL parity): the LEAN Neutrino launch path for HDL games -- see bdmTryNeutrinoLaunch's
// rationale in bdmsupport.c. The native flow's VMC block-chain prompts + mcemu patching, DMA
// setup, sbPrepare, cheats (with dialogs), PS2RD images and CheckPS2Logo all exist for the
// embedded cdvdman core; Neutrino re-derives everything from -bsd=ata -bsdfs=hdl -dvd=hdl:<part>
// after its own IOP reset. The one probe Neutrino DOES need is the ZSO header check (its hdl
// backend can't run ZSO) -- a single sector read, kept here.
// Returns 1 = handled (handed off; caller returns); 0 = proceed with the native launch (core is
// OPL, or any Neutrino-side failure -- ZSO, no install, preflight -- since HDL always boots natively).
static int hddTryNeutrinoLaunch(hdl_game_info_t *game, config_set_t *configSet)
{
    int coreLoader = 0;
    configGetInt(configSet, CONFIG_ITEM_CORE_LOADER, &coreLoader);
    if (!coreLoader)
        return 0;

    // ZSO probe (one sector): Neutrino's hdl backend can't run ZSO -- fall back to the native
    // core, which can. Same read the native path performs for its layer-1 setup.
    hddReadSectors(game->start_sector + OPL_HDD_MODE_PS2LOGO_OFFSET, 1, IOBuffer);
    if (*(u32 *)IOBuffer == ZSO_MAGIC) {
        guiWarning(_l(_STR_NEUTRINO_BAD_FORMAT), 6);
        return 0;
    }

    const char *neutrinoPath = sbResolveNeutrinoPath(NULL); // #300: HDD keeps custom-path + mc0/mc1 + Device-picker resolution (raw APA isn't POSIX-reachable; pfs0 probe = shared-slot risk)
    if (neutrinoPath == NULL) {
        guiWarning(_l(_STR_NEUTRINO_NOT_FOUND), 6);
        return 0;
    }

    // Everything Neutrino needs, copied to THIS frame (deinit below frees `game`).
    int compatMode = 0, neutrinoVideo = 0, neutrinoGsmComp = 0;
    char neutrinoExtraArgs[256] = "";
    char apaPart[APA_IDMAX + 1];
    configGetInt(configSet, CONFIG_ITEM_COMPAT, &compatMode);
    configGetStrCopy(configSet, CONFIG_ITEM_NEUTRINO_ARGS, neutrinoExtraArgs, sizeof(neutrinoExtraArgs));
    configGetInt(configSet, CONFIG_ITEM_NEUTRINO_VIDEO, &neutrinoVideo);
    configGetInt(configSet, CONFIG_ITEM_NEUTRINO_GSMCOMP, &neutrinoGsmComp);
    snprintf(apaPart, sizeof(apaPart), "%s", game->partition_name);

    if (gRememberLastPlayed) {
        configSetStr(configGetByType(CONFIG_LAST), "last_played", game->startup);
        saveConfig(CONFIG_LAST, 0);
    }

    // Δ6 pre-teardown validation. On failure fall back to the native core (same contract as
    // bdmTryNeutrinoLaunch's non-udp legs): HDL always boots natively, and the native path owns
    // the autolaunch teardown -- aborting here instead would leak gAutoLaunchGame/configSet.
    if (sysNeutrinoPreflight("apa", neutrinoPath) < 0)
        return 0;

    // MMCE cross-device game-id (#261); HDD emits no -mc args (VMC->neutrino deferred), mask 0.
    mmceSendGameID(game->startup, neutrinoPath, 0);

    // game->startup lives in hddGames / gAutoLaunchGame, freed below (deinitEx's itemCleanUp or the
    // explicit free). Copy it before the teardown so sysLaunchNeutrino's -elf build is not a UAF read.
    char apaStartup[sizeof(game->startup)];
    snprintf(apaStartup, sizeof(apaStartup), "%s", game->startup);

    if (gAutoLaunchGame == NULL) {
        // Keep-IOP handoff: keep the HDD stack up (NHDDL hands off with its full ATA stack
        // resident) AND the neutrino.elf device (-cwd config/module reads).
        int neutrinoDevMode = oplPath2Mode(neutrinoPath);
        deinitEx(UNMOUNT_EXCEPTION, HDD_MODE, neutrinoDevMode); // CAREFUL: itemCleanUp frees hddGames/game
    } else {
        miniDeinit(configSet);
        free(gAutoLaunchGame);
        gAutoLaunchGame = NULL;
        fileXioUmount("pfs0:");
        fileXioDevctl("pfs:", PDIOC_CLOSEALL, NULL, 0, NULL, 0);
    }

    LOG("[NEUTRINO] apa partition_name=[%s]\n", apaPart);
    // gPS2Logo passes the preference straight through (Neutrino does its own logo work).
    sysLaunchNeutrino("apa", apaPart, apaStartup, compatMode, gPS2Logo, neutrinoPath, neutrinoExtraArgs, neutrinoVideo, neutrinoGsmComp, 0 /* #11 inert: APA is always -bsdfs=hdl */, NULL /* HDD VMC->neutrino deferred (APA/pfs) */);
    return 1;
}

void hddLaunchGame(item_list_t *itemList, int id, config_set_t *configSet)
{
    int i, size_irx = 0;
    int EnablePS2Logo = 0;
    int result;
    void *irx = NULL;
    char filename[32];
    hdl_game_info_t *game;
    struct cdvdman_settings_hdd *settings;

    // HDD VCD view: hand off to POPSTARTER instead of the HDL/Neutrino path below. Menu-launch only
    // (HDD-VCD autolaunch is out of scope). POPSTARTER's argv[0] is just the VCD name -- that name is
    // all it needs to find <name>.VCD; the __.POPS* partition the VCD lives on is passed OUT OF BAND so
    // POPSTARTER self-mounts it after the loader's IOP reset. HW-VALIDATE: POPSTARTER's exact HDD
    // selector/partition contract is hardware-testable -- POPSLoader proved the shape with a vendored
    // loader; we use the stock ps2sdk loader, the same one the shipping USB/MMCE/SMB VCD launch uses.
    if (gAutoLaunchGame == NULL && vcdViewActive(itemList->mode)) {
        hddDoLaunchVcd(itemList, hddVcdGames[id].name, hddVcdParts[id]);
        return;
    }

    if (gAutoLaunchGame == NULL)
        game = &hddGames.games[id];
    else
        game = gAutoLaunchGame;

    // D8: Neutrino core gets its own lean path FIRST -- everything below is native-core prep it
    // neither needs nor should be able to die on (see hddTryNeutrinoLaunch).
    if (hddTryNeutrinoLaunch(game, configSet))
        return;

    apa_sub_t parts[APA_MAXSUB + 1];
    char vmc_name[2][32];
    int part_valid = 0, size_mcemu_irx = 0, nparts;
    hdd_vmc_infos_t hdd_vmc_infos;
    memset(&hdd_vmc_infos, 0, sizeof(hdd_vmc_infos_t));

    configGetVMC(configSet, vmc_name[0], sizeof(vmc_name[0]), 0);
    configGetVMC(configSet, vmc_name[1], sizeof(vmc_name[1]), 1);

    if (vmc_name[0][0] || vmc_name[1][0]) {
        nparts = hddGetPartitionInfo(gOPLPart, parts);
        if (nparts > 0 && nparts <= 5) {
            for (i = 0; i < nparts; i++) {
                hdd_vmc_infos.parts[i].start = parts[i].start;
                hdd_vmc_infos.parts[i].length = parts[i].length;
                LOG("HDDSUPPORT hdd_vmc_infos.parts[%d].start : 0x%X\n", i, hdd_vmc_infos.parts[i].start);
                LOG("HDDSUPPORT hdd_vmc_infos.parts[%d].length : 0x%X\n", i, hdd_vmc_infos.parts[i].length);
            }
            part_valid = 1;
        }
    }

    if (part_valid) {
        char vmc_path[256];
        int vmc_id, have_error = 0;
        vmc_superblock_t vmc_superblock;
        pfs_blockinfo_t blocks[11];

        for (vmc_id = 0; vmc_id < 2; vmc_id++) {
            if (vmc_name[vmc_id][0]) {
                have_error = 1;
                hdd_vmc_infos.active = 0;
                if (sysCheckVMC(gHDDPrefix, "/", vmc_name[vmc_id], 0, &vmc_superblock) > 0) {
                    hdd_vmc_infos.flags = vmc_superblock.mc_flag & 0xFF;
                    hdd_vmc_infos.flags |= 0x100;
                    hdd_vmc_infos.specs.page_size = vmc_superblock.page_size;
                    hdd_vmc_infos.specs.block_size = vmc_superblock.pages_per_block;
                    hdd_vmc_infos.specs.card_size = vmc_superblock.pages_per_cluster * vmc_superblock.clusters_per_card;

                    // Check vmc inode block chain (write operation can cause damage)
                    snprintf(vmc_path, sizeof(vmc_path), "%sVMC/%s.bin", gHDDPrefix, vmc_name[vmc_id]);
                    if ((nparts = hddGetFileBlockInfo(vmc_path, parts, blocks, 11)) > 0) {
                        have_error = 0;
                        hdd_vmc_infos.active = 1;
                        for (i = 0; i < nparts - 1; i++) {
                            hdd_vmc_infos.blocks[i].number = blocks[i + 1].number;
                            hdd_vmc_infos.blocks[i].subpart = blocks[i + 1].subpart;
                            hdd_vmc_infos.blocks[i].count = blocks[i + 1].count;
                            LOG("HDDSUPPORT hdd_vmc_infos.blocks[%d].number     : 0x%X\n", i, hdd_vmc_infos.blocks[i].number);
                            LOG("HDDSUPPORT hdd_vmc_infos.blocks[%d].subpart    : 0x%X\n", i, hdd_vmc_infos.blocks[i].subpart);
                            LOG("HDDSUPPORT hdd_vmc_infos.blocks[%d].count      : 0x%X\n", i, hdd_vmc_infos.blocks[i].count);
                        }
                    } else { // else VMC file is too fragmented
                        LOG("HDDSUPPORT Block Chain NG\n");
                        have_error = 2;
                    }
                }

                if (have_error) {
                    if (gAutoLaunchGame == NULL) {
                        char error[256];
                        if (have_error == 2) // VMC file is fragmented
                            snprintf(error, sizeof(error), _l(_STR_ERR_VMC_FRAGMENTED_CONTINUE), vmc_name[vmc_id], (vmc_id + 1));
                        else
                            snprintf(error, sizeof(error), _l(_STR_ERR_VMC_CONTINUE), vmc_name[vmc_id], (vmc_id + 1));
                        if (!guiMsgBox(error, 1, NULL))
                            return;
                    } else
                        LOG("VMC error\n");
                }

                for (i = 0; i < size_hdd_mcemu_irx; i++) {
                    if (((u32 *)&hdd_mcemu_irx)[i] == (0xC0DEFAC0 + vmc_id)) {
                        if (hdd_vmc_infos.active)
                            size_mcemu_irx = size_hdd_mcemu_irx;
                        memcpy(&((u32 *)&hdd_mcemu_irx)[i], &hdd_vmc_infos, sizeof(hdd_vmc_infos_t));
                        break;
                    }
                }
            }
        }
    }

    if (gRememberLastPlayed) {
        configSetStr(configGetByType(CONFIG_LAST), "last_played", game->startup);
        saveConfig(CONFIG_LAST, 0);
    }

    char gid[5];
    configGetDiscIDBinary(configSet, gid);

    int dmaType = 0, dmaMode = 7, compatMode = 0;
    configGetInt(configSet, CONFIG_ITEM_COMPAT, &compatMode);
    configGetInt(configSet, CONFIG_ITEM_DMA, &dmaMode);
    if (dmaMode < 3)
        dmaType = 0x20;
    else {
        dmaType = 0x40;
        dmaMode -= 3;
    }
    hddSetTransferMode(dmaType, dmaMode);
    // gHDDSpindown [0..20] -> spindown [0..240] -> seconds [0..1200]
    hddSetIdleTimeout(gHDDSpindown * 12);

    if (hddHDProKitDetected) {
        size_irx = size_hdd_hdpro_cdvdman_irx;
        irx = &hdd_hdpro_cdvdman_irx;
    } else {
        size_irx = size_hdd_cdvdman_irx;
        irx = &hdd_cdvdman_irx;
    }

    sbPrepare(NULL, configSet, size_irx, irx, &i);

    if ((result = sbLoadCheats(gHDDPrefix, game->startup)) < 0) {
        if (gAutoLaunchGame == NULL) {
            switch (result) {
                case -ENOENT:
                    guiWarning(_l(_STR_NO_CHEATS_FOUND), 10);
                    break;
                default:
                    guiWarning(_l(_STR_ERR_CHEATS_LOAD_FAILED), 10);
            }
        } else
            LOG("Cheats error\n");
    }
    sbLoadImage(gHDDPrefix, game->startup);

    settings = (struct cdvdman_settings_hdd *)((u8 *)irx + i);

    // patch 48bit flag
    settings->common.media = hddIs48bit() & 0xff;

    // patch start_sector
    settings->lba_start = game->start_sector;

    if (configGetStrCopy(configSet, CONFIG_ITEM_ALTSTARTUP, filename, sizeof(filename)) == 0)
        strcpy(filename, game->startup);

    if (gPS2Logo)
        EnablePS2Logo = CheckPS2Logo(0, game->start_sector + OPL_HDD_MODE_PS2LOGO_OFFSET);

    // Check for ZSO to correctly adjust layer1 start
    settings->common.layer1_start = 0; // cdvdman will read it from APA header
    hddReadSectors(game->start_sector + OPL_HDD_MODE_PS2LOGO_OFFSET, 1, IOBuffer);
    if (*(u32 *)IOBuffer == ZSO_MAGIC) {
        probed_fd = 0;
        probed_lba = game->start_sector + OPL_HDD_MODE_PS2LOGO_OFFSET;
        ziso_init((ZISO_header *)IOBuffer, *(u32 *)((u8 *)IOBuffer + sizeof(ZISO_header)));
        ziso_read_sector(IOBuffer, 16, 1);
        u32 maxLBA = *(u32 *)(IOBuffer + 80);
        if (maxLBA > 0 && maxLBA < ziso_total_block) {   // dual layer check
            settings->common.layer1_start = maxLBA - 16; // adjust second layer start
        }
    }

    // D8: Neutrino never reaches this point (hddTryNeutrinoLaunch handled it at the top) --
    // everything from here on is the NATIVE (embedded cdvdman) launch only.

    // MMCE cross-device game-id (#261): push the HDL disc id to a present MMCE card before the HDD
    // teardown (self-probes mmce0/mmce1; no-ops if no card / feature off). Read `game` before deinit.
    mmceSendGameID(game->startup, NULL, 0);

    if (gAutoLaunchGame == NULL) {
        deinit(NO_EXCEPTION, HDD_MODE); // CAREFUL: deinit will call hddCleanUp, so hddGames/game will be freed
    } else {
        miniDeinit(configSet);

        free(gAutoLaunchGame);
        gAutoLaunchGame = NULL;

        fileXioUmount("pfs0:");
        fileXioDevctl("pfs:", PDIOC_CLOSEALL, NULL, 0, NULL, 0);
    }

    settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_DEV9;
    settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_ATAD;

    // adjust ZSO cache
    settings->common.zso_cache = hddCacheSize;

    sysLaunchLoaderElf(filename, "HDD_MODE", size_irx, irx, size_mcemu_irx, hdd_mcemu_irx, EnablePS2Logo, compatMode);
}

static config_set_t *hddGetConfig(item_list_t *itemList, int id)
{
    char path[256];

    // VCD (PS1) view: `id` indexes hddVcdGames, NOT hddGames (which stays at its zero/ISO-view state --
    // {games=NULL,count=0} on a PS1-only HDD). Mirror the other VCD-aware accessors and key the per-game
    // CFG off the VCD basename, instead of dereferencing &hddGames.games[id] off a NULL base (crash).
    if (vcdViewActive(itemList->mode)) {
        base_game_info_t *g = &hddVcdGames[id];
        snprintf(path, sizeof(path), "%sCFG/%s.cfg", gHDDPrefix, g->name);
        config_set_t *vcdConfig = configAlloc(0, NULL, path);
        configRead(vcdConfig);
        configSetStr(vcdConfig, CONFIG_ITEM_NAME, g->name);
        configSetStr(vcdConfig, CONFIG_ITEM_STARTUP, g->name);
        // HDD bypasses sbPopulateConfig, so set the #System/#Media/#DiscType badge attributes via the
        // shared helper (FR #49) -- a POPS disc is always a PS1 CD. Without it those badges never render.
        sbSetDiscAttributes(vcdConfig, 1, 1);
        return vcdConfig;
    }

    hdl_game_info_t *game = &hddGames.games[id];

    snprintf(path, sizeof(path), "%sCFG/%s.cfg", gHDDPrefix, game->startup);
    config_set_t *config = configAlloc(0, NULL, path);
    configRead(config); // Does not matter if the config file exists or not.

    configSetStr(config, CONFIG_ITEM_NAME, game->name);
    configSetInt(config, CONFIG_ITEM_SIZE, game->total_size_in_kb >> 10);
    configSetStr(config, CONFIG_ITEM_FORMAT, "HDL");
    // HDD bypasses sbPopulateConfig, so set #System/#Media/#DiscType via the shared helper (FR #49) --
    // without it a theme's #DiscType / #System AttributeImage badge never rendered on HDD games. HDL
    // titles are always PS2; reuse game->disctype for the CD-vs-DVD axis.
    sbSetDiscAttributes(config, 0, game->disctype == SCECdPS2CD);
    configSetStr(config, CONFIG_ITEM_STARTUP, game->startup);

    return config;
}

static int hddGetImage(item_list_t *itemList, char *folder, int isRelative, char *value, char *suffix, GSTEXTURE *resultTex, short psm)
{
    char path[256];

    // VCD (PS1) covers: fall back disc-id -> filename in the OPL ART folder. POPSLoader's HDD layout keeps
    // art on the __common partition (POPS/ART/<name>.png), a different partition than gHDDPrefix, so that
    // step is a follow-up -- pass NULL to skip it rather than probe the wrong partition.
    // VCD covers live at the APA partition ROOT /ART/ (pfs0:/ART/, whatever partition is mounted --
    // common or +OPL), NOT the OPL data subfolder. pfs0: is already mounted while browsing, so no remount.
    if (isRelative && vcdViewActive(itemList->mode) && (!strcmp(suffix, "COV") || !strcmp(suffix, "ICO")))
        return vcdLoadArt("pfs0:/", '/', folder, value, suffix, NULL, resultTex);

    if (isRelative)
        snprintf(path, sizeof(path), "%s%s/%s_%s", gHDDPrefix, folder, value, suffix);
    else
        snprintf(path, sizeof(path), "%s%s_%s", folder, value, suffix);
    return texDiscoverLoad(resultTex, path, -1);
}

static int hddGetTextId(item_list_t *itemList)
{
    return _STR_HDD_GAMES;
}

static int hddGetIconId(item_list_t *itemList)
{
    return HDD_ICON;
}

// This may be called, even if hddInit() was not.
static void hddCleanUp(item_list_t *itemList, int exception)
{
    LOG("HDDSUPPORT CleanUp\n");

    if (hddGameList.enabled) {
        hddFreeHDLGamelist(&hddGames);
        hddFreeVcdGameList();

        if ((exception & UNMOUNT_EXCEPTION) == 0)
            fileXioUmount(hddPrefix);
    }

    // UI may have loaded modules outside of HDD mode, so deinitialize regardless of the enabled status.
    if (hddSupportModulesLoaded) {
        fileXioDevctl("pfs:", PDIOC_CLOSEALL, NULL, 0, NULL, 0);

        hddSupportModulesLoaded = 0;
    }
}

static int hddCheckVMC(item_list_t *itemList, char *name, int createSize)
{
    return sysCheckVMC(gHDDPrefix, "/", name, createSize, NULL);
}

// This may be called, even if hddInit() was not.
static void hddShutdown(item_list_t *itemList)
{
    LOG("HDDSUPPORT Shutdown\n");

    if (hddGameList.enabled) {
        hddFreeHDLGamelist(&hddGames);
        hddFreeVcdGameList();
        fileXioUmount(hddPrefix);
    }

    // UI may have loaded modules outside of HDD mode, so deinitialize regardless of the enabled status.
    if (hddSupportModulesLoaded) {
        /* Close all files */
        fileXioDevctl("pfs:", PDIOC_CLOSEALL, NULL, 0, NULL, 0);

        hddSupportModulesLoaded = 0;
    }

    if (hddModulesLoadCount > 0) {
        hddModulesLoadCount -= 1;
        if (hddModulesLoadCount == 0) {
            // DEV9 will remain active if ETH is in use, so put the HDD in IDLE state.
            // The HDD should still enter standby state after 21 minutes & 15 seconds, as per the ATAD defaults.
            hddSetIdleImmediate();
        }

        // Only shut down dev9 from here, if it was initialized from here before -- and only on a
        // TERMINAL teardown (exit/poweroff). On the launch path this shutdown runs for every
        // non-selected page, and powering DEV9 off here kills the ATA bus BEFORE bdmLaunchVcd's
        // post-deinit POPSTARTER.ELF read from the ATA-backed massN: mount -- the elf-loader then
        // returns into deinit'd OPL: the 4236edf6-class black-screen freeze (PCSX2 masks it; its
        // emulated DEV9 power-off is inert). ee_core/POPSTARTER reset the IOP right after, so the
        // launch path needs no power-off. Note the refcount asymmetry this also softens: N
        // hddLoadModules calls take ONE dev9 reference, but every hddShutdown used to drop it.
        if (gDeinitTerminal)
            sysShutdownDev9();
    }
}

static int hddLoadGameListCache(hdl_games_list_t *cache)
{
    char filename[256];
    FILE *file;
    hdl_game_info_t *games;
    int result, size, count;

    if (!gHDDGameListCache)
        return 1;

    hddFreeHDLGamelist(cache);

    sprintf(filename, "%sgames.bin", gHDDPrefix);
    file = fopen(filename, "rb");
    if (file != NULL) {
        fseek(file, 0, SEEK_END);
        size = ftell(file);
        rewind(file);

        count = size / sizeof(hdl_game_info_t);
        if (count > 0) {
            games = memalign(64, count * sizeof(hdl_game_info_t));
            if (games != NULL) {
                if (fread(games, sizeof(hdl_game_info_t), count, file) == count) {
                    cache->count = count;
                    cache->games = games;
                    LOG("hddLoadGameListCache: %d games loaded.\n", count);
                    result = 0;
                } else {
                    LOG("hddLoadGameListCache: I/O error.\n");
                    free(games);
                    result = EIO;
                }
            } else {
                LOG("hddLoadGameListCache: failed to allocate memory.\n");
                result = ENOMEM;
            }
        } else {
            result = -1; // Empty file
        }

        fclose(file);
    } else {
        result = ENOENT;
    }

    return result;
}

static int hddUpdateGameListCache(hdl_games_list_t *cache, hdl_games_list_t *game_list)
{
    char filename[256];
    FILE *file;
    int result, i, j, modified;

    if (!gHDDGameListCache)
        return 1;

    if (cache->count > 0) {
        modified = 0;
        for (i = 0; i < cache->count; i++) {
            for (j = 0; j < game_list->count; j++) {
                if (strncmp(cache->games[i].partition_name, game_list->games[j].partition_name, APA_IDMAX + 1) == 0)
                    break;
            }

            if (j == game_list->count) {
                LOG("hddUpdateGameListCache: game added.\n");
                modified = 1;
                break;
            }
        }

        if ((!modified) && (game_list->count != cache->count)) {
            LOG("hddUpdateGameListCache: game removed.\n");
            modified = 1;
        }
    } else {
        modified = (game_list->count > 0) ? 1 : 0;
    }

    if (!modified)
        return 0;
    LOG("hddUpdateGameListCache: caching new game list.\n");

    sprintf(filename, "%sgames.bin", gHDDPrefix);
    if (game_list->count > 0) {
        file = fopen(filename, "wb");
        if (file != NULL) {
            result = (fwrite(game_list->games, sizeof(hdl_game_info_t), game_list->count, file) == game_list->count) ? 0 : EIO;
            fclose(file);
        } else {
            result = EIO;
        }
    } else {
        // Last game deleted.
        remove(filename);
        result = 0;
    }

    return result;
}

int hddIsPresent()
{
    // the only thing that currently uses ata_device_identify is ATA_DEVCTL_GET_HIGHEST_UDMA_MODE, so this is the best method to check for presence via xhdd (for now anyways)
    // ideally, we'd only have ata_device_identify
    return fileXioDevctl("xhdd0:", ATA_DEVCTL_GET_HIGHEST_UDMA_MODE, NULL, 0, NULL, 0) >= 0;
}

static char *hddGetPrefix(item_list_t *itemList)
{
    return gHDDPrefix;
}

static item_list_t hddGameList = {
    HDD_MODE, 0, 0, MODE_FLAG_COMPAT_DMA, MENU_MIN_INACTIVE_FRAMES, HDD_MODE_UPDATE_DELAY, NULL, NULL, &hddGetTextId, &hddGetPrefix, &hddInit, &hddNeedsUpdate, &hddUpdateGameList,
    &hddGetGameCount, &hddGetGame, &hddGetGameName, &hddGetGameNameLength, &hddGetGameStartup, &hddDeleteGame, &hddRenameGame,
    &hddLaunchGame, &hddGetConfig, &hddGetImage, &hddCleanUp, &hddShutdown, &hddCheckVMC, &hddGetIconId, &hddLaunchVcd};
