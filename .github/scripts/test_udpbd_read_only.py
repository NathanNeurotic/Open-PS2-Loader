#!/usr/bin/env python3
"""Read-only UDPBD/UDPFS IMG servers (belomaxorka / YAOPL 093b541b..760d7e3c, df65546e).

A network block server may keep nothing that is written (udpbd-vexfat, udpbd-server on a read-only image,
PS2-Servers on a folder or with --read-only) and still acknowledge every write. Compiles the real write check
and the "massN:" path test against a fake server: one that keeps writes passes, one that drops them, one whose
sectors still hold an earlier check's data, one that refuses the open and one that refuses the write all fail,
and the test file is always removed. Then checks that every write the menu makes to such a device is skipped
or sent elsewhere, and that the UDPBD driver reports a refused write as done so FatFs keeps reading the disk.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP = (ROOT / 'src/sources').exists()
failures = []


def src(*names):
    for name in names:
        path = ROOT / name
        if path.exists():
            return path.read_text(encoding='utf-8').replace('\r\n', '\n')
    sys.exit('none of %s found' % ', '.join(names))


def function(text, signature, where):
    start = text.find(signature)
    if start < 0:
        sys.exit('%s: %s not found' % (where, signature))
    return text[start:text.index('\n}\n', start) + 3]


DEVICES = src('src/sources/bdmdevices.cpp', 'src/bdmsupport.c')
BDM = src('src/sources/bdmsupport.cpp', 'src/bdmsupport.c')
LAUNCH = src('src/sources/bdmlaunch.cpp', 'src/bdmsupport.c')
SUPPORTBASE = src('src/sources/supportbase.cpp', 'src/supportbase.c')
GUIGAME = src('src/ui/guigame.cpp', 'src/guigame.c')
MENUSYS = src('src/ui/menusys.cpp', 'src/menusys.c')
TRIANGLE = src('src/ui/menuitems.cpp', 'src/opl.c')
APPS = src('src/sources/appsupport.cpp', 'src/appsupport.c')
IOSUPPORT = src('include/iosupport.h')
UDPBD = src('modules/network/smap_udpbd/src/udpbd.c')

flag = re.search(r'^#define MODE_FLAG_READ_ONLY\s+(0x[0-9a-fA-F]+)', IOSUPPORT, re.M)
if flag is None:
    sys.exit('include/iosupport.h: MODE_FLAG_READ_ONLY not defined')
taken = re.findall(r'^#define MODE_FLAG_\w+\s+(0x[0-9a-fA-F]+)', IOSUPPORT, re.M)
if taken.count(flag.group(1)) != 1:
    failures.append('iosupport.h: MODE_FLAG_READ_ONLY shares its bit with another MODE_FLAG')

check = function(DEVICES, 'static int bdmCheckWritable(int unit)\n{', 'bdm write check')
readonly = function(BDM, 'int bdmModeIsReadOnly(int mode)\n{', 'bdmModeIsReadOnly')
path_test = function(BDM, 'int bdmIsReadOnlyPath(const char *path)\n{', 'bdmIsReadOnlyPath')

HARNESS = r'''
#include <fcntl.h>
#include <stdio.h>
#include <string.h>

typedef unsigned int u32;
enum { BDM_MODE = 0, BDM_MODE_LAST = 7, MAX_BDM_DEVICES = 8 };
#define MODE_FLAG_READ_ONLY %(flag)s
typedef struct { unsigned char flags; void *priv; } item_list_t;
static item_list_t bdmDeviceList[MAX_BDM_DEVICES];

/* The fake server: one file. */
enum { KEEP, DROP, NO_OPEN, NO_WRITE };
static int mode, removed, opens;
static unsigned char disk[512], pending[512];
static int pendingLen, writing;
static u32 clock_now = 1000;
static u32 GetTimerSystemTime(void) { return clock_now += 7919; }
static int fake_open(const char *path, int flags, ...)
{
    opens++;
    if (mode == NO_OPEN || strstr(path, "mass2:/") != path)
        return -1;
    writing = (flags & O_WRONLY) != 0;
    pendingLen = 0;
    return 3;
}
static int fake_write(int fd, const void *buf, unsigned len)
{
    if (fd != 3 || !writing || mode == NO_WRITE)
        return -1;
    memcpy(pending, buf, len > 512 ? 512 : len);
    pendingLen = (int)len;
    return (int)len; /* every server here acknowledges the write */
}
static int fake_read(int fd, void *buf, unsigned len)
{
    if (fd != 3 || writing)
        return -1;
    memcpy(buf, disk, len > 512 ? 512 : len);
    return (int)len;
}
static int fake_close(int fd)
{
    if (writing && pendingLen == 512 && mode == KEEP)
        memcpy(disk, pending, 512); /* a dropping server forgets it */
    writing = 0;
    return 0;
}
static int fake_remove(const char *path) { removed++; return 0; }
#define open fake_open
#define write fake_write
#define read fake_read
#define close fake_close
#define remove fake_remove

%(code)s

static int run(int m)
{
    mode = m;
    removed = opens = 0;
    return bdmCheckWritable(2);
}

int main(void)
{
    int bad = 0;
#define EXPECT(cond, what) do { if (!(cond)) { printf("FAIL: %%s\n", what); bad = 1; } } while (0)
    EXPECT(run(KEEP) == 1 && removed == 1, "a server that keeps writes passes and the test file is removed");
    EXPECT(run(KEEP) == 1, "a second check on a writable server passes");
    unsigned char earlier[512];
    memcpy(earlier, disk, 512); /* what the last check left in the sectors */
    EXPECT(run(DROP) == 0 && removed == 1, "a server that drops writes fails, and the test file is removed");
    memcpy(disk, earlier, 512);
    EXPECT(run(DROP) == 0, "a dropping server whose sectors hold an earlier check's data fails (new data every check)");
    memset(disk, 0, sizeof(disk));
    EXPECT(run(DROP) == 0, "a dropping server with empty sectors fails");
    EXPECT(run(NO_OPEN) == 0 && opens == 1, "a server that refuses the open fails");
    EXPECT(run(NO_WRITE) == 0 && removed == 1, "a server that refuses the write fails, and the test file is removed");

    bdmDeviceList[1].flags = MODE_FLAG_READ_ONLY;
    bdmDeviceList[3].flags = 0x02;
    EXPECT(bdmModeIsReadOnly(1) && !bdmModeIsReadOnly(3) && !bdmModeIsReadOnly(0), "the flag is read per slot");
    EXPECT(!bdmModeIsReadOnly(-1) && !bdmModeIsReadOnly(8) && !bdmModeIsReadOnly(20), "a mode that is not a BDM slot is never read-only");
    EXPECT(bdmIsReadOnlyPath("mass1:/APPS/OPL/BOOT.ELF") && bdmIsReadOnlyPath("mass1:OPL/"), "a path on the read-only slot");
    EXPECT(!bdmIsReadOnlyPath("mass0:/APPS/x") && !bdmIsReadOnlyPath("mass3:/x"), "a path on another slot");
    EXPECT(!bdmIsReadOnlyPath("mass11:/x") && !bdmIsReadOnlyPath("mass:/x") && !bdmIsReadOnlyPath("mass1/x"), "a malformed or out-of-range mass path");
    EXPECT(!bdmIsReadOnlyPath("mc0:OPL/") && !bdmIsReadOnlyPath("pfs0:/x") && !bdmIsReadOnlyPath("") && !bdmIsReadOnlyPath(NULL), "not a mass path");
    return bad;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'ro.c'
    c.write_text(HARNESS % {'flag': flag.group(1), 'code': '\n'.join([check, readonly, path_test])}, encoding='utf-8')
    exe = Path(tmp) / 'ro'
    build = subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(c)],
                           capture_output=True, text=True)
    if build.returncode != 0:
        sys.exit('harness does not build:\n' + build.stdout + build.stderr)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    sys.stdout.write(out.stdout)
    if out.returncode != 0:
        failures.append('write check or path test (see above)')


def before(text, first, second, what):
    a, b = text.find(first), text.find(second)
    if not (0 <= a < b):
        failures.append(what)


# The check runs once, when the device connects, after the flags are reset and before the first scan.
connect = DEVICES[DEVICES.index('int bdmUpdateDeviceData(item_list_t *itemList)\n{'):]
connect = connect[:connect.index('\n}\n')]
call = connect.find('if (pDeviceData->bdmDeviceType == BDM_TYPE_UDPBD && !bdmCheckWritable(itemList->mode)) {')
reset = connect.find('itemList->flags = 0;')
visible = connect.find('// Make the menu item visible.')
if not (0 <= reset < call < visible) or 'itemList->flags |= MODE_FLAG_READ_ONLY;' not in connect[call:visible]:
    failures.append('bdmUpdateDeviceData: reset the flags, then check a UDPBD device and set MODE_FLAG_READ_ONLY, '
                    'before the page is shown')

find = function(BDM, 'int bdmFindPartition(char *target, const char *name, int write)\n{', 'bdmFindPartition')
before(find, 'if (write && (bdmDeviceList[i].flags & MODE_FLAG_READ_ONLY))', 'fd = open(path, O_WRONLY | O_CREAT',
       'bdmFindPartition: a read-only device must be skipped before the write probe opens a file on it')

if not re.search(r'if \(!\(itemList->flags & MODE_FLAG_READ_ONLY\)\)\n\s+sbCreateFolders\(pDeviceData->bdmPrefix, 1\);', BDM):
    failures.append('BDM needsUpdate: no sbCreateFolders on a read-only device')
if not re.search(r'sbListCacheReadOnly = \(itemList->flags & MODE_FLAG_READ_ONLY\) != 0;\n\s+sbReadList\([^\n]*\n'
                 r'\s+sbListCacheReadOnly = 0;', BDM):
    failures.append('BDM update: sbListCacheReadOnly must be set around sbReadList and cleared after it')
update_list = function(SUPPORTBASE, 'static int updateISOGameList(', 'updateISOGameList')
before(update_list, 'if (sbListCacheReadOnly)\n        return 0;', 'fopen(', 'updateISOGameList: return before games.bin is written')

# Game settings next to OPL's own; the device's CFG still read once.
populate = function(SUPPORTBASE, 'config_set_t *sbPopulateConfigIn(', 'sbPopulateConfigIn')
if 'return sbPopulateConfigIn(game, prefix, sep, NULL);' not in SUPPORTBASE:
    failures.append('sbPopulateConfig must be sbPopulateConfigIn with no cfgDir')
# C moves the set with configMove(set, name), C++ with set->rename(name).
move_device, move_back = (('config->rename(devicePath)', 'config->rename(path);') if CPP else
                          ('configMove(config, devicePath);', 'configMove(config, path);'))
for step in ('snprintf(path, sizeof(path), "%s%s.cfg", cfgDir, cfgKey);', 'int configLoaded = configRead(config);',
             'if (!configLoaded && cfgDir != NULL) {', move_device, 'configLoaded = configRead(config);', move_back):
    if step not in populate:
        failures.append('sbPopulateConfigIn: missing step ' + step)
before(populate, move_device, move_back,
       'sbPopulateConfigIn: read the device CFG, then point the config back at cfgDir so a save never writes the device')
if not re.search(r'if \(\(itemList->flags & MODE_FLAG_READ_ONLY\) && home != NULL && home\[0\] != \'\\0\' && '
                 r'!bdmIsReadOnlyPath\(home\)\)', BDM) or \
        'sbPopulateConfigIn(game, pDeviceData->bdmPrefix, "/", useCfgDir ? cfgDir : NULL);' not in BDM:
    failures.append('BDM config: a read-only device keeps game settings in <OPL settings home>/CFG/')

# No VMC on a read-only device, on either core.
if not re.search(r'if \(itemList != NULL && \(itemList->flags & MODE_FLAG_READ_ONLY\)\)\n[^\n]*\n\s+else\n'
                 r'\s+sbBuildVmcNeutrinoArgs\(configSet, pDeviceData->bdmPrefix, &neutrinoVmc\);', LAUNCH):
    failures.append('Neutrino launch: no -mc VMC args for a game on a read-only device')
native = re.search(r'configGetVMC\(configSet, vmc_name, sizeof\(vmc_name\), vmc_id\);\n(.*?)\n\s+if \(vmc_name\[0\]\) \{', LAUNCH, re.S)
if native is None or "if (vmc_name[0] && itemList != NULL && (itemList->flags & MODE_FLAG_READ_ONLY))" not in native.group(1) \
        or "vmc_name[0] = '\\0';" not in native.group(1):
    failures.append('OPL-core launch: a VMC named for a game on a read-only device must be dropped before sysCheckVMC')

# Menus.
vmc_menu = function(GUIGAME, 'void guiGameShowVMCMenu(int id, item_list_t *support, config_set_t *configSet)\n{', 'VMC menu')
before(vmc_menu, 'if (bdmModeIsReadOnly(sourceMode)) {\n        guiMsgBox(_l(_STR_NET_READ_ONLY_VMC), 0, NULL);\n        return;',
       '// show dialog', 'guiGameShowVMCMenu: a read-only device shows the message instead of the VMC dialog')
game_menu = function(MENUSYS, 'void menuInitGameMenu(item_list_t *support)\n{', 'game menu')
if 'int readOnly = support != NULL && !fav && (support->flags & MODE_FLAG_READ_ONLY);' not in game_menu or \
        len(re.findall(r'&& !readOnly\)\)\n\s+submenuAppendItem\(&gameMenu, -1, NULL, GAME_(RENAME|DELETE)_GAME', game_menu)) != 2:
    failures.append('menuInitGameMenu: no Rename or Delete for a game on a read-only device')
vcd_menu = function(MENUSYS, 'void menuInitVcdMenu(int isEmber, int readOnly)\n{', 'VCD menu')
if 'if (isEmber && !readOnly)\n' not in vcd_menu or 'if (!readOnly)\n        submenuAppendItem(&appMenu, -1, NULL, APP_RENAME' not in vcd_menu:
    failures.append('menuInitVcdMenu: no Rename or Ember settings for a PS1 row on a read-only device')
if 'menuInitVcdMenu(kind == FAV_KIND_CUE, bdmModeIsReadOnly(sourceMode));' not in TRIANGLE:
    failures.append('Triangle: the PS1 menu must be told whether the row is on a read-only device')
if '!(support->mode == APP_MODE && appIsReadOnly(support, curMenu->current->item.id))' not in TRIANGLE:
    failures.append('Triangle: no Rename/Delete menu for an app on a read-only device')
if not re.search(r'appsList\[id\]\.legacy\) \{\n[^\n]*appGetConfigValue\(id\);\n\s+return cur != NULL && bdmIsReadOnlyPath\(cur->val\);'
                 r'\n\s+\}\n\s+return bdmIsReadOnlyPath\(appsList\[id\]\.path\);', APPS):
    failures.append('appIsReadOnly: a legacy app is read-only by its ELF, any other by its folder')

# The UDPBD driver: a write the server answers with an error counts as done; a timeout does not.
write = function(UDPBD, 'static int udpbd_write(struct block_device *bd, uint64_t sector, const void *buffer, uint16_t count)\n{',
                 'udpbd_write')
tail = write[write.find('if (EFBits & 1) { // done'):]
refused = tail.find('if (g_errno == 0) {')
eio = tail.find('return -EIO;\n}')
if not (0 < refused < eio) or 'return count;' not in tail[refused:eio]:
    failures.append('udpbd_write: an error answer (g_errno 0) must return count before the -EIO of a timeout')
if 'g_errno = 1;' not in UDPBD:
    failures.append('udpbd.c: the timeout no longer sets g_errno, so it would count as done')

# The message, in the base and every overlay.
LABEL = 'NET_READ_ONLY_VMC'
base = src('lng/tmpl/_base.yml', 'lng_tmpl/_base.yml')
if 'label: %s\n' % LABEL not in base:
    failures.append('_base.yml: no %s' % LABEL)
fork = ROOT / ('lng/fork' if CPP else 'lng_fork')
missing = [p.stem for p in sorted(fork.glob('*.yml')) if '\n  %s: ' % LABEL not in p.read_text(encoding='utf-8')]
if missing:
    failures.append('overlays without %s: %s' % (LABEL, ', '.join(missing)))

for line in failures:
    print('FAIL: ' + line)
if failures:
    sys.exit(1)
print('Read-only UDPBD/UDPFS IMG: write check, path test and every menu write guarded')
