"""Source-level guard for UDPFS THM discovery and the first scan of a remembered PS1 page.

UDPFS is a network filesystem whose server can become reachable after its menu support is initialized.
Theme discovery must therefore wait for the server, run before view-specific early returns, and avoid
re-registering the same remote themes on every refresh. It must not latch merely because udpfs:/ answers:
udpfs:/THM itself has to open successfully, and a failed first attempt must keep the lightweight retry
cadence alive even when Automatic Refresh is off. A scan that started before the server answered
must keep the page polling (its "empty" result proves nothing), and a page whose L3 position was restored
onto PS1 must still do its first scan -- the PS1 early return in NeedsUpdate sits before the "never
scanned" check (TwistedZeon, 09-29: remembered PS1 page blank until L3, and no THM themes). That first
scan belongs to UDPFS itself, not to a global libview flag (zackcage6, Beta-3335: boot popup).

THM is found in ANY case (TwistedZeon, NixOS server, 09-30): the share is a PC folder, a case-sensitive
server keeps "thm" and "THM" apart, and sbCreateFolders makes an empty "THM" beside a user's "thm" -- a
fixed "THM" open found that empty one and latched with no themes. The root is listed and every THM-named
folder is scanned (compiled + run against a scripted share below); theme folders match "thm_" in any case.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "src/udpfssupport.c").read_text(encoding="utf-8").replace("\r\n", "\n")
libview = (root / "src/libview.c").read_text(encoding="utf-8").replace("\r\n", "\n")
failures = []


def function_body(source, signature):
    start = source.find(signature)
    if start < 0:
        failures.append(f"missing {signature}")
        return ""
    brace = source.find("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    failures.append(f"unterminated {signature}")
    return ""


if "static int udpfsThemesScanned = 0;" not in src:
    failures.append("missing one-session UDPFS theme-scan latch")

waiter = function_body(src, "static void udpfsSetWaitingForServer(int waiting)")
if waiter:
    cadence = re.compile(
        r"\(\s*waiting\s*\|\|\s*!udpfsThemesScanned\s*\)\s*\?\s*"
        r"MENU_UPD_DELAY_GENREFRESH\s*:\s*UDPFS_MODE_UPDATE_DELAY"
    )
    if not cadence.search(waiter):
        failures.append("failed THM discovery must keep the general-refresh retry cadence alive")

init = function_body(src, "void udpfsInit(item_list_t *itemList)")
if init:
    for needle in ("thmReinit(udpfsBase);", "udpfsThemesScanned = 0;"):
        if needle not in init:
            failures.append(f"udpfsInit missing {needle}")
    if "if (udpfsBase != NULL)" not in init:
        failures.append("udpfsInit must only remove stale UDPFS theme registrations on re-init")

discover = function_body(src, "static void udpfsDiscoverThemes(void)")
if discover:
    expected = (
        "if (udpfsThemesScanned || !udpfsIomanModLoaded || !udpfsServerAnswers())",
        'if (strcasecmp(entry->d_name, "THM") != 0)',
        "dir = opendir(themePath);",
        'thmAddElements(themePath, "/", 1);',
        "if (!found)",
        "udpfsThemesScanned = 1;",
        "udpfsSetWaitingForServer(udpfsWaitingForServer);",
    )
    for needle in expected:
        if needle not in discover:
            failures.append(f"udpfsDiscoverThemes missing {needle}")
    if '"%sTHM"' in discover:
        failures.append("udpfsDiscoverThemes must not open a fixed-case THM path")

    bail = discover.find("if (!found)")
    latch = discover.find("udpfsThemesScanned = 1;")
    if bail < 0 or latch < 0 or bail > latch:
        failures.append("THM discovery must bail before setting the scan latch when no THM folder opened")

    HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <strings.h>

typedef struct { int unused; } DIR;
struct dirent { char d_name[64]; };

static const char *udpfsPrefix = "udpfs:/";
static int udpfsThemesScanned, udpfsIomanModLoaded = 1, udpfsWaitingForServer, setWaiting;
static int rootOpens;
static const char *rootNames[8];
static const char *dirsThatOpen[8];
static char added[8][64];
static int nAdded, rootPos;
static DIR rootDir, subDir;
static struct dirent ent;

static int udpfsServerAnswers(void) { return 1; }
static void udpfsSetWaitingForServer(int waiting) { (void)waiting; setWaiting++; }
static DIR *opendir(const char *path)
{
    int i;
    if (strcmp(path, udpfsPrefix) == 0) {
        rootPos = 0;
        return rootOpens ? &rootDir : NULL;
    }
    for (i = 0; dirsThatOpen[i]; i++)
        if (strcmp(path, dirsThatOpen[i]) == 0)
            return &subDir;
    return NULL;
}
static struct dirent *readdir(DIR *d)
{
    if (d != &rootDir || rootNames[rootPos] == NULL)
        return NULL;
    strcpy(ent.d_name, rootNames[rootPos++]);
    return &ent;
}
static int closedir(DIR *d) { (void)d; return 0; }
static int thmAddElements(char *path, const char *sep, int force)
{
    (void)sep; (void)force;
    strcpy(added[nAdded++], path);
    return 0;
}

@FUNCTION@

static int fails;
static void reset(int opens)
{
    memset(rootNames, 0, sizeof(rootNames));
    memset(dirsThatOpen, 0, sizeof(dirsThatOpen));
    udpfsThemesScanned = nAdded = setWaiting = 0;
    rootOpens = opens;
}
static void expect(const char *what, int latched, int adds)
{
    if (udpfsThemesScanned != latched || nAdded != adds) {
        printf("FAIL %s: latched=%d scanned=%d (want %d, %d)\n", what, udpfsThemesScanned, nAdded, latched, adds);
        fails++;
    }
}

int main(void)
{
    /* the report: the user's lowercase "thm" beside the empty "THM" RiptOPL created */
    reset(1);
    rootNames[0] = "CD"; rootNames[1] = "thm"; rootNames[2] = "THM"; rootNames[3] = "DVD";
    dirsThatOpen[0] = "udpfs:/thm"; dirsThatOpen[1] = "udpfs:/THM";
    udpfsDiscoverThemes();
    expect("lowercase thm beside an empty THM", 1, 2);
    if (nAdded == 2 && (strcmp(added[0], "udpfs:/thm") != 0 || strcmp(added[1], "udpfs:/THM") != 0)) {
        printf("FAIL scanned %s and %s\n", added[0], added[1]);
        fails++;
    }

    reset(1);
    rootNames[0] = "Thm";
    dirsThatOpen[0] = "udpfs:/Thm";
    udpfsDiscoverThemes();
    expect("mixed-case Thm only", 1, 1);

    reset(1);
    rootNames[0] = "CD"; rootNames[1] = "DVD";
    udpfsDiscoverThemes();
    expect("no THM folder yet (keep retrying)", 0, 0);

    reset(1);
    rootNames[0] = "THM"; /* a FILE named THM: never opens as a directory */
    udpfsDiscoverThemes();
    expect("a file named THM", 0, 0);

    reset(0);
    udpfsDiscoverThemes();
    expect("root not reachable yet", 0, 0);

    reset(1);
    rootNames[0] = "THM";
    dirsThatOpen[0] = "udpfs:/THM";
    udpfsDiscoverThemes();
    udpfsDiscoverThemes();
    expect("a second call after the latch", 1, 1);

    if (!fails)
        printf("UDPFS: THM found in any case; nothing latched until a THM folder really opened\n");
    return fails ? 1 : 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        csrc = Path(tmp) / "thm_case.c"
        exe = Path(tmp) / ("thm_case" + (".exe" if sys.platform == "win32" else ""))
        csrc.write_text(HARNESS.replace("@FUNCTION@", discover), encoding="utf-8")
        build = subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Werror", "-o", str(exe), str(csrc)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append("THM case harness did not compile:\n" + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append("THM case harness reported failures")

themes_c = (root / "src/themes.c").read_text(encoding="utf-8").replace("\r\n", "\n")
entry_fn = function_body(themes_c, "static int thmReadEntry(")
if entry_fn and (entry_fn.count('strncasecmp(name, "thm_", 4) == 0') != 2 or 'strncmp(name, "thm_"' in entry_fn):
    failures.append("thmReadEntry must match the thm_ prefix in any case, in both checks")

needs = function_body(src, "static int udpfsNeedsUpdate(item_list_t *itemList)")
if needs:
    call = needs.find("udpfsDiscoverThemes();")
    if call < 0:
        failures.append("udpfsNeedsUpdate does not try theme discovery")
    for label, needle in (("dirty-view", "libViewConsumeDirty(itemList->mode)"),
                          ("folder-dirty", "folderConsumeDirty(itemList->mode)"),
                          ("server-wait", "if (udpfsWaitingForServer)"),
                          ("PS1-view", "libListViewActive(itemList) == LIB_VIEW_PS1")):
        pos = needs.find(needle)
        if call >= 0 and pos >= 0 and call > pos:
            failures.append(f"theme discovery must run before the {label} early return")

update = function_body(src, "static int udpfsUpdateGameList(item_list_t *itemList)")
if update:
    asked = update.find("answeredBefore = udpfsServerAnswers();")
    scan = update.find("cueFillGameList(")
    if asked < 0:
        failures.append("udpfsUpdateGameList must ask the server BEFORE scanning")
    elif scan >= 0 and asked > scan:
        failures.append("the pre-scan server check must come before the Ember scan")
    if "if (answeredBefore)\n        udpfsDiscoverThemes();" not in update:
        failures.append("a scan that reaches the server must also register its themes")
    folders = update.find("sbCreateFolders(udpfsPrefix, 1);")
    discover_after = update.find("udpfsDiscoverThemes();")
    if folders < 0 or discover_after < 0 or discover_after < folders:
        failures.append("UDPFS must create the standard folders before attempting THM discovery")
    if "udpfsSetWaitingForServer(!answeredBefore || (!reached && !udpfsServerAnswers()));" not in update:
        failures.append("a scan that started before the server answered must keep polling")

    if "if (answeredBefore && r >= 0) // only a scan that reached the server AND read the list counts\n            udpfsPs1Scanned = 1;" not in update:
        failures.append("the PS1 first-scan latch must only be set by a scan that reached the server and succeeded")

# A remembered PS1 page gets its first scan from UDPFS itself (as MMCE and BDM do), NOT from marking
# every restored page dirty in libview -- that forced a scan of every empty BDM slot at boot and raised
# "Could not open the CD or DVD folder in (error 5)" on every boot (zackcage6, Beta-3335).
if needs and "if (libListViewActive(itemList) == LIB_VIEW_PS1)\n        return !udpfsPs1Scanned;" not in needs:
    failures.append("udpfsNeedsUpdate must give a remembered PS1 page its first scan")
if init and "udpfsPs1Scanned = 0;" not in init:
    failures.append("udpfsInit must re-arm the PS1 first scan")
load = function_body(libview, "void libViewLoadFromConfig(config_set_t *configLast)")
if load and "libDirty" in load:
    failures.append("libViewLoadFromConfig must not mark restored pages dirty (it scans empty BDM slots at boot)")
bdm = (root / "src/bdmsupport.c").read_text(encoding="utf-8").replace("\r\n", "\n")
if "sub[0] == '\\0' && pDeviceData->bdmPrefix[0] != '\\0')\n            setErrorMessagePathCode(_STR_BDM_PS2_FOLDERS_UNREADABLE" not in bdm:
    failures.append("the CD/DVD-unreadable popup must never fire for a slot with no device path")

if failures:
    print("UDPFS theme discovery checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)

print("UDPFS: THM open-success latch/retry, server polling and restored-view first scan verified")
