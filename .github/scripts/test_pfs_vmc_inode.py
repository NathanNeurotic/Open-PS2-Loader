"""Execute the real hddGetFileBlockInfo against raw inode sectors (#986).

pfs0: is mounted write-back, so the sector read off the disk can be a stale or never-written
inode. Only a committed inode -- PFS's own magic and checksum -- may yield a block map that
native mcemu writes through.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
header = (root / 'include/hdd.h').read_text(encoding='utf-8')
start = header.index('typedef struct')
types = header[start:header.index('} pfs_inode_t;') + len('} pfs_inode_t;')]
source = (root / 'src/hdd.c').read_text(encoding='utf-8')
start = source.index('int hddGetFileBlockInfo(')
function = source[start:source.index('\n}\n', start) + 3]

program = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
#define APA_MAXSUB 64
#define APA_IDMAX 32
#define APA_PASSMAX 8
@TYPES@
typedef struct { unsigned int private_4, private_5; } iox_stat_t;
static unsigned char IOBuffer[2048] __attribute__((aligned(64)));
static pfs_inode_t disk;
static int statResult, readResult;
static u32 readLba;
static int fileXioGetStat(const char *name, iox_stat_t *stat)
{
    assert(!strcmp(name, "pfs0:VMC/card.bin"));
    stat->private_4 = 1;
    stat->private_5 = 0x40;
    return statResult;
}
static int hddReadSectors(u32 lba, u32 nsectors, void *buf)
{
    assert(nsectors == 2 && buf == IOBuffer);
    readLba = lba;
    memcpy(buf, &disk, sizeof(disk));
    return readResult;
}
@FUNCTION@
static void commit(void)
{
    const u32 *word = (const u32 *)&disk;
    u32 sum = 0;
    for (unsigned int i = 1; i < sizeof(disk) / sizeof(u32); i++)
        sum += word[i];
    disk.checksum = sum;
}
static void card(int segments)
{
    memset(&disk, 0, sizeof(disk));
    disk.magic = PFS_SEGD_MAGIC;
    disk.number_data = segments;
    for (int i = 0; i < segments; i++)
        disk.data[i] = (pfs_blockinfo_t){0x100 + i * 0x40, 0, i ? 0x40 : 1};
    commit();
    statResult = readResult = 0;
}
int main(void)
{
    apa_sub_t subs[2] = {{0x1000, 0x100000}, {0x200000, 0x100000}};
    pfs_blockinfo_t blocks[11];
    assert(sizeof(pfs_inode_t) == 1024);

    card(3);
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == 3);
    assert(readLba == 0x200040 && blocks[2].number == 0x180 && blocks[2].count == 0x40);

    card(10);
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == 10);
    card(11);
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -ENOMEM);

    /* A sector PFS never committed: zeros, an old free zone, or a stale inode edited since. */
    memset(&disk, 0, sizeof(disk));
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -EIO);
    card(3); disk.magic = 0x53454749; commit(); /* an indirect segment descriptor, not a file inode */
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -EIO);
    card(3); disk.data[1].number++;               /* map changed after the checksum was written */
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -EIO);
    card(3); disk.checksum ^= 1;
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -EIO);

    card(3); readResult = -1;
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -EIO);
    card(3); statResult = -ENOENT;
    assert(hddGetFileBlockInfo("pfs0:VMC/card.bin", subs, blocks, 11) == -ENOENT);
    puts("PFS VMC inode: committed maps pass, uncommitted/foreign/edited sectors and read errors are refused");
    return 0;
}
'''.replace('@TYPES@', types).replace('@FUNCTION@', function)

with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    cfile, exe = temp / 'inode.c', temp / 'inode.exe'
    cfile.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
