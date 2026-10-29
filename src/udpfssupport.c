#include "include/opl.h"
#include "include/saveicon.h"
#include "include/lang.h"
#include "include/gui.h"
#include "include/supportbase.h"
#include "include/udpfssupport.h"
#include "include/cuesupport.h"
#include "include/vcdsupport.h"
#include "include/libview.h" // libViewActive / libListViewActive -- which list this page shows
#include "include/folderbrowse.h"
#include "include/util.h"
#include "include/renderman.h"
#include "include/themes.h"
#include "include/textures.h"
#include "include/texcache.h"
#include "include/artindex.h"
#include "include/ioman.h"
#include "include/system.h"
#include "include/extern_irx.h"
#include "include/cheatman.h"
#include "include/ethsupport.h"  // ethGetModulesLoaded() for the UDPFS<->SMB NIC interlock
#include "include/bdmsupport.h"  // bdmIsUDPBDLoaded() for the UDPFS<->UDPBD NIC interlock
#include "include/mmcesupport.h" // mmceSendGameID() cross-device game-id (#261)
#include "modules/iopcore/common/cdvd_config.h"

#include <ps2sdkapi.h>
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h>
#include <delaythread.h>
#include <errno.h>

// udpfs is a network FILESYSTEM device: the iomanX device "udpfs:" is served by the udpfs_ioman IRX
// chain (smap -> ministack(ip=) -> udpfs_ioman). Games are read straight off "udpfs:/". They boot through
// the external Neutrino core by default, like the "udp" BDM transport in bdmsupport.c; a game whose own
// Loader Core is <OPL> boots the OPL core with udpfs_cdvdman, which reads the ISO in game through
// udpfs_fhi by the server handle the menu kept open (udpfsLaunchOplCore).
static char udpfsPrefix[40]; // full path to the folder that holds all the games ("udpfs:/")
static char *udpfsBase;      // device root ("udpfs:")
static int udpfsIsoScanned = 0;
static time_t udpfsModifiedCDPrev;
static time_t udpfsModifiedDVDPrev;
static int udpfsGameCount = 0;
static base_game_info_t *udpfsGames = NULL;
static int udpfsPs1GameCount = 0;
static base_game_info_t *udpfsPs1Games = NULL;
static int udpfsIomanModLoaded = 0;
static int udpfsNicClaimed = 0;       // SMAP resident, even if later modules fail; requires IOP reset
static int udpfsWaitingForServer = 0; // the last scan got no answer from the server; see udpfsSetWaitingForServer
static int udpfsThemesScanned = 0;    // THM is registered once per active UDPFS session, after THM opens
static int udpfsLanguagesScanned = 0; // LNG uses the shared registry once its directory becomes readable
static int udpfsPs1Scanned = 0;       // a PS1-view scan has reached the server this session; see udpfsNeedsUpdate

// Another device answering for this PS2's IP (udpfs_ioman devctl, value shared with udpfs_ioman.c).
// The scan runs on the IO thread, but guiWarning draws, so the scan only queues the text and the GUI
// thread shows it (udpfsShowPendingNotice, from the menu frame hook). Once per boot.
#define UDPFS_DEVCTL_IP_CONFLICT 0x55460001
static int udpfsIpConflictWarned = 0;
static volatile int udpfsIpConflictNotice = 0;
static char udpfsIpConflictText[320];

// UDPFS shares may be case-sensitive. These are immutable strings: the art worker reads
// only a small index, which the list worker publishes once after the server answers.
// No root scans, directory probes or string-case searches occur on the per-image hot path.
static const char *const udpfsArtCaseNames[8] = {
    "ART", "ARt", "ArT", "Art", "aRT", "aRt", "arT", "art"};
static volatile unsigned int udpfsArtCaseIndex = 0;
static int udpfsArtCaseChecked = 0;

// forward declaration
static item_list_t udpfsGameList;
static void udpfsDiscoverArtFolder(void);

// Load the UDPFS ioman IRX chain ONCE per boot. Mirrors bdmsupport's udpfs_bd chain load
// (bdmLoadBlockDeviceModules), but loads udpfs_ioman (the FILESYSTEM variant) instead of udpfs_bd (the
// BLOCK-device variant): smap (exports to ministack + ioman) -> ministack (gets the "ip=" arg) ->
// udpfs_ioman (registers the "udpfs:" iomanX device).
//
// SOCKET-ONCE: the ministack has no udp_unbind, so this is load-once -- never DelDrv+re-AddDrv and never
// re-load (a re-bind of the UDPRDMA socket bricks UDPFS after a few cycles). Once udpfsIomanModLoaded is
// set it stays set for the life of the boot.
static void udpfsLoadModules(void)
{
    char ipArg[24];

    LOG("UDPFSSUPPORT LoadModules\n");

    if (udpfsIomanModLoaded)
        return;
    if (udpfsNicClaimed) {
        LOG("UDPFSSUPPORT: partial NIC chain resident, requires IOP reset\n");
        return;
    }

    // NIC-exclusivity: the SMAP adapter registers a single "SMAP_driver". The SMB/ETH stack and the
    // UDPBD/udpfs_bd block chain both own it, so refuse to bring up the UDPFS ioman stack on top of
    // either. The Device-hub UI already interlocks these; this is the runtime backstop.
    if (ethGetModulesLoaded()) {
        LOG("UDPFSSUPPORT: SMB NIC active -- not loading the UDPFS ioman stack\n");
        return;
    }
    if (bdmIsUDPBDLoaded()) {
        LOG("UDPFSSUPPORT: UDPBD/udpfs_bd active -- not loading the UDPFS ioman stack\n");
        return;
    }

    // dev9 is refcounted (shared with ATA-HDD). The ministack has no DHCP client, so it needs the PS2's
    // static IP as an "ip=A.B.C.D" arg -- built exactly as bdmsupport does for the udpfs_bd chain.
    // Without DEV9 there is no adapter for SMAP to drive. Refuse before loading anything, like
    // Launchstation, so a failed DEV9 is retried next time instead of leaving a half-claimed NIC.
    if (!sysInitDev9()) {
        LOG("UDPFSSUPPORT: DEV9 failed to initialize -- not loading the UDPFS ioman stack\n");
        sysShutdownDev9();
        return;
    }
    snprintf(ipArg, sizeof(ipArg), "ip=%d.%d.%d.%d", ps2_ip[0], ps2_ip[1], ps2_ip[2], ps2_ip[3]);

    LOG("[UDPFS_SMAP]:\n");
    if (sysLoadModuleBuffer(&udpfs_smap_irx, size_udpfs_smap_irx, 0, NULL) >= 0) {
        udpfsNicClaimed = 1; // first loaded SMAP owns NIC even after partial failure
        LOG("[UDPFS_MINISTACK]:\n");
        if (sysLoadModuleBuffer(&udpfs_ministack_irx, size_udpfs_ministack_irx, (int)strlen(ipArg) + 1, ipArg) >= 0) {
            LOG("[UDPFS_IOMAN]:\n");
            if (sysLoadModuleBuffer(&udpfs_ioman_irx, size_udpfs_ioman_irx, 0, NULL) >= 0) {
                udpfsIomanModLoaded = 1;
                LOG("UDPFSSUPPORT Modules loaded\n");
                return;
            }
        }
    }

    // Release DEV9 only if SMAP never loaded. A partially initialized SMAP
    // still requires DEV9 and cannot safely be replaced without IOP reset.
    LOG("UDPFSSUPPORT: module chain failed to load\n");
    if (!udpfsNicClaimed)
        sysShutdownDev9();
}

