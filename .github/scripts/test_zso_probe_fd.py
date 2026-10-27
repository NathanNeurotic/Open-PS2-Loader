"""Run the actual ZSO probe reader with fd zero, HDD backing and invalid states."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/zso.c').read_text()
if len(sys.argv) > 1:
    source = subprocess.check_output(['git', 'show', sys.argv[1] + ':src/zso.c'], text=True)

def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]

program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define MIN(a,b) ((a)<(b)?(a):(b))
#define SEEK_SET 0
#define SEEK_CUR 1
static int probed_fd, reads, seeks, hddReads, hddFail;
static u32 probed_lba;
static u8 ziso_tmp_buf[2048];
static int lseek(int fd,unsigned int offset,int whence) {
    (void)offset;(void)whence;assert(fd==probed_fd&&fd>=0);seeks++;return 0;
}
static int read(int fd,void *out,unsigned int bytes) {
    assert(fd==probed_fd&&fd>=0);reads++;memset(out,0x5a,bytes);return bytes;
}
static int ReadHDDSectors(u32 lba,u8 *out,u32 count) {
    (void)lba;assert(probed_lba>0&&probed_fd==0);hddReads++;if(hddFail)return -1;memset(out,0xa5,count*2048);return 0;
}
@FUNCTIONS@
int main(void) {
    u8 out[100];
    probed_fd=0;probed_lba=0;
    assert(read_raw_data(out,sizeof(out),64,0)==sizeof(out));
    assert(reads==1&&seeks==2&&!hddReads&&out[0]==0x5a);
    probed_fd=3;
    assert(read_raw_data(out,sizeof(out),64,0)==sizeof(out)&&reads==2&&!hddReads);
    probed_fd=0;probed_lba=100;
    assert(read_raw_data(out,sizeof(out),64,0)==sizeof(out));
    assert(hddReads==1&&reads==2&&out[0]==0xa5&&out[99]==0xa5);
    hddFail=1;
    assert(read_raw_data(out,sizeof(out),64,0)<0); /* a failed HDD sector read is reported, never returned as data */
    hddFail=0;hddReads=1;
    probed_fd=-1;probed_lba=0;
    assert(read_raw_data(out,sizeof(out),64,0)<0&&hddReads==1&&reads==2);
    probed_fd=3;probed_lba=100;
    assert(read_raw_data(out,sizeof(out),64,0)<0&&hddReads==1&&reads==2);
    puts("ZSO probe: fd zero and normal file descriptors, HDD and invalid backing states pass");
}
'''.replace('@FUNCTIONS@', function('static void longLseek(') + '\n' + function('int read_raw_data('))
with tempfile.TemporaryDirectory() as temp:
    c, exe = Path(temp) / 'probe.c', Path(temp) / 'probe.exe'
    c.write_text(program)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
