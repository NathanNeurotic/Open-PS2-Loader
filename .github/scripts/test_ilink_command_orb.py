"""Capture the real command ORB: disk reads require target writes into IOP RAM.

Also check the fixed write-buffer/ORB length limit before publication. The test
storage is oversized to expose the old overflow without corrupting the host.
--source-root can point at a checkout before the fix.
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
SIGNATURE = 'static int sbp2_queue_cmd('
HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "sbp2_disk.h"
#define M_DEBUG(...) ((void)0)
#define BSWAP32(v) __builtin_bswap32(v)
static unsigned char storage[131072], data[131072];
static unsigned char *writeBuffer=storage;
static unsigned int captured, submitted;
int ieee1394_SendCommandBlockORB(struct SBP2Device *dev, struct CommandDescriptorBlock *cdb) {
    (void)dev;captured=cdb->misc;submitted++;return 1;
}
int ieee1394_Sync(void) { return 0; }
@FUNCTION@
static int failures;
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL %s\n",msg);failures++; } } while(0)
int main(void) {
    struct SBP2Device dev={0};dev.scsi.priv=&dev;
    unsigned char cmd[sizeof(((struct CommandDescriptorBlock *)0)->CDBs)]={0};
    unsigned int i;
    /* INQUIRY, READ CAPACITY, READ(10), READ(16) all transfer device -> host. */
    const unsigned char reads[]={0x12,0x25,0x28,0x88};
    for(i=0;i<sizeof(reads);i++) {
        if(reads[i]==0x88 && sizeof(cmd)<16) continue;
        cmd[0]=reads[i];submitted=0;
        int rc=sbp2_queue_cmd(&dev.scsi,cmd,sizeof(cmd),data,36,0);
        CHECK(rc==0 && submitted==1,"read command reaches fetch agent");
        CHECK((captured & (1u<<27))!=0,"disk read ORB lets target write to host memory");
    }
    cmd[0]=0x2a;submitted=0;memset(storage,0xa5,sizeof(storage));
    int rc=sbp2_queue_cmd(&dev.scsi,cmd,sizeof(cmd),data,XFER_BLOCK_SIZE,1);
    CHECK(rc==0 && submitted==1,"maximum write fits the staging buffer");
    CHECK((captured & (1u<<27))==0,"disk write ORB lets target read host memory");
    CHECK((captured & 0xffff)==XFER_BLOCK_SIZE,"maximum ORB byte length is exact");
    CHECK(storage[XFER_BLOCK_SIZE]==0xa5,"maximum write preserves buffer canary");
    for(i=0;i<2;i++) {
        submitted=0;memset(storage,0xa5,sizeof(storage));
        rc=sbp2_queue_cmd(&dev.scsi,cmd,sizeof(cmd),data,65536,i);
        CHECK(rc<0 && submitted==0,"reject 64 KiB before publishing a truncated ORB");
        CHECK(storage[XFER_BLOCK_SIZE]==0xa5,"oversized write cannot overrun staging buffer");
    }
    return failures ? 1 : 0;
}
'''


def run(driver):
    source = (driver / 'sbp2_driver.c').read_text(encoding='utf-8')
    start = source.rindex(SIGNATURE)
    function = source[start:source.index('\n}', start) + 2]
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / 'tamtypes.h').write_text(
            '#include <stdint.h>\ntypedef uint8_t u8; typedef uint16_t u16; '
            'typedef uint32_t u32; typedef uint64_t u64;\n', encoding='utf-8')
        cfile = folder / 'orb.c'
        exe = folder / ('orb.exe' if sys.platform == 'win32' else 'orb')
        cfile.write_text(HARNESS.replace('@FUNCTION@', function), encoding='utf-8')
        subprocess.run(['gcc', '-std=gnu99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-pointer-to-int-cast', '-I', str(folder), '-I', str(driver / 'include'),
                        str(cfile), '-o', str(exe)], check=True, timeout=60)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        print(str(driver) + ':')
        print(result.stdout.strip() or 'PASS: read/write direction and command byte limits')
        return result.returncode == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    results = [run(args.source_root / driver) for driver in DRIVERS]
    sys.exit(0 if all(results) else 1)
