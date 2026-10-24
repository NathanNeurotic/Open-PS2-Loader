"""Compile both real SCSI implementations against simulated READ CAPACITY replies.

Verify byte-bounded reads/writes for 512/2048/4096-byte blocks, exact sector
counts, RC16 selection/fallback, and refusal of unrepresentable geometry.
"""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = (
    Path('modules/ilink/IEEE1394_bd/src'),
    Path('modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src'),
)
TYPES = '''#ifndef TEST_TYPES_H
#define TEST_TYPES_H
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#endif
'''
BDM = '''#ifndef TEST_BDM_H
#define TEST_BDM_H
#include "tamtypes.h"
struct block_device {
    void *priv; char *name; unsigned int devNr,parNr; unsigned char parId;
    unsigned int sectorSize; u64 sectorOffset,sectorCount;
    int (*read)(struct block_device *,u64,void *,u16);
    int (*write)(struct block_device *,u64,const void *,u16);
    void (*flush)(struct block_device *);
    int (*stop)(struct block_device *);
    char *path;
};
void bdm_connect_bd(struct block_device *);
void bdm_disconnect_bd(struct block_device *);
#endif
'''
HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "bdm.h"
#include "scsi.h"
#include "thbase.h"
void GetSystemTime(iop_sys_clock_t *c) { c->lo=c->hi=0; }
void SysClock2USec(iop_sys_clock_t *c,uint32_t *s,uint32_t *u) { (void)c;*s=*u=0; }

