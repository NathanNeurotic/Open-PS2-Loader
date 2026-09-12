"""Exercise production HDD startup functions with fault-injected host IOP stubs."""

from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
hdd = (root / "src/hddsupport.c").read_text()
system = (root / "src/system.c").read_text()
header = (root / "include/hddsupport.h").read_text()


def function(source, signature):
    start = source.index(signature + "\n{")
    return source[start:source.index("\n}", start) + 2] + "\n"


prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define LOG(...) ((void)0)
#define HDD_PFS_DIAG_NOT_RUN (-9999)
#define ERROR_HDD_IF_NOT_DETECTED 400
#define _STR_HDD_NOT_CONNECTED_ERROR 1
#define PDIOC_CLOSEALL 1
#define DDIOC_OFF 2
#define MAX_MODULES 32
#define sysLoadModuleLock 1
#define WaitSema(x) ((void)0)
#define SignalSema(x) ((void)0)
enum { DEV9, BDM, ATAD, HDPRO, XHDD, MODULE_COUNT };
static char ps2dev9_irx, bdm_irx, ps2atad_irx, hdpro_atad_irx, xhdd_irx;
static int size_ps2dev9_irx = 1, size_bdm_irx = 1, size_ps2atad_irx = 1;
static int size_hdpro_atad_irx = 1, size_xhdd_irx = 1;
static void *g_sysLoadedModBuffer[MAX_MODULES];
static unsigned char dev9Initialized, dev9Loaded, dev9InitCount;
static int attempts[MODULE_COUNT], resident[MODULE_COUNT], failures[MODULE_COUNT];
static int hdpro, powerOffs, powered, errors, settles, supportCalls, folderCalls;
static int nestedLoad, nestedResult;
static unsigned char hddForceUpdate, hddHDProKitDetected, hddModulesLoadCount;
static unsigned char hddModulesLoaded, hddSupportModulesLoaded;
'''
# Include the new ownership state only when present, so the same regression tests can
# also compile the original implementation and demonstrate its failures.
prefix += "\n".join(re.findall(r"^static unsigned char hddDev9Owned.*$", hdd, re.M))
prefix += r'''
static int hddRetryQueued, gDeinitTerminal, hddGames;
static char *gHDDPrefix;
static const char *hddPrefix = "pfs0:";
typedef struct { int enabled, mode; } item_list_t;
static item_list_t hddGameList;
static int module_id(void *buffer) {
    if (buffer == &ps2dev9_irx) return DEV9;
    if (buffer == &bdm_irx) return BDM;
    if (buffer == &ps2atad_irx) return ATAD;
    if (buffer == &hdpro_atad_irx) return HDPRO;
    assert(buffer == &xhdd_irx);
    return XHDD;
}
int hddLoadModules(void);
static int SifExecModuleBuffer(void *buffer, int size, int argc, char *argv, int *ret) {
    int id = module_id(buffer);
    attempts[id]++;
    if (id == XHDD) {
        assert(hdpro ? (argc == 6 && !strcmp(argv, "-hdpro")) : argc == 0);
    }
    if (nestedLoad) {
        nestedLoad = 0;
        nestedResult = hddLoadModules();
    }
    if (failures[id] > 0) {
        failures[id]--;
        *ret = 1;
        return -1;
    }
    if ((id == ATAD && (!resident[DEV9] || !resident[BDM])) ||
        (id == HDPRO && !resident[DEV9]) ||
        (id == XHDD && !resident[hdpro ? HDPRO : ATAD])) {
        *ret = 1;
        return -1;
    }
    resident[id] = 1;
    if (id == DEV9) powered = 1;
    *ret = 0;
    return id + 1;
}
static int fileXioDevctl(const char *device, int command, void *arg, int size,
                         void *out, int outsize) {
    if (!strcmp(device, "dev9x:") && command == DDIOC_OFF) {
        powerOffs++;
        powered = 0;
    }
    return 0;
}
static void fileXioUmount(const char *path) {}
static void hddFreeHDLGamelist(int *games) {}
static void hddFreeVcdGameList(void) {}
static void hddSetIdleImmediate(void) {}
static void hddDiagBootStageBegin(const char *stage) {}
static void hddDiagBootStageEnd(const char *stage, int result) {}
static void hddDiagBootStageEndVoid(const char *stage) {}
static int hddCheckHDProKit(void) { return hdpro; }
static void setErrorMessageWithCode(int message, int code) { errors++; }
static void DelayThread(int duration) {
    assert(duration == 1000000);
    assert(hddModulesLoaded); /* Preserve the hardware-validated readiness ordering. */
    assert(resident[XHDD] && resident[hdpro ? HDPRO : ATAD] && powered);
    settles++;
}
static void hddLoadSupportModules(void) {
    supportCalls++;
    gHDDPrefix = "pfs0:";
}
static void thmAddElements(const char *path, const char *separator, int mode) {}
static void lngAddLanguages(const char *path, const char *separator, int mode) {}
static void sbCreateFolders(const char *path, int flags) { folderCalls++; }
'''

enum_start = header.index("typedef enum {\n    HDD_LOADMODULES_STATUS_ERROR")
enum_end = header.index("} hdd_loadmodules_status;", enum_start) + len("} hdd_loadmodules_status;")
production = header[enum_start:enum_end] + "\n"
production += function(system, "int sysLoadModuleBuffer(void *buffer, int size, int argc, char *argv)")
production += function(system, "void sysInitDev9(void)")
production += function(system, "void sysShutdownDev9(void)")
production += function(hdd, "int hddLoadModules(void)")
production += function(header, "static inline int hddLoadModulesReady(void)")
production += function(hdd, "static void hddInitModules(void)")
production += function(hdd, "static void hddShutdown(item_list_t *itemList)")

tests = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *test = argv[1];
    if (!strcmp(test, "worker-failure")) {
        failures[ATAD] = 1;
        hddInitModules();
        assert(supportCalls == 0 && folderCalls == 0);
        assert(!hddModulesLoaded && errors == 1);
    } else if (!strcmp(test, "worker-busy")) {
        hddModulesLoadCount = 1;
        hddInitModules();
        assert(supportCalls == 0 && folderCalls == 0 && errors == 0);
    } else if (!strcmp(test, "worker-success")) {
        hddInitModules();
        assert(supportCalls == 1 && folderCalls == 1 && errors == 0);
    } else if (!strcmp(test, "busy")) {
        nestedLoad = 1;
        assert(hddLoadModulesReady());
        assert(nestedResult == HDD_LOADMODULES_STATUS_BUSYLOADING);
        assert(attempts[DEV9] == 1 && attempts[ATAD] == 1 && attempts[XHDD] == 1);
    } else {
        hdpro = strstr(test, "hdpro") != NULL;
        int shared = strstr(test, "shared") != NULL;
        int terminalFailure = strstr(test, "terminal-failure") != NULL;
        if (shared) sysInitDev9(); /* Another subsystem owns DEV9. */
        int failed = -1;
        if (strstr(test, "xhdd")) failed = XHDD;
        else if (strstr(test, "atad")) failed = hdpro ? HDPRO : ATAD;
        else if (strstr(test, "bdm")) failed = BDM;
        else if (strstr(test, "dev9")) failed = DEV9;
        if (failed >= 0) {
            failures[failed] = 3;
            for (int retry = 0; retry < 3; retry++) {
                assert(!hddLoadModulesReady());
                assert(!hddModulesLoaded && hddModulesLoadCount == 0);
                assert(supportCalls == 0 && settles == 0 && powerOffs == 0);
                assert(dev9InitCount == 1 + shared);
            }
        }
        if (!terminalFailure) {
            assert(hddLoadModulesReady());
            assert(powered && resident[XHDD]);
            assert(resident[hdpro ? HDPRO : ATAD]);
            assert(hdpro ? attempts[BDM] == 0 : resident[BDM]);
            assert(settles == 1 && dev9InitCount == 1 + shared);
            if (failed == XHDD) {
                assert(attempts[hdpro ? HDPRO : ATAD] == 1);
                assert(attempts[XHDD] == 4);
            }
            int before = attempts[XHDD];
            assert(hddLoadModulesReady());
            assert(settles == 1 && attempts[XHDD] == before);
            gDeinitTerminal = 0;
            hddShutdown(&hddGameList);
            assert(powered && powerOffs == 0 && dev9InitCount == 1 + shared);
        }
        gDeinitTerminal = 1;
        hddShutdown(&hddGameList);
        assert(dev9InitCount == shared);
        assert(powerOffs == (shared || !dev9Loaded ? 0 : 1));
        hddShutdown(&hddGameList);
        assert(dev9InitCount == shared); /* Do not release another subsystem's reference. */
        assert(powerOffs == (shared || !dev9Loaded ? 0 : 1));
    }
    printf("PASS: %s\n", test);
    return 0;
}
'''

cases = [
    "normal", "hdpro", "xhdd", "hdpro-xhdd", "atad", "hdpro-atad", "bdm", "dev9",
    "shared-xhdd", "terminal-failure-xhdd", "terminal-failure-dev9",
    "shared-terminal-failure-xhdd", "worker-failure", "worker-busy", "worker-success", "busy",
]
with tempfile.TemporaryDirectory(prefix="hdd-startup-tests-") as temp:
    source = Path(temp) / "test.c"
    executable = Path(temp) / "test"
    source.write_text(prefix + production + tests)
    subprocess.run([
        "gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
        "-Wno-unused-variable", str(source), "-o", str(executable),
    ], check=True)
    for case in sys.argv[1:] or cases:
        if case not in cases:
            raise ValueError(f"Unknown test case: {case}")
        subprocess.run([str(executable), case], check=True)
