"""Run production USB/MX4SIO discovery probes; autoload must leave them for the menu."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/bdmsupport.c").read_text(encoding="utf-8")
start = source.index("    static int mx4sioSecondProbeDone = 0;")
end = source.index("    // iLink initial discovery:", start)
probe = source[start:end]
program = r"""
#include <assert.h>
#include <stdio.h>
static int gEnableMX4SIO, mx4sioModLoaded, iUSBModLoaded, bdmAutoLaunch;
static int sleeps, refreshes, scans, ready;
#define BDM_TYPE_SDC 1
static int bdmGetDeviceRootByType(int type, char *root, unsigned int size) {
    assert(type == BDM_TYPE_SDC && size >= 8);
    (void)root;
    return ready;
}
static void DelayThread(int us) { assert(us == 600000); sleeps++; }
static void bdmForceDeviceRefresh(void) { refreshes++; }
static void bdmProbeMassSlots(const char *stage) { (void)stage; scans++; }
static void run(void) {
""" + probe + r"""
}
int main(int argc, char **argv) {
    (void)argv;
    ready = argc > 1;
    gEnableMX4SIO = mx4sioModLoaded = iUSBModLoaded = bdmAutoLaunch = 1;
    run(); run();
    assert(sleeps == 0 && refreshes == 0 && scans == 0);
    bdmAutoLaunch = 0;
    run();
    assert(sleeps == (ready ? 1 : 2));
    assert(refreshes == sleeps && scans == 1);
    run();
    assert(sleeps == (ready ? 1 : 2) && scans == 1);
    gEnableMX4SIO = 0; run();
    gEnableMX4SIO = 1; ready = 0; run();
    assert(sleeps == (argc > 1 ? 2 : 3) && scans == 1);
    puts("autoload skips settles; fallback menu retains ready/absent and one-shot discovery");
    return 0;
}
"""
with tempfile.TemporaryDirectory() as temp:
    cfile = Path(temp) / "settles.c"
    exe = Path(temp) / "settles.exe"
    cfile.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(cfile), "-o", str(exe)], check=True, timeout=30)
    for args in ([], ["ready"]):
        subprocess.run([str(exe), *args], check=True, timeout=10)
