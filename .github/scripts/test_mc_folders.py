"""Memory-card folders: a Custom Settings Path on a card saves, and POPSTARTER appears only when needed.

Two reports from 10-05. Berion: settings would not save "on mc1" -- a card path such as "mc1:" (or a
folder not yet on the card) could never take the file, because a card only creates "mcN:/FILE" and
nothing made the folder. A user with no interest in POPStarter: RiptOPL put an empty POPSTARTER folder
on the card that the browser shows as Corrupted Data -- merely READING the BDMA setting created it.

Compiles the real normalizeMcPath / createMcSettingsFolder (src/opl.c) and the real POPSTARTER folder
code (src/vcdsupport.c: find, resolve, icon stamp, BDMA mode read, environment check, the PS1 launch
install) against an in-memory memory card that, like a real one, makes one folder level at a time,
then checks the wiring of every flow that creates a folder.
"""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        sys.exit('missing ' + signature)
    return source[match.start():source.index('\n}', match.start()) + 2]


def block(source, pattern):
    match = re.search(pattern, source, re.M | re.S)
    if match is None:
        sys.exit('missing ' + pattern)
    return match.group(0)


opl = text('src/opl.c')
vcd = text('src/vcdsupport.c')
icon_sys = (root / 'misc/icon.sys').read_bytes()

pieces = '\n\n'.join([
    function(opl, 'static void normalizeMcPath('),
    function(opl, 'static int createMcSettingsFolder('),
    function(opl, 'static void resolveMcWildcardBootDir('),
    function(opl, 'static void normalizeMcBootDir('),
    function(opl, 'static int bootHomeIsConcreteMc('),
    function(opl, 'static int bootHomeIsMcRoot('),
    block(vcd, r'^static const char \*vcdBdmaSuffix\[VCD_BDMA_MODE_COUNT\] = \{[^;]*\};'),
    block(vcd, r'^static const char \*vcdBdmaModule\[2\] = \{[^;]*\};'),
    block(vcd, r'^#define VCD_BDMA_MARKER .*?$'),
    block(vcd, r'^#define VCD_ICON_SYS_TITLE .*?$'),
    block(vcd, r'^#define VCD_ICON_SYS_NAMES .*?$'),
    block(vcd, r'^static const char \*vcdPopsIconFile\[3\] = \{[^;]*\};'),
    function(vcd, 'static void vcdStampPopstarterIcons('),
    function(vcd, 'static int vcdFindPopstarterMc('),
    function(vcd, 'static int vcdResolvePopstarterMc('),
    function(vcd, 'int vcdReadBdmaMode('),
    block(vcd, r'^typedef struct\s*\{\s*int usbdSize;\s*int hdfsdSize;\s*\} bdma_pair_sig_t;'),
    block(vcd, r'^static const bdma_pair_sig_t vcdBdmaPairSig\[VCD_BDMA_MODE_COUNT\] = \{.*?\};'),
    function(vcd, 'static int vcdGetFileSize('),
    function(vcd, 'int vcdBdmaEnvironmentValid('),
    '#define POPS_FOLDER "POPS"',
    function(vcd, 'static char vcdSep('),
    block(vcd, r'^static const char \*vcdPopstarterMcFile\[9\] = \{[^;]*\};'),
    function(vcd, 'static int vcdInstallPopstarterMcAt('),
    function(vcd, 'static int vcdPopstarterModulesAt('),
    function(vcd, 'int vcdInstallPopstarterMc('),
])

