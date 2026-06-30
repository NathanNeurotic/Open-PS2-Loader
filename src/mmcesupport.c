#include "include/opl.h"
#include "include/lang.h"
#include "include/gui.h"
#include "include/supportbase.h"
#include "include/mmcesupport.h"
#include "include/vcdsupport.h"
#include "include/util.h"
#include "include/themes.h"
#include "include/textures.h"
#include "include/texcache.h"
#include "include/ioman.h"
#include "include/system.h"
#include "include/extern_irx.h"
#include "include/cheatman.h"
#include "modules/iopcore/common/cdvd_config.h"
#include "../ee_core/include/coreconfig.h"
#include <usbhdfsd-common.h>

#include <kernel.h>
#include <ps2sdkapi.h>
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h> // fileXioIoctl, fileXioDevctl
#include <delaythread.h> // DelayThread() -- real-sleep gap in the MMCE card-switch wait

static char mmcePrefix[40]; // Contains the full path to the folder where all the games are.
static char mmceArtPrimary[40];
static int mmceULSizePrev = -2;
static time_t mmceModifiedCDPrev;
static time_t mmceModifiedDVDPrev;
static int mmceGameCount = 0;
static base_game_info_t *mmceGames;

// Card-switch wait: poll the MMCE busy bit every 500 ms for up to ~7.5 s, matching mmceman's own
// switch handshake. On a CROSS-DEVICE launch (a USB/HDD/SMB game whose per-game card lives on the
// MMCE) the 0x8 push physically switches the SD card, and the launch MUST wait for that to finish --
// otherwise the game boots while the card is still mounting and freezes at its MC check (issue #50,
// cross-device path). A prior change had collapsed the per-poll gap to a sub-ms nopdelay(), which
// gutted the wait so it returned in well under a second; a real sleep restores it.
#define MMCE_GAMEID_WAIT_TICKS    15           // max polls of the card-switch busy bit
#define MMCE_GAMEID_POLL_US       (200 * 1000) // 200 ms between polls -> ~3 s total budget (was 500 ms x 15 = 7.5 s)
/* Allow up to 500 ms for the art thread to drain before resorting to
 * TerminateThread.  The MMCE worker checks the abort flag between every
 * 4 KB read chunk (~16 ms at typical card speeds), so 500 ms covers
 * even very slow cards and avoids the fileXio RPC corruption that
 * TerminateThread can cause mid-read. */
#define MMCE_ART_ABORT_WAIT_TICKS 500

// forward declaration
static item_list_t mmceGameList;
static void mmceGetDeviceRoot(char *root, size_t size);

