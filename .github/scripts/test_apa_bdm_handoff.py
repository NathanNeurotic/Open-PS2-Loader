"""Source-level safety invariants for the APA-hosted ELF -> ATA-BDM/exFAT handoff (#545).

This is deliberately a structural regression test, not a hardware simulation. The dangerous failures
found during the #715 audit were ownership/order bugs: force-closing PFS before a successful unmount,
reacquiring PFS during a BDM-owned save, broad device discovery, and double-acquiring the ATA stack.
Pin those properties so later config refactors cannot silently reintroduce them.
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[2]
failures = []


def text(path):
    return path.read_text().replace('\r\n', '\n')


def check(condition, message):
    if not condition:
        failures.append(message)


def function_body(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        return None
    depth = 0
    start = source.find('{', match.start())
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[match.start():i + 1]
    return None


opl = text(root / 'src/opl.c')
hdd = text(root / 'src/hddsupport.c')
bdm = text(root / 'src/bdmsupport.c')

release = function_body(hdd, 'int hddReleasePfsForBdm(')
check(release is not None, 'hddReleasePfsForBdm is missing')
if release is not None:
    check(not re.search(r'fileXioDevctl\\s*\\(\\s*"pfs:"\\s*,\\s*PDIOC_CLOSEALL', release),
          'APA->BDM handoff force-closes PFS descriptors before ownership is transferred')
    check('fileXioUmount("pfs1:")' not in release,
          'APA->BDM handoff unexpectedly tears down the unrelated pfs1: scratch mount')
    check('fileXioUmount(hddPrefix)' in release,
          'APA->BDM handoff no longer requires a successful pfs0: unmount')
    failed = release.find('if (ret < 0)')
    clear = release.find('gHDDPrefix = NULL')
    check(failed >= 0 and clear > failed,
          'gHDDPrefix can be cleared before the pfs0: unmount failure is handled')
    check('return 0;' in release[failed:clear],
          'failed pfs0: unmount no longer aborts the BDM handoff')

alternate = function_body(opl, 'static int tryAlternateDevice(')
check(alternate is not None, 'tryAlternateDevice is missing')
if alternate is not None:
    apa = alternate.find('if (gBootHomeApa)')
    handoff = alternate.find('hddReleasePfsForBdm()', apa)
    ata_only = alternate.find('bdmEnsureSourceModules(BDM_TYPE_ATA', handoff)
    root_by_type = alternate.find('bdmGetDeviceRootByType(BDM_TYPE_ATA', ata_only)
    recovery = alternate.find('tryReadRecoveryConfigHome(types, home)', root_by_type)
    owner = alternate.find('gBootApaConfigFromBdm = 1', recovery)
    restore = alternate.find('hddLoadSupportModules()', owner)
    check(apa >= 0 and handoff > apa and ata_only > handoff and root_by_type > ata_only and
          recovery > root_by_type and owner > recovery,
          'GUI APA->BDM recovery no longer transfers ownership in the audited order')
    check(restore > owner,
          'failed ATA-BDM config discovery no longer restores the original APA/PFS home')
    region = alternate[apa:restore if restore > 0 else len(alternate)]
    check('BDM_TYPE_USB' not in region and 'BDM_TYPE_SDC' not in region and 'BDM_TYPE_ILINK' not in region,
          'APA->BDM recovery broadened beyond the ATA device that owns the reported config')

save = function_body(opl, 'static void _saveConfig(')
check(save is not None, '_saveConfig is missing')
if save is not None:
    check(save.count('gBootHomeApa && !gBootApaConfigFromBdm') >= 2,
          'BDM-owned APA boot can reacquire PFS through an APA save path')
    check('prepareHddSettingsFallback' in save,
          'normal APA save fallback disappeared while guarding the BDM-owned case')

redirect = function_body(opl, 'static int configPathRedirectLocation(')
check(redirect is not None, 'configPathRedirectLocation is missing')
if redirect is not None:
    check('gBootApaConfigFromBdm' in redirect and 'gBootApaBdmConfigHome' in redirect,
          'config.path no longer follows the BDM settings owner on an APA-hosted ELF')

load = function_body(opl, 'static void _loadConfig(')
check(load is not None, '_loadConfig is missing')
if load is not None:
    check(re.search(r'!configGetInt\(configOPL, CONFIG_OPL_HDD_MODE, &gHDDStartMode\).*?'
                    r'gBootHomeApa && !gBootApaConfigFromBdm', load, re.S),
          'legacy HDD-mode fallback can re-enable APA after BDM became the settings owner')

ensure = function_body(bdm, 'static int bdmEnsureTransportLoaded(')
check(ensure is not None, 'bdmEnsureTransportLoaded is missing')
if ensure is not None:
    ata = re.search(r'case BDM_TYPE_ATA:(.*?)default:', ensure, re.S)
    check(ata is not None and 'hddModulesAreLoaded() || hddLoadModulesReady()' in ata.group(1),
          'BDM ATA handoff can double-acquire an ATA stack already loaded by APA discovery')

mini = function_body(opl, 'static void miniInit(')
check(mini is not None, 'miniInit is missing')
if mini is not None:
    check('apaBdmAutoLaunch' in mini and
          'configInit(apaBdmAutoLaunch ? NULL' in mini and
          'if (!apaBdmAutoLaunch)' in mini and
          'ret = checkLoadConfigBDM(CONFIG_ALL)' in mini,
          'APA-hosted BDM auto-launch no longer follows the official-style no-PFS config ordering')

# The handoff itself must remain metadata-neutral. These operations belong nowhere in the #545 path.
for forbidden in ('fileXioFormat(', 'hddCreateOPLPartition(', 'HDIOC_WRITESECTOR', 'hddDeleteGame',
                  'hddSetHDLGameInfo'):
    if release is not None:
        check(forbidden not in release, 'hddReleasePfsForBdm contains unsafe operation: ' + forbidden)

if failures:
    print('APA -> BDM handoff safety checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)

print('APA -> BDM handoff safety invariants: OK')
