#!/usr/bin/env python3
"""The OPL core's i.LINK pair stops visibly when it cannot start.

ee_core loads iLinkman, then IEEE1394_bd only when iLinkman started. Both are required transports:
one that the menu did not pack, that is empty, that MODLOAD refused, or that loaded and declined to
stay resident stops the boot on the blinking red screen (modmgr.c, RequiredTransportFailed) instead of
leaving CDVDMAN waiting on a black screen for a drive that can never attach.

The real IsRequiredTransport, RequiredTransportFailed and LoadOPLModule are compiled against a mocked
module table and MODLOAD, with and without the flavour defines that add module IDs, and every failure
is played through every required transport and through a module that is not one.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
failures = 0


def check(condition, message):
    global failures
    if not condition:
        print('FAIL: ' + message)
        failures += 1


def function(source, signature, name):
    start = source.find(signature + '\n{')
    if start < 0:
        raise SystemExit('FAIL: %s: %s not found' % (name, signature))
    return source[start:source.index('\n}', start) + 2]


iopmgr = (ROOT / 'ee_core/src/iopmgr.c').read_text(encoding='utf-8')
modmgr = (ROOT / 'ee_core/src/modmgr.c').read_text(encoding='utf-8')

case_start = iopmgr.find('case BDM_ILK_MODE:')
check(case_start >= 0, 'iopmgr.c: the i.LINK game mode loads its transport')
case = iopmgr[case_start:iopmgr.find('break;', case_start)] if case_start >= 0 else ''
check('if (LoadOPLModule(OPL_MODULE_ID_ILINK, 0, 0, NULL) > 0)\n                LoadOPLModule(OPL_MODULE_ID_ILINKBD, 0, 0, NULL);' in case,
      'iopmgr.c: IEEE1394_bd starts only after iLinkman started')

required = function(modmgr, 'static int IsRequiredTransport(int id)', 'ee_core/src/modmgr.c')
for module in ('OPL_MODULE_ID_ILINK', 'OPL_MODULE_ID_ILINKBD'):
    check(re.search(r'\bid == %s\b' % module, required) is not None,
          'modmgr.c: %s is a required transport, so a failed start is a red screen, not a black one' % module)

parts = '\n\n'.join((required,
                     function(modmgr, 'static void RequiredTransportFailed(void)', 'ee_core/src/modmgr.c'),
                     function(modmgr, 'int LoadOPLModule(int id, int mode, int arg_len, const char *args)',
                              'ee_core/src/modmgr.c')))

HARNESS = r"""
#include <setjmp.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "modules.h"
#define MODMGR 0
#define DBGCOL(...) ((void)0)
#define BGCOLND(...) ((void)0)
#define DBGCOL_BLNK(count, colour, forever, type, description) halt(description)
static int EnableDebug, failures, packed, size, loadResult, startResult, loads;
static const char *halted;
static jmp_buf stop;
static int moduleStartResult;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL: " __VA_ARGS__); printf("\n"); failures++; } } while (0)
static void halt(const char *why) { halted = why; longjmp(stop, 1); }
static void delay(int seconds) { (void)seconds; }
static char blob[16];
static int GetOPLModInfo(int id, void **pointer, unsigned int *bytes)
{
    (void)id;
    if (!packed)
        return -1;
    *pointer = blob;
    *bytes = size;
    return 0;
}
static int LoadMemModule(int mode, void *modptr, unsigned int modsize, int arg_len, const char *args)
{
    (void)mode; (void)modptr; (void)modsize; (void)arg_len; (void)args;
    loads++;
    if (loadResult > 0)
        moduleStartResult = startResult; /* MODLOAD only reports a start result for a module it started */
    return loadResult;
}
@FUNCTIONS@
enum outcome { RETURNS, TRANSPORT_HALT, OOM_HALT };
static int play(int id, int isPacked, int bytes, int result, int start, int *returned)
{
    packed = isPacked; size = bytes; loadResult = result; startResult = start; loads = 0; halted = NULL;
    moduleStartResult = 12345; /* whatever the previous module left */
    if (setjmp(stop) == 0) {
        *returned = LoadOPLModule(id, 0, 0, NULL);
        return RETURNS;
    }
    return strstr(halted, "out of IOP Memory") ? OOM_HALT : TRANSPORT_HALT;
}
int main(void)
{
    static const int transports[] = {OPL_MODULE_ID_ILINK, OPL_MODULE_ID_ILINKBD, OPL_MODULE_ID_PCCF, OPL_MODULE_ID_SMAP_UDPBD,
                                     OPL_MODULE_ID_UDPFS_SMAP, OPL_MODULE_ID_UDPFS_MINISTACK, OPL_MODULE_ID_UDPFS_BD,
                                     OPL_MODULE_ID_UDPFS_FHI};
    static const int others[] = {OPL_MODULE_ID_USBD, OPL_MODULE_ID_USBMASSBD, OPL_MODULE_ID_MCEMU, OPL_MODULE_ID_PADEMU};
    int i, debug, r, got;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (debug = 0; debug < 2; debug++) {
        EnableDebug = debug;
        for (i = 0; i < (int)(sizeof(transports) / sizeof(transports[0])); i++) {
            int id = transports[i];
            CHECK(play(id, 0, 0, 0, 0, &r) == TRANSPORT_HALT, "module %d: a required transport the menu did not pack halts", id);
            CHECK(play(id, 1, 0, 0, 0, &r) == TRANSPORT_HALT && !loads, "module %d: an empty required transport halts", id);
            CHECK(play(id, 1, 8, -200, 0, &r) == TRANSPORT_HALT, "module %d: a required transport MODLOAD refused halts", id);
            CHECK(play(id, 1, 8, -400, 0, &r) != RETURNS, "module %d: a required transport without IOP memory halts", id);
            CHECK(play(id, 1, 8, 1, 1, &r) == TRANSPORT_HALT, "module %d: a required transport that declines to stay resident halts", id);
            got = play(id, 1, 8, 1, 0, &r);
            CHECK(got == RETURNS && r == 1 && loads == 1, "module %d: a required transport that stays resident boots on", id);
        }
        for (i = 0; i < (int)(sizeof(others) / sizeof(others[0])); i++) {
            int id = others[i];
            CHECK(play(id, 0, 0, 0, 0, &r) == RETURNS && r == -1, "module %d: an optional module the menu did not pack is skipped", id);
            CHECK(play(id, 1, 0, 0, 0, &r) == RETURNS && r == 0, "module %d: an empty optional module is skipped", id);
            CHECK(play(id, 1, 8, -200, 0, &r) == RETURNS && r == -200, "module %d: MODLOAD's refusal is returned", id);
            CHECK(play(id, 1, 8, 1, 1, &r) == RETURNS && r == 1, "module %d: a non-resident optional module is not a transport failure", id);
            CHECK(play(id, 1, 8, -400, 0, &r) == OOM_HALT, "module %d: out of IOP memory still stops on the MODLOAD loop", id);
        }
    }
    return failures ? 1 : 0;
}
"""

FLAVOURS = ((), ('RETROACHIEVEMENTS', 'INGAMEDIAG', 'IGR_MENU'))
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    cfile = folder / 'transport.c'
    cfile.write_text(HARNESS.replace('@FUNCTIONS@', parts), encoding='utf-8')
    for defines in FLAVOURS:
        exe = folder / ('transport.exe' if sys.platform == 'win32' else 'transport')
        build = subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                                '-Wno-clobbered'] + ['-D' + d for d in defines] +
                               ['-I', str(ROOT / 'ee_core/include'), str(cfile), '-o', str(exe)],
                               capture_output=True, text=True, timeout=60)
        if build.returncode != 0:
            print(build.stdout + build.stderr)
            check(False, 'modmgr.c: LoadOPLModule compiles in the harness (%s)' % (' '.join(defines) or 'no flavour defines'))
            continue
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        if result.stdout.strip():
            print(result.stdout.strip())
        check(result.returncode == 0, 'modmgr.c: LoadOPLModule halts exactly the failed required transports (%s)' %
              (' '.join(defines) or 'no flavour defines'))

if failures:
    sys.exit(1)
print('i.LINK game transport: iLinkman before IEEE1394_bd, and every failed start of a required transport halts visibly')
