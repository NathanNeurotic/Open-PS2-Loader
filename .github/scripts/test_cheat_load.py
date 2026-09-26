"""A cheat file that exists but will not load must never be reported as "no cheats found".

sbLoadCheats (src/supportbase.c) tries CHT/cht.tar, then CHT/<ID>.cht, then CHT/<ID>.CHT, and returns
-ENOENT only when there is no cheat source at all -- the launch legs show "No cheats found" for that,
and with cheats switched on for ALL games the launch now continues with no prompt. Anything that
exists and fails to load must come back as a load failure, which always prompts.

It used to probe only the LAST spelling tried, so an existing-but-broken "<ID>.cht" read as absent
whenever "<ID>.CHT" was missing, and a cht.tar member that failed to parse read as absent whenever
the loose files were missing (CodeRabbit on PR #756).

This compiles sbCheatLogAppend and sbLoadCheats on the host with the tar engine, the .cht parser
and open() replaced by a scripted device, and checks every combination that matters.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/supportbase.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/supportbase.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


member_max = re.search(r'^#define CHT_TAR_MEMBER_MAX\s+(.+)$', source, re.M)
if member_max is None:
    failures.append('src/supportbase.c: #define CHT_TAR_MEMBER_MAX not found')
functions = function_text('static void sbCheatLogAppend(') + function_text('int sbLoadCheats(')

HARNESS = r'''
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned int u32;
#define LOG(...) ((void)0)
#define O_RDONLY 0
#define CHT_TAR_MEMBER_MAX @MEMBER_MAX@
typedef enum { TAR_KIND_CHT = 2 } TarKind;
typedef struct { u32 rawSize; } TarEntryBase;
static void *gAutoLaunchGame, *gAutoLaunchBDMGame;
static char cheatSearchLog[512];

/* Scripted device. Loose files: exists? and what load_cheats returns for each spelling. */
static int lowerExists, lowerLoad, upperExists, upperLoad;
/* cht.tar: a member present (with this size) and what its parse returns. */
static int tarPresent, tarParse;
static TarEntryBase tarEntry;

static int GetCheatsEnabled(void) { return 1; }
static void guiManageCheats(void) {}
static const char *tarGetDevicePrefix(TarKind k) { (void)k; return "mass0:"; }
static TarEntryBase *tarFind(TarKind k, const char *name) { (void)k; return (tarPresent && strstr(name, ".cht")) ? &tarEntry : NULL; }
static u32 tarRead(TarKind k, const TarEntryBase *e, void *dst, u32 n) { (void)k; (void)e; memset(dst, 'x', n); return n; }
static int load_cheats_buf(const char *buf) { (void)buf; return tarParse; }
static int isUpper(const char *p) { size_t n = strlen(p); return n >= 3 && !strcmp(p + n - 3, "CHT"); }
static int load_cheats(const char *p) { return isUpper(p) ? upperLoad : lowerLoad; }
static int open(const char *p, int f) { (void)f; return (isUpper(p) ? upperExists : lowerExists) ? 7 : -1; }
static int close(int fd) { (void)fd; return 0; }

@FUNCTIONS@

static int fails;
static void scenario(const char *name, int le, int ll, int ue, int ul, int tp, u32 tsize, int tparse, int want)
{
    int got;
    lowerExists = le; lowerLoad = ll; upperExists = ue; upperLoad = ul;
    tarPresent = tp; tarEntry.rawSize = tsize; tarParse = tparse;
    got = sbLoadCheats("mass0:/", "SLUS_203.70");
    /* want: -ENOENT exactly, a load FAILURE (any negative but -ENOENT), or a mode >= 0 */
    if ((want == -ENOENT && got != -ENOENT) || (want == -1 && (got >= 0 || got == -ENOENT)) || (want >= 0 && got != want)) {
        printf("FAIL %s: sbLoadCheats returned %d (want %s)\n", name, got,
               want == -ENOENT ? "-ENOENT" : want == -1 ? "a load failure (not -ENOENT)" : "the cheat mode");
        fails++;
    }
}

int main(void)
{
    /*        name                                   lowE lowLd upE upLd tar size tarParse  want */
    scenario("nothing anywhere",                       0, -1,   0, -1,  0,  0,  0,      -ENOENT);
    scenario("broken <ID>.cht, no <ID>.CHT",           1, -1,   0, -1,  0,  0,  0,      -1);
    scenario("no <ID>.cht, broken <ID>.CHT",           0, -1,   1, -1,  0,  0,  0,      -1);
    scenario("broken .cht whose load says -ENOENT",    1, -ENOENT, 0, -1, 0, 0,  0,      -1);
    scenario("good <ID>.cht",                          1,  0,   0, -1,  0,  0,  0,      0);
    scenario("good <ID>.CHT (select mode)",            0, -1,   1,  1,  0,  0,  0,      1);
    scenario("broken tar member, no loose file",       0, -1,   0, -1,  1, 64, -1,      -1);
    scenario("good tar member",                        0, -1,   0, -1,  1, 64,  0,      0);
    scenario("empty tar member, no loose file",        0, -1,   0, -1,  1,  0,  0,      -ENOENT);
    scenario("broken tar member, good loose file",     1,  0,   0, -1,  1, 64, -1,      0);
    return fails ? 1 : 0;
}
'''


def run_harness():
    program = (HARNESS.replace('@MEMBER_MAX@', member_max.group(1).strip() if member_max else '0')
               .replace('@FUNCTIONS@', functions))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'cheats.c'
        exe = Path(tmp) / 'cheats'
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        if result.returncode != 0:
            lines = [line for line in result.stdout.splitlines() if line]
            # A crash prints nothing: never let a dead harness read as a pass.
            failures.extend(lines or ['harness exited %d with no result:\n%s' % (result.returncode, result.stderr)])


if not failures:
    run_harness()

if failures:
    print('Cheat load checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('cheat load: 10 device/tar scenarios OK (absent -> -ENOENT, broken -> load failure)')
