"""Run the Ember scanner and SDK dopen on real disposable FAT32/exFAT images.

Uses the same hash-pinned SDK/FatFs inputs as the native VMC image regression.
The host adapter preserves fs_dopen's raw negative FRESULT -> newlib errno
conversion, including FR_NO_PATH (5) becoming EIO for a regular file.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, help='Cache containing the pinned source paths')
parser.add_argument('--ref', help='Read the Ember scanner from this git ref for a before/after check')
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('installer', root / '.github/scripts/install_safe_bdmfs.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


cue = (root / 'src/cuesupport.c').read_text()
if args.ref:
    cue = subprocess.check_output(['git', 'show', args.ref + ':src/cuesupport.c'], cwd=root, text=True)
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

program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include "ff.h"
#include "diskio.h"
typedef DIR FF_DIR;
static unsigned char *disk;
static const unsigned int sectors = 131072;
DSTATUS disk_initialize(BYTE n) {(void)n;return 0;}
DSTATUS disk_status(BYTE n) {(void)n;return 0;}
DRESULT disk_read(BYTE n, BYTE *out, LBA_t sector, UINT count) {
    (void)n;if(sector>=sectors||count>sectors-sector)return RES_ERROR;
    memcpy(out,disk+(size_t)sector*512,(size_t)count*512);return RES_OK;
}
DRESULT disk_write(BYTE n, const BYTE *in, LBA_t sector, UINT count) {
    (void)n;if(sector>=sectors||count>sectors-sector)return RES_ERROR;
    memcpy(disk+(size_t)sector*512,in,(size_t)count*512);return RES_OK;
}
DRESULT disk_ioctl(BYTE n, BYTE cmd, void *out) {
    (void)n;
    switch(cmd) {
    case CTRL_SYNC:return RES_OK;
    case GET_SECTOR_COUNT:*(LBA_t*)out=sectors;return RES_OK;
    case GET_SECTOR_SIZE:*(WORD*)out=512;return RES_OK;
    case GET_BLOCK_SIZE:*(DWORD*)out=1;return RES_OK;
    default:return RES_PARERR;
    }
}
DWORD get_fattime(void) {return (2026-1980U)<<25|10U<<21|19U<<16;}
int ff_mutex_create(int n) {(void)n;return 1;}
void ff_mutex_delete(int n) {(void)n;}
int ff_mutex_take(int n) {(void)n;return 1;}
void ff_mutex_give(int n) {(void)n;}

/* Build the pinned SDK dopen verbatim; only IOP locking and volume/slot
 * bookkeeping are replaced. The actual f_opendir and error return run here. */
typedef struct {const char *name;} iop_device_t;
typedef struct {iop_device_t *device;int unit;void *privdata;} iop_file_t;
static iop_device_t device = {"mass"};
#define M_DEBUG(...) ((void)0)
#define _fs_lock() ((void)0)
#define _fs_unlock() ((void)0)
static int fs_driver_resolve_volume(const char *name, int unit) {
    assert(!strcmp(name,"mass")&&unit==0);return 0;
}
static FF_DIR directorySlots[16];
static FF_DIR *fs_find_free_dir_structure(void) {
    for(unsigned int i=0;i<sizeof(directorySlots)/sizeof(directorySlots[0]);i++)
        if(directorySlots[i].obj.fs==NULL)return &directorySlots[i];
    return NULL;
}
#define FATFS_FS_DRIVER_NAME_ALLOC_ON_STACK_DEFINITIONS(name) char converted[384];const char *modified_##name=converted
#define FATFS_FS_DRIVER_NAME_ALLOC_ON_STACK_IMPLEMENTATION(name,vol) snprintf(converted,sizeof(converted),"%d:%s",vol,name)
@SDK_DOPEN@

struct host_dirent {char d_name[256];};
typedef struct {FF_DIR *dir;struct host_dirent entry;} host_DIR;
static int injectDirectoryError;
static const char *local(const char *path) {
    const char *colon=strchr(path,':');assert(colon);return colon+1;
}
static void fatPath(const char *path, char *out) {snprintf(out,384,"0:%s",local(path));}
static host_DIR *host_opendir(const char *path) {
    if(injectDirectoryError&&strstr(path,"/Spyro")) {errno=EIO;return NULL;}
    iop_file_t file={&device,0,NULL};
    int result=fs_dopen(&file,local(path));
    if(result<0) {errno=-result;return NULL;}
    host_DIR *dir=calloc(1,sizeof(*dir));assert(dir);dir->dir=file.privdata;return dir;
}
static struct host_dirent *host_readdir(host_DIR *dir) {
    FILINFO info;
    FRESULT result=f_readdir(dir->dir,&info);
    assert(result==FR_OK); /* This fixture's images have no read faults. */
    if(!info.fname[0])return NULL;
    snprintf(dir->entry.d_name,sizeof(dir->entry.d_name),"%s",info.fname);return &dir->entry;
}
static int host_closedir(host_DIR *dir) {
    assert(f_closedir(dir->dir)==FR_OK);free(dir);return 0;
}
static int host_stat(const char *path, struct stat *st) {
    FILINFO info;char name[384];fatPath(path,name);
    FRESULT result=f_stat(name,&info);
    if(result!=FR_OK) {errno=result;return -1;}
    memset(st,0,sizeof(*st));st->st_mode=(info.fattrib&AM_DIR)?S_IFDIR:S_IFREG;return 0;
}
static int host_open(const char *path, int flags) {
    FIL file;char name[384];(void)flags;fatPath(path,name);
    FRESULT result=f_open(&file,name,FA_READ);
    if(result!=FR_OK) {errno=result;return -1;}
    assert(f_close(&file)==FR_OK);return 3;
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
#define dirent host_dirent
@CONSTANTS@
@ENTRY@
@EXTENSIONS@
@PRODUCTION@
#undef stat

static void create(const char *name) {
    FIL file;assert(f_open(&file,name,FA_CREATE_NEW|FA_WRITE)==FR_OK);assert(f_close(&file)==FR_OK);
}
static int checkScan(const char *prefix, int want) {
    cue_entry_t *games=NULL;
    int count=cueScanDir(prefix,&games);
    int ok=count==want&&(want<=0||!strcmp(games[0].name,"Spyro"));
    if(!ok)fprintf(stderr,"FAIL %s count=%d expected=%d\n",prefix,count,want);
    free(games);return ok;
}
static int run(BYTE format) {
    FATFS fs;unsigned char work[4096];
    MKFS_PARM options={.fmt=format|FM_SFD,.n_fat=1,.align=1,.n_root=512,.au_size=512};
    memset(disk,0,(size_t)sectors*512);
    assert(f_mkfs("0:",&options,work,sizeof(work))==FR_OK);
    assert(f_mount(&fs,"0:",1)==FR_OK);
    assert(f_mkdir("0:/EMBER")==FR_OK);create("0:/EMBER/ember.elf");
    assert(f_mkdir("0:/EMBER/games")==FR_OK);
    assert(f_mkdir("0:/EMBER/games/Spyro")==FR_OK);
    create("0:/EMBER/games/Spyro/Spyro.cue");create("0:/EMBER/games/Spyro/Spyro.bin");
    if(!checkScan("mass0:/",1))return 0;
    printf("Ember %s: clean Spyro layout lists; checking loose files next\n",format==FM_EXFAT?"exFAT":"FAT32");
    /* A regular file under games/ must not poison the entire library. */
    create("0:/EMBER/games/readme.txt");create("0:/EMBER/games/.DS_Store");
    FF_DIR probe;
    assert(f_opendir(&probe,"0:/EMBER/games/readme.txt")==FR_NO_PATH);
    assert(FR_NO_PATH==5&&EIO==5);
    if(!checkScan("mass0:/",1)||!checkScan("ata:/",1))return 0;
    assert(f_mkdir("0:/EMBER/games/EmptyGroup")==FR_OK);
    if(!checkScan("mass0:/",1))return 0;
    /* Successful stat of a DIRECTORY must not swallow a real dopen failure. */
    injectDirectoryError=1;
    if(!checkScan("mass0:/",-1))return 0;
    injectDirectoryError=0;
    assert(f_mount(NULL,"0:",0)==FR_OK);
    printf("Ember %s: Spyro lists with loose files; typed/legacy paths and directory-I/O failure pass\n",format==FM_EXFAT?"exFAT":"FAT32");
    return 1;
}
int main(void) {
    disk=malloc((size_t)sectors*512);assert(disk);
    int fat32=run(FM_FAT32), exfat=run(FM_EXFAT);free(disk);return fat32&&exfat?0:1;
}
'''
with tempfile.TemporaryDirectory(prefix='ember-fatfs-') as temp:
    build = Path(temp)
    for item in json.loads((root / '.github/patches/bdmfs-vmc-sources.json').read_text()):
        if item['group'] != 'fatfs' and not item['path'].endswith('fs_driver.c'):
            continue
        target = build / Path(item['path']).name
        if args.source:
            source = args.source / item['path']
            assert hashlib.sha256(source.read_bytes()).hexdigest() == item['sha256'], item['path']
            shutil.copyfile(source, target)
        else:
            installer.download(item, target)
    sdk = (build / 'fs_driver.c').read_text()
    config = build / 'ffconf.h'
    config.write_text(re.sub(r'(#define FF_USE_MKFS\s+)0\b', r'\g<1>1', config.read_text()))
    (build / 'module_debug.h').write_text('#include <stdint.h>\ntypedef uint64_t u64;\n#define M_DEBUG(...) ((void)0)\n#define M_PRINTF(...) ((void)0)\n#define DEBUG_U64_2XU32(x) ((void)(x))\n')
    c = build / 'scan.c'
    c.write_text(program.replace('@SDK_DOPEN@', function(sdk, 'static int fs_dopen('))
                 .replace('@CONSTANTS@', constants).replace('@ENTRY@', entry)
                 .replace('@EXTENSIONS@', extensions).replace('@PRODUCTION@', production))
    exe = build / 'scan'
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-Wno-format-truncation', '-I', str(build),
                    str(c), str(build / 'ff.c'), str(build / 'ffunicode.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)
