"""Work the single IO worker no longer does -- and the work it must keep doing.

Three removals (audit of everything queued on the ioman worker, after FifthFox's #761):

1. menuDeferredUpdate queued an APPS rebuild after EVERY list rebuild, including an L3 view flip.
   A flip changes which list a page shows, not which devices exist, so APPS -- a walk of every
   device's APPS folder -- cannot change. It is skipped for a flip; a real rebuild still queues it
   (eliminator1403's empty-APPS-at-boot fix), and the Favourites re-sync still runs either way
   (favourites resolve against a device's PS1/PS2 list, which a flip can fill for the first time).
2. bdmShouldQueueModuleLoad asked for a module pass whenever USB was not loaded, even with USB
   switched OFF (the default), so every device event queued a pass that did nothing.
3. Each BDM slot's bdmInit queued its own module pass (eight at boot, a ninth from
   bdmEnumerateDevices), and every pass retried any transport that had failed. They now go through
   ioPutRequestUnlessWaiting: one waiting pass covers the rest. The first pass keeps its place, and
   the one-shot MX4SIO / USB "double tap" inside it must stay -- checked below.

This compiles ioPutRequest + ioPutRequestUnlessWaiting (src/ioman.c), bdmShouldQueueModuleLoad
(src/bdmsupport.c) and menuDeferredUpdate (src/opl.c) on the host against stubs.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


ioman = read('src/ioman.c')
bdm = read('src/bdmsupport.c')
opl = read('src/opl.c')

io_functions = ''.join(function_text(ioman, 'src/ioman.c', sig) for sig in (
    'static io_request_handler_t ioGetHandler(',
    'int ioPutRequest(',
    'int ioPutRequestUnlessWaiting(',
))
should_queue = function_text(bdm, 'src/bdmsupport.c', 'static int bdmShouldQueueModuleLoad(')
deferred = function_text(opl, 'src/opl.c', 'void menuDeferredUpdate(')
module_pass = function_text(bdm, 'src/bdmsupport.c', 'static void bdmLoadBlockDeviceModules(')

# --- source guards -------------------------------------------------------------------------------
raw_puts = bdm.count('ioPutRequest(IO_CUSTOM_SIMPLEACTION, &bdmLoadBlockDeviceModules)')
coalesced = bdm.count('ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, &bdmLoadBlockDeviceModules)')
if raw_puts != 0 or coalesced != 3:
    failures.append('bdmsupport.c: all three module-pass requests (bdmLoadModules, bdmNeedsUpdate, '
                    'bdmEnumerateDevices) must use ioPutRequestUnlessWaiting (found %d raw, %d coalesced)'
                    % (raw_puts, coalesced))
# The double taps are one-shot statics INSIDE the pass: coalescing passes must not remove them.
if 'mx4sioSecondProbeDone' not in module_pass or 'DelayThread(600 * 1000); // bounded settle for SIO2 SPI init' not in module_pass:
    failures.append('bdmLoadBlockDeviceModules: the MX4SIO double tap (one 600 ms settle + one refresh) is gone')
if 'usbSecondProbeDone' not in module_pass or 'bdmProbeMassSlots("after-usb-settle")' not in module_pass:
    failures.append('bdmLoadBlockDeviceModules: the USB double tap (settle + bdmProbeMassSlots + refresh) is gone')
if 'modsNow != modsWere && !wasFirstPass' not in module_pass:
    failures.append('bdmLoadBlockDeviceModules: the late-load refresh (enabling a transport from Game Sources) is gone')
worker = function_text(ioman, 'src/ioman.c', 'static void ioWorkerThread(')
if not re.search(r'gReqRunning = req;\s*\n\s*ioProcessRequest\(req\);', worker) or 'gReqRunning = NULL;' not in worker:
    failures.append('ioWorkerThread: must mark the request it runs (gReqRunning) around ioProcessRequest')

IO_HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define IO_OK 0
#define IO_ERR_INVALID_HANDLER -4
#define IO_ERR_IO_BLOCKED -5
#define IO_ERR_TOO_MANY_REQUESTS -6
#define IO_CUSTOM_SIMPLEACTION 1
#define IO_MENU_UPDATE_DEFFERED 2
#define IO_REQ_TYPE_COUNT 5
#define MAX_IO_HANDLERS 64

typedef void (*io_request_handler_t)(void *request);
struct io_request_t { int type; void *data; struct io_request_t *next; };
struct io_handler_t { int type; io_request_handler_t handler; };

static struct io_request_t *gReqList, *gReqEnd;
static struct io_request_t *volatile gReqRunning;
static struct io_handler_t gRequestHandlers[MAX_IO_HANDLERS];
static int gHandlerCount, isIOBlocked, gEndSemaId, gIOThreadId;
static int gIoPending[IO_REQ_TYPE_COUNT];
static unsigned int gIoTotal[IO_REQ_TYPE_COUNT];
static int semaHeld;
static void WaitSema(int s) { (void)s; semaHeld++; }
static void SignalSema(int s) { (void)s; semaHeld--; }
static void WakeupThread(int t) { (void)t; }
static void handler(void *d) { (void)d; }

@IO@

static void pass(void) {}
static short slotMode[8];
static int count(void *data)
{
    int n = 0;
    for (struct io_request_t *r = gReqList; r; r = r->next)
        n += r->data == data;
    return n;
}

int main(void)
{
    int failed = 0;
    gRequestHandlers[0].type = IO_CUSTOM_SIMPLEACTION; gRequestHandlers[0].handler = handler;
    gRequestHandlers[1].type = IO_MENU_UPDATE_DEFFERED; gRequestHandlers[1].handler = handler;
    gHandlerCount = 2;

    /* Boot: bdmEnumerateDevices -> initSupport per slot -> bdmInit (module pass) + that slot's list
       update, then bdmEnumerateDevices' own pass. The worker has not run yet. */
    for (int i = 0; i < 8; i++) {
        ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&pass);
        ioPutRequest(IO_MENU_UPDATE_DEFFERED, &slotMode[i]);
    }
    ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&pass);
    if (count((void *)&pass) != 1 || gReqList->data != (void *)&pass) {
        printf("FAIL boot: %d module passes queued (want 1, still first in the queue)\n", count((void *)&pass));
        failed = 1;
    }
    if (count(&slotMode[3]) != 1) {
        printf("FAIL boot: the per-slot list updates must still all be queued\n");
        failed = 1;
    }

    /* The worker starts that pass: it may already have read a setting the caller now changes, so a
       new request must queue behind it. */
    gReqRunning = gReqList;
    ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&pass);
    if (count((void *)&pass) != 2) {
        printf("FAIL a request while the pass RUNS must queue a new one (have %d, want 2)\n", count((void *)&pass));
        failed = 1;
    }
    ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&pass);
    if (count((void *)&pass) != 2) {
        printf("FAIL a request while one is WAITING must not queue another (have %d, want 2)\n", count((void *)&pass));
        failed = 1;
    }
    /* Same data, different type is a different request. */
    ioPutRequestUnlessWaiting(IO_MENU_UPDATE_DEFFERED, (void *)&pass);
    if (count((void *)&pass) != 3) {
        printf("FAIL type is part of the identity (have %d, want 3)\n", count((void *)&pass));
        failed = 1;
    }
    isIOBlocked = 1;
    if (ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&handler) != IO_ERR_IO_BLOCKED) {
        printf("FAIL a blocked queue must refuse, like ioPutRequest\n");
        failed = 1;
    }
    if (semaHeld != 0) {
        printf("FAIL gEndSemaId left held (%d)\n", semaHeld);
        failed = 1;
    }
    if (!failed)
        printf("io queue: one module pass at boot, running passes never absorb new requests\n");
    return failed;
}
'''

SHOULD_HARNESS = r'''
#include <stdio.h>
static int gEnableUSB, iUSBModLoaded, gEnableILK, iLinkModLoaded, gEnableMX4SIO, mx4sioModLoaded;
static int gEnableBdmHDD, hddModLoaded, gEnableUDPBD, udpbdModLoaded;
static int ethGetModulesLoaded(void) { return 0; }
static int udpfsGetModulesLoaded(void) { return 0; }

@SHOULD@

int main(void)
{
    int failed = 0;
    /* Defaults: USB off and never loaded, nothing else enabled -> nothing to load. */
    if (bdmShouldQueueModuleLoad() != 0) { printf("FAIL USB off (default): no pass is needed\n"); failed = 1; }
    gEnableUSB = 1;
    if (bdmShouldQueueModuleLoad() != 1) { printf("FAIL USB on, not loaded: a pass is needed\n"); failed = 1; }
    iUSBModLoaded = 1;
    if (bdmShouldQueueModuleLoad() != 0) { printf("FAIL USB on and loaded: no pass is needed\n"); failed = 1; }
    gEnableUSB = 0; iUSBModLoaded = 0; gEnableMX4SIO = 1;
    if (bdmShouldQueueModuleLoad() != 1) { printf("FAIL USB off must not hide an MX4SIO that still needs loading\n"); failed = 1; }
    if (!failed)
        printf("io queue: USB off asks for no module pass; other transports still do\n");
    return failed;
}
'''

DEFERRED_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#define IO_MENU_UPDATE_DEFFERED 2
#define APP_MODE 10
#define FAV_MODE 11
#define MODE_COUNT 12

typedef struct item_list item_list_t;
struct item_list { short mode; int enabled; int (*itemNeedsUpdate)(item_list_t *); };
typedef struct { item_list_t *support; } opl_io_module_t;

static opl_io_module_t list_support[MODE_COUNT];
static unsigned char shouldAppsUpdate;
static int gFAVStartMode = 1;
static int needs, pendingView, appsQueued, favLoads, rebuilds;
static int needsUpdate(item_list_t *l) { (void)l; return needs; }
static void updateMenuFromGameList(opl_io_module_t *m) { (void)m; rebuilds++; pendingView = 0; }
static int libViewPending(int mode) { (void)mode; return pendingView; }
static int ioPutRequestUnlessWaiting(int type, void *data) { if (type == IO_MENU_UPDATE_DEFFERED && data == &list_support[APP_MODE].support->mode) appsQueued++; return 0; }
#define ioPutRequest ioPutRequestUnlessWaiting /* either spelling counts as queuing (--baseline runs) */
static void loadFavourites(void) { favLoads++; }
static void guiExecDeferredOps(void) {}
static void clearMenuGameList(opl_io_module_t *m) { (void)m; }
static void libViewCommitPending(int mode) { (void)mode; }
static void libViewFinishPending(int mode) { (void)mode; pendingView = 0; }

@DEFERRED@

static item_list_t bdm = {2, 1, needsUpdate}, apps = {APP_MODE, 1, needsUpdate}, fav = {FAV_MODE, 1, needsUpdate};

static int run(item_list_t *l, int need, int flip)
{
    needs = need; pendingView = flip; appsQueued = favLoads = rebuilds = 0; shouldAppsUpdate = 0;
    menuDeferredUpdate(&l->mode);
    return 0;
}

int main(void)
{
    int failed = 0;
    list_support[2].support = &bdm; list_support[APP_MODE].support = &apps; list_support[FAV_MODE].support = &fav;

    run(&bdm, 1, 0); /* a device page rebuilt for a real reason (connect, SELECT, rescan) */
    if (rebuilds != 1 || appsQueued != 1 || !shouldAppsUpdate || favLoads != 1) {
        printf("FAIL real rebuild: rebuilds %d apps %d flag %d fav %d (want 1 1 1 1)\n", rebuilds, appsQueued, shouldAppsUpdate, favLoads);
        failed = 1;
    }
    run(&bdm, 1, 1); /* L3 flip on that page */
    if (rebuilds != 1 || appsQueued != 0 || shouldAppsUpdate || favLoads != 1) {
        printf("FAIL L3 flip: rebuilds %d apps %d flag %d fav %d (want 1 0 0 1)\n", rebuilds, appsQueued, shouldAppsUpdate, favLoads);
        failed = 1;
    }
    run(&apps, 1, 0); /* APPS itself never re-queues APPS */
    if (appsQueued != 0) { printf("FAIL APPS rebuild queued another APPS rebuild\n"); failed = 1; }
    run(&fav, 1, 0);  /* FAV never re-syncs itself */
    if (appsQueued != 0 || favLoads != 0) { printf("FAIL FAV rebuild queued APPS or FAV\n"); failed = 1; }
    if (!failed)
        printf("io queue: an L3 flip skips the APPS rebuild, keeps the Favourites re-sync\n");
    return failed;
}
'''


def compile_and_run(name, program):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (name + '.c')
        exe = Path(tmp) / name
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-Wno-unused-variable', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('%s harness did not compile:\n%s' % (name, build.stderr))
            return
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        if run.returncode != 0:
            failures.append('%s harness reported failures' % name)


if not failures:
    compile_and_run('io_queue', IO_HARNESS.replace('@IO@', io_functions))
    compile_and_run('should_queue', SHOULD_HARNESS.replace('@SHOULD@', should_queue))
    compile_and_run('deferred', DEFERRED_HARNESS.replace('@DEFERRED@', deferred))

if failures:
    print('IO queue checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
