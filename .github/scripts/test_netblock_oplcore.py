"""UDPBD and UDPFS IMG games boot the OPL core when their own Loader Core says <OPL> (YAOPL b3ff109).

The udp BDM device used to be Neutrino-only. Now the native launch picks a ninth CDVDMAN variant
(bdm_udp_cdvdman, which exports dev9 and bdm), hands the EE core BDM_UDP_MODE or BDM_UFS_MODE, and the
EE core reloads the block chain the menu used after the IOP reset. This checks that wiring end to end
in the sources and runs the real core picker (bdmNetBlockCoreLoader) against every config state.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def check(cond, msg):
    if not cond:
        failures.append(msg)


def function(text, head, where):
    i = text.find(head)
    if i < 0:
        failures.append('%s: %s not found' % (where, head))
        return ''
    return text[i:text.index('\n}\n', i) + 3]


bdm = read('src/bdmsupport.c')
system = read('src/system.c')
iopmgr = read('ee_core/src/iopmgr.c')
main_c = read('ee_core/src/main.c')
ee_core_h = read('ee_core/include/ee_core.h')
modules_h = read('ee_core/include/modules.h')
cdvdman_make = read('modules/iopcore/cdvdman/Makefile')
ioplib = read('modules/iopcore/cdvdman/ioplib_util.c')
top = read('Makefile')
extern_irx = read('include/extern_irx.h')
menusys = read('src/menusys.c')
guigame = read('src/guigame.c')

# 1. The core picker: Neutrino unless the game's own key is <OPL> (0). Compiled from the source.
picker = function(bdm, 'int bdmNetBlockCoreLoader(config_set_t *configSet)', 'src/bdmsupport.c')
harness = r'''
#include <assert.h>
#include <stddef.h>
#define CONFIG_ITEM_CORE_LOADER "$CoreLoader"
typedef struct { int present, value; } config_set_t;
static int configGetInt(config_set_t *c, const char *key, int *v)
{
    (void)key;
    if (!c->present) return 0;
    *v = c->value;
    return 1;
}
@PICKER@
int main(void)
{
    config_set_t c = {0, 0};
    assert(bdmNetBlockCoreLoader(NULL) == 1);
    assert(bdmNetBlockCoreLoader(&c) == 1);  /* Default: Neutrino, whatever the global core */
    c.present = 1; c.value = 1;
    assert(bdmNetBlockCoreLoader(&c) == 1);  /* Neutrino */
    c.value = 0;
    assert(bdmNetBlockCoreLoader(&c) == 0);  /* <OPL> */
    c.value = 7;
    assert(bdmNetBlockCoreLoader(&c) == 1);  /* anything else stays on Neutrino */
    return 0;
}
'''.replace('@PICKER@', picker)
if picker:
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / 'picker.c'
        exe = Path(tmp) / ('picker' + ('.exe' if sys.platform == 'win32' else ''))
        c.write_text(harness, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('core picker harness did not compile:\n' + build.stderr)
        elif subprocess.run([str(exe)]).returncode != 0:
            failures.append('bdmNetBlockCoreLoader: wrong core for a config state')

# 2. Every place that resolves the core of a udp game uses the picker, and UDPFS Files stays Neutrino.
neutrino = function(bdm, 'static int bdmTryNeutrinoLaunch(', 'src/bdmsupport.c')
check('if (isUdp)\n        coreLoader = bdmNetBlockCoreLoader(configSet);' in neutrino,
      'bdmTryNeutrinoLaunch: the udp device must take its core from bdmNetBlockCoreLoader')
check('int failResult = 0;' in neutrino,
      'bdmTryNeutrinoLaunch: a failed udp Neutrino leg falls back to the OPL core, like local devices')
check('bdmDevNr) < 0) {\n        if (isUdp)\n            failResult = 1;\n        goto fail;' in neutrino,
      'Neutrino leg: a failed preflight (bsd toml) on udp aborts, as its toast says')
check('_STR_NET_NEEDS_NEUTRINO' not in neutrino,
      'bdmTryNeutrinoLaunch: udp games are no longer Neutrino-only')
check(menusys.count('bdmNetBlockCoreLoader(itemConfig)') == 2,
      'gameMenuCoreIsNeutrino: both udp branches (Favourites and direct) use the picker')
check(guigame.count('bdmNetBlockCoreLoader(configSet)') == 2,
      'guigame.c: effective core and auto-VMC core both use the picker for udp')

# 3. The native launch: the udp CDVDMAN variant, DEV9/SMAP faked, the mode chosen from the resident chain.
check('irx = &bdm_udp_cdvdman_irx;' in bdm and 'irx_size = size_bdm_udp_cdvdman_irx;' in bdm,
      'bdmLaunchGame: the udp device takes bdm_udp_cdvdman')
check('!bdmDriverIsUDPBD(pDeviceData->bdmDriver) && pDeviceData->bdmDeviceType != BDM_TYPE_PCCF' in bdm,
      'bdmLaunchGame: the native guard admits the udp device')
read_at = bdm.find('int netBlockProtocol = bdmGetLoadedNetProtocol();')
teardown = bdm.find('deinit(NO_EXCEPTION, itemList->mode);', read_at)
check(read_at >= 0 and teardown > read_at,
      'bdmLaunchGame: the resident protocol is read before the teardown')
branch = bdm[bdm.find('} else if (bdmDriverIsUDPBD(bdmCurrentDriver)) {'):]
branch = branch[:branch.find('\n    }\n')]
check('FAKE_MODULE_FLAG_DEV9' in branch and 'FAKE_MODULE_FLAG_SMAP' in branch,
      'bdmLaunchGame: the game\'s own DEV9 and SMAP are faked on udp')
check('netBlockProtocol == NET_BOOT_UDPFS ? "BDM_UFS_MODE" : "BDM_UDP_MODE"' in branch,
      'bdmLaunchGame: UDPFS IMG launches BDM_UFS_MODE, UDPBD launches BDM_UDP_MODE')

# 4. The CDVDMAN variant: BDM driver with DEV9, fakes SMAP, built and embedded.
variant = cdvdman_make[cdvdman_make.find('ifeq ($(USE_BDM_UDP),1)'):]
variant = variant[:variant.find('endif')]
check('IOP_BIN  = bdm_udp_cdvdman.irx' in variant and '-DBDM_DRIVER -DUSE_BDM_UDP' in variant and
      'USE_DEV9 = 1' in variant and 'device-bdm.o' in variant and '-lbdm' in variant,
      'cdvdman Makefile: USE_BDM_UDP is a BDM variant with DEV9 and bdm')
check('#if defined(SMB_DRIVER) || defined(HTTP_DRIVER) || defined(USE_BDM_UDP)' in ioplib,
      'ioplib_util.c: the udp variant fakes the game\'s SMAP like SMB and HTTP')
check('USE_BDM_UDP=1 -C $< all' in top and 'bdm_udp_cdvdman.o' in top and 'USE_BDM_UDP=1 clean' in top,
      'Makefile: bdm_udp_cdvdman is built, embedded and cleaned')
check('IMPORT_BIN2C(bdm_udp_cdvdman_irx);' in extern_irx, 'extern_irx.h: bdm_udp_cdvdman_irx is declared')

# 5. The EE core: both modes parsed and their chains reloaded in order with the static IP.
check(re.search(r'BDM_CF_MODE = 32,\n\s*BDM_UDP_MODE,[^\n]*\n\s*BDM_UFS_MODE,', ee_core_h) is not None,
      'ee_core.h: BDM_UDP_MODE and BDM_UFS_MODE follow BDM_CF_MODE')
for mode in ('BDM_UDP_MODE', 'BDM_UFS_MODE'):
    check('!_strncmp(config->GameModeDesc, "%s", 12))\n        config->GameMode = %s;' % (mode, mode) in main_c,
          'ee_core main.c: %s is parsed' % mode)
check(re.search(r'OPL_MODULE_ID_PCCF = 60,\n(?:\s*//[^\n]*\n|\s*\n)*\s*OPL_MODULE_ID_SMAP_UDPBD,\n\s*OPL_MODULE_ID_UDPFS_SMAP,\n'
                r'\s*OPL_MODULE_ID_UDPFS_MINISTACK,\n\s*OPL_MODULE_ID_UDPFS_BD,\n\s*OPL_MODULE_ID_COUNT', modules_h) is not None,
      'modules.h: the network block IDs are appended after PCCF')
case = iopmgr[iopmgr.find('case BDM_UDP_MODE:'):]
case = case[:case.find('break;') + 6]
check('case BDM_UFS_MODE: {' in case and '_strcpy(&ipArg[3], config->g_ps2_ip);' in case,
      'iopmgr.c: both modes pass ip=<static PS2 IP>')
check('LoadOPLModule(OPL_MODULE_ID_SMAP_UDPBD, 0, strlen(ipArg) + 1, ipArg);' in case,
      'iopmgr.c: UDPBD reloads smap_udpbd with its IP')
smap = case.find('LoadOPLModule(OPL_MODULE_ID_UDPFS_SMAP, 0, 0, NULL) > 0')
stack = case.find('LoadOPLModule(OPL_MODULE_ID_UDPFS_MINISTACK, 0, strlen(ipArg) + 1, ipArg) > 0')
bd = case.find('LoadOPLModule(OPL_MODULE_ID_UDPFS_BD, 0, 0, NULL);')
check(0 <= smap < stack < bd, 'iopmgr.c: UDPFS reloads smap, then ministack (with IP), then udpfs_bd, each after the one before')
check('config->GameMode != BDM_UDP_MODE &&\n        config->GameMode != BDM_UFS_MODE && RA_TelemetryWanted(config)' in iopmgr,
      'iopmgr.c: no RA SMAP/SMSTCPIP beside the block driver')

modmgr = read('ee_core/src/modmgr.c')
required = function(modmgr, 'static int IsRequiredTransport(int id)', 'ee_core/src/modmgr.c')
check(all(m in required for m in ('OPL_MODULE_ID_PCCF', 'OPL_MODULE_ID_SMAP_UDPBD', 'OPL_MODULE_ID_UDPFS_SMAP',
                                  'OPL_MODULE_ID_UDPFS_MINISTACK', 'OPL_MODULE_ID_UDPFS_BD')),
      'modmgr.c: every network block module is a required transport')
check('if (IsRequiredTransport(id) && (result < 1 || moduleStartResult != 0))\n                RequiredTransportFailed();' in modmgr,
      'modmgr.c: a required transport that loads but does not stay resident halts visibly')
check(modmgr.count('RequiredTransportFailed();') == 3,
      'modmgr.c: failed, empty and unpacked required transports all halt visibly')

# 6. The menu packs the right modules and nothing else that would take the adapter.
check('static int sysModeIsNetBlock(const char *mode_str)' in system and
      'return !strcmp(mode_str, "BDM_UDP_MODE") || !strcmp(mode_str, "BDM_UFS_MODE");' in system,
      'system.c: both net-block modes are recognised')
check('modules &= ~(CORE_IRX_ETH | CORE_IRX_SMB | CORE_IRX_DECI2);' in system,
      'system.c: sendIrxKernelRAM never packs a second SMAP stack for net-block modes')
check('modules &= ~(CORE_IRX_ETH | CORE_IRX_DECI2 | CORE_IRX_DEBUG);' in system,
      'system.c: sysLaunchLoaderElf strips udptty/DECI2 for net-block modes')
check('SET_OPL_MOD_ID(OPL_MODULE_ID_SMAP_UDPBD)' in system and 'SET_OPL_MOD_ID(OPL_MODULE_ID_UDPFS_SMAP)' in system and
      'SET_OPL_MOD_ID(OPL_MODULE_ID_UDPFS_MINISTACK)' in system and 'SET_OPL_MOD_ID(OPL_MODULE_ID_UDPFS_BD)' in system,
      'system.c: the block chain modules are packed under their IDs')
check('if (sysModeIsNetBlock(mode_str))\n        sprintf(config->g_ps2_ip, "%d.%d.%d.%d", ps2_ip[0], ps2_ip[1], ps2_ip[2], ps2_ip[3]);' in system,
      'system.c: net-block modes hand the EE core the static PS2 IP')
check('!strcmp(mode_str, "BDM_CF_MODE") ?' not in system,
      'system.c: every RA gate goes through sysModeHasNoRATelemetry')

if failures:
    print('Net-block OPL core checks FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('net-block OPL core: picker, launch, CDVDMAN variant, EE reload and module packing all wired')
