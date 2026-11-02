#!/usr/bin/env python3
"""A language switch never leaves a Settings page reading freed text, and an unsaved pick outlives a device.

A switch publishes the new string table and frees the old one. Settings pages kept _l() pointers in their enum
lists, and the Settings Index in its label array, and drew them in later frames, while the IO worker switched the
language behind them: a device bringing its LNG folder made lngPublishLanguages apply the saved language again over
a Language-page pick that was not saved yet, which reverted the pick and freed the strings on screen. The rows now
name their strings by id (diaSetEnumIds), looked up in each frame, and the publish leaves a pick alone
(lngSetUserPick).

Compiles the real src/lang.c, whole, with host stand-ins for what it calls and the English table and string ids that
tools/lang_compiler.py makes from lng_tmpl/_base.yml, together with dia.c's enum text (diaEnumValueText,
diaEnumText), gui.c's Settings Index (guiSettingsShowIndex) and every enum list gui.c and guigame.c give
diaSetEnumIds with static arrays. Each scenario runs in its own process:

1. picked: boot applies the saved German, the Language page applies French without saving, then a device brings its
   LNG folder while the Index is drawn. French stays, the publish switches nothing, and every enum row and Index
   label reads French.
2. deferred: the saved German's .lng is not there at boot, so English shows; a device brings it while the Index is
   drawn, and the publish applies it.
3. switch: the language changes while the Index is drawn (the saved German applied over the French pick, what the
   publish did before, and what a settings load on the IO worker does): the next frame reads German, and the French
   table really was freed.

lang.c's free() keeps a block allocated and overwrites it with "FREED", so reading freed text fails every time,
without a sanitizer. --asan builds everything with -fsanitize=address and a real free() instead.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ASAN = "--asan" in sys.argv[1:]
failures = []


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def function(source, where, pattern):
    """The definition whose first line matches `pattern`, through its closing brace."""
    match = re.search(pattern, source, re.M)
    if not match:
        failures.append("%s: no %s" % (where, pattern))
        return ""
    end = source.find("\n}\n", match.end())
    return source[match.start():end + 3]


gui = read("src/gui.c")
guigame = read("src/guigame.c")
dia = read("src/dia.c")
dia_h = read("include/dia.h")
opl = read("src/opl.c")

# The harness takes the steps these call sites take, in their order -------------------------------------------
language_page = function(gui, "src/gui.c", r"^static int guiSettingsShowLanguage\(")
if not re.search(r"lngSetUserPick\(1\);\s*applyConfig\(-1, langID, 1\);", language_page):
    failures.append("src/gui.c: the Language page does not flag its pick (lngSetUserPick(1)) before applying it")
if not re.search(r"if \(langID >= 0\)\s*lngSetUserPick\(0\);\s*applyConfig\(themeID, langID, 0\);", opl):
    failures.append("src/opl.c: the settings load does not clear the pick (lngSetUserPick(0)) as it applies the "
                    "saved language")
if "int langChanged = lngSetGuiValue(langID);" not in function(opl, "src/opl.c", r"^void applyConfig\("):
    failures.append("src/opl.c: applyConfig no longer switches the language with lngSetGuiValue")

# The real code the harness runs ------------------------------------------------------------------------------
types = "\n".join(re.search(pattern, dia_h, re.M | re.S).group(0)
                  for pattern in (r"^typedef enum \{.*?\} UIItemType;", r"^struct UIItem\s*\{.*?^\};"))
resolver = "".join(function(dia, "src/dia.c", r"^static const char \*%s\(" % name)
                   for name in ("diaEnumValueText", "diaEnumText"))
pages = re.search(r"^enum gui_settings_page \{.*?\};", gui, re.M | re.S).group(0)
index = function(gui, "src/gui.c", r"^static int guiSettingsShowIndex\(")

# Every enum list given with static arrays: the arrays as written, under names of their own
headers = {path.name: path.read_text(encoding="utf-8") for path in sorted((ROOT / "include").glob("*.h"))}
lists, entries, enums = [], [], []
for rel, source in (("src/gui.c", gui), ("src/guigame.c", guigame)):
    for call in re.finditer(r"diaSetEnumIds\(\s*\w+,\s*(\w+),\s*(\w+),\s*(\w+)\);", source):
        row, names, ids = call.groups()
        before = source[:call.start()]
        name_decl = list(re.finditer(r"static const char \*" + names + r"(\[[^\]]*\]) = (\{.*?\});", before, re.S))
        id_decl = list(re.finditer(r"static const int " + ids + r"(\[[^\]]*\]) = (\{.*?\});", before, re.S))
        if not name_decl or not id_decl:
            continue  # filled at run time or handed in: not a list this check can rebuild
        n = len(lists)
        text = ("static const char *list%d_names%s = %s;\nstatic const int list%d_ids%s = %s;\n"
                % (n, name_decl[-1].group(1), name_decl[-1].group(2), n, id_decl[-1].group(1), id_decl[-1].group(2)))
        # enumerators an array uses for its size or a designator (THM_VIEW_PICK_*, VCD_BDMA_*)
        for ident in set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", re.sub(r'"(?:[^"\\]|\\.)*"', '""', text))) - {"NULL"}:
            if any(ident in block for block in enums):
                continue
            for header in headers.values():
                block = next((m.group(0) for m in re.finditer(r"^enum\s*\w*\s*\{.*?^\};", header, re.M | re.S)
                              if re.search(r"\b" + ident + r"\b", m.group(0))), None)
                if block:
                    enums.append(block)
                    break
        lists.append(text)
        entries.append('{"%s", "%s", list%d_names, list%d_ids, (int)(sizeof(list%d_ids) / sizeof(list%d_ids[0]))}'
                       % (rel, row, n, n, n, n))
if len(lists) < 40:
    failures.append("only %d enum lists with static arrays found in src/gui.c and src/guigame.c" % len(lists))

STAND_INS = r'''
/* Host stand-ins for what src/lang.c calls outside itself, and the allocator its heap goes through. */
#include <dirent.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/util.h"

void fail(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    fputs("FAIL: ", stdout);
    vprintf(fmt, args);
    fputs("\n", stdout);
    va_end(args);
    fflush(stdout);
    exit(1);
}

/* A block carries its size. free() keeps it allocated and fills it with "FREED", and remembers where it was, so a
   later read of freed text is caught every time. With TEST_REAL_FREE (the -fsanitize=address build) it is freed. */
#define BLOCK_LIVE 0x4c495645u
#define BLOCK_FREED 0x44454144u
typedef union
{
    struct
    {
        size_t size;
        unsigned magic;
    } h;
    long double align1;
    void *align2;
    long long align3;
} header_t;

int gFreedBlocks;
#ifndef TEST_REAL_FREE
static struct { const char *start; size_t size; } *freedList;
static int freedCount, freedCapacity;
#endif

void *testMalloc(size_t size)
{
    header_t *h = malloc(sizeof(*h) + (size ? size : 1));
    if (h == NULL)
        return NULL;
    h->h.size = size;
    h->h.magic = BLOCK_LIVE;
    return h + 1;
}

void *testCalloc(size_t count, size_t size)
{
    if (size && count > (size_t)-1 / size)
        return NULL;
    void *block = testMalloc(count * size);
    if (block)
        memset(block, 0, count * size);
    return block;
}

char *testStrdup(const char *text)
{
    size_t size = strlen(text) + 1;
    char *copy = testMalloc(size);
    if (copy)
        memcpy(copy, text, size);
    return copy;
}

void testFree(void *block)
{
    if (block == NULL)
        return;
    header_t *h = (header_t *)block - 1;
    if (h->h.magic != BLOCK_LIVE)
        fail("lang.c frees %s", h->h.magic == BLOCK_FREED ? "a block twice" : "memory it never allocated");
    h->h.magic = BLOCK_FREED;
    gFreedBlocks++;
#ifdef TEST_REAL_FREE
    free(h);
#else
    char *bytes = block;
    for (size_t i = 0; i < h->h.size; i++)
        bytes[i] = "FREED"[i % 5];
    if (h->h.size)
        bytes[h->h.size - 1] = '\0';
    if (freedCount == freedCapacity) {
        freedCapacity = freedCapacity ? 2 * freedCapacity : 1024;
        freedList = realloc(freedList, freedCapacity * sizeof(*freedList));
        if (freedList == NULL)
            fail("out of memory");
    }
    freedList[freedCount].start = block;
    freedList[freedCount].size = h->h.size;
    freedCount++;
#endif
}

void *testRealloc(void *block, size_t size)
{
    if (block == NULL)
        return testMalloc(size);
    header_t *h = (header_t *)block - 1;
    void *moved = testMalloc(size);
    if (moved == NULL)
        return NULL;
    memcpy(moved, block, h->h.size < size ? h->h.size : size);
    testFree(block);
    return moved;
}

/* 1: text lies in a block lang.c freed (the -fsanitize=address build leaves this to the sanitizer) */
int testIsFreed(const void *text)
{
#ifdef TEST_REAL_FREE
    (void)text;
#else
    for (int i = 0; i < freedCount; i++) {
        const char *start = freedList[i].start;
        if ((const char *)text >= start && (const char *)text < start + (freedList[i].size ? freedList[i].size : 1))
            return 1;
    }
#endif
    return 0;
}

/* The locks. The GUI lock and the language switch lock (lngSwitchSema) are not recursive, and the switch lock is
   never taken under the GUI lock (lock order: language switch, theme switch, GUI lock). */
int gGuiLockDepth, gSwitchDepth;
static int switchSema = -1;
void guiLock(void)
{
    if (gGuiLockDepth != 0)
        fail("the GUI lock is taken twice");
    gGuiLockDepth++;
}
void guiUnlock(void)
{
    if (gGuiLockDepth != 1)
        fail("the GUI lock is released without being held");
    gGuiLockDepth--;
}
int sbCreateSemaphore(void) { return switchSema = 7; }
int WaitSema(int id)
{
    if (id != switchSema || gSwitchDepth != 0 || gGuiLockDepth != 0)
        fail("the language switch lock is taken twice, or under the GUI lock");
    gSwitchDepth++;
    return id;
}
int SignalSema(int id)
{
    if (id != switchSema || gSwitchDepth != 1)
        fail("the language switch lock is released without being held");
    gSwitchDepth--;
    return id;
}

/* What a switch does besides the strings */
int gMenuUpdates, gThemeReloads;
void bgmMute(void) {}
void bgmUnMute(void) {}
int thmReload(void)
{
    if (gGuiLockDepth != 0 || gSwitchDepth != 1)
        fail("the theme reloads outside the language switch lock, or under the GUI lock");
    gThemeReloads++;
    return 1;
}
int fntLoadDefault(char *path) { (void)path; return -1; }
int fntLoadFallback(char *path) { (void)path; return -1; }
void fntInit(void) {}
void fntEnd(void) {}
void moduleUpdateMenu(int mode, int themeChanged, int langChanged)
{
    (void)mode;
    if (themeChanged != 0 || langChanged != 1)
        fail("moduleUpdateMenu(%d, %d, %d) after a language publish", mode, themeChanged, langChanged);
    gMenuUpdates++;
}

/* The settings: language_text in memory, as a settings load leaves it (only a save writes it) */
char gBootDir[256];
char *gBaseMCDir;
const char *gSavedLanguage;
typedef struct config_set config_set_t;
struct config_set
{
    int unused;
};
static struct config_set configOPL;
config_set_t *configGetByType(int type)
{
    (void)type;
    return &configOPL;
}
int configGetStr(config_set_t *configSet, const char *key, const char **value)
{
    if (configSet != &configOPL || strcmp(key, "language_text") != 0 || gSavedLanguage == NULL)
        return 0;
    *value = gSavedLanguage;
    return 1;
}
const char *configGetHomePath(void) { return ""; }

/* util.c's directory list and line reader. A line is the reader's own copy (allocResult), from the allocator
   above, because lang.c frees each one; '#' lines are comments. */
int listDir(char *path, const char *separator, int maxElem,
            int (*readEntry)(int index, const char *path, const char *separator, const char *name, unsigned char d_type))
{
    int index = 0;
    DIR *dir = opendir(path);
    struct dirent *entry;
    if (dir == NULL)
        return 0;
    while (index < maxElem && (entry = readdir(dir)) != NULL)
        index = readEntry(index, path, separator, entry->d_name, DT_REG);
    closedir(dir);
    return index;
}
file_buffer_t *openFileBuffer(char *fpath, int mode, short allocResult, unsigned int size)
{
    (void)mode;
    (void)size;
    if (!allocResult)
        fail("a language table must own its lines");
    FILE *fp = fopen(fpath, "rb");
    if (fp == NULL)
        return NULL;
    file_buffer_t *buffer = malloc(sizeof(*buffer));
    buffer->fp = fp;
    return buffer;
}
int readFileBuffer(file_buffer_t *readContext, char **outBuf)
{
    char line[1024];
    while (fgets(line, sizeof(line), readContext->fp) != NULL) {
        size_t length = strcspn(line, "\r\n");
        line[length] = '\0';
        if (line[0] == '#')
            continue;
        *outBuf = testMalloc(length + 1);
        memcpy(*outBuf, line, length + 1);
        return 1;
    }
    return 0;
}
int closeFileBuffer(file_buffer_t *fileBuffer)
{
    fclose(fileBuffer->fp);
    free(fileBuffer);
    return 0;
}
'''

HEADERS = {
    "opl.h": r'''
/* Host stand-in for include/opl.h: what src/lang.c takes from it and the headers it brings in. */
#ifndef TEST_OPL_H
#define TEST_OPL_H
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#define LOG(...) ((void)0)
extern char *gBaseMCDir;
extern char gBootDir[256];
typedef struct config_set config_set_t;
#define CONFIG_OPL 1
config_set_t *configGetByType(int type);
int configGetStr(config_set_t *configSet, const char *key, const char **value);
const char *configGetHomePath(void);
void moduleUpdateMenu(int mode, int themeChanged, int langChanged);
int WaitSema(int id);
int SignalSema(int id);
/* lang.c's heap goes through the test allocator: free() keeps the block and overwrites it */
void *testMalloc(size_t size);
void *testCalloc(size_t count, size_t size);
void *testRealloc(void *block, size_t size);
char *testStrdup(const char *text);
void testFree(void *block);
#define malloc(size) testMalloc(size)
#define calloc(count, size) testCalloc(count, size)
#define realloc(block, size) testRealloc(block, size)
#define strdup(text) testStrdup(text)
#define free(block) testFree(block)
#endif
''',
    "util.h": r'''
#ifndef TEST_UTIL_H
#define TEST_UTIL_H
#include <stdio.h>
typedef struct
{
    FILE *fp;
} file_buffer_t;
int listDir(char *path, const char *separator, int maxElem,
            int (*readEntry)(int index, const char *path, const char *separator, const char *name, unsigned char d_type));
file_buffer_t *openFileBuffer(char *fpath, int mode, short allocResult, unsigned int size);
int readFileBuffer(file_buffer_t *readContext, char **outBuf);
int closeFileBuffer(file_buffer_t *fileBuffer);
#endif
''',
    "fntsys.h": "int fntLoadFallback(char *path);\nint fntLoadDefault(char *path);\nvoid fntInit(void);\nvoid fntEnd(void);\n",
    "ioman.h": "\n",
    "themes.h": "int thmReload(void);\n",
    "sound.h": "void bgmMute(void);\nvoid bgmUnMute(void);\n",
    "gui.h": "void guiLock(void);\nvoid guiUnlock(void);\n",
    "supportbase.h": "int sbCreateSemaphore(void);\n",
}

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/lang.h"

void fail(const char *fmt, ...);
int testIsFreed(const void *text);
void guiLock(void);
void guiUnlock(void);
extern int gGuiLockDepth, gSwitchDepth, gMenuUpdates, gThemeReloads, gFreedBlocks;
extern char *gBaseMCDir;
extern const char *gSavedLanguage;

typedef unsigned long long u64;
@TYPES@
@RESOLVER@

/* The language every string on screen must be in: its name, or NULL for the internal English */
static const char *want;

static void expectLive(const char *what, const char *text)
{
    if (text == NULL)
        fail("%s: no text", what);
#ifndef TEST_REAL_FREE
    if (testIsFreed(text) || strncmp(text, "FREED", 5) == 0)
        fail("%s reads freed memory", what);
#endif
    if (want == NULL) {
        for (int i = 0; i < LANG_STR_COUNT; i++)
            if (text == internalEnglish[i])
                return;
        fail("%s reads \"%s\", not the internal English", what, text);
    }
    size_t length = strlen(want);
    if (strncmp(text, want, length) != 0 || text[length] != ' ')
        fail("%s reads \"%s\", not %s", what, text, want);
}

/* Every enum list the Settings pages give diaSetEnumIds with static arrays */
@ENUMS@
@LISTS@
static const struct
{
    const char *where, *row, **names;
    const int *ids;
    int idCount;
} lists[] = {
@ENTRIES@
};

/* One dialog frame: under the GUI lock, every row of every list, through dia.c's enum text */
static int enumRows;
static void enumFrame(void)
{
    char what[160];
    enumRows = 0;
    guiLock();
    for (int l = 0; l < (int)(sizeof(lists) / sizeof(lists[0])); l++) {
        int count = 0;
        while (lists[l].names[count] != NULL)
            count++;
        if (count != lists[l].idCount)
            fail("%s: %s has %d rows and %d string ids", lists[l].where, lists[l].row, count, lists[l].idCount);
        for (int i = 0; i < count; i++) {
            struct UIItem item;
            memset(&item, 0, sizeof(item));
            item.type = UI_ENUM;
            item.intvalue.enumvalues = lists[l].names;
            item.intvalue.enumids = lists[l].ids;
            item.intvalue.current = i;
            const char *text = diaEnumText(&item);
            snprintf(what, sizeof(what), "%s: %s row %d", lists[l].where, lists[l].row, i);
            if (lists[l].ids[i] < 0) {
                if (text != lists[l].names[i] || text[0] == '\0')
                    fail("%s shows \"%s\", not its own text", what, text);
            } else {
                if (text != _l(lists[l].ids[i]))
                    fail("%s shows \"%s\", not the string its id names", what, text);
                expectLive(what, text);
            }
            enumRows++;
        }
    }
    guiUnlock();
}

/* The Settings Index, as gui.c has it: three frames, the IO worker running once between the first two (the GUI
   thread waits for the vertical blank there, with the GUI lock released), then Cross on the first page */
@PAGES@
#define ALIGN_CENTER 1
#define OPL_VERSION "host"
enum { KEY_UP = 1, KEY_DOWN, KEY_START, KEY_CROSS, KEY_CIRCLE };
enum { SFX_CURSOR, SFX_CONFIRM, SFX_CANCEL };
enum { SETTINGS_PROMPT_SAVE = 1, SETTINGS_PROMPT_EXIT };
static struct { int fonts[1]; int usedHeight; u64 textColor, selTextColor; } theme = {{0}, 448, 1, 2}, *gTheme = &theme;
static int screenWidth = 640, guiSettingsSavePending, frame, labels;
static void (*ioWorker)(void);
static void guiStartFrame(void) { guiLock(); }
static void guiEndFrame(void)
{
    guiUnlock();
    if (frame++ == 0 && ioWorker != NULL)
        ioWorker();
}
static int guiDrawBGSettings(void) { return 1; }
static void guiDrawBGPlasma(void) {}
static void guiDrawSettingsIndexHints(void) {}
static void readPads(void) {}
static int getKey(int key) { (void)key; return 0; }
static int getKeyOn(int key) { return key == KEY_CROSS && frame == 3; }
static int guiConfirmKey(void) { return KEY_CROSS; }
static int guiCancelKey(void) { return KEY_CIRCLE; }
static void sfxPlay(int id) { (void)id; }
static int menuSaveSettings(void) { fail("the Index saved"); return 0; }
static int guiSettingsPromptSave(void) { fail("the Index prompted"); return 0; }
static void hddDiscardOplHomeSelection(void) {}
static int fntRenderString(int id, int x, int y, short aligned, size_t width, size_t height, const char *string, u64 colour)
{
    (void)id; (void)x; (void)y; (void)aligned; (void)width; (void)height; (void)colour;
    if (gGuiLockDepth != 1)
        fail("the Index draws outside its frame");
    if (strncmp(string, "RiptOPL ", 8) == 0)
        return 0; /* the version line */
    expectLive("a Settings Index label", string);
    labels++;
    return 0;
}
@INDEX@

static void showIndex(void (*worker)(void))
{
    int page = SETTINGS_SOURCES;
    frame = labels = 0;
    ioWorker = worker;
    if (guiSettingsShowIndex(&page) != 1 || page != SETTINGS_SOURCES || frame != 3)
        fail("the Index did not take Cross on its first page after three frames");
    if (labels != 3 * (SETTINGS_PAGE_COUNT + 2))
        fail("the Index drew %d labels in three frames", labels);
}

/* The steps the code takes, in its order (the test checks the call sites) */
static char *deviceDir;
static void settingsLoad(const char *saved) /* _loadConfig: the saved language_text, then applyConfig */
{
    gSavedLanguage = saved;
    int langID = lngFindGuiID(saved);
    if (langID >= 0)
        lngSetUserPick(0);
    lngSetGuiValue(langID);
}
static void languagePagePick(const char *name) /* guiSettingsShowLanguage: flag the pick, then applyConfig */
{
    int langID = lngFindGuiID(name);
    if (langID <= 0)
        fail("%s is not listed", name);
    lngSetUserPick(1);
    if (lngSetGuiValue(langID) != 1)
        fail("the pick did not switch to %s", name);
}
static void devicePublish(void) /* a device's LNG folder on the IO worker (ethsupport.c, bdmsupport.c, ...) */
{
    if (lngAddLanguages(deviceDir, "/", 3) != 1)
        fail("the device's LNG folder was not read");
}
static void deviceBringsSaved(void)
{
    devicePublish();
    want = "German";
}
static void ioSettingsLoad(void) /* the saved language applied over the pick while the Index is up */
{
    settingsLoad("German");
    want = "German";
}

static void expectLanguage(const char *name)
{
    const char *live = lngGetValue();
    if (strcmp(live, name) != 0)
        fail("the language on screen is %s, not %s", live, name);
}

int main(int argc, char **argv)
{
    if (argc != 4)
        fail("usage: %s picked|deferred|switch <boot LNG folder> <device LNG folder>", argv[0]);
    gBaseMCDir = argv[2];
    deviceDir = argv[3];
    lngInit();

    if (strcmp(argv[1], "picked") == 0) {
        settingsLoad("German");
        expectLanguage("German");
        languagePagePick("French");
        want = "French";
        enumFrame();
        const char *french = _l(_STR_SETTINGS);
        int updates = gMenuUpdates, reloads = gThemeReloads;
        showIndex(devicePublish);
        if (lngFindGuiID("Spanish") <= 0)
            fail("the device's language is not listed");
        expectLanguage("French");
        if (gMenuUpdates != updates || gThemeReloads != reloads || _l(_STR_SETTINGS) != french)
            fail("the publish switched the language over the pick");
        enumFrame();
        printf("picked: French stays after a device's LNG folder; %d enum rows and the Index read it\n", enumRows);
    } else if (strcmp(argv[1], "deferred") == 0) {
        settingsLoad("German");
        if (lngFindGuiID("German") != 0)
            fail("German is there at boot");
        expectLanguage("English (internal)");
        want = NULL;
        enumFrame();
        showIndex(deviceBringsSaved);
        expectLanguage("German");
        if (gMenuUpdates != 1)
            fail("the menus were refreshed %d times for the deferred language", gMenuUpdates);
        enumFrame();
        printf("deferred: the saved German applies when its LNG folder comes; %d enum rows and the Index read it\n",
               enumRows);
    } else if (strcmp(argv[1], "switch") == 0) {
        settingsLoad("German");
        languagePagePick("French");
        want = "French";
        enumFrame();
        const char *stale = _l(_STR_SETTINGS);
        int freed = gFreedBlocks;
        showIndex(ioSettingsLoad);
        expectLanguage("German");
        if (gFreedBlocks < freed + LANG_STR_COUNT)
            fail("the French table was not freed (%d blocks)", gFreedBlocks - freed);
#ifndef TEST_REAL_FREE
        if (!testIsFreed(stale) || strncmp(stale, "FREED", 5) != 0)
            fail("a pointer kept from the French table does not read as freed");
#endif
        (void)stale;
        enumFrame();
        printf("switch: the frame after a switch reads German; %d enum rows and the Index read it\n", enumRows);
    } else {
        fail("no scenario %s", argv[1]);
    }
    if (gGuiLockDepth != 0 || gSwitchDepth != 0)
        fail("a lock is still held");
    return 0;
}
'''


def write_lng(folder, name, count):
    """A stand-in translation: line i is "<name> i", which takes no printf arguments."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("lang_%s.lng" % name)).write_text("".join("%s %d\n" % (name, i) for i in range(count)),
                                                 encoding="utf-8")