// An in-menu IOP reset unloads every module; forget the latches so the next refresh loads them again.
// Ported from RIPPS2 build 115 (akilluminati47/RIPPS2).
void udpfsIopWasReset(void)
{
    udpfsIomanModLoaded = udpfsNicClaimed = 0;
}

int udpfsGetModulesLoaded(void)
{
    return udpfsNicClaimed; // NIC interlock must catch partial module loads
}

int udpfsEnsureReady(u32 timeoutMs)
{
    u64 start;

    if (ethGetModulesLoaded() || bdmIsUDPBDLoaded())
        return 0;

    if (!udpfsIomanModLoaded)
        udpfsLoadModules();
    if (!udpfsIomanModLoaded)
        return 0;

    // A healthy, already-connected server returns on the first probe. A just-loaded ioman session
    // can need a short discovery window, so only the explicit custom-path request pays this wait.
    start = GetTimerSystemTime();
    do {
        struct stat st;
        if (stat("udpfs:/", &st) == 0)
            return 1;
        if ((GetTimerSystemTime() - start) / (kBUSCLK / 1000) >= timeoutMs)
            break;
        DelayThread(100 * 1000);
    } while (1);

    return 0;
}

// True when the server answers. While the udpfs_ioman session is down, every call fails inside the IOP
// before anything reaches the network, so this is cheap enough to poll.
static int udpfsServerAnswers(void)
{
    struct stat st;

    return stat(udpfsPrefix, &st) == 0;
}

