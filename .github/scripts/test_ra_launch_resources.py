"""Compile real EE-core RA resource paths against controlled IOP-heap failures.

The optional achievements module must never trap a game in MODLOAD's -400 loop.
The snapshot buffer must be proportional to this game's watch list, with
strict bounds on pointer-chain pairs and full cleanup on module-load failure.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
iop = (root / "ee_core/src/iopmgr.c").read_text()
mod = (root / "ee_core/src/modmgr.c").read_text()


def function(source, signature):
    begin = source.index(signature)
    return source[begin:source.index("\n}", begin) + 2]


wanted = function(iop, "static int RA_TelemetryWanted(struct EECoreConfig_t *config)")
hex32 = function(iop, "static void RA_Hex32(unsigned int v, char *out)")
load_begin = iop.index("    ra_snap_iop = 0;\n    if (RA_TelemetryWanted(config)")
load_end = iop.index("\n#endif\n}", load_begin)
load_body = iop[load_begin:load_end]
module_loader = function(mod, "int LoadOPLModule(int id, int mode, int arg_len, const char *args)")

# Check that the normal RA ELF cannot accidentally reserve the card's workspace
# or install its extra GS write breakpoint, even with Caduceus selected.
assert "#define RA_EXPERIMENTAL_CARD_DMA 0" in (root / "include/ra_features.h").read_text()
for path, guard in [
    ("src/rawatch.c", "#if RA_EXPERIMENTAL_CARD_DMA\n    if (gRAMode == RA_MODE_CADUCEUS)"),
    ("ee_core/src/main.c", "#if defined(RETROACHIEVEMENTS) && RA_EXPERIMENTAL_CARD_DMA\n    if (!config->EnableGSMOp"),
    ("ee_core/src/padhook.c", "#if defined(RETROACHIEVEMENTS) && RA_EXPERIMENTAL_CARD_DMA\n        else if (config->raOverlayBuf)"),
]:
    assert guard in (root / path).read_text(), f"production GS guard missing in {path}"

harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "modules/network/common/ra_snap.h"
#define RETROACHIEVEMENTS 1
#define RA_PROBE 0
#define IPCONFIG_MAX_LEN 128
#define ETH_MODE 3
#define HTTP_MODE 4
#define OPL_MODULE_ID_RAUDP 111
#define MODMGR 0
#define BGCOLND(...) ((void)0)
#define DBGCOL(...) ((void)0)
#define DBGCOL_BLNK(...) ((void)0)
typedef struct EECoreConfig_t {
    const unsigned *raWatchList;
    int raWatchCount, raSnapBytes, raNodeCount;
    void *raSnapBuf;
    char GameID[16], raHost[16];
    int GameMode, raClientMode;
} EECoreConfig_t;
static int EnableDebug, module_result, module_calls, allocations, frees, fail_alloc;
static unsigned last_size, ra_snap_iop;
static char last_args[256], g_ipconfig[IPCONFIG_MAX_LEN];
static int g_ipconfig_len;
static char buffer[RA_SNAP_TOTAL];
static char module_data[8];
static void delay(int n) { (void)n; }
static void *SifAllocIopHeap(unsigned n) {
    allocations++;
    last_size = n;
    assert(n <= sizeof(buffer));
    return fail_alloc ? NULL : buffer;
}
static void SifFreeIopHeap(void *p) { assert(p == buffer); frees++; }
static int GetOPLModInfo(int id, void **p, unsigned *size) {
    assert(id == OPL_MODULE_ID_RAUDP);
    *p = module_data;
    *size = sizeof(module_data);
    return 0;
}
static int LoadMemModule(int mode, void *p, unsigned size, int argc, const char *args) {
    assert(mode == 0 && p == module_data && size == sizeof(module_data));
    assert(argc < (int)sizeof(last_args));
    memcpy(last_args, args, argc);
    last_args[argc] = '\0';
    module_calls++;
    return module_result;
}
static void *RA_OverlayEventBuffer(void) { return module_data; }
"""
harness += wanted + "\n" + hex32 + "\n" + module_loader + "\n"
harness += "static void load_ra(EECoreConfig_t *config) {\n" + load_body + "\n}\n"
harness += r"""
static unsigned watch[10];
static void reset(void) {
    EnableDebug=0; module_result=1; module_calls=allocations=frees=fail_alloc=0;
    last_size=0; ra_snap_iop=0; last_args[0]=0;
}
int main(void) {
    EECoreConfig_t c;
    memset(&c,0,sizeof(c));
    c.raWatchList=watch; c.raWatchCount=10; c.raSnapBytes=697;
    c.raSnapBuf=buffer; c.GameMode=3;
    c.raClientMode=1;
    strcpy(c.GameID,"SLUS_212.69");
    strcpy(c.raHost,"192.168.1.5");
    reset(); load_ra(&c);
    assert(allocations==1 && module_calls==1 && !frees);
    assert(last_size==RA_SNAP_TOTAL_FOR(697) && last_size<RA_SNAP_TOTAL);
    assert(last_args[RA_ARG_RX]=='2' && ra_snap_iop);
    puts("PASS: small Caduceus watch list uses only its own rounded snapshot capacity");

    reset(); c.raNodeCount=3; load_ra(&c);
    assert(last_size==RA_SNAP_TOTAL_FOR(697+3*RA_NODE_PAIR_BYTES));
    puts("PASS: pointer-chain value pairs are included");

    reset(); c.raSnapBytes=RA_SNAP_MAX_BYTES; load_ra(&c);
    assert(!allocations && !module_calls && !ra_snap_iop);
    puts("PASS: oversize snapshot+nodes never enters IOP heap");

    c.raSnapBytes=697; c.raNodeCount=0;
    reset(); c.raWatchCount=0; load_ra(&c);
    assert(!allocations && !module_calls);
    c.raWatchCount=10;
    reset(); fail_alloc=1; load_ra(&c);
    assert(allocations==1 && module_calls==0 && ra_snap_iop==0);
    puts("PASS: untracked or out-of-memory launches remain untracked");

    reset(); module_result=-400; load_ra(&c);
    assert(allocations==1 && module_calls==1 && frees==1 && ra_snap_iop==0);
    puts("PASS: optional RAUDP -400 failure does not hang and releases IOP heap");

    reset(); c.GameMode=0; c.raClientMode=0; load_ra(&c);
    assert(last_args[RA_ARG_RX]=='1');
    puts("PASS: legacy xeRAbora client flags still select the same RA module");

    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="ra-launch-resources-") as temp:
    src = Path(temp) / "ra-launch-resources.c"
    exe = Path(temp) / "ra-launch-resources"
    src.write_text(harness)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-pointer-to-int-cast", "-I", str(root),
                    str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
