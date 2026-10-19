"""Run the Ember scanner over the real mmceman directory calls, end to end.

Compiles, unmodified:
  * mmceman's mmce_fs_dopen / mmce_fs_dread at the pin install_coherent_mmce.sh builds, with the
    repo's mmceman patches applied in the installer's order;
  * the pinned SDK's fileXio dread helper, getdents and __transform_errno (the EE-side path from
    readdir() down to the IOP driver's return value);
  * the production Ember scanner from src/cuesupport.c.
Only the SIO2 transfer is replaced, by a card that answers the way the sd2psXtd MMCE firmware does:
its DOPEN opens files as well as folders (sd_open), and its DREAD replies a non-zero status once
sd_iterate_dir's openNext fails -- at the end of every listing, and for a FILE opened as a folder.

Without mmceman-fs-dread-eof.patch that status reached the EE as readdir() == NULL with errno
EPERM, cueScanDir treated every completed MMCE listing as a read failure, and ps1FillGameList
published the POPSTARTER half alone: no Ember titles on MMCE. The test builds that baseline too
and requires it to fail, so it proves it can see the defect, then requires the patched driver to
list the games while still reporting real SIO2 timeouts as failures.
"""
from pathlib import Path
import argparse
import hashlib
import re
import subprocess
import tempfile
import urllib.request

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, help='Cache holding <repo>/<path> copies of the pinned sources')
args = parser.parse_args()

installer = (root / '.github/scripts/install_coherent_mmce.sh').read_text()
MMCE_PIN = re.search(r'MMCE_PIN="\$\{MMCE_PIN:-([0-9a-f]{40})\}"', installer)[1]
SDK_PIN = '329e2bb43287e16af16c4dde1c614e2662c24468'  # same SDK ref as bdmfs-vmc-sources.json
SOURCES = {
    'mmce_fs.c': ('ps2-mmce/mmceman', MMCE_PIN, 'mmceman/src/mmce_fs.c',
                  '0f6ffa10a03dcdd3a453ae65b99426e126d30570ebe8cffaaa489896384efdc9'),
    'mmce_cmds.h': ('ps2-mmce/mmceman', MMCE_PIN, 'mmceman/include/mmce_cmds.h',
                    '1163e81f9f4557ef6ee54c35abc6cdc0df9bf8eca7f18fdb759f863a09f00b8a'),
    'glue.c': ('ps2dev/ps2sdk', SDK_PIN, 'ee/libcglue/src/glue.c',
               '16098641d0bf2b7fea847d12285cb2ec94ccd4cb54c731f19c86f62aa1c1c2e5'),
    'fileXio_ps2sdk.c': ('ps2dev/ps2sdk', SDK_PIN, 'ee/rpc/filexio/src/fileXio_ps2sdk.c',
                         'e780b3ea3c5886a18820facf4a25ea38d9a2a982306b2184349e1d5a5419a40a'),
}
# The installer's order; the last one is the fix under test.
PATCHES = ['mmceman-fs-close-fd-leak.patch', 'mmceman-fs-open-enoent.patch',
           'mmceman-fs-dopen-enoent.patch', 'mmceman-fs-dread-eof.patch']
for name in PATCHES:
    assert name in installer, name + ' is no longer applied by install_coherent_mmce.sh'


def fetch(name):
    repo, ref, path, digest = SOURCES[name]
    if args.source:
        data = (args.source / repo / path).read_bytes()
    else:
        url = 'https://raw.githubusercontent.com/{}/{}/{}'.format(repo, ref, path)
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    assert hashlib.sha256(data).hexdigest() == digest, 'source hash mismatch: ' + path
    return data.decode('utf-8')


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


def patched_driver(work, patches):
    tree = work / 'mmceman-src'
    target = tree / 'mmceman/src/mmce_fs.c'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch('mmce_fs.c').encode('utf-8'))
    for name in patches:
        # Committed patches are LF, like the pinned source; a Windows checkout may hold CRLF copies.
        patch = work / name
        patch.write_bytes((root / '.github/patches' / name).read_bytes().replace(b'\r\n', b'\n'))
        subprocess.run(['git', 'apply', str(patch)], cwd=tree, check=True)
    driver = target.read_text()
    return ''.join(function(driver, s) for s in (
        'static int *mmce_fs_find_free_handle(', 'static int mmce_fs_update_unit(',
        'int mmce_fs_dopen(', 'int mmce_fs_dread(',
    ))