int mmceSendGameID(const char *startup, const char *protectMcPath)
{
    char mmceDevice[sizeof(mmcePrefix)];

    if (!gMMCEEnableGameID || startup == NULL || startup[0] == '\0')
        return 0;

    // #261 cross-device launches (a USB/HDD/SMB game with the MMCE holding the card) can reach here on a
    // cold boot where the MMCE tab was never opened, so its Start Mode (default Manual) never loaded
    // mmceman. Without mmceman resident the mmce0:/mmce1: devctl probes below all fail and the game-id is
    // silently dropped -> the card never switches to the per-game folder (issue #51). Self-arm the
    // transport here; mmceLoadModules() is idempotent (guarded by mmceModLoaded).
    mmceLoadModules();

    mmceGetDeviceRoot(mmceDevice, sizeof(mmceDevice));
    // Use the resolved slot only if a card is actually present there; otherwise -- no slot resolved
    // (MMCE tab off, the common cross-device case), OR a configured/stale gMMCESlot that is now empty
    // -- probe both slots so a card in EITHER slot still gets the game-id for per-game folder switching
    // on a cross-device (USB/HDD/SMB) launch (#261). The same 0x1 device-present devctl mmceDetectSlot uses.
    if (mmceDevice[0] == '\0' || fileXioDevctl(mmceDevice, 0x1, NULL, 0, NULL, 0) == -1) {
        if (fileXioDevctl("mmce0:/", 0x1, NULL, 0, NULL, 0) != -1)
            snprintf(mmceDevice, sizeof(mmceDevice), "mmce0:/");
        else if (fileXioDevctl("mmce1:/", 0x1, NULL, 0, NULL, 0) != -1)
            snprintf(mmceDevice, sizeof(mmceDevice), "mmce1:/");
        else
            return 0; // no MMCE card present -> graceful no-op
    }

    // NHDDL-parity guard (#51): never switch the per-game card on a slot whose EMULATED memory card
    // (mcN:) holds the neutrino.elf we are about to load -- the 0x8 switch moves the mcN: surface and
    // would yank the loader out from under sysLaunchNeutrino. A neutrino.elf on the MMCE's SD (mmceN:)
    // is NOT affected by the card switch, so only the mcN: case is guarded.
    if (protectMcPath != NULL && protectMcPath[0] != '\0') {
        const char *mc = NULL;
        if (!strncmp(mmceDevice, "mmce0", 5))
            mc = "mc0:";
        else if (!strncmp(mmceDevice, "mmce1", 5))
            mc = "mc1:";
        if (mc != NULL && !strncmp(protectMcPath, mc, strlen(mc)))
            return 0; // neutrino.elf is on this slot's emulated card -- leave the card alone
    }

    if (fileXioDevctl(mmceDevice, 0x8, (void *)startup, (strlen(startup) + 1), NULL, 0) < 0)
        return 0;

    // Wait until the busy bit clears -- i.e. until the physical card has finished switching to the
    // per-game folder. This runs on the single GUI thread BEFORE deinit, so every millisecond here is a
    // frozen loading screen. POLL FIRST, sleep only if still busy: a card that switches instantly (the
    // common case) now costs ~0 ms instead of a guaranteed 500 ms (the old loop slept 500 ms before its
    // first poll, taxing EVERY cross-device launch -- a regression on slow late-slim MC buses). The total
    // budget is generous enough (~3 s) to still cover a slow switch before we launch anyway (#50 race),
    // but no longer the 7.5 s worst case that read as a hard freeze on hardware. Break the instant it clears.
    for (int i = 0; i < MMCE_GAMEID_WAIT_TICKS; i++) {
        int status = fileXioDevctl(mmceDevice, 0x2, NULL, 0, NULL, 0);
        if (status < 0)
            break; // busy-bit query unsupported/failed -> don't block the launch

        if ((status & 1) == 0) {
            LOG("Set MMCE GameID to: %s\n", startup);
            return 1; // card finished switching
        }

        DelayThread(MMCE_GAMEID_POLL_US); // still busy -> wait a short interval, then re-poll
    }

    LOG("MMCE GameID switch did not signal ready within %d ms; launching anyway\n", MMCE_GAMEID_WAIT_TICKS * (MMCE_GAMEID_POLL_US / 1000));
    return 1;
}

static void mmceGetDeviceRoot(char *root, size_t size)
{
    const char *separator = strstr(mmcePrefix, ":/");
    size_t length;

    if (root == NULL || size == 0)
        return;

    if (separator != NULL) {
        length = (size_t)(separator - mmcePrefix) + 2;
        if (length >= size)
            length = size - 1;

        memcpy(root, mmcePrefix, length);
        root[length] = '\0';
        return;
    }

    if (gMMCESlot == 0)
        snprintf(root, size, "mmce0:/");
    else if (gMMCESlot == 1)
        snprintf(root, size, "mmce1:/");
    else
        root[0] = '\0';
}

static void mmceRefreshArtRoots(void)
{
    int len;

    mmceArtPrimary[0] = '\0';

    if (mmcePrefix[0] == '\0')
        return;

    /* Ensure mmcePrefix always ends with '/' so path concatenation is correct
     * (e.g. "mmce0:/CD" -> "mmce0:/CD/" prevents "mmce0:/CDART" paths). */
    len = strlen(mmcePrefix);
    if (len < (int)sizeof(mmcePrefix) - 1 && mmcePrefix[len - 1] != '/') {
        mmcePrefix[len] = '/';
        mmcePrefix[len + 1] = '\0';
    }

    snprintf(mmceArtPrimary, sizeof(mmceArtPrimary), "%s", mmcePrefix);
}

