"""The user's .pad USB pad profiles on their way to PADEMU and to the menu's USB pad driver.

src/padprofiles.c is from RIPPS2 build 126-129 by akilluminati47 (https://github.com/akilluminati47/RIPPS2): it reads
the PADS folder beside the settings, packs the profiles and the game's button map (PADS/GAMES/<ID>.pad) into the
180-byte block, and hands that block to a launch (sbPrepare reads it, sysLaunchLoaderElf places it after the modules,
ee_core gives it to PADEMU) and to the menu's driver (read at boot, sent from readPads). This checks:

1. The build and the wiring: padprofiles.o only with PADEMU=1; the six functions the other pieces call, declared as
   agreed; every call to them under #ifdef PADEMU; PadEmuArgs the last member of EECoreConfig_t, in every flavour;
   sbPrepare drops any block an earlier launch left, then reads the profiles for the USB PADEMU only, after the game's
   PADEMU settings are known; the block is placed
   after the cheats, the watch block and the achievements page and before the in-game menu's overlay; the menu reads at
   boot (deferredInit), sends from readPads, and sends again after the NBD server's IOP reset.
2. padprofiles.c compiled on the PC against a fake file system, kernel and driver:
   - the PADS path for each kind of settings home, and none for an empty home, mc? or raw APA (hdd...);
   - no PADS folder: no block, one failed opendir per read, nothing in DIAG.TXT, the menu's driver never called, and
     the next read looks again;
   - one profile: the block padBlockPack makes, dropped by padProfilesClear with nothing read, sent to the menu's
     driver once, again after a reset, and an empty block once when the profile goes; a later launch then gets no
     block, not the old one;
   - a profile with decoder= other than generic, a file over 4095 bytes and a bad file are left out, each with its
     reason in DIAG.TXT; a fifth profile is left out unopened;
   - a profile for a Sony ID (054C, 12BA) or the ShanWan PS3 pad (2563:0575), which neither USB driver ever profiles,
     is left out too, with its reason, whatever its decoder=; another ShanWan pad's is packed;
   - a game map alone makes a block with no profile; no ID, another game, a map that changes nothing or a bad map
     makes none, and the menu never gets a game map;
   - a driver that does not take the block is tried again the next frame; Set Up A USB Pad open sends no profile
     and both ports, closed sends the profiles and one port, and a failed open is undone;
   - interrupts go off only around the shared copy, never across a file or driver call, and come back as they were.
3. The placement, extracted from sysLaunchLoaderElf and run with and without the RETROACHIEVEMENTS overlay: 64-byte
   aligned after the storage end, 8 zero bytes then the block, below 0xD0000 or below the overlay when it goes in, never
   for the Bluetooth PADEMU, PADEMU off, disc mode or a game whose storage was moved, and nothing written with no block.
4. Without PADEMU, padprofiles.c builds to nothing.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
fail = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8', errors='replace')


def blank(text):
    """C text with its comments and string and character literals blanked, same length and lines, for matching code."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
        elif text[i] in '"\'':
            q, j = text[i], i + 1
            while j < n and text[j] != q and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            j = min(j + 1, n)
            out.append(q + ' ' * (j - i - 2) + q if j - i >= 2 else text[i:j])
        else:
            j = i + 1
            out.append(text[i])
        i = j
    return ''.join(out)


