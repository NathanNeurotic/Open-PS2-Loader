"""UDPFS Files games boot the OPL core when their own Loader Core says <OPL>.

The menu opens the ISO on udpfs_ioman, keeps it open across the IOP reset and hands cdvdman the server's
handle for it (ioctl2 0x80). After the reset the EE core loads udpfs_smap, udpfs_ministack and udpfs_fhi,
and udpfs_cdvdman reads the disc through udpfs_fhi's "udpfsfhi" exports. A game's VMCs are opened
read-write and kept open the same way; udpfs_mcemu moves their pages through udpfs_cdvdman's
udpfs_vmc_read/udpfs_vmc_write. This checks that wiring in the sources and runs the real in-game reader
and VMC exports (device-udpfs.c) against a stub udpfs_fhi.
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


udpfs = read('src/udpfssupport.c')
system = read('src/system.c')
guigame = read('src/guigame.c')
menusys = read('src/menusys.c')
iopmgr = read('ee_core/src/iopmgr.c')
main_c = read('ee_core/src/main.c')
ee_core_h = read('ee_core/include/ee_core.h')
modmgr = read('ee_core/src/modmgr.c')
extern_irx = read('include/extern_irx.h')
cdvd_config = read('modules/iopcore/common/cdvd_config.h')
internal_h = read('modules/iopcore/cdvdman/internal.h')
cdvdman_make = read('modules/iopcore/cdvdman/Makefile')
ioplib = read('modules/iopcore/cdvdman/ioplib_util.c')
device = read('modules/iopcore/cdvdman/device-udpfs.c')
fhi = read('modules/network/udpfs_fhi/src/udpfs_fhi.c')
fhi_exports = read('modules/network/udpfs_fhi/src/exports.tab')
fhi_main = read('modules/network/udpfs_fhi/src/main.c')
fhi_make = read('modules/network/udpfs_fhi/Makefile')
root_make = read('Makefile')
cdvd_exports = read('modules/iopcore/cdvdman/exports.tab')
mcemu_h = read('modules/mcemu/mcemu.h')
mcemu_utils = read('modules/mcemu/mcemu_utils.h')
mcemu_imports = read('modules/mcemu/imports.lst')
mcemu_make = read('modules/mcemu/Makefile')
mcemu_dev = read('modules/mcemu/device-udpfs.c')
udpfs_h = read('include/udpfssupport.h')

# 1. The launch: Neutrino by default, the OPL core from the game's own <OPL> key or when Neutrino cannot run it.
launch = function(udpfs, 'static void udpfsLaunchGame(item_list_t *itemList, int id, config_set_t *configSet)', 'udpfssupport.c')
check('int coreLoader = bdmNetBlockCoreLoader(configSet);' in launch, 'launch: the core comes from bdmNetBlockCoreLoader')
pick = launch.find('int coreLoader = bdmNetBlockCoreLoader(configSet);')
native = launch.find('udpfsLaunchOplCore(itemList, game, configSet);')
scratch = launch.find('sbPrepare(game, configSet, size_smb_cdvdman_irx, smb_cdvdman_irx, &index)')
check(0 <= pick < native < scratch, 'launch: the core is chosen, and the OPL core leg taken, before the Neutrino leg borrows the SMB IRX')
zso = launch.find('!strcasecmp(game->extension, ".zso")')
check(zso > pick and '_STR_NEUTRINO_BAD_FORMAT' in launch[zso:native] and '_STR_NEUTRINO_NOT_FOUND' in launch[zso:native],
      'launch: a .zso image or a missing neutrino.elf falls back to the OPL core with the usual toast')
check('_STR_NET_NEEDS_NEUTRINO' not in udpfs, 'udpfssupport.c: UDPFS Files is no longer Neutrino-only')
check(0 <= launch.find('GAME_FORMAT_USBLD') < pick, 'launch: a split (UL) game is refused before either core')

leg = function(udpfs, 'static void udpfsLaunchOplCore(', 'udpfssupport.c')
order = ['compatmask = sbPrepare(game, configSet, irx_size, irx, &index);',
         'settings = (struct cdvdman_settings_udpfs *)((u8 *)irx + index);',
         'sbEnsureIgrUsbDrivers(compatmask);',
         'settings->common.mediaLsnCount = sbGetMediaLsnCount(partname, isoBytes);',
         'settings->common.layer1_start = layer1_start;',
         'sbCheatsMissingContinue(&settings->common, result)',
         'sbLoadImage(udpfsPrefix, game->startup);',
         'int iso_file = fileXioOpen(partname, 0x1, 0666);',
         'fileXioIoctl2(iso_file, 0x80, NULL, 0, NULL, 0)',
         'settings->iso_handle = iso_handle;',
         'vmc_files[vmc_id] = fileXioOpen(vmc_path, 0x3, 0666);',
         'sbMcemuSlotWord(&udpfs_mcemu_irx, size_udpfs_mcemu_irx, vmc_id, udpfsMcemuSlots)',
         'mmceSendGameID(game->startup, NULL, vmcMask);',
         'deinit(NO_EXCEPTION, itemList->mode);',
         'settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_DEV9;',
         'settings->common.fakemodule_flags |= FAKE_MODULE_FLAG_SMAP;',
         'sysLaunchLoaderElf(filename, "UDPFS_MODE", irx_size, irx, size_mcemu_irx, udpfs_mcemu_irx, EnablePS2Logo, compatmask);']
at = [leg.find(s) for s in order]
check(all(a >= 0 for a in at) and at == sorted(at),
      'udpfsLaunchOplCore: prepare, size, layer 1, cheats, open the ISO and the VMCs last, keep their handles, tear down, launch UDPFS_MODE '
      '(missing or out of order: %r)' % [s for s, a in zip(order, at) if a < 0])
check('void *irx = &udpfs_cdvdman_irx;' in leg and 'int irx_size = size_udpfs_cdvdman_irx;' in leg,
      'udpfsLaunchOplCore: boots udpfs_cdvdman')
bail = leg[leg.find('if (iso_handle < 0) {'):]
bail = bail[:bail.find('settings->iso_handle')]
check('udpfsCloseFiles(iso_file, vmc_files);' in bail and 'sbUnprepare(&settings->common);' in bail and 'return;' in bail,
      'udpfsLaunchOplCore: an ISO that cannot be opened closes it, restores the patch zone and stays in the menu')
after = leg[leg.find('settings->iso_handle = iso_handle;'):]
vmc_bail = after[after.find('if (vmc_infos[vmc_id].fd < 0) {'):after.find('vmcMask |= 1 << vmc_id;')]
check('fileXioClose(vmc_files[vmc_id]);' in vmc_bail and '_STR_ERR_VMC_CONTINUE' in vmc_bail and
      'udpfsCloseFiles(iso_file, vmc_files);\n                    sbUnprepare(&settings->common);\n                    return;' in vmc_bail,
      'udpfsLaunchOplCore: a VMC the server will not open read-write may be skipped; declining closes everything and stays in the menu')
check(after.count('fileXioClose') == 1 and after.count('udpfsCloseFiles(') == 1,
      'udpfsLaunchOplCore: the ISO and the VMCs stay open across the reset')
pre = leg[:leg.find('compatmask = sbPrepare(')]
check('sysCheckVMC(udpfsPrefix, "/", vmc_name[vmc_id], 0, &vmc_superblock) > 0' in pre and '_STR_ERR_VMC_CONTINUE' in pre,
      'udpfsLaunchOplCore: VMCs are checked before anything is prepared')
check('static int udpfsMcemuSlots[2] = {-2, -2};' in udpfs and 'if (vmc_infos[vmc_id].active)\n                size_mcemu_irx = size_udpfs_mcemu_irx;' in leg,
      'udpfsLaunchOplCore: mcemu goes only with an active card, slots found once')
cleanup = function(udpfs, 'static void udpfsCleanUp(', 'udpfssupport.c')
check('udpfsIomanModLoaded = 0' not in cleanup and 'fileXioUmount' not in cleanup,
      'udpfsCleanUp leaves the udpfs_ioman chain (and the open ISO) alone')

# 2. The menu side resolves the same core everywhere; both cores use the game's VMCs.
check('if (sourceMode == UDPFS_MODE || bdmSupportIsUDPBD(support) || bdmModeIsUDPBD(sourceMode))\n        coreLoader = bdmNetBlockCoreLoader(configSet);' in guigame,
      'guigame.c: the automatic VMC takes the UDPFS Files core from the picker')
check(not re.search(r'UDPFS_MODE && (core)?[lL]oader == 0', guigame),
      'guigame.c: a UDPFS Files game on the OPL core gets its automatic VMC too (udpfs_mcemu)')
check('coreDefaultNeutrino = sourceMode == UDPFS_MODE ||' in guigame, 'compat dialog: UDPFS Files "Default" means Neutrino')
check('} else if (sourceMode == UDPFS_MODE) {' not in guigame, 'compat dialog: the UDPFS Files Loader row is no longer locked')
check('if (sourceMode == UDPFS_MODE || bdmModeIsUDPBD(sourceMode))\n                return bdmNetBlockCoreLoader(itemConfig);' in menusys,
      'gameMenuCoreIsNeutrino: UDPFS Files takes its core from the picker')

# 3. The menu packs the in-game chain and treats the mode as a net-block mode (no second SMAP, no RA, static IP).
check('!strcmp(mode_str, "UDPFS_MODE")' in function(system, 'static int sysModeIsNetBlock(', 'system.c'),
      'system.c: UDPFS_MODE is a net-block mode')
check('else if (!strcmp(mode_str, "UDPFS_MODE"))\n        modules |= CORE_IRX_UDPFS_FILES;' in system,
      'system.c: UDPFS_MODE packs CORE_IRX_UDPFS_FILES')
block = system[system.find('if (modules & CORE_IRX_UDPFS_FILES) {'):]
block = block[:block.find('\n    }\n')]
ids = [block.find('SET_OPL_MOD_ID(OPL_MODULE_ID_%s)' % m) for m in ('UDPFS_SMAP', 'UDPFS_MINISTACK', 'UDPFS_FHI')]
check(all(i >= 0 for i in ids) and ids == sorted(ids) and '&udpfs_fhi_irx' in block and 'udpfs_ioman' not in block,
      'system.c: UDPFS Files packs udpfs_smap, udpfs_ministack and udpfs_fhi (not udpfs_ioman)')

# 4. The EE core parses the mode and loads the chain in order, every module a required transport.
check(re.search(r'BDM_UFS_MODE,[^\n]*\n\s*UDPFS_FILE_MODE,', ee_core_h) is not None, 'ee_core.h: UDPFS_FILE_MODE follows BDM_UFS_MODE')
check('!_strncmp(config->GameModeDesc, "UDPFS_MODE", 10))\n        config->GameMode = UDPFS_FILE_MODE;' in main_c,
      'ee_core main.c: UDPFS_MODE is parsed')
case = iopmgr[iopmgr.find('case BDM_UDP_MODE:'):]
case = case[:case.find('break;') + 6]
check('case UDPFS_FILE_MODE: {' in case and
      'LoadOPLModule(config->GameMode == UDPFS_FILE_MODE ? OPL_MODULE_ID_UDPFS_FHI : OPL_MODULE_ID_UDPFS_BD, 0, 0, NULL);' in case,
      'iopmgr.c: UDPFS Files reloads smap and ministack, then udpfs_fhi in place of udpfs_bd')
check('config->GameMode != UDPFS_FILE_MODE && RA_TelemetryWanted(config)' in iopmgr, 'iopmgr.c: no RA stack beside udpfs_fhi')
check('OPL_MODULE_ID_UDPFS_FHI' in function(modmgr, 'static int IsRequiredTransport(int id)', 'modmgr.c'),
      'modmgr.c: udpfs_fhi is a required transport')

# 5. The IOP side: the cdvdman variant, its settings, the SMAP fake, the module and how both are built.
check(re.search(r'struct cdvdman_settings_udpfs\n\{\n\s*struct cdvdman_settings_common common;\n\s*int iso_handle;\n\} __attribute__\(\(packed\)\);', cdvd_config) is not None,
      'cdvd_config.h: cdvdman_settings_udpfs is the common block plus the ISO handle')
check('#elif UDPFS_DRIVER\n#define CDVDMAN_SETTINGS_TYPE cdvdman_settings_udpfs' in internal_h, 'internal.h: UDPFS_DRIVER selects its settings')
variant = cdvdman_make[cdvdman_make.find('ifeq ($(USE_UDPFS),1)'):]
variant = variant[:variant.find('endif')]
check('IOP_BIN  = udpfs_cdvdman.irx' in variant and '-DUDPFS_DRIVER' in variant and 'device-udpfs.o' in variant and 'USE_DEV9 = 1' in variant,
      'cdvdman Makefile: USE_UDPFS builds device-udpfs with DEV9')
check('#if defined(SMB_DRIVER) || defined(HTTP_DRIVER) || defined(USE_BDM_UDP) || defined(UDPFS_DRIVER)\n    {"SMAP.IRX"' in ioplib,
      'ioplib_util.c: udpfs_cdvdman fakes the game\'s SMAP')
check('-DFEATURE_UDPFS_FHI -DUDPRDMA_MAX_SOCKETS=1' in fhi_make and 'udpfs_fhi.o' in fhi_make and
      '$(IOP_OBJS_DIR)udpfs_core.o: ../udpfs_shared/src/udpfs_core.c' in fhi_make,
      'udpfs_fhi Makefile: the FHI build of the shared transport')
check('IMPORT_BIN2C(udpfs_cdvdman_irx);' in extern_irx and 'IMPORT_BIN2C(udpfs_fhi_irx);' in extern_irx, 'extern_irx.h: both IRX are declared')
check('udpfs_fhi.o' in root_make and 'udpfs_cdvdman.o' in root_make and 'USE_UDPFS=1 -C $< all' in root_make and
      '$(MAKE) -C modules/network/udpfs_fhi clean' in root_make and '$(MAKE) -C modules/iopcore/cdvdman USE_UDPFS=1 clean' in root_make,
      'Makefile: both are built, embedded and cleaned')

# The export indices device-udpfs.c reads are the ones the module declares.
exports = re.findall(r'DECLARE_EXPORT\((\w+)\)', fhi_exports)
check('DECLARE_EXPORT_TABLE(udpfsfhi, 1, 1)' in fhi_exports and exports[4:7] == ['udpfs_fhi_read', 'udpfs_fhi_connected', 'udpfs_fhi_write'],
      'udpfs_fhi exports.tab: library "udpfsfhi", [4] read, [5] connected, [6] write')
check('getModInfo("udpfsfhi", &info)' in device and 'fp_udpfs_fhi_read = (void *)info.exports[4];' in device and
      'fp_udpfs_fhi_connected = (void *)info.exports[5];' in device and 'fp_udpfs_fhi_write = (void *)info.exports[6];' in device,
      'device-udpfs.c: binds [4] to [6] of "udpfsfhi"')
write_fn = function(fhi, 'int udpfs_fhi_write(', 'udpfs_fhi.c')
check('WaitSema(g_sema);' in write_fn and 'udpfs_core_bwrite(handle, (uint64_t)sector, buffer, count, 512)' in write_fn,
      'udpfs_fhi_write: locked 512-byte BWRITE of the caller\'s handle')

# The VMC path: cdvdman exports the page calls at the oplutils ordinals udpfs_mcemu imports.
oplutils = cdvd_exports[cdvd_exports.find('DECLARE_EXPORT_TABLE(oplutils, 1, 2)'):]
oplutils = oplutils[:oplutils.find('END_EXPORT_TABLE')]
check('#ifdef UDPFS_DRIVER\n\tDECLARE_EXPORT(udpfs_vmc_read)' in oplutils and 'DECLARE_EXPORT(udpfs_vmc_write)' in oplutils,
      'cdvdman exports.tab: oplutils [6] udpfs_vmc_read, [7] udpfs_vmc_write under UDPFS_DRIVER')
check('#define I_udpfs_vmc_read DECLARE_IMPORT(6, udpfs_vmc_read)' in mcemu_utils and
      '#define I_udpfs_vmc_write DECLARE_IMPORT(7, udpfs_vmc_write)' in mcemu_utils and
      '#ifdef UDPFS_DRIVER\nI_udpfs_vmc_read\nI_udpfs_vmc_write\n#endif' in mcemu_imports,
      'mcemu: imports udpfs_vmc_read/write at the ordinals cdvdman exports')
check('#if defined(MMCE_DRIVER) || defined(UDPFS_DRIVER)\n    int fd;' in mcemu_h, 'mcemu.h: the UDPFS card carries the server handle as fd')
check(re.search(r'typedef struct\n\{\n\s*int active;[^\n]*\n\s*int fd;[^\n]*\n\s*int flags;[^\n]*\n\s*vmc_spec_t specs;[^\n]*\n\} udpfs_vmc_infos_t;', udpfs_h) is not None,
      'udpfssupport.h: udpfs_vmc_infos_t matches McImageSpec with UDPFS_DRIVER (active, fd, flags, spec)')
check('udpfs_vmc_write(vmc_fd, offset, vmcSpec[mc_num].cspec.PageSize, buf)' in mcemu_dev and
      'udpfs_vmc_read(vmc_fd, offset, vmcSpec[mc_num].cspec.PageSize, buf)' in mcemu_dev, 'mcemu device-udpfs.c: pages go through the UDPFS imports')
variant = mcemu_make[mcemu_make.find('ifeq ($(USE_UDPFS),1)'):]
variant = variant[:variant.find('endif')]
check('IOP_BIN  = udpfs_mcemu.irx' in variant and '-DUDPFS_DRIVER' in variant and 'device-udpfs.o' in variant,
      'mcemu Makefile: USE_UDPFS builds udpfs_mcemu')
check('IMPORT_BIN2C(udpfs_mcemu_irx);' in extern_irx and 'udpfs_mcemu.o' in root_make and
      '$(MAKE) -C modules/mcemu USE_UDPFS=1 clean' in root_make, 'udpfs_mcemu: declared, built, embedded and cleaned')
check(fhi_main.find('udpfs_fhi_init() < 0') < fhi_main.find('RegisterLibraryEntries(&_exp_udpfsfhi)') < fhi_main.find('udpfs_fhi_start();'),
      'udpfs_fhi main.c: create, register, then connect')
start_fn = function(fhi, 'void udpfs_fhi_start(', 'udpfs_fhi.c')
check(0 <= start_fn.find('udpfs_fhi_try_connect();') < start_fn.find('StartThread(g_tid, NULL);'),
      'udpfs_fhi_start: first connect attempt, then the watchdog thread')
cleanup_fn = function(fhi, 'void udpfs_fhi_cleanup(', 'udpfs_fhi.c')
register = fhi_main[fhi_main.find('RegisterLibraryEntries(&_exp_udpfsfhi)'):]
check('DeleteThread(g_tid);' in cleanup_fn and 'DeleteSema(g_sema);' in cleanup_fn and
      0 <= register.find('udpfs_fhi_cleanup();') < register.find('MODULE_NO_RESIDENT_END'),
      'udpfs_fhi main.c: a failed registration frees the semaphore and the watchdog thread')
read_fn = function(fhi, 'int udpfs_fhi_read(', 'udpfs_fhi.c')
check('WaitSema(g_sema);' in read_fn and 'udpfs_core_bread(handle, (uint64_t)sector, buffer, count, 512)' in read_fn,
      'udpfs_fhi_read: locked 512-byte BREAD of the caller\'s handle')
connect = function(fhi, 'static void udpfs_fhi_try_connect(', 'udpfs_fhi.c')
check('WaitSema(g_sema);' in connect and 'udpfs_core_exit' not in fhi, 'udpfs_fhi: discovery under the read lock, socket bound once')

# 6. The in-game reader, compiled against a stub udpfs_fhi.
STUB_INTERNAL = r'''
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64; typedef int32_t s32;
typedef struct { int attr, option, initial, max; } iop_sema_t;
#define SA_THPRI 1
#define SCECdErNO 0
#define SCECdErREAD 0x30
#define SCECdErTRMOPN 0x31
#define SCECdComplete 2
#define DPRINTF(...) do { } while (0)
struct cdvdman_settings_common { int dummy; };
struct cdvdman_settings_udpfs { struct cdvdman_settings_common common; int iso_handle; };
int CreateSema(iop_sema_t *s);
int WaitSema(int s);
int SignalSema(int s);
int DelayThread(int us);
void cdvdman_vmc_io_begin(int is_write);
void cdvdman_vmc_io_end(void);
'''
STUB_IOPLIB = r'''
#pragma once
typedef struct { unsigned short version; void **exports; } modinfo_t;
int getModInfo(char *modname, modinfo_t *info);
'''
STUB_DEVICE = r'''
#pragma once
void DeviceInit(void); void DeviceDeinit(void); int DeviceReady(void); void DeviceFSInit(void);
void DeviceLock(void); void DeviceUnmount(void); void DeviceStop(void);
int DeviceReadSectors(u64 lsn, void *buffer, unsigned int sectors);
int udpfs_vmc_read(int handle, unsigned int offset, unsigned int size, unsigned char *buffer);
int udpfs_vmc_write(int handle, unsigned int offset, unsigned int size, const unsigned char *buffer);
'''
HARNESS = r'''
#include <assert.h>
#include "internal.h"
#include "device.h"
#include "ioplib_util.h"
struct cdvdman_settings_udpfs cdvdman_settings;
static int resident = 1, connected = 1, connect_after = -1, delays, held, calls, fail_next;
static unsigned char disc[64 * 2048];
static unsigned last_sector, last_count; static int last_handle;
static unsigned char vmc[16 * 512]; static int read_only, vmc_busy, vmc_writes;
void cdvdman_vmc_io_begin(int is_write) { assert(!vmc_busy); vmc_busy = 1; vmc_writes += is_write; }
void cdvdman_vmc_io_end(void) { assert(vmc_busy && !held); vmc_busy = 0; }
int CreateSema(iop_sema_t *s) { (void)s; return 1; }
int WaitSema(int s) { (void)s; assert(!held); held = 1; return 0; }
int SignalSema(int s) { (void)s; assert(held); held = 0; return 0; }
int DelayThread(int us) { (void)us; delays++; if (connect_after >= 0 && delays >= connect_after) connected = 1; return 0; }
static int fhi_read(int handle, void *buffer, u32 sector, u32 count)
{
    calls++; last_handle = handle; last_sector = sector; last_count = count;
    assert(((unsigned long)buffer & 3) == 0);           /* the network path writes words */
    if (!connected) return -5;
    if (fail_next > 0) { fail_next--; connected = 0; return -5; }  /* a dropped session */
    if (handle == 7) memcpy(buffer, vmc + sector * 512, count * 512);
    else memcpy(buffer, disc + sector * 512, count * 512);
    return (int)count;
}
static int fhi_connected(void) { return connected; }
static int fhi_write(int handle, const void *buffer, u32 sector, u32 count)
{
    calls++; last_handle = handle; last_sector = sector; last_count = count;
    assert(((unsigned long)buffer & 3) == 0);
    if (!connected) return -5;
    if (fail_next > 0) { fail_next--; connected = 0; return -5; }
    if (read_only) return -13;                                     /* udpfsd: EACCES */
    memcpy(vmc + sector * 512, buffer, count * 512);
    return (int)count;
}
static void *table[7] = {0, 0, 0, 0, (void *)fhi_read, (void *)fhi_connected, (void *)fhi_write};
int getModInfo(char *modname, modinfo_t *info)
{
    assert(memcmp(modname, "udpfsfhi", 8) == 0);
    if (!resident) return 0;
    info->exports = table;
    return 1;
}
int main(void)
{
    static unsigned char out[4 * 2048 + 1] __attribute__((aligned(64)));
    for (unsigned i = 0; i < sizeof(disc); i++) disc[i] = (unsigned char)(i * 7 + i / 2048);
    cdvdman_settings.iso_handle = 42;
    DeviceInit();

    /* udpfs_fhi not resident: reads fail fast and never call through a stale pointer. */
    resident = 0; DeviceFSInit();
    assert(DeviceReadSectors(0, out, 1) == SCECdErREAD && calls == 0);

    /* The server never answers at start: a bounded wait, then fail fast until it is back. */
    resident = 1; connected = 0; delays = 0; DeviceFSInit();
    assert(delays == 300);
    assert(DeviceReadSectors(0, out, 1) == SCECdErREAD && calls == 0);
    connected = 1;
    assert(DeviceReadSectors(3, out, 2) == SCECdErNO);  /* a late server recovers on the next read */
    assert(last_handle == 42 && last_sector == 12 && last_count == 8 && !memcmp(out, disc + 3 * 2048, 2 * 2048));

    /* An unaligned buffer goes sector by sector through the bounce buffer. */
    calls = 0;
    assert(DeviceReadSectors(5, out + 1, 3) == SCECdErNO);
    assert(calls == 3 && last_sector == 7 * 4 && last_count == 4 && !memcmp(out + 1, disc + 5 * 2048, 3 * 2048));

    /* A session that drops mid-read is waited for and the read resumes on the kept handle. */
    calls = 0; delays = 0; fail_next = 1; connect_after = 5;
    assert(DeviceReadSectors(9, out, 4) == SCECdErNO);
    assert(calls == 2 && delays == 5 && !memcmp(out, disc + 9 * 2048, 4 * 2048));

    /* A server that stays away fails the read once the wait runs out, and releases the lock. */
    calls = 0; delays = 0; fail_next = 1; connect_after = -1;
    assert(DeviceReadSectors(1, out, 1) == SCECdErREAD);
    assert(calls == 1 && delays == 300 && !held);

    /* VMC pages: a write lands at its sector of the VMC's own handle and reads back. */
    static unsigned char page[513] __attribute__((aligned(64))), back[512] __attribute__((aligned(64)));
    connected = 1; calls = 0;
    for (int i = 0; i < 512; i++) page[i] = (unsigned char)(i ^ 0x5A);
    assert(udpfs_vmc_write(7, 3 * 512, 512, page) == 1 && last_handle == 7 && last_sector == 3 && last_count == 1);
    assert(!memcmp(vmc + 3 * 512, page, 512) && vmc_writes == 1);
    assert(udpfs_vmc_read(7, 3 * 512, 512, back) == 1 && !memcmp(back, page, 512));
    /* mcemu's page buffer need not be word aligned: it is bounced, both ways. */
    memmove(page + 1, page, 512);
    assert(udpfs_vmc_write(7, 5 * 512, 512, page + 1) == 1 && !memcmp(vmc + 5 * 512, page + 1, 512));
    assert(udpfs_vmc_read(7, 5 * 512, 512, page + 1) == 1 && !memcmp(page + 1, vmc + 5 * 512, 512));
    /* A partial page is refused without touching the server. */
    calls = 0;
    assert(udpfs_vmc_write(7, 100, 512, back) == 0 && udpfs_vmc_read(7, 0, 16, back) == 0 && calls == 0);
    /* A dropped session during a save is waited for and the page written on the kept handle. */
    delays = 0; fail_next = 1; connect_after = 3;
    assert(udpfs_vmc_write(7, 2 * 512, 512, back) == 1 && delays == 3 && !memcmp(vmc + 2 * 512, back, 512));
    /* A read-only share fails the save (mcemu reports it) after its retries, and never hangs. */
    read_only = 1; calls = 0; delays = 0; connect_after = -1;
    assert(udpfs_vmc_write(7, 4 * 512, 512, back) == 0 && calls == 3 && delays == 0 && !held && !vmc_busy);
    /* No server since boot: fail fast. */
    read_only = 0; connected = 0; calls = 0; resident = 1; delays = 0; DeviceFSInit();
    calls = 0; delays = 0;
    assert(udpfs_vmc_read(7, 0, 512, back) == 0 && calls == 0 && delays == 0);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'internal.h').write_text(STUB_INTERNAL, encoding='utf-8')
    (tmp / 'ioplib_util.h').write_text(STUB_IOPLIB, encoding='utf-8')
    (tmp / 'device.h').write_text(STUB_DEVICE, encoding='utf-8')
    (tmp / 'device-udpfs.c').write_text(device, encoding='utf-8')
    (tmp / 'harness.c').write_text(HARNESS, encoding='utf-8')
    exe = tmp / ('harness' + ('.exe' if sys.platform == 'win32' else ''))
    build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-pointer-to-int-cast', '-I', str(tmp),
                            str(tmp / 'device-udpfs.c'), str(tmp / 'harness.c'), '-o', str(exe)], capture_output=True, text=True)
    if build.returncode != 0:
        failures.append('device-udpfs.c harness did not compile:\n' + build.stderr)
    elif subprocess.run([str(exe)]).returncode != 0:
        failures.append('device-udpfs.c: the in-game reader misbehaved against the stub udpfs_fhi')

if failures:
    print('UDPFS Files OPL core checks FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('UDPFS Files OPL core: core picker, launch leg, module packing, EE chain, cdvdman variant and in-game reader OK')
