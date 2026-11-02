#!/usr/bin/env python3
"""The OPL core's i.LINK pair stops visibly when it cannot start.

ee_core loads iLinkman, then IEEE1394_bd only when iLinkman started. Both are required transports:
one that does not load, or loads but declines to stay resident, stops the boot on the blinking red
screen (modmgr.c, RequiredTransportFailed) instead of leaving CDVDMAN waiting on a black screen for a
drive that can never attach.
"""
from pathlib import Path
import re
import sys

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
check('if (IsRequiredTransport(id) && (result < 1 || moduleStartResult != 0))\n                RequiredTransportFailed();' in modmgr,
      'modmgr.c: a required transport that loads but does not stay resident halts visibly')

if failures:
    sys.exit(1)
print('i.LINK game transport: iLinkman before IEEE1394_bd, and a failed start of either halts visibly')
