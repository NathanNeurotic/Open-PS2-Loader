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

# Every launch leg must name the file it looked for, not just say "Missing ember.elf".
for rel in ('src/bdmsupport.c', 'src/ethsupport.c', 'src/mmcesupport.c', 'src/udpfssupport.c', 'src/hddsupport.c'):
    text = read(rel)
    if re.search(r'guiMsgBox\(_l\(_STR_(EMBER_NOT_FOUND|EMBER_BIOS_MISSING|POPSTARTER_NOT_FOUND)\)', text):
        failures.append('%s: a PS1 "missing" message still shows no path (use guiMsgBoxMissing)' % rel)

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

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ember scan: a missing core still lists game folders, never fails the scan; launch messages name the path')
