"""Exercise the pinned FatFs and production guards on disposable FAT32/exFAT images."""
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
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "ff.h"
#include "diskio.h"
#include "vmc_alloc.h"
typedef uint64_t u64;
typedef struct {u64 sector; unsigned int count;} bd_fragment_t;
struct block_device {u64 sectorOffset;};
static struct block_device device;
static unsigned char *disk;
static const unsigned int sectors=131072;
static int failSync;
static struct block_device *fatfs_fs_driver_get_mounted_bd_from_index(unsigned int n) {(void)n;return &device;}
#define M_DEBUG(...) ((void)0)
#define DEBUG_U64_2XU32(x) ((void)0)
DSTATUS disk_initialize(BYTE n) {(void)n;return 0;}
DSTATUS disk_status(BYTE n) {(void)n;return 0;}
DRESULT disk_read(BYTE n,BYTE *out,LBA_t sector,UINT count) {
    (void)n;if(sector>=sectors||count>sectors-sector)return RES_ERROR;
    memcpy(out,disk+(size_t)sector*512,(size_t)count*512);return RES_OK;
}
DRESULT disk_write(BYTE n,const BYTE *in,LBA_t sector,UINT count) {
    (void)n;if(sector>=sectors||count>sectors-sector)return RES_ERROR;
    memcpy(disk+(size_t)sector*512,in,(size_t)count*512);return RES_OK;
}
DRESULT disk_ioctl(BYTE n,BYTE cmd,void *out) {
    (void)n;
    switch(cmd) {
    case CTRL_SYNC:return failSync?RES_ERROR:RES_OK;
    case GET_SECTOR_COUNT:*(LBA_t*)out=sectors;return RES_OK;
    case GET_SECTOR_SIZE:*(WORD*)out=512;return RES_OK;
    case GET_BLOCK_SIZE:*(DWORD*)out=1;return RES_OK;
    default:return RES_PARERR;
    }
}
DWORD get_fattime(void) {return (2026-1980U)<<25|10U<<21|18U<<16;}
int ff_mutex_create(int n) {(void)n;return 1;}
void ff_mutex_delete(int n) {(void)n;}
int ff_mutex_take(int n) {(void)n;return 1;}
void ff_mutex_give(int n) {(void)n;}
@WALKER@
@ALLOCATION@
static void verifySavedCard(void) {
    FIL f;unsigned char buf[4096];UINT got;
    assert(f_open(&f,"0:/saved.bin",FA_READ)==FR_OK);
    for(unsigned int offset=0;offset<8*1048576U;offset+=sizeof(buf)) {
        assert(f_read(&f,buf,sizeof(buf),&got)==FR_OK&&got==sizeof(buf));
        for(unsigned int j=0;j<sizeof(buf);j++)assert(buf[j]==0x5a);
    }
    assert(f_close(&f)==FR_OK);
}
static void run(BYTE format) {
    FATFS fs;FIL f;unsigned char work[4096],buf[4096];UINT written;
    MKFS_PARM options={.fmt=format|FM_SFD,.n_fat=1,.align=1,.n_root=512,.au_size=512};
    vmc_alloc_request_t request={VMC_ALLOC_V1,8*1048576U};
    memset(disk,0,(size_t)sectors*512);
    assert(f_mkfs("0:",&options,work,sizeof(work))==FR_OK);
    assert(f_mount(&fs,"0:",1)==FR_OK);
    assert(fs.fs_type==(format==FM_EXFAT?FS_EXFAT:FS_FAT32));
    assert(f_open(&f,"0:/saved.bin",FA_CREATE_NEW|FA_READ|FA_WRITE)==FR_OK);
    assert(vmc_allocate_contiguous(&f,&request,1)==VMC_ALLOC_V1);
    memset(buf,0x5a,sizeof(buf));
    for(unsigned int offset=0;offset<request.bytes;offset+=sizeof(buf))
        assert(f_write(&f,buf,sizeof(buf),&written)==FR_OK&&written==sizeof(buf));
    assert(vmc_allocate_contiguous(&f,&request,0)==VMC_ALLOC_V1);
    assert(f_close(&f)==FR_OK);
    /* Atomic create-new refuses a racing existing card without truncating it. */
    assert(f_open(&f,"0:/saved.bin",FA_CREATE_NEW|FA_READ|FA_WRITE)==FR_EXIST);
    assert(f_mount(NULL,"0:",0)==FR_OK);
    assert(f_mount(&fs,"0:",1)==FR_OK);
    verifySavedCard();
    /* Fill the remainder in 1-MiB files, then punch alternating 1-MiB holes.
       There is ample total free space, but no free 8-MiB run. */
    int files=0;char name[32];
    for(int i=0;i<128;i++) {
        snprintf(name,sizeof(name),"0:/f%03d.bin",i);
        assert(f_open(&f,name,FA_CREATE_NEW|FA_WRITE)==FR_OK);
        FRESULT result=f_expand(&f,1048576,1);
        assert(f_close(&f)==FR_OK);
        if(result==FR_DENIED) {assert(f_unlink(name)==FR_OK);break;}
        assert(result==FR_OK);files++;
    }
    assert(files>20);
    for(int i=0;i<files-1;i+=2) {
        snprintf(name,sizeof(name),"0:/f%03d.bin",i);assert(f_unlink(name)==FR_OK);
    }
    assert(f_open(&f,"0:/new.bin",FA_CREATE_NEW|FA_READ|FA_WRITE)==FR_OK);
    assert(vmc_allocate_contiguous(&f,&request,1)==-ENOSPC);
    assert(f_size(&f)==0);
    assert(f_close(&f)==FR_OK);assert(f_unlink("0:/new.bin")==FR_OK);
    verifySavedCard();
    assert(f_mount(NULL,"0:",0)==FR_OK);
    printf("FatFs image: %s reservation, format/readback, remount, create collision and fragmented free-space refusal pass\n",format==FM_EXFAT?"exFAT":"FAT32");
}
int main(void) {
    disk=malloc((size_t)sectors*512);assert(disk);
    run(FM_FAT32);run(FM_EXFAT);free(disk);return 0;
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
            relative = entry['path'].removeprefix('source/')
            shutil.copyfile(args.source / relative, target)
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
    c, exe = build / 'image.c', build / 'image.exe'
    c.write_text(program.replace('@WALKER@', walker).replace('@ALLOCATION@', allocation))
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-I', str(build), '-I', str(root / 'include'),
                    str(c), str(build / 'ff.c'), str(build / 'ffunicode.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=90)
