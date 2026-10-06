#ifndef __SUPPORT_BASE_H
#define __SUPPORT_BASE_H

#include "include/system.h" // neutrino_vmc_args_t

#define UL_GAME_NAME_MAX       32
#define ISO_GAME_NAME_MAX      160
#define ISO_GAME_EXTENSION_MAX 4
#define GAME_STARTUP_MAX       12

#define ISO_GAME_FNAME_MAX (ISO_GAME_NAME_MAX + ISO_GAME_EXTENSION_MAX)

enum GAME_FORMAT {
    GAME_FORMAT_USBLD = 0,
    GAME_FORMAT_OLD_ISO,
    GAME_FORMAT_ISO,
    // A browsable subdirectory row (folder navigation, opt-in). Never launched, never written to the
    // games.bin cache and never stored as a favourite; the dispatch intercepts it to descend instead.
    GAME_FORMAT_FOLDER,
};

typedef struct
{
    char name[ISO_GAME_NAME_MAX + 1]; // MUST be the higher value from UL / ISO
    char startup[GAME_STARTUP_MAX + 1];
    char extension[ISO_GAME_EXTENSION_MAX + 1];
    u8 parts;
    u8 media;
    u8 format;
    u32 sizeMB;
} base_game_info_t;

typedef struct
{
    char name[UL_GAME_NAME_MAX];    // it is not a string but character array, terminating NULL is not necessary
    char magic[3];                  // magic string "ul."
    char startup[GAME_STARTUP_MAX]; // it is not a string but character array, terminating NULL is not necessary
    u8 parts;                       // slice count
    u8 media;                       // Disc type
    u8 unknown[4];                  // Always zero
    u8 Byte08;                      // Always 0x08
    u8 unknown2[10];                // Always zero
} USBExtreme_game_entry_t;

int isValidIsoName(char *name, int *pNameLen);
int sbIsSameSize(const char *prefix, int prevSize);
int sbCreateSemaphore(void);
// sub = current browse subpath below CD/DVD ("" at root); NULL opts the caller OUT of folder rows
// (ETH/SMB). On a TOTAL device-read failure the caller's list is left untouched (last-good list);
// GAME_FORMAT_FOLDER rows, and the ul.cfg (USBLD) leg -- a device-root-only concept -- is skipped
// inside subfolders.
int sbReadList(base_game_info_t **list, const char *prefix, const char *sub, int *fsize, int *gamecount);
// errno of the last CD/DVD folder the latest sbReadList could not open (0 = both opened).
int sbGetReadListError(void);
// Folder browsing: set the active subpath the path composers inject (see sbBrowseSub in supportbase.c).
void sbSetBrowseSub(const char *sub);
const char *sbGetCheatSearchLog(void);
// "No cheats found" text with the locations actually probed appended (#265).
const char *sbCheatsNotFoundText(void);
int sbCheatsMissingContinue(void *pCommon, int cheatResult);
int sbLoadImage(const char *path, const char *file);
void sbSetDiscAttributes(config_set_t *config, int isPS1, int isCD); // #System/#Media/#DiscType identity stamp

// Compatibility modes for a game: its saved $Compatibility key, else a known title default. Every reader of
// the modes (launch paths and the per-game screen) must use sbGetCompatModes so they agree.
int sbTitleCompatDefault(config_set_t *configSet);
int sbGetCompatModes(config_set_t *configSet);

void sbEnsureIgrUsbDrivers(int compatmask);
int sbPrepare(base_game_info_t *game, config_set_t *configSet, int size_cdvdman, void **cdvdman_irx, int *patchindex);
void sbUnprepare(void *pCommon);
// Where VMC slot `slot` (0/1) lives in an embedded mcemu image, as a u32 word index; -1 when the image has
// no such slot. A launch writes the slot's VMC settings over its marker (0xC0DEFAC0 + slot) and nothing
// writes the marker back, so a launch that returned to the menu left the next one unable to find it -- and
// that game silently ran without its VMC. The slot is found once, while the image is pristine, and the
// position is reused from then on. cache is two ints per image, both -2 until searched.
int sbMcemuSlotWord(const void *irx, int size, int slot, int *cache);
void sbRebuildULCfg(base_game_info_t **list, const char *prefix, int gamecount, int excludeID);
void sbCreatePath(const base_game_info_t *game, char *path, const char *prefix, const char *sep, int part);
void sbDelete(base_game_info_t **list, const char *prefix, const char *sep, int gamecount, int id);
void sbRename(base_game_info_t **list, const char *prefix, const char *sep, int gamecount, int id, char *newname);
config_set_t *sbPopulateConfig(base_game_info_t *game, const char *prefix, const char *sep);
// Gate for sbPopulateConfig's per-game size stat. OFF while scrolling the game list -- over SMB a
// fresh stat() of an ISO can cost seconds, and the main page only needs the metadata-derived badges
// (#DiscType/#Media/#Format), never #Size. The info screen flips it on via menuRequestInfoSize() so
// #Size still resolves on demand. (1 = stat, 0 = skip.)
void sbSetConfigStatSize(int enable);
int sbConfigStatSizeEnabled(void);
void sbMakeDirTree(const char *path);
void sbCreateFolders(const char *path, int createDiscImgFolders);