HARNESS = r'''
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LOG(...) ((void)0)
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 0x200
#define O_TRUNC 0x400
#define SEEK_SET 0
#define SEEK_END 2
enum { VCD_BDMA_FAT32 = 0, VCD_BDMA_USBEXFAT, VCD_BDMA_MX4SIO, VCD_BDMA_MMCE, VCD_BDMA_ATA, VCD_BDMA_ILINK, VCD_BDMA_MODE_COUNT };
static char gCustomSettingsPath[64];
static char gBootDir[256], gBootElfName[64];
static volatile int gLastSaveErrno;

/* An in-memory card: folders and files by full path. */
static char dirs[64][96];
static int ndirs, mkdirs, mkdirFails;
static struct { char path[96]; unsigned char data[2048]; int len; int used; } files[64];
#define DIR fake_DIR
#define opendir fake_opendir
#define closedir fake_closedir
#define mkdir fake_mkdir
#define open fake_open
#define read fake_read
#define lseek fake_lseek
#define close fake_close
#define unlink fake_unlink
typedef struct { int unused; } DIR;
static DIR theDir;
static int isDir(const char *p) { for (int i = 0; i < ndirs; i++) if (!strcmp(dirs[i], p)) return 1; return 0; }
static DIR *opendir(const char *p) { return isDir(p) ? &theDir : NULL; }
static int closedir(DIR *d) { (void)d; return 0; }
static int mkdir(const char *p, int mode)
{
    char parent[96]; const char *sl = strrchr(p, '/');
    (void)mode; mkdirs++;
    if (mkdirFails) { errno = EIO; return -1; }
    snprintf(parent, sizeof(parent), "%.*s", sl ? (int)(sl - p) : 0, p);
    if (sl && sl - p > 4 && !isDir(parent)) { errno = ENOENT; return -1; }   /* like a card: one level at a time */
    if (!isDir(p)) snprintf(dirs[ndirs++], 96, "%s", p);
    return 0;
}
static int findFile(const char *p) { for (int i = 0; i < 64; i++) if (files[i].used && !strcmp(files[i].path, p)) return i; return -1; }
static int putFile(const char *p, const void *d, int len)
{
    char parent[96]; const char *sl = strrchr(p, '/');
    snprintf(parent, sizeof(parent), "%.*s", sl ? (int)(sl - p) : 0, p);
    if (sl && strlen(parent) > 5 && !isDir(parent)) return -1;   /* a card file needs its folder */
    int i = findFile(p);
    if (i < 0) for (i = 0; i < 64 && files[i].used; i++) ;
    if (i >= 64 || len > 2048) return -1;
    snprintf(files[i].path, 96, "%s", p); memcpy(files[i].data, d, len); files[i].len = len; files[i].used = 1;
    return 0;
}
static int fds[16], fdPos[16];
static int open(const char *p, int flags, ...)
{
    int i = findFile(p);
    if (i < 0) { errno = ENOENT; return -1; }
    (void)flags;
    for (int f = 3; f < 16; f++) if (!fds[f]) { fds[f] = i + 1; fdPos[f] = 0; return f; }
    return -1;
}
static int read(int fd, void *buf, int n) { int i = fds[fd] - 1; int left = files[i].len - fdPos[fd]; if (n > left) n = left; memcpy(buf, files[i].data + fdPos[fd], n); fdPos[fd] += n; return n; }
static int lseek(int fd, int off, int whence) { int i = fds[fd] - 1; fdPos[fd] = whence == SEEK_END ? files[i].len + off : off; return fdPos[fd]; }
static int close(int fd) { fds[fd] = 0; return 0; }
static int unlink(const char *p) { int i = findFile(p); if (i >= 0) files[i].used = 0; return 0; }
static int vcdSafeCopyFile(const char *src, const char *dst) { int i = findFile(src); if (i < 0) return -1; return putFile(dst, files[i].data, files[i].len) == 0 ? 0 : -3; }
static int vcdSafeWriteFile(const char *dst, const void *buf, int len) { return putFile(dst, buf, len) == 0 ? 0 : -3; }

unsigned char icon_sys[] = {@ICON_SYS@};
unsigned int size_icon_sys = sizeof(icon_sys);
unsigned char save_icn[] = {1, 2, 3, 4, 5, 6, 7, 8};
unsigned int size_save_icn = sizeof(save_icn);

@PIECES@

static void reset(void) { ndirs = mkdirs = mkdirFails = 0; memset(files, 0, sizeof(files)); snprintf(dirs[ndirs++], 96, "mc0:/"); snprintf(dirs[ndirs++], 96, "mc1:/"); }
static void hexfile(const char *label, const char *p) { int i = findFile(p); printf("%s:", label); if (i < 0) { printf(" none\n"); return; } for (int k = 0; k < files[i].len; k++) printf("%02x", files[i].data[k]); printf("\n"); }

int main(void)
{
    char path[64], out[64];
    const char *inputs[] = {"mc1:", "mc1:OPL", "mc1:/OPL", "mc0:APPS/X", "mmce0:", "mc?:OPL", "mass0:/OPL", NULL};
    for (int i = 0; inputs[i]; i++) { snprintf(path, sizeof(path), "%s", inputs[i]); normalizeMcPath(path, sizeof(path)); printf("norm %s -> %s\n", inputs[i], path); }

    int r, a, b, c, d; /* every call made before its counters are printed: argument order is unspecified */
    reset(); r = createMcSettingsFolder("mc1:/"); printf("folder root r=%d mkdirs=%d\n", r, mkdirs);
    reset(); r = createMcSettingsFolder("mc1:/OPL/"); printf("folder new r=%d mkdirs=%d exists=%d\n", r, mkdirs, isDir("mc1:/OPL"));
    reset(); createMcSettingsFolder("mc1:/OPL"); mkdirs = 0; r = createMcSettingsFolder("mc1:/OPL"); printf("folder again r=%d mkdirs=%d\n", r, mkdirs);
    reset(); mkdirFails = 1; gLastSaveErrno = 0; r = createMcSettingsFolder("mc1:/OPL"); printf("folder fail r=%d errno=%d\n", r, gLastSaveErrno == EIO);
    reset(); r = createMcSettingsFolder("mass0:/OPL"); printf("folder notcard r=%d mkdirs=%d\n", r, mkdirs);
    reset(); r = createMcSettingsFolder("mc1:/APPS/OPL/"); a = isDir("mc1:/APPS"); b = isDir("mc1:/APPS/OPL");
    printf("folder nested r=%d mkdirs=%d exists=%d,%d\n", r, mkdirs, a, b);
    reset(); snprintf(dirs[ndirs++], 96, "mc1:/APPS"); r = createMcSettingsFolder("mc1:/APPS/OPL"); printf("folder under r=%d mkdirs=%d\n", r, mkdirs);

    /* POPSTARTER: reading never makes the folder. */
    reset();
    a = vcdReadBdmaMode(); b = vcdFindPopstarterMc(out, sizeof(out));
    c = vcdBdmaEnvironmentValid(VCD_BDMA_FAT32); d = vcdBdmaEnvironmentValid(VCD_BDMA_USBEXFAT);
    printf("read mode=%d found=%d valid fat32=%d valid usbexfat=%d mkdirs=%d\n", a, b, c, d, mkdirs);
    /* Resolving for a write makes it once, on the first present card. */
    r = vcdResolvePopstarterMc(out, sizeof(out)); printf("resolve r=%d dir=%s mkdirs=%d\n", r, out, mkdirs);
    r = vcdResolvePopstarterMc(out, sizeof(out)); printf("resolve again r=%d mkdirs=%d\n", r, mkdirs);

    /* Icons: POPStarter's own set from a source folder... */
    reset(); snprintf(dirs[ndirs++], 96, "mass0:/POPS");
    putFile("mass0:/POPS/icon.sys", "SYS", 3); putFile("mass0:/POPS/list.icn", "LST", 3); putFile("mass0:/POPS/del.icn", "DEL", 3);
    vcdResolvePopstarterMc(out, sizeof(out));
    vcdStampPopstarterIcons(out, "mass0:/POPS/");
    hexfile("own icon.sys", "mc0:/POPSTARTER/icon.sys"); hexfile("own del.icn", "mc0:/POPSTARTER/del.icn");
    /* ...an existing icon.sys is never replaced... */
    vcdStampPopstarterIcons(out, NULL);
    hexfile("kept icon.sys", "mc0:/POPSTARTER/icon.sys");
    /* ...and with no source set, RiptOPL's icon retitled POPSTARTER, one list.icn for all three views. */
    reset(); vcdResolvePopstarterMc(out, sizeof(out)); vcdStampPopstarterIcons(out, "mass0:/POPS/");
    hexfile("fallback list.icn", "mc0:/POPSTARTER/list.icn"); hexfile("fallback icon.sys", "mc0:/POPSTARTER/icon.sys");

    /* The PS1 launch install: a POPS/ folder with only icons needs nothing on the card... */
    reset(); snprintf(dirs[ndirs++], 96, "mass0:/POPS"); putFile("mass0:/POPS/list.icn", "LST", 3);
    r = vcdInstallPopstarterMc("mass0:/"); a = vcdFindPopstarterMc(out, sizeof(out));
    printf("install iconsonly r=%d mkdirs=%d found=%d\n", r, mkdirs, a);
    /* ...one with a module gets the folder, the module and icons... */
    reset(); snprintf(dirs[ndirs++], 96, "mass0:/POPS"); putFile("mass0:/POPS/smbman.irx", "SMB", 3);
    r = vcdInstallPopstarterMc("mass0:/");
    a = findFile("mc0:/POPSTARTER/smbman.irx") >= 0; b = findFile("mc0:/POPSTARTER/icon.sys") >= 0; c = findFile("mc0:/POPSTARTER/list.icn") >= 0;
    printf("install modules mkdirs=%d smbman=%d icon=%d list=%d\n", mkdirs, a, b, c);
    /* ...and a folder already there without icons (an older build's) gets them on the next launch. */
    reset(); vcdResolvePopstarterMc(out, sizeof(out)); mkdirs = 0;
    r = vcdInstallPopstarterMc("mass0:/"); a = findFile("mc0:/POPSTARTER/icon.sys") >= 0;
    printf("install existing mkdirs=%d icon=%d\n", mkdirs, a);

    /* A launcher's mc?: wildcard boot dir becomes the card that holds the booted ELF. */
    struct { const char *dir, *elf; int on0, on1; } boots[] = {
        {"mc?:/APP_RIPTOPL", "RIPTOPL.ELF", 0, 1}, {"mc?:/APP_RIPTOPL", "RIPTOPL.ELF", 1, 1},
        {"mc?:/APP_RIPTOPL", "RIPTOPL.ELF", 0, 0}, {"mc?:APP_RIPTOPL", "RIPTOPL.ELF", 0, 1},
        {"mc?:/APP_RIPTOPL", "", 0, 1}, {"mc1:APP_RIPTOPL", "RIPTOPL.ELF", 1, 0}, {"mc?:", "RIPTOPL.ELF", 0, 1},
        {NULL, NULL, 0, 0}};
    for (int i = 0; boots[i].dir; i++) {
        reset();
        for (int s = 0; s < 2; s++) {
            if (!(s ? boots[i].on1 : boots[i].on0))
                continue;
            char d[32], f[64];
            snprintf(d, sizeof(d), "mc%d:/APP_RIPTOPL", s);
            snprintf(dirs[ndirs++], 96, "%s", d);
            snprintf(f, sizeof(f), "%s/RIPTOPL.ELF", d);
            putFile(f, "ELF", 3);
            snprintf(f, sizeof(f), "mc%d:/RIPTOPL.ELF", s);
            putFile(f, "ELF", 3);
        }
        snprintf(gBootDir, sizeof(gBootDir), "%s", boots[i].dir);
        snprintf(gBootElfName, sizeof(gBootElfName), "%s", boots[i].elf);
        normalizeMcBootDir();
        printf("boot %s [%s] mc0=%d mc1=%d -> %s\n", boots[i].dir, boots[i].elf, boots[i].on0, boots[i].on1, gBootDir);
    }

    /* Only a bare card boot dir keeps a recovered same-card folder as its save home. */
    const char *roots[] = {"mc1:", "mc1:/", "mc1:/APP_RIPTOPL", "mc0:/", "mc?:", "mass0:/", NULL};
    printf("root:");
    for (int i = 0; roots[i]; i++) {
        snprintf(gBootDir, sizeof(gBootDir), "%s", roots[i]);
        printf(" %d", bootHomeIsMcRoot());
    }
    printf("\n");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'mc.c'
    exe = Path(tmp) / 'mc'
    src.write_text(HARNESS.replace('@PIECES@', pieces).replace('@ICON_SYS@', ', '.join(str(b) for b in icon_sys)), encoding='utf-8')
    build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                           capture_output=True, text=True, check=False)
    if build.returncode != 0:
        sys.exit('harness did not compile:\n' + build.stderr)
    got = dict(line.split(':', 1) if ':' in line and not line.startswith(('norm', 'folder', 'read', 'resolve', 'boot', 'root')) else (line, '')
               for line in subprocess.run([str(exe)], capture_output=True, text=True, check=False).stdout.splitlines())

lines = list(got)
want_head = ['norm mc1: -> mc1:/', 'norm mc1:OPL -> mc1:/OPL', 'norm mc1:/OPL -> mc1:/OPL', 'norm mc0:APPS/X -> mc0:/APPS/X',
             'norm mmce0: -> mmce0:', 'norm mc?:OPL -> mc?:OPL', 'norm mass0:/OPL -> mass0:/OPL',
             'folder root r=0 mkdirs=0', 'folder new r=0 mkdirs=1 exists=1', 'folder again r=0 mkdirs=0', 'folder fail r=-1 errno=1',
             'folder notcard r=0 mkdirs=0', 'folder nested r=0 mkdirs=2 exists=1,1', 'folder under r=0 mkdirs=1',
             'read mode=0 found=0 valid fat32=1 valid usbexfat=0 mkdirs=0',
             'resolve r=1 dir=mc0:/POPSTARTER mkdirs=1', 'resolve again r=1 mkdirs=1']
if lines[:len(want_head)] != want_head:
    failures.append('settings path / POPSTARTER folder:\n  got  %r\n  want %r' % (lines[:len(want_head)], want_head))
if got.get('own icon.sys', '').strip() != b'SYS'.hex() or got.get('own del.icn', '').strip() != b'DEL'.hex():
    failures.append("POPStarter's own icon set must be copied from the source POPS/ folder")
if got.get('kept icon.sys', '').strip() != b'SYS'.hex():
    failures.append('an icon.sys already in the folder must never be replaced')
if got.get('fallback list.icn', '').strip() != bytes(range(1, 9)).hex():
    failures.append('the fallback must write RiptOPL\'s list.icn')
else:
    fallback = bytes.fromhex(got.get('fallback icon.sys', '').strip() or '00')
    if len(fallback) != len(icon_sys):
        failures.append('the fallback icon.sys must be the full built-in one')
    else:
        title = fallback[0xC0:0xC0 + 68].split(b'\0\0')[0].decode('shift_jis')
        names = [fallback[o:o + 64].split(b'\0')[0] for o in (0x104, 0x144, 0x184)]
        if title != 'ＰＯＰＳＴＡＲＴＥＲ' or struct.unpack_from('<H', fallback, 6)[0] != 20 or names != [b'list.icn'] * 3:
            failures.append('fallback icon.sys: title %r, break %d, names %r' % (title, struct.unpack_from('<H', fallback, 6)[0], names))
        if fallback[:0xC0] [8:] != icon_sys[:0xC0][8:] or fallback[0x1C4:] != icon_sys[0x1C4:]:
            failures.append('the fallback may only change the title, its break and the three names')
for line, why in (('boot mc?:/APP_RIPTOPL [RIPTOPL.ELF] mc0=0 mc1=1 -> mc1:/APP_RIPTOPL', 'an mc?: boot must take the card that holds the ELF'),
                  ('boot mc?:/APP_RIPTOPL [RIPTOPL.ELF] mc0=1 mc1=1 -> mc0:/APP_RIPTOPL', 'with the ELF on both cards, mc0 as before'),
                  ('boot mc?:/APP_RIPTOPL [RIPTOPL.ELF] mc0=0 mc1=0 -> mc?:/APP_RIPTOPL', 'with neither card answering, nothing changes'),
                  ('boot mc?:APP_RIPTOPL [RIPTOPL.ELF] mc0=0 mc1=1 -> mc1:/APP_RIPTOPL', 'a compact mc?:FOLDER resolves and gains its slash'),
                  ('boot mc?:/APP_RIPTOPL [] mc0=0 mc1=1 -> mc1:/APP_RIPTOPL', 'without an ELF name the boot folder decides'),
                  ('boot mc1:APP_RIPTOPL [RIPTOPL.ELF] mc0=1 mc1=0 -> mc1:/APP_RIPTOPL', 'a concrete slot is never second-guessed'),
                  ('boot mc?: [RIPTOPL.ELF] mc0=0 mc1=1 -> mc1:/', 'an ELF in a card root resolves to that root'),
                  ('root: 1 1 0 1 0 0', 'only a bare mcN: boot dir is the card root')):
    if line not in got:
        failures.append('memory-card boot dir: %s (output %r)' % (why, [l for l in lines if l.startswith(('boot', 'root'))]))
for line, why in (('install iconsonly r=0 mkdirs=0 found=0', 'a POPS/ folder with no modules must not put a folder on the card'),
                  ('install modules mkdirs=1 smbman=1 icon=1 list=1', 'a POPS/ folder with modules gets the card folder, the modules and icons'),
                  ('install existing mkdirs=0 icon=1', 'an existing folder without icons must get them on the next launch')):
    if line not in got:
        failures.append('PS1 launch install: %s (output %r)' % (why, [l for l in lines if l.startswith('install')]))

# ---- the wiring --------------------------------------------------------------------------------

save = function(opl, 'static void _saveConfig(')
custom = save[save.index('if (gCustomSettingsPath[0] != \'\\0\') {'):]
made = custom.find('if (createMcSettingsFolder(customSettingsTarget) < 0) {')
moved = custom.find('configSetMove(customSettingsTarget);\n            customSettingsExplicit = 1;', made)
if made < 0 or moved < 0 or 'return;' not in custom[made:moved]:
    failures.append('opl.c _saveConfig: a card Custom Settings Path needs its folder (or a reported failure) before the save moves there')
prepare = function(opl, 'static int prepareCustomSettingsPath(')
if not (0 <= prepare.find('normalizeMcPath(path, (size_t)pathLen);') < prepare.find('isApaSettingsPath(path)')):
    failures.append('opl.c prepareCustomSettingsPath: card paths must be normalized for both the save and the boot-time read')
if 'createMcSettingsFolder' in prepare:
    failures.append('opl.c prepareCustomSettingsPath: the boot-time read must never create a folder')
boot_norm = function(opl, 'static void normalizeMcBootDir(')
if not (0 <= boot_norm.find('resolveMcWildcardBootDir();') < boot_norm.find('normalizeMcPath(gBootDir, sizeof(gBootDir));')):
    failures.append('opl.c normalizeMcBootDir must resolve an mc?: boot dir, then share normalizeMcPath')
restore = function(opl, 'static void restoreRecoverySaveHome(')
if 'sameConcreteMcSlot(gBootDir, recoveredHome) && !configOplIsOfficialSeed() && bootHomeIsMcRoot()' not in restore:
    failures.append('opl.c restoreRecoverySaveHome: only a bare mcN: boot may keep a recovered folder; others save beside the ELF')

mkdirs = re.findall(r'^static [^\n]*?(\w+)\([^)]*\)\n\{(?:(?!\n\}).)*?mkdir\(', vcd, re.M | re.S)
if sorted(mkdirs) != ['vcdEnsurePopstarterNetDir', 'vcdResolvePopstarterMc']:
    failures.append('vcdsupport.c: only the two creating resolvers may mkdir (found %r)' % mkdirs)
for reader in ('int vcdReadBdmaMode(', 'int vcdBdmaEnvironmentValid(', 'static int vcdBdmaManualPairMatches('):
    body = function(vcd, reader)
    if 'vcdResolvePopstarterMc(' in body or 'vcdFindPopstarterMc(' not in body:
        failures.append('vcdsupport.c %s: a read must find the folder, never create it' % reader)
equip = function(vcd, 'int vcdEquipBdma(')
first_find, not_found = equip.find('vcdFindPopstarterMc(mcDir, sizeof(mcDir))'), equip.find('return -4;')
create, stamp, stage = (equip.find('vcdResolvePopstarterMc(mcDir, sizeof(mcDir))'), equip.find('vcdStampPopstarterIcons(mcDir, srcDir);'),
                        equip.find('vcdSafeCopyFile(src0, tmp0)'))
if not (0 <= first_find < not_found < create < stamp < stage):
    failures.append('vcdsupport.c vcdEquipBdma: make the folder only once a pair was found, and give it icons before the pair')
if not re.search(r'if \(mode == VCD_BDMA_FAT32\) \{(?:(?!\n    \}).)*?if \(!haveDir\)\s*return 0;', equip, re.S):
    failures.append('vcdsupport.c vcdEquipBdma: FAT32 needs no folder -- with none there, nothing to do')
install = function(vcd, 'int vcdInstallPopstarterMc(')
if not (0 <= install.find('vcdFindPopstarterMc(mcDir, sizeof(mcDir))') < install.find('if (!vcdPopstarterModulesAt(devPrefix))') <
        install.find('vcdResolvePopstarterMc(mcDir, sizeof(mcDir))') < install.find('vcdInstallPopstarterMcAt(devPrefix, mcDir)') <
        install.find('vcdStampPopstarterIcons(mcDir, NULL);')):
    failures.append('vcdsupport.c vcdInstallPopstarterMc: make the folder only for modules to install, and end with icons')
smb = function(vcd, 'vcd_popsnet_ensure_t vcdPreparePopstarterSmbLaunch(')
if not (0 <= smb.find('else if (errno == ENOENT && !vcdPopstarterModulesAt(smbPrefix))\n        return VCD_POPSNET_SMB_MISSING;') <
        smb.find('vcdEnsurePopstarterNetDir(cfg.home)') < smb.find('vcdInstallPopstarterMcAt(smbPrefix, cfg.home)') <
        smb.find('vcdStampPopstarterIcons(cfg.home, NULL);')):
    failures.append('vcdsupport.c vcdPreparePopstarterSmbLaunch: no folder when the share has no modules for it; icons on the one it makes')
net = function(vcd, 'int vcdWritePopstarterNetFiles(')
if not (0 <= net.find('vcdEnsurePopstarterNetDir(dir)') < net.find('vcdStampPopstarterIcons(dir, NULL);') < net.find('vcdSafeWriteFile(')):
    failures.append('vcdsupport.c vcdWritePopstarterNetFiles: the folder it makes must get icons before the config files')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('memory-card folders: card settings paths save; POPSTARTER only when needed, always with icons')
