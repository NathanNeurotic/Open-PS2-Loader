"""The keep-IOP handoff probe must not refuse a target the child could still load (#755 triage).

sysLoadELFCommon (src/elfldr_noreset.c) opens the target once more after the launch teardown, so a bad
path fails in OPL instead of inside the child loader. On FatBaldDad's UDPBD setup neutrino.elf on
mmce0: opened fine before the teardown and failed that probe after it, and the old probe refused on
the first failed open(). The child loads the target through fileXio, not newlib, so the probe now:

- returns at once, with no delay, when the first open() works (the normal case);
- accepts a file that only fileXio can open (the child's own route);
- retries a bounded ~3 s for a device that is still settling;
- on a real refusal, tells "device root still opens" from "device root gone" apart.

This compiles probeTargetOnce, probeDeviceRootOpens and probeTarget from src/elfldr_noreset.c on the
host with open/fileXio/DelayThread replaced by a scripted device, and checks each outcome, the time
it costs and the diagnostic code it reports.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/elfldr_noreset.c').read_text(encoding='utf-8').replace('\r\n', '\n')
header = (root / 'include/launchdiag.h').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('src/elfldr_noreset.c: %s...) not found' % signature)
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def define(name):
    match = re.search(r'^#define ' + name + r'\s+(.+)$', source, re.M)
    if match is None:
        failures.append('src/elfldr_noreset.c: #define %s not found' % name)
        return '0'
    return match.group(1).strip()


enum = re.search(r'enum LaunchDiagRefusal \{.*?\};', header, re.S)
if enum is None:
    failures.append('include/launchdiag.h: enum LaunchDiagRefusal not found')

functions = ''.join(function_text(sig) for sig in (
    'static int probeTargetOnce(',
    'static int probeDeviceRootOpens(',
    'static int probeTarget(',
))

# The probe must be what sysLoadELFCommon actually calls, ahead of the stage-10 marker.
common = function_text('static int sysLoadELFCommon(')
call = common.find('probeTarget(filename, diag)')
if call < 0 or call > common.find('launchDiagMark(10)'):
    failures.append('sysLoadELFCommon: must gate the handoff on probeTarget(filename, diag) before stage 10')
if re.search(r'open\(filename, O_RDONLY\)', common):
    failures.append('sysLoadELFCommon: a bare open() probe is back -- it refuses what the child could load')

HARNESS = r'''
#include <stdio.h>
#include <string.h>

#define LOG(...) ((void)0)
#define O_RDONLY 0
#define PROBE_RETRIES @RETRIES@
#define PROBE_RETRY_US @RETRY_US@
@ENUM@

/* Scripted device: open() succeeds from call number openOkFrom on (0 = never), fileXioOpen likewise. */
static int openCalls, xioCalls, openOkFrom, xioOkFrom, rootOk;
static long delayedUs;
static int held, refused;
static char lastRoot[64];

static int open(const char *p, int f) { (void)p; (void)f; ++openCalls; return (openOkFrom && openCalls >= openOkFrom) ? 3 : -1; }
static int close(int fd) { (void)fd; return 0; }
static int fileXioOpen(const char *p, int f, int m) { (void)p; (void)f; (void)m; ++xioCalls; return (xioOkFrom && xioCalls >= xioOkFrom) ? 4 : -1; }
static int fileXioClose(int fd) { (void)fd; return 0; }
static int fileXioDopen(const char *p) { snprintf(lastRoot, sizeof(lastRoot), "%s", p); return rootOk ? 5 : -1; }
static int fileXioDclose(int fd) { (void)fd; return 0; }
static void DelayThread(int us) { delayedUs += us; }
static void launchDiagHold(int stage, int ms) { (void)ms; held = stage; }
static void launchDiagRefuse(int code) { refused = code; }

@FUNCTIONS@

static int fails;
static void run(const char *name, const char *path, int openFrom, int xioFrom, int rootIsOk, int diag,
                int wantRet, long wantDelayUs, int wantHeld, int wantRefused, const char *wantRoot)
{
    int ret;
    openCalls = xioCalls = 0;
    delayedUs = 0;
    held = refused = 0;
    lastRoot[0] = 0;
    openOkFrom = openFrom;
    xioOkFrom = xioFrom;
    rootOk = rootIsOk;
    ret = probeTarget(path, diag);
    if (ret != wantRet || delayedUs != wantDelayUs || held != wantHeld || refused != wantRefused ||
        (wantRoot && strcmp(lastRoot, wantRoot))) {
        printf("FAIL %s: ret=%d delay=%ldus held=%d refused=%d root='%s' (want %d %ldus %d %d '%s')\n", name, ret,
               delayedUs, held, refused, lastRoot, wantRet, wantDelayUs, wantHeld, wantRefused, wantRoot ? wantRoot : "");
        fails++;
    }
}

int main(void)
{
    const long step = PROBE_RETRY_US, all = (long)PROBE_RETRIES * PROBE_RETRY_US;

    run("first open works", "mmce0:/NEUTRINO/neutrino.elf", 1, 0, 1, 1, 0, 0, 0, 0, NULL);
    run("fileXio only", "mmce0:/NEUTRINO/neutrino.elf", 0, 1, 1, 1, 0, 0, 15, 0, NULL);
    run("settles on 4th open", "mmce0:/NEUTRINO/neutrino.elf", 4, 0, 1, 1, 0, 3 * step, 16, 0, NULL);
    run("fileXio settles later", "mass0:/NEUTRINO/neutrino.elf", 0, 3, 1, 1, 0, 2 * step, 15, 0, NULL);
    run("gone, root opens", "mmce0:/NEUTRINO/neutrino.elf", 0, 0, 1, 1, -1, all, 0, LAUNCHDIAG_REFUSE_OPEN_ROOT_OK, "mmce0:/");
    run("gone, root gone", "mmce0:NEUTRINO/neutrino.elf", 0, 0, 0, 1, -1, all, 0, LAUNCHDIAG_REFUSE_OPEN_ROOT_GONE, "mmce0:/");
    run("pfs root", "pfs0:OPL/NEUTRINO/neutrino.elf", 0, 0, 0, 1, -1, all, 0, LAUNCHDIAG_REFUSE_OPEN_ROOT_GONE, "pfs0:/");
    run("no diag: no markers", "mmce0:/NEUTRINO/neutrino.elf", 0, 1, 1, 0, 0, 0, 0, 0, NULL);
    run("no diag refusal", "mmce0:/NEUTRINO/neutrino.elf", 0, 0, 0, 0, -1, all, 0, 0, NULL);

    if (all < 2000000 || all > 5000000) {
        printf("FAIL retry budget %ld us: must stay a bounded few seconds\n", all);
        fails++;
    }
    return fails ? 1 : 0;
}
'''


def run_harness():
    program = (HARNESS.replace('@RETRIES@', define('PROBE_RETRIES'))
               .replace('@RETRY_US@', define('PROBE_RETRY_US'))
               .replace('@ENUM@', enum.group(0) if enum else '')
               .replace('@FUNCTIONS@', functions))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'probe.c'
        exe = Path(tmp) / 'probe'
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
            return
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.extend(line for line in result.stdout.splitlines() if line)


if not failures:
    run_harness()

if failures:
    print('Handoff probe checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
print('handoff probe: 9 device scenarios, retry budget and call site OK')
