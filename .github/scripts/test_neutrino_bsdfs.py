"""A -bsdfs=bd Neutrino launch must be refused BEFORE the teardown when the device has no number.

-bsdfs=bd names the raw bdm device "<driver><devNr>p0" (src/system.c, sysLaunchNeutrino). A mount
whose USBMASS_IOCTL_GET_DEVICE_NUMBER failed carries -1, and sysLaunchNeutrino used to turn that into
device 0 after the menu was already gone -- the wrong stick when two share a driver (CodeRabbit on
PR #756). sysNeutrinoPreflight now refuses it while the GUI is alive, using the same
neutrinoEffectiveBsdfs sysLaunchNeutrino builds its argv from, so the two cannot disagree.

bd TYPED into the Neutrino args counts too (CodeRabbit on #762): it used to switch our own -bsdfs off
and leave a bare file path in -dvd, which bd can never open -- after the teardown. The effective value
is the last active typed token (per-game args after global ones), else the picker; a typed -dvd=
names the device itself, so it is never refused.

This compiles neutrinoArgHasActiveFlag, neutrinoTypedBsdfs, neutrinoEffectiveBsdfs, getDeviceName and
sysNeutrinoPreflight from src/system.c on the host and checks every case that decides the refusal.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/system.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/system.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


functions = ''.join(function_text(sig) for sig in (
    'static const char *getDeviceName(',
    'static int neutrinoArgHasActiveFlag(',
    'static int neutrinoEffectiveBsdfs(',
    'int sysNeutrinoPreflight(',
))

# sysLaunchNeutrino must shape -dvd from the same effective value the preflight checks, and emit that
# value as its OWN -bsdfs= even when it was typed: ours is a core arg the budget never drops, the
# user's is a tail token it may, and a bdfs: -dvd without -bsdfs=bd fails after the teardown
# (CodeRabbit on #762, second pass).
launch = function_text('void sysLaunchNeutrino(')
if 'int fsOverride = neutrinoEffectiveBsdfs(deviceName, neutrinoBsdfs, extraArgs, &userDvd);' not in launch or \
        'if (fsOverride) {' not in launch or '!typedFs' in launch:
    failures.append('sysLaunchNeutrino: must take fsOverride from neutrinoEffectiveBsdfs (shared with the preflight) '
                    'and always emit it as its own -bsdfs=')

# Every Neutrino leg must hand the preflight what it will hand sysLaunchNeutrino.
bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8').replace('\r\n', '\n')
if 'sysNeutrinoPreflight(bdmCurrentDriver, neutrinoPath, neutrinoBsdfs, neutrinoExtraArgs, bdmDevNr)' not in bdm:
    failures.append('bdmTryNeutrinoLaunch: the preflight must get neutrinoBsdfs, the per-game args and bdmDevNr')

HARNESS = r'''
#include <stdio.h>
#include <string.h>

#define LOG(...) ((void)0)
#define NET_BOOT_UDPFS 2
#define _STR_NEUTRINO_DEV_UNSUPPORTED 1
#define _STR_NEUTRINO_TOML_SYNC_FAILED 2
#define _STR_NEUTRINO_BD_NO_DEVICE_NUMBER 3

static char gNeutrinoArgs[256];
static int lastWarning;
static int bdmGetLoadedNetProtocol(void) { return 0; }
static const char *_l(int id) { lastWarning = id; return ""; }
static void guiWarning(const char *msg, int secs) { (void)msg; (void)secs; }
static int sysSyncNeutrinoUdpfsToml(const char *path, const char *dev) { (void)path; (void)dev; return 0; }

@FUNCTIONS@

static int fails;
static void scenario(const char *name, const char *driver, int bsdfs, const char *globalArgs, const char *gameArgs, int devNr, int wantRefuse, int wantWarning)
{
    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "%s", globalArgs);
    lastWarning = 0;
    int r = sysNeutrinoPreflight(driver, "mmce0:/NEUTRINO/neutrino.elf", bsdfs, gameArgs, devNr);
    if ((r < 0) != wantRefuse || (wantRefuse && lastWarning != wantWarning)) {
        printf("FAIL %s: preflight returned %d (warning %d), want %s\n", name, r, lastWarning, wantRefuse ? "a refusal" : "proceed");
        fails++;
    }
}

int main(void)
{
    /*        name                                      driver  bsdfs global         per-game          devNr refuse warning */
    scenario("usb bd, no device number",                 "usb",  3,   "",             NULL,              -1,   1, 3);
    scenario("mx4sio bd, no device number",              "sdc",  3,   "",             "",                -1,   1, 3);
    scenario("usb bd, second stick (usb1)",              "usb",  3,   "",             NULL,               1,   0, 0);
    scenario("usb bd, first stick (usb0)",               "usb",  3,   "",             NULL,               0,   0, 0);
    scenario("ata bd, no device number (one device)",    "ata",  3,   "",             NULL,              -1,   0, 0);
    scenario("usb exfat, no device number",              "usb",  1,   "",             NULL,              -1,   0, 0);
    scenario("usb hdl, no device number",                "usb",  2,   "",             NULL,              -1,   0, 0);
    scenario("usb Auto, no device number",               "usb",  0,   "",             NULL,              -1,   0, 0);
    scenario("per-game -bsdfs= wins over bd",            "usb",  3,   "",             "-dbc -bsdfs=exfat", -1, 0, 0);
    scenario("global -bsdfs= wins over bd",              "usb",  3,   "-bsdfs=exfat", NULL,              -1,   0, 0);
    scenario("$-disabled -bsdfs= does not win",          "usb",  3,   "",             "$-bsdfs=exfat",   -1,   1, 3);
    scenario("mmce leg (no block device)",               "mmce", 0,   "",             NULL,              -1,   0, 0);
    scenario("smb is still unsupported",                 "smb",  0,   "",             NULL,              -1,   1, 1);
    /* bd typed into the args (CodeRabbit on #762) */
    scenario("typed per-game bd, picker Auto",           "usb",  0,   "",             "-bsdfs=bd",       -1,   1, 3);
    scenario("typed global bd, picker Auto",             "usb",  0,   "-bsdfs=bd",    NULL,              -1,   1, 3);
    scenario("typed bd + typed -dvd= names the device",  "usb",  0,   "",             "-bsdfs=bd -dvd=bdfs:usb1p0", -1, 0, 0);
    scenario("typed bd, device number known",            "usb",  0,   "",             "-bsdfs=bd",        1,   0, 0);
    scenario("per-game exfat beats global bd",           "usb",  0,   "-bsdfs=bd",    "-bsdfs=exfat",    -1,   0, 0);
    scenario("per-game bd beats global exfat",           "usb",  0,   "-bsdfs=exfat", "-bsdfs=bd",       -1,   1, 3);
    scenario("last active token wins",                   "usb",  0,   "",             "-bsdfs=bd -bsdfs=exfat", -1, 0, 0);
    scenario("-bsdfs= after --b belongs to the game",    "usb",  0,   "",             "--b -bsdfs=bd",   -1,   0, 0);
    scenario("typed bd on ATA",                          "ata",  0,   "",             "-bsdfs=bd",       -1,   0, 0);
    scenario("typed bd on mmce (no fs layer)",           "mmce", 0,   "",             "-bsdfs=bd",       -1,   0, 0);
    /* "--b": everything after the FIRST one -- per-game args included -- belongs to the game */
    scenario("global --b ends the per-game args",        "usb",  0,   "-bsdfs=bd --b", "-bsdfs=exfat",   -1,   1, 3);
    scenario("global --b hides a per-game bd",           "usb",  0,   "--b",          "-bsdfs=bd",       -1,   0, 0);
    scenario("-dvd= after --b is the game's",            "usb",  0,   "",             "-bsdfs=bd --b -dvd=bdfs:usb1p0", -1, 1, 3);
    scenario("global -dvd= names the device",            "usb",  0,   "-dvd=bdfs:usb1p0", "-bsdfs=bd",   -1,   0, 0);

    /* The value sysLaunchNeutrino shapes -dvd from and emits as its own -bsdfs=, and what counts as
       a -dvd= reaching Neutrino. */
    int userDvd;
    snprintf(gNeutrinoArgs, sizeof(gNeutrinoArgs), "%s", "");
    if (neutrinoEffectiveBsdfs("usb", 0, "-bsdfs=bd", &userDvd) != 3 || userDvd) {
        printf("FAIL typed bd must shape -dvd as bd\n");
        fails++;
    }
    if (neutrinoEffectiveBsdfs("usb", 3, NULL, &userDvd) != 3) {
        printf("FAIL picker bd must shape -dvd as bd\n");
        fails++;
    }
    if (neutrinoEffectiveBsdfs("usb", 3, "-bsdfs=hdl", &userDvd) != 2) {
        printf("FAIL typed hdl beats picker bd\n");
        fails++;
    }
    if (neutrinoEffectiveBsdfs("usb", 3, "-bsdfs=zfs", &userDvd) != 0) {
        printf("FAIL an unknown typed value leaves -dvd bare (Neutrino decides)\n");
        fails++;
    }
    if (neutrinoEffectiveBsdfs("usb", 0, "-bsdfs=bd -dvd=bdfs:usb1p0", &userDvd) != 3 || !userDvd) {
        printf("FAIL a typed -dvd= before --b reaches Neutrino\n");
        fails++;
    }
    if (neutrinoEffectiveBsdfs("usb", 0, "-bsdfs=bd --b -dvd=bdfs:usb1p0", &userDvd) != 3 || userDvd) {
        printf("FAIL a -dvd= after --b does not reach Neutrino\n");
        fails++;
    }
    return fails ? 1 : 0;
}
'''

if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'preflight.c'
        exe = Path(tmp) / 'preflight'
        src.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            if result.returncode != 0:
                lines = [line for line in result.stdout.splitlines() if line]
                failures.extend(lines or ['harness exited %d with no result:\n%s' % (result.returncode, result.stderr)])

if failures:
    print('Neutrino -bsdfs preflight checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('neutrino bsdfs: 27 preflight scenarios + 6 argv checks OK (bd with no device number refused before teardown, typed or picked; --b ends the Neutrino args)')
