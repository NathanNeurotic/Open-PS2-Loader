"""A settings re-apply must not hide a USB/BDM page whose device is still there (#806, zackcage6).

Every full settings apply (applyConfig(..., 0) -> initAllSupport -> bdmEnumerateDevices) runs
bdmInitDevicesData, which used to hide EVERY started BDM page until the next device poll re-showed it.
Returning from the Start menu in that window, refreshMenuPosition found the user's page invisible and
moved them to the first visible tab -- APPS, Favourites -- and the games came back only after a
refresh and a wait (Beta-3383).

This compiles the real bdmSlotIdentified + bdmInitDevicesData from src/bdmsupport.c against stubs and
checks, for Auto and for Manual-after-start:

- a slot with a mounted, identified device keeps its page visible (and is re-checked: tick reset);
- a slot that never identified a device, or whose first scan failed (-2), is hidden as before;
- Manual before the first start still shows only the first page; Disabled hides everything.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/bdmsupport.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/bdmsupport.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_BDM_DEVICES 3
#define START_MODE_DISABLED 0
#define START_MODE_MANUAL 1
#define START_MODE_AUTO 2
#define BDM_TYPE_UNKNOWN -1
#define BDM_TYPE_USB 0
#define LOG(...) ((void)0)

typedef struct { int visible; } menu_item_t;
typedef struct { menu_item_t menuItem; } opl_io_module_t;
typedef struct { int mode; void *owner; void *priv; } item_list_t;
typedef struct {
    char bdmDeviceRoot[16];
    char bdmDriver[16];
    int bdmDeviceType;
    int bdmULSizePrev;
    int bdmDeviceTick;
} bdm_device_data_t;

static item_list_t bdmDeviceList[MAX_BDM_DEVICES];
static item_list_t bdmGameList;
static opl_io_module_t owners[MAX_BDM_DEVICES];
static int bdmDeviceListInitialized;
static int bdmDeviceModeStarted;
static int effectiveMode;

static int bdmEffectiveStartMode(void) { return effectiveMode; }
static void initSupport(item_list_t *itemList, int mode, int force)
{
    (void)force;
    itemList->owner = &owners[mode];
}

@FUNCTIONS@

static int fails;
static bdm_device_data_t *slot(int i) { return (bdm_device_data_t *)bdmDeviceList[i].priv; }

static void setup(int mode, int started)
{
    int i;
    bdmDeviceListInitialized = 0;
    memset(bdmDeviceList, 0, sizeof(bdmDeviceList));
    bdmInitDevicesData(); /* first call allocates the per-slot data, like boot */
    for (i = 0; i < MAX_BDM_DEVICES; i++) {
        memset(slot(i), 0, sizeof(bdm_device_data_t));
        slot(i)->bdmDeviceType = BDM_TYPE_UNKNOWN;
        slot(i)->bdmULSizePrev = -2;
        slot(i)->bdmDeviceTick = 7;
        owners[i].menuItem.visible = 1;
    }
    /* slot 0: a USB stick, mounted, identified and scanned */
    strcpy(slot(0)->bdmDeviceRoot, "mass0:/");
    strcpy(slot(0)->bdmDriver, "usb");
    slot(0)->bdmDeviceType = BDM_TYPE_USB;
    slot(0)->bdmULSizePrev = 0;
    /* slot 1: mounted and identified, but its first scan failed (-2) */
    strcpy(slot(1)->bdmDeviceRoot, "mass1:/");
    strcpy(slot(1)->bdmDriver, "usb");
    slot(1)->bdmDeviceType = BDM_TYPE_USB;
    /* slot 2: never held a device */
    effectiveMode = mode;
    bdmDeviceModeStarted = started;
}

static void expect(const char *what, int i, int visible, int tickReset)
{
    int got = owners[i].menuItem.visible;
    int reset = slot(i)->bdmDeviceTick == -1;
    if (got != visible || (tickReset >= 0 && reset != tickReset)) {
        printf("FAIL %s: slot %d visible=%d tickReset=%d (want %d, %d)\n", what, i, got, reset, visible, tickReset);
        fails++;
    }
}

int main(void)
{
    const char *names[] = {"Auto", "Manual (started)"};
    int modes[] = {START_MODE_AUTO, START_MODE_MANUAL};
    int m;

    for (m = 0; m < 2; m++) {
        char what[64];
        setup(modes[m], 1);
        bdmInitDevicesData(); /* the settings re-apply */
        snprintf(what, sizeof(what), "%s: identified USB page", names[m]);
        expect(what, 0, 1, 1);
        snprintf(what, sizeof(what), "%s: failed-first-scan page", names[m]);
        expect(what, 1, 0, 1);
        snprintf(what, sizeof(what), "%s: never-connected page", names[m]);
        expect(what, 2, 0, 1);
    }

    setup(START_MODE_MANUAL, 0);
    bdmInitDevicesData();
    expect("Manual before the first start: first page", 0, 1, 0);
    expect("Manual before the first start: other pages", 1, 0, 0);

    setup(START_MODE_DISABLED, 1);
    bdmInitDevicesData();
    expect("Disabled: identified page", 0, 0, 0);

    if (!fails)
        printf("bdm keep page: a re-apply keeps an identified device's page; everything else as before\n");
    return fails ? 1 : 0;
}
'''

functions = function_text('static int bdmSlotIdentified(') + function_text('void bdmInitDevicesData(')
if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'keep_page.c'
        exe = Path(tmp) / ('keep_page' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('keep_page harness did not compile:\n%s' % build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('keep_page harness reported failures')

# The reappearance path and the re-apply must share one identity test.
update = function_text('int bdmUpdateDeviceData(')
if update and 'if (dir >= 0 && visible == 0 && bdmSlotIdentified(pDeviceData)) {' not in update:
    failures.append('bdmUpdateDeviceData: the intact-reappearance branch must use bdmSlotIdentified')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
