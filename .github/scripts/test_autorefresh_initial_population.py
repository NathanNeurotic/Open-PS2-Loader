"""Automatic Refresh must not suppress the first population of a newly-started source.

A Manual source is initialized from itemExecSelect via itemInitSupport(). Historically that helper
skipped its initial IO_MENU_UPDATE_DEFFERED request when gAutoRefresh was enabled, assuming the
periodic refresh cadence would populate it later. That leaves an enabled page empty immediately
after entering it and makes the UI appear stuck on another populated page.

Automatic Refresh is a policy for subsequent background rescans. Initial population is mandatory.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
opl = (root / "src/opl.c").read_text(encoding="utf-8").replace("\r\n", "\n")


def function_text(signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", opl, re.M)
    if match is None:
        raise RuntimeError(f"{signature}...) not found")
    depth = 0
    start = match.start()
    brace = opl.index("{", match.start())
    for i in range(brace, len(opl)):
        if opl[i] == "{":
            depth += 1
        elif opl[i] == "}":
            depth -= 1
            if depth == 0:
                return opl[start:i + 1]
    raise RuntimeError(f"{signature}...) is unterminated")


fn = function_text("static void itemInitSupport(")
failures = []

# Source guards: this is the actual contract we are pinning.
if "gAutoRefresh" in fn:
    failures.append("itemInitSupport still conditions first population on gAutoRefresh")
if fn.count("ioPutRequest(IO_MENU_UPDATE_DEFFERED, &support->mode);") != 1:
    failures.append("itemInitSupport must queue exactly one initial deferred list update")

HARNESS = r'''
#include <stdio.h>
#include <string.h>

#define IO_MENU_UPDATE_DEFFERED 7

typedef struct item_list item_list_t;
struct item_list {
    int mode;
    int enabled;
    void *owner;
    void (*itemInit)(item_list_t *);
};

typedef struct { int dummy; } opl_io_module_t;

static int initCalls, menuCalls, queueCalls;
static char order[8];
static int orderLen;

static void record(char c)
{
    if (orderLen < (int)sizeof(order) - 1) {
        order[orderLen++] = c;
        order[orderLen] = '\0';
    }
}

static void fakeInit(item_list_t *support)
{
    initCalls++;
    support->enabled = 1;
    record('I');
}

static void moduleUpdateMenuInternal(opl_io_module_t *owner, int themeChanged, int langChanged)
{
    (void)owner;
    (void)themeChanged;
    (void)langChanged;
    menuCalls++;
    record('M');
}

static int ioPutRequest(int type, void *data)
{
    short *mode = (short *)data;
    if (type != IO_MENU_UPDATE_DEFFERED || *mode != 3)
        return -1;
    queueCalls++;
    record('Q');
    return 0;
}

@FUNCTION@

int main(void)
{
    item_list_t support;
    memset(&support, 0, sizeof(support));
    support.mode = 3;
    support.owner = NULL;
    support.itemInit = fakeInit;

    itemInitSupport(&support);

    if (initCalls != 1 || menuCalls != 1 || queueCalls != 1) {
        printf("FAIL calls: init=%d menu=%d queue=%d\n", initCalls, menuCalls, queueCalls);
        return 1;
    }
    if (strcmp(order, "IMQ") != 0) {
        printf("FAIL order: %s (want IMQ)\n", order);
        return 1;
    }
    if (!support.enabled) {
        printf("FAIL support was not initialized before population\n");
        return 1;
    }

    puts("autorefresh: newly-started support always gets one immediate list population");
    return 0;
}
'''.replace("@FUNCTION@", fn)

if not failures:
    with tempfile.TemporaryDirectory(prefix="opl-autorefresh-") as tmp:
        src = Path(tmp) / "autorefresh.c"
        exe = Path(tmp) / "autorefresh"
        src.write_text(HARNESS, encoding="utf-8")
        build = subprocess.run(
            ["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(src)],
            capture_output=True, text=True, check=False,
        )
        if build.returncode != 0:
            failures.append("host harness did not compile:\n" + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append("host harness reported failure")

if failures:
    print("Automatic Refresh initial-population checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)
