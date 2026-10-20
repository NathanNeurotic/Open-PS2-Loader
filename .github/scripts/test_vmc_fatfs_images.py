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
@ADAPTER@
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
    int progress=0;char message[64];
    genvmc_job.VMC_flags=VMC_CREATE_CONTIGUOUS;
    assert(vmc_mcformat("0:/native.bin",8192,16,&progress,message)==0);
    assert(progress==100&&genvmc_owns_file==1);
    verifyFailure=1;
    assert(vmc_mcformat("0:/verify.bin",8192,16,&progress,message)==-113);
    verifyFailure=0;assert(f_unlink("0:/verify.bin")==FR_OK);
    closeFailure=1;
    assert(vmc_mcformat("0:/close.bin",8192,16,&progress,message)==-114);
    closeFailure=0;assert(f_unlink("0:/close.bin")==FR_OK);
    genvmc_job.VMC_flags=0;closeFailure=1;
    assert(vmc_mcformat("0:/legacy.bin",8192,16,&progress,message)==-114);
    closeFailure=0;assert(f_unlink("0:/legacy.bin")==FR_OK);
    /* Atomic create-new refuses a racing existing card without truncating it. */
    assert(f_open(&f,"0:/saved.bin",FA_CREATE_NEW|FA_READ|FA_WRITE)==FR_EXIST);
    assert(f_mount(NULL,"0:",0)==FR_OK);
    assert(f_mount(&fs,"0:",1)==FR_OK);
    verifySavedCard();
    verifyFormattedCard();
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
    verifyFormattedCard();
    assert(f_mount(NULL,"0:",0)==FR_OK);
    printf("FatFs image: %s reservation, actual genvmc format/readback, remount, create collision and fragmented free-space refusal pass\n",format==FM_EXFAT?"exFAT":"FAT32");
}
int main(void) {
    disk=malloc((size_t)sectors*512);assert(disk);
    run(FM_FAT32);run(FM_EXFAT);free(disk);return 0;
}
'''
source = (root / 'modules/vmc/genvmc/genvmc.c').read_text()
def function(name):
    start = source.index('static ', source.index(name) - 20)
    return source[start:source.index('\n}', start) + 2]
start = source.index('// SONY superblock magic')
end = source.index('static int genvmc_io_sema', start)
formatter = source[start:end] + '\nstatic int genvmc_abort_sema, genvmc_abort, genvmc_owns_file;\nstatic createVMCparam_t genvmc_job;\n'
for name in ('long_multiply(', 'mc_writecluster(', 'vmc_open_contiguous(', 'vmc_reserve_pfs(', 'vmc_mcformat('):
    formatter += function(name) + '\n'
# Host adapters retain the SDK libmc-common.h on-disk entry ABI. Clock,
# interrupt and semaphore adapters do not model IOP scheduling; lifecycle
# fault injection lives in test_genvmc_lifecycle.py. Formatter bodies below
# are extracted unchanged, including the fd-zero create/verify path.
adapter = r'''
#include "genvmc.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef int16_t s16;
typedef uint32_t u32;
typedef struct {u8 Resv2,Sec,Min,Hour,Day,Month;u16 Year;} sceMcStDateTime;
typedef struct {
    u16 mode,unused;u32 length;sceMcStDateTime created;
    u32 cluster,dir_entry;sceMcStDateTime modified;u32 attr,unused2[7];
    char name[32];u8 unused3[416];
} McFsEntry;
#define sceMcFileAttrReadable 1
#define sceMcFileAttrWriteable 2
#define sceMcFileAttrExecutable 4
#define sceMcFileAttrSubdir 0x20
#define sceMcFile0400 0x400
#define sceMcFileAttrHidden 0x2000
#define sceMcFileAttrExists 0x8000
#define O_RDWR 3
#define O_CREAT 0x200
#define O_TRUNC 0x400
#define PIOCALLOC 0x7001
#define DPRINTF(...) ((void)0)
#define MODNAME "genvmc"
#define FIO_O_EXCL 0x800
#define ALLOC_FIRST 0
static FIL formatted;
static int closeFailure, verifyFailure;
static int host_open(const char *name,int flags) {
    assert(flags==(O_RDWR|O_CREAT|FIO_O_EXCL)||flags==(O_RDWR|O_CREAT|O_TRUNC));
    BYTE create=(flags&FIO_O_EXCL)?FA_CREATE_NEW:FA_CREATE_ALWAYS;
    return f_open(&formatted,name,create|FA_READ|FA_WRITE)==FR_OK?0:-1;
}
static int host_close(int fd) {assert(fd==0);FRESULT result=f_close(&formatted);return result==FR_OK&&!closeFailure?0:-1;}
static int host_write(int fd,const void *buf,int bytes) {
    UINT written;assert(fd==0);
    return f_write(&formatted,buf,bytes,&written)==FR_OK?(int)written:-1;
}
static int host_lseek(int fd,int offset,int mode) {
    assert(fd==0&&mode==SEEK_SET);
    return f_lseek(&formatted,offset)==FR_OK?offset:-1;
}
static int host_devctl(const char *name,unsigned int cmd,void *in,int insize,void *out,int outsize) {
    (void)name;(void)in;(void)out;assert(cmd==VMC_ALLOC_CAPS&&insize==0&&outsize==0);
    return VMC_ALLOC_V1;
}
static int host_ioctl2(int fd,unsigned int cmd,void *in,int insize,void *out,int outsize) {
    assert(fd==0&&insize==sizeof(vmc_alloc_request_t)&&out==NULL&&outsize==0);
    assert(cmd==VMC_ALLOC_RESERVE||cmd==VMC_ALLOC_VERIFY);
    if(cmd==VMC_ALLOC_VERIFY&&verifyFailure)return -EIO;
    return vmc_allocate_contiguous(&formatted,in,cmd==VMC_ALLOC_RESERVE);
}
static int mc_getmcrtime(sceMcStDateTime *time) {
    memset(time,0,sizeof(*time));time->Year=2026;time->Month=10;time->Day=18;return 0;
}
#define WaitSema(n) ((void)(n))
#define SignalSema(n) ((void)(n))
#define CpuSuspendIntr(p) (*(p)=0)
#define CpuResumeIntr(n) ((void)(n))
#define AllocSysMemory(mode,size,address) malloc(size)
#define FreeSysMemory(p) free(p)
#define open host_open
#define close host_close
#define write host_write
#define lseek host_lseek
#define devctl host_devctl
#define ioctl2 host_ioctl2
@FORMATTER@
#undef open
#undef close
#undef write
#undef lseek
#undef devctl
#undef ioctl2
static void verifyFormattedCard(void) {
    FIL f;MCDevInfo info;McFsEntry entries[2];UINT got;
    assert(sizeof(info)==384&&sizeof(McFsEntry)==512);
    assert(f_open(&f,"0:/native.bin",FA_READ)==FR_OK);
    assert(f_size(&f)==8*1048576U);
    assert(f_read(&f,&info,sizeof(info),&got)==FR_OK&&got==sizeof(info));
    assert(memcmp(info.magic,SUPERBLOCK_MAGIC,sizeof(SUPERBLOCK_MAGIC)-1)==0);
    assert(memcmp(info.version,SUPERBLOCK_VERSION,sizeof(SUPERBLOCK_VERSION))==0);
    assert(info.cardform==1&&info.pagesize==512&&info.clusters_per_card==8192);
    assert(f_lseek(&f,info.alloc_offset*1024)==FR_OK);
    assert(f_read(&f,entries,sizeof(entries),&got)==FR_OK&&got==sizeof(entries));
    assert(strcmp(entries[0].name,".")==0&&strcmp(entries[1].name,"..")==0);
    assert(entries[0].length==2&&entries[0].cluster==0);
    assert(f_close(&f)==FR_OK);
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
    c.write_text(program.replace('@WALKER@', walker).replace('@ALLOCATION@', allocation).replace('@ADAPTER@', adapter.replace('@FORMATTER@', formatter)))
    subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-I', str(build), '-I', str(root / 'include'), '-I', str(root / 'modules/vmc/genvmc'), '-Wno-sign-compare',
                    str(c), str(build / 'ff.c'), str(build / 'ffunicode.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=90)