// The server is silent. If another device has answered ARP for this PS2's IP, the server's replies
// go to that device: say so once, with the address and the other device's MAC, instead of leaving an
// empty list. The query is answered inside the IOP without network traffic.
static void udpfsCheckIpConflict(void)
{
    static unsigned char mac[64] __attribute__((aligned(64)));

    if (udpfsIpConflictWarned || !udpfsIomanModLoaded)
        return;
    if (fileXioDevctl("udpfs:", UDPFS_DEVCTL_IP_CONFLICT, NULL, 0, mac, 6) != 1)
        return;
    udpfsIpConflictWarned = 1;
    snprintf(udpfsIpConflictText, sizeof(udpfsIpConflictText), "%s\n%d.%d.%d.%d  /  %02X:%02X:%02X:%02X:%02X:%02X",
             _l(_STR_UDPFS_IP_CONFLICT), ps2_ip[0], ps2_ip[1], ps2_ip[2], ps2_ip[3],
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    LOG("UDPFSSUPPORT: IP conflict -- %s\n", udpfsIpConflictText);
    udpfsIpConflictNotice = 1;
}

void udpfsShowPendingNotice(void)
{
    if (!udpfsIpConflictNotice)
        return;
    udpfsIpConflictNotice = 0;
    guiWarning(udpfsIpConflictText, 10);
}

// Without Automatic Refresh (off by default) this page is scanned when it first comes up and on SELECT,
// nothing else. udpfs_ioman connects in the background, so a first scan that ran before the server
// answered -- server started after the console, slow link negotiation, server restarted -- left the page
// empty for good, and the server log showed DISCOVERY and nothing after it. While waiting, poll through
// the every-frame background path (2 s throttle, idle only, yields to cover art) and rescan the moment the
// server answers; once a scan reaches it, go back to the normal cadence.
static void udpfsSetWaitingForServer(int waiting)
{
    udpfsWaitingForServer = waiting;
    // Keep the lightweight background poll alive until THM, LNG and ART resolution complete.
    // The server root/game folders can become usable before those asset folders; without this,
    // a failed first attempt drops back to the normal cadence and, with Automatic Refresh off,
    // is never retried for the rest of the session. ART belongs here for the same reason (#1036):
    // a game list published by a scan that started before the server answered never ran art
    // discovery, and nothing else re-arms it once this cadence lapses.
    udpfsGameList.updateDelay = (waiting || !udpfsThemesScanned || !udpfsLanguagesScanned || !udpfsArtCaseChecked) ? MENU_UPD_DELAY_GENREFRESH : UDPFS_MODE_UPDATE_DELAY;
}

void udpfsInit(item_list_t *itemList)
{
    LOG("UDPFSSUPPORT Init\n");

    // A settings re-apply can re-enter this initializer while UDPFS themes are already registered.
    // Remove only the old udpfs:-backed entries before scanning the refreshed server again, matching
    // SMB's reconnect behavior and avoiding duplicate theme names in the picker.
    if (udpfsBase != NULL)
        thmReinit(udpfsBase);

    udpfsBase = "udpfs:";
    udpfsThemesScanned = 0;
    udpfsLanguagesScanned = 0;
    udpfsPs1Scanned = 0;
    udpfsArtCaseIndex = 0;
    udpfsArtCaseChecked = 0;
    // The games live directly at the device root; no share/prefix to prepend (unlike SMB).
    snprintf(udpfsPrefix, sizeof(udpfsPrefix), "udpfs:/");
    udpfsIsoScanned = 0;
    udpfsModifiedCDPrev = 0;
    udpfsModifiedDVDPrev = 0;
    udpfsGameCount = 0;
    udpfsGames = NULL;
    udpfsPs1GameCount = 0;
    udpfsPs1Games = NULL;
    udpfsGameList.delay = gArtDelay;
    udpfsSetWaitingForServer(0);
    ioPutRequest(IO_CUSTOM_SIMPLEACTION, &udpfsLoadModules);
    udpfsGameList.enabled = 1;
}

item_list_t *udpfsGetObject(int initOnly)
{
    if (initOnly && !udpfsGameList.enabled)
        return NULL;
    return &udpfsGameList;
}

// Keep the PS2 and Ember lists physically separate. Besides making forced-view/Favorites proxies
// unambiguous, this prevents a transient first Ember scan failure from exposing stale PS2 rows on
// the PS1 page. A network PS1 page is therefore Ember-only even in its failure state.
static int udpfsGetItemView(item_list_t *itemList, int id)
{
    int view = libListViewActive(itemList);
    if (view == LIB_VIEW_MIXED)
        return id >= 0 && id < udpfsGameCount ? LIB_VIEW_ISO : LIB_VIEW_PS1;
    return view;
}

static int udpfsGetSourceId(item_list_t *itemList, int id)
{
    return libListViewActive(itemList) == LIB_VIEW_MIXED && id >= udpfsGameCount ? id - udpfsGameCount : id;
}

static int udpfsActiveGameCount(const item_list_t *itemList)
{
    int view = libListViewActive(itemList);
    return view == LIB_VIEW_MIXED ? udpfsGameCount + udpfsPs1GameCount :
           view == LIB_VIEW_PS1   ? udpfsPs1GameCount :
                                    udpfsGameCount;
}

// Resolve every row through one bounds-checked sentinel, matching the BDM support's split-list
// guard. L3 now stages its destination until the old submenu is cleared, but an unscanned, failed,
// partial, or teardown refresh can still leave either array NULL/shorter than a stale id.
static base_game_info_t udpfsEmptyGame = {0};
static base_game_info_t *udpfsActiveGame(item_list_t *itemList, int id)
{
    int ps1 = udpfsGetItemView(itemList, id) == LIB_VIEW_PS1;
    id = udpfsGetSourceId(itemList, id);
    base_game_info_t *games = ps1 ? udpfsPs1Games : udpfsGames;
    int count = ps1 ? udpfsPs1GameCount : udpfsGameCount;

    if (games == NULL || id < 0 || id >= count)
        return &udpfsEmptyGame;
    return &games[id];
}

// Theme discovery used to be missing entirely from the UDPFS filesystem backend: BDM, MMCE, SMB and
// APA all register their THM directories when the device becomes usable, while UDPFS only scanned
// games/art. Once the server-backed root actually answers, register udpfs:/THM exactly once for this
// session. thmAddElements(..., forceRefresh=1) also reapplies a saved UDPFS theme as soon as it
// appears.
//
// Do NOT latch merely because the root answered. listDir()/thmAddElements() returns 0 both for an
// existing-but-empty THM directory and for a directory that could not be opened at all. On Auto boot
// the root/game paths can win that race before THM is ready; latching that failed attempt made themes
// disappear for the whole session. Probe THM itself first. A successful open (even if empty) is the
// proof that completes discovery; a failed open keeps the lightweight background retry armed.
//
// ANY CASE. The share is a PC folder, and on a case-sensitive server (Linux) "thm" and "THM" are two
// different folders. Worse, sbCreateFolders makes an empty "THM" beside a user's "thm", and a fixed
// "THM" open then found that empty one and latched with no themes. So list the root and scan every
// folder whose name is THM in any case -- an empty auto-created one costs nothing.
static void udpfsDiscoverThemes(void)
{
    char themePath[128];
    DIR *root, *dir;
    struct dirent *entry;
    int found = 0;

    if (udpfsThemesScanned || !udpfsIomanModLoaded || !udpfsServerAnswers())
        return;

    root = opendir(udpfsPrefix);
    if (root == NULL)
        return;
    while ((entry = readdir(root)) != NULL) {
        if (strcasecmp(entry->d_name, "THM") != 0)
            continue;
        snprintf(themePath, sizeof(themePath), "%s%s", udpfsPrefix, entry->d_name);
        dir = opendir(themePath); // a directory, whatever d_type the driver reports
        if (dir == NULL)
            continue;
        closedir(dir);
        thmAddElements(themePath, "/", 1);
        found = 1;
    }
    closedir(root);

    if (!found)
        return;
    udpfsThemesScanned = 1;
    // If server-waiting is already clear, retire the temporary general-refresh cadence now that
    // theme discovery really completed. If the server is still considered down, preserve that wait.
    udpfsSetWaitingForServer(udpfsWaitingForServer);
}

// Match the shared LNG registration used by SMB/BDM/MMCE/HDD. Scan every case
// variant so an empty auto-created LNG cannot hide an existing populated lng.
// Failed root enumeration or an inaccessible matching directory keeps retrying.
static void udpfsDiscoverLanguages(void)
{
    char path[128];
    DIR *root, *dir;
    struct dirent *entry;
    int found = 0, failed = 0, error;

    if (udpfsLanguagesScanned || !udpfsIomanModLoaded || !udpfsServerAnswers())
        return;
    root = opendir(udpfsPrefix);
    if (root == NULL)
        return;
    for (;;) {
        errno = 0;
        entry = readdir(root);
        if (entry == NULL) {
            error = errno;
            break;
        }
        if (strcasecmp(entry->d_name, "LNG") != 0)
            continue;
        snprintf(path, sizeof(path), "%s%s", udpfsPrefix, entry->d_name);
        dir = opendir(path);
        if (dir == NULL) {
            failed = 1;
            continue;
        }
        closedir(dir);
        lngAddLanguages(path, "/", udpfsGameList.mode);
        found = 1;
    }
    closedir(root);
    if (!found || failed || error)
        return;
    udpfsLanguagesScanned = 1;
    udpfsSetWaitingForServer(udpfsWaitingForServer);
}

static int udpfsNeedsUpdate(item_list_t *itemList)
{
    int result = 0;

    // Keep this before every view-specific early return so a remembered PS1/Ember page cannot
    // suppress theme, language or ART discovery. ART resolution used to run only inside
    // udpfsUpdateGameList, so it had no retry independent of a full list rebuild (#1036).
    udpfsDiscoverThemes();
    udpfsDiscoverLanguages();
    udpfsDiscoverArtFolder();

    // PS1/Ember view: force a rescan once on toggle, then refresh on toggle only (skip disc heuristics).
    if (libViewConsumeDirty(itemList->mode))
        return 1;
    // Folder browsing: descend/ascend forces one rescan.
    if (folderConsumeDirty(itemList->mode))
        return 1;
    // Waiting for the server: rescan only once it answers, so an unreachable server costs one failed stat
    // per poll instead of an empty rebuild every two seconds. Ahead of the PS1 early-out so Ember heals too.
    if (udpfsWaitingForServer)
        return udpfsServerAnswers();
    // The PS1 view refreshes on L3 / SELECT only -- but it must still get its FIRST scan. A page
    // restored onto a remembered PS1 view (Remember Last Played on an Ember title) otherwise returned
    // here forever and stayed blank until the user toggled L3 (TwistedZeon, 09-29). MMCE and BDM
    // build that first list the same way (mmcePs1Scanned; bdmNeedsUpdate's connect pass).
    if (libListViewActive(itemList) == LIB_VIEW_PS1)
        return !udpfsPs1Scanned;

    if (!udpfsIsoScanned)
        result = 1;

    // Only stat the mount once the ioman device is actually up -- statting "udpfs:/..." before then
    // just fails and would keep result at 0 anyway, but guard it to avoid pointless RPC churn.
    if (udpfsIomanModLoaded) {
        struct stat st;
        char path[256];

        snprintf(path, sizeof(path), "%sCD", udpfsPrefix);
        if (stat(path, &st) != 0)
            st.st_mtime = 0;
        if (udpfsModifiedCDPrev != st.st_mtime) {
            udpfsModifiedCDPrev = st.st_mtime;
            result = 1;
        }

        snprintf(path, sizeof(path), "%sDVD", udpfsPrefix);
        if (stat(path, &st) != 0)
            st.st_mtime = 0;
        if (udpfsModifiedDVDPrev != st.st_mtime) {
            udpfsModifiedDVDPrev = st.st_mtime;
            result = 1;
        }
    }

    return result;
}

// Check the remote share's ART spelling once after its root can be fully enumerated.
// The ordinary path remains udpfs:/ART, including on newly created shares. If a
// case-sensitive server has both an empty auto-created ART and a populated art,
// use the populated directory instead. Collision probes happen only at discovery.
static int udpfsArtFolderHasFiles(unsigned int variant)
{
    char path[64];
    DIR *dir;
    struct dirent *entry;
    int found = 0;

    snprintf(path, sizeof(path), "%s%s", udpfsPrefix, udpfsArtCaseNames[variant]);
    dir = opendir(path);
    if (dir == NULL)
        return -1; // root entry may be a file named "art", not a directory
    for (;;) {
        errno = 0;
        entry = readdir(dir);
        if (entry == NULL) {
            if (errno != 0)
                found = -2; // transient read failure; discovery must retry
            break;
        }
        if (entry->d_name[0] != '.') {
            found = 1;
            break;
        }
    }
    closedir(dir);
    return found;
}

static void udpfsDiscoverArtFolder(void)
{
    DIR *root;
    struct dirent *entry;
    unsigned int candidates = 0;
    unsigned int chosen = 0;
    int readError;

    if (udpfsArtCaseChecked || !udpfsIomanModLoaded || !udpfsServerAnswers())
        return;

    root = opendir(udpfsPrefix);
    if (root == NULL)
        return;

    for (;;) {
        errno = 0;
        if ((entry = readdir(root)) == NULL)
            break;
        if (strlen(entry->d_name) == 3 && strcasecmp(entry->d_name, "ART") == 0) {
            for (unsigned int i = 0; i < 8; i++) {
                if (strcmp(entry->d_name, udpfsArtCaseNames[i]) == 0) {
                    candidates |= 1u << i;
                    break;
                }
            }
        }
    }
    readError = errno;
    closedir(root);
    if (readError != 0)
        return; // incomplete root enumeration must not become a permanent resolution

    // Prefer the conventional spelling unless it is empty and another spelling is
    // populated. A single ART folder requires no extra directory opens at all.
    if (candidates != 0 && !(candidates & 1u)) {
        for (unsigned int i = 1; i < 8; i++) {
            if (candidates & (1u << i)) {
                chosen = i;
                break;
            }
        }
    }
    if (candidates && (candidates & (candidates - 1u))) {
        int chosenState = udpfsArtFolderHasFiles(chosen);
        if (chosenState == -2)
            return;
        if (chosenState <= 0) {
            unsigned int fallback = chosenState == 0 ? chosen : 0;
            int haveFallback = chosenState == 0;
            int foundPopulated = 0;
            for (unsigned int i = 0; i < 8; i++) {
                if (i == chosen || !(candidates & (1u << i)))
                    continue;
                int candidateState = udpfsArtFolderHasFiles(i);
                if (candidateState == -2)
                    return;
                if (candidateState > 0) {
                    chosen = i;
                    foundPopulated = 1;
                    break;
                }
                if (candidateState == 0 && !haveFallback) {
                    fallback = i;
                    haveFallback = 1;
                }
            }
            if (!foundPopulated)
                chosen = haveFallback ? fallback : 0;
        }
    }

    // For a single noncanonical entry, verify that it is actually a directory.
    // d_type is unreliable over this filesystem, so an open probe is necessary.
    // The common canonical ART path still takes no additional directory open.
    if (chosen != 0 && !(candidates & (candidates - 1u))) {
        int chosenState = udpfsArtFolderHasFiles(chosen);
        if (chosenState == -2)
            return;
        if (chosenState < 0)
            chosen = 0;
    }

    udpfsArtCaseChecked = 1;
    udpfsArtCaseIndex = chosen;
    // First-connect probes can memoize missing covers or an unavailable directory before
    // discovery runs. Re-arm both once, even when the selected spelling stays uppercase ART.
    cacheInvalidateFailMemo();
    artIndexInvalidate();
    // If server-waiting is already clear, retire the temporary general-refresh cadence now that
    // ART resolution really completed (mirrors udpfsDiscoverThemes/Languages).
    udpfsSetWaitingForServer(udpfsWaitingForServer);
}

static int udpfsFoldersCreated = 0;

static int udpfsUpdateGameList(item_list_t *itemList)
{
    int view = libListViewActive(itemList);
    int reached = 0;
    int answeredBefore;
    if (udpfsIomanModLoaded == 0)
        return udpfsActiveGameCount(itemList);

    // Asked BEFORE scanning: a scan that started while the server was not answering cannot be trusted
    // even when it "succeeds" -- the Ember scan reports an unreachable server as "no titles" -- so
    // such a pass always keeps polling, and the next poll rescans once the server answers.
    answeredBefore = udpfsServerAnswers();

    // Resolve an existing lowercase ART before sbCreateFolders creates an empty ART
    // beside it. This one-time discovery never runs from the art worker.
    if (answeredBefore)
        udpfsDiscoverArtFolder();

    // Latch only once the server can hear us. A scan that ran before it answered used to latch here, so
    // the CD/DVD folders were never created for the rest of the boot.
    if (!udpfsFoldersCreated && answeredBefore) {
        sbCreateFolders(udpfsPrefix, 1);
        udpfsFoldersCreated = 1;
    }

    // Folder creation includes THM. Discover only AFTER that pass so a fresh share gets the same
    // chance as one that already contained THM; udpfsDiscoverThemes itself refuses to latch a failed
    // directory open and leaves the background retry cadence armed.
    if (answeredBefore)
        udpfsDiscoverThemes();
    if (answeredBefore)
        udpfsDiscoverLanguages();

    if (view == LIB_VIEW_PS1 || view == LIB_VIEW_MIXED) {
        // POPSTARTER uses the UDPFS BDMA pair after reset; Ember inherits this mount.
        int r = ps1FillGameList(udpfsPrefix, &udpfsPs1Games);
        if (answeredBefore && r >= 0 && !ps1GameListNeedsRetry())
            udpfsPs1Scanned = 1;
        if (r >= 0) // r < 0: transient scan failure -> preserve the last-good list
            udpfsPs1GameCount = r;
    }
    if (view == LIB_VIEW_ISO || view == LIB_VIEW_MIXED) {
        // Neutrino launches disc images, not USBExtreme split parts. Avoid even
        // probing ul.cfg on the network share, and never publish unlaunchable UL rows.
        if (sbReadList(&udpfsGames, udpfsPrefix, folderGetSub(itemList->mode), NULL, &udpfsGameCount) < 0) {
            // A failed CD/DVD scan is not an empty library. Keep the last-good
            // games and retry on the regular idle refresh until a folder opens.
            udpfsIsoScanned = 0;
        } else {
            reached = 1;
            // An offline first pass is retried by udpfsWaitingForServer.
            udpfsIsoScanned = answeredBefore;
        }
    }
    // Only a readable CD/DVD scan proves the server answered. A share without those folders, or the PS1
    // view (whose empty result can't tell "no titles" from "no answer"), asks the server itself before
    // deciding to wait -- otherwise a working server would be polled and rescanned every two seconds.
    udpfsSetWaitingForServer(!answeredBefore || (!reached && !udpfsServerAnswers()));
    if (udpfsWaitingForServer)
        udpfsCheckIpConflict();
    return udpfsActiveGameCount(itemList);
}

static int udpfsGetGameCount(item_list_t *itemList)
{
    return udpfsActiveGameCount(itemList);
}

static void *udpfsGetGame(item_list_t *itemList, int id)
{
    return (void *)udpfsActiveGame(itemList, id);
}

static char *udpfsGetGameName(item_list_t *itemList, int id)
{
    return udpfsActiveGame(itemList, id)->name;
}

static int udpfsGetGameNameLength(item_list_t *itemList, int id)
{
    if (udpfsActiveGame(itemList, id)->format != GAME_FORMAT_USBLD)
        return ISO_GAME_NAME_MAX + 1;
    else
        return UL_GAME_NAME_MAX + 1;
}

static char *udpfsGetGameStartup(item_list_t *itemList, int id)
{
    base_game_info_t *game = udpfsActiveGame(itemList, id);

    // VCD view keys per-game data (CFG/art) off the VCD filename, not a disc ID (see sbPopulateConfig).
    if (udpfsGetItemView(itemList, id) == LIB_VIEW_PS1)
        return game->name;
    return game->startup;
}

static void udpfsDeleteGame(item_list_t *itemList, int id)
{
    if (udpfsGetItemView(itemList, id) == LIB_VIEW_PS1)
        return; // PS1 rows are Ember folders, not CD/DVD images for sbDelete
    if (udpfsActiveGame(itemList, id) == &udpfsEmptyGame)
        return;
    sbSetBrowseSub(folderGetSub(itemList->mode)); // delete inside the current subfolder, not the root
    id = udpfsGetSourceId(itemList, id);
    sbDelete(&udpfsGames, udpfsPrefix, "/", udpfsGameCount, id);
    udpfsIsoScanned = 0;
}

static void udpfsRenameGame(item_list_t *itemList, int id, char *newName)
{
    if (udpfsGetItemView(itemList, id) == LIB_VIEW_PS1) {
        base_game_info_t *game = udpfsActiveGame(itemList, id);
        if (game != &udpfsEmptyGame && cueIsCueEntry(game) && cueRenameGame(udpfsPrefix, game->name, newName) == 0)
            libViewMarkDirty(itemList->mode); // the already-queued menu update must re-scan EMBER/games
        return;
    }
    if (udpfsActiveGame(itemList, id) == &udpfsEmptyGame)
        return;
    id = udpfsGetSourceId(itemList, id);
    sbSetBrowseSub(folderGetSub(itemList->mode)); // rename inside the current subfolder, not the root
    sbRename(&udpfsGames, udpfsPrefix, "/", udpfsGameCount, id, newName);
    udpfsIsoScanned = 0;
}

// One handoff for the UDPFS page and Favorites, using the existing BDMA equip.
static void udpfsLaunchVcd(item_list_t *itemList, const char *vcdName, config_set_t *configSet)
{
    char elf[256], selector[320], vcdPath[320];
    const int mode = VCD_BDMA_UDPFS;
    (void)configSet;
    if (vcdName == NULL || vcdName[0] == '\0' || !strcasecmp(vcdName, "POPSTARTER"))
        return;
    // Linux servers are case-sensitive and this IRX only accepts uppercase .VCD. Without one, UDPFS
    // Assault builds the VCD from POPS/<game>.cue (or .CUE) and its .bin files on the fly.
    snprintf(vcdPath, sizeof(vcdPath), "%sPOPS/%s.VCD", udpfsPrefix, vcdName);
    int fd = open(vcdPath, O_RDONLY);
    if (fd < 0) {
        static const char *const cueExt[] = {".cue", ".CUE"};
        char cuePath[320];
        int k;
        for (k = 0; k < 2 && fd < 0; k++) {
            snprintf(cuePath, sizeof(cuePath), "%sPOPS/%s%s", udpfsPrefix, vcdName, cueExt[k]);
            fd = open(cuePath, O_RDONLY);
        }
        if (fd < 0) {
            guiMsgBoxMissing(_l(_STR_ERR_FILE_INVALID), vcdPath);
            return;
        }
    }
    close(fd);
    if (!vcdResolvePopstarter(udpfsPrefix, elf, sizeof(elf))) {
        vcdDescribePopstarterLookup(udpfsPrefix, elf, sizeof(elf));
        guiMsgBoxMissing(_l(_STR_POPSTARTER_NOT_FOUND), elf);
        return;
    }
    guiRenderTextScreen(_l(_STR_PLEASE_WAIT));
    (void)vcdInstallPopstarterMc(udpfsPrefix);
    char popsDir[96], diag[160];
    snprintf(popsDir, sizeof(popsDir), "%s" POPS_FOLDER "/", udpfsPrefix);
    int er = vcdInstallPopsUdpfsNet(popsDir);
    if (er != 0) {
        guiMsgBox(_l(er == -2 ? _STR_BDMA_ERR_SPACE : _STR_BDMA_ERR_IO), 0, NULL);
        return;
    }
    if (gBdmaApplyOnLaunch && !vcdBdmaLaunchReady(mode)) {
        er = vcdEquipBdmaFromPops(popsDir, mode, diag, sizeof(diag));
        if (er != 0) {
            guiMsgBox(_l(er == -5 ? _STR_BDMA_ERR_OLD : er == -4 ? _STR_BDMA_ERR_SRC :
                                                    er == -2     ? _STR_BDMA_ERR_SPACE :
                                                                   _STR_BDMA_ERR_IO),
                      0, NULL);
            return;
        }
    }
    if (!vcdBdmaLaunchReady(mode)) {
        // Unlike local POPSTARTER, network VCDs require this exact driver family.
        guiMsgBox(_l(_STR_POPS_UDPFS_DRIVER_NOT_READY), 0, NULL);
        return;
    }
    // POPS UDPFS has no RA integration yet. Do not leave our USB-only RA module
    // reading a network VCD through unsupported telemetry hooks.
    if (!vcdConfirmCleanLaunch(udpfsPrefix))
        return;
    vcdBuildSelector(udpfsPrefix, VCD_PREFIX_MASS, vcdName, selector, sizeof(selector));
    vcdPrepareRetroGemBarcode(vcdPath);
    deinitEx(sbLoaderDeinitException(elf), itemList->mode, oplPath2Mode(elf));
    sysLaunchPopstarter(elf, selector);
}

// Ember over UDPFS. Ember performs no IOP reset, so it inherits the live udpfs: filesystem and can
// read both its own ELF and EMBER/games/<name>/ from the connection already mounted by RiptOPL.
static void udpfsLaunchCue(item_list_t *itemList, const char *cueName, config_set_t *configSet)
{
    char emberElf[256], biosPath[288];
    char launchName[CUE_NAME_MAX];

    if (cueName == NULL || cueName[0] == '\0')
        return;
    if (!cueNameLaunchable(cueName)) {
        guiMsgBox(_l(_STR_EMBER_BAD_NAME), 0, NULL);
        return;
    }
    if (!cueResolveEmber(udpfsPrefix, emberElf, sizeof(emberElf))) {
        guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), emberElf); // the resolvers leave the tried path
        return;
    }
    if (!cueResolveEmberBios(udpfsPrefix, biosPath, sizeof(biosPath))) {
        guiMsgBoxMissing(_l(_STR_EMBER_BIOS_MISSING), biosPath);
        return;
    }
    if (!guiPrepareEmberLaunch(udpfsPrefix, cueName, emberElf, launchName, sizeof(launchName)))
        return;

    cueApplySettings(udpfsPrefix, cueName, configSet); // best-effort marker, never a launch gate
    if (!cueGameHasImage(udpfsPrefix, cueName)) {
        guiMsgBox(_l(_STR_EMBER_NO_DISC), 0, NULL);
        return;
    }

    // The prepared argument is owned on our stack; cleanup frees udpfsPs1Games during deinit.
    cuePrepareRetroGemBarcode(udpfsPrefix, cueName);

    // UNMOUNT_EXCEPTION is load-bearing: Ember inherits this live mount. udpfsCleanUp keeps the
    // socket/module chain resident for the whole boot, so no network reinitialization is attempted.
    deinit(UNMOUNT_EXCEPTION, itemList->mode);
    sysLaunchEmber(emberElf, launchName);
}

