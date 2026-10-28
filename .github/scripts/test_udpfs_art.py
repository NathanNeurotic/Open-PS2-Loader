"""Compile and exercise RiptOPL's actual UDPFS ART resolver and negative-index logic.

The fast path must not enumerate directories per image. A partial UDPFS directory
listing must never be published as proof that missing files do not exist.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
UDPFS = (ROOT / "src/udpfssupport.c").read_text(encoding="utf-8")
INDEX = (ROOT / "src/artindex.c").read_text(encoding="utf-8")
failures = []


def function(source, signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\{", source, re.M)
    if match is None:
        raise AssertionError(f"Missing function: {signature}")
    pos = match.start()
    start = source.find("{", pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[pos:i + 1]
    raise AssertionError(f"Unterminated function: {signature}")


def run_harness(label, code):
    with tempfile.TemporaryDirectory() as directory:
        src = Path(directory) / "test.c"
        exe = Path(directory) / "test"
        src.write_text(code, encoding="utf-8")
        build = subprocess.run(
            ["cc", "-std=gnu99", "-O0", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter",
             "-o", str(exe), str(src)],
            capture_output=True, text=True, check=False,
        )
        if build.returncode != 0:
            failures.append(f"{label} compilation failed:\n{build.stderr}")
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        print(result.stdout, end="")
        if result.returncode != 0:
            failures.append(f"{label} assertions failed:\n{result.stderr}")


get_image = function(UDPFS, "static int udpfsGetImage(")
init = function(UDPFS, "void udpfsInit(")
update = function(UDPFS, "static int udpfsUpdateGameList(")
needs_update = function(UDPFS, "static int udpfsNeedsUpdate(")
if "udpfsDiscoverArtFolder();" not in needs_update:
    failures.append("udpfsNeedsUpdate must retry ART discovery like THM/LNG (#1036)")
waiter_fn = function(UDPFS, "static void udpfsSetWaitingForServer(")
if "!udpfsArtCaseChecked" not in waiter_fn:
    failures.append("Unresolved ART resolution must keep the general-refresh retry cadence alive (#1036)")
discover = function(UDPFS, "static void udpfsDiscoverArtFolder(void)")
folder_files = function(UDPFS, "static int udpfsArtFolderHasFiles(")
table = re.search(
    r"static const char \*const udpfsArtCaseNames\[8\] = \{.*?\};", UDPFS, re.S
)
if not table:
    failures.append("ART casing table is missing")
if any(word in get_image for word in ("opendir(", "readdir(", "stat(", "udpfsDiscoverArtFolder(")):
    failures.append("The per-image hot path must not perform extra directory/network discovery")
if "udpfsArtCaseChecked = 0;" not in init or "udpfsArtCaseIndex = 0;" not in init:
    failures.append("Reinitialization must reset ART resolution for a different share")
if update.find("udpfsDiscoverArtFolder();") > update.find("sbCreateFolders(udpfsPrefix, 1);"):
    failures.append("The case resolver must run BEFORE an empty uppercase ART can be created")
if "cacheInvalidateFailMemo();" not in discover:
    failures.append("Changing ART spelling must re-arm earlier cached missing-cover results")
if "strcmp(folder, \"ART\")" not in get_image:
    failures.append("Other relative directories must retain their original spelling")

if table:
    casing_harness = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
#include <sys/stat.h>
#define MENU_UPD_DELAY_GENREFRESH 0
#define UDPFS_MODE_UPDATE_DELAY 300
#define LIB_VIEW_PS1 1
typedef struct { int kind; int pos; } DIR;
struct dirent { char d_name[128]; };
typedef struct { int mode; } item_list_t;
typedef struct { int dummy; } GSTEXTURE;

static char udpfsPrefix[40] = "udpfs:/";
static int udpfsIomanModLoaded = 1, serverOnline = 1;
static int invalidations, rootOpens, folderOpens, imageCalls;
static int indexInvalidations, udpfsWaitingForServer;
static int udpfsThemesScanned = 1, udpfsLanguagesScanned = 1;
static int udpfsPs1Scanned = 1, udpfsIsoScanned = 1;
static time_t udpfsModifiedCDPrev, udpfsModifiedDVDPrev;
static struct { int updateDelay; } udpfsGameList;
static char imagePath[256];
static const char *rootNames[12];
static const char *folderNames[8][4];
static int rootReadError, folderOpenError[8], folderReadError[8], successfulReadErrno;
static DIR rootDir, folders[8];
static struct dirent returnedEntry;

@TABLE@
static volatile unsigned int udpfsArtCaseIndex;
static int udpfsArtCaseChecked;

static int udpfsServerAnswers(void) { return serverOnline; }
static void cacheInvalidateFailMemo(void) { invalidations++; }
static void artIndexInvalidate(void) { indexInvalidations++; }
static void udpfsDiscoverThemes(void) {}
static void udpfsDiscoverLanguages(void) {}
static int libViewConsumeDirty(int mode) { return 0; }
static int folderConsumeDirty(int mode) { return 0; }
static int libListViewActive(item_list_t *list) { return LIB_VIEW_PS1; }
static int stub_stat(const char *path, struct stat *st) { memset(st, 0, sizeof(*st)); return 0; }
#define stat(path, st) stub_stat(path, st)
@WAITER@
static DIR *opendir(const char *path)
{
    if (strcmp(path, "udpfs:/") == 0) {
        rootOpens++;
        rootDir.kind = -1;
        rootDir.pos = 0;
        return &rootDir;
    }
    for (int i = 0; i < 8; i++) {
        char full[40];
        snprintf(full, sizeof(full), "udpfs:/%s", udpfsArtCaseNames[i]);
        if (strcmp(path, full) == 0) {
            folderOpens++;
            if (folderOpenError[i]) { errno = ENOTDIR; return NULL; }
            folders[i].kind = i;
            folders[i].pos = 0;
            return &folders[i];
        }
    }
    errno = ENOENT;
    return NULL;
}
static struct dirent *readdir(DIR *dir)
{
    const char *name;
    if (dir->kind == -1) {
        name = rootNames[dir->pos++];
        if (!name && rootReadError)
            errno = EIO;
    } else {
        name = folderNames[dir->kind][dir->pos++];
        if (!name && folderReadError[dir->kind])
            errno = EIO;
    }
    if (name && successfulReadErrno)
        errno = EIO;
    if (!name)
        return NULL;
    snprintf(returnedEntry.d_name, sizeof(returnedEntry.d_name), "%s", name);
    return &returnedEntry;
}
static int closedir(DIR *dir) { (void)dir; return 0; }
static int texDiscoverArt(GSTEXTURE *tex, const char *path)
{
    (void)tex;
    imageCalls++;
    snprintf(imagePath, sizeof(imagePath), "%s", path);
    return 0;
}
@FOLDER@
@DISCOVER@
@NEEDS_UPDATE@
@IMAGE@

static int fails;
static void reset(void)
{
    memset(rootNames, 0, sizeof(rootNames));
    memset(folderNames, 0, sizeof(folderNames));
    memset(folderOpenError, 0, sizeof(folderOpenError));
    udpfsArtCaseIndex = 0;
    udpfsArtCaseChecked = invalidations = rootOpens = folderOpens = imageCalls = 0;
    indexInvalidations = udpfsWaitingForServer = 0;
    rootReadError = successfulReadErrno = 0;
    memset(folderReadError, 0, sizeof(folderReadError));
    serverOnline = 1;
}
static void check(const char *label, int ok)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", label);
        fails++;
    }
}
int main(void)
{
    GSTEXTURE texture = {0};
    item_list_t list = {0};
    reset();
    rootNames[0] = "ART";
    udpfsDiscoverArtFolder();
    check("canonical case", udpfsArtCaseChecked && udpfsArtCaseIndex == 0 &&
          invalidations == 1 && indexInvalidations == 1 && folderOpens == 0 && rootOpens == 1);

    reset();
    rootNames[0] = "art";
    udpfsDiscoverArtFolder();
    int rootBeforeImage = rootOpens, foldersBeforeImage = folderOpens;
    udpfsGetImage(NULL, "ART", 1, "SLUS_123.45", "COV", &texture, 0);
    check("lowercase art resolves", udpfsArtCaseIndex == 7 && invalidations == 1 &&
          strcmp(imagePath, "udpfs:/art/SLUS_123.45_COV") == 0);
    check("per-image lookup makes no directory probes",
          rootOpens == rootBeforeImage && folderOpens == foldersBeforeImage);

    reset();
    rootNames[0] = "ART"; rootNames[1] = "art";
    folderNames[7][0] = "SLUS_123.45_COV.png";
    udpfsDiscoverArtFolder();
    check("populated lowercase wins over auto-created empty uppercase",
          udpfsArtCaseIndex == 7 && folderOpens <= 2);

    reset();
    rootNames[0] = "art"; rootNames[1] = "ART";
    folderNames[0][0] = "SLUS_123.45_COV.png";
    folderNames[7][0] = "SLUS_123.45_COV.png";
    udpfsDiscoverArtFolder();
    check("populated canonical spelling wins", udpfsArtCaseIndex == 0 &&
          invalidations == 1 && folderOpens == 1);

    reset();
    rootNames[0] = "ART"; rootNames[1] = "Art"; rootNames[2] = "art";
    folderOpenError[3] = 1;
    folderNames[7][0] = "SLUS_123.45_COV.png";
    udpfsDiscoverArtFolder();
    check("failed open is not populated", udpfsArtCaseIndex == 7);

    reset();
    rootNames[0] = "Art"; rootNames[1] = "art";
    folderOpenError[3] = 1;
    udpfsDiscoverArtFolder();
    check("unusable preferred entry falls back to an empty directory", udpfsArtCaseIndex == 7);

    reset();
    rootNames[0] = "Art"; rootNames[1] = "art";
    folderOpenError[3] = folderOpenError[7] = 1;
    udpfsDiscoverArtFolder();
    check("all unusable entries fall back to canonical ART", udpfsArtCaseIndex == 0);

    reset();
    rootNames[0] = "art";
    folderOpenError[7] = 1;
    udpfsDiscoverArtFolder();
    check("single file masquerading as art is rejected", udpfsArtCaseIndex == 0);

    reset();
    rootNames[0] = "art";
    rootReadError = 1;
    udpfsDiscoverArtFolder();
    check("partial root enumeration is not latched", !udpfsArtCaseChecked &&
          udpfsArtCaseIndex == 0);
    rootReadError = 0;
    udpfsDiscoverArtFolder();
    check("root enumeration may recover", udpfsArtCaseChecked && udpfsArtCaseIndex == 7);

    reset();
    rootNames[0] = "ART";
    successfulReadErrno = 1;
    udpfsDiscoverArtFolder();
    check("successful read errno does not poison EOF", udpfsArtCaseChecked && rootOpens == 1);
    udpfsDiscoverArtFolder();
    check("completed discovery does not rescan", rootOpens == 1);

    reset();
    rootNames[0] = "ART"; rootNames[1] = "art";
    folderReadError[0] = 1;
    folderNames[7][0] = "cover.png";
    udpfsDiscoverArtFolder();
    check("canonical scan error does not latch", !udpfsArtCaseChecked);
    folderReadError[0] = 0;
    udpfsDiscoverArtFolder();
    check("canonical scan recovers", udpfsArtCaseChecked && udpfsArtCaseIndex == 7);

    reset();
    rootNames[0] = "ART"; rootNames[1] = "art";
    folderReadError[7] = 1;
    udpfsDiscoverArtFolder();
    check("alternative scan error does not latch", !udpfsArtCaseChecked);

    reset();
    rootNames[0] = "art";
    folderReadError[7] = 1;
    udpfsDiscoverArtFolder();
    check("single candidate scan error does not latch", !udpfsArtCaseChecked);
    folderReadError[7] = 0;
    folderNames[7][0] = ".";
    successfulReadErrno = 1;
    udpfsDiscoverArtFolder();
    check("empty folder with successful-read errno is usable", udpfsArtCaseChecked && udpfsArtCaseIndex == 7);

    reset();
    serverOnline = 0;
    udpfsDiscoverArtFolder();
    check("offline share does not latch", !udpfsArtCaseChecked && rootOpens == 0);
    serverOnline = 1;
    udpfsDiscoverArtFolder();
    check("fresh share retains ART default", udpfsArtCaseChecked && udpfsArtCaseIndex == 0);

    reset();
    serverOnline = 0;
    udpfsSetWaitingForServer(0);
    check("unresolved ART keeps polling after theme/language discovery",
          udpfsGameList.updateDelay == MENU_UPD_DELAY_GENREFRESH);
    check("offline PS1 page polls without rebuilding", udpfsNeedsUpdate(&list) == 0 && rootOpens == 0);
    serverOnline = 1;
    rootNames[0] = "art";
    check("PS1 early return still discovers ART", udpfsNeedsUpdate(&list) == 0 &&
          udpfsArtCaseChecked && udpfsArtCaseIndex == 7 && invalidations == 1 && indexInvalidations == 1);
    check("completed ART retires temporary cadence", udpfsGameList.updateDelay == UDPFS_MODE_UPDATE_DELAY);
    udpfsNeedsUpdate(&list);
    check("completed discovery neither rescans nor invalidates again",
          rootOpens == 1 && invalidations == 1 && indexInvalidations == 1);

    if (!fails)
        puts("UDPFS ART: canonical, lowercase, duplicate casing, incomplete scan and zero per-image I/O pass");
    return fails ? 1 : 0;
}
"""
    run_harness(
        "UDPFS ART resolver",
        casing_harness.replace("@TABLE@", table.group(0))
        .replace("@WAITER@", waiter_fn)
        .replace("@FOLDER@", folder_files)
        .replace("@DISCOVER@", discover)
        .replace("@NEEDS_UPDATE@", needs_update)
        .replace("@IMAGE@", get_image),
    )