cue = (root / 'src/cuesupport.c').read_text()
production = ''.join(function(cue, signature) for signature in (
    'static char cueSep(', 'const char *cueEmberFolder(', 'static int cueResolveEmberFile(',
    'int cueResolveEmber(', 'void cueBuildGamesDir(', 'int cueNameLaunchable(',
    'static int cueNameIsDiscImage(', 'static int cueEntryIsGame(', 'int cueScanDir(',
))
extensions = re.search(r'^static const char \*const cueDiscExts\[\] = \{[^}]*\};', cue, re.M)[0]
header = (root / 'include/cuesupport.h').read_text()
constants = '\n'.join(line for line in header.splitlines() if line.startswith(('#define CUE_', '#define EMBER_')))
constants += '\n#define ISO_GAME_NAME_MAX 160\n'
entry = re.search(r'^typedef struct\s*\{[^}]*\} cue_entry_t;', header, re.M)[0]
cmds = re.sub(r'^#include .*$', '', fetch('mmce_cmds.h'), flags=re.M)
glue = fetch('glue.c')
fileXio = fetch('fileXio_ps2sdk.c')
sdk = (function(glue, 'int __transform_errno(int res) {') + function(glue, 'int getdents(int fd, void *dd_buf, int count)')
       + function(fileXio, 'int __fileXioDreadHelper(void *userdata, struct dirent *dir)'))

program = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* ---- the card: sd2psXtd firmware semantics ---------------------------------------------- */
typedef struct {const char *path; int dir;} node_t;
static node_t tree[] = {
    {"/EMBER", 1}, {"/EMBER/ember.elf", 0}, {"/EMBER/bios.bin", 0}, {"/EMBER/games", 1},
    {"/EMBER/games/Spyro", 1}, {"/EMBER/games/Spyro/Spyro.cue", 0}, {"/EMBER/games/Spyro/Spyro.bin", 0},
    {"/EMBER/games/readme.txt", 0},          /* a loose file: DOPEN on it succeeds on this card */
    {"/EMBER/games/EmptyGroup", 1},          /* a folder holding nothing Ember can mount */
    {"/EMBER/games/Crash", 1}, {"/EMBER/games/Crash/Crash.cue", 0},
};
#define NODES (int)(sizeof(tree) / sizeof(tree[0]))
static int gamesPresent = 1;
static int nodeFind(const char *path) {
    for (int i = 0; i < NODES; i++)
        if (!strcmp(tree[i].path, path) && (gamesPresent || strncmp(path, "/EMBER/games", 12)))
            return i;
    return -1;
}
/* Is child a direct entry of the folder parent? */
static int childOf(int child, int parent) {
    size_t n = strlen(tree[parent].path);
    return !strncmp(tree[child].path, tree[parent].path, n) && tree[child].path[n] == '/' &&
           strchr(tree[child].path + n + 1, '/') == NULL;
}
/* Card file table. Slot 0 stays busy (the card's own memory-card image), as on hardware. */
#define CARD_FILES 16
static struct {int open, node, next;} card[CARD_FILES] = {{1, -1, 0}};
static int cardOpen(const char *path) {
    int node = nodeFind(path);
    if (node < 0) return -1;
    for (int fd = 1; fd < CARD_FILES; fd++)
        if (!card[fd].open) {card[fd].open = 1; card[fd].node = node; card[fd].next = 0; return fd;}
    return -1;
}
/* sd_iterate_dir: the next child, or -1 (end of listing, or the handle is a FILE). */
static int cardIterate(int fd, int *child) {
    if (fd <= 0 || fd >= CARD_FILES || !card[fd].open || !tree[card[fd].node].dir) return -1;
    for (int i = card[fd].next; i < NODES; i++)
        if (childOf(i, card[fd].node) && nodeFind(tree[i].path) >= 0) {card[fd].next = i + 1; *child = i; return fd + 1; /* nonzero iterator id */}
    card[fd].next = NODES;
    return -1;
}