// The OPL core for a UDPFS Files game. The ISO stays open on udpfs_ioman across the IOP reset (nothing in
// the teardown closes it, and the reset itself sends the server nothing), and cdvdman gets the server's
// handle for it. After the reset the EE core loads udpfs_smap, udpfs_ministack and udpfs_fhi; udpfs_fhi
// re-discovers the server, which keeps a peer's open handles across a re-discovery (udpfsd
// Connection.ResetPeer), and reads the disc by that handle. This is how Neutrino's own udpfs_fhi boots
// these games. A game's VMCs are kept open read-write the same way, and udpfs_mcemu reads and writes
// their pages through udpfs_fhi, so saves land on the server.
static int udpfsMcemuSlots[2] = {-2, -2};

// Close what the launch opened when it goes back to the menu (a launch that goes on keeps them open).
static void udpfsCloseFiles(int isoFile, const int *vmcFiles)
{
    int i;

    for (i = 0; i < 2; i++)
        if (vmcFiles[i] >= 0)
            fileXioClose(vmcFiles[i]);
    if (isoFile >= 0)
        fileXioClose(isoFile);
}

static void udpfsLaunchOplCore(item_list_t *itemList, base_game_info_t *game, config_set_t *configSet)
{
    int index, compatmask, result;
    int EnablePS2Logo = 0;
    char partname[256], filename[32];
    struct cdvdman_settings_udpfs *settings;
    u32 layer1_start;
    void *irx = &udpfs_cdvdman_irx;
    int irx_size = size_udpfs_cdvdman_irx;
    char vmc_name[2][32];
    int vmc_id, size_mcemu_irx = 0, vmcMask = 0;
    int vmc_files[2] = {-1, -1};
    udpfs_vmc_infos_t vmc_infos[2];
    vmc_superblock_t vmc_superblock;

    // VMCs first, before any state is prepared: a card that is missing or bad may still be declined.
    memset(vmc_infos, 0, sizeof(vmc_infos));
    for (vmc_id = 0; vmc_id < 2; vmc_id++) {
        configGetVMC(configSet, vmc_name[vmc_id], sizeof(vmc_name[vmc_id]), vmc_id);
        if (!vmc_name[vmc_id][0])
            continue;
        if (sysCheckVMC(udpfsPrefix, "/", vmc_name[vmc_id], 0, &vmc_superblock) > 0) {
            vmc_infos[vmc_id].flags = (vmc_superblock.mc_flag & 0xFF) | 0x100;
            vmc_infos[vmc_id].specs.page_size = vmc_superblock.page_size;
            vmc_infos[vmc_id].specs.block_size = vmc_superblock.pages_per_block;
            vmc_infos[vmc_id].specs.card_size = vmc_superblock.pages_per_cluster * vmc_superblock.clusters_per_card;
            vmc_infos[vmc_id].active = 1;
        } else {
            char error[256];
            snprintf(error, sizeof(error), _l(_STR_ERR_VMC_CONTINUE), vmc_name[vmc_id], (vmc_id + 1));
            if (!guiMsgBox(error, 1, NULL))
                return;
        }
    }

    compatmask = sbPrepare(game, configSet, irx_size, irx, &index);
    if (compatmask < 0) // patch zone not found: `index` is unset
        return;
    settings = (struct cdvdman_settings_udpfs *)((u8 *)irx + index);
    sbEnsureIgrUsbDrivers(compatmask);

    // One file: the scan lists no split (UL) games here. Its size bounds cdvdman's out-of-range reads
    // (sbGetMediaLsnCount); an unknown size keeps the driver on the PVD.
    sbCreatePath(game, partname, udpfsPrefix, "/", 0);
    u64 isoBytes = 0;
    int fd = open(partname, O_RDONLY, 0666);
    if (fd >= 0) {
        s64 bytes = lseek64(fd, 0, SEEK_END);
        if (bytes > 0)
            isoBytes = (u64)bytes;
        close(fd);
    }
    if (gPS2Logo) {
        fd = open(partname, O_RDONLY, 0666);
        if (fd >= 0) {
            EnablePS2Logo = CheckPS2Logo(fd, 0);
            close(fd);
        }
    }

    layer1_start = sbGetISO9660MaxLBA(partname);
    settings->common.mediaLsnCount = sbGetMediaLsnCount(partname, isoBytes);
    if (sbProbeISO9660(partname, game, layer1_start) != 0) {
        layer1_start = 0;
        LOG("DVD detected.\n");
    } else {
        layer1_start -= 16;
        LOG("DVD-DL layer 1 @ sector 0x%lx.\n", layer1_start);
    }
    settings->common.layer1_start = layer1_start;
    settings->common.zso_cache = bdmCacheSize; // the UDPFS IMG native leg's cache (bdmsupport.c)

    // No RetroAchievements here: udpfs_fhi owns the adapter in game (sysModeHasNoRATelemetry).
    if ((result = sbLoadCheats(udpfsPrefix, game->startup, configSet)) < 0) {
        // The helper does the sbUnprepare itself (include/supportbase.h).
        if (!sbCheatsMissingContinue(&settings->common, result))
            return;
    }
    sbLoadImage(udpfsPrefix, game->startup);

    if (configGetStrCopy(configSet, CONFIG_ITEM_ALTSTARTUP, filename, sizeof(filename)) == 0)
        strcpy(filename, game->startup);

    // Opened last, so every way back to the menu above leaves no handle behind. Never closed: the
    // server's handle is the game's disc until the console is reset.
    int iso_file = fileXioOpen(partname, 0x1, 0666); // iomanX FIO_O_RDONLY (newlib O_RDONLY is 0)
    int iso_handle = iso_file >= 0 ? fileXioIoctl2(iso_file, 0x80, NULL, 0, NULL, 0) : -1;
    if (iso_handle < 0) {
        LOG("UDPFSSUPPORT: cannot open %s for the OPL core (fd %d, handle %d)\n", partname, iso_file, iso_handle);
        udpfsCloseFiles(iso_file, vmc_files);
        guiWarning(_l(_STR_ERR_FILE_INVALID), 8);
        sbUnprepare(&settings->common);
        return;
    }
    settings->iso_handle = iso_handle;

    // Each VMC is opened read-write (iomanX FIO_O_RDWR) and kept open the same way, so udpfs_mcemu can
    // write saves to it in game. udpfsd refuses a write open on a read-only share or a file already
    // open elsewhere: that card is then offered to be skipped, as a bad card is above.
    for (vmc_id = 0; vmc_id < 2; vmc_id++) {
        if (vmc_infos[vmc_id].active) {
            char vmc_path[256];
            snprintf(vmc_path, sizeof(vmc_path), "%sVMC/%s.bin", udpfsPrefix, vmc_name[vmc_id]);
            vmc_files[vmc_id] = fileXioOpen(vmc_path, 0x3, 0666);
            vmc_infos[vmc_id].fd = vmc_files[vmc_id] >= 0 ? fileXioIoctl2(vmc_files[vmc_id], 0x80, NULL, 0, NULL, 0) : -1;
            if (vmc_infos[vmc_id].fd < 0) {
                char error[256];
                LOG("UDPFSSUPPORT: cannot open %s read-write (fd %d, handle %d)\n", vmc_path, vmc_files[vmc_id], vmc_infos[vmc_id].fd);
                if (vmc_files[vmc_id] >= 0)
                    fileXioClose(vmc_files[vmc_id]);
                vmc_files[vmc_id] = -1;
                memset(&vmc_infos[vmc_id], 0, sizeof(vmc_infos[vmc_id]));
                snprintf(error, sizeof(error), _l(_STR_ERR_VMC_CONTINUE), vmc_name[vmc_id], (vmc_id + 1));
                if (!guiMsgBox(error, 1, NULL)) {
                    udpfsCloseFiles(iso_file, vmc_files);
                    sbUnprepare(&settings->common);
                    return;
                }
            } else
                vmcMask |= 1 << vmc_id;
        }

        // This write covers the slot's marker, so its position is found once and reused (sbMcemuSlotWord).
        int slotWord = sbMcemuSlotWord(&udpfs_mcemu_irx, size_udpfs_mcemu_irx, vmc_id, udpfsMcemuSlots);
        if (slotWord >= 0) {
            if (vmc_infos[vmc_id].active)
                size_mcemu_irx = size_udpfs_mcemu_irx;
            memcpy(&((u32 *)&udpfs_mcemu_irx)[slotWord], &vmc_infos[vmc_id], sizeof(udpfs_vmc_infos_t));
        }
    }

    // MMCE cross-device game-id (#261), before deinit frees `game`; slots with a VMC keep their card.
    mmceSendGameID(game->startup, NULL, vmcMask);

    // udpfsCleanUp leaves the udpfs_ioman chain (and with it the open ISO) alone.
    deinit(NO_EXCEPTION, itemList->mode); // CAREFUL: frees the game lists, and with them `game`

    // udpfs_fhi owns the network adapter in game: the game's own DEV9 and SMAP are faked, as for UDPBD.
    settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_DEV9;
    settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_SMAP;
    sysLaunchLoaderElf(filename, "UDPFS_MODE", irx_size, irx, size_mcemu_irx, udpfs_mcemu_irx, EnablePS2Logo, compatmask);
}

