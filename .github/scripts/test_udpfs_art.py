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
    pos = source.find(signature)
    if pos < 0:
        raise AssertionError(f"Missing function: {signature}")
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
typedef struct { int kind; int pos; } DIR;
struct dirent { char d_name[128]; };
typedef struct { int dummy; } item_list_t;
typedef struct { int dummy; } GSTEXTURE;

static char udpfsPrefix[40] = "udpfs:/";
static int udpfsIomanModLoaded = 1, serverOnline = 1;
static int invalidations, rootOpens, folderOpens, imageCalls;
static char imagePath[256];
static const char *rootNames[12];
static const char *folderNames[8][4];
static int rootReadError, folderOpenError[8];
static DIR rootDir, folders[8];
static struct dirent returnedEntry;

@TABLE@
static volatile unsigned int udpfsArtCaseIndex;
static int udpfsArtCaseChecked;

static int udpfsServerAnswers(void) { return serverOnline; }
static void cacheInvalidateFailMemo(void) { invalidations++; }
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
    }
    if (!name)
        return NULL;
    snprintf(returnedEntry.d_name, sizeof(returnedEntry.d_name), "%s", name);
    return &returnedEntry;
}
static int closedir(DIR *dir) { (void)dir; return 0; }
static int texDiscoverLoad(GSTEXTURE *tex, const char *path, int id)
{
    (void)tex; (void)id;
    imageCalls++;
    snprintf(imagePath, sizeof(imagePath), "%s", path);
    return 0;
}
@FOLDER@
@DISCOVER@
@IMAGE@

static int fails;
static void reset(void)
{
    memset(rootNames, 0, sizeof(rootNames));
    memset(folderNames, 0, sizeof(folderNames));
    memset(folderOpenError, 0, sizeof(folderOpenError));
    udpfsArtCaseIndex = 0;
    udpfsArtCaseChecked = invalidations = rootOpens = folderOpens = imageCalls = 0;
    rootReadError = 0;
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
    reset();
    rootNames[0] = "ART";
    udpfsDiscoverArtFolder();
    check("canonical case", udpfsArtCaseChecked && udpfsArtCaseIndex == 0 &&
          invalidations == 0 && folderOpens == 0 && rootOpens == 1);

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
          invalidations == 0 && folderOpens == 1);

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
    serverOnline = 0;
    udpfsDiscoverArtFolder();
    check("offline share does not latch", !udpfsArtCaseChecked && rootOpens == 0);
    serverOnline = 1;
    udpfsDiscoverArtFolder();
    check("fresh share retains ART default", udpfsArtCaseChecked && udpfsArtCaseIndex == 0);

    if (!fails)
        puts("UDPFS ART: canonical, lowercase, duplicate casing, incomplete scan and zero per-image I/O pass");
    return fails ? 1 : 0;
}
"""
    run_harness(
        "UDPFS ART resolver",
        casing_harness.replace("@TABLE@", table.group(0))
        .replace("@FOLDER@", folder_files)
        .replace("@DISCOVER@", discover)
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
typedef struct {
    char dir[ART_INDEX_DIR_MAX];
    unsigned int *hashes;
    int count, valid;
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
static unsigned int artIndexHash(const char *name)
{
    unsigned int hash = 2166136261u;
    while (*name) {
        unsigned char c = (unsigned char)*name++;
        if (c >= 'a' && c <= 'z') c -= 32;
        hash = (hash ^ c) * 16777619u;
    }
    return hash;
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
    if (!second->valid || !second->hashes || second->count != 1) {
        fputs("Complete index was not published\n", stderr);
        return 1;
    }
    puts("ART index: interrupted enumeration falls back; complete enumeration indexes normally");
    return 0;
}
"""
run_harness("ART negative index", index_harness.replace("@INDEX@", index_fn))

if failures:
    print("UDPFS ART checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)
print("UDPFS ART regression checks passed")