// ISO9660 filesystem management functions.
u32 sbGetISO9660MaxLBA(const char *path);
int sbProbeISO9660(const char *path, base_game_info_t *game, u32 layer1_offset);

int sbLoadCheats(const char *path, const char *file, config_set_t *configSet);
// The cheats of a Neutrino launch whose leg skips the native preparation (BDM, APA): this game's cheat
// settings, its .cht from <prefix>CHT/ (Select mode: remembered picks, then the picker), then
// sysNeutrinoHandCheats. 0 = launch; <0 = the user chose to stay in the menu.
int sbNeutrinoLoadCheats(const char *prefix, const char *startup, config_set_t *configSet, const char *neutrinoPath, const char *extraArgs);


int sbFileExists(const char *path);

// Resolve one user-entered full ELF path into the filesystem path RiptOPL can actually open.
// This activates the explicitly named storage stack when safe (USB/MX4SIO/iLink/exFAT BDM,
// MMCE, SMB, UDPFS, UDPBD/UDPFS-BD, APA/PFS) and normalizes aliases to live namespaces such as
// massN:/ or smb0:. Returns 1 only when the resolved file can be opened.
int sbResolveCustomLoaderPath(const char *requested, char *out, int outSize);

// First usable Neutrino core ELF, or NULL. Runtime order is fixed:
// custom gNeutrinoPath -> active game's device (activePrefix) -> mc0/mc1.
// A Memory Card / HDD (APA) choice migrated from the retired picker also gets that picker's
// case-tolerant probe until the migrated path is edited (see configReadNeutrinoGlobals).
const char *sbResolveNeutrinoPath(const char *activePrefix);

// Deinit exception mask for an external ELF that is opened AFTER OPL's teardown. Every loader path
// keeps its mount; PFS additionally keeps the IOP-side descriptors because hddCleanUp's
// PDIOC_CLOSEALL would otherwise invalidate the mount before the ELF loader opens it.
int sbLoaderDeinitException(const char *loaderPath);
// Backward-compatible Neutrino-named wrapper used by existing launch legs.
int sbNeutrinoDeinitException(const char *neutrinoPath);

// Structured view of the USER-settable Neutrino launch flags (the catch-all "Launch Args" box).
typedef struct
{
    int qb;           // -qb (quick-boot)
    int dbc;          // -dbc (debug colors)
    int logo;         // -logo (PS2 logo)
    char cwd[256];    // -cwd=
    char cfg[256];    // -cfg=
    char elf[256];    // -elf=
    char ata0[256];   // -ata0=
    char ata0id[256]; // -ata0id=
    char ata1[256];   // -ata1=
    char extra[256];  // unrecognised/free tokens, space-joined; "--b ..." preserved at the tail
} neutrino_args_t;
// Parse an args string into the struct; assemble it back in a Neutrino-accepted order (--b last).
void neutrinoArgsParse(const char *in, neutrino_args_t *na);
int neutrinoArgsAssemble(const neutrino_args_t *na, char *out, int outSize); // 0 if the result would be truncated

// Fully-formed Neutrino -mcN VMC args for both slots, resolved from the per-game config
// BEFORE deinit frees it. vmcPrefix = the device prefix VMC/ lives under.
void sbBuildVmcNeutrinoArgs(config_set_t *configSet, const char *vmcPrefix, neutrino_vmc_args_t *vmcArgs);

#ifdef RETROACHIEVEMENTS
// RA: load this game's watch list from <path>RA/<file>.wl. Mirrors sbLoadCheats'
// shape (256-byte path, both extension cases). A missing list is not an error.
int sbLoadWatchList(const char *path, const char *file);

// RA: the hash log, <path>RA/hashes.txt. Open before hashing, close after:
// raHashStep and ranet.c drop their crumbs into whatever log is open.
void raHashLogOpen(const char *path);
void raHashStep(const char *what);
void raHashLogAdd(const char *name, const char *startup, const char *hash);
void raHashLogClose(void);

// RA: hash one image and ask the PC client for its watch list. From the menu
// call ONLY the deferred variant -- it runs on the I/O thread, where device
// access is safe. sbHashGameDeferred returns 1 when queued, 0 when a check is
// already running.
void sbHashGame(const char *path, const char *name, const char *ext, const char *startup, int format);
int sbHashGameBusy(void);
int sbHashGameDeferred(const char *path, const char *name, const char *ext, const char *startup, int format);

// RA: ask the PC client to answer, from the I/O thread; the result is shown
// as a notice.
void sbTestPCLinkDeferred(void);
#endif

#endif