static void udpfsLaunchGame(item_list_t *itemList, int id, config_set_t *configSet)
{
    int compatmask = 0, index;
    int EnablePS2Logo = 0;
    int result;
    char filename[32], partname[256];
    base_game_info_t *game = udpfsActiveGame(itemList, id);

    if (game == &udpfsEmptyGame)
        return; // stale/invalid id

    // Folder browsing: a folder row is never launched (the dispatch descends first); guard defensively
    // and pin the path composers to the current subfolder so a nested game resolves.
    if (game != NULL && game->format == GAME_FORMAT_FOLDER)
        return;
    sbSetBrowseSub(folderGetSub(itemList->mode));

    // Dispatch the mixed PS1 library by the selected row's core.
    if (game != NULL && (udpfsGetItemView(itemList, id) == LIB_VIEW_PS1)) {
        if (cueIsCueEntry(game))
            udpfsLaunchCue(itemList, game->name, configSet);
        else
            udpfsLaunchVcd(itemList, game->name, configSet);
        return;
    }

    // Neutrino by default; the OPL core when the game's own Loader Core is <OPL> (bdmNetBlockCoreLoader),
    // or when Neutrino cannot run it (no neutrino.elf, a .zso image), as on the udp BDM device and MMCE.
    // NB: Neutrino's VMC emulation is emitted as discrete -mcN args (sbBuildVmcNeutrinoArgs below); the
    // OPL core leg uses udpfs_mcemu (udpfsLaunchOplCore).

    if (gRememberLastPlayed) {
        configSetStr(configGetByType(CONFIG_LAST), "last_played", game->startup);
        saveConfig(CONFIG_LAST, 0);
    }

    // The scan lists no USBExtreme (UL) split games; neither core reads split parts from this device.
    if (game->format == GAME_FORMAT_USBLD) {
        guiWarning(_l(_STR_ERR_FILE_INVALID), 6);
        return;
    }
    // Resolved while `game`/`configSet` are still valid -- deinit frees them.
    const char *neutrinoPath = NULL;
    int coreLoader = bdmNetBlockCoreLoader(configSet);
    if (coreLoader) {
        neutrinoPath = sbResolveNeutrinoPath(udpfsPrefix);
        if (!strcasecmp(game->extension, ".zso")) {
            // game->extension is stored verbatim, so ".ZSO" must reject here too.
            guiWarning(_l(_STR_NEUTRINO_BAD_FORMAT), 6);
            coreLoader = 0;
        } else if (neutrinoPath == NULL) {
            guiWarning(_l(_STR_NEUTRINO_NOT_FOUND), 6);
            coreLoader = 0;
        }
    }
    if (!coreLoader) {
        udpfsLaunchOplCore(itemList, game, configSet);
        return;
    }

    // sbPrepare resolves the per-game compat mask (and per-game pad-emu etc.). The Neutrino leg does not
    // patch an OPL cdvdman IRX, but sbPrepare still needs a valid buffer to locate the patch zone; reuse
    // the smb cdvdman image as a scratch target (its patched fields are never launched here -- only the
    // returned compatmask is used).
    compatmask = sbPrepare(game, configSet, size_smb_cdvdman_irx, smb_cdvdman_irx, &index);
    if (compatmask < 0)
        return;
    compatmask = sbGetCompatModes(configSet, 1); // this leg launches Neutrino, and a title default can differ per core

    if ((result = sbLoadCheats(udpfsPrefix, game->startup, configSet)) < 0) {
        // #265: let the user back out instead of sitting through the whole load. The helper does
        // the sbUnprepare itself -- see include/supportbase.h; skipping it breaks the NEXT launch.
        // udpfs never assigns `settings` (Neutrino reads the game, not an OPL cdvdman), but
        // sbPrepare still patched smb_cdvdman_irx, so the unwind is required all the same.
        if (!sbCheatsMissingContinue((u8 *)(&smb_cdvdman_irx) + index, result))
            return;
    }
    // The scratch patch has done its job (the compat mask, and the cheats step's way back out above).
    // Restore the zone NOW, so every return below -- format, no neutrino.elf, the preflights, the
    // cheats hand-off -- leaves it pristine: smb_cdvdman_irx is the SMB leg's IRX too, and a zone left
    // patched fails the next SMB or UDPFS launch's sbPrepare ("unable to locate patch zone").
    sbUnprepare((u8 *)(&smb_cdvdman_irx) + index);
    sbLoadImage(udpfsPrefix, game->startup);

    if (gPS2Logo) {
        int fd;
        sbCreatePath(game, partname, udpfsPrefix, "/", 0);
        fd = open(partname, O_RDONLY, 0666);
        if (fd >= 0) {
            EnablePS2Logo = CheckPS2Logo(fd, 0);
            close(fd);
        }
    }

    if (configGetStrCopy(configSet, CONFIG_ITEM_ALTSTARTUP, filename, sizeof(filename)) == 0)
        strcpy(filename, game->startup);

    // Per-game Neutrino flags, resolved BEFORE deinit frees configSet's owner (neutrino.elf was above).
    char neutrinoExtraArgs[256] = "";
    int neutrinoVideo = gNeutrinoVideoDefault, neutrinoGsmComp = gNeutrinoGsmCompDefault; // absent per-game keys = follow the globals
    neutrino_vmc_args_t neutrinoVmc = {0};

    configGetStrCopy(configSet, CONFIG_ITEM_NEUTRINO_ARGS, neutrinoExtraArgs, sizeof(neutrinoExtraArgs));
    configGetInt(configSet, CONFIG_ITEM_NEUTRINO_VIDEO, &neutrinoVideo);
    configGetInt(configSet, CONFIG_ITEM_NEUTRINO_GSMCOMP, &neutrinoGsmComp);

    // VMC -> neutrino (#47): resolve any per-game VMC into discrete -mc0/-mc1 argv entries before deinit.
    sbBuildVmcNeutrinoArgs(configSet, udpfsPrefix, &neutrinoVmc);

    // Build the filesystem device path Neutrino reads the game from. This is a plausible, correct-shaped
    // -dvd target (the udpfs: filesystem game file); a follow-up stage finalizes the exact -dvd/-bsd argv.
    sbCreatePath(game, partname, udpfsPrefix, "/", 0);

    // Neutrino keep-IOP handoff (sysLoadELFKeepIOP): Neutrino reads the game through OUR udpfs
    // filesystem and its config/modules from the neutrino.elf device (-cwd) before its own IOP
    // reset -- keep BOTH mounted across the teardown. Mirrors bdmsupport's Neutrino deinit contract.
    // D6: pre-teardown validation -- for UDPFS this is where the bsd toml ip= sync now happens
    // (was post-deinit inside sysLaunchNeutrino); a failure toasts and stays in the menu.
    //
    // ORDER (matches bdmsupport/hddsupport): the preflight runs BEFORE the GameID push, never after.
    // The 0x8 devctl below physically re-mounts the MMCE card, and on Gen2 the busy bit it waits on
    // can clear before the FILESYSTEM surface is back (see mmceSettleAfterSwitch). On a
    // "Neutrino Device = MMCE" install the preflight's config/bsd-udpfs.toml open lands on mmceN:,
    // so running it after the push aimed that open straight into the re-mount window and failed the
    // launch with _STR_NEUTRINO_TOML_SYNC_FAILED on a toml that reads fine a moment earlier or
    // later. Preflighting first also means an abort leaves the card UNSWITCHED instead of dropping
    // the user back into the menu sitting on the per-game card.
    if (sysNeutrinoPreflight("udpfs", neutrinoPath, 0, NULL, -1) < 0)
        return;
    // Cheats: loaded above (sbLoadCheats) and handed to Neutrino here. Backing out stays in the menu.
    if (sysNeutrinoHandCheats(game->startup, neutrinoPath, neutrinoExtraArgs) < 0)
        return;
#ifdef RETROACHIEVEMENTS
    sysNeutrinoPrepareRA(udpfsPrefix, game->startup, "udpfs", neutrinoPath, neutrinoExtraArgs);
#endif
    if (sysNeutrinoArgsPreflight("udpfs", partname, game->startup, compatmask, EnablePS2Logo, neutrinoPath, neutrinoExtraArgs, neutrinoVideo, neutrinoGsmComp, 0, -1, &neutrinoVmc) < 0)
        return;

    sysNeutrinoWarnPadEmu(configSet);
    // MMCE cross-device game-id (#261): push the disc id to a present MMCE card before teardown frees
    // `game`. Neutrino path forwarded so a Neutrino launch protects the MMCE hand-off timing.
    mmceSendGameID(game->startup, neutrinoPath,
                   (neutrinoVmc.arg[0][0] ? 1 : 0) | (neutrinoVmc.arg[1][0] ? 2 : 0)); // Δ3: -mc-covered slots keep their card

    int neutrinoDevMode = oplPath2Mode(neutrinoPath);
    char gameStartup[GAME_STARTUP_MAX + 1];
    snprintf(gameStartup, sizeof(gameStartup), "%s", game->startup);
    deinitEx(sbNeutrinoDeinitException(neutrinoPath), itemList->mode, neutrinoDevMode); // itemCleanUp frees udpfsGames/game

    // Hand off to Neutrino with the udpfs driver token. `partname` and `gameStartup` survive the deinit;
    // `game` does not and is not dereferenced past this point.
    sysLaunchNeutrino("udpfs", partname, gameStartup, compatmask, EnablePS2Logo, neutrinoPath, neutrinoExtraArgs, neutrinoVideo, neutrinoGsmComp, 0 /* udpfs is fileid, no fs layer */, -1, &neutrinoVmc);
}