/* ---- the SIO2 wire: mmceman's packets, answered as the firmware answers them ------------- */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef struct {u32 lo, hi;} iop_sys_clock_t;
static iop_sys_clock_t timeout_1s;
@CMDS@
static int failDreadAt = -1, dreads, sio2Locked;
static enum {IDLE, DOPEN_NAME, DOPEN_FD, DREAD_STAT, DREAD_NAME, DREAD_TAIL} wire = IDLE;
static char dopenName[256];
static int dreadChild, dreadIt;
static void mmce_sio2_lock(void) {assert(!sio2Locked); sio2Locked = 1;}
static void mmce_sio2_unlock(void) {assert(sio2Locked); sio2Locked = 0;}
static void mmce_sio2_set_port(int port) {(void)port;}
static int mmce_sio2_tx_rx_pio(u8 tx, u8 rx, u8 *out, u8 *in, iop_sys_clock_t *timeout) {
    (void)timeout;
    if (wire == IDLE) {
        assert(tx >= 4 && out[0] == MMCE_ID);
        if (out[1] == MMCE_CMD_FS_DOPEN) {in[1] = MMCE_REPLY_CONST; wire = DOPEN_NAME; return 0;}
        assert(out[1] == MMCE_CMD_FS_DREAD && tx == 5 && rx == 5);
        if (dreads++ == failDreadAt) return -1; /* bus timeout waiting for /ACK */
        in[1] = MMCE_REPLY_CONST;
        int it = cardIterate(out[3], &dreadChild);
        in[4] = it < 0; /* ps2_mmceman_cmd_fs_dread: mc_respond(0x1) when the iterator fails */
        dreadIt = it;
        wire = it < 0 ? IDLE : DREAD_STAT;
        return 0;
    }
    switch (wire) {
    case DOPEN_NAME: snprintf(dopenName, sizeof(dopenName), "%s", (const char *)out); wire = DOPEN_FD; return 0;
    case DOPEN_FD: {int fd = cardOpen(dopenName); in[1] = fd < 0 ? 0xff : (u8)fd; wire = IDLE; return 0;}
    case DREAD_STAT: {
        const char *name = strrchr(tree[dreadChild].path, '/') + 1;
        u32 mode = tree[dreadChild].dir ? 0x1000 : 0x2000; /* FIO_S_IFDIR / FIO_S_IFREG */
        memset(in, 0, rx);
        in[1] = mode >> 24; in[2] = mode >> 16; in[3] = mode >> 8; in[4] = mode;
        in[0x29] = (u8)(strlen(name) + 1);
        wire = DREAD_NAME; return 0;
    }
    case DREAD_NAME: memcpy(in, strrchr(tree[dreadChild].path, '/') + 1, rx); wire = DREAD_TAIL; return 0;
    case DREAD_TAIL: in[1] = (u8)dreadIt; wire = IDLE; return 0;
    default: assert(0); return -1;
    }
}

/* ---- the pinned mmceman driver, patched as the installer patches it ---------------------- */
typedef struct {u32 mode, attr, size; u8 ctime[8], atime[8], mtime[8]; u32 hisize, priv[6];} iox_stat_t;
typedef struct {iox_stat_t stat; char name[256]; void *unknown;} iox_dirent_t;
typedef struct {int mode; int unit; void *device; void *privdata;} iomanX_iop_file_t;
#define DPRINTF(...) ((void)0)
#define MMCE_FS_MAX_FD 16
static int mmce_fs_fds[MMCE_FS_MAX_FD];
static int last_unit = -1;
@DRIVER@

/* ---- iomanX + fileXio RPC: the driver's return value travels to the EE unchanged --------- */
static iomanX_iop_file_t iopFiles[8];
static int fileXioDread(int fd, iox_dirent_t *dirent) {return mmce_fs_dread(&iopFiles[fd], dirent);}
static int __fileXioGetFdHelper(void *userdata) {return (int)(intptr_t)userdata;}
#define FIO_S_IFMT 0xF000
#define FIO_S_IFLNK 0x4000
#define FIO_S_IFREG 0x2000
#define FIO_S_IFDIR 0x1000
#define DT_UNKNOWN 0
#define DT_DIR 4
#define DT_REG 8
#define DT_LNK 10
struct sdk_dirent {long d_fileno; unsigned short d_reclen; unsigned char d_type; char d_name[256];};
#define dirent sdk_dirent
typedef struct {int (*dread)(void *userdata, struct dirent *dir);} fd_ops_t;
typedef struct {fd_ops_t *ops; void *userdata;} _libcglue_fdman_fd_info_t;
typedef struct {_libcglue_fdman_fd_info_t info;} descriptor_t;
static descriptor_t descriptors[8];
static descriptor_t *__descriptormap[8];
@SDK@
#undef dirent

