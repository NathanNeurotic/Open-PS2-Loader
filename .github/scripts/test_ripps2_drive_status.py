"""Drive Status and DIAG.TXT, ported from RIPPS2 (akilluminati47/RIPPS2, builds 114-115).

1. The hardware log keeps the newest lines when it wraps, never splits the copy, and DIAG.TXT carries a header (version,
   uptime, pad fault runs, Game ID) and then the lines. The launch-time save only runs with Debug on, and never to a
   memory card or an MMCE card.
2. The size, driver and format names the page shows.
3. The wiring: the main menu item, the dialog (hidden unused lines, Save Diagnostics), the BDM free-space devctl in
   the patched driver, and the log lines at the pad, MMCE Game ID, launch, boot and settings-save sites.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]


def read(rel):
    return (root / rel).read_text(encoding='utf-8')


def function(source, signature):
    pos = source.index(signature)
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1]
    raise AssertionError('unterminated ' + signature)


def run(name, code, cwd):
    src = Path(cwd) / (name + '.c')
    exe = Path(cwd) / (name + '.exe')
    src.write_text(code)
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(src), '-o', str(exe)], check=True, cwd=cwd)
    subprocess.run([str(exe)], check=True, cwd=cwd)


# ---- 1. the log ----
diag = read('src/diaglog.c')
body = re.sub(r'#include "include/[a-z]+\.h"\n', '', diag).replace('#include <kernel.h>\n', '')
log_mocks = r'''
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
typedef unsigned int u32;
#define OPL_VERSION "test"
static int intrOn = 1;
static int DIntr(void) { int was = intrOn; intrOn = 0; return was; }
static int EIntr(void) { intrOn = 1; return 1; }
static char cfgDir[64] = "./";
static char *configGetDir(void) { return cfgDir; } /* the settings device only */
static char cfgHome[64] = "./OPL";
static const char *configGetHomePath(void) { return cfgHome; } /* the settings folder */
static void padGetFaultCounters(u32 *a, u32 *b) { *a = 7; *b = 3; }
static int gMMCEEnableGameID = 1, gEnableDebug = 0;
void diagLog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
int diagCopy(char *out, int size, int *wrapped);
int diagSave(const char *dir, char *path, int pathSize);
void diagSaveBeforeLaunch(void);
'''
log_main = r'''
static char buf[DIAG_SIZE + 1];
static int slurp(const char *path, char *out, int size)
{
    FILE *f = fopen(path, "rb");
    int n;
    if (f == NULL)
        return -1;
    n = (int)fread(out, 1, size - 1, f);
    out[n] = '\0';
    fclose(f);
    return n;
}
int main(void)
{
    static char file[DIAG_SIZE * 2];
    char path[128];
    int wrapped = 1, len, i;

    len = diagCopy(buf, sizeof(buf), &wrapped);
    assert(len == 0 && !wrapped);
    diagLog("pad: %u polls in a row could not be read", 5u);
    assert(intrOn); /* interrupts back on after the write */
    intrOn = 0; /* a caller that has them off keeps them off */
    diagLog("nested");
    assert(!intrOn);
    intrOn = 1;
    len = diagCopy(buf, sizeof(buf), &wrapped);
    buf[len] = '\0';
    assert(strstr(buf, "pad: 5 polls in a row could not be read\r\n") && strstr(buf, "nested\r\n") && !wrapped);

    /* past the ring's size: the newest lines stay, in order */
    for (i = 0; i < 2000; i++)
        diagLog("line %04d", i);
    len = diagCopy(buf, sizeof(buf), &wrapped);
    buf[len] = '\0';
    assert(len == DIAG_SIZE && wrapped);
    assert(strstr(buf, "line 1999\r\n") != NULL && strstr(buf, "line 0000") == NULL);
    {
        const char *a = strstr(buf, "line 1500"), *b = strstr(buf, "line 1999");
        assert(a != NULL && b != NULL && a < b);
    }
    /* a smaller copy keeps the newest bytes */
    len = diagCopy(buf, 64, &wrapped);
    buf[len] = '\0';
    assert(len == 64 && wrapped && strstr(buf, "line 1999\r\n") != NULL);

    /* DIAG.TXT: header, then the log */
    /* the default is the settings folder, not its device (CodeRabbit on OPL #1084) */
    assert(diagSave(NULL, path, sizeof(path)) == 1);
    assert(!strcmp(path, "./OPL/DIAG.TXT"));
    assert(slurp(path, file, sizeof(file)) > DIAG_SIZE);
    assert(!strncmp(file, "Open PS2 Loader test diagnostics, ", 34));
    assert(strstr(file, "longest run of missed pad reads: 7 polls; of empty reads: 3 polls\r\n"));
    assert(strstr(file, "MMCE: Game ID on\r\n") && strstr(file, "(the oldest lines have rolled out of the log)"));
    assert(strstr(file, "line 1999\r\n"));
    remove(path);

    /* an unwritable folder: 0, and the path still says where */
    assert(diagSave("./no/such/dir/", path, sizeof(path)) == 0 && !strcmp(path, "./no/such/dir/DIAG.TXT"));

    /* before a launch: Debug off writes nothing; on, never to a card */
    diagSaveBeforeLaunch();
    assert(slurp("./OPL/DIAG.TXT", file, sizeof(file)) < 0);
    gEnableDebug = 1;
    strcpy(cfgDir, "mc0:");
    strcpy(cfgHome, "mc0:OPL");
    diagSaveBeforeLaunch();
    strcpy(cfgDir, "mmce0:");
    strcpy(cfgHome, "mmce0:/OPL/");
    diagSaveBeforeLaunch();
    strcpy(cfgDir, "./");
    strcpy(cfgHome, "./OPL/");
    diagSaveBeforeLaunch();
    assert(slurp("./OPL/DIAG.TXT", file, sizeof(file)) > 0);
    puts("diaglog ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='drive-status-') as temp:
    (Path(temp) / 'OPL').mkdir()
    run('diaglog', log_mocks + body + log_main, temp)
    assert not (Path(temp) / 'mc0:OPL').exists() and not list(Path(temp).glob('mc*DIAG.TXT')) and not list(Path(temp).glob('mmce*'))
print('ok   the hardware log: wrap keeps the newest lines, DIAG.TXT header, launch save only with Debug and never to a card')

# ---- 2. names ----
ds = read('src/drivestatus.c')
helpers = '\n\n'.join(function(ds, s) for s in ('void dsSizeText(', 'const char *dsDriverLabel(', 'const char *dsFsName('))
names_main = r'''
#include <stdio.h>
#include <string.h>
#include <assert.h>
''' + helpers + r'''
int main(void)
{
    char s[24];
    dsSizeText(512, s, sizeof(s));
    assert(!strcmp(s, "512 KB"));
    dsSizeText(8 * 1024, s, sizeof(s));
    assert(!strcmp(s, "8 MB"));
    dsSizeText(1536ULL * 1024, s, sizeof(s));
    assert(!strcmp(s, "1.5 GB"));
    dsSizeText(976762584ULL, s, sizeof(s)); /* a "1 TB" drive */
    assert(!strcmp(s, "931.5 GB"));
    dsSizeText(2ULL * 1024 * 1024 * 1024 + 512ULL * 1024 * 1024, s, sizeof(s));
    assert(!strcmp(s, "2.5 TB"));
    assert(!strcmp(dsDriverLabel("usb"), "USB") && !strcmp(dsDriverLabel("sd"), "iLink") && !strcmp(dsDriverLabel("sdc"), "MX4SIO"));
    assert(!strcmp(dsDriverLabel("udp"), "UDPBD") && dsDriverLabel("ata") == NULL && !strcmp(dsDriverLabel("pccf"), "pccf"));
    assert(!strcmp(dsFsName(4), "exFAT") && !strcmp(dsFsName(3), "FAT32") && !strcmp(dsFsName(2), "FAT16") && !strcmp(dsFsName(1), "FAT12"));
    puts("names ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='drive-status-') as temp:
    run('names', names_main, temp)
print('ok   sizes, drivers and formats by name')

# ---- 3. wiring ----
scan = function(ds, 'static void dsScan(')
assert 'fileXioDopen(root)' in scan and 'bdmReadDriverName(dir, driver, sizeof(driver))' in scan, 'the driver name the safe way'
assert 'BDM_DEVCTL_VOLINFO' in scan and 'hddGetSpace(&total, &freeS)' in scan and 'HDIOC_FREESECTOR, NULL, 0, &freeCount, sizeof(freeCount)' in read('src/hdd.c') and 'mcGetInfo(' in scan and '"mmce%d:/"' in scan
assert 'diaSetVisible(diaDriveStatus, DSTAT_LINE_FIRST + i, i < dsCount)' in scan, 'unused lines hidden'
assert '_l(_STR_DRIVE_STATUS_SETTINGS), configGetHomePath())' in scan, 'the settings folder, not only its device'
mmce = read('src/mmcesupport.c')
assert mmce.count('diagSaveBeforeLaunch();') == 3, 'saved before the Game ID switch and again after its wait, on both cores'
show = function(ds, 'void guiShowDriveStatus(')
assert '== DSTAT_SAVE_DIAG' in show and 'diagSave(NULL, where, sizeof(where))' in show
dialogs = read('src/dialogs.c')
dia = function(dialogs, 'struct UIItem diaDriveStatus[] =')
assert dia.count('DSTAT_LINE_FIRST + ') == 16 and 'DSTAT_SAVE_DIAG' in dia and '_STR_HINT_SAVE_DIAGNOSTICS' in dia
assert 'DSTAT_LINES 16' in read('include/drivestatus.h')
menu = read('src/menusys.c')
assert 'MENU_DRIVE_STATUS, _STR_DRIVE_STATUS' in menu and 'guiShowDriveStatus();' in menu
assert 'diaglog.o drivestatus.o' in read('Makefile')

alloc = read('include/vmc_alloc.h')
assert re.search(r'#define BDM_DEVCTL_VOLINFO\s+0x52500002', alloc), 'the same number RIPPS2 uses'
patch = read('.github/scripts/install_safe_bdmfs.py')
assert "+ BDM_VOLINFO + source[index:]" in patch and 'case BDM_DEVCTL_VOLINFO:' in patch
vol = patch[patch.index("BDM_VOLINFO = '''"):]
assert 'if (vol < 0 || vol > 9 || buf == NULL || buflen < 16)' in vol, 'checked before any use'
assert 'f_getfree(root, &nclst, &vfs)' in vol and 'o[3] = vfs->fs_type;' in vol

assert 'if (gPadNotReadyRun >= 4)' in read('src/pad.c') and 'diagLog("pad: %u polls in a row could not be read"' in read('src/pad.c')
mmce = read('src/mmcesupport.c')
for line in ('diagLog("gameid %s: the card switching after %d ms"', 'diagLog("gameid %s: no switch within %d ms"',
             'diagLog("mmce: the game\'s card ready after %d ms"', 'diagLog("launch: %s (%s) from MMCE, Game ID %s"'):
    assert line in mmce, line
launch = function(mmce, 'void mmceLaunchGame(')
assert launch.index('cacheAbortMmceImageLoadsTimed') < launch.index('diagSaveBeforeLaunch();') < launch.index('deinit('), \
    'saved after the art reads stop and before the drives go down'
system = read('src/system.c')
for line in ('diagLog("launch: Neutrino %s', 'diagLog("launch: POPSTARTER %s, %s"', 'diagLog("launch: Ember %s, game %s"',
             'diagLog("launch: OPL core, %s, %s, logo %d, compat 0x%x"'):
    assert line in system, line
assert 'diagSaveBeforeLaunch' not in system, 'no file writes after the drives are taken down'
opl = read('src/opl.c')
assert 'diagLog("boot: the menu is up; settings from %s", configGetDir());' in opl
assert 'diagLog("settings: not saved to %s, error %d", failedPath, gLastSaveErrno);' in opl
assert 'diagLog("game settings: not saved to %s, error %d"' in menu
print('ok   wiring: main menu, dialog, VOLINFO devctl, log lines at pad, Game ID, launch, boot and save sites')