static config_set_t *udpfsGetConfig(item_list_t *itemList, int id)
{
    base_game_info_t *game = udpfsActiveGame(itemList, id);

    config_set_t *config;

    if (game == &udpfsEmptyGame)
        return NULL;
    config = sbPopulateConfig(game, udpfsPrefix, "/");
    sbResolvePs1Size(game, udpfsPrefix, config);
    return config;
}

static int udpfsGetImage(item_list_t *itemList, char *folder, int isRelative, char *value, char *suffix, GSTEXTURE *resultTex, short psm)
{
    char path[256];

    if (isRelative) {
        const char *imageFolder = strcmp(folder, "ART") == 0 ? udpfsArtCaseNames[udpfsArtCaseIndex] : folder;
        snprintf(path, sizeof(path), "%s%s/%s_%s", udpfsPrefix, imageFolder, value, suffix);
    } else
        snprintf(path, sizeof(path), "%s%s_%s", folder, value, suffix);
    int r = texDiscoverArt(resultTex, path);
    // ART LIVES IN THE ART FOLDER, and nowhere else. A PS1 cover is
    // ART/<name>_COV.png -- the same rule as a PS2 title -- which the texDiscoverLoad
    // above already tried. A miss is simply "no cover": there is no second directory to
    // search, which also means a missing cover costs one failed open instead of several.
    return r;
}