index_fn = function(INDEX, "static art_index_dir_t *artIndexBuild(")
if "errno = 0;" not in index_fn or "readError = errno;" not in index_fn:
    failures.append("Directory index must distinguish EOF from readdir I/O error")
if index_fn.find("if (readError != 0)") > index_fn.find("slot->valid = 1;"):
    failures.append("Incomplete index must be rejected before valid=1")

index_harness = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
typedef struct { int pos; } DIR;
struct dirent { char d_name[128]; };
#define LOG(...) ((void)0)
#define ART_INDEX_DIR_MAX 192
#define ART_INDEX_MAX_ENTRIES 4096
#define ART_INDEX_SLOTS 3
#define ART_INDEX_NAMES_MAX (128 * 1024)
typedef struct { unsigned int hash; int name; } art_index_pic_t;
typedef struct {
    char dir[ART_INDEX_DIR_MAX];
    unsigned int *hashes;
    int count;
    art_index_pic_t *pics;
    int picCount;
    char *names;
    int valid;
} art_index_dir_t;
static art_index_dir_t gArtIndex[ART_INDEX_SLOTS];
static int gArtIndexNext;
static unsigned int gArtIndexSweepFailed;
static int failRead;
static DIR directory;
static struct dirent returnedEntry;
static DIR *opendir(const char *path) { (void)path; directory.pos = 0; return &directory; }
static int closedir(DIR *dir) { (void)dir; return 0; }
static struct dirent *readdir(DIR *dir)
{
    if (dir->pos++ == 0) {
        strcpy(returnedEntry.d_name, "SLUS_123.45_COV.png");
        return &returnedEntry;
    }
    if (failRead)
        errno = EIO;
    return NULL;
}
static unsigned int artIndexHashN(const char *name, size_t n)
{
    unsigned int hash = 2166136261u;
    while (n-- > 0 && *name) {
        unsigned char c = (unsigned char)*name++;
        if (c >= 'a' && c <= 'z') c -= 32;
        hash = (hash ^ c) * 16777619u;
    }
    return hash;
}
static unsigned int artIndexHash(const char *name) { return artIndexHashN(name, (size_t)-1); }
static int artIndexPictureExt(const char *name)
{
    const char *dot = strrchr(name, '.');
    return (dot != NULL && dot != name && !strcmp(dot, ".png")) ? (int)(dot - name) : -1;
}
static int artIndexPicCmp(const void *a, const void *b)
{
    unsigned int left = ((const art_index_pic_t *)a)->hash, right = ((const art_index_pic_t *)b)->hash;
    return (left > right) - (left < right);
}
static int artIndexCmp(const void *a, const void *b)
{
    unsigned int left = *(const unsigned int *)a, right = *(const unsigned int *)b;
    return (left > right) - (left < right);
}
@INDEX@
int main(void)
{
    failRead = 1;
    art_index_dir_t *first = artIndexBuild("udpfs:/ART");
    if (first->valid || first->hashes || gArtIndexSweepFailed != 1) {
        fputs("Partial index was published or failure was not counted\n", stderr);
        return 1;
    }
    failRead = 0;
    art_index_dir_t *second = artIndexBuild("udpfs:/ART");
    if (!second->valid || !second->hashes || second->count != 1 || second->picCount != 1 || !second->names) {
        fputs("Complete index was not published\n", stderr);
        return 1;
    }
    puts("ART index: interrupted enumeration falls back; complete enumeration indexes normally");
    return 0;
}
"""
run_harness("ART negative index", index_harness.replace("@INDEX@", index_fn))

# Exercise the complete production cache lookup, including the ID fast path. A
# request retains the fail generation it was issued in when it completes late.
cache_source = (ROOT / "src/texcache.c").read_text(encoding="utf-8")
cache_header = (ROOT / "include/texcache.h").read_text(encoding="utf-8")
cache_types = cache_header[cache_header.index("typedef struct"):cache_header.index("} image_cache_t;") + len("} image_cache_t;")]
request_type = cache_source[cache_source.index("typedef struct load_image_request"):cache_source.index("} load_image_request_t;") + len("} load_image_request_t;")]
cache_harness = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { void *Mem, *Clut; int Vram, VramClut, ClutStorageMode; } GSTEXTURE;
typedef struct { int delay; } item_list_t;
@CACHE_TYPES@
@REQUEST_TYPE@
#define ART_MIN_SETTLE_FRAMES 8
#define GS_CLUT_STORAGE_CSM1 0
static unsigned int gArtFailEpoch = 1, gArtFocusEpoch = 1, gArtEpoch = 1;
static unsigned int gArtKeyTooLong;
static int guiFrameId = 10, guiInactiveFrames = 100;
static int gArtNavActive, gArtRunning = 1, gEnableArtTar;
static int enqueued;
static load_image_request_t *pending;
static void artUpdateFocus(item_list_t *list, const char *value) {}
static void artPromote(load_image_request_t *request) {}
static void cacheAbortOtherBackgrounds(image_cache_t *cache, const char *value) {}
static int cacheRequestIsSIO2(item_list_t *list, const char *value) { return 0; }
static int cacheResolveArtArchive(item_list_t *list, const char *value, char *path, size_t size) { return 0; }
static void rmUnloadTexture(GSTEXTURE *texture) {}
static void artPush(load_image_request_t *request) { pending = request; enqueued++; }
static void artPushFront(load_image_request_t *request) { artPush(request); }
static void cacheWakeArtWorker(void) {}
@CLEAR@
@INVALIDATE@
@GET_TEXTURE@
static void finish_missing(void)
{
    assert(pending != NULL);
    pending->entry->lastUsed = 0;
    pending->entry->failEpoch = pending->failEpoch;
    pending->entry->qr = NULL;
    pending->cache->activeRequests--;
    free(pending);
    pending = NULL;
}
int main(void)
{
    cache_entry_t entry = { .lastUsed = -1 };
    image_cache_t cache = { .count = 1, .suffix = "COV", .nextUID = 1, .content = &entry };
    item_list_t list = {0};
    int id = -1, uid = 0;
    char value[] = "SLUS_123.45";

    /* A row still holding its cache ID when the old request finishes must retry. */
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(enqueued == 1 && pending && pending->failEpoch == gArtFailEpoch);
    cacheInvalidateFailMemo();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(enqueued == 1); /* Keep the active request alive; do not duplicate it. */
    finish_missing();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(enqueued == 2 && pending && pending->failEpoch == gArtFailEpoch);

    /* A current-generation miss parks normally and does not retry every frame. */
    finish_missing();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(id == -2 && (unsigned int)uid == gArtFailEpoch);
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(enqueued == 2 && pending == NULL);

    /* A miss already parked on the row before discovery is also re-armed. */
    cacheInvalidateFailMemo();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 1) == NULL);
    assert(enqueued == 3 && pending && id == 0);
    finish_missing();

    /* A rebuilt row finds the same stale miss by value and re-probes once. */
    id = -1;
    uid = 0;
    cacheInvalidateFailMemo();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 0) == NULL);
    assert(enqueued == 4 && pending);
    finish_missing();

    /* Ready images survive invalidation and remain resident. */
    entry.lastUsed = guiFrameId;
    entry.texture.Mem = &entry;
    cacheInvalidateFailMemo();
    assert(cacheGetTextureEx(&cache, &list, &id, &uid, value, 1) == &entry.texture);
    assert(enqueued == 4 && pending == NULL && cache.activeRequests == 0);
    puts("ART cache: late failure, parked row, rebuilt row and resident texture generations pass");
    return 0;
}
"""
for placeholder, replacement in {
    "@CACHE_TYPES@": cache_types,
    "@REQUEST_TYPE@": request_type,
    "@CLEAR@": function(cache_source, "static void cacheClearItem("),
    "@INVALIDATE@": function(cache_source, "void cacheInvalidateFailMemo("),
    "@GET_TEXTURE@": function(cache_source, "GSTEXTURE *cacheGetTextureEx("),
}.items():
    cache_harness = cache_harness.replace(placeholder, replacement)
run_harness("ART cache fail generations", cache_harness)

if failures:
    print("UDPFS ART checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)
print("UDPFS ART regression checks passed")