static struct block_device *connected;
static unsigned int block_size=512,last10=999,block16=512;
static u64 last16=0x100000002ull;
static int fail16,calls16,rw_calls,failures,expected_write;
static unsigned int transferred,max_bytes;
static unsigned char data[131072];
static u64 expected_lba;
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL %s\n",msg);failures++; } } while(0)
int DelayThread(int us) { (void)us;return 0; }
void bdm_connect_bd(struct block_device *bd) { connected=bd; }
void bdm_disconnect_bd(struct block_device *bd) { (void)bd;connected=NULL; }
static void be32(unsigned char *p,unsigned int v) { p[0]=v>>24;p[1]=v>>16;p[2]=v>>8;p[3]=v; }
static int lun(struct scsi_interface *s) { (void)s;return 0; }
static int command(struct scsi_interface *s,const unsigned char *cmd,unsigned int len,
                   unsigned char *buffer,unsigned int bytes,unsigned int write) {
    (void)s;(void)len;
    switch(cmd[0]) {
        case 0x25: be32(buffer,last10);be32(buffer+4,block_size);return 0;
        case 0x9e:
            calls16++;
            if(fail16) return -1;
            be32(buffer,last16>>32);be32(buffer+4,last16);be32(buffer+8,block16);return 0;
        case 0x28: case 0x2a: case 0x88: case 0x8a: {
            unsigned int sectors;
            u64 lba=0;
            int i;
            if(cmd[0]==0x88 || cmd[0]==0x8a) {
                for(i=2;i<10;i++) lba=(lba<<8)|cmd[i];
                sectors=((unsigned int)cmd[10]<<24)|((unsigned int)cmd[11]<<16)|(cmd[12]<<8)|cmd[13];
            } else {
                for(i=2;i<6;i++) lba=(lba<<8)|cmd[i];
                sectors=(cmd[7]<<8)|cmd[8];
            }
            CHECK(bytes<=65024,"each SCSI transfer fits ORB length and staging buffer");
            CHECK(sectors>0,"chunking makes progress");
            CHECK(bytes==sectors*connected->sectorSize,"CDB sectors match transfer bytes");
            CHECK(lba==expected_lba,"chunks advance disk LBA");
            CHECK(buffer==data+transferred,"chunks advance memory pointer");
            CHECK(write==(unsigned int)expected_write,"read/write direction reaches transport");
            expected_lba+=sectors;transferred+=bytes;rw_calls++;
            if(bytes>max_bytes) max_bytes=bytes;
            return 0;
        }
        default: memset(buffer,0,bytes);return 0;
    }
}
static struct scsi_interface iface={.name="sd",.max_sectors=127,.get_max_lun=lun,.queue_cmd=command};
static void disconnect(void) { scsi_disconnect(&iface);connected=NULL; }
static void transfer(unsigned int size,unsigned int count,unsigned int chunks) {
    block_size=size;last10=999;scsi_connect(&iface);
    CHECK(connected!=NULL,"supported geometry is connected");
    if(!connected) return;
    CHECK(connected->sectorCount==1000,"capacity is last LBA plus one");
    for(expected_write=0;expected_write<2;expected_write++) {
        expected_lba=123;transferred=max_bytes=rw_calls=0;
        int rc=expected_write ? connected->write(connected,123,data,count) : connected->read(connected,123,data,count);
        CHECK(rc==(int)count,"full block request completes");
        CHECK(transferred==size*count && rw_calls==(int)chunks,"byte limit selects exact chunk sizes");
    }
    disconnect();
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    scsi_init();
    transfer(512,128,2);transfer(2048,33,2);transfer(4096,32,3);transfer(65024,2,2);
    block_size=512;last10=0;scsi_connect(&iface);
    CHECK(connected && connected->sectorCount==1,"one-block disk has one usable sector");disconnect();
    last10=0xffffffffu;calls16=0;scsi_connect(&iface);
#ifdef NATIVE_DRIVER
    CHECK(calls16==1 && connected && connected->sectorCount==last16+1,"RC10 sentinel selects exact 64-bit capacity");
    disconnect();fail16=1;scsi_connect(&iface);
    CHECK(connected && connected->sectorCount==0x100000000ull,"unsupported RC16 preserves RC10 addressable range");
    disconnect();fail16=0;last16=~0ull;scsi_connect(&iface);
    CHECK(!connected,"unrepresentable RC16 sector count is refused");disconnect();
    last16=0x100000002ull;block16=65536;scsi_connect(&iface);
    CHECK(!connected,"oversized RC16 block length is refused");disconnect();
#else
    CHECK(calls16==0 && connected && connected->sectorCount==0x100000000ull,"legacy RC10 range does not wrap to zero");
#endif
    disconnect();last10=999;block_size=65536;scsi_connect(&iface);
    CHECK(!connected,"block larger than one SBP-2 buffer is refused");disconnect();
    block_size=0;scsi_connect(&iface);
    CHECK(!connected,"zero block length is refused");disconnect();
    return failures ? 1 : 0;
}
'''


def run(driver, native):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for name, text in {'tamtypes.h': TYPES, 'bdm.h': BDM, 'sysclib.h': '#include <string.h>\n',
                           'thbase.h': '#include <stdint.h>\ntypedef struct { uint32_t lo, hi; } iop_sys_clock_t;\nint DelayThread(int);\nvoid GetSystemTime(iop_sys_clock_t *);\nvoid SysClock2USec(iop_sys_clock_t *, uint32_t *, uint32_t *);\n', 'thsemap.h': ''}.items():
            (folder / name).write_text(text, encoding='utf-8')
        cfile = folder / 'geometry.c'
        cfile.write_text(HARNESS, encoding='utf-8')
        exe = folder / ('geometry.exe' if sys.platform == 'win32' else 'geometry')
        flags = ['-DNATIVE_DRIVER'] if native else []
        subprocess.run(['gcc', '-std=gnu2x', '-O2', '-Wall', '-Werror', '-DMINI_DRIVER', *flags,
                        '-I', str(folder), '-I', str(driver), '-I', str(driver / 'include'),
                        str(driver / 'scsi.c'), str(cfile), '-o', str(exe)], check=True, timeout=60)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        print(str(driver) + ':')
        if result.returncode == 0:
            print(result.stdout.strip() or 'PASS: geometry, capacity and byte-bounded I/O')
        else:
            print(result.stdout.strip() or 'FAIL: harness exited %d' % result.returncode)
            if result.stderr: print(result.stderr.strip())
        return result.returncode == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    results = [run(args.source_root / driver, native=i == 0) for i, driver in enumerate(DRIVERS)]
    sys.exit(0 if all(results) else 1)