static int udpfsGetTextId(item_list_t *itemList)
{
    return _STR_UDPFS_GAMES;
}

static int udpfsGetIconId(item_list_t *itemList)
{
    return UDPFS_ICON;
}

// This may be called, even if udpfsInit() was not.
static void udpfsCleanUp(item_list_t *itemList, int exception)
{
    if (udpfsGameList.enabled) {
        LOG("UDPFSSUPPORT CleanUp\n");
        free(udpfsGames);
        udpfsGames = NULL;
        udpfsGameCount = 0;
        free(udpfsPs1Games);
        udpfsPs1Games = NULL;
        udpfsPs1GameCount = 0;
    }
    // SOCKET-ONCE: the ministack has no udp_unbind, so the module chain is intentionally NOT torn down
    // here (never DelDrv+re-AddDrv the UDPRDMA socket). udpfsIomanModLoaded stays set for the boot.
    (void)exception;
}

// This may be called, even if udpfsInit() was not.
static void udpfsShutdown(item_list_t *itemList)
{
    if (udpfsGameList.enabled) {
        LOG("UDPFSSUPPORT Shutdown\n");
        free(udpfsGames);
        udpfsGames = NULL;
        udpfsGameCount = 0;
        free(udpfsPs1Games);
        udpfsPs1Games = NULL;
        udpfsPs1GameCount = 0;
    }
    // SOCKET-ONCE: keep the ioman stack loaded (no unbind path). dev9 was init'd once in udpfsLoadModules
    // and is left to the shared dev9 refcount / final power-off.
}