static int mmceTryLoadImage(const char *prefix, char *folder, int isRelative, char *value, char *suffix, GSTEXTURE *resultTex)
{
    char path[256];

    if ((prefix == NULL || prefix[0] == '\0') && isRelative)
        return -1;

    if (isRelative)
        snprintf(path, sizeof(path), "%s%s/%s_%s", prefix, folder, value, suffix);
    else
        snprintf(path, sizeof(path), "%s%s_%s", folder, value, suffix);

    return texDiscoverLoad(resultTex, path, -1);
}

int mmceDetectSlot(void)
{
    int ret = -1;
    if (fileXioDevctl("mmce0:/", 0x1, NULL, 0, NULL, 0) != -1) {
        sprintf(mmcePrefix, "mmce0:/%s", gMMCEPrefix);
        ret = 2;
    } else if (fileXioDevctl("mmce1:/", 0x1, NULL, 0, NULL, 0) != -1) {
        sprintf(mmcePrefix, "mmce1:/%s", gMMCEPrefix);
        ret = 3;
    }
    return ret;
}

void mmceSetPrefix(void)
{
    if (gMMCESlot == 0)
        sprintf(mmcePrefix, "mmce0:/%s", gMMCEPrefix);
    else if (gMMCESlot == 1)
        sprintf(mmcePrefix, "mmce1:/%s", gMMCEPrefix);
    else if (gMMCESlot == 2)
        (void)mmceDetectSlot();

    mmceRefreshArtRoots();
}

static int mmceModLoaded = 0;
void mmceLoadModules(void)
{
    // mmceman is a singleton -- loading the IRX buffer twice creates a 2nd instance. Guard so this is
    // idempotent: mmceInit calls it, and the BDMA equip now also calls it (to wake an MMCE source when
    // MMCE games are off / Manual-not-started). Set the flag first so a partial load can't double-load.
    if (mmceModLoaded)
        return;
    mmceModLoaded = 1;
    LOG("MMCESUPPORT LoadModules\n");
    LOG("[MMCEMAN]:\n");
    sysLoadModuleBuffer(&mmceman_irx, size_mmceman_irx, 0, NULL);
}

void mmceInit(item_list_t *itemList)
{
    LOG("MMCESUPPORT Init\n");
    mmcePrefix[0] = '\0';
    mmceArtPrimary[0] = '\0';
    mmceULSizePrev = -2;
    mmceModifiedCDPrev = 0;
    mmceModifiedDVDPrev = 0;
    mmceGameCount = 0;
    mmceGames = NULL;

    configGetInt(configGetByType(CONFIG_OPL), "usb_frames_delay", &mmceGameList.delay);
    mmceGameList.updateDelay = MMCE_MODE_UPDATE_DELAY;

    mmceLoadModules();
    mmceSetPrefix();

    mmceGameList.enabled = 1;
}

item_list_t *mmceGetObject(int initOnly)
{
    if (initOnly && !mmceGameList.enabled)
        return NULL;
    return &mmceGameList;
}

