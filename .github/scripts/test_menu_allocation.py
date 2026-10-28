"""Compile real menu allocation paths and inject failures at every allocation."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/menusys.c").read_text(encoding="utf-8")

def function(signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError(signature)

functions = "\n\n".join(function(sig) for sig in (
    "static menu_list_t *AllocMenuItem(",
    "void menuAppendItem(",
    "void submenuRebuildCache(",
    "static submenu_list_t *submenuAllocItem(",
    "submenu_list_t *submenuAppendItem(",
    "void menuAddHint(",
))
program = r"""
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct menu_hint_item {
    int text_id, icon_id;
    struct menu_hint_item *next;
} menu_hint_item_t;
typedef struct menu_item {
    int rank;
    menu_hint_item_t *hints;
} menu_item_t;
typedef struct menu_list {
    menu_item_t *item;
    struct menu_list *prev, *next;
} menu_list_t;
typedef struct submenu_item {
    int icon_id;
    char *text;
    int text_id, id;
    int *cache_id, *cache_uid;
    int favourited, isFolder, lastPlayed;
} submenu_item_t;
typedef struct submenu_list {
    struct submenu_list *prev, *next;
    submenu_item_t item;
} submenu_list_t;
typedef struct { int gameCacheCount; } theme_t;
static theme_t theme;
static theme_t *gTheme = &theme;
static menu_list_t *menu, *selected_item;
static int menuListSemaId = 10, semaphoreDepth;
static int allocCount, failAt, live;
static int WaitSema(int id) { assert(id == menuListSemaId); semaphoreDepth++; return 0; }
static int SignalSema(int id) { assert(id == menuListSemaId && semaphoreDepth == 1); semaphoreDepth--; return 0; }
static int menuDevicePageRank(const menu_item_t *item) { return item->rank; }

static void *trackedMalloc(size_t n) {
    ++allocCount;
    if (failAt && allocCount == failAt) return NULL;
    void *ptr = malloc(n);
    if (ptr) live++;
    return ptr;
}
static void trackedFree(void *ptr) {
    if (ptr) {
        assert(live > 0);
        live--;
        free(ptr);
    }
}
#define malloc trackedMalloc
#define free trackedFree
@FUNCTIONS@
static void startFail(int at) { allocCount = 0; failAt = at; }
int main(void) {
    menu_item_t device1 = {1, NULL}, device2 = {0, NULL};
    submenu_list_t *entries = NULL;
    theme.gameCacheCount = 3;

    startFail(1);
    menuAppendItem(&device1);
    assert(menu == NULL && selected_item == NULL && semaphoreDepth == 0 && live == 0);
    startFail(0);
    menuAppendItem(&device1);
    assert(menu && selected_item == menu && semaphoreDepth == 0 && live == 1);
    startFail(1);
    menuAppendItem(&device2);
    assert(menu && menu->next == NULL && live == 1 && semaphoreDepth == 0);
    startFail(0);
    menuAppendItem(&device2);
    assert(menu->item == &device2 && menu->next->item == &device1);
    free(menu->next);
    free(menu);
    menu = selected_item = NULL;
    assert(live == 0);

    // Node allocation failure does not mutate an empty submenu.
    startFail(1);
    assert(submenuAppendItem(&entries, -1, NULL, 7, 8) == NULL);
    assert(entries == NULL && live == 0);

    // The index array or UID array may fail independently.
    for (int n = 2; n <= 3; n++) {
        startFail(n);
        entries = submenuAppendItem(&entries, -1, NULL, 7, 8);
        assert(entries && entries->item.cache_id == NULL && entries->item.cache_uid == NULL);
        assert(live == 1);
        free(entries);
        entries = NULL;
        assert(live == 0);
    }

    // Both valid art index arrays are initialized to -1.
    startFail(0);
    entries = submenuAppendItem(&entries, -1, NULL, 7, 8);
    assert(entries && live == 3);
    for (int i = 0; i < 3; i++) {
        assert(entries->item.cache_id[i] == -1 && entries->item.cache_uid[i] == -1);
    }
    // A theme switch on a half-allocated replacement must drop both old arrays.
    startFail(2);
    submenuRebuildCache(entries);
    assert(entries->item.cache_id == NULL && entries->item.cache_uid == NULL && live == 1);
    startFail(1);
    submenuRebuildCache(entries);
    assert(entries->item.cache_id == NULL && entries->item.cache_uid == NULL && live == 1);
    startFail(0);
    submenuRebuildCache(entries);
    assert(entries->item.cache_id && entries->item.cache_uid && live == 3);
    theme.gameCacheCount = 0;
    submenuRebuildCache(entries);
    assert(entries->item.cache_id == NULL && entries->item.cache_uid == NULL && live == 1);
    theme.gameCacheCount = 3;

    // Appending to a populated list never links a NULL successor on OOM.
    startFail(1);
    assert(submenuAppendItem(&entries, -1, NULL, 9, 10) == NULL);
    assert(entries->next == NULL && live == 1);
    startFail(0);
    submenu_list_t *next = submenuAppendItem(&entries, -1, NULL, 9, 10);
    assert(next && entries->next == next && next->prev == entries);
    free(next->item.cache_id);
    free(next->item.cache_uid);
    free(next);
    free(entries);
    assert(live == 0);

    startFail(1);
    menuAddHint(&device1, 100, 3);
    assert(device1.hints == NULL && live == 0);
    startFail(0);
    menuAddHint(&device1, 100, 3);
    assert(device1.hints && device1.hints->text_id == 100 && live == 1);
    free(device1.hints);
    assert(live == 0);
    puts("PASS: menu allocations fail without crashes, leaks or half-initialized art pairs");
    return 0;
}
""".replace("@FUNCTIONS@", functions)
with tempfile.TemporaryDirectory() as tmp:
    source_file = Path(tmp) / "test.c"
    exe = Path(tmp) / "test"
    source_file.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-parameter", str(source_file), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)
