"""Run genvmc's real formatter over a fake PFS file to check the HDD reservation (#986).

PFS grows a file write by write from small free runs, so a new card on a used partition can need
more segments than native mcemu's PFS map holds. A new HDD card asks for every zone in one
PIOCALLOC before the first write. That request is best effort: a refusal must leave the format
(and its result) exactly as it was without one. The route itself is pinned too: only the HDD's
create path sets the flag, and genvmc accepts it.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'modules/vmc/genvmc/genvmc.c').read_text(encoding='utf-8')


def function(name):
    start = source.index('static ', source.index(name) - 20)
    return source[start:source.index('\n}', start) + 2]


start = source.index('// SONY superblock magic')
formatter = source[start:source.index('static int genvmc_io_sema', start)]
formatter += '\nstatic int genvmc_abort_sema, genvmc_abort, genvmc_owns_file;\nstatic createVMCparam_t genvmc_job;\n'
for name in ('long_multiply(', 'mc_writecluster(', 'vmc_open_contiguous(', 'vmc_reserve_pfs(', 'vmc_mcformat('):
    formatter += function(name) + '\n'

program = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "genvmc.h"
#include "vmc_alloc.h"
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
#define FIO_O_EXCL 0x800
#define SEEK_SET 0
#define ALLOC_FIRST 0
#define PIOCALLOC 0x7001
#define DPRINTF(...) ((void)0)
#define MODNAME "genvmc"
static unsigned char *image;
static int imageSize, position, writes, allocs, allocBytes, allocResult, writesBeforeAlloc, opens, openFlags;
static int fake_open(const char *name, int flags)
{
    assert(!strcmp(name, "pfs0:VMC/new.bin"));
    opens++; openFlags = flags; return 7;
}
static int fake_close(int fd) { assert(fd == 7); return 0; }
static int fake_lseek(int fd, int offset, int mode) { assert(fd == 7 && mode == SEEK_SET); position = offset; return offset; }
static int fake_write(int fd, const void *buf, int bytes)
{
    assert(fd == 7 && position + bytes <= imageSize);
    memcpy(image + position, buf, bytes); position += bytes; writes++;
    return bytes;
}
static int fake_ioctl2(int fd, unsigned int cmd, void *in, unsigned int insize, void *out, int outsize)
{
    assert(fd == 7 && cmd == PIOCALLOC && insize == sizeof(int) && out == NULL && outsize == 0);
    allocs++; allocBytes = *(int *)in; writesBeforeAlloc = writes;
    return allocResult;
}
static int fake_devctl(const char *n, unsigned int c, void *i, int is, void *o, int os)
{
    (void)n; (void)c; (void)i; (void)is; (void)o; (void)os; assert(0); return -1;
}
static int mc_getmcrtime(sceMcStDateTime *time) { memset(time, 0, sizeof(*time)); return 0; }
#define WaitSema(n) ((void)(n))
#define SignalSema(n) ((void)(n))
#define CpuSuspendIntr(p) (*(p)=0)
#define CpuResumeIntr(n) ((void)(n))
#define AllocSysMemory(mode,size,address) malloc(size)
#define FreeSysMemory(p) free(p)
#define open fake_open
#define close fake_close
#define write fake_write
#define lseek fake_lseek
#define devctl fake_devctl
#define ioctl2 fake_ioctl2
@FORMATTER@
#undef open
#undef close
#undef write
#undef lseek
#undef devctl
#undef ioctl2
static unsigned char reference[8 * 1048576];
static int format(int flags, int result)
{
    int progress = 0;
    char message[64];
    memset(image, 0, imageSize);
    position = writes = allocs = allocBytes = opens = openFlags = 0;
    writesBeforeAlloc = -1;
    allocResult = result;
    genvmc_job.VMC_flags = flags;
    return vmc_mcformat("pfs0:VMC/new.bin", 8192, 16, &progress, message);
}
int main(void)
{
    imageSize = 8 * 1048576;
    image = malloc(imageSize);
    assert(image);

    /* No flag (every other device): no PFS request, as before. */
    assert(format(0, 0) == 0 && allocs == 0 && openFlags == (O_RDWR | O_CREAT | O_TRUNC));
    memcpy(reference, image, imageSize);

    /* HDD: one request for the whole card, before the first cluster is written. */
    assert(format(VMC_CREATE_PFS_RESERVE, 0) == 0);
    assert(allocs == 1 && allocBytes == 8 * 1048576 && writesBeforeAlloc == 0);
    assert(openFlags == (O_RDWR | O_CREAT | O_TRUNC) && opens == 1);
    assert(memcmp(reference, image, imageSize) == 0); /* the card itself is byte-identical */

    /* Best effort: a refused reservation still formats the same card. */
    assert(format(VMC_CREATE_PFS_RESERVE, -ENOSPC) == 0 && allocs == 1);
    assert(memcmp(reference, image, imageSize) == 0);
    assert(format(VMC_CREATE_PFS_RESERVE, -EINVAL) == 0 && allocs == 1);
    puts("genvmc PFS reservation: whole card requested before writing, card unchanged, refusal is best effort");
    free(image);
    return 0;
}
'''.replace('@FORMATTER@', formatter)

with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    cfile, exe = temp / 'pfs_reserve.c', temp / 'pfs_reserve.exe'
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-sign-compare',
                    '-I', str(root / 'include'), '-I', str(root / 'modules/vmc/genvmc'), str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=60)

# Route: the HDD create path sets the flag, BDM keeps its own, and genvmc accepts the flag.
hdd = (root / 'src/hddsupport.c').read_text(encoding='utf-8')
start = hdd.index('static int hddCheckVMC(')
check = hdd[start:hdd.index('\n}\n', start)]
assert 'sysCheckVMCEx(gHDDPrefix, "/", name, createSize, NULL, VMC_CREATE_PFS_RESERVE)' in check, check
start = source.index('static int vmc_create(')
create = source[start:source.index('\n}\n', start)]
assert '~(VMC_CREATE_CONTIGUOUS | VMC_CREATE_PFS_RESERVE | VMC_CREATE_REBUILD)' in create, create
print('genvmc PFS reservation: HDD creation requests it and genvmc accepts the flag')
