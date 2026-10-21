"""Run the actual language registration code on the host.

Covers dynamic growth, strict file names, case-insensitive deduplication,
CWD precedence, and slash/colon handling without requiring a PS2 SDK.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/lang.c").read_text(encoding="utf-8")
start = source.index("static int lngEnsureCapacity(int count)\n{")
end = source.index("static void lngRebuildLangNames(void)", start)
registration = source[start:end]

harness = r"""
#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#define DT_DIR 4
#define DT_REG 8
typedef struct {
    char *filePath;
    char *name;
    unsigned char sourcePriority;
} language_t;
static int nLanguages, languageCapacity, scanFoundFiles;
static unsigned char scanPriority;
static language_t *languages;
/* The GUI lock: the GUI thread reads the registry while the IO worker adds to it, so the array may
   only move while the lock is held, and taking it twice would deadlock the PS2. */
static int guiLockDepth, guiLockTaken;
static void guiLock(void)
{
    assert(guiLockDepth == 0);
    guiLockDepth++;
    guiLockTaken++;
}
static void guiUnlock(void)
{
    assert(guiLockDepth == 1);
    guiLockDepth--;
}
static void *lockedRealloc(void *block, size_t size)
{
    assert(guiLockDepth == 1);
    return realloc(block, size);
}
#define realloc(block, size) lockedRealloc(block, size)
""" + registration + r"""
static int scan(int priority, const char *path, const char *separator,
                const char *const *names, int count)
{
    int added = 0;
    scanFoundFiles = 0;
    scanPriority = priority;
    for (int i = 0; i < count; i++)
        added = lngReadEntry(added, path, separator, names[i], DT_REG);
    nLanguages += added;
    return scanFoundFiles;
}
int main(void)
{
    const char *legacy[] = {"lang_French.lng", "lang_German.lng",
                            "bad_French.lng", "lang_.lng", "lang_French.lng.bak"};
    assert(scan(0, "mass0:/LNG", "/", legacy, 5) == 2);
    assert(nLanguages == 2);
    assert(strcmp(languages[0].filePath, "mass0:/LNG/lang_French.lng") == 0);

    const char *cwd[] = {"lang_French.lng", "LANG_SPANISH.LNG"};
    assert(scan(2, "mass1:/APPS/RIPTOPL/", "/", cwd, 2) == 2);
    assert(nLanguages == 3);
    assert(strcmp(languages[0].filePath, "mass1:/APPS/RIPTOPL/lang_French.lng") == 0);
    assert(languages[0].sourcePriority == 2);

    const char *cwdLangs[] = {"lang_French.lng", "lang_German.lng"};
    assert(scan(1, "mass1:/APPS/RIPTOPL/LNG", "/", cwdLangs, 2) == 2);
    assert(nLanguages == 3);
    assert(strcmp(languages[0].filePath, "mass1:/APPS/RIPTOPL/lang_French.lng") == 0);
    assert(strcmp(languages[1].filePath, "mass1:/APPS/RIPTOPL/LNG/lang_German.lng") == 0);

    // Colon-relative legacy MC paths and case-insensitive duplicate names.
    const char *card[] = {"lang_german.lng", "lang_Italian.lng"};
    assert(scan(0, "mc0:OPL", "/", card, 2) == 2);
    assert(nLanguages == 4);
    assert(strcmp(languages[1].filePath, "mass1:/APPS/RIPTOPL/LNG/lang_German.lng") == 0);
    assert(strcmp(languages[3].filePath, "mc0:OPL/lang_Italian.lng") == 0);

    // More than 15, including more than 32, without displacing existing names.
    for (int i = 0; i < 64; i++) {
        char file[40];
        snprintf(file, sizeof(file), "lang_Extra%02d.lng", i);
        const char *files[] = {file};
        assert(scan(0, "mass2:/LNG", "/", files, 1) == 1);
    }
    assert(nLanguages == 68);
    assert(languageCapacity >= nLanguages);
    assert(strcmp(languages[0].filePath, "mass1:/APPS/RIPTOPL/lang_French.lng") == 0);
    assert(guiLockDepth == 0 && guiLockTaken > 0);

    for (int i = 0; i < nLanguages; i++) {
        free(languages[i].name);
        free(languages[i].filePath);
    }
    free(languages);
    return 0;
}
"""

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    program = path / "test.c"
    exe = path / "test"
    program.write_text(harness, encoding="utf-8")
    subprocess.run(
        ["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(program), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
print("Language discovery tests passed")
