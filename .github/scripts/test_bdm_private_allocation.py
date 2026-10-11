"""Compile BDM production lifecycle paths and fail allocations before registration."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/bdmsupport.c").read_text(encoding="utf-8")
opl = (root / "src/opl.c").read_text(encoding="utf-8")

def function(signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError(signature)

parts = "\n\n".join(function(x) for x in (
    "static void bdmInit(item_list_t *itemList)",
    "static void bdmCleanUp(item_list_t *itemList, int exception)",
    "static int bdmCheckVMC(item_list_t *itemList, char *name, int createSize)",
    "static char *bdmGetPrefix(item_list_t *itemList)",
    "static int bdmSlotIdentified(const bdm_device_data_t *pDeviceData)",
    "void bdmInitDevicesData()",
))
begin = opl.index("int oplGetAppImageByMode(")
prefix_use = opl[:begin]
assert 'if (prefix == NULL || prefix[0] == \'\\0\')\n                continue;' in prefix_use

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MAX_BDM_DEVICES 3
#define START_MODE_DISABLED 0
#define START_MODE_MANUAL 1
#define START_MODE_AUTO 2
#define BDM_TYPE_UNKNOWN -1
#define LOG(...) ((void)0)
typedef struct item_list {
    int mode, enabled, delay;
    void *owner, *priv;
} item_list_t;
typedef struct {
    int visible;
} menu_item_t;
typedef struct {
    menu_item_t menuItem;
} opl_io_module_t;
typedef struct {
    int bdmULSizePrev, bdmModifiedCDPrev, bdmModifiedDVDPrev;
    int bdmGameCount, bdmPs1GameCount, FoldersCreated, bdmDeviceType;
    int bdmHddIsLBA48, ataHighestUDMAMode, bdmDeviceTick;
    void *bdmGames, *bdmPs1Games;
    char bdmDeviceRoot[32], bdmDriver[32], bdmPrefix[64];
} bdm_device_data_t;
static item_list_t bdmGameList, bdmDeviceList[MAX_BDM_DEVICES];
static opl_io_module_t owners[MAX_BDM_DEVICES];
static int bdmDeviceListInitialized, bdmDeviceModeStarted;
static int gArtDelay=15, initCalls[MAX_BDM_DEVICES], live, allocCall, failAt;
static void bdmLoadModules(void) {}
static int bdmEffectiveStartMode(void) { return START_MODE_AUTO; }
static int sysCheckVMC(const char *prefix, const char *sep, char *name, int sz, void *super) {
    (void)sep; (void)name; (void)sz; (void)super;
    assert(!strcmp(prefix,"mass0:"));
    return 8;
}
static void bdmInit(item_list_t *itemList);
static void initSupport(item_list_t *itemList, int mode, int forceReinit) {
    (void)forceReinit;
    assert(itemList->priv != NULL && mode >= 0 && mode < MAX_BDM_DEVICES);
    initCalls[mode]++;
    if (!itemList->enabled)
        bdmInit(itemList);
    itemList->owner = &owners[mode];
}
static void *trackedMalloc(size_t n) {
    allocCall++;
    if (allocCall == failAt) return NULL;
    void *p = malloc(n);
    if (p) live++;
    return p;
}
static void trackedFree(void *p) {
    if (p) {
        live--;
        free(p);
    }
}
#define malloc trackedMalloc
#define free trackedFree
@SOURCE@
int main(void) {
    // First failed slot must never be registered or dereferenced by bdmInit.
    allocCall=0; failAt=1;
    bdmInitDevicesData();
    assert(bdmDeviceList[0].priv == NULL && initCalls[0] == 0);
    assert(initCalls[1] == 1 && initCalls[2] == 1);
    assert(bdmDeviceList[0].enabled == 0);
    // If a slot has already been registered in a prior session, a failed retry
    // must mark it disabled and hide it rather than publish a dangling page.
    bdmDeviceList[0].owner = &owners[0];
    bdmDeviceList[0].enabled = 1;
    owners[0].menuItem.visible = 1;
    allocCall=0; failAt=1;
    bdmInitDevicesData();
    assert(bdmDeviceList[0].priv == NULL && !bdmDeviceList[0].enabled);
    assert(!owners[0].menuItem.visible && initCalls[0] == 0);

    bdmInit(&bdmDeviceList[0]);
    assert(!bdmDeviceList[0].enabled);
    assert(bdmGetPrefix(&bdmDeviceList[0]) == NULL);
    assert(bdmCheckVMC(&bdmDeviceList[0], "CARD", 0) == -1);
    bdmDeviceList[0].enabled = 1;
    bdmCleanUp(&bdmDeviceList[0], 0);
    assert(bdmDeviceList[0].priv == NULL);

    // Memory recovery: next apply allocates slot zero and initializes it.
    allocCall=0; failAt=0;
    bdmInitDevicesData();
    assert(bdmDeviceList[0].priv != NULL && initCalls[0] == 1);
    assert(bdmDeviceList[0].enabled);
    strcpy(((bdm_device_data_t *)bdmDeviceList[0].priv)->bdmPrefix, "mass0:");
    assert(!strcmp(bdmGetPrefix(&bdmDeviceList[0]),"mass0:"));
    assert(bdmCheckVMC(&bdmDeviceList[0], "CARD", 0) == 8);

    for(int i=0; i<MAX_BDM_DEVICES; i++) {
        bdmDeviceList[i].enabled = 1;
        bdmCleanUp(&bdmDeviceList[i], 0);
        assert(bdmDeviceList[i].priv == NULL);
    }
    assert(live == 0);
    puts("PASS: failed BDM allocation never publishes a broken slot, and later retries safely");
    return 0;
}
'''.replace("@SOURCE@", parts)

with tempfile.TemporaryDirectory() as tmp:
    inp = Path(tmp) / "bdm.c"
    exe = Path(tmp) / "bdm"
    inp.write_text(harness, encoding="utf-8")
    subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-Werror", str(inp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