static int mmceNeedsUpdate(item_list_t *itemList)
{
    static unsigned char ThemesLoaded = 0;
    static unsigned char LanguagesLoaded = 0;

    char path[256];
    int result = 0;
    struct stat st;

    // Hacky: check if slot was changed, update prefix if needed
    mmceSetPrefix();

    if (mmcePrefix[0] == '\0') {
        mmceGameList.updateDelay = MMCE_MODE_UPDATE_DELAY;
        return (mmceGameCount > 0);
    }

    mmceGameList.updateDelay = MENU_UPD_DELAY_NOUPDATE;

    // VCD view: force a rescan once on toggle, then skip the disc heuristics while showing VCDs.
    if (vcdConsumeDirty(itemList->mode))
        return 1;
    if (vcdViewActive(itemList->mode))
        return 0;

    if (mmceULSizePrev == -2)
        result = 1;

    sprintf(path, "%sCD", mmcePrefix);
    if (stat(path, &st) != 0)
        st.st_mtime = 0;

    if (mmceModifiedCDPrev != st.st_mtime) {
        mmceModifiedCDPrev = st.st_mtime;
        result = 1;
    }

    sprintf(path, "%sDVD", mmcePrefix);
    if (stat(path, &st) != 0)
        st.st_mtime = 0;

    if (mmceModifiedDVDPrev != st.st_mtime) {
        mmceModifiedDVDPrev = st.st_mtime;
        result = 1;
    }

    if (!sbIsSameSize(mmcePrefix, mmceULSizePrev))
        result = 1;

    // update Themes
    if (!ThemesLoaded) {
        sprintf(path, "%sTHM", mmcePrefix);
        if (thmAddElements(path, "/", 1) > 0)
            ThemesLoaded = 1;
    }

    // update Languages
    if (!LanguagesLoaded) {
        sprintf(path, "%sLNG", mmcePrefix);
        if (lngAddLanguages(path, "/", mmceGameList.mode) > 0)
            LanguagesLoaded = 1;
    }

    sbCreateFolders(mmcePrefix, 1);

    return result;
}

static int mmceUpdateGameList(item_list_t *itemList)
{
    if (mmcePrefix[0] == '\0')
        return mmceGameCount;

    if (vcdViewActive(itemList->mode))
        mmceGameCount = vcdFillGameList(mmcePrefix, &mmceGames);
    else
        sbReadList(&mmceGames, mmcePrefix, &mmceULSizePrev, &mmceGameCount);
    return mmceGameCount;
}

static int mmceGetGameCount(item_list_t *itemList)
{
    return mmceGameCount;
}

static void *mmceGetGame(item_list_t *itemList, int id)
{
    return (void *)&mmceGames[id];
}

static char *mmceGetGameName(item_list_t *itemList, int id)
{
    return mmceGames[id].name;
}

static int mmceGetGameNameLength(item_list_t *itemList, int id)
{
    return ((mmceGames[id].format != GAME_FORMAT_USBLD) ? ISO_GAME_NAME_MAX + 1 : UL_GAME_NAME_MAX + 1);
}

static char *mmceGetGameStartup(item_list_t *itemList, int id)
{
    // VCD view keys per-game data (CFG/art) off the VCD filename, not a disc ID (see sbPopulateConfig).
    if (vcdViewActive(itemList->mode))
        return mmceGames[id].name;
    return mmceGames[id].startup;
}

static void mmceDeleteGame(item_list_t *itemList, int id)
{
    sbDelete(&mmceGames, mmcePrefix, "/", mmceGameCount, id);
    mmceULSizePrev = -2;
}

static void mmceRenameGame(item_list_t *itemList, int id, char *newName)
{
    sbRename(&mmceGames, mmcePrefix, "/", mmceGameCount, id, newName);
    mmceULSizePrev = -2;
}

// Launch a PS1/.VCD entry BY NAME via POPSTARTER (view-independent entry point: the in-view menu
// launch below and the Favourites tab both use it). mmcePrefix is static; UNMOUNT_EXCEPTION keeps the
// MMCE device mounted across the IOP reset.
static void mmceLaunchVcd(item_list_t *itemList, const char *vcdName, config_set_t *configSet)
{
    char vcdElf[256], vcdSelector[320];

    if (vcdName == NULL || vcdName[0] == '\0' || !strcmp(vcdName, "POPSTARTER"))
        return;
    if (!vcdResolvePopstarter(mmcePrefix, vcdElf, sizeof(vcdElf))) {
        guiMsgBox(_l(_STR_POPSTARTER_NOT_FOUND), 0, NULL);
        return;
    }
    vcdBuildSelector(mmcePrefix, VCD_PREFIX_MASS, vcdName, vcdSelector, sizeof(vcdSelector));
    // POPSTARTER reloads its driver from the MC after its own IOP reset -> ensure the .mmce BDMAssault
    // variant is equipped first, or it can't mount the MMCE drive (-> OSDSYS).
    vcdEnsureBdmaForLaunch(VCD_BDMA_SRC_MMCE, VCD_BDMA_MMCE);
    deinit(UNMOUNT_EXCEPTION, itemList->mode); // keep the MMCE device mounted across the IOP reset
    sysLaunchPopstarter(vcdElf, vcdSelector, "");
}