static int udpfsCheckVMC(item_list_t *itemList, char *name, int createSize)
{
    return sysCheckVMC(udpfsPrefix, "/", name, createSize, NULL);
}

static char *udpfsGetPrefix(item_list_t *itemList)
{
    return udpfsPrefix;
}

static int udpfsSaveCueSettings(item_list_t *itemList, int id, const char *name, config_set_t *configSet)
{
    (void)itemList;
    (void)id;
    return cueSaveGameSettings(udpfsPrefix, name, configSet);
}

static int udpfsGetPs1SaveDir(item_list_t *itemList, int id, const char *name, int ember,
                              char *directory, int directorySize, char *partition, int partitionSize)
{
    (void)itemList;
    (void)id;
    (void)partitionSize;
    partition[0] = '\0';
    return ember && saveIconPs1Directory(udpfsPrefix, name, 1, directory, directorySize);
}

static item_list_t udpfsGameList = {
    UDPFS_MODE, 1, 0, 0, MENU_MIN_INACTIVE_FRAMES, UDPFS_MODE_UPDATE_DELAY, NULL, NULL, &udpfsGetTextId, &udpfsGetPrefix, &udpfsInit, &udpfsNeedsUpdate,
    &udpfsUpdateGameList, &udpfsGetGameCount, &udpfsGetGame, &udpfsGetGameName, &udpfsGetGameNameLength, &udpfsGetGameStartup, &udpfsDeleteGame, &udpfsRenameGame,
    &udpfsLaunchGame, &udpfsGetConfig, &udpfsGetImage, &udpfsCleanUp, &udpfsShutdown, &udpfsCheckVMC, &udpfsGetIconId,
    &udpfsLaunchVcd, /* viewOverride */ 0, /* itemGetArtArchivePath */ NULL, &udpfsLaunchCue,
    &udpfsGetItemView, &udpfsGetSourceId, &udpfsSaveCueSettings, &udpfsGetPs1SaveDir};
