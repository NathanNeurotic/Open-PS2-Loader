"""Fault-inject the actual allocation guard and formatter's create-only opener."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
allocation = (root / '.github/patches/bdmfs-vmc-allocation.c').read_text()
source = (root / 'modules/vmc/genvmc/genvmc.c').read_text()
start = source.index('static int vmc_open_contiguous(')
opener = source[start:source.index('\n}', start) + 2]
program = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include "vmc_alloc.h"
typedef uint64_t u64;
typedef struct {u64 sector; unsigned int count;} bd_fragment_t;
typedef struct {int fs_type, ssize;} FATFS;
typedef struct {FATFS *fs; u64 objsize;} FFOBJID;
typedef struct {FFOBJID obj; unsigned int flag, fptr;} FIL;
typedef int FRESULT;
#define FF_MAX_SS 4096
#define FF_MIN_SS 512
#define FS_FAT12 1
#define FS_FAT16 2
#define FS_FAT32 3
#define FS_EXFAT 4
#define FA_WRITE 2
#define FR_OK 0
#define FR_DENIED 7
#define O_RDWR 3
#define O_CREAT 0x200
#define FIO_O_EXCL 0x800
static FATFS fs;
static FIL file;
static int expandResult,syncResult,fragments,expands,syncs;
static u64 sector;
static unsigned int count;
static int f_expand(FIL *f,unsigned int bytes,int allocate) {
    assert(allocate==1);expands++;
    if(expandResult==FR_OK) f->obj.objsize=bytes;
    return expandResult;
}
static int f_sync(FIL *f) {(void)f;syncs++;return syncResult;}
static int get_frag_list(FIL *f,void *out,unsigned int length) {
    (void)f;assert(length==sizeof(bd_fragment_t));
    *(bd_fragment_t*)out=(bd_fragment_t){sector,count};return fragments;
}
@ALLOCATION@
static int capability,openResult,opens,closes,genvmc_owns_file;
static int devctl(const char *path,int cmd,void *a,int al,void *o,int ol) {
    (void)path;(void)a;(void)al;(void)o;(void)ol;assert(cmd==VMC_ALLOC_CAPS);return capability;
}
static int open(const char *path,int flags) {
    (void)path;assert(flags==(O_RDWR|O_CREAT|FIO_O_EXCL));opens++;return openResult;
}
static int close(int fd) {assert(fd==openResult);closes++;return 0;}
static int ioctl2(int fd,int cmd,void *arg,unsigned int len,void *out,int outlen) {
    (void)out;(void)outlen;assert(fd==openResult&&len==sizeof(vmc_alloc_request_t));
    return vmc_allocate_contiguous(&file,arg,cmd==VMC_ALLOC_RESERVE);
}
@OPENER@
static void reset(void) {
    fs=(FATFS){FS_FAT32,512};file=(FIL){.obj={&fs,0},.flag=FA_WRITE};
    expands=syncs=expandResult=syncResult=opens=closes=genvmc_owns_file=0;
    fragments=1;sector=100;count=8*2048;capability=VMC_ALLOC_V1;openResult=0;
}
int main(void) {
    vmc_alloc_request_t req={VMC_ALLOC_V1,8*1048576U};
    reset();assert(vmc_open_contiguous("mass0:/VMC/new.bin",req.bytes)==0);
    assert(genvmc_owns_file&&opens==1&&expands==1&&!closes);
    assert(vmc_allocate_contiguous(&file,&req,0)==VMC_ALLOC_V1&&expands==1);
    reset();fs.fs_type=FS_EXFAT;assert(vmc_allocate_contiguous(&file,&req,1)==VMC_ALLOC_V1);
    reset();capability=0;assert(vmc_open_contiguous("mass0:/VMC/new.bin",req.bytes)==-111&&!opens&&!genvmc_owns_file);
    reset();capability=-ENXIO;assert(vmc_open_contiguous("mass0:/VMC/new.bin",req.bytes)==-111&&!opens);
    reset();openResult=-EEXIST;assert(vmc_open_contiguous("mass0:/VMC/old.bin",req.bytes)==-101&&!expands&&!genvmc_owns_file);
    reset();expandResult=FR_DENIED;assert(vmc_open_contiguous("mass0:/VMC/new.bin",req.bytes)==-112&&closes==1&&genvmc_owns_file);
    reset();expandResult=1;assert(vmc_allocate_contiguous(&file,&req,1)==-EIO);
    reset();file.obj.objsize=1;assert(vmc_allocate_contiguous(&file,&req,1)==-EEXIST&&!expands);
    reset();file.fptr=1;assert(vmc_allocate_contiguous(&file,&req,1)==-EEXIST&&!expands);
    reset();file.flag=0;assert(vmc_allocate_contiguous(&file,&req,1)==-EINVAL&&!expands);
    reset();fs.ssize=4096;assert(vmc_allocate_contiguous(&file,&req,1)==-EINVAL&&!expands);
    reset();syncResult=1;assert(vmc_allocate_contiguous(&file,&req,1)==-EIO);
    reset();fragments=-EIO;assert(vmc_allocate_contiguous(&file,&req,1)==-EIO);
    reset();fragments=2;assert(vmc_allocate_contiguous(&file,&req,1)==-EIO);
    reset();count--;assert(vmc_allocate_contiguous(&file,&req,1)==-EOVERFLOW);
    reset();sector=UINT32_MAX-count+1;assert(vmc_allocate_contiguous(&file,&req,1)==VMC_ALLOC_V1);
    reset();sector=UINT32_MAX-count+2;assert(vmc_allocate_contiguous(&file,&req,1)==-EOVERFLOW);
    reset();req.version=0;assert(vmc_allocate_contiguous(&file,&req,1)==-EINVAL&&!expands);
    reset();req.version=VMC_ALLOC_V1;req.bytes=1;assert(vmc_allocate_contiguous(&file,&req,1)==-EINVAL&&!expands);
    puts("VMC reservation: capability, exclusive create, both filesystems, errors, layout and range guards pass");
}
'''.replace('@ALLOCATION@', allocation).replace('@OPENER@', opener)
with tempfile.TemporaryDirectory() as temp:
    c, exe = Path(temp) / 'allocate.c', Path(temp) / 'allocate.exe'
    c.write_text(program)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I', str(root / 'include'), str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
