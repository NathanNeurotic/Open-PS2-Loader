"""Exercise production APA file/partition transfers with a recording stub.

No block device is opened. Invalid inputs must return before the stub is called.
An optional hdd_fio.c path permits checking the regression against an older source.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (Path(sys.argv[1]) if len(sys.argv) > 1 else
          root / 'modules/hdd/apa/src/hdd_fio.c').read_text()


def function(signature):
    start = source.index(signature + '\n{')
    return source[start:source.index('\n}', start) + 2] + '\n'


prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32; typedef uint16_t u16; typedef int32_t s32;
#define APA_MAXSUB 64
#define APA_IDMAX 32
#define BLKIO_MAX_VOLUMES 2
#define BLKIO_DIR_READ 0
#define BLKIO_DIR_WRITE 1
typedef struct { u32 start, length; } apa_sub_t;
typedef struct { int unit; void *privdata; } iomanX_iop_file_t;
typedef struct {
 iomanX_iop_file_t *f; u32 post; u16 nsub, type; char id[APA_IDMAX];
 apa_sub_t parts[APA_MAXSUB+1];
} hdd_file_slot_t;
typedef struct { u32 sub, sector, size, mode; void *buffer; } hddIoctl2Transfer_t;
static struct { u32 totalLBA; } hddDevices[2]={{0x100000}, {0x200000}};
static int calls, io_error, lock_depth, fioSema;
static u32 last_sector,last_count;
static int last_mode;
static void *last_buffer;
static int WaitSema(int s) { (void)s; assert(lock_depth++==0); return 0; }
static int SignalSema(int s) { (void)s; assert(--lock_depth==0); return 0; }
static int blkIoDmaTransfer(int dev,void *buf,u32 sector,u32 count,int mode) {
 assert(dev>=0 && dev<2);
 assert(sector<hddDevices[dev].totalLBA && count<=hddDevices[dev].totalLBA-sector);
 calls++; last_sector=sector; last_count=count; last_mode=mode; last_buffer=buf;
 return io_error;
}
'''
production = ''
helper = 'static int fioPartitionRange(s32 device, const apa_sub_t *part, u32 sector, u32 count)'
if helper in source:
    production += function(helper)
production += function('static int fioDataTransfer(iomanX_iop_file_t *f, void *buf, int size, int mode)')
production += function('static int ioctl2Transfer(s32 device, hdd_file_slot_t *fileSlot, hddIoctl2Transfer_t *arg)')

tests = r'''
int main(void) {
 char buffer[1024];
 hdd_file_slot_t slot={.nsub=1,.parts={{0x40000,0x40000},{0x80000,0x40000}}};
 hddIoctl2Transfer_t req={.sub=0,.sector=0x2000,.size=2,.buffer=buffer};
 iomanX_iop_file_t file={.unit=0,.privdata=&slot};
 /* A malformed partition must be rejected before address translation. */
 apa_sub_t initial=slot.parts[0];
 slot.parts[0].start=UINT32_MAX-0x1fff;
 assert(ioctl2Transfer(0,&slot,&req)<0 && calls==0);
 slot.parts[0]=initial;
 for(int direction=0;direction<=1;direction++) {
  req.mode=direction;
  for(unsigned sub=0;sub<=1;sub++) {
   req.sub=sub; req.sector=sub?2:0x2000; req.size=2;
   int before=calls;
   assert(ioctl2Transfer(0,&slot,&req)==0 && calls==before+1);
   assert(last_sector==slot.parts[sub].start+req.sector && last_count==2);
   assert(last_buffer==buffer && last_mode==direction);
   req.sector=slot.parts[sub].length-1; req.size=1;
   assert(ioctl2Transfer(0,&slot,&req)==0);
   before=calls;
   req.size=2; assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   req.sector=slot.parts[sub].length; req.size=1;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   req.size=0; assert(ioctl2Transfer(0,&slot,&req)==0 && calls==before);
   req.sector=sub?1:0x1fff; req.size=1;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   req.sector=UINT32_MAX-1; req.size=2;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   req.sector=sub?2:0x2000; req.size=UINT32_MAX;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   req.size=2;
   apa_sub_t saved=slot.parts[sub];
   slot.parts[sub].start=UINT32_MAX-0x1fff;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   slot.parts[sub]=saved; slot.parts[sub].length=UINT32_MAX;
   assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
   slot.parts[sub]=saved;
  }
 }
 int before=calls;
 req=(hddIoctl2Transfer_t){.sub=2,.sector=2,.size=1,.buffer=buffer};
 assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
 req.sub=UINT32_MAX; assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
 req.sub=0; req.sector=0x2000; slot.nsub=APA_MAXSUB+1;
 assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
 slot.nsub=1; req.mode=2;
 assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
 req.mode=0;
 assert(ioctl2Transfer(-1,&slot,&req)<0 && calls==before);
 assert(ioctl2Transfer(2,&slot,&req)<0 && calls==before);
 /* The highest legal sub index and a partition ending exactly at capacity. */
 slot.nsub=APA_MAXSUB; slot.parts[APA_MAXSUB]=(apa_sub_t){0xc0000,0x40000};
 req.sub=APA_MAXSUB; req.sector=0x3ffff; req.size=1;
 assert(ioctl2Transfer(0,&slot,&req)==0 && last_sector==0xfffff);
 req.sub=0; req.sector=0x2000; slot.nsub=1;
 before=calls;
 u32 capacity=hddDevices[0].totalLBA;
 hddDevices[0].totalLBA=0;
 assert(ioctl2Transfer(0,&slot,&req)<0 && calls==before);
 hddDevices[0].totalLBA=capacity;
 io_error=1;
 assert(ioctl2Transfer(0,&slot,&req)==-EIO && calls==before+1);
 io_error=0;
 puts("PASS: APA main/sub read-write limits, invalid geometry/index/direction, zero count and device errors");

 for(int direction=0;direction<=1;direction++) {
  slot.post=0;
  assert(fioDataTransfer(&file,buffer,512,direction)==512);
  assert(slot.post==1 && last_sector==slot.parts[0].start+8 && last_mode==direction);
  slot.post=0x1ff7;
  assert(fioDataTransfer(&file,buffer,1024,direction)==512 && slot.post==0x1ff8);
  assert(last_sector==slot.parts[0].start+0x1fff && last_count==1);
  before=calls;
  assert(fioDataTransfer(&file,buffer,512,direction)==0 && calls==before);
  slot.post=UINT32_MAX;
  assert(fioDataTransfer(&file,buffer,512,direction)<0 && calls==before);
  slot.post=0;
  assert(fioDataTransfer(&file,buffer,-512,direction)<0 && calls==before);
  assert(fioDataTransfer(&file,buffer,511,direction)<0 && calls==before);
  assert(fioDataTransfer(&file,buffer,0,direction)==0 && calls==before);
  apa_sub_t saved=slot.parts[0]; slot.parts[0].start=UINT32_MAX-7;
  assert(fioDataTransfer(&file,buffer,512,direction)<0 && calls==before);
  slot.parts[0]=saved; io_error=1;
  assert(fioDataTransfer(&file,buffer,512,direction)==-EIO && slot.post==0);
  assert(lock_depth==0); io_error=0;
  iomanX_iop_file_t null_file={.unit=0,.privdata=NULL};
  assert(fioDataTransfer(&null_file,buffer,512,direction)==-EBADF && lock_depth==0);
 }
 puts("PASS: APA file-view limits, EOF clamping, position/size checks and lock/position cleanup");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='apa-bounds-') as temp:
    c, exe = Path(temp) / 'test.c', Path(temp) / 'test'
    c.write_text(prefix + production + tests)
    subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
