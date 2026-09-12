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
#include <stdlib.h>
#include <string.h>
#define LOG(...) ((void)0)
#define HDD_PFS_DIAG_NOT_RUN (-9999)
#define ERROR_HDD_IF_NOT_DETECTED 400
#define ERROR_HDD_NOT_DETECTED 401
#define ERROR_HDD_MODULE_HDD_FAILURE 402
#define ATA_DEVCTL_READ_PARTITION_SECTOR 0x1234
#define _STR_HDD_NOT_CONNECTED_ERROR 1
#define _STR_HDD_UNAVAILABLE_ERROR 2
#define _STR_HDD_APA_REJECTED_ERROR 3
#define PDIOC_CLOSEALL 1
#define DDIOC_OFF 2
#define MAX_MODULES 32
#define sysLoadModuleLock 1
#define WaitSema(x) ((void)0)
#define SignalSema(x) ((void)0)
typedef unsigned char u8;
typedef unsigned int u32;
enum { DEV9, BDM, ATAD, HDPRO, XHDD, PS2HDD, PS2FS, MODULE_COUNT };
static char ps2dev9_irx, bdm_irx, ps2atad_irx, hdpro_atad_irx, xhdd_irx;
static char ps2hdd_irx, ps2fs_irx;
static int size_ps2dev9_irx = 1, size_bdm_irx = 1, size_ps2atad_irx = 1;
static int size_hdpro_atad_irx = 1, size_xhdd_irx = 1;
static int size_ps2hdd_irx = 1, size_ps2fs_irx = 1;
static void *g_sysLoadedModBuffer[MAX_MODULES];
static unsigned char dev9Initialized, dev9Loaded, dev9InitCount;
static int attempts[MODULE_COUNT], resident[MODULE_COUNT], failures[MODULE_COUNT];
static int hdpro, powerOffs, powered, errors, settles, supportCalls, folderCalls;
static int nestedLoad, nestedResult;
static int hddCheckResult, diagArmed, diagReason, lastMessage;
static unsigned char hddSupportErrToasted;
static unsigned char apaImage[1024], mbrImage[1024], zeroImage[1024];
static const unsigned char *probeImages[4];
static int probeResults[4], probeCalls, probeTotal;
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
    if (buffer == &ps2hdd_irx) return PS2HDD;
    if (buffer == &ps2fs_irx) return PS2FS;
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
        return 0;
    }
    if (!strcmp(device, "xhdd0:") && command == ATA_DEVCTL_READ_PARTITION_SECTOR) {
        int index = probeCalls < probeTotal ? probeCalls : probeTotal - 1;
        probeCalls++;
        if (probeResults[index] < 0)
            return probeResults[index];
        memcpy(out, probeImages[index], outsize);
        return 0;
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
static int hddCheck(void) { return hddCheckResult; }
static void hddArmPfsDiagFailure(int reason, int hddCheckRes, int ps2fsResult) {
    diagArmed++;
    diagReason = reason;
}
static void hddClearPfsDiagFailure(const char *reason) { diagArmed = 0; }
static void hddClearRecoveredErrors(void) {}
static void setErrorMessageWithCode(int message, int code) {
    errors++;
    lastMessage = message;
}
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

diag_start = hdd.index("typedef enum {\n    HDD_PFS_DIAG_REASON_NONE")
diag_end = hdd.index("} hdd_pfs_diag_reason_t;", diag_start) + len("} hdd_pfs_diag_reason_t;")
production += hdd[diag_start:diag_end] + "\n"
production += function(hdd, "static int hddApaHeaderValid(const u8 *pSectorData)")
production += function(hdd, "int hddDetectNonSonyFileSystem()")
production += function(hdd, "static int hddLoadCoreSupportModules(void)")

tests = r'''
static void makeApaImage(void) {
    u32 sum = 0;
    int i;
    memset(apaImage, 0, sizeof(apaImage));
    memcpy(apaImage + 4, "APA", 3);
    for (i = 1; i < 128; i++)
        sum += ((u32 *)apaImage)[i];
    ((u32 *)apaImage)[0] = sum;
}
static void makeMbrImage(void) {
    memset(mbrImage, 0, sizeof(mbrImage));
    mbrImage[0x1FE] = 0x55;
    mbrImage[0x1FF] = 0xAA;
}
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
    } else if (!strcmp(test, "unformatted-rejected")) {
        /* The partial raw probe passes but ps2hdd reports "unformatted". Warn without
           claiming that the partition table or game data survived. */
        makeApaImage();
        probeImages[0] = apaImage; probeImages[1] = apaImage;
        probeResults[0] = 0; probeResults[1] = 0; probeTotal = 2;
        hddCheckResult = 1;
        assert(!hddLoadCoreSupportModules());
        assert(probeCalls == 2 && errors == 1 && lastMessage == _STR_HDD_APA_REJECTED_ERROR);
        assert(diagArmed == 0 && !hddSupportModulesLoaded);
    } else if (!strcmp(test, "unformatted-degraded")) {
        /* The second raw probe no longer matches APA; retain the existing diagnostic path. */
        makeApaImage();
        probeImages[0] = apaImage; probeImages[1] = zeroImage;
        probeResults[0] = 0; probeResults[1] = 0; probeTotal = 2;
        hddCheckResult = 1;
        assert(!hddLoadCoreSupportModules());
        assert(probeCalls == 2 && errors == 0 && diagArmed == 1);
        assert(diagReason == HDD_PFS_DIAG_REASON_HDD_CHECK_STATUS_1);
    } else if (!strcmp(test, "unformatted-probe-fails")) {
        /* A failed re-read retains the existing diagnostic path too. */
        makeApaImage();
        probeImages[0] = apaImage; probeImages[1] = apaImage;
        probeResults[0] = 0; probeResults[1] = -1; probeTotal = 2;
        hddCheckResult = 1;
        assert(!hddLoadCoreSupportModules());
        assert(probeCalls == 2 && errors == 0 && diagArmed == 1);
    } else if (!strcmp(test, "support-success")) {
        makeApaImage();
        probeImages[0] = apaImage; probeResults[0] = 0; probeTotal = 1;
        hddCheckResult = 0;
        assert(hddLoadCoreSupportModules());
        assert(hddSupportModulesLoaded && errors == 0 && diagArmed == 0);
        assert(resident[PS2HDD] && resident[PS2FS]);
        /* Already-proven guard: a second call must not re-probe the drive. */
        assert(hddLoadCoreSupportModules());
        assert(probeCalls == 1);
    } else if (!strcmp(test, "support-mbr")) {
        /* A genuine MBR/exFAT disk is normal BDM territory: bail silently. */
        makeMbrImage();
        probeImages[0] = mbrImage; probeResults[0] = 0; probeTotal = 1;
        assert(!hddLoadCoreSupportModules());
        assert(probeCalls == 1 && errors == 0 && !hddSupportModulesLoaded);
    } else if (!strcmp(test, "support-probe-fail")) {
        probeImages[0] = zeroImage; probeResults[0] = -1; probeTotal = 1;
        assert(!hddLoadCoreSupportModules());
        assert(errors == 1 && lastMessage == _STR_HDD_NOT_CONNECTED_ERROR);
    } else if (!strcmp(test, "support-pfs-fail")) {
        makeApaImage();
        probeImages[0] = apaImage; probeResults[0] = 0; probeTotal = 1;
        hddCheckResult = 0;
        failures[PS2FS] = 1;
        assert(!hddLoadCoreSupportModules());
        assert(errors == 0 && diagArmed == 1);
        assert(diagReason == HDD_PFS_DIAG_REASON_PS2FS_LOAD_FAILURE);
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
    "unformatted-rejected", "unformatted-degraded", "unformatted-probe-fails",
    "support-success", "support-mbr", "support-probe-fail", "support-pfs-fail",
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