def main():
    compiler = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc")
    if not compiler:
        failures.append("no C compiler")
    if failures:
        for line in failures:
            print("FAIL: " + line)
        return 1

    program = (HARNESS.replace("@TYPES@", types).replace("@RESOLVER@", resolver).replace("@ENUMS@", "\n".join(enums))
               .replace("@LISTS@", "".join(lists)).replace("@ENTRIES@", ",\n".join(entries))
               .replace("@PAGES@", pages).replace("@INDEX@", index))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        include = tmp / "include"
        include.mkdir()
        for name, text in HEADERS.items():
            (include / name).write_text(text, encoding="utf-8")
        shutil.copy(ROOT / "include/lang.h", include / "lang.h")
        compiler_py = [sys.executable, str(ROOT / "tools/lang_compiler.py")]
        base = ["--base", str(ROOT / "lng_tmpl/_base.yml")]
        subprocess.run(compiler_py + ["--make_header"] + base + [str(include / "lang_autogen.h")], check=True,
                       capture_output=True)
        subprocess.run(compiler_py + ["--make_source"] + base + [str(tmp / "lang_internal.c")], check=True,
                       capture_output=True)
        header = (include / "lang_autogen.h").read_text(encoding="utf-8")
        count = len(re.findall(r"^\s*_STR_\w+", header.split("LANG_STR_COUNT")[0], re.M))
        (tmp / "stand_ins.c").write_text(STAND_INS, encoding="utf-8")
        (tmp / "harness.c").write_text(program, encoding="utf-8")

        write_lng(tmp / "both", "German", count)
        write_lng(tmp / "both", "French", count)
        write_lng(tmp / "french", "French", count)
        write_lng(tmp / "spanish", "Spanish", count)
        write_lng(tmp / "german", "German", count)

        exe = tmp / ("harness.exe" if os.name == "nt" else "harness")
        flags = ["-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function", "-I", str(tmp), "-I", str(include)]
        if ASAN:
            flags += ["-g", "-fsanitize=address", "-fno-omit-frame-pointer", "-DTEST_REAL_FREE"]
        build = subprocess.run([compiler] + flags + [str(ROOT / "src/lang.c"), str(tmp / "lang_internal.c"),
                                                     str(tmp / "stand_ins.c"), str(tmp / "harness.c"), "-o", str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append("the harness did not build:\n" + build.stderr)
        else:
            env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0")
            for scenario, boot, device in (("picked", "both", "spanish"), ("deferred", "french", "german"),
                                           ("switch", "both", "spanish")):
                run = subprocess.run([str(exe), scenario, str(tmp / boot), str(tmp / device)], capture_output=True,
                                     text=True, timeout=60, env=env)
                sys.stdout.write(run.stdout)
                if run.returncode != 0:
                    failures.append("%s (exit %d)%s" % (scenario, run.returncode,
                                                        ("\n" + run.stderr[-3000:]) if run.stderr else ""))

    for line in failures:
        print("FAIL: " + line)
    if failures:
        return 1
    print("language live text: %d enum lists and the Settings Index read live text through a switch; an unsaved "
          "pick outlives a device's LNG folder; the saved language still applies when it arrives late%s"
          % (len(lists), " (AddressSanitizer)" if ASAN else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
