"""Rebuild a really fragmented card on disposable FAT32/exFAT images (#986).

The pinned FatFs, the shipped fragment walker and allocation patch, genvmc's real request/worker/copy
code and the EE's real start/finish (src/vmcrebuild.c with bdmsupport.c's launch layout check) run
together. A card is written interleaved with other files so it lands in many pieces; the launch check
calls it fragmented. With no 8 MiB run free the rebuild says so and changes nothing. With room, the
card ends up as one extent with every byte the same, and the old card survives a remount as .bak.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, help='Local pinned FatFs source directory; otherwise fetch hash-verified inputs')
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('installer', root / '.github/scripts/install_safe_bdmfs.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

genvmc = (root / 'modules/vmc/genvmc/genvmc.c').read_text(encoding='utf-8')
rebuild = (root / 'src/vmcrebuild.c').read_text(encoding='utf-8')
bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8')


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start) + 3]


start = genvmc.index('// SONY superblock magic')
iop = genvmc[start:genvmc.index('static int genvmc_io_sema', start)]
start = genvmc.index('static int genvmc_io_sema')
iop += genvmc[start:genvmc.index('\n//----', start)] + '\n'
for signature in ('static int mc_writecluster(', 'static int vmc_open_contiguous(', 'static int vmc_reserve_pfs(',
                  'static int vmc_rebuild(char *filename'):
    iop += function(genvmc, signature)
iop += r'''
static int vmc_mcformat(char *filename, int size_kb, int blocksize, int *progress, char *msg)
{ (void)filename; (void)size_kb; (void)blocksize; (void)progress; (void)msg; assert(!"a rebuild never formats"); return -1; }
static int vmc_mccopy(char *filename, int slot, int *progress, char *msg)
{ (void)filename; (void)slot; (void)progress; (void)msg; assert(!"a rebuild never reads a memory card"); return -1; }
'''
iop += genvmc[genvmc.index('static int genvmc_init(iop_device_t *dev)\n{'):genvmc.index('int _start(')]
ee = rebuild[rebuild.index('static struct\n{'):]
layout = function(bdm, 'int bdmCheckNativeVmcLayout(int iop_fd')

program = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "ff.h"
#include "diskio.h"
#include "vmc_alloc.h"
#include "genvmc.h"
#include "nativevmc.h"
#include "vmcrebuild.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef int16_t s16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct {u64 sector; unsigned int count;} bd_fragment_t;
struct block_device {u64 sectorOffset;};
static struct block_device device;
static unsigned char *disk;
static const unsigned int sectors = 131072;
static struct block_device *fatfs_fs_driver_get_mounted_bd_from_index(unsigned int n) {(void)n; return &device;}
#define M_DEBUG(...) ((void)0)
#define DEBUG_U64_2XU32(x) ((void)0)
DSTATUS disk_initialize(BYTE n) {(void)n; return 0;}
DSTATUS disk_status(BYTE n) {(void)n; return 0;}
DRESULT disk_read(BYTE n, BYTE *out, LBA_t sector, UINT count)
{
    (void)n; if (sector >= sectors || count > sectors - sector) return RES_ERROR;
    memcpy(out, disk + (size_t)sector * 512, (size_t)count * 512); return RES_OK;
}
DRESULT disk_write(BYTE n, const BYTE *in, LBA_t sector, UINT count)
{
    (void)n; if (sector >= sectors || count > sectors - sector) return RES_ERROR;
    memcpy(disk + (size_t)sector * 512, in, (size_t)count * 512); return RES_OK;
}
DRESULT disk_ioctl(BYTE n, BYTE cmd, void *out)
{
    (void)n;
    switch (cmd) {
    case CTRL_SYNC: return RES_OK;
    case GET_SECTOR_COUNT: *(LBA_t *)out = sectors; return RES_OK;
    case GET_SECTOR_SIZE: *(WORD *)out = 512; return RES_OK;
    case GET_BLOCK_SIZE: *(DWORD *)out = 1; return RES_OK;
    default: return RES_PARERR;
    }
}
DWORD get_fattime(void) {return (2026 - 1980U) << 25 | 10U << 21 | 20U << 16;}
int ff_mutex_create(int n) {(void)n; return 1;}
void ff_mutex_delete(int n) {(void)n;}
int ff_mutex_take(int n) {(void)n; return 1;}
void ff_mutex_give(int n) {(void)n;}
@WALKER@
@ALLOCATION@

#define O_RDONLY 0
#define O_RDWR 2
#define O_CREAT 0x200
#define O_TRUNC 0x400
#define FIO_O_EXCL 0x800
#define SEEK_SET 0
#define SEEK_END 2
#define PIOCALLOC 0x7001
#define DPRINTF(...) ((void)0)
#define LOG(...) ((void)0)
#define MODNAME "genvmc"
#define TH_C 0x02000000
#define IOP_MUTEX_UNLOCKED 1
#define CARD (8 * 1048576U)
typedef struct iop_device { int unused; } iop_device_t;
typedef struct iop_file { int unused; } iop_file_t;
typedef struct { unsigned int attr, option; void *thread; unsigned int stacksize, priority; } iop_thread_t;
typedef struct { unsigned int mode; char name[256]; } iox_dirent_t;

/* ---- the bdmfs file calls genvmc and the EE make, straight onto FatFs ---- */
static FIL fil[4];
static int fused[4];
static int fs_open(const char *name, int flags)
{
    BYTE mode = flags == O_RDONLY ? FA_READ : (flags & FIO_O_EXCL) ? FA_CREATE_NEW | FA_READ | FA_WRITE : FA_CREATE_ALWAYS | FA_READ | FA_WRITE;
    for (int i = 0; i < 4; i++)
        if (!fused[i]) {
            FRESULT r = f_open(&fil[i], name, mode);
            if (r != FR_OK)
                return r == FR_EXIST ? -EEXIST : -ENOENT;
            fused[i] = 1;
            return i;
        }
    return -EMFILE;
}
static FIL *fs_fil(int fd) { assert(fd >= 0 && fd < 4 && fused[fd]); return &fil[fd]; }
static int fs_close(int fd) { FRESULT r = f_close(fs_fil(fd)); fused[fd] = 0; return r == FR_OK ? 0 : -EIO; }
static int fs_read(int fd, void *buf, int n) { UINT got; return f_read(fs_fil(fd), buf, n, &got) == FR_OK ? (int)got : -EIO; }
static int fs_write(int fd, const void *buf, int n) { UINT put; return f_write(fs_fil(fd), buf, n, &put) == FR_OK ? (int)put : -EIO; }
static int fs_lseek(int fd, int offset, int whence)
{
    FIL *f = fs_fil(fd);
    if (whence == SEEK_END)
        offset += (int)f_size(f);
    return f_lseek(f, offset) == FR_OK ? offset : -EIO;
}
static int fs_remove(const char *name) { return f_unlink(name) == FR_OK ? 0 : -EIO; }
static int fs_devctl(const char *name, unsigned int cmd, void *in, int insize, void *out, int outsize)
{
    (void)name; (void)in; (void)out;
    assert(cmd == VMC_ALLOC_CAPS && insize == 0 && outsize == 0);
    return VMC_ALLOC_V1;
}
static int fs_ioctl2(int fd, unsigned int cmd, void *in, unsigned int insize, void *out, int outsize)
{
    assert(cmd == VMC_ALLOC_RESERVE || cmd == VMC_ALLOC_VERIFY);
    assert(insize == sizeof(vmc_alloc_request_t) && out == NULL && outsize == 0);
    return vmc_allocate_contiguous(fs_fil(fd), in, cmd == VMC_ALLOC_RESERVE);
}

static int semTokens[8], semCount;
static int CreateMutex(int tokens) { semTokens[semCount] = tokens; return semCount++; }
static int DeleteSema(int id) { (void)id; return 0; }
static int WaitSema(int id) { assert(semTokens[id] > 0); semTokens[id]--; return 0; }
static int SignalSema(int id) { semTokens[id]++; return 0; }
static void (*pending)(void *);
static int CreateThread(iop_thread_t *t) { pending = (void (*)(void *))t->thread; return 7; }
static int StartThread(int thid, void *arg) { (void)thid; (void)arg; return 0; }
static int DeleteThread(int thid) { (void)thid; pending = NULL; return 0; }
static void ExitDeleteThread(void) {}

#define open fs_open
#define close fs_close
#define lseek fs_lseek
#define read fs_read
#define write fs_write
#define remove fs_remove
#define devctl fs_devctl
#define ioctl2 fs_ioctl2
@IOP@
#undef open
#undef close
#undef lseek
#undef read
#undef write
#undef remove
#undef devctl
#undef ioctl2

/* ---- EE fileXio: the bdmfs ioctls the launch uses, and directory reads ---- */
#define USBMASS_IOCTL_GET_LBA 1
#define USBMASS_IOCTL_GET_FRAGLIST 2
static int ee_open(const char *name, int flags) { assert(flags == O_RDONLY); return fs_open(name, flags); }
static int ps2sdk_get_iop_fd(int fd) { return fd; }
static int fileXioIoctl2(int fd, int cmd, void *in, unsigned int insize, void *out, unsigned int outsize)
{
    FIL *f = fs_fil(fd);
    (void)in; (void)insize;
    if (cmd == USBMASS_IOCTL_GET_LBA) {
        assert(outsize == sizeof(u64));
        *(u64 *)out = clst2sect(f->obj.fs, f->obj.sclust) + device.sectorOffset;
        return 0;
    }
    assert(cmd == USBMASS_IOCTL_GET_FRAGLIST);
    return get_frag_list(f, out, outsize);
}
@LAYOUT@
static int hddVMCMapFits(const char *path) { (void)path; assert(!"not a PFS card"); return -1; }
static int ee_rename(const char *from, const char *to) { return f_rename(from, to) == FR_OK ? 0 : -1; }
static int ee_unlink(const char *name) { return f_unlink(name) == FR_OK ? 0 : -1; }
static DIR folder;
static int fileXioDopen(const char *path) { return f_opendir(&folder, path) == FR_OK ? 5 : -ENOENT; }
static int fileXioDread(int dir, iox_dirent_t *entry)
{
    FILINFO info;
    assert(dir == 5);
    if (f_readdir(&folder, &info) != FR_OK)
        return -EIO;
    if (info.fname[0] == '\0')
        return 0;
    snprintf(entry->name, sizeof(entry->name), "%s", info.fname);
    return 1;
}
static int fileXioDclose(int dir) { assert(dir == 5); return f_closedir(&folder) == FR_OK ? 0 : -EIO; }
static int fileXioSync(const char *device, int flag) { (void)device; (void)flag; assert(!"no PFS here"); return -1; }
static int fileXioDevctl(const char *name, int cmd, void *in, unsigned int insize, void *out, unsigned int outsize)
{
    assert(!strcmp(name, "genvmc:"));
    return genvmc_devctl(NULL, name, cmd, in, insize, out, outsize);
}
#define open ee_open
#define close fs_close
#define rename ee_rename
#define unlink ee_unlink
@EE@
#undef open
#undef close
#undef rename
#undef unlink

static unsigned char pattern(unsigned int offset) { return (unsigned char)(offset * 13 + (offset >> 11)); }
static int exists(const char *name) { FILINFO info; return f_stat(name, &info) == FR_OK; }
static void verifyBytes(const char *name)
{
    static unsigned char buf[65536];
    FIL f; UINT got;
    assert(f_open(&f, name, FA_READ) == FR_OK && f_size(&f) == CARD);
    for (unsigned int offset = 0; offset < CARD; offset += sizeof(buf)) {
        assert(f_read(&f, buf, sizeof(buf), &got) == FR_OK && got == sizeof(buf));
        for (unsigned int i = 0; i < sizeof(buf); i++)
            assert(buf[i] == pattern(offset + i));
    }
    assert(f_close(&f) == FR_OK);
}
static int fragments(const char *name)
{
    FIL f;
    assert(f_open(&f, name, FA_READ) == FR_OK);
    int count = get_frag_list(&f, NULL, 0);
    assert(f_close(&f) == FR_OK);
    return count;
}
static int rebuildCard(void)
{
    statusVMCparam_t status;
    int started = vmcRebuildStart("0:/VMC/card.bin", 8);
    if (started != 0)
        return started;
    void (*entry)(void *) = pending;
    pending = NULL;
    assert(entry);
    entry(NULL);
    assert(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_STATUS, NULL, 0, &status, sizeof(status)) == 0);
    assert(status.VMC_status == GENVMC_STAT_AVAIL);
    return vmcRebuildFinish(status.VMC_error);
}

static void run(BYTE format)
{
    FATFS fs; FIL card, filler; UINT written;
    unsigned char work[4096];
    static unsigned char chunk[65536];
    char name[32];
    MKFS_PARM options = {.fmt = format | FM_SFD, .n_fat = 1, .align = 1, .n_root = 512, .au_size = 512};
    memset(disk, 0, (size_t)sectors * 512);
    memset(&gVMCRebuild, 0, sizeof(gVMCRebuild));
    memset(&genvmc_stats, 0, sizeof(genvmc_stats));
    semCount = 0;
    genvmc_init(NULL);
    assert(f_mkfs("0:", &options, work, sizeof(work)) == FR_OK);
    assert(f_mount(&fs, "0:", 1) == FR_OK);
    assert(f_mkdir("0:/VMC") == FR_OK);

    /* A card written 64 KiB at a time between other files: it lands in many pieces. */
    assert(f_open(&card, "0:/VMC/card.bin", FA_CREATE_NEW | FA_WRITE) == FR_OK);
    for (unsigned int offset = 0, i = 0; offset < CARD; offset += sizeof(chunk), i++) {
        for (unsigned int j = 0; j < sizeof(chunk); j++)
            chunk[j] = pattern(offset + j);
        assert(f_write(&card, chunk, sizeof(chunk), &written) == FR_OK && written == sizeof(chunk));
        assert(f_sync(&card) == FR_OK);
        snprintf(name, sizeof(name), "0:/g%03u.bin", i);
        assert(f_open(&filler, name, FA_CREATE_NEW | FA_WRITE) == FR_OK);
        assert(f_write(&filler, chunk, sizeof(chunk), &written) == FR_OK && written == sizeof(chunk));
        assert(f_close(&filler) == FR_OK);
    }
    assert(f_close(&card) == FR_OK);
    assert(fragments("0:/VMC/card.bin") > 100);
    verifyBytes("0:/VMC/card.bin");
    assert(vmcRebuildLayout("0:/VMC/card.bin", 8) == 0); /* the launch check: fragmented, so offered */

    /* No 8 MiB run anywhere (4 MiB holes in the rest of the disk, the last file kept so the tail
       stays short): say so, change nothing. 4 MiB, not smaller: exFAT grows the root directory a
       cluster at a time between new files, which would chop up the space freed below. */
    int files = 0;
    for (int i = 0; i < 128; i++) {
        snprintf(name, sizeof(name), "0:/h%03d.bin", i);
        assert(f_open(&filler, name, FA_CREATE_NEW | FA_WRITE) == FR_OK);
        FRESULT result = f_expand(&filler, 4 * 1048576, 1);
        assert(f_close(&filler) == FR_OK);
        if (result == FR_DENIED) { assert(f_unlink(name) == FR_OK); break; }
        assert(result == FR_OK);
        files++;
    }
    assert(files > 6);
    for (int i = 0; i < files - 1; i += 2) {
        snprintf(name, sizeof(name), "0:/h%03d.bin", i);
        assert(f_unlink(name) == FR_OK);
    }
    assert(rebuildCard() == VMC_REBUILD_NO_ROOM && genvmc_stats.VMC_error == -112);
    assert(!exists("0:/VMC/card.new") && !exists("0:/VMC/card.bak"));
    verifyBytes("0:/VMC/card.bin");
    assert(fragments("0:/VMC/card.bin") > 100);

    /* Room again: the card is rebuilt in one piece, every byte the same, the old card kept. */
    for (int i = 1; i < files; i += 2) {
        snprintf(name, sizeof(name), "0:/h%03d.bin", i);
        assert(f_unlink(name) == FR_OK);
    }
    if ((files - 1) % 2 == 0) { /* the kept last file */
        snprintf(name, sizeof(name), "0:/h%03d.bin", files - 1);
        assert(f_unlink(name) == FR_OK);
    }
    assert(rebuildCard() == VMC_REBUILD_DONE);
    assert(!exists("0:/VMC/card.new"));
    assert(f_mount(NULL, "0:", 0) == FR_OK);
    assert(f_mount(&fs, "0:", 1) == FR_OK);
    assert(fragments("0:/VMC/card.bin") == 1);
    assert(vmcRebuildLayout("0:/VMC/card.bin", 8) == 1); /* the launch would map it now */
    verifyBytes("0:/VMC/card.bin");
    assert(fragments("0:/VMC/card.bak") > 100);
    verifyBytes("0:/VMC/card.bak");

    /* A second rebuild never touches the backup the first one left. */
    assert(rebuildCard() == VMC_REBUILD_LEFTOVER);
    verifyBytes("0:/VMC/card.bak");
    assert(f_mount(NULL, "0:", 0) == FR_OK);
    printf("FatFs image: %s fragmented card refused without room, rebuilt to one extent with identical bytes, backup kept across remount\n",
           format == FM_EXFAT ? "exFAT" : "FAT32");
}

int main(void)
{
    disk = malloc((size_t)sectors * 512);
    assert(disk);
    run(FM_FAT32);
    run(FM_EXFAT);
    free(disk);
    return 0;
}
'''
walker = (root / '.github/patches/bdmfs-vmc-fragment-walk.c').read_text()
allocation = (root / '.github/patches/bdmfs-vmc-allocation.c').read_text()
with tempfile.TemporaryDirectory() as temp:
    build = Path(temp)
    for entry in json.loads((root / '.github/patches/bdmfs-vmc-sources.json').read_text()):
        if entry['group'] != 'fatfs':
            continue
        target = build / Path(entry['path']).name
        if args.source:
            shutil.copyfile(args.source / entry['path'].removeprefix('source/'), target)
        else:
            installer.download(entry, target)
    (build / 'module_debug.h').write_text('#include <stdint.h>\ntypedef uint64_t u64;\n#define M_DEBUG(...) ((void)0)\n#define M_PRINTF(...) ((void)0)\n#define DEBUG_U64_2XU32(x) ((void)0)\n')
    config = build / 'ffconf.h'
    text = config.read_text()
    for option in ('FF_USE_MKFS', 'FF_USE_EXPAND'):
        text, changed = re.subn(r'(#define ' + option + r'\s+)[01]\b', r'\g<1>1', text)
        assert changed == 1
    config.write_text(text)
    # MinGW defines _WIN32 but the library's VC-only integer branch is not GCC.
    header = build / 'ff.h'
    header.write_text(header.read_text().replace('#if defined(_WIN32)', '#if defined(_MSC_VER)'))
    c, exe = build / 'rebuild.c', build / 'rebuild.exe'
    c.write_text(program.replace('@WALKER@', walker).replace('@ALLOCATION@', allocation)
                 .replace('@IOP@', iop).replace('@EE@', ee).replace('@LAYOUT@', layout), encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter',
                    '-Wno-sign-compare', '-Wno-unused-const-variable', '-Wno-format-truncation',
                    '-I', str(build), '-I', str(root / 'include'), '-I', str(root / 'modules/vmc/genvmc'),
                    str(c), str(build / 'ff.c'), str(build / 'ffunicode.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=180)