void mmceLaunchGame(item_list_t *itemList, int id, config_set_t *configSet)
{
    int i, index, compatmask = 0;
    int EnablePS2Logo = 0;
    int result;

    char partname[256], filename[32];
    base_game_info_t *game;
    struct cdvdman_settings_mmce *settings;
    u32 layer1_start, layer1_offset;
    unsigned short int layer1_part;

    // No Autolaunch yet
    if (gAutoLaunchBDMGame == NULL)
        game = &mmceGames[id];
    else
        game = gAutoLaunchBDMGame;

    // VCD view: hand off to POPSTARTER (by name) instead of the disc path below. Menu-launch only.
    if (gAutoLaunchBDMGame == NULL && game != NULL && vcdViewActive(itemList->mode)) {
        mmceLaunchVcd(itemList, game->name, configSet);
        return;
    }

    if (!cacheAbortMmceImageLoadsTimed(MMCE_ART_ABORT_WAIT_TICKS)) {
        cacheEnd(1);
        cacheInit();
    }

    void *irx = &mmce_cdvdman_irx;
    int irx_size = size_mmce_cdvdman_irx;
    compatmask = sbPrepare(game, configSet, irx_size, irx, &index);
    settings = (struct cdvdman_settings_mmce *)((u8 *)irx + index);
    if (settings == NULL)
        return;

    char vmc_name[32];
    char vmc_path[256];
    int vmc_size_mb;
    int vmc_id, size_mcemu_irx = 0;
    int vmc_fd;
    int vmc_fds[2] = {-1, -1}; // track VMC fds to close on the Neutrino handoff path (B3)
    mmce_vmc_infos_t mmce_vmc_infos;
    vmc_superblock_t vmc_superblock;

    for (vmc_id = 0; vmc_id < 2; vmc_id++) {
        memset(&mmce_vmc_infos, 0, sizeof(mmce_vmc_infos));
        configGetVMC(configSet, vmc_name, sizeof(vmc_name), vmc_id);
        if (vmc_name[0]) {
            vmc_size_mb = sysCheckVMC(mmcePrefix, "/", vmc_name, 0, &vmc_superblock);
            if (vmc_size_mb > 0) {
                mmce_vmc_infos.flags = vmc_superblock.mc_flag & 0xFF;
                mmce_vmc_infos.flags |= 0x100;
                mmce_vmc_infos.specs.page_size = vmc_superblock.page_size;
                mmce_vmc_infos.specs.block_size = vmc_superblock.pages_per_block;
                mmce_vmc_infos.specs.card_size = vmc_superblock.pages_per_cluster * vmc_superblock.clusters_per_card;

                sprintf(vmc_path, "%sVMC/%s.bin", mmcePrefix, vmc_name);

                vmc_fd = fileXioOpen(vmc_path, 0x3, 0666);
                if (vmc_fd >= 0) {
                    vmc_fds[vmc_id] = vmc_fd;
                    mmce_vmc_infos.fd = fileXioIoctl2(vmc_fd, 0x80, NULL, 0, NULL, 0);
                    mmce_vmc_infos.active = 1;
                }
            }
        }

        for (i = 0; i < size_mmce_mcemu_irx; i++) {
            if (((u32 *)&mmce_mcemu_irx)[i] == (0xC0DEFAC0 + vmc_id)) {
                if (mmce_vmc_infos.active)
                    size_mcemu_irx = size_mmce_mcemu_irx;
                memcpy(&((u32 *)&mmce_mcemu_irx)[i], &mmce_vmc_infos, sizeof(mmce_vmc_infos_t));
                break;
            }
        }
    }

    // Initialize layer 1 information.
    sbCreatePath(game, partname, mmcePrefix, "/", 0);

    if (gPS2Logo) {
        int fd = open(partname, O_RDONLY, 0666);
        if (fd >= 0) {
            EnablePS2Logo = CheckPS2Logo(fd, 0);
            close(fd);
        }
    }

    layer1_start = sbGetISO9660MaxLBA(partname);

    switch (game->format) {
        case GAME_FORMAT_USBLD:
            layer1_part = layer1_start / 0x80000;
            layer1_offset = layer1_start % 0x80000;
            sbCreatePath(game, partname, mmcePrefix, "/", layer1_part);
            break;
        default: // Raw ISO9660 disc image; one part.
            layer1_part = 0;
            layer1_offset = layer1_start;
    }

    if (sbProbeISO9660(partname, game, layer1_offset) != 0) {
        layer1_start = 0;
        LOG("DVD detected.\n");
    } else {
        layer1_start -= 16;
        LOG("DVD-DL layer 1 @ part %u sector 0x%lx.\n", layer1_part, layer1_offset);
    }
    settings->common.layer1_start = layer1_start;

    if ((result = sbLoadCheats(mmcePrefix, game->startup)) < 0) {
        if (gAutoLaunchBDMGame == NULL) {
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
    sbLoadImage(mmcePrefix, game->startup);

    if (gRememberLastPlayed) {
        configSetStr(configGetByType(CONFIG_LAST), "last_played", game->startup);
        saveConfig(CONFIG_LAST, 0);
    }

    if (configGetStrCopy(configSet, CONFIG_ITEM_ALTSTARTUP, filename, sizeof(filename)) == 0)
        strcpy(filename, game->startup);


    // MMCEDRV settings
    if (gMMCESlot == 0)
        settings->port = 2;
    else if (gMMCESlot == 1)
        settings->port = 3;
    else if (gMMCESlot == 2) {
        int detectedPort = mmceDetectSlot();
        if (detectedPort < 0) {
            // Neither slot responded; abort rather than forward port -1 to the IOP.
            LOG("MMCE slot lost, aborting launch\n");
            // Close the VMC fds opened above so a failed launch does not leak them
            // back to the menu across repeated attempts (Codex audit, Medium 2).
            if (vmc_fds[0] >= 0)
                fileXioClose(vmc_fds[0]);
            if (vmc_fds[1] >= 0)
                fileXioClose(vmc_fds[1]);
            return;
        }
        settings->port = detectedPort;
        // Re-apply trailing-slash normalization: mmceDetectSlot() rewrites
        // mmcePrefix via sprintf with no slash append, de-normalizing the
        // value mmceRefreshArtRoots() previously set. sbBuildVmcNeutrinoArgs
        // (called below) builds "-mcN=<prefix>VMC/<name>.bin" and requires
        // mmcePrefix to end in '/' -- without this call a non-empty gMMCEPrefix
        // (e.g. "GAMES") produces the broken path "mmce0:/GAMESVMC/<name>.bin".
        mmceRefreshArtRoots();
    }

    // Per-game Neutrino core: gate BEFORE opening iso_file so no fd is leaked on
    // the Neutrino path (game is still valid here for the format check).
    int coreLoader = 0;
    configGetInt(configSet, CONFIG_ITEM_CORE_LOADER, &coreLoader);
    const char *neutrinoPath = NULL;
    char neutrinoExtraArgs[256] = "";      // per-game Neutrino flags; copied before deinit teardown
    int neutrinoVideo = 0;                 // per-game Neutrino -gsm video mode; copied before deinit
    neutrino_vmc_args_t neutrinoVmc = {0}; // per-game VMC -mc args; resolved before deinit, lives on this stack frame across the launch (#47)
    if (coreLoader) {
        configGetStrCopy(configSet, CONFIG_ITEM_NEUTRINO_ARGS, neutrinoExtraArgs, sizeof(neutrinoExtraArgs));
        configGetInt(configSet, CONFIG_ITEM_NEUTRINO_VIDEO, &neutrinoVideo);
        neutrinoPath = sbResolveNeutrinoPath(mmcePrefix); // #300: AUTO also probes this MMCE card for a co-located neutrino.elf
        if (game->format == GAME_FORMAT_USBLD || !strcasecmp(game->extension, ".zso")) {
            // isValidIsoName() admits .zso case-insensitively and game->extension is stored
            // verbatim, so an upper/mixed-case ".ZSO" must reject here too (Neutrino can't run it).
            guiWarning(_l(_STR_NEUTRINO_BAD_FORMAT), 6);
            coreLoader = 0;
        } else if (neutrinoPath == NULL) {
            guiWarning(_l(_STR_NEUTRINO_NOT_FOUND), 6);
            coreLoader = 0;
        }

        // VMC -> neutrino (#47): resolve any per-game VMC into discrete -mc0/-mc1 argv entries
        // (mmcePrefix ends in '/'); not the whitespace-tokenized extra-args buffer (spaced names).
        if (coreLoader)
            sbBuildVmcNeutrinoArgs(configSet, mmcePrefix, &neutrinoVmc);
    }
    if (coreLoader) {
        char mmcePartname[256];
        snprintf(mmcePartname, sizeof(mmcePartname), "%s", partname); // defensive copy across the deinit teardown (partname is a stack buffer, not freed by deinit)
        // Neutrino bypasses OPL's mcemu, so the VMC fds opened above go unused on
        // this path — close them instead of leaking until the IOP reset (B3).
        if (vmc_fds[0] >= 0)
            fileXioClose(vmc_fds[0]);
        if (vmc_fds[1] >= 0)
            fileXioClose(vmc_fds[1]);
        // Keep the device that holds neutrino.elf mounted (UNMOUNT_EXCEPTION) so LoadELFFromFile can
        // read it post-teardown -- apps do the same. mc-hosted neutrino (mode -1) survives any deinit.
        int neutrinoDevMode = oplPath2Mode(neutrinoPath);
        if (neutrinoDevMode >= 0)
            deinit(UNMOUNT_EXCEPTION, neutrinoDevMode);
        else
            deinit(NO_EXCEPTION, MMCE_MODE);
        sysLaunchNeutrino("mmce", mmcePartname, compatmask, EnablePS2Logo, neutrinoPath, neutrinoExtraArgs, neutrinoVideo, &neutrinoVmc);
        return;
    }

    int iso_file = fileXioOpen(partname, 0x1, 0666);
    if (iso_file < 0) {
        LOG("Failed to open iso, aborting\n");
        // Same VMC-fd leak guard as the slot-lost path above (Codex audit, Medium 2).
        if (vmc_fds[0] >= 0)
            fileXioClose(vmc_fds[0]);
        if (vmc_fds[1] >= 0)
            fileXioClose(vmc_fds[1]);
        return;
    }

    settings->ack_wait_cycles = gMMCEAckWaitCycles;
    settings->use_alarms = gMMCEUseAlarms;

    // TEMP: The fd given by sd2psx is not the same one we see here on the EE
    // and ps2sdk_get_iop_fd does not seem to return the right value either
    settings->iso_fd = fileXioIoctl2(iso_file, 0x80, NULL, 0, NULL, 0);

    LOG("name: %s\n", game->name);
    LOG("start: %s\n", game->startup);

    // Issue #50: do NOT push a launcher GameID on the NATIVE MMCE launch. For a game ON the MMCE, the
    // in-game card is handled by OPL's mcemu (the VMC fds above), so a SET_GAMEID here is at best
    // redundant -- and it re-switches the physical card mid-launch, so a game that probes the memory
    // card early boots before the re-mount finishes and FREEZES (regressed beta 2257 -> 2813; reported by
    // ramonesfm, SCPH-30001 + PSxMemCard Gen2). The cross-device paths (bdm/hdd/eth) STILL send it,
    // because there the MMCE can't see the boot device's id and must be told which per-game folder to use.

    // mcReset();
    // mcInit(MC_TYPE_XMC);

    if (gAutoLaunchBDMGame == NULL) {
        deinit(NO_EXCEPTION, MMCE_MODE); // CAREFUL: deinit will call mmceCleanUp, so mmceGames/game will be freed
    }

    /* No autolaunch yet
    else {
        miniDeinit(configSet);

        free(gAutoLaunchBDMGame);
        gAutoLaunchBDMGame = NULL;
    }*/

    settings->common.zso_cache = 0;

    sysLaunchLoaderElf(filename, "MMCE_MODE", irx_size, irx, size_mcemu_irx, mmce_mcemu_irx, EnablePS2Logo, compatmask);
}

static config_set_t *mmceGetConfig(item_list_t *itemList, int id)
{
    return sbPopulateConfig(&mmceGames[id], mmcePrefix, "/");
}

static int mmceGetImage(item_list_t *itemList, char *folder, int isRelative, char *value, char *suffix, GSTEXTURE *resultTex, short psm)
{
    // VCD (PS1) covers: fall back disc-id -> filename -> POPSLoader's next-to-VCD <dev>/POPS/<name>.png.
    if (isRelative && mmceArtPrimary[0] != '\0' && vcdViewActive(itemList->mode) && (!strcmp(suffix, "COV") || !strcmp(suffix, "ICO")))
        return vcdLoadArt(mmceArtPrimary, '/', folder, value, suffix, "POPS", resultTex);

    return mmceTryLoadImage(mmceArtPrimary, folder, isRelative, value, suffix, resultTex);
}

static int mmceGetTextId(item_list_t *itemList)
{
    int mode = _STR_MMCE_GAMES;

    return mode;
}

static int mmceGetIconId(item_list_t *itemList)
{
    int mode = MMCE_ICON;

    return mode;
}

// This may be called, even if mmceInit() was not.
static void mmceCleanUp(item_list_t *itemList, int exception)
{
    if (mmceGameList.enabled) {
        LOG("MMCESUPPORT CleanUp\n");

        free(mmceGames);

        //      if ((exception & UNMOUNT_EXCEPTION) == 0)
        //          ...
    }
}

// This may be called, even if mmceInit() was not.
static void mmceShutdown(item_list_t *itemList)
{
    if (mmceGameList.enabled) {
        LOG("MMCESUPPORT Shutdown\n");

        free(mmceGames);
    }

    // As required by some (typically 2.5") HDDs, issue the SCSI STOP UNIT command to avoid causing an emergency park.
    // fileXioDevctl("mass:", USBMASS_DEVCTL_STOP_ALL, NULL, 0, NULL, 0);
}

static int mmceCheckVMC(item_list_t *itemList, char *name, int createSize)
{
    return sysCheckVMC(mmcePrefix, "/", name, createSize, NULL);
}

static char *mmceGetPrefix(item_list_t *itemList)
{
    return mmcePrefix;
}

static item_list_t mmceGameList = {
    MMCE_MODE, 2, 0, 0, MENU_MIN_INACTIVE_FRAMES, MMCE_MODE_UPDATE_DELAY, NULL, NULL, &mmceGetTextId, &mmceGetPrefix, &mmceInit, &mmceNeedsUpdate,
    &mmceUpdateGameList, &mmceGetGameCount, &mmceGetGame, &mmceGetGameName, &mmceGetGameNameLength, &mmceGetGameStartup, &mmceDeleteGame, &mmceRenameGame,
    &mmceLaunchGame, &mmceGetConfig, &mmceGetImage, &mmceCleanUp, &mmceShutdown, &mmceCheckVMC, &mmceGetIconId, &mmceLaunchVcd};
