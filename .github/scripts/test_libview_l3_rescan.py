"""Regression: L3 must trigger a fresh source scan at the library root.

A BDM slot that already loaded its ISO list has an unchanged device generation.
folderReset() marks dirty only when exiting a subfolder, so a root-level L3
view switch can otherwise commit PS1 and clear the submenu without ever
calling the Ember/POPS scanner. This harness compiles the actual toggle handler
and checks success, queue rejection, and stage rejection.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
opl = (ROOT / "src/opl.c").read_text(encoding="utf-8").replace("\r\n", "\n")
bdm = (ROOT / "src/bdmsupport.c").read_text(encoding="utf-8").replace("\r\n", "\n")
folder = (ROOT / "src/folderbrowse.c").read_text(encoding="utf-8").replace("\r\n", "\n")


def function_text(source, signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", source, re.M)
    if match is None:
        raise AssertionError(signature + " definition missing")
    brace = source.index("{", match.start())
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():i + 1]
    raise AssertionError(signature + " definition unterminated")


toggle = function_text(opl, "static void itemExecToggleView(")
reset = function_text(folder, "void folderReset(")
needs = function_text(bdm, "static int bdmNeedsUpdate(")

# The real root reset deliberately does not force an update; the L3 path must.
assert "if (folderSub[mode][0] != '\\0' || folderLevels[mode] != 0)" in reset
assert "libViewMarkDirty(support->mode);" in toggle
assert toggle.index("if (!libViewStageAdvance(support->mode))") < toggle.index("libViewMarkDirty(support->mode);")
assert toggle.index("libViewMarkDirty(support->mode);") < toggle.index("cacheDropQueuedArt();")
# The mode-dirty escape must stay ABOVE the otherwise-skipping generation gate.
assert needs.index("if (libViewConsumeDirty(itemList->mode))") < needs.index("pDeviceData->bdmDeviceTick == BdmGeneration")

HARNESS = r"""
#include <stdio.h>
#include <string.h>
#define IO_OK 0
#define IO_MENU_UPDATE_DEFFERED 7
#define SFX_CONFIRM 1
#define FAV_MODE 25
#define APP_MODE 26
#define LIB_VIEW_ISO 0
#define LIB_VIEW_PS1 1
#define LIB_VIEW_ELF 2
#define LIB_VIEW_ALL 3
#define LIB_VIEW_PS1_ELF 4
#define LIB_VIEW_MIXED 5
#define _STR_VIEW_PS1 10
#define _STR_VIEW_ELF 11
#define _STR_VIEW_ALL 12
#define _STR_VIEW_PS2 13
#define _STR_VIEW_PS1_ELF 14
#define _STR_VIEW_APPS 15
#define _STR_VIEW_MIXED 16
#define _STR_VCD_ON 17
#define _STR_VCD_OFF 18
typedef struct { short mode; } item_list_t;
struct menu_item { void *userdata; };
static int queueReject, stageReject, folderDepth;
static int dirty, queues, scans, cacheDrops, warnings;
static int staged, pending;
static char sequence[64];
static void record(char c) { size_t n = strlen(sequence); sequence[n] = c; sequence[n + 1] = 0; }
static int libViewRingUsable(int mode) { (void)mode; return 1; }
static int libViewPending(int mode) { (void)mode; return pending; }
static int ioPutRequest(int type, void *data) {
    (void)data; if (type != IO_MENU_UPDATE_DEFFERED) return -1;
    record('Q'); queues++; return queueReject ? -1 : IO_OK;
}
static void folderReset(int mode) {
    (void)mode; record('F');
    if (folderDepth) { dirty++; folderDepth = 0; }
}
static int libViewStageAdvance(int mode) {
    (void)mode; record('S');
    if (stageReject) return 0;
    staged = 1; pending = 1; return 1;
}
static void libViewMarkDirty(int mode) {
    (void)mode; record('D'); dirty++;
}
static void cacheDropQueuedArt(void) { record('C'); cacheDrops++; }
static void sfxPlay(int sound) { (void)sound; }
static int libViewPendingTarget(int mode) { (void)mode; return LIB_VIEW_PS1; }
static const char *_l(int id) { (void)id; return "PS1"; }
static void guiWarning(const char *s, int duration) {
    (void)s; (void)duration; warnings++;
}
@TOGGLE@

static void reset_case(void) {
    queueReject = stageReject = folderDepth = 0;
    dirty = queues = scans = cacheDrops = warnings = staged = pending = 0;
    sequence[0] = 0;
}
static void consume_bdm_scan(void) {
    /* The source bdmNeedsUpdate dirty-before-cache ordering is asserted above. */
    if (dirty) { dirty = 0; scans++; }
}
int main(void) {
    item_list_t list = { 3 };
    struct menu_item menu = { &list };
    reset_case();
    itemExecToggleView(&menu);
    consume_bdm_scan();
    if (!staged || queues != 1 || scans != 1 || cacheDrops != 1 ||
        warnings != 1 || strcmp(sequence, "QFSDC"))
        { printf("FAIL root L3: %s scans=%d\n", sequence, scans); return 1; }

    reset_case();
    queueReject = 1;
    itemExecToggleView(&menu);
    consume_bdm_scan();
    if (staged || scans || cacheDrops || dirty || strcmp(sequence, "Q"))
        { printf("FAIL rejected queue: %s\n", sequence); return 1; }

    reset_case();
    stageReject = 1;
    itemExecToggleView(&menu);
    consume_bdm_scan();
    if (staged || scans || cacheDrops || dirty || strcmp(sequence, "QFS"))
        { printf("FAIL rejected stage: %s\n", sequence); return 1; }

    puts("L3: root switch scans once; rejected transitions do not scan");
    return 0;
}
""".replace("@TOGGLE@", toggle)

with tempfile.TemporaryDirectory(prefix="opl-l3-scan-") as temp:
    src = Path(temp) / "l3_scan.c"
    exe = Path(temp) / "l3_scan"
    src.write_text(HARNESS, encoding="utf-8")
    build = subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                            "-o", str(exe), str(src)], capture_output=True, text=True)
    if build.returncode:
        sys.exit("L3 harness compile FAILED:\n" + build.stderr)
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    print(run.stdout, end="")
    if run.returncode:
        sys.exit("L3 harness FAILED:\n" + run.stderr)
