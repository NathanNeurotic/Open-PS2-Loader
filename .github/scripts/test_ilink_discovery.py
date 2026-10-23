"""Exercise production bus-reset discovery with failed and still-live requests.

A pending LOGIN must keep its device storage; failed configuration must release
its transaction context. FS attach/detach must never run under the I/O mutex.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
DRIVERS=(ROOT/'modules/ilink/IEEE1394_bd/src',ROOT/'modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src')
HARNESS=r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "sbp2_disk.h"
#define MAX_DEVICES 5
#define WEF_AND 1
#define WEF_CLEAR 2
static struct SBP2Device SBP2Devices[MAX_DEVICES];
static struct { int pending;struct SBP2Device *owner; } command;
static int sbp2_io_sema,sbp2_event_flag;
static int events,held,failures,mode,allocations,frees,configured,live[16];
static jmp_buf done;
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL: %s\n",msg);failures++; } } while(0)
static int WaitSema(int s) { (void)s;CHECK(!held,"discovery must not recursively acquire transport");held=1;return 0; }
static int SignalSema(int s) { (void)s;CHECK(held,"discovery releases owned transport");held=0;return 0; }
static int iLinkGetGenerationNumber(void) { return events; }
static int WaitEventFlag(int id,int bits,int op,void *out) {
    (void)id;(void)bits;(void)op;(void)out;
    CHECK(!held,"event wait cannot retain transport mutex");
    if(++events>2) longjmp(done,1);
    return 0;
}
static int iLinkGetNodeCount(void) { return events==1 ? 2 : 1; }
static int iLinkFindUnit(int index,int spec,int version) { (void)spec;(void)version;return events==1 ? index+1 : 2; }
static int iLinkGetLocalNodeID(void) { return 0xffc0; }
static int iLinkGetNodeMaxSpeed(int node) { (void)node;return mode==2 ? 3 : 0; }
static int iLinkTrAlloc(int node,int speed) {
    (void)node;(void)speed;CHECK(held,"context allocation serialized with I/O");
    live[allocations]=1;return allocations++;
}
static void iLinkTrFree(int ctx) {
    CHECK(held && ctx>=0 && ctx<allocations && live[ctx],"context is freed exactly once under transport mutex");
    live[ctx]=0;frees++;
}
static int iLinkGetNodeTrSpeed(int ctx) { (void)ctx;return 0; }
static int sbp2StatusReady(struct SBP2Device *dev,void *orb) { (void)dev;(void)orb;return 0; }
static int sbp2CommandAvailable(void) { CHECK(held,"pending-state checks are serialized");return !command.pending; }
void scsi_disconnect(struct scsi_interface *iface) { (void)iface;CHECK(!held,"FS detach runs outside transport mutex"); }
static int initSBP2Disk(struct SBP2Device *dev) {
    CHECK(held,"CROM/config snapshot is serialized");dev->ManagementAgent_low=0xf0004000;return 0;
}
static int initConfigureSBP2Device(struct SBP2Device *dev) {
    CHECK(!held,"SCSI warm-up can submit requests without recursive transport lock");
    if(dev->nodeID==1) {
        dev->managementPending=mode==0;
        return -1;
    }
    configured++;return 0;
}
@FUNCTION@
static void run(int scenario) {
    memset(SBP2Devices,0,sizeof(SBP2Devices));memset(live,0,sizeof(live));memset(&command,0,sizeof(command));
    for(int i=0;i<MAX_DEVICES;i++) { SBP2Devices[i].trContext=-1;SBP2Devices[i].scsi.priv=&SBP2Devices[i]; }
    mode=scenario;events=held=allocations=frees=configured=0;
    if(setjmp(done)==0) iLinkIntrCBHandlingThread(NULL);
    if(mode==2) {
        CHECK(!allocations && !configured,"invalid speed cannot index payload table or publish a device");return;
    }
    CHECK(allocations==3 && frees==2 && configured==2,"failed setup and later bus reset each release their old context");
    unsigned int slot=mode==0 ? 1 : 0;
    CHECK(SBP2Devices[slot].IsConnected && SBP2Devices[slot].nodeID==2 && SBP2Devices[slot].generation==2,
          "only successfully configured current-generation node is connected");
    if(mode==0) CHECK(SBP2Devices[0].managementPending && SBP2Devices[0].nodeID==1 && SBP2Devices[0].trContext==-1,
                      "still-live LOGIN retains its original slot across discovery and reset");
    CHECK(!held,"all paths release the transport mutex");
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0); run(0);run(1);run(2);return failures ? 1 : 0; }
"""

def run(driver):
    source=(driver/'sbp2_driver.c').read_text(encoding='utf-8')
    start=source.index('static void iLinkIntrCBHandlingThread(void *arg)\n{')
    function=source[start:source.index('\n}',start)+2]
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory);cfile=folder/'discovery.c';exe=folder/('discovery.exe' if sys.platform=='win32' else 'discovery')
        (folder/'tamtypes.h').write_text('#include <stdint.h>\ntypedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;\n')
        cfile.write_text(HARNESS.replace('@FUNCTION@',function),encoding='utf-8')
        subprocess.run(['gcc','-std=gnu99','-O2','-Wall','-Wextra','-Werror','-Wno-clobbered','-I',str(folder),
                        '-I',str(driver/'include'),str(cfile),'-o',str(exe)],check=True,timeout=60)
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
        print(str(driver)+':')
        if result.returncode == 0:
            print(result.stdout.strip() or 'PASS: reset ownership, failed contexts and pending-slot retention')
        else:
            print(result.stdout.strip() or 'FAIL: harness exited %d' % result.returncode)
            if result.stderr: print(result.stderr.strip())
        return result.returncode==0
if __name__=='__main__':
    results=[run(p) for p in DRIVERS]
    sys.exit(0 if all(results) else 1)