/* ---- newlib's opendir/readdir/closedir over that glue ------------------------------------ */
static fd_ops_t fileXioDirOps = {__fileXioDreadHelper};
typedef struct {int fd; struct sdk_dirent entry;} host_DIR;
static int openDirs;
static const char *local(const char *path) {const char *c = strchr(path, ':'); assert(c); return c + 1;}
static host_DIR *host_opendir(const char *path) {
    assert(!strncmp(path, "mmce0:", 6));
    int fd;
    for (fd = 3; fd < 8 && iopFiles[fd].privdata != NULL; fd++) ;
    assert(fd < 8);
    iopFiles[fd].unit = 0;
    int rv = mmce_fs_dopen(&iopFiles[fd], local(path));
    if (rv < 0) {errno = -rv; return NULL;} /* libcglue: __transform_errno */
    descriptors[fd].info.ops = &fileXioDirOps; descriptors[fd].info.userdata = (void *)(intptr_t)fd;
    __descriptormap[fd] = &descriptors[fd];
    host_DIR *dir = calloc(1, sizeof(*dir)); assert(dir); dir->fd = fd; openDirs++;
    return dir;
}
static struct sdk_dirent *host_readdir(host_DIR *dir) {
    /* newlib readdir.c: dd_size = getdents(...); if (dd_size <= 0) return NULL; */
    return getdents(dir->fd, &dir->entry, sizeof(dir->entry)) <= 0 ? NULL : &dir->entry;
}
static int host_closedir(host_DIR *dir) {
    int slot = *(int *)iopFiles[dir->fd].privdata;
    card[slot].open = 0; *(int *)iopFiles[dir->fd].privdata = -1; iopFiles[dir->fd].privdata = NULL;
    __descriptormap[dir->fd] = NULL; free(dir); openDirs--;
    return 0;
}
static int host_stat(const char *path, struct stat *st) {
    int node = nodeFind(local(path));
    if (node < 0) {errno = ENOENT; return -1;}
    memset(st, 0, sizeof(*st)); st->st_mode = tree[node].dir ? S_IFDIR : S_IFREG; return 0;
}
static int host_open(const char *path, int flags) {
    int node = nodeFind(local(path)); (void)flags;
    if (node < 0 || tree[node].dir) {errno = ENOENT; return -1;}
    return 3;
}
#define LOG(...) ((void)0)
#define O_RDONLY 0
#define open host_open
#define close(fd) ((void)(fd))
#define opendir host_opendir
#define readdir host_readdir
#define closedir host_closedir
#define stat(...) host_stat(__VA_ARGS__)
#define DIR host_DIR
#define dirent sdk_dirent
@CONSTANTS@
@ENTRY@
@EXTENSIONS@
@PRODUCTION@
#undef stat
#undef dirent

static int scan(const char *label, int want) {
    cue_entry_t *games = NULL;
    dreads = 0;
    int count = cueScanDir("mmce0:/", &games);
    int ok = count == want && openDirs == 0 && !sio2Locked;
    if (ok && want == 2)
        ok = (!strcmp(games[0].name, "Spyro") && !strcmp(games[1].name, "Crash")) ||
             (!strcmp(games[0].name, "Crash") && !strcmp(games[1].name, "Spyro"));
    printf("%s %s: cueScanDir=%d (want %d)\n", ok ? "ok  " : "FAIL", label, count, want);
    free(games);
    return ok;
}
int main(int argc, char **argv) {
    memset(mmce_fs_fds, -1, sizeof(mmce_fs_fds)); /* mmce_fs_init */
    if (argc > 1 && !strcmp(argv[1], "baseline"))
        return scan("unpatched dread: Spyro + Crash beside a loose file and an empty group", 2) ? 0 : 1;
    int ok = scan("Spyro + Crash beside a loose file and an empty group", 2);
    failDreadAt = 1; /* dread 0 lists Spyro, dread 1 is the image probe inside Spyro/ */
    ok &= scan("SIO2 timeout inside a game folder keeps the last-good list", -1);
    failDreadAt = 2; /* dread 2 is the games listing's next entry */
    ok &= scan("SIO2 timeout during the games listing keeps the last-good list", -1);
    failDreadAt = -1;
    gamesPresent = 0;
    ok &= scan("no EMBER/games folder is an empty library", 0);
    return ok ? 0 : 1;
}
'''


def build(work, patches, name):
    work.mkdir()
    c = work / (name + '.c')
    c.write_text(program.replace('@CMDS@', cmds).replace('@DRIVER@', patched_driver(work, patches))
                 .replace('@SDK@', sdk).replace('@CONSTANTS@', constants).replace('@ENTRY@', entry)
                 .replace('@EXTENSIONS@', extensions).replace('@PRODUCTION@', production))
    exe = work / name
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-Wno-unused-parameter', '-Wno-format-truncation', '-Wno-pointer-sign',
                    '-Wno-discarded-qualifiers', '-Wno-sign-compare', str(c), '-o', str(exe)], check=True)
    return exe


with tempfile.TemporaryDirectory(prefix='ember-mmce-') as temp:
    work = Path(temp)
    baseline = build(work / 'baseline', PATCHES[:-1], 'scan')
    result = subprocess.run([str(baseline), 'baseline'], timeout=30)
    assert result.returncode != 0, 'the unpatched driver lists Ember on MMCE: this test no longer sees the defect'
    print('baseline (without mmceman-fs-dread-eof.patch) fails as expected: every MMCE listing ends in EPERM')
    patched = build(work / 'patched', PATCHES, 'scan')
    subprocess.run([str(patched)], check=True, timeout=30)
print('Ember on MMCE: games list through the real mmceman dread; SIO2 timeouts still preserve the list')
