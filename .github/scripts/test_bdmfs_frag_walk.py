"""Fault-inject the production fragment walker without a block device or save data."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parents[1] / 'patches/bdmfs-vmc-fragment-walk.c'
text = source.read_text()
start = text.index('static int get_frag_list(')
function = text[start:text.index('\n}\n', start) + 3]
program = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint64_t u64;
typedef uint32_t DWORD;
typedef struct { u64 sector; unsigned int count; } bd_fragment_t;
typedef struct { unsigned int csize, n_fatent, pdrv, fs_type; } FATFS;
typedef struct { FATFS *fs; DWORD sclust; u64 objsize; } FFOBJID;
typedef struct { FFOBJID obj; } FIL;
struct block_device { u64 sectorOffset; };
#define FF_MAX_SS 512
#define FF_MIN_SS 512
#define FF_FS_EXFAT 1
#define FS_FAT12 1
#define FS_FAT16 2
#define FS_FAT32 3
#define FS_EXFAT 4
#define M_DEBUG(...) ((void)0)
#define DEBUG_U64_2XU32(x) ((void)0)
static FATFS fs;
static FIL file;
static struct block_device bd;
static DWORD fat[64];
static int calls, device_missing, no_fat_chain;
static struct block_device *fatfs_fs_driver_get_mounted_bd_from_index(unsigned int index) {
    (void)index; return device_missing ? NULL : &bd;
}
static u64 clst2sect(FATFS *f, DWORD cluster) { return 100+(u64)(cluster-2)*f->csize; }
static DWORD get_fat(FFOBJID *obj, DWORD cluster) {
    if (++calls > 128) { fputs("unbounded FAT traversal\n", stderr); exit(77); }
    if (cluster<2 || cluster>=fs.n_fatent) return 1;
    if (no_fat_chain) {
        DWORD last=obj->sclust+(obj->objsize-1)/(512*fs.csize);
        return cluster==last ? 0x7FFFFFFF : cluster+1;
    }
    return fat[cluster];
}
@FUNCTION@
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c); return 1; } } while(0)
static void reset(void) {
    memset(fat,0,sizeof(fat)); calls=device_missing=no_fat_chain=0;
    fs=(FATFS){.csize=8,.n_fatent=64,.pdrv=0,.fs_type=FS_FAT32};
    file=(FIL){.obj={.fs=&fs,.sclust=2,.objsize=3*8*512}};
    bd.sectorOffset=1000; fat[2]=3; fat[3]=4; fat[4]=0x0FFFFFFF;
}
int main(void) {
    bd_fragment_t out[2];
    reset(); CHECK(get_frag_list(&file,NULL,0)==1 && calls==3);
    CHECK(get_frag_list(&file,out,sizeof(out))==1 && out[0].sector==1100 && out[0].count==24);
    reset(); fat[3]=8; fat[8]=0x0FFFFFFF;
    CHECK(get_frag_list(&file,NULL,0)==2);
    CHECK(get_frag_list(&file,out,sizeof(out[0]))==2 && out[0].count==16);
    /* Disk failure must not be accepted as EOC or a single contiguous extent. */
    reset(); fat[2]=0xFFFFFFFF; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); fat[4]=0xFFFFFFFF; CHECK(get_frag_list(&file,out,sizeof(out))<0);
    reset(); fat[2]=1; CHECK(get_frag_list(&file,NULL,0)<0 && calls<=3);
    reset(); fat[2]=0; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); fat[2]=0x0FFFFFFF; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); fat[4]=3; CHECK(get_frag_list(&file,NULL,0)<0 && calls<=3);
    reset(); fat[3]=2; CHECK(get_frag_list(&file,NULL,0)<0 && calls<=3);
    reset(); fat[4]=0x0FFFFFF7; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); fat[4]=100; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); file.obj.sclust=1; CHECK(get_frag_list(&file,NULL,0)<0 && calls==0);
    reset(); device_missing=1; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); file.obj.fs=NULL; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); CHECK(get_frag_list(NULL,NULL,0)<0);
    reset(); CHECK(get_frag_list(&file,NULL,sizeof(out))<0);
    reset(); fs.csize=0; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); file.obj.objsize=0; CHECK(get_frag_list(&file,NULL,0)==0 && calls==0);
    reset(); file.obj.objsize=UINT64_MAX; CHECK(get_frag_list(&file,NULL,0)<0 && calls==0);
    reset(); file.obj.objsize=3*8*512-1; CHECK(get_frag_list(&file,NULL,0)==1);
    reset(); file.obj.objsize=8*512; CHECK(get_frag_list(&file,NULL,0)<0);
    reset(); fs.fs_type=FS_EXFAT; no_fat_chain=1;
    CHECK(get_frag_list(&file,out,sizeof(out))==1 && out[0].count==24);
    reset(); fs.fs_type=FS_FAT12; fat[4]=0xFF8; CHECK(get_frag_list(&file,NULL,0)==1);
    reset(); fs.fs_type=FS_FAT16; fat[4]=0xFFF8; CHECK(get_frag_list(&file,NULL,0)==1);
    reset(); fs.fs_type=FS_FAT32; fat[4]=0x0FFFFFF8; CHECK(get_frag_list(&file,NULL,0)==1);
    puts("FAT fragment walker: error/early-EOC/cycle refusals and FAT/exFAT mappings pass");
    return 0;
}
'''.replace('@FUNCTION@', function)
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    c = path / 'frag.c'
    exe = path / 'frag.exe'
    c.write_text(program)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)
