"""A missing ember.elf must not hide the Ember games -- and must never fail the PS1 scan.

Aislinn (October 2026) asked for a useful error when a PS1 prerequisite is missing. The silent case
was the scan: cueScanDir returned 0 as soon as ember.elf would not open, so a missing or misnamed core
made every Ember game vanish with no message anywhere. The games now still list, and launching one
names the missing file.

What must NOT change is the FifthFox iLink guarantee the core check was added for: on a device whose
driver does not report ENOENT (mmceman collapses every failure into a bare -1), a device with a POPS
library and no EMBER folder must read as "nothing here" (0), never as an unreadable device (-1) --
-1 makes ps1FillGameList keep the whole last-good PS1 list, POPSTARTER rows included.

This compiles cueScanDir and its helpers from src/cuesupport.c against a fake filesystem and checks
both rules, plus that every launch leg names the path it looked for.
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


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


def defines(source, where, names):
    out = []
    for name in names:
        match = re.search(r'^#define ' + name + r'\s+(\S+)', source, re.M)
        if match is None:
            failures.append('%s: #define %s not found' % (where, name))
            continue
        out.append('#define %s %s' % (name, match.group(1)))
    return '\n'.join(out) + '\n'


cue = read('src/cuesupport.c')
header = read('include/cuesupport.h')
supportbase = read('include/supportbase.h')

constants = defines(header, 'include/cuesupport.h', (
    'CUE_NAME_MAX', 'CUE_NAME_LAUNCH_MAX', 'CUE_MAX_ITEMS',
    'EMBER_FOLDER_DEFAULT', 'EMBER_ELF_NAME', 'EMBER_GAMES_FOLDER'))
constants += defines(supportbase, 'include/supportbase.h', ('ISO_GAME_NAME_MAX',))

entry = re.search(r'^typedef struct\s*\{[^}]*\} cue_entry_t;', header, re.M)
if entry is None:
    failures.append('include/cuesupport.h: cue_entry_t not found')

functions = ''.join(function_text(cue, 'src/cuesupport.c', sig) for sig in (
    'static char cueSep(',
    'const char *cueEmberFolder(',
    'static int cueResolveEmberFile(',
    'int cueResolveEmber(',
    'void cueBuildGamesDir(',
    'int cueNameLaunchable(',
    'static int cueEntryIsDir(',
    'int cueScanDir(',
))

# Every launch leg must name the file it looked for, not just say "Missing ember.elf" -- and with the
# buffer that holds THAT file's path (CodeRabbit, #836: rejecting the old calls alone would also pass a
# leg that dropped its dialog or passed the wrong buffer).
EXPECTED = {
    'src/bdmsupport.c': ['guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), emberElf)',
                         'guiMsgBoxMissing(_l(_STR_EMBER_BIOS_MISSING), biosPath)',
                         'vcdDescribePopstarterLookup(vcdPrefix, vcdElf, sizeof(vcdElf))',
                         'guiMsgBoxMissing(_l(_STR_POPSTARTER_NOT_FOUND), vcdElf)'],
    'src/ethsupport.c': ['guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), emberElf)',
                         'guiMsgBoxMissing(_l(_STR_EMBER_BIOS_MISSING), biosPath)',
                         'vcdDescribePopstarterLookup(ethPrefix, vcdElf, sizeof(vcdElf))',
                         'guiMsgBoxMissing(_l(_STR_POPSTARTER_NOT_FOUND), vcdElf)'],
    'src/mmcesupport.c': ['guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), emberElf)',
                          'guiMsgBoxMissing(_l(_STR_EMBER_BIOS_MISSING), biosPath)',
                          'vcdDescribePopstarterLookup(ps1Root, vcdElf, sizeof(vcdElf))',
                          'guiMsgBoxMissing(_l(_STR_POPSTARTER_NOT_FOUND), vcdElf)'],
    'src/udpfssupport.c': ['guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), emberElf)',
                           'guiMsgBoxMissing(_l(_STR_EMBER_BIOS_MISSING), biosPath)'],
    'src/hddsupport.c': ['hddShowEmberMissing(_STR_EMBER_NOT_FOUND, mountSrc, emberElf)',
                         'hddShowEmberMissing(_STR_EMBER_BIOS_MISSING, mountSrc, biosPath)',
                         'guiMsgBoxMissing(_l(_STR_ERR_FILE_INVALID), mountSrc)',
                         'vcdDescribePopstarterLookup("hdd0:__common/", vcdElf, sizeof(vcdElf))',
                         'guiMsgBoxMissing(_l(_STR_POPSTARTER_NOT_FOUND), vcdElf)'],
}
for rel, calls in EXPECTED.items():
    text = read(rel)
    if re.search(r'guiMsgBox\(_l\(_STR_(EMBER_NOT_FOUND|EMBER_BIOS_MISSING|POPSTARTER_NOT_FOUND)\)', text):
        failures.append('%s: a PS1 "missing" message still shows no path (use guiMsgBoxMissing)' % rel)
    for call in calls:
        if call not in text:
            failures.append('%s: expected %s' % (rel, call))
# A partition that would not mount was never searched: it must not claim the ELF is missing.
if 'guiMsgBoxMissing(_l(_STR_EMBER_NOT_FOUND), mountSrc)' in read('src/hddsupport.c'):
    failures.append('src/hddsupport.c: a failed partition mount must not say "Missing ember.elf"')

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* Everything the scan touches is faked. Renamed so nothing collides with the host's own headers. */
#undef errno
static int fake_errno;
#define errno fake_errno
#define LOG(...) ((void)0)
#define O_RDONLY 0
#define open fake_open
#define close fake_close
#define opendir fake_opendir
#define readdir fake_readdir
#define closedir fake_closedir
#define DIR fake_DIR
#define dirent fake_dirent

@CONSTANTS@
@ENTRY@

struct dirent { char d_name[256]; };
typedef struct { int isGames; int pos; } DIR;

static const char *coreFile;           /* the one path open() accepts; NULL = ember.elf missing */
static int gamesOpens;                 /* does EMBER/games open at all? */
static int gamesErrno;                 /* errno when it does not */
static const char *const *gameNames;   /* its entries; names starting "file_" are files */
static DIR gamesDir, probeDir;
static struct dirent ent;
#define GAMES_PATH "mass0:/EMBER/games"

static int open(const char *path, int flags) { (void)flags; return coreFile != NULL && !strcmp(path, coreFile) ? 3 : -1; }
static int close(int fd) { (void)fd; return 0; }
static DIR *opendir(const char *path)
{
    size_t n = strlen(GAMES_PATH);
    if (!strcmp(path, GAMES_PATH)) {
        if (!gamesOpens) {
            errno = gamesErrno;
            return NULL;
        }
        gamesDir.isGames = 1;
        gamesDir.pos = 0;
        return &gamesDir;
    }
    if (!strncmp(path, GAMES_PATH "/", n + 1) && strncmp(path + n + 1, "file_", 5) != 0)
        return &probeDir; /* a game folder answers its probe */
    errno = ENOENT;
    return NULL;
}
static struct dirent *readdir(DIR *d)
{
    if (!d->isGames || gameNames == NULL || gameNames[d->pos] == NULL)
        return NULL;
    snprintf(ent.d_name, sizeof(ent.d_name), "%s", gameNames[d->pos++]);
    return &ent;
}
static int closedir(DIR *d) { (void)d; return 0; }

@FUNCTIONS@

static int fails;
static const char *const games[] = {".", "..", "Alpha", "Beta", "file_readme.txt", NULL};

static void expect(const char *what, const char *core, int opens, int err, int want)
{
    cue_entry_t *list = NULL;
    coreFile = core;
    gamesOpens = opens;
    gamesErrno = err;
    gameNames = games;
    int got = cueScanDir("mass0:/", &list);
    if (got != want) {
        printf("FAIL %s: cueScanDir returned %d, expected %d\n", what, got, want);
        fails++;
    } else if (want > 0 && (list == NULL || strcmp(list[0].name, "Alpha") || strcmp(list[1].name, "Beta"))) {
        printf("FAIL %s: the two game folders were not listed\n", what);
        fails++;
    }
    free(list);
}

int main(void)
{
    const char *core = "mass0:/EMBER/ember.elf";

    expect("core present, games listed", core, 1, 0, 2);
    expect("core MISSING still lists the game folders", NULL, 1, 0, 2);
    expect("core missing, no EMBER folder (ENOENT) is empty", NULL, 0, ENOENT, 0);
    expect("core missing, driver collapses errno: still empty, never -1", NULL, 0, EPERM, 0);
    expect("core missing, contended read: still empty, never -1", NULL, 0, EIO, 0);
    expect("core present, absent games folder is empty", core, 0, ENOENT, 0);
    expect("core present, unreadable games folder keeps the last-good list", core, 0, EIO, -1);
    return fails ? 1 : 0;
}
'''

if not failures:
    program = (HARNESS.replace('@CONSTANTS@', constants)
               .replace('@ENTRY@', entry.group(0))
               .replace('@FUNCTIONS@', functions))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'scan.c'
        exe = Path(tmp) / ('scan' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        # -Wno-format-truncation: the scan length-checks a name before copying it, which GCC cannot see.
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-Wno-format-truncation',
                                '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('scan harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            if run.returncode != 0:
                failures.extend(run.stdout.strip().splitlines() or ['scan harness exited %d' % run.returncode])

# What the user actually reads: the helpers that format the second line, compiled from the source.
gui = read('src/gui.c')
hdd = read('src/hddsupport.c')
vcd = read('src/vcdsupport.c')
vcd_defines = defines(read('include/system.h'), 'include/system.h', ('POPS_FOLDER',))
MESSAGES = r'''
#include <stdio.h>
#include <string.h>
struct UIItem;
#define APA_IDMAX 32
@DEFINES@
static char gPopstarterPath[256];
static char shown[512];
static int boxes;
static int guiMsgBox(const char *text, int addAccept, struct UIItem *ui) { (void)addAccept; (void)ui; boxes++; snprintf(shown, sizeof(shown), "%s", text); return 0; }
static char *_l(int id) { static char t[32]; snprintf(t, sizeof(t), "MSG%d", id); return t; }
@FUNCTIONS@
static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL %s: got [%s]\n", m, shown); fails++; } } while (0)
int main(void)
{
    char out[256];
    guiMsgBoxMissing("Missing ember.elf", "mass0:/EMBER/ember.elf");
    CHECK(!strcmp(shown, "Missing ember.elf\nmass0:/EMBER/ember.elf"), "message, then the path on its own line");
    guiMsgBoxMissing("Missing ember.elf", "");
    CHECK(!strcmp(shown, "Missing ember.elf"), "an empty path shows the bare message");
    guiMsgBoxMissing("Missing ember.elf", NULL);
    CHECK(!strcmp(shown, "Missing ember.elf"), "a NULL path shows the bare message");
    guiMsgBoxMissing("100% sure %s", "mass0:/x");
    CHECK(!strcmp(shown, "100% sure %s\nmass0:/x"), "the translated label is text, never a format");
    hddShowEmberMissing(7, "hdd0:__.EMBER", "pfs0:/EMBER/ember.elf");
    CHECK(!strcmp(shown, "MSG7\nhdd0:__.EMBER/EMBER/ember.elf"), "the HDD names the partition, not pfs0:");
    vcdDescribePopstarterLookup("mass0:/", out, sizeof(out));
    snprintf(shown, sizeof(shown), "%s", out);
    CHECK(!strcmp(out, "mass0:/POPS/POPSTARTER.ELF"), "POPSTARTER is looked for in the device's POPS folder");
    vcdDescribePopstarterLookup("hdd0:__common/", out, sizeof(out));
    snprintf(shown, sizeof(shown), "%s", out);
    CHECK(!strcmp(out, "hdd0:__common/POPS/POPSTARTER.ELF"), "the HDD's POPSTARTER home is __common");
    snprintf(gPopstarterPath, sizeof(gPopstarterPath), "mc0:/MINE/POPSTARTER.ELF");
    vcdDescribePopstarterLookup("mass0:/", out, sizeof(out));
    snprintf(shown, sizeof(shown), "%s", out);
    CHECK(!strcmp(out, "mc0:/MINE/POPSTARTER.ELF"), "a custom POPSTARTER.ELF Path is the one named");
    return fails ? 1 : 0;
}
'''
helpers = (function_text(gui, 'src/gui.c', 'void guiMsgBoxMissing(') +
           function_text(hdd, 'src/hddsupport.c', 'static void hddShowEmberMissing(') +
           function_text(vcd, 'src/vcdsupport.c', 'static char vcdSep(') +
           function_text(vcd, 'src/vcdsupport.c', 'void vcdDescribePopstarterLookup('))
if not failures:
    program = MESSAGES.replace('@DEFINES@', vcd_defines).replace('@FUNCTIONS@', helpers)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'messages.c'
        exe = Path(tmp) / ('messages' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(program, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-Wno-format-truncation',
                                '-o', str(exe), str(src)], capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('message harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            if run.returncode != 0:
                failures.extend(run.stdout.strip().splitlines() or ['message harness exited %d' % run.returncode])

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ember scan: a missing core still lists game folders, never fails the scan; launch messages name the path')
