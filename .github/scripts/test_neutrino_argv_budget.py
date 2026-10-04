"""Compile the real Neutrino argv builder and verify pre-teardown budget refusal."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/system.c").read_text(encoding="utf-8")


def function(signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", source, re.M)
    if match is None:
        raise AssertionError(f"missing {signature}")
    return source[match.start():source.index("\n}", match.start()) + 2]


functions = "\n\n".join(function(sig) for sig in (
    "static const char *getDeviceName(",
    "static int appendArgTokens(",
    "static int sysStartupShapeOk(",
    "static int neutrinoArgHasActiveFlag(",
    "static int neutrinoEffectiveBsdfs(",
    "static const char *sysLastPathSeparator(",
    "static int sysRunNeutrinoLaunch(",
    "int sysNeutrinoArgsPreflight(",
))

for filename in ("bdmsupport.c", "hddsupport.c", "mmcesupport.c", "udpfssupport.c"):
    leg = (root / "src" / filename).read_text(encoding="utf-8")
    assert "sysNeutrinoArgsPreflight(" in leg, filename
    assert leg.index("sysNeutrinoArgsPreflight(") < leg.index("sysLaunchNeutrino("), filename

bdm = (root / "src/bdmsupport.c").read_text(encoding="utf-8")
assert re.search(r"if \(sysNeutrinoArgsPreflight\([^;]+?\) < 0\) \{\s*failResult = 1;", bdm), \
    "BDM budget refusal must not fall back to the native core"

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LOG(...) ((void)0)
#define NET_BOOT_UDPFS 2
#define LAUNCHDIAG_REFUSE_ARGS 1
#define LAUNCHDIAG_REFUSE_CORE_ARGV 2
#define _STR_NEUTRINO_LAUNCH_ARGS_OVERFLOW 7
#define NEUTRINO_VMC_SLOTS 2
typedef struct { char arg[NEUTRINO_VMC_SLOTS][160]; } neutrino_vmc_args_t;

static char gNeutrinoArgs[256];
static int gNeutrinoElfArg = 1, gEnableDebug, gLaunchDiag;
static int lastWarning, loads, refuses, lastArgc;
static char lastArgs[14][256];
static int bdmGetLoadedNetProtocol(void) { return 0; }
static int convertCompatmaskToModes(int mask) { return mask; }
static const char *_l(int id) { lastWarning = id; return ""; }
static void guiWarning(const char *msg, int secs) { (void)msg; (void)secs; }
static void launchDiagRefuse(int reason) { (void)reason; refuses++; }
static void launchDiagMark(int stage) { (void)stage; }
static int sysLoadELFKeepIOP(const char *path, const char *args, int argc, char **argv)
{
    (void)path; (void)args;
    lastArgc = argc;
    for (int i = 0; i < argc; i++) snprintf(lastArgs[i], sizeof(lastArgs[i]), "%s", argv[i]);
    loads++;
    return 0;
}

@FUNCTIONS@

static int check(const char *name, const char *global, const char *game, const neutrino_vmc_args_t *vmc, int expected)
{
    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "%s", global);
    lastWarning = 0;
    int beforeLoads = loads;
    int result = sysNeutrinoArgsPreflight("usb", "mass0:/DVD/SLUS_123.45.iso", "SLUS_123.45",
                                        0, 0, "mass0:/NEUTRINO/neutrino.elf", game, 0, 0, 0, 0, vmc);
    if (result != expected || loads != beforeLoads ||
        (expected < 0 && lastWarning != _STR_NEUTRINO_LAUNCH_ARGS_OVERFLOW)) {
        printf("FAIL %s: result=%d warning=%d loads=%d\n", name, result, lastWarning, loads);
        return 1;
    }
    return 0;
}

int main(void)
{
    int failures = 0;
    char many[160] = "";
    for (int i = 0; i < 18; i++) strcat(many, "-x ");
    char longArg[224];
    longArg[0] = '-'; longArg[1] = 'x';
    memset(longArg + 2, 'a', sizeof(longArg) - 3);
    longArg[sizeof(longArg) - 1] = '\0';
    neutrino_vmc_args_t vmc = {{"", ""}};
    snprintf(vmc.arg[0], sizeof(vmc.arg[0]), "-mc0=mass0:/VMC/%0138d.bin", 0);

    failures += check("normal options", "-dbc", "-gsm=fp2", NULL, 0);
    failures += check("entry count", many, "", NULL, -1);
    failures += check("byte pool", longArg, "", NULL, -1);
    failures += check("VMC consumes budget", "-cfg=long-name", "", &vmc, -1);

    /* Exactly 14 target entries must retain each token after the second --b pass. */
    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "-a -b -c -d -e -f --b tail");
    int beforeLoads = loads;
    if (sysRunNeutrinoLaunch("usb", "mass0:/DVD/SLUS_123.45.iso", "SLUS_123.45", 0, 0,
                             "mass0:/NEUTRINO/neutrino.elf", "", 0, 0, 0, 0, NULL, 0) != 0 ||
        loads != beforeLoads + 1 || lastArgc != 14 ||
        strcmp(lastArgs[6], "-a") || strcmp(lastArgs[11], "-f") ||
        strcmp(lastArgs[12], "--b") || strcmp(lastArgs[13], "tail")) {
        puts("FAIL boundary argv must preserve each token without concatenated suffixes");
        failures++;
    }

    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "%s", many);
    beforeLoads = loads;
    int beforeRefuses = refuses;
    if (sysRunNeutrinoLaunch("usb", "mass0:/DVD/SLUS_123.45.iso", "SLUS_123.45", 0, 0,
                             "mass0:/NEUTRINO/neutrino.elf", "", 0, 0, 0, 0, NULL, 0) != -1 ||
        loads != beforeLoads || refuses != beforeRefuses + 1) {
        puts("FAIL actual launch must refuse an overfull argv even if preflight was bypassed");
        failures++;
    }
    return failures ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "budget.c"
    exe = Path(tmp) / "budget"
    src.write_text(harness.replace("@FUNCTIONS@", functions), encoding="utf-8")
    build = subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Werror", "-Wno-unused-function",
                            "-o", str(exe), str(src)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

print("neutrino argv budget: count, bytes, VMC, 14-entry token integrity, and pre-teardown refusal OK")
