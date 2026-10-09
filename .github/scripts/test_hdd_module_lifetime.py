"""Host regression: repeated ATA readiness probes must not inflate DEV9 ownership.

Compile the real hddLoadModules/hddShutdown functions with stub IOP drivers and
exercise boot probes, page teardown/re-entry, terminal shutdown and retry after
a failed ATAD load. No HDD or physical PS2 is touched by this test.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/hddsupport.c").read_text(encoding="utf-8")


def extract(signature):
    start = source.index(signature)
    opening = source.index("{", start)
    level = 0
    for i in range(opening, len(source)):
        if source[i] == "{":
            level += 1
        elif source[i] == "}":
            level -= 1
            if level == 0:
                return source[start:i + 1]
    raise AssertionError("unclosed function: " + signature)


functions = (extract("int hddLoadModules(void)") + "\n\n"
             + extract("static void hddShutdown(item_list_t *itemList)"))

harness = r"""
#include <stdio.h>
#include <string.h>
#include <stddef.h>
typedef unsigned char u8;
typedef struct { int enabled; } item_list_t;

enum {
    HDD_LOADMODULES_STATUS_ERROR = -2,
    HDD_LOADMODULES_STATUS_UNK = -1,
    HDD_LOADMODULES_STATUS_NOERROR = 0,
    HDD_LOADMODULES_STATUS_ALREADYLOADED = 1,
    HDD_LOADMODULES_STATUS_BUSYLOADING = 2
};
#define HDD_PFS_DIAG_NOT_RUN (-9)
#define ERROR_HDD_IF_NOT_DETECTED 400
#define _STR_HDD_NOT_CONNECTED_ERROR "missing HDD"
#define PDIOC_CLOSEALL 1
#define LOG(...) ((void)0)
#define hddDiagBootStageBegin(...) ((void)0)
#define hddDiagBootStageEnd(...) ((void)0)
#define hddDiagBootStageEndVoid(...) ((void)0)
#define setErrorMessageWithCode(...) ((void)0)

static u8 hddModulesLoadCount, hddModulesLoaded;
static int hddHDProKitDetected, hddSupportModulesLoaded, gDeinitTerminal;
static char *gHDDPrefix;
static const char *hddPrefix = "pfs0:";
static item_list_t hddGameList;
static int hddGames, bdm_irx, hdpro_atad_irx, hdpro_irx, ps2atad_irx, xhdd_irx;
static int size_bdm_irx, size_hdpro_atad_irx, size_hdpro_irx, size_ps2atad_irx, size_xhdd_irx;

static int initDev9, shutdownDev9, idleOps, flushOps, loadCalls, failAtad;
static void sysInitDev9(void) { initDev9++; }
static void sysShutdownDev9(void) { shutdownDev9++; }
static int hddCheckHDProKit(void) { return 0; }
static int sysLoadModuleBuffer(void *p, int len, int argc, char *argv)
{
    (void)len; (void)argc; (void)argv;
    loadCalls++;
    if (p == &ps2atad_irx && failAtad) {
        failAtad = 0;
        return -1;
    }
    return 0;
}
static void DelayThread(int us) { (void)us; }
static void hddFreeHDLGamelist(void *p) { (void)p; }
static void hddFreeVcdGameList(void) {}
static int fileXioUmount(const char *p) { (void)p; return 0; }
static int fileXioDevctl(const char *p, int cmd, void *in, int inlen, void *out, int outlen)
{
    (void)p; (void)cmd; (void)in; (void)inlen; (void)out; (void)outlen;
    return 0;
}
static void hddFlushCache(void) { flushOps++; }
static void hddSetIdleImmediate(void) { idleOps++; }

@FUNCTIONS@

#define CHECK(cond, msg) do { if (!(cond)) { puts("FAIL: " msg); return 1; } } while (0)

int main(void)
{
    int i;
    CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_NOERROR, "first ATA probe loads drivers");
    for (i = 0; i < 20; i++) {
        CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_ALREADYLOADED, "resident ATA probe returns ready");
    }
    CHECK(hddModulesLoadCount == 1 && initDev9 == 1, "repeated probes do not acquire more DEV9 owners");
    CHECK(loadCalls == 3, "drivers are loaded only on the first probe");

    gDeinitTerminal = 0;
    hddShutdown(NULL);
    CHECK(hddModulesLoadCount == 0 && idleOps == 1, "page shutdown sends idle once");
    CHECK(shutdownDev9 == 0, "non-terminal shutdown preserves DEV9 for other devices");

    CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_ALREADYLOADED, "page reentry reuses resident ATA");
    CHECK(hddModulesLoadCount == 1 && initDev9 == 1, "reentry does not acquire a second DEV9 owner");

    gDeinitTerminal = 1;
    hddShutdown(NULL);
    CHECK(hddModulesLoadCount == 0 && idleOps == 2, "terminal shutdown idles once");
    CHECK(shutdownDev9 == 1, "terminal shutdown releases DEV9 exactly once");
    hddShutdown(NULL);
    CHECK(shutdownDev9 == 1 && idleOps == 2, "repeated shutdown does not release DEV9 twice");

    /* New IOP generation, one failed first load, then retry. */
    hddModulesLoaded = hddModulesLoadCount = 0;
    failAtad = 1;
    CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_ERROR, "failed ATAD load is an error");
    CHECK(hddModulesLoadCount == 0 && shutdownDev9 == 2, "failed load releases owner and can retry");
    CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_NOERROR, "retry succeeds");
    CHECK(hddModulesLoadCount == 1 && initDev9 == 3, "retry acquires one DEV9 owner");
    hddShutdown(NULL);
    CHECK(shutdownDev9 == 3, "retry's owner released once on terminal shutdown");

    hddModulesLoaded = 0;
    hddModulesLoadCount = 1; /* another thread is initializing */
    i = loadCalls;
    CHECK(hddLoadModules() == HDD_LOADMODULES_STATUS_BUSYLOADING, "in-progress load is not ready");
    CHECK(hddModulesLoadCount == 1 && loadCalls == i, "busy probe does not change ownership");
    puts("HDD: idempotent ATA probes, retry and DEV9 release verified");
    return 0;
}
"""

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "hdd_modules.c"
    exe = Path(tmp) / "hdd_modules"
    c.write_text(harness.replace("@FUNCTIONS@", functions), encoding="utf-8")
    cc = subprocess.run(
        ["cc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function",
         "-Wno-unused-variable", "-Wno-unused-parameter", str(c), "-o", str(exe)],
        capture_output=True, text=True
    )
    if cc.returncode:
        print(cc.stderr)
        sys.exit(cc.returncode)
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
