"""A BDM page whose first PS2 scan fails must not rescan on every idle poll -- and must say why.

sbReadList (src/supportbase.c) keeps the old list and leaves bdmULSizePrev at -2 ("never scanned")
when neither CD nor DVD opens and there is no ul.cfg. bdmNeedsUpdate used to treat a published page
still at -2 as needing a scan on EVERY poll (the #186 rescue), and menuUpdateHook polls each BDM page
about every 2 s of idle. So a device whose folders would not open rescanned forever, and every pass
also rebuilt APPS and Favourites (menuDeferredUpdate) -- every L3 on every page waited behind it
(FifthFox, USB and MX4SIO). Upstream never had the rescue: "no change" returns 0.

This compiles bdmNeedsUpdate and bdmUpdateGameList from src/bdmsupport.c on the host against stubs
and checks:

- a failed first scan runs ONCE; 30 idle polls and a generation bump add no scans;
- that failure raises one BDM_PS2_FOLDERS_UNREADABLE message naming the prefix and the errno;
- SELECT/L3 (libViewConsumeDirty) still rescans, and says so again if it fails again;
- a slot whose identity is not ready yet is still re-polled every pass (the -2 bypass upstream has);
- a successful scan, a subfolder scan and the PS1 view raise no message.

A second harness compiles the real span of src/supportbase.c (sbReadListErrno through sbReadList)
against a scripted opendir: a folder that will not open records its errno, the next scan clears it,
and a driver that fails without setting errno never reports a stale one.

Run with --baseline <file> to point it at another bdmsupport.c (for example the pre-fix one from git)
and watch the no-rescan and message cases fail.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/bdmsupport.c'
if len(sys.argv) == 3 and sys.argv[1] == '--baseline':
    source_path = Path(sys.argv[2])
source = source_path.read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    # Whole definition (a prototype ends in ';'), closing brace included.
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (source_path, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


functions = function_text('static int bdmNeedsUpdate(') + function_text('static int bdmUpdateGameList(')

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define START_MODE_DISABLED 0
#define START_MODE_AUTO 2
#define LIB_VIEW_ISO 0
#define LIB_VIEW_PS1 1
#define LIB_VIEW_MIXED 2
#define IO_OK 0
#define IO_CUSTOM_SIMPLEACTION 1
#define SFX_BD_CONNECT 1
#define SFX_BD_DISCONNECT 2
#define BDM_TYPE_USB 1
#define BDM_TYPE_UDPBD 5
#define BDM_DEVICE_ROOT_MAX 16
#define _STR_BDM_PS2_FOLDERS_UNREADABLE 4242

typedef struct base_game_info base_game_info_t;

typedef struct
{
    int mode;
    void *priv;
    void *owner;
} item_list_t;

typedef struct
{
    struct
    {
        int visible;
    } menuItem;
} opl_io_module_t;

typedef struct
{
    int ForceRefresh;
    int bdmDeviceType;
    unsigned int bdmDeviceTick;
    int bdmULSizePrev;
    int bdmMissCount;
    int FoldersCreated;
    char bdmPrefix[64];
    time_t bdmModifiedCDPrev;
    time_t bdmModifiedDVDPrev;
    int ThemesLoaded;
    int LanguagesLoaded;
    base_game_info_t *bdmGames;
    int bdmGameCount;
    base_game_info_t *bdmPs1Games;
    int bdmPs1GameCount;
} bdm_device_data_t;

static int bdmDeviceModeStarted;
static unsigned int BdmGeneration = 1;

/* ---- the world the two functions see ---- */
static int view = LIB_VIEW_ISO;
static const char *browseSub = "";
static int dirty;              /* SELECT / L3 pending */
static int deviceResults[64];  /* what bdmUpdateDeviceData returns, pass by pass (0 after the list) */
static int deviceResultCount, deviceCalls;
static int scanFails = 1;      /* sbReadList: 1 = neither CD nor DVD opens (keeps -2), 0 = success */
static int scans, messages, lastMessageError;
static char lastMessagePath[64];

static int bdmEffectiveStartMode(void) { return START_MODE_AUTO; }
static void bdmReportUnsupportedDrives(void) {}
static int bdmTransportEnabled(int type) { (void)type; return 1; }
static void moduleUpdateMenu(int mode, int a, int b) { (void)mode; (void)a; (void)b; }
static int libViewConsumeDirty(int mode) { (void)mode; int d = dirty; dirty = 0; return d; }
static int folderConsumeDirty(int mode) { (void)mode; return 0; }
static int bdmShouldQueueModuleLoad(void) { return 0; }
static void bdmLoadBlockDeviceModules(void *arg) { (void)arg; }
static int ioPutRequest(int type, void *data) { (void)type; (void)data; return IO_OK; }
static int ioPutRequestUnlessWaiting(int type, void *data) { (void)type; (void)data; return IO_OK; }
static int bdmUpdateDeviceData(item_list_t *itemList)
{
    (void)itemList;
    int r = deviceCalls < deviceResultCount ? deviceResults[deviceCalls] : 0;
    deviceCalls++;
    return r;
}
static void sfxPlay(int id) { (void)id; }
static void sbCreateFolders(const char *path, int disc) { (void)path; (void)disc; }
static int libListViewActive(item_list_t *itemList) { (void)itemList; return view; }
static int stub_stat(const char *path, struct stat *st) { (void)path; memset(st, 0, sizeof(*st)); return -1; }
#define stat(p, s) stub_stat(p, s)
static int sbIsSameSize(const char *prefix, int prev) { (void)prefix; return prev == -1; }
static int thmAddElements(const char *p, const char *s, int m) { (void)p; (void)s; (void)m; return 0; }
static int lngAddLanguages(const char *p, const char *s, int m) { (void)p; (void)s; (void)m; return 0; }
static void bdmBuildPs1Prefix(char *t, int n, int slot) { snprintf(t, n, "mass%d:/", slot); }
static int ps1FillGameList(const char *p, base_game_info_t **g) { (void)p; (void)g; return 0; }
static int cueFillGameList(const char *p, base_game_info_t **g) { (void)p; (void)g; return 0; }
static const char *folderGetSub(int mode) { (void)mode; return browseSub; }
static int sbReadList(base_game_info_t **list, const char *prefix, const char *sub, int *fsize, int *count)
{
    (void)list; (void)prefix; (void)sub;
    scans++;
    if (scanFails)
        return *count; /* total failure: list, count and fsize untouched */
    *fsize = -1;       /* both folders opened, no ul.cfg */
    *count = 0;
    return 0;
}
static int sbGetReadListError(void) { return 5; /* EIO */ }
static void setErrorMessagePathCode(int id, const char *path, int error)
{
    if (id != _STR_BDM_PS2_FOLDERS_UNREADABLE)
        return;
    messages++;
    snprintf(lastMessagePath, sizeof(lastMessagePath), "%s", path);
    lastMessageError = error;
}

@FUNCTIONS@

/* ---- one slot, driven the way menuDeferredUpdate drives it ---- */
static bdm_device_data_t dev;
static opl_io_module_t owner;
static item_list_t list = {2, &dev, &owner};
static int failed;

static void reset(void)
{
    memset(&dev, 0, sizeof(dev));
    dev.bdmULSizePrev = -2;
    dev.bdmDeviceType = BDM_TYPE_USB;
    dev.bdmDeviceTick = (unsigned int)-1;
    owner.menuItem.visible = 0;
    view = LIB_VIEW_ISO;
    browseSub = "";
    dirty = 0;
    deviceResultCount = deviceCalls = 0;
    scanFails = 1;
    scans = messages = lastMessageError = 0;
    lastMessagePath[0] = '\0';
}

/* One deferred update: needsUpdate, and the rebuild (itemUpdate) when it says so. */
static void pass(void)
{
    int r = bdmNeedsUpdate(&list);
    if (r == 1)
        bdmUpdateGameList(&list);
}

/* The connect pass: bdmUpdateDeviceData publishes the page and reports 1. */
static void connectDevice(void)
{
    snprintf(dev.bdmPrefix, sizeof(dev.bdmPrefix), "mass0:");
    owner.menuItem.visible = 1;
    deviceResults[0] = 1;
    deviceResultCount = 1;
    pass();
}

#define CHECK(cond, ...)                         \
    do {                                         \
        if (!(cond)) {                           \
            printf("FAIL %s: ", __func__);       \
            printf(__VA_ARGS__);                 \
            printf("\n");                        \
            failed = 1;                          \
        }                                        \
    } while (0)

static void failedScanRunsOnce(void)
{
    reset();
    connectDevice();
    CHECK(scans == 1, "connect pass scanned %d times, want 1", scans);
    for (int i = 0; i < 30; i++)
        pass();
    CHECK(scans == 1, "30 idle polls after a failed first scan rescanned: %d scans, want 1", scans);
    BdmGeneration++; /* another device's hotplug */
    pass();
    CHECK(scans == 1, "a generation bump rescanned a failed page: %d scans, want 1", scans);
}

static void failedScanSaysWhere(void)
{
    reset();
    connectDevice();
    for (int i = 0; i < 10; i++)
        pass();
    CHECK(messages == 1, "%d unreadable-folder messages, want 1", messages);
    CHECK(strcmp(lastMessagePath, "mass0:") == 0, "message path '%s', want 'mass0:'", lastMessagePath);
    CHECK(lastMessageError == 5, "message error %d, want 5", lastMessageError);
}

static void selectStillRetries(void)
{
    reset();
    connectDevice();
    dirty = 1; /* SELECT or L3 */
    pass();
    CHECK(scans == 2, "SELECT after a failed scan: %d scans, want 2", scans);
    CHECK(messages == 2, "a failed retry should say so again: %d messages, want 2", messages);
    scanFails = 0;
    dirty = 1;
    pass();
    CHECK(scans == 3 && messages == 2, "successful retry: %d scans / %d messages, want 3 / 2", scans, messages);
}

static void identityWaitStillPolls(void)
{
    reset();
    snprintf(dev.bdmPrefix, sizeof(dev.bdmPrefix), "mass0:");
    deviceResults[0] = deviceResults[1] = deviceResults[2] = 0; /* mounted, identity not ready */
    deviceResults[3] = 1;                                       /* identity ready: published */
    deviceResultCount = 4;
    for (int i = 0; i < 3; i++)
        pass();
    CHECK(deviceCalls == 3, "unpublished never-scanned slot polled %d times in 3 passes, want 3", deviceCalls);
    owner.menuItem.visible = 1; /* what bdmUpdateDeviceData does as it returns 1 */
    pass();
    CHECK(scans == 1, "publish pass scanned %d times, want 1", scans);
}

static void successIsQuiet(void)
{
    reset();
    scanFails = 0;
    connectDevice();
    for (int i = 0; i < 10; i++)
        pass();
    CHECK(scans == 1 && messages == 0, "successful scan: %d scans / %d messages, want 1 / 0", scans, messages);
    CHECK(deviceCalls == 1, "a scanned page polled the device %d times, want 1 (the per-generation cache)", deviceCalls);
}

static void subfolderAndPs1AreQuiet(void)
{
    reset();
    browseSub = "RPGs";
    connectDevice();
    CHECK(messages == 0, "a subfolder scan failure raised %d messages, want 0", messages);

    reset();
    view = LIB_VIEW_PS1;
    connectDevice();
    for (int i = 0; i < 10; i++)
        pass();
    CHECK(scans == 0 && messages == 0, "PS1 view: %d PS2 scans / %d messages, want 0 / 0", scans, messages);
}

int main(void)
{
    failedScanRunsOnce();
    failedScanSaysWhere();
    selectStillRetries();
    identityWaitStillPolls();
    successIsQuiet();
    subfolderAndPs1AreQuiet();
    if (!failed)
        printf("bdm scan retry: all cases passed\n");
    return failed;
}
'''

# The error number in that message comes from the REAL scan: scanForISO records the errno of a CD/DVD
# folder that will not open, and sbReadList clears it at the start of every scan. Compile that span of
# src/supportbase.c (sbReadListErrno through sbReadList) against a scripted opendir.
support = (root / 'src/supportbase.c').read_text(encoding='utf-8').replace('\r\n', '\n')
span_start = support.find('static int sbReadListErrno;')
span_end_match = re.search(r'^int sbReadList\([^;{]*\)\s*\{', support, re.M)
if span_start < 0 or span_end_match is None:
    failures.append('src/supportbase.c: sbReadListErrno ... sbReadList span not found')
    scan_span = ''
else:
    scan_span = support[span_start:support.index('\n}', span_end_match.start())] + '\n}\n'

SCAN_HARNESS = r'''
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#define LOG(...) ((void)0)
#define O_RDONLY 0
#define FOLDER_SUB_MAX 128
#define ISO_GAME_NAME_MAX 160
#define ISO_GAME_EXTENSION_MAX 4
#define UL_GAME_NAME_MAX 32
#define GAME_STARTUP_MAX 12
#define GAME_FORMAT_USBLD 0
#define GAME_FORMAT_OLD_ISO 1
#define GAME_FORMAT_ISO 2
#define GAME_FORMAT_FOLDER 3
#define SCECdPS2CD 0x12
#define SCECdPS2DVD 0x14
#define FIO_MT_RDONLY 0

typedef struct
{
    char name[ISO_GAME_NAME_MAX + 1];
    char startup[GAME_STARTUP_MAX + 1];
    char extension[ISO_GAME_EXTENSION_MAX + 1];
    unsigned char parts;
    unsigned char media;
    unsigned short format;
    int sizeMB;
} base_game_info_t;

typedef struct
{
    char name[UL_GAME_NAME_MAX];
    char startup[GAME_STARTUP_MAX];
    unsigned char parts;
    unsigned char media;
} USBExtreme_game_entry_t;

struct game_list_t
{
    base_game_info_t gameinfo;
    struct game_list_t *next;
};

struct game_cache_list
{
    unsigned int count;
    base_game_info_t *games;
};

static int gEnableFolderNav;

/* Scripted device: which folder names refuse opendir, and with what errno. Opened folders are empty. */
static const char *failPath1, *failPath2;
static int failErrno;
static int fakeDir;
static DIR *stub_opendir(const char *path)
{
    if ((failPath1 && !strcmp(path, failPath1)) || (failPath2 && !strcmp(path, failPath2))) {
        if (failErrno >= 0) /* -1: a driver that fails without setting errno */
            errno = failErrno;
        return NULL;
    }
    return (DIR *)&fakeDir;
}
static struct dirent *stub_readdir(DIR *d) { (void)d; return NULL; }
static int stub_closedir(DIR *d) { (void)d; return 0; }
#define opendir stub_opendir
#define readdir stub_readdir
#define closedir stub_closedir

static int loadISOGameListCache(const char *path, struct game_cache_list *c) { (void)path; (void)c; errno = 99; return -1; }
static void freeISOGameListCache(struct game_cache_list *c) { (void)c; }
static int queryISOGameListCache(const struct game_cache_list *c, base_game_info_t *g, const char *n, int *h) { (void)c; (void)g; (void)n; (void)h; return ENOENT; }
static int updateISOGameList(const char *p, const struct game_cache_list *c, const struct game_list_t *h, int n) { (void)p; (void)c; (void)h; (void)n; return 0; }
static int isValidIsoName(char *name, int *len) { (void)name; *len = 0; return 0; }
static int fileXioMount(const char *m, const char *p, int f) { (void)m; (void)p; (void)f; return -1; }
static int fileXioUmount(const char *m) { (void)m; return 0; }
static int GetStartupExecName(const char *p, char *o, int n) { (void)p; (void)o; (void)n; return -1; }
static int openFile(const char *p, int f) { (void)p; (void)f; return -1; } /* no ul.cfg */
static int getFileSize(int fd) { (void)fd; return 0; }
static int stub_read(int fd, void *b, int n) { (void)fd; (void)b; (void)n; return 0; }
static int stub_close(int fd) { (void)fd; return 0; }
#define read stub_read
#define close stub_close

@SPAN@

int main(void)
{
    base_game_info_t *list = NULL;
    int fsize = -2, count = 0, failed = 0;

    failPath1 = "mass0:CD";
    failPath2 = "mass0:DVD";
    failErrno = EIO;
    sbReadList(&list, "mass0:", "", &fsize, &count);
    if (fsize != -2 || sbGetReadListError() != EIO) {
        printf("FAIL neither folder opens: fsize %d (want -2, list kept), error %d (want EIO=%d)\n", fsize, sbGetReadListError(), EIO);
        failed = 1;
    }

    failPath1 = failPath2 = NULL;
    sbReadList(&list, "mass0:", "", &fsize, &count);
    if (fsize != -1 || sbGetReadListError() != 0) {
        printf("FAIL both folders open: fsize %d (want -1), error %d (want 0: cleared by the new scan)\n", fsize, sbGetReadListError());
        failed = 1;
    }

    failPath1 = "mass0:CD";
    failErrno = ENOENT;
    fsize = -2;
    sbReadList(&list, "mass0:", "", &fsize, &count);
    if (fsize != -1 || sbGetReadListError() != ENOENT) {
        printf("FAIL only CD refuses: fsize %d (want -1, not a total failure), error %d (want ENOENT)\n", fsize, sbGetReadListError());
        failed = 1;
    }
    /* A driver that fails without setting errno must not report the cache lookup's leftover (99). */
    failPath1 = "mass0:CD";
    failPath2 = "mass0:DVD";
    failErrno = -1;
    fsize = -2;
    sbReadList(&list, "mass0:", "", &fsize, &count);
    if (sbGetReadListError() != 0) {
        printf("FAIL silent driver failure: error %d (want 0, not a stale errno)\n", sbGetReadListError());
        failed = 1;
    }
    free(list);
    if (!failed)
        printf("bdm scan retry: real scan records and clears the folder error\n");
    return failed;
}
'''


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        c_file = Path(tmp) / (name + '.c')
        exe = Path(tmp) / name
        c_file.write_text(program, encoding='utf-8')
        build = subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-o', str(exe), str(c_file)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s%s' % (name, build.stdout, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            failures.append('%s harness reported failures' % name)


if not failures:
    compile_and_run('needs_update', HARNESS.replace('@FUNCTIONS@', functions))
    compile_and_run('scan_error', SCAN_HARNESS.replace('@SPAN@', scan_span))

# The removed rescue must stay removed: it is the only thing that made a failed page rescan per poll.
if 'neverScanned && connectedAndPublished' in source:
    failures.append('bdmNeedsUpdate: the #186 per-poll rescue is back')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
