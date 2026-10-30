"""Compile real queue-count and submenu-removal routines; check GUI append OOM guard."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
io = (root / "src/ioman.c").read_text(encoding="utf-8")
menu = (root / "src/menusys.c").read_text(encoding="utf-8")
gui = (root / "src/gui.c").read_text(encoding="utf-8")

def body(src, signature):
    pos = src.index(signature)
    brace = src.index("{", pos)
    balance = 0
    for end in range(brace, len(src)):
        balance += (src[end] == "{") - (src[end] == "}")
        if balance == 0:
            return src[pos:end + 1]
    raise AssertionError("unterminated function: " + signature)

queue_fn = body(io, "int ioGetPendingRequestCount(void)")
remove_fn = body(menu, "void submenuRemoveItem(")
destroy_fn = body(menu, "static void submenuDestroyItem(")

assert queue_fn.index("WaitSema(gProcSemaId)") < queue_fn.index("= gReqList;")
append_start = gui.index("case GUI_OP_APPEND_MENU:")
append_end = gui.index("case GUI_OP_SELECT_MENU:", append_start)
append = gui[append_start:append_end]
assert "if (result == NULL)" in append and "break;" in append
assert append.index("if (result == NULL)") < append.index("->last = result")
assert append.index("if (result == NULL)") < append.index("->current = result")

program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct io_request_t {
    int type;
    void *data;
    struct io_request_t *next;
} io_request_t;
static io_request_t old = {0}, head = {0}, tail = {0};
static io_request_t *gReqList;
static int gProcSemaId = 5, lockHeld = 0, mutateOnLock = 0;
static int WaitSema(int id) {
    assert(id == gProcSemaId && !lockHeld);
    if (mutateOnLock) {
        gReqList = &head;
        head.next = &tail;
        tail.next = NULL;
    }
    lockHeld = 1;
    return 0;
}
static int SignalSema(int id) {
    assert(id == gProcSemaId && lockHeld);
    lockHeld = 0;
    return 0;
}
@QUEUE_FN@
typedef struct submenu_item {
    int id;
    int *cache_id, *cache_uid;
} submenu_item_t;
typedef struct submenu_list {
    struct submenu_list *prev, *next;
    submenu_item_t item;
} submenu_list_t;
static void gridForgetItem(const void *item) { (void)item; } /* themes.c: a freed row drops its case-flip state */
@DESTROY_FN@
@REMOVE_FN@
static submenu_list_t *node(int id) {
    submenu_list_t *n = calloc(1, sizeof(*n));
    assert(n);
    n->item.id = id;
    return n;
}
int main(void) {
    gReqList = &old;
    old.next = NULL;
    mutateOnLock = 1;
    assert(ioGetPendingRequestCount() == 2);
    assert(lockHeld == 0);
    mutateOnLock = 0;
    assert(ioGetPendingRequestCount() == 2);
    gReqList = NULL;
    assert(ioGetPendingRequestCount() == 0);

    submenu_list_t *first = node(1), *middle = node(2), *last = node(3);
    first->next = middle; middle->prev = first;
    middle->next = last; last->prev = middle;
    submenu_list_t *list = first;
    submenuRemoveItem(&list, 2);
    assert(list == first && first->next == last && last->prev == first);
    submenuRemoveItem(&list, 1);
    assert(list == last && list->prev == NULL);
    submenuRemoveItem(&list, 3);
    assert(list == NULL);

    first = node(2); middle = node(2); last = node(3);
    first->next = middle; middle->prev = first;
    middle->next = last; last->prev = middle;
    list = first;
    submenuRemoveItem(&list, 2);
    assert(list == last && list->prev == NULL && list->next == NULL);
    submenuRemoveItem(&list, 3);
    assert(list == NULL);
    puts("PASS: queue snapshot is locked; removals preserve backward and forward links");
    return 0;
}
'''.replace("@QUEUE_FN@", queue_fn).replace("@DESTROY_FN@", destroy_fn).replace("@REMOVE_FN@", remove_fn)

cfg_src = (root / "src/config.c").read_text(encoding="utf-8")
cfg_fns = "\n".join(body(cfg_src, sig) for sig in (
    "static int configKeyValidate(",
    "static struct config_value_t *allocConfigItem(",
    "static int addConfigValue(",
    "static struct config_value_t *getConfigItemForName(",
    "int configSetStr(",
    "int configGetStr(",
    "int configGetStrCopy(",
    "int configSetInt(",
    "int configGetInt(",
    "int configRemoveKey(",
    "void configMerge(",
))

menu_cfg_fns = "\n".join(body(menu, sig) for sig in (
    "static void _menuLoadConfig()",
    "static void _menuLoadConfigAsync()",
    "static void _menuRequestConfig()",
    "config_set_t *menuLoadConfig()",
    "config_set_t *gameMenuLoadConfig(",
    "static int menuCanRequestItemConfig(",
))

menu_cfg_program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IO_OK 0
#define IO_CUSTOM_SIMPLEACTION 1
#define APP_MODE 10
#define FAV_MODE 11
#define MMCE_MODE 5
#define BDM_MODE 2
#define MENU_APP_CONFIG_IDLE_FRAMES 1
#define MENU_MMCE_CONFIG_IDLE_FRAMES 3
#define min(a, b) ((a) < (b) ? (a) : (b))

static void _menuLoadConfig(void);

struct config_value_t {
    char key[32];
    char val[256];
    struct config_value_t *next;
};
typedef struct {
    int uid;
    int type;
    struct config_value_t *head;
    struct config_value_t *tail;
    char *filename;
    int modified;
    int format;
} config_set_t;

static void configFree(config_set_t *cfg) {
    if (!cfg) return;
    struct config_value_t *it = cfg->head;
    while (it) {
        struct config_value_t *next = it->next;
        free(it);
        it = next;
    }
    free(cfg->filename);
    free(cfg);
}

@CFG_FNS@

typedef struct item_list item_list_t;
struct item_list {
    short mode;
    int delay;
    config_set_t *(*itemGetConfig)(item_list_t *list, int id);
};
typedef struct { int id; } submenu_item_inner_t;
typedef struct { submenu_item_inner_t item; } submenu_cur_t;
typedef struct { submenu_cur_t *current; item_list_t *userdata; } menu_item_t;
typedef struct { menu_item_t *item; } menu_list_t;
struct UIItem;

static menu_list_t *selected_item;
static int menuSemaId = 1, actionStatus, itemConfigId = -1, guiInactiveFrames;
static config_set_t *itemConfig;
static item_list_t *itemConfigList;
static unsigned char itemConfigWorkerPending;
static unsigned int itemConfigGeneration;

static int WaitSema(int id) { (void)id; return 0; }
static int SignalSema(int id) { (void)id; return 0; }

static int queuedAsyncCount, queuedSyncCount, mmceAbortCount, pendingCancelCount, rumbleFlushCount;
static int favSourceMode = BDM_MODE;
static int favGetItemSourceMode(int id) { (void)id; return favSourceMode; }
static int cacheAbortMmceImageLoadsTimed(int ms) { (void)ms; mmceAbortCount++; return 0; }
static int cacheCancelPendingImageLoadsTimed(int ms) { (void)ms; pendingCancelCount++; return 0; }
static void padRumbleFlush(void) { rumbleFlushCount++; }

static void (*lastQueuedAction)(void);
static int ioPutRequest(int type, void *data) {
    assert(type == IO_CUSTOM_SIMPLEACTION);
    lastQueuedAction = (void (*)(void))data;
    if (data == (void *)&_menuLoadConfig)
        queuedSyncCount++;
    else
        queuedAsyncCount++;
    return IO_OK;
}

@MENU_CFG_FNS@

static int getConfigCalls;
static config_set_t *fakeGetConfig(item_list_t *list, int id) {
    (void)list;
    getConfigCalls++;
    config_set_t *cfg = calloc(1, sizeof(*cfg));
    assert(cfg);
    configSetInt(cfg, "id", id);
    return cfg;
}

int main(void) {
    int val = 123;
    char buf[16] = "keep";
    /* NULL config_set_t must never dereference NULL->head */
    assert(configGetInt(NULL, "k", &val) == 0 && val == 123);
    assert(configSetInt(NULL, "k", 42) == 0);
    assert(configGetStrCopy(NULL, "k", buf, sizeof(buf)) == 0 && buf[0] == '\0');
    assert(configRemoveKey(NULL, "k") == 0);
    configMerge(NULL, NULL);

    item_list_t favList = {FAV_MODE, 6, fakeGetConfig};
    submenu_cur_t cur = {{0}};
    menu_item_t mitem = {&cur, &favList};
    menu_list_t mlist = {&mitem};
    selected_item = &mlist;

    /* Active scroll (guiInactiveFrames == 0) must not request browse-time item configs */
    guiInactiveFrames = 0;
    favSourceMode = BDM_MODE;
    assert(menuCanRequestItemConfig(&favList) == 0);
    guiInactiveFrames = 1;
    assert(menuCanRequestItemConfig(&favList) == 1);

    /* FAV_MODE backed by MMCE_MODE enforces MENU_MMCE_CONFIG_IDLE_FRAMES (3) */
    favSourceMode = MMCE_MODE;
    guiInactiveFrames = 2;
    assert(menuCanRequestItemConfig(&favList) == 0);
    guiInactiveFrames = 3;
    assert(menuCanRequestItemConfig(&favList) == 1);

    /* Deduplicated async worker: multiple settled row changes while worker is pending queue only 1 request */
    guiInactiveFrames = 10;
    cur.item.id = 1;
    _menuRequestConfig();
    assert(queuedAsyncCount == 1 && itemConfigWorkerPending == 1);
    cur.item.id = 2;
    _menuRequestConfig();
    cur.item.id = 3;
    _menuRequestConfig();
    assert(queuedAsyncCount == 1 && itemConfigWorkerPending == 1 && itemConfigId == 3);
    lastQueuedAction();
    assert(itemConfigWorkerPending == 0 && itemConfig != NULL);
    assert(configGetInt(itemConfig, "id", &val) == 1 && val == 3);

    /* Scrolling to a new row (guiInactiveFrames == 0 < list->delay) and immediately pressing Triangle
       (gameMenuLoadConfig) must load the new row's config directly, abort MMCE + pending art on FAV_MODE,
       and flush rumble without returning NULL or queuing onto ioman */
    guiInactiveFrames = 0;
    cur.item.id = 7;
    favSourceMode = MMCE_MODE;
    mmceAbortCount = pendingCancelCount = rumbleFlushCount = 0;
    int prevQueued = queuedAsyncCount + queuedSyncCount;
    config_set_t *loaded = gameMenuLoadConfig(NULL);
    assert(loaded != NULL && loaded == itemConfig);
    assert(configGetInt(loaded, "id", &val) == 1 && val == 7);
    assert(rumbleFlushCount == 1 && mmceAbortCount == 1 && pendingCancelCount == 1);
    assert(queuedAsyncCount + queuedSyncCount == prevQueued);

    configFree(itemConfig);
    itemConfig = NULL;
    puts("PASS: NULL-safe config accessors, FAV_MODE scroll/MMCE gates, async config dedupe, and direct Triangle load");
    return 0;
}
'''.replace("@CFG_FNS@", cfg_fns).replace("@MENU_CFG_FNS@", menu_cfg_fns)

with tempfile.TemporaryDirectory() as temp:
    f = Path(temp) / "regression.c"
    exe = Path(temp) / "regression"
    f.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", str(f), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)

    f2 = Path(temp) / "menu_cfg.c"
    exe2 = Path(temp) / "menu_cfg"
    f2.write_text(menu_cfg_program, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(f2), "-o", str(exe2)], check=True)
    subprocess.run([str(exe2)], check=True, timeout=10)
