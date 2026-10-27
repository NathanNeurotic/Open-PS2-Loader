"""Exercise production SBP-2 lifetime, status matching and delayed DMA paths.

Both drivers are compiled against a target/clock simulator. Only the bus, clock
and kernel mutex are substituted. Missing completions must return within their
budget without exposing caller memory or reusing remotely accessible storage.
The simulated target stores status quadlets in host order, as iLinkman does, so
the first detail quadlet is sfmt:2 status:6 | V M E I sense key:4 | ASC | ASCQ.
"""
from pathlib import Path
import argparse
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = (Path('modules/ilink/IEEE1394_bd/src'),
           Path('modules/bdmassault/ilink_bd_assault/src/IEEE1394_bd/src'))

def function(source, signature):
    start = source.index(signature + '\n{')
    return source[start:source.index('\n}', start) + 2]

TYPES = '#include <stdint.h>\ntypedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;\n'
HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "sbp2_disk.h"
#define M_DEBUG(...) ((void)0)
#define M_PRINTF(...) ((void)0)
#define BSWAP32(v) __builtin_bswap32(v)
typedef struct { u32 lo, hi; } iop_sys_clock_t;
static unsigned char storage[XFER_BLOCK_SIZE+8], caller[XFER_BLOCK_SIZE+8];
static unsigned char *writeBuffer=storage;
@STATE@
static struct SBP2Device device, other;
static struct SBP2Device *target;
static const void *target_orb;
static unsigned long long now_us, due_us, delay_us;
static unsigned int result_status, foreign_status, captured;
static int suppress_reply, pointer_error, reset_error, submitted, notified, generation;
static int failures, held, reset_calls, reset_value,polls,partial_status;
static u32 detail;
#define DETAIL(sfmt,sam,key,asc,ascq) (((u32)(sfmt)<<30)|((u32)(sam)<<24)|((u32)(key)<<16)|((u32)(asc)<<8)|(u32)(ascq))
static void set_detail(struct SBP2Device *dev,u32 value) { memcpy((void *)dev->statusFIFO.data,&value,4); }
static unsigned char published_data[8];
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL: %s\n",msg);failures++; } } while(0)
static void GetSystemTime(iop_sys_clock_t *c) { c->lo=now_us; c->hi=now_us>>32; }
static void SysClock2USec(iop_sys_clock_t *c,u32 *s,u32 *u) {
    unsigned long long n=((u64)c->hi<<32)|c->lo; *s=n/1000000; *u=n%1000000;
}
static int iLinkGetGenerationNumber(void) { return generation; }
static int WaitSema(int id) { (void)id; CHECK(!held,"request mutex is not recursively acquired"); held=1; return 0; }
static int SignalSema(int id) { (void)id;CHECK(held,"request releases its mutex");held=0;return 0; }
static void deliver(void) {
    if(target_orb==&target->managementORB) {
        target->loginResponse.command_block_agent.high=0xffff;
        target->loginResponse.command_block_agent.low=0xf0010000;
        target->loginResponse.login_ID=7;
    } else if(target_orb==&command.cdb && (command.cdb.misc&(1u<<27)) && (command.cdb.misc&0xffff)) {
        /* Model target writes to the advertised resident data buffer. */
        u32 word=0x11223344;
        memcpy(writeBuffer,&word,4);memcpy(writeBuffer+4,&word,4);
    }
    if(((result_status>>24)&7)>1)
        set_detail(target,detail);
    target->statusFIFO.ORB_low=(u32)target_orb;
    target->statusFIFO.status=result_status;
    notified=1;
}
static int DelayThread(unsigned int usec) {
    now_us+=usec;polls++;
    if(partial_status && now_us==50) {
        target->statusFIFO.ORB_low=(u32)target_orb;
        target->statusFIFO.status=result_status;
    }
    if(foreign_status && now_us==50) {
        target->statusFIFO.status=foreign_status;
        target->statusFIFO.ORB_low=0xdeadbeef;
    }
    if(submitted && !notified && !suppress_reply && now_us>=due_us) deliver();
    return 0;
}
static int iLinkTrWrite(int ctx,unsigned long high,unsigned long low,void *buffer,unsigned int bytes) {
    (void)ctx;(void)high;
    CHECK(held,"pointer/reset publication is serialized");
    if(bytes==4) {
        reset_calls++;
        reset_value=*(u32 *)buffer;
        return reset_error ? -1024 : 4;
    }
    CHECK(bytes==8,"ORB pointer uses exactly eight bytes");
    target=low==device.ManagementAgent_low ? &device : command.owner;
    if(target==NULL) target=&device;
    target_orb=low==target->ManagementAgent_low ? (void *)&target->managementORB : (void *)command.orb;
    CHECK(((struct sbp2_pointer *)buffer)->low==(u32)target_orb,"publish the resident ORB address");
    CHECK(buffer==(target_orb==&target->managementORB ? (void *)&target->managementPointer : (void *)&command.pointer),
          "published pointer storage is resident too");
    if(target_orb==&command.cdb) memcpy(published_data,writeBuffer,sizeof(published_data));
    submitted++;
    due_us=now_us+delay_us;
    captured=command.cdb.misc;
    if(!delay_us && !suppress_reply) deliver();
    return pointer_error ? -1024 : 8;
}
@FUNCTIONS@
static void reset_case(void) {
    memset(&device,0,sizeof(device));memset(&other,0,sizeof(other));
    memset(&command,0,sizeof(command));memset(storage,0xa5,sizeof(storage));memset(caller,0xcc,sizeof(caller));
    now_us=due_us=0;delay_us=500;result_status=(1u<<30)|(1u<<24);foreign_status=0;
    suppress_reply=pointer_error=reset_error=submitted=notified=reset_calls=held=0;generation=1;
    polls=partial_status=0;detail=0;memset(published_data,0,sizeof(published_data));
    target=NULL;target_orb=NULL;device.IsConnected=1;device.generation=1;device.ORB_size=8;
    device.scsi.priv=&device;device.scsi.timeout_us=2000;device.ManagementAgent_low=0xf0004000;
    other.scsi.priv=&other;other.IsConnected=1;other.generation=1;other.scsi.timeout_us=2000;
}
static int queue(unsigned int bytes,unsigned int write) {
    unsigned char cmd[12]={0x28};
    return sbp2_queue_cmd(&device.scsi,cmd,12,caller,bytes,write);
}
int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    static const unsigned int delays[]={0,50,500,1500};
    for(unsigned int offset=0;offset<4;offset++) {
        for(unsigned int length=1;length<=8;length++) {
            reset_case();
            unsigned char cmd[16]={0};cmd[1]=0x28;
            CHECK(sbp2_queue_cmd(&device.scsi,cmd+1,12,caller+offset,length,0)==0,
                  "unaligned CDB and caller buffers remain supported");
            const unsigned char expected[8]={0x11,0x22,0x33,0x44,0x11,0x22,0x33,0x44};
            CHECK(!memcmp(caller+offset,expected,length),"read converts every requested byte in order");
            CHECK(caller[offset+length]==0xcc && (!offset || caller[offset-1]==0xcc),
                  "partial read preserves both caller boundary canaries");
        }
    }
    for(unsigned int offset=0;offset<4;offset++) {
        reset_case();
        unsigned char cmd[16]={0};cmd[1]=0x2a;
        const unsigned char input[8]={0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88};
        const unsigned char wire[8]={0x44,0x33,0x22,0x11,0x88,0x77,0x66,0x55};
        memcpy(caller+offset,input,sizeof(input));
        CHECK(sbp2_queue_cmd(&device.scsi,cmd+1,12,caller+offset,8,1)==0,
              "aligned and unaligned write sources remain supported");
        CHECK(!memcmp(published_data,wire,sizeof(wire)),"write publishes the exact endian-converted words");
        CHECK(!memcmp(caller+offset,input,sizeof(input)) && caller[offset+8]==0xcc,
              "write conversion leaves caller data and boundary untouched");
    }
    for(unsigned int i=0;i<4;i++) {
        reset_case();delay_us=delays[i];
        device.statusFIFO.status=result_status;device.statusFIFO.ORB_low=(u32)&device.managementORB;
        CHECK(queue(4,0)==0 && notified && now_us>=delay_us,"command waits for its own immediate/delayed status");
        CHECK(caller[0]==0x11 && caller[1]==0x22 && caller[2]==0x33 && caller[3]==0x44,
              "read payload is endian-converted from resident staging");
        CHECK(caller[4]==0xcc,"read preserves bytes beyond requested length");
    }
    reset_case();pointer_error=1;delay_us=1000;
    CHECK(queue(4,0)==0 && notified && submitted==1,"lost pointer ACK waits for completion without duplicate execution");
    reset_case();foreign_status=(1u<<30)|(1u<<24);delay_us=1000;
    CHECK(queue(4,0)==0 && now_us>=1000,"foreign ORB status cannot release the live request");
    reset_case();result_status=1u<<24;
    CHECK(queue(4,0)==0 && notified,"source-zero ORB completion is accepted");
    for(unsigned int source=2;source<=3;source++) {
        reset_case();result_status=(source<<30)|(1u<<24);
        CHECK(queue(4,0)<0 && command.pending && now_us>=2000,"unsolicited status cannot complete a command");
    }
    reset_case();result_status=(1u<<30)|(1u<<24)|1;
    CHECK(queue(4,0)<0 && command.pending,"nonzero ORB high address cannot match IOP request");
    reset_case();result_status=(1u<<30)|(2u<<24)|(2u<<16);
    CHECK(queue(4,0)==-1 && !command.pending,"failed matching completion retires storage and reports error");
    set_detail(&device,DETAIL(0,2,5,0x24,0x00));
    CHECK(ProcessStatus(&device,&command.cdb)==-5,"SCSI sense key comes from bits 16-19 of the detail quadlet");

    reset_case();result_status=(1u<<30)|(2u<<24);partial_status=1;
    CHECK(queue(4,0)==0 && notified && now_us>=500,
          "extended SCSI GOOD status succeeds after its status data arrives");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(0,2,2,0x04,0x01);
    CHECK(queue(4,0)==-2 && !command.pending && caller[0]==0xcc,
          "extended CHECK CONDITION reports sense without copying invalid read data");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(0,2,3,0x11,0x00);
    CHECK(queue(4,0)==-3 && !command.pending && caller[0]==0xcc,
          "a CHECK CONDITION whose ASCQ is 0 (unrecovered read error) is not GOOD");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(0,2,6,0x29,0x00);
    CHECK(queue(4,0)==-6 && !command.pending,"a UNIT ATTENTION after a bus reset reports sense key 6");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(0,2,4,0x44,0xff);
    CHECK(queue(4,0)==-4 && !command.pending && now_us<2000,
          "an ASCQ of 0xff does not look like a status that has not arrived");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(2,0,0,0,0);
    CHECK(queue(4,0)<0 && !command.pending,"reserved extended status format is refused");
    reset_case();result_status=(1u<<30)|(2u<<24);detail=DETAIL(1,0,0,0,0);
    CHECK(queue(4,0)==0 && !command.pending,"a deferred-format GOOD status succeeds");
    reset_case();result_status|=1u<<27;
    CHECK(queue(4,0)<0 && device.fetchAgentNeedsReset && !command.pending,
          "DEAD status retires completed request and remembers agent recovery");
    result_status=(1u<<30)|(1u<<24);notified=0;
    CHECK(queue(4,0)==0 && reset_calls==1 && reset_value==0 && !device.fetchAgentNeedsReset,
          "reset a dead fetch agent before retrying SCSI");

    reset_case();suppress_reply=1;
    CHECK(queue(4,0)<0 && command.pending && now_us==2000,"missing status returns within budget with request retained");
    CHECK(command.cdb.DataDescriptor.low==(u32)writeBuffer,"target writes to staging, never the returned caller buffer");
    unsigned char orb_copy[sizeof(command.cdb)];memcpy(orb_copy,command.orb,sizeof(command.cdb));
    unsigned char stage_copy[XFER_BLOCK_SIZE];memcpy(stage_copy,writeBuffer,sizeof(stage_copy));
    CHECK(queue(8,1)<0 && submitted==1,"uncertain request is not republished or overwritten");
    CHECK(!memcmp(orb_copy,command.orb,sizeof(command.cdb)) && !memcmp(stage_copy,writeBuffer,sizeof(stage_copy)),
          "quarantined ORB and data remain unchanged");
    unsigned char cmd[12]={0x28};
    CHECK(sbp2_queue_cmd(&other.scsi,cmd,12,caller,4,0)<0 && submitted==1,
          "another device cannot reuse the live shared staging buffer");
    deliver(); /* A very late target write occurs after the caller has returned. */
    CHECK(caller[0]==0xcc && caller[4]==0xcc,"late DMA cannot alter the returned caller buffer");
    suppress_reply=0;notified=0;delay_us=50;
    CHECK(queue(4,0)==0 && submitted==2,"late matching completion allows the next request to proceed");

    reset_case();generation=2;
    CHECK(queue(4,0)<0 && submitted==0,"old-generation device cannot publish a new request");
    reset_case();suppress_reply=1;queue(4,0);generation=2;
    CHECK(queue(4,0)<0 && command.pending && submitted==1,"bus reset alone does not authorize live storage reuse");

    for(unsigned int i=0;i<4;i++) {
        reset_case();delay_us=delays[i];result_status|=0x0bu<<16;
        device.statusFIFO.status=(1u<<30)|(1u<<24);
        CHECK(ieee1394_InitializeFetchAgent(&device)==0 && notified && now_us>=delay_us,
              "dummy ORB waits for its own completion, preserving immediate replies");
        CHECK(reset_calls==1 && reset_value==0,"fetch-agent reset transmits initialized data");
    }
    reset_case();device.ORB_size=0;
    CHECK(ieee1394_InitializeFetchAgent(&device)<0 && !submitted,"undersized dummy ORB is refused");
    reset_case();reset_error=1;
    CHECK(ieee1394_InitializeFetchAgent(&device)<0 && !submitted,"failed agent reset does not publish a dummy ORB");
    reset_case();suppress_reply=1;
    CHECK(ieee1394_InitializeFetchAgent(&device)<0 && command.pending && now_us==SBP2_COMMAND_BUDGET_US,
          "missing dummy status is bounded without freeing its resident ORB");
    CHECK(polls<40000,"slow-tail backoff avoids hundreds of thousands of timeout wakeups");

    reset_case();pointer_error=1;
    CHECK(ieee1394_SendManagementORB(SBP2_LOGIN_REQUEST,&device)==0 && notified && submitted==1,
          "LOGIN survives a lost pointer ACK and uses its actual reply");
    CHECK(device.CommandBlockAgent_low==0xf0010000 && !device.managementPending,"successful matching LOGIN installs agent");
    reset_case();suppress_reply=1;
    CHECK(ieee1394_SendManagementORB(SBP2_LOGIN_REQUEST,&device)<0 && device.managementPending,
          "timed-out LOGIN retains all remotely visible request storage");
    struct management_ORB saved=device.managementORB;
    CHECK(ieee1394_SendManagementORB(SBP2_LOGIN_REQUEST,&device)<0 && submitted==1 &&
          !memcmp(&saved,&device.managementORB,sizeof(saved)),"pending LOGIN cannot be overwritten by retry");
    deliver();
    CHECK(ieee1394_SendManagementORB(SBP2_LOGIN_REQUEST,&device)==0 && submitted==1,
          "late matching LOGIN is collected without duplicate publication");
    CHECK(!held,"every path releases the transport mutex");
    return failures ? 1 : 0;
}
"""

def run(driver):
    source=(driver/'sbp2_driver.c').read_text(encoding='utf-8')
    state=source[re.search(r'static struct\s*\{',source).start():source.index('\n\n',source.index('#define SBP2_COMMAND_BUDGET_US'))]
    signatures=(
        'static u32 sbp2ElapsedUs(const iop_sys_clock_t *start)',
        'static void sbp2CopySwapped(void *destination, const void *source, unsigned int nQuads)',
        'static int sbp2StatusReady(struct SBP2Device *dev, const void *orb)',
        'static int ProcessStatus(struct SBP2Device *dev, const void *orb)',
        'static int sbp2WaitStatus(struct SBP2Device *dev, const void *orb, u32 budget_us)',
        'static int sbp2CommandAvailable(void)',
        'static int sbp2PublishCommand(struct SBP2Device *dev, u32 budget_us)',
        'static int ieee1394_ResetFetchAgent(struct SBP2Device *dev)',
        'static int ieee1394_InitializeFetchAgent(struct SBP2Device *dev)',
        'static int ieee1394_SendManagementORB(int mode, struct SBP2Device *dev)',
        'static int sbp2_queue_cmd(struct scsi_interface *scsi, const unsigned char *cmd, unsigned int cmd_len, unsigned char *data, unsigned int data_len, unsigned int data_wr)',
    )
    functions='\n\n'.join(function(source,s) for s in signatures)
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory);cfile=folder/'completion.c';exe=folder/('completion.exe' if sys.platform=='win32' else 'completion')
        (folder/'tamtypes.h').write_text(TYPES,encoding='utf-8')
        text=HARNESS.replace('@STATE@',state).replace('@FUNCTIONS@',functions)
        text=text.replace('@LOGIN_BUDGET@','5000000')
        cfile.write_text('#define SBP2_LOGIN_BUDGET_US 5000000\n'+text,encoding='utf-8')
        subprocess.run(['gcc','-std=gnu99','-O2','-Wall','-Wextra','-Werror','-Wno-pointer-to-int-cast',
                        '-I',str(folder),'-I',str(driver/'include'),str(cfile),'-o',str(exe)],check=True,timeout=60)
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
        print(str(driver)+':')
        if result.returncode == 0:
            print(result.stdout.strip() or 'PASS: matched status, bounded waits, persistent requests and late-DMA isolation')
        else:
            print(result.stdout.strip() or 'FAIL: harness exited %d' % result.returncode)
            if result.stderr: print(result.stderr.strip())
        return result.returncode==0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    args=parser.parse_args()
    results=[run(args.source_root/p) for p in DRIVERS]
    sys.exit(0 if all(results) else 1)