def body_of(code, name):
    """The braces of function name in blanked code, or ''."""
    m = re.search(r'^[A-Za-z_][\w \t*]*\b' + name + r'\s*\([^;{)]*\)\s*\{', code, re.M)
    if not m:
        return ''
    depth = 0
    for i in range(m.end() - 1, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return code[m.end() - 1:i + 1]
    return ''


def pademu_lines(code):
    """For each line of blanked code, whether it is built only with PADEMU."""
    stack, flags = [], []
    for line in code.split('\n'):
        m = re.match(r'\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)', line)
        if m:
            kind, cond = m.group(1), m.group(2).strip()
            if kind == 'ifdef':
                stack.append('pos' if cond == 'PADEMU' else 'other')
            elif kind == 'ifndef':
                stack.append('neg' if cond == 'PADEMU' else 'other')
            elif kind == 'if':
                pos = re.search(r'(?<!!)\bdefined\s*\(?\s*PADEMU\b', cond) and '||' not in cond
                stack.append('pos' if pos else 'other')
            elif kind == 'elif' and stack:
                stack[-1] = 'other'
            elif kind == 'else' and stack:
                stack[-1] = 'pos' if stack[-1] == 'neg' else 'other'
            elif kind == 'endif' and stack:
                stack.pop()
        flags.append('pos' in stack)
    return flags


def define(rel, name):
    m = re.search(r'#define\s+' + name + r'\s+(0x[0-9A-Fa-f]+|\d+)\b', read(rel))
    if not m:
        fail.append('%s: #define %s not found' % (rel, name))
        return '0'
    return m.group(1)


# 1. The build and the wiring
mk = read('Makefile')
m = re.search(r'^ifeq \(\$\(PADEMU\),1\)\n(.*?)^(?:else|endif)', mk, re.M | re.S)
if not m or not re.search(r'^\s*FRONTEND_OBJS \+= padprofiles\.o\s*$', m.group(1), re.M) or mk.count('padprofiles.o') != 1:
    fail.append('Makefile: padprofiles.o goes in the ELF in the ifeq ($(PADEMU),1) block, and only there')

hdr = blank(read('include/padprofiles.h'))
CONTRACT = ['int padProfilesPrepare(const char *gameId);', 'const unsigned char *padProfilesBlock(void);',
            'void padProfilesMenuLoad(void);', 'void padProfilesMenuTick(void);', 'int padProfilesMenuLearn(int on);',
            'int padProfilesDir(char *out, int size);']
for sig in CONTRACT:
    if sig not in hdr:
        fail.append('include/padprofiles.h: ' + sig + ' (the name and signature the other pieces call)')

mod = blank(read('src/padprofiles.c'))
if not (mod.strip().startswith('#ifdef PADEMU') and mod.strip().endswith('#endif')):
    fail.append('src/padprofiles.c: the whole module inside #ifdef PADEMU')
for m in re.finditer(r'^([A-Za-z_][\w \t*]*?)\b(\w+)\s*\([^;{)]*\)\s*\{', mod, re.M):
    if m.group(1).split()[0] == 'static':
        continue
    if not m.group(2).startswith('padProfiles') or not re.search(r'\b' + m.group(2) + r'\s*\(', hdr):
        fail.append('src/padprofiles.c: %s is neither static nor declared in include/padprofiles.h' % m.group(2))

dslib = blank(read('modules/ds34usb/ee/libds34usb.h'))
for sig in ['int ds34usb_set_profiles(const u8 *block, int size, int learn);', 'int ds34usb_reinit_ports(u8 ports);']:
    if sig not in dslib:
        fail.append('modules/ds34usb/ee/libds34usb.h: ' + sig)

core = blank(read('ee_core/include/coreconfig.h'))
m = re.search(r'struct EECoreConfig_t\s*\{(.*?)\n\};', core, re.S)
if not m:
    fail.append('ee_core/include/coreconfig.h: struct EECoreConfig_t not found')
else:
    lines = m.group(1).split('\n')
    members = [(i, l.strip()) for i, l in enumerate(lines) if l.strip() and not l.strip().startswith('#')]
    depth = sum(1 if re.match(r'\s*#\s*if', l) else -1 if re.match(r'\s*#\s*endif', l) else 0 for l in lines[:members[-1][0]])
    if members[-1][1] != 'char *PadEmuArgs;' or depth != 0:
        fail.append('ee_core/include/coreconfig.h: char *PadEmuArgs; the last member of EECoreConfig_t, in every flavour '
                    '(the launcher and ee_core share the layout)')

sites = 0
for path in sorted((root / 'src').glob('*.c')):
    if path.name == 'padprofiles.c':
        continue
    code = blank(path.read_text(encoding='utf-8', errors='replace'))
    flags = pademu_lines(code)
    for n, line in enumerate(code.split('\n')):
        if re.search(r'\bpadProfiles\w+\s*\(', line):
            sites += 1
            if not flags[n]:
                fail.append('src/%s:%d: a call to the pad profiles outside #ifdef PADEMU' % (path.name, n + 1))
if sites < 6:
    fail.append('src: %d calls to the pad profiles, want sbPrepare\'s two, sysLaunchLoaderElf, deferredInit, '
                'unloadLwnbdSvr and readPads at least' % sites)

sb = body_of(blank(read('src/supportbase.c')), 'sbPrepare')
m = re.search(r'padProfilesClear\(\);\s*if \(gEnablePadEmu\) \{[^}]*?if \(!\(gPadEmuSettings & 0xFF\)\) \{[^}]*?'
              r'CONFIG_ITEM_STARTUP[^}]*?padProfilesPrepare\(startup\);', sb, re.S)
if not m or sb.find('gPadEmuSettings = 0;') < 0 or sb.find('gPadEmuSettings = 0;') > m.start():
    fail.append('src/supportbase.c: sbPrepare drops any earlier block (padProfilesClear), then reads the profiles and '
                'the #Startup game map for the USB PADEMU only (gEnablePadEmu, low byte of gPadEmuSettings clear), after '
                'the game\'s PADEMU settings are resolved')

opl = blank(read('src/opl.c'))
if 'padProfilesMenuLoad();' not in body_of(opl, 'deferredInit'):
    fail.append('src/opl.c: deferredInit reads the profiles for the menu (padProfilesMenuLoad)')
unl = body_of(opl, 'unloadLwnbdSvr')
if not re.search(r'\breset\(\);\s*#ifdef PADEMU\s*padProfilesMenuResend\(\);', unl):
    fail.append('src/opl.c: unloadLwnbdSvr sends the profiles again right after its IOP reset (padProfilesMenuResend)')
if 'padProfilesMenuTick();' not in body_of(blank(read('src/pad.c')), 'readPads'):
    fail.append('src/pad.c: readPads hands the menu\'s profiles to the driver (padProfilesMenuTick)')

sys_raw = read('src/system.c')
launch = body_of(blank(sys_raw), 'sysLaunchLoaderElf')
order = ['ModuleStorageEnd = (void *)((u8 *)ModuleStorage + ModuleStorageSize);', 'PlaceWatchBlock(ModuleStorageEnd)',
         'raHuntTotal = 0;', 'padProfilesBlock()', 'igrOvlPlaced = sysPlaceIgrOverlay();', 'initKernel(',
         'memset(config, 0, sizeof(struct EECoreConfig_t));', 'config->PadMacroSettings =', 'config->PadEmuArgs = padEmuArgs;']
at = [launch.find(s) for s in order]
if min(at) < 0 or at != sorted(at):
    fail.append('src/system.c: sysLaunchLoaderElf places the block after the storage end, the watch block and the '
                'achievements page, before the overlay and initKernel, and sets config->PadEmuArgs (%s)' %
                ', '.join('%s at %d' % (s, a) for s, a in zip(order, at)))
if not re.search(r'_Static_assert\(PAD_BLOCK_SIZE == 180,', blank(sys_raw)):
    fail.append('src/system.c: a static assert that the block is 180 bytes, as ee_core hands PADEMU 8 + 180')

# the placement block itself, for the program below
lines = sys_raw.split('\n')
start = next((i for i in range(len(lines) - 1) if lines[i].strip() == '#ifdef PADEMU' and "PADEMU's arguments" in lines[i + 1]), -1)
place_body = ''
if start < 0:
    fail.append('src/system.c: the PADEMU arguments block in sysLaunchLoaderElf not found')
else:
    depth, end = 0, start + 1
    while end < len(lines):
        s = lines[end].strip()
        if re.match(r'#\s*if', s):
            depth += 1
        elif re.match(r'#\s*endif', s):
            if depth == 0:
                break
            depth -= 1
        end += 1
    place_body = '\n'.join(lines[start + 1:end])
room = re.search(r'#define PADEMU_ARGS_ROOM (.+)', sys_raw)
if not room:
    fail.append('src/system.c: PADEMU_ARGS_ROOM not found')

cc = shutil.which('gcc') or shutil.which('cc')
if cc is None:
    print('\n'.join(fail) or 'pad profiles launch: no host C compiler, programs skipped')
    sys.exit(1 if fail else 0)

# 2. padprofiles.c on the PC
STUB_OPL = r'''
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
typedef unsigned char u8;
const char *configGetHomePath(void);
int DIntr(void);
int EIntr(void);
int t_open(const char *path, int flags);
int t_close(int fd);
DIR *t_opendir(const char *path);
int t_closedir(DIR *d);
#define open t_open
#define close t_close
#define opendir t_opendir
#define closedir t_closedir
'''
STUB_IOMAN = 'void t_log(const char *fmt, ...);\n#define LOG(...) t_log(__VA_ARGS__)\n'
STUB_DIAG = 'void diagLog(const char *fmt, ...);\n'
STUB_DS34 = 'int ds34usb_set_profiles(const u8 *block, int size, int learn);\nint ds34usb_reinit_ports(u8 ports);\n'

HARNESS = r'''
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
typedef unsigned char u8;
#include <libds34usb.h>
#include "include/diaglog.h"
#include "include/padfile.h"
#include "include/padprofiles.h"

#define MAP_AT (4 + PAD_DEFS_MAX * PAD_DEF_SIZE)

const char *t_home = "";
int t_intr_on = 1, t_di, t_ei, t_bad_intr;
int t_opendirs, t_opendir_ok, t_closedirs, t_opens, t_open_ok, t_closes;
int t_set_ok = 1, t_reinit_ok = 1, t_sets, t_reinits, t_last_size = -1, t_diags;
unsigned char t_last_block[PAD_BLOCK_SIZE];
char t_seq[512], t_diag[4096];

const char *configGetHomePath(void) { return t_home; }
int DIntr(void)
{
    int was = t_intr_on;
    t_intr_on = 0;
    t_di++;
    return was;
}
int EIntr(void)
{
    t_intr_on = 1;
    t_ei++;
    return 0;
}
int t_open(const char *path, int flags)
{
    int fd;
    t_bad_intr += !t_intr_on;
    t_opens++;
    if ((fd = open(path, flags)) >= 0)
        t_open_ok++;
    return fd;
}
int t_close(int fd)
{
    t_closes++;
    return close(fd);
}
DIR *t_opendir(const char *path)
{
    DIR *d;
    t_bad_intr += !t_intr_on;
    t_opendirs++;
    if ((d = opendir(path)) != NULL)
        t_opendir_ok++;
    return d;
}
int t_closedir(DIR *d)
{
    t_closedirs++;
    return closedir(d);
}
void t_log(const char *fmt, ...) { (void)fmt; }
void diagLog(const char *fmt, ...)
{
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    t_diags++;
    strncat(t_diag, line, sizeof(t_diag) - strlen(t_diag) - 2);
    strcat(t_diag, "|");
}
static void t_note(const char *s) { strncat(t_seq, s, sizeof(t_seq) - strlen(t_seq) - 1); }
int ds34usb_set_profiles(const u8 *block, int size, int learn)
{
    char s[16];
    int i, zero = 1;
    t_bad_intr += !t_intr_on;
    t_sets++;
    t_last_size = size;
    memcpy(t_last_block, block, size < PAD_BLOCK_SIZE ? size : PAD_BLOCK_SIZE);
    for (i = 0; i < size; i++)
        zero &= block[i] == 0;
    snprintf(s, sizeof(s), "S%d%s ", learn, zero ? "Z" : block[0] == 'P' && block[1] == 'D' ? "P" : "?");
    t_note(s);
    return t_set_ok;
}
int ds34usb_reinit_ports(u8 ports)
{
    char s[8];
    t_bad_intr += !t_intr_on;
    t_reinits++;
    snprintf(s, sizeof(s), "R%d ", ports);
    t_note(s);
    return t_reinit_ok;
}

static const char *scen;
static int fails;
#define CHECK(c, ...)                                          \
    do {                                                       \
        if (!(c)) {                                            \
            printf("FAIL %s (harness line %d): ", scen, __LINE__); \
            printf(__VA_ARGS__);                               \
            printf("\n");                                      \
            fails++;                                           \
        }                                                      \
    } while (0)

static void balanced(void)
{
    CHECK(t_intr_on == 1 && t_di == t_ei, "interrupts back on after every call (DIntr %d, EIntr %d)", t_di, t_ei);
    CHECK(t_bad_intr == 0, "%d file or driver calls with interrupts off", t_bad_intr);
    CHECK(t_open_ok == t_closes && t_opendir_ok == t_closedirs, "everything opened is closed (files %d/%d, folders %d/%d)",
          t_closes, t_open_ok, t_closedirs, t_opendir_ok);
}

// the block padBlockPack makes of one profile and no game map
static int expect_block(const char *file, unsigned vid, unsigned pid, unsigned char out[PAD_BLOCK_SIZE])
{
    char path[1024], text[8192], err[96];
    unsigned char map[PAD_B_COUNT];
    pad_def_t d;
    FILE *f;
    int n;
    snprintf(path, sizeof(path), "%s/PADS/%s", t_home, file);
    if ((f = fopen(path, "rb")) == NULL)
        return -1;
    n = (int)fread(text, 1, sizeof(text) - 1, f);
    fclose(f);
    text[n] = '\0';
    if (padDefParse(text, n, vid, pid, &d, err, sizeof(err)) != 0)
        return -1;
    memset(map, PAD_REMAP_SAME, sizeof(map));
    padBlockPack(&d, 1, map, out);
    return 0;
}

static void s_dir(void)
{
    static const struct
    {
        const char *home, *want;
    } c[] = {{"", NULL}, {"mc?:OPL", NULL}, {"hdd0:", NULL}, {"hdd0:+OPL", NULL}, {"mass0:", "mass0:PADS"},
             {"mass0:/OPL", "mass0:/OPL/PADS"}, {"mass0:/OPL/", "mass0:/OPL/PADS"}, {"mc0:OPL", "mc0:OPL/PADS"},
             {"pfs0:", "pfs0:PADS"}, {"smb0:OPL", "smb0:OPL/PADS"}};
    char out[64];
    unsigned i;
    for (i = 0; i < sizeof(c) / sizeof(c[0]); i++) {
        int r;
        t_home = c[i].home;
        memset(out, 'x', sizeof(out) - 1);
        out[sizeof(out) - 1] = '\0';
        r = padProfilesDir(out, sizeof(out));
        if (c[i].want == NULL)
            CHECK(r == -1 && out[0] == '\0', "home '%s': no PADS path (got %d '%s')", c[i].home, r, out);
        else
            CHECK(r == 0 && !strcmp(out, c[i].want), "home '%s': want '%s', got %d '%s'", c[i].home, c[i].want, r, out);
    }
    t_home = "mass0:/OPL";
    CHECK(padProfilesDir(out, 16) == 0 && !strcmp(out, "mass0:/OPL/PADS"), "a path that just fits");
    memset(out, 'x', sizeof(out) - 1);
    CHECK(padProfilesDir(out, 15) == -1 && out[0] == '\0', "a path that does not fit is refused, not cut");
    CHECK(padProfilesDir(NULL, 16) == -1, "no buffer");
    t_home = "mc?:OPL";
    CHECK(padProfilesPrepare("SLUS_123.45") == -1 && padProfilesBlock() == NULL, "no memory card: no block");
    padProfilesMenuLoad();
    padProfilesMenuTick();
    CHECK(t_opendirs == 0 && t_opens == 0, "a home with no PADS path is never read (%d folders, %d files)", t_opendirs, t_opens);
    CHECK(t_sets == 0 && t_reinits == 0, "nor is the driver called (%s)", t_seq);
    balanced();
}

static void s_absent(void)
{
    CHECK(padProfilesPrepare("SLUS_123.45") == -1, "no PADS folder: no block");
    CHECK(padProfilesBlock() == NULL, "no PADS folder: padProfilesBlock() is NULL, so PadEmuArgs stays NULL");
    CHECK(t_opendirs == 1 && t_opendir_ok == 0 && t_opens == 0, "one failed opendir and nothing else (%d, %d files)", t_opendirs, t_opens);
    CHECK(t_diags == 0, "nothing in DIAG.TXT (%s)", t_diag);
    padProfilesMenuLoad();
    padProfilesMenuTick();
    padProfilesMenuTick();
    padProfilesMenuResend();
    padProfilesMenuTick();
    CHECK(t_opendirs == 2, "the menu's read is one more failed opendir (%d)", t_opendirs);
    CHECK(t_sets == 0 && t_reinits == 0, "the menu's driver is never called (%s)", t_seq);
    CHECK(padProfilesPrepare("SLUS_123.45") == -1 && t_opendirs == 3, "the absence is not remembered: the next launch looks again");
    balanced();
}

static void s_empty(void)
{
    CHECK(padProfilesPrepare("SLUS_123.45") == -1 && padProfilesBlock() == NULL, "an empty PADS folder: no block");
    CHECK(t_opendirs == 1 && t_open_ok == 0, "no file is opened (%d)", t_open_ok);
    CHECK(t_diags == 0, "nothing in DIAG.TXT (%s)", t_diag);
    padProfilesMenuLoad();
    padProfilesMenuTick();
    CHECK(t_sets == 0, "the menu's driver is not called (%s)", t_seq);
    balanced();
}

static void s_one(void)
{
    unsigned char want[PAD_BLOCK_SIZE];
    const unsigned char *b;
    char path[1024];
    int i;
    CHECK(expect_block("0079_0006.pad", 0x0079, 0x0006, want) == 0, "the test profile reads");
    CHECK(padProfilesPrepare("SLUS_123.45") == 0, "one profile: a block");
    b = padProfilesBlock();
    CHECK(b != NULL && !memcmp(b, want, PAD_BLOCK_SIZE), "the block is the profile as padBlockPack packs it");
    if (b != NULL) {
        CHECK(b[0] == 'P' && b[1] == 'D' && b[2] == PAD_FORMAT && b[3] == 1, "PD, format 1, one profile");
        CHECK(b[4] == 0x79 && b[5] == 0x00 && b[6] == 0x06 && b[7] == 0x00, "the VID and PID from its name, little endian");
        for (i = MAP_AT; i < PAD_BLOCK_SIZE; i++)
            CHECK(b[i] == PAD_REMAP_SAME, "no game map: byte %d", i);
    }
    CHECK(t_diags == 0, "a good profile is not reported (%s)", t_diag);
    i = t_opendirs + t_opens;
    padProfilesClear();
    CHECK(padProfilesBlock() == NULL && t_opendirs + t_opens == i, "padProfilesClear drops the block and reads nothing");
    CHECK(padProfilesPrepare("SLUS_123.45") == 0 && padProfilesBlock() != NULL, "the next read makes it again");
    padProfilesMenuLoad();
    CHECK(t_sets == 0, "the read does not call the driver");
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S0P ") && t_last_size == PAD_BLOCK_SIZE && !memcmp(t_last_block, want, PAD_BLOCK_SIZE),
          "readPads sends the profile (%s)", t_seq);
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(t_sets == 1, "once (%d)", t_sets);
    padProfilesMenuResend();
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S0P S0P "), "after the NBD server's IOP reset, once more (%s)", t_seq);
    snprintf(path, sizeof(path), "%s/PADS/0079_0006.pad", t_home);
    CHECK(remove(path) == 0, "remove %s", path);
    CHECK(padProfilesPrepare("SLUS_123.45") == -1 && padProfilesBlock() == NULL, "the profile gone: a later launch gets no block, not the old one");
    padProfilesMenuLoad();
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S0P S0P S0Z "), "the menu's driver gets an empty block once (%s)", t_seq);
    padProfilesMenuLoad();
    padProfilesMenuTick();
    padProfilesMenuResend();
    padProfilesMenuTick();
    CHECK(t_sets == 3, "and then nothing (%s)", t_seq);
    balanced();
    t_intr_on = 0;
    padProfilesMenuResend();
    CHECK(t_intr_on == 0, "a caller with interrupts off gets them back off");
    t_intr_on = 1;
}

static void s_ds3(void)
{
    const unsigned char *b;
    CHECK(padProfilesPrepare("SLUS_123.45") == 0, "the generic profile makes a block");
    b = padProfilesBlock();
    CHECK(b != NULL && b[3] == 1 && b[4] == 0x79 && b[5] == 0x00, "the generic profile alone (count %d)", b ? b[3] : -1);
    CHECK(t_diags == 1 && strstr(t_diag, "0001_0004.pad left out: decoder= is not generic") != NULL,
          "the decoder=ds3 profile is left out, and DIAG.TXT says why (%s)", t_diag);
    balanced();
}

static void s_builtin(void)
{
    static const char *const dead[] = {"054C_0268.pad", "054C_05C4.pad", "12BA_0100.pad", "2563_0575.pad"};
    const unsigned char *b;
    char want[96], path[1024];
    unsigned i;
    CHECK(padProfilesPrepare("SLUS_123.45") == 0, "another ShanWan pad's profile makes a block");
    b = padProfilesBlock();
    CHECK(b != NULL && b[3] == 1 && b[4] == 0x63 && b[5] == 0x25 && b[6] == 0x76 && b[7] == 0x05,
          "2563_0576.pad alone (count %d)", b ? b[3] : -1);
    for (i = 0; i < sizeof(dead) / sizeof(dead[0]); i++) {
        snprintf(want, sizeof(want), "%s left out: a Sony pad or the ShanWan PS3 pad takes no profile", dead[i]);
        CHECK(strstr(t_diag, want) != NULL, "%s is left out, whatever its decoder=, and DIAG.TXT says why (%s)", dead[i], t_diag);
    }
    CHECK(t_diags == 4, "four files reported (%d)", t_diags);
    snprintf(path, sizeof(path), "%s/PADS/2563_0576.pad", t_home);
    CHECK(remove(path) == 0, "remove %s", path);
    CHECK(padProfilesPrepare("SLUS_123.45") == -1 && padProfilesBlock() == NULL, "only those left: no block");
    padProfilesMenuLoad();
    padProfilesMenuTick();
    CHECK(t_sets == 0, "and the menu's driver is not called (%s)", t_seq);
    balanced();
}

static void s_big(void)
{
    const unsigned char *b;
    CHECK(padProfilesPrepare("SLUS_123.45") == 0, "a 4095-byte profile makes a block");
    b = padProfilesBlock();
    CHECK(b != NULL && b[3] == 1 && b[4] == 0x11 && b[5] == 0x11, "1111_2222.pad alone (count %d)", b ? b[3] : -1);
    CHECK(strstr(t_diag, "3333_4444.pad left out: larger than 4095 bytes") != NULL, "a 4096-byte file is left out, not cut (%s)", t_diag);
    CHECK(strstr(t_diag, "5555_6666.pad left out: line 2: not key=value") != NULL, "a bad file is left out with its line and reason (%s)", t_diag);
    CHECK(t_diags == 2, "two files reported (%d)", t_diags);
    balanced();
}

static void s_maponly(void)
{
    const unsigned char *b;
    int i;
    CHECK(padProfilesPrepare("SLUS_123.45") == 0, "a game map alone makes a block");
    b = padProfilesBlock();
    CHECK(b != NULL && b[3] == 0, "with no profile (count %d)", b ? b[3] : -1);
    if (b != NULL)
        for (i = 0; i < PAD_B_COUNT; i++)
            CHECK(b[MAP_AT + i] == (i == PAD_B_CROSS ? PAD_B_CIRCLE : PAD_REMAP_SAME), "game map byte %d is %d", i, b[MAP_AT + i]);
    CHECK(padProfilesPrepare(NULL) == -1 && padProfilesBlock() == NULL, "no game ID: no block");
    CHECK(padProfilesPrepare("") == -1, "an empty game ID: no block");
    CHECK(padProfilesPrepare("SLUS_999.99") == -1, "another game: no block");
    CHECK(padProfilesPrepare("SLES_000.00") == -1, "a map that changes nothing: no block");
    CHECK(t_diags == 0, "nothing reported so far (%s)", t_diag);
    CHECK(padProfilesPrepare("SCUS_111.11") == -1 && t_diags == 1 && strstr(t_diag, "SCUS_111.11.pad left out: ") != NULL,
          "a bad map is left out, and DIAG.TXT says why (%s)", t_diag);
    padProfilesMenuLoad();
    padProfilesMenuTick();
    CHECK(t_sets == 0, "the menu never gets a game map (%s)", t_seq);
    balanced();
}

static void s_five(void)
{
    const unsigned char *b;
    CHECK(padProfilesPrepare("SLUS_123.45") == 0 && (b = padProfilesBlock()) != NULL && b[3] == PAD_DEFS_MAX,
          "five profiles: the first four are packed");
    CHECK(t_diags == 1 && strstr(t_diag, "left out: the first 4 profiles fill the block") != NULL, "the fifth is reported (%s)", t_diag);
    CHECK(t_open_ok == PAD_DEFS_MAX, "and not opened (%d files)", t_open_ok);
    balanced();
}

static void s_retry(void)
{
    t_set_ok = 0;
    padProfilesMenuLoad();
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(t_sets == 2, "a driver that does not take the block yet is tried again the next frame (%d)", t_sets);
    t_set_ok = 1;
    padProfilesMenuTick();
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(t_sets == 3 && t_reinits == 0, "until it does, and then not again (%s)", t_seq);
    balanced();
}

static void s_learn(void)
{
    unsigned char want[PAD_BLOCK_SIZE];
    CHECK(expect_block("0079_0006.pad", 0x0079, 0x0006, want) == 0, "the test profile reads");
    padProfilesMenuLoad();
    CHECK(padProfilesMenuLearn(1) == 0, "Set Up A USB Pad opens");
    CHECK(!strcmp(t_seq, "S1Z R3 "), "open: no profile, both ports (%s)", t_seq);
    padProfilesMenuTick();
    padProfilesMenuLoad(); // a profile saved while the screen is open
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S1Z R3 "), "nothing is sent while it is open (%s)", t_seq);
    CHECK(padProfilesMenuLearn(0) == 0, "Set Up A USB Pad closes");
    CHECK(!strcmp(t_seq, "S1Z R3 S0P R1 ") && !memcmp(t_last_block, want, PAD_BLOCK_SIZE), "closed: the profiles and the menu's one port (%s)", t_seq);
    padProfilesMenuTick();
    CHECK(t_sets == 2, "and nothing more (%s)", t_seq);
    balanced();
}

static void s_learnfail(void)
{
    padProfilesMenuLoad();
    padProfilesMenuTick();
    t_set_ok = 0;
    CHECK(padProfilesMenuLearn(1) < 0, "an open the driver does not take fails");
    CHECK(!strcmp(t_seq, "S0P S1Z S0P "), "and is undone (%s)", t_seq);
    t_set_ok = 1;
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S0P S1Z S0P S0P "), "not left learning: readPads sends the profiles again (%s)", t_seq);
    t_reinit_ok = 0;
    CHECK(padProfilesMenuLearn(1) < 0, "an open whose port change fails fails");
    CHECK(!strcmp(t_seq, "S0P S1Z S0P S0P S1Z R3 S0P R1 "), "and is undone (%s)", t_seq);
    t_reinit_ok = 1;
    padProfilesMenuTick();
    padProfilesMenuTick();
    CHECK(!strcmp(t_seq, "S0P S1Z S0P S0P S1Z R3 S0P R1 S0P "), "then readPads sends the profiles once (%s)", t_seq);
    balanced();
}

static void s_learnnone(void)
{
    CHECK(padProfilesMenuLearn(1) == 0 && padProfilesMenuLearn(0) == 0, "Set Up A USB Pad opens and closes with no PADS folder");
    CHECK(!strcmp(t_seq, "S1Z R3 S0Z R1 "), "no profile either way (%s)", t_seq);
    padProfilesMenuTick();
    CHECK(t_sets == 2 && t_opendirs == 0, "and no file is read (%s)", t_seq);
    balanced();
}

int main(int argc, char **argv)
{
    static const struct
    {
        const char *name;
        void (*run)(void);
    } s[] = {{"dir", s_dir}, {"absent", s_absent}, {"empty", s_empty}, {"one", s_one}, {"ds3", s_ds3}, {"builtin", s_builtin},
             {"big", s_big}, {"maponly", s_maponly}, {"five", s_five}, {"retry", s_retry}, {"learn", s_learn},
             {"learnfail", s_learnfail}, {"learnnone", s_learnnone}};
    unsigned i;
    if (argc != 3)
        return 2;
    scen = argv[1];
    if (strcmp(argv[2], "-"))
        t_home = argv[2];
    for (i = 0; i < sizeof(s) / sizeof(s[0]); i++)
        if (!strcmp(s[i].name, scen)) {
            s[i].run();
            if (!fails)
                printf("ok %s\n", scen);
            return fails ? 1 : 0;
        }
    printf("FAIL no scenario %s\n", scen);
    return 2;
}
'''

# A generic profile (test_ripps2_pad.py's copy DualShock 3), and one PADEMU would play with its own decoder
GEN = ('# USB Gamepad (made by RIPPS2)\r\n[Device]\r\nformat=1\r\nname=USB Gamepad\r\ndecoder=generic\r\noffset=0\r\n'
       '[Buttons]\r\nsquare=b0.0\r\ncross=b0.1\r\ncircle=b0.2\r\ntriangle=b0.3\r\nl1=b0.4\r\nr1=b0.5\r\nl2=b0.6\r\n'
       'r2=b0.7\r\nselect=b1.0\r\nstart=b1.1\r\nl3=b1.2\r\nr3=!b1.3\r\n[Axes]\r\ndpad=hat2\r\nlx=a3\r\nly=a4\r\nrx=a5\r\n'
       'ry=a6-\r\ndeadzone=12\r\n')
DS3 = '[Device]\nformat=1\nname=DualShock 3\ndecoder=ds3\n[Buttons]\ncross=b0.1\n'


def padded(text, size):
    """text with comment lines after it, size bytes in all"""
    out, left = text, size - len(text)
    while left > 0:
        n = min(left, 80)
        out += '#' * (n - 1) + '\n'
        left -= n
    assert len(out) == size
    return out


SCENARIOS = {
    'dir': None,
    'absent': {},
    'empty': {'PADS/readme.txt': 'not a profile\n', 'PADS/GAMES/': None},
    'one': {'PADS/0079_0006.pad': GEN},
    'ds3': {'PADS/0001_0004.pad': DS3, 'PADS/0079_0006.pad': GEN},
    'builtin': {'PADS/054C_0268.pad': GEN, 'PADS/054C_05C4.pad': DS3, 'PADS/12BA_0100.pad': GEN, 'PADS/2563_0575.pad': GEN,
                'PADS/2563_0576.pad': GEN},
    'big': {'PADS/1111_2222.pad': padded(GEN, 4095), 'PADS/3333_4444.pad': padded(GEN, 4096),
            'PADS/5555_6666.pad': 'cross=b0.1\nnot a line\n'},
    'maponly': {'PADS/GAMES/SLUS_123.45.pad': 'format=1\ncross=circle\n', 'PADS/GAMES/SLES_000.00.pad': 'format=1\n',
                'PADS/GAMES/SCUS_111.11.pad': 'format=1\ncross=banana\n'},
    'five': {'PADS/100%d_0001.pad' % i: GEN for i in range(1, 6)},
    'retry': {'PADS/0079_0006.pad': GEN},
    'learn': {'PADS/0079_0006.pad': GEN},
    'learnfail': {'PADS/0079_0006.pad': GEN},
    'learnnone': {},
}

# 3. The placement, extracted from sysLaunchLoaderElf
PLACE = r'''
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "include/padfile.h"
typedef uint32_t u32;
typedef uint8_t u8;
#define OPL_MOD_STORAGE  @OPL_MOD_STORAGE@
#define COMPAT_MODE_6    @COMPAT_MODE_6@
#define IGROVL_BASE      @IGROVL_BASE@
#define PADEMU_ARGS_ROOM @ROOM@
#define LOG(...)         ((void)0)
int gEnablePadEmu, gPadEmuSettings, gIgrMenu;
static const unsigned char *t_block;
static const unsigned char *padProfilesBlock(void) { return t_block; }
static int t_diags, t_writes;
static char t_diag[256];
static uintptr_t t_set_at, t_cpy_at;
static size_t t_set_n, t_cpy_n;
static const void *t_cpy_src;
static void diagLog(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(t_diag, sizeof(t_diag), fmt, ap);
    va_end(ap);
    t_diags++;
}
static void t_memset(void *p, int v, size_t n)
{
    t_set_at = v == 0 ? (uintptr_t)p : 1;
    t_set_n = n;
    t_writes++;
}
static void t_memcpy(void *d, const void *s, size_t n)
{
    t_cpy_at = (uintptr_t)d;
    t_cpy_src = s;
    t_cpy_n = n;
    t_writes++;
}
#define memset(p, v, n) t_memset((p), (v), (n))
#define memcpy(d, s, n) t_memcpy((d), (s), (n))
static char *place(void *ModuleStorage, void **endp, int discMode, unsigned int compatflags)
{
    void *ModuleStorageEnd = *endp;
    (void)discMode;
    (void)compatflags;
@BODY@
    *endp = ModuleStorageEnd;
    return padEmuArgs;
}
#undef memset
#undef memcpy

static const unsigned char blk[PAD_BLOCK_SIZE] = {'P', 'D', 1, 1};
static int fails;
#define CHECK(c, ...)            \
    do {                         \
        if (!(c)) {              \
            printf("FAIL ");     \
            printf(__VA_ARGS__); \
            printf("\n");        \
            fails++;             \
        }                        \
    } while (0)

static void run(const char *what, uintptr_t storage, uintptr_t end, int enable, int settings, int disc, int igr,
                unsigned compat, const unsigned char *block, uintptr_t wantAt, uintptr_t wantEnd, int wantDiags)
{
    void *e = (void *)end;
    char *a;
    gEnablePadEmu = enable;
    gPadEmuSettings = settings;
    gIgrMenu = igr;
    t_block = block;
    t_diags = t_writes = 0;
    t_set_at = t_cpy_at = 0;
    t_set_n = t_cpy_n = 0;
    t_cpy_src = NULL;
    t_diag[0] = '\0';
    a = place((void *)storage, &e, disc, compat);
    CHECK((uintptr_t)a == wantAt, "%s: PadEmuArgs %#lx, want %#lx", what, (unsigned long)(uintptr_t)a, (unsigned long)wantAt);
    CHECK((uintptr_t)e == wantEnd, "%s: storage end %#lx, want %#lx", what, (unsigned long)(uintptr_t)e, (unsigned long)wantEnd);
    if (wantAt) {
        CHECK(t_writes == 2 && t_set_at == wantAt && t_set_n == 8 && t_cpy_at == wantAt + 8 && t_cpy_n == PAD_BLOCK_SIZE &&
                  t_cpy_src == block,
              "%s: 8 zero bytes for ee_core, then the block", what);
        CHECK(wantAt % 64 == 0, "%s: 64-byte aligned", what);
    } else
        CHECK(t_writes == 0, "%s: nothing written", what);
    CHECK(t_diags == wantDiags, "%s: %d DIAG.TXT lines, want %d (%s)", what, t_diags, wantDiags, t_diag);
}

int main(void)
{
    const uintptr_t S = OPL_MOD_STORAGE;
    CHECK(PADEMU_ARGS_ROOM == 192, "8 + 180 bytes in whole 64-byte lines, %d", PADEMU_ARGS_ROOM);
    run("no profiles", S, 0xB7000, 1, 0, 0, 0, 0, NULL, 0, 0xB7000, 0);
    run("USB PADEMU", S, 0xB7000, 1, 0, 0, 0, 0, blk, 0xB7000, 0xB70C0, 1);
    run("an unaligned storage end", S, 0xB7010, 1, 0, 0, 0, 0, blk, 0xB7040, 0xB7100, 1);
    run("Bluetooth PADEMU", S, 0xB7000, 1, 0x0101, 0, 0, 0, blk, 0, 0xB7000, 0);
    run("PADEMU off", S, 0xB7000, 0, 0, 0, 0, 0, blk, 0, 0xB7000, 0);
    run("disc mode", S, 0xB7000, 1, 0, 1, 0, 0, blk, 0, 0xB7000, 0);
    run("a game whose storage was moved", 0x01FC7000, 0x01FD0000, 1, 0, 0, 0, 0, blk, 0, 0x01FD0000, 1);
    run("a game whose storage was moved lower", 0x90000, 0xA0000, 1, 0, 0, 0, 0, blk, 0, 0xA0000, 1);
    run("just fits below 0xD0000", S, 0xCFF40, 1, 0, 0, 0, 0, blk, 0xCFF40, 0xD0000, 1);
    run("no room below 0xD0000", S, 0xCFF41, 1, 0, 0, 0, 0, blk, 0, 0xCFF41, 1);
#ifdef IGR_OVERLAY
    run("overlay: just fits below it", S, 0xCBF40, 1, 0, 0, 1, 0, blk, 0xCBF40, IGROVL_BASE, 1);
    run("overlay: no room below it", S, 0xCBF80, 1, 0, 0, 1, 0, blk, 0, 0xCBF80, 1);
    run("overlay: none with compat mode 6", S, 0xCBF80, 1, 0, 0, 1, COMPAT_MODE_6, blk, 0xCBF80, 0xCC040, 1);
    run("overlay: none with the menu off", S, 0xCBF80, 1, 0, 0, 0, 0, blk, 0xCBF80, 0xCC040, 1);
    run("overlay: no place for it already", S, 0xCC100, 1, 0, 0, 1, 0, blk, 0xCC100, 0xCC1C0, 1);
#else
    run("menu in ee_core: 0xD0000 the top", S, 0xCBF80, 1, 0, 0, 1, 0, blk, 0xCBF80, 0xCC040, 1);
#endif
    if (!fails)
        printf("placement ok\n");
    return fails ? 1 : 0;
}
'''

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    stub = td / 'stub'
    (stub / 'include').mkdir(parents=True)
    (stub / 'include/opl.h').write_text(STUB_OPL, encoding='utf-8')
    (stub / 'include/ioman.h').write_text(STUB_IOMAN, encoding='utf-8')
    (stub / 'include/diaglog.h').write_text(STUB_DIAG, encoding='utf-8')
    (stub / 'libds34usb.h').write_text(STUB_DS34, encoding='utf-8')
    (td / 'harness.c').write_text(HARNESS, encoding='utf-8')
    exe = td / 'harness.exe'
    flags = [cc, '-std=gnu99', '-Wall', '-Wextra', '-Werror']
    r = subprocess.run(flags + ['-DPADEMU', '-I', str(stub), '-I', str(root), str(td / 'harness.c'),
                                str(root / 'src/padprofiles.c'), str(root / 'src/padfile.c'), '-o', str(exe)],
                       capture_output=True, text=True)
    if r.returncode:
        fail.append('src/padprofiles.c must build on the PC with PADEMU: ' + r.stderr[-1500:])
    else:
        for name, files in SCENARIOS.items():
            home = td / name / 'OPL'
            if files is not None:
                home.mkdir(parents=True)
                for rel, text in files.items():
                    if text is None:
                        (home / rel).mkdir(parents=True, exist_ok=True)
                        continue
                    (home / rel).parent.mkdir(parents=True, exist_ok=True)
                    (home / rel).write_bytes(text.encode('ascii'))
            r = subprocess.run([str(exe), name, str(home) if files is not None else '-'], capture_output=True, text=True, timeout=60)
            if r.returncode or ('ok ' + name) not in r.stdout:
                fail.append('padprofiles.c, %s:\n%s' % (name, (r.stdout + r.stderr).strip()[-2000:]))

    # 4. without PADEMU the module is empty: these definitions would clash with any it made
    (td / 'none.c').write_text('int padProfilesPrepare(const char *g) { return g != 0; }\n'
                               'const unsigned char *padProfilesBlock(void) { return 0; }\nvoid padProfilesClear(void) {}\n'
                               'void padProfilesMenuLoad(void) {}\nvoid padProfilesMenuTick(void) {}\n'
                               'int padProfilesMenuLearn(int on) { return on; }\nvoid padProfilesMenuResend(void) {}\n'
                               'int padProfilesDir(char *out, int size) { return out != 0 && size > 0; }\n'
                               'int padProfilesRead(const char *p, char *b, int s) { return p != 0 && b != 0 && s > 0; }\n'
                               'int padProfilesLeftOut(const void *d) { return d != 0; }\n'
                               'int main(void) { return padProfilesBlock() != 0; }\n', encoding='utf-8')
    r = subprocess.run(flags + ['-I', str(stub), '-I', str(root), str(td / 'none.c'), str(root / 'src/padprofiles.c'),
                                '-o', str(td / 'none.exe')], capture_output=True, text=True)
    if r.returncode:
        fail.append('src/padprofiles.c without PADEMU must build to nothing: ' + r.stderr[-800:])

    if place_body and room:
        prog = (PLACE.replace('@BODY@', place_body).replace('@ROOM@', room.group(1).strip())
                .replace('@OPL_MOD_STORAGE@', define('include/iosupport.h', 'OPL_MOD_STORAGE'))
                .replace('@COMPAT_MODE_6@', define('include/iosupport.h', 'COMPAT_MODE_6'))
                .replace('@IGROVL_BASE@', define('ee_core/include/igrovl.h', 'IGROVL_BASE')))
        (td / 'place.c').write_text(prog, encoding='utf-8')
        for extra in ([], ['-DIGR_OVERLAY']):
            what = 'with the overlay' if extra else 'without the overlay'
            pexe = td / ('place%d.exe' % len(extra))
            r = subprocess.run(flags + ['-Wno-int-to-pointer-cast', '-Wno-pointer-to-int-cast'] + extra +
                               ['-I', str(root), str(td / 'place.c'), '-o', str(pexe)], capture_output=True, text=True)
            if r.returncode:
                fail.append('the placement from src/system.c must build on the PC (%s): %s' % (what, r.stderr[-1500:]))
                continue
            r = subprocess.run([str(pexe)], capture_output=True, text=True, timeout=60)
            if r.returncode or 'placement ok' not in r.stdout:
                fail.append('the placement %s:\n%s' % (what, (r.stdout + r.stderr).strip()[-2000:]))

print('\n'.join(fail) or 'pad profiles launch: wired under PADEMU; no PADS folder costs one failed opendir and changes nothing; '
      'the profiles and the game map reach the launch block and the menu\'s driver, bad files are left out with their '
      'reason, and the block is placed only where it fits')
sys.exit(1 if fail else 0)
