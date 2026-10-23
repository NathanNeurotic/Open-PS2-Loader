"""Check real manager packet bounds, CROM updates and concurrent client requests.

FIFO reads and physical IOP addresses are mapped into host storage; packet
parsing and copy lengths remain production code. Public API concurrency uses
real host threads and a single shared reply pointer, as the manager does.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
MANAGERS=(ROOT/'modules/ilink/iLinkman/src',ROOT/'modules/bdmassault/ilink_bd_assault/src/iLinkman/src')
def function(source, signature):
    match=re.search(r'^'+re.escape(signature)+r'[^;{]*\)\s*\{',source,re.M)
    assert match,signature
    return source[match.start():source.index('\n}',match.start())+2]

PREAMBLE=r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#include "iLink_internal.h"
#undef DEBUG_PRINTF
#define DEBUG_PRINTF(...) ((void)0)
#define iLink_CB_WRITE_REQUEST 1
#define iLink_CB_READ_REQUEST 2
#define BSWAP32(v) __builtin_bswap32(v)
#define BSWAP16(v) __builtin_bswap16(v)
static int failures;
#define CHECK(c,msg) do { if(!(c)) { printf("FAIL %s\n",msg);failures++; } } while(0)
"""
PACKET=r"""
static unsigned int fifo[64],head,tail,responses,rcode,callbacks;
static unsigned char ram[0x200000];
static unsigned int rom[16],*ConfigurationROM=rom,ConfigurationROMSize=sizeof(rom);
static void (*CallBackFunction)(int,unsigned int,unsigned int);
static unsigned int read_fifo(volatile unsigned int *p) {
    (void)p;CHECK(head<tail,"parser cannot read beyond available FIFO");return head<tail ? fifo[head++] : 0;
}
void SendResponse(unsigned short a,unsigned short b,unsigned char c,unsigned char d,
                         unsigned char e,unsigned char f,unsigned int *g,unsigned int h) {
    (void)a;(void)b;(void)d;(void)e;(void)f;(void)g;(void)h;responses++;rcode=c;
}
static void callback(int reason,unsigned int offset,unsigned int size) {
    (void)reason;(void)offset;(void)size;callbacks++;
}
@FUNCTIONS@
static void packet(unsigned int address,unsigned int high,unsigned int bytes,int quad,int truncated) {
    memset(ram,0xcc,sizeof(ram));head=tail=responses=callbacks=rcode=0;
    fifo[tail++]=high;fifo[tail++]=address;
    if(!quad) fifo[tail++]=bytes<<16;
    for(unsigned int i=0;i<(bytes+3)/4;i++) fifo[tail++]=0x11223344;
    if(!truncated) fifo[tail++]=0x20000;
    unsigned int available=tail;
    fifo[tail++]=0xdeadbeef; /* next packet must remain untouched */
    WriteRequestHandler((quad ? IEEE1394_TCODE_WRITEQ : IEEE1394_TCODE_WRITEB)<<4,fifo,available);
    CHECK(head==available,"consume exactly the declared packet, including rejected payload and trailer");
    CHECK(fifo[head]==0xdeadbeef,"preserve following packet in receive FIFO");
}
static void read_packet(unsigned int address,unsigned int high,unsigned int bytes,int quad,int truncated) {
    head=tail=responses=callbacks=rcode=0;
    fifo[tail++]=quad ? high : BSWAP32(high);fifo[tail++]=quad ? address : BSWAP32(address);
    if(!quad) fifo[tail++]=bytes<<16;
    if(!truncated) fifo[tail++]=0;
    unsigned int available=tail;fifo[tail++]=0xdeadbeef;
    ReadRequestHandler((quad ? IEEE1394_TCODE_READQ : IEEE1394_TCODE_READB)<<4,fifo,available);
    CHECK(head==available && fifo[head]==0xdeadbeef,"read request preserves the following FIFO packet");
}
int main(void) {
    CallBackFunction=callback;
    packet(0x1000,0,4,1,0);
    CHECK(responses==1 && rcode==0 && callbacks==1,"quadlet request reports its four-byte write");
    CHECK(ram[0x1000]==0x44 && ram[0x1003]==0x11 && ram[0x1004]==0xcc,"quadlet payload reaches memory without overrun");
    packet(0x1001,0,5,0,0);
    CHECK(responses==1 && !rcode && callbacks==1,"unaligned partial block is accepted within RAM");
    CHECK(ram[0x1000]==0xcc && ram[0x1001]==0x44 && ram[0x1005]==0x44 && ram[0x1006]==0xcc,
          "partial final quadlet cannot overwrite adjacent memory");
    packet(0x1ffffc,0,4,0,0);
    CHECK(!rcode && ram[0x1fffff]==0x11,"write ending at RAM boundary is accepted");
    const unsigned int bad[]={0,0x1fffff,0x200000,0xfffffffcu};
    for(unsigned int i=0;i<4;i++) {
        packet(bad[i],0,4,0,0);
        CHECK(responses==1 && rcode==6 && callbacks==0,"out-of-range write drains packet and reports address error");
        CHECK(ram[0]==0xcc && ram[0x1fffff]==0xcc,"rejected write cannot touch RAM");
    }
    packet(0x1000,1,4,0,0);
    CHECK(rcode==6 && !callbacks,"nonzero high physical address is refused");
    packet(0x1000,0,8,0,1);
    CHECK(!responses && !callbacks && ram[0x1000]==0xcc,"truncated packet drains available input without copying");
    read_packet(0xf0000400,0xffff,64,0,0);
    CHECK(responses==1 && !rcode && callbacks==1,"full CROM read stays within its installed size");
    read_packet(0xf000043c,0xffff,8,0,0);
    CHECK(responses==1 && rcode==6 && !callbacks,"CROM read cannot cross its final byte");
    read_packet(0x1ffffc,0,8,0,0);
    CHECK(rcode==6 && !callbacks,"RAM read cannot cross physical memory boundary");
    read_packet(0x1000,1,4,1,0);
    CHECK(rcode==6 && !callbacks,"read cannot use a nonzero high physical address");
    read_packet(0x1000,0,4,1,1);
    CHECK(!responses && !callbacks,"truncated read header is drained without a response");
    return failures ? 1 : 0;
}
"""
CROM=r"""
#include "iLink_CROM.h"
static void *ExtraCROMUnits[16];
static unsigned int ExtraCROMUnitsSize[16],nExtraCROMUnits;
static unsigned int *ConfigurationROM,ConfigurationROMSize;
static unsigned char LinkSpeed=4,CycleClkAcc=255,Max_Rec=10;
static u64 ConsoleGUID;
static char ConsoleModelName[32]="SCPH-10000";
static int NodeCapabilities,fail_alloc,alloc_calls,fail_at;
static unsigned char pool[65536];static unsigned int used;
static void *host_alloc(unsigned int n) {
    alloc_calls++;
    if(fail_alloc || alloc_calls==fail_at) return NULL;
    unsigned int at=used;used=(used+n+7)&~7u;CHECK(used<=sizeof(pool),"fixture pool");return pool+at;
}
static void host_free(void *p) { (void)p; }
#define malloc host_alloc
#define free host_free
static void BuildConfigurationROM(void);
@FUNCTIONS@
static u32 rom_word(u32 word) {
#ifdef POPS_CROM
    return BSWAP32(word);
#else
    return word;
#endif
}
static unsigned int rom_length(struct DirectoryHeader *h) {
#ifdef POPS_CROM
    return BSWAP16(h->Directory_length);
#else
    return h->Directory_length;
#endif
}
static void check_leaf(unsigned int extras) {
    unsigned int root_at=sizeof(struct BusInformationBlockHeader)+sizeof(struct BusInformationBlock)+sizeof(struct DirectoryHeader);
    struct Root_Directory *root=(void *)((unsigned char *)ConfigurationROM+root_at);
    unsigned int offset=rom_word(root->Module_Vendor_ID_Offset)&0xffffff;
    CHECK(offset==extras+1,"ModuleVendor leaf offset uses all extra quadlets");
    struct DirectoryHeader *leaf=(void *)((unsigned char *)&root->Module_Vendor_ID_Offset+4*offset);
    CHECK(rom_length(leaf)==1,"relative vendor pointer reaches the actual leaf");
    u32 *vendor=&root->Module_Vendor_ID_Texual_Descriptor_Offset;
    CHECK((rom_word(*vendor)>>24)==0x81,"vendor text entry uses the descriptor leaf key");
    struct DirectoryHeader *text=(void *)((unsigned char *)vendor+4*(rom_word(*vendor)&0xffffff));
    CHECK(rom_length(text)==3,"vendor text pointer reaches its descriptor");
    u32 *uid=&root->Node_Unique_ID_Offset;
    struct DirectoryHeader *unique=(void *)((unsigned char *)uid+4*(rom_word(*uid)&0xffffff));
    CHECK(rom_length(unique)==2,"node ID pointer reaches its two-quadlet leaf");
    struct Module_Vendor_Id *module=(void *)(leaf+1);
    struct DirectoryHeader *model=(void *)((unsigned char *)&module->Textual_Descriptor+4*(rom_word(module->Textual_Descriptor)&0xffffff));
    CHECK(rom_length(model)==sizeof(struct ModelID_Textual_Descriptor)/4,
          "module text descriptor points at the model leaf");
}
int main(void) {
    BuildConfigurationROM();check_leaf(0);
    unsigned int data[5]={1,2,3,4,5};
    int first=iLinkAddCROMUnit(data,3),second=iLinkAddCROMUnit(data,5);
    CHECK(first>=0 && second>=0 && nExtraCROMUnits==2,"two extra units install");check_leaf(8);
    unsigned int size=ConfigurationROMSize;void *rom=ConfigurationROM;
    fail_at=alloc_calls+2;
    int third=iLinkAddCROMUnit(data,1); /* unit copy succeeds; larger ROM allocation fails */
    CHECK(third>=0 && ConfigurationROM==rom && ConfigurationROMSize==size,
          "failed larger rebuild preserves installed ROM and its true size");
    fail_at=0;iLinkDeleteCROMUnit(third);
    iLinkDeleteCROMUnit(16);iLinkDeleteCROMUnit(10000);
    CHECK(nExtraCROMUnits==2,"invalid delete cannot change unit count");
    iLinkDeleteCROMUnit(first);check_leaf(5);
    CHECK(nExtraCROMUnits==1,"delete decrements before rebuilding");
    iLinkDeleteCROMUnit(first);CHECK(nExtraCROMUnits==1,"duplicate delete is harmless");
    iLinkDeleteCROMUnit(second);check_leaf(0);CHECK(!nExtraCROMUnits,"last delete restores base ROM");
    return failures ? 1 : 0;
}
"""
CLIENT=r"""
#include <pthread.h>
#include <unistd.h>
static struct TransactionContextData TransactionContexts[MAX_CONCURRENT_TRANSACTIONS];
static int RequestSema,GenerationNumber=1;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t wait_notice=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wait_entered=PTHREAD_COND_INITIALIZER;
static int waiting;
static unsigned int *TargetBuffer;
static int WaitSema(int s) {
    (void)s;pthread_mutex_lock(&wait_notice);waiting++;
    pthread_cond_signal(&wait_entered);pthread_mutex_unlock(&wait_notice);
    return pthread_mutex_lock(&mutex);
}
static int SignalSema(int s) { (void)s;return pthread_mutex_unlock(&mutex); }
static int CpuSuspendIntr(int *s) { *s=0;return 0; }
static int CpuResumeIntr(int s) { (void)s;return 0; }
void iLinkFinishRequest(void) {}
static int transfer(struct TransactionContextData *ctx, unsigned short high,unsigned int low,void *buffer,unsigned int count) {
    (void)high;(void)low;(void)count;
    if(ctx->GenerationNumber!=GenerationNumber) return -1021;
    TargetBuffer=buffer;usleep(3000);*TargetBuffer=ctx->NodeID;return 0;
}
#define iLinkReadReq transfer
#define iLinkWriteReq transfer
#define iLinkReadPHTReq transfer
#define iLinkWritePHTReq transfer
@FUNCTIONS@
struct task { int id,count,result;unsigned int value; };
static void *worker(void *arg) {
    struct task *t=arg;
    t->result=iLinkTrRead(t->id,0,0,&t->value,t->count);return NULL;
}
int main(void) {
    for(int i=0;i<2;i++) TransactionContexts[i]=(struct TransactionContextData){1,(unsigned short)(0x1111*(i+1)),1,0};
    for(int i=0;i<30;i++) {
        pthread_t a,b;struct task first={0,4,0,0},second={1,8,0,0};
        pthread_create(&a,NULL,worker,&first);pthread_create(&b,NULL,worker,&second);
        pthread_join(a,NULL);pthread_join(b,NULL);
        CHECK(first.result==0 && second.result==0 && first.value==0x1111 && second.value==0x2222,
              "concurrent quadlet/block clients retain their own shared reply pointer");
    }
    unsigned int value=0;
    CHECK(iLinkTrWrite(-1,0,0,&value,4)==-1002 && iLinkTrRead(MAX_CONCURRENT_TRANSACTIONS,0,0,&value,4)==-1002,
          "invalid context indices cannot touch the context table");
    CHECK(iLinkTrRead(9,0,0,&value,4)==-1002,"disconnected context is refused");
    pthread_mutex_lock(&mutex);pthread_t waiter;struct task stale={0,4,0,0};
    pthread_mutex_lock(&wait_notice);waiting=0;
    pthread_create(&waiter,NULL,worker,&stale);
    while(!waiting) pthread_cond_wait(&wait_entered,&wait_notice);
    pthread_mutex_unlock(&wait_notice);
    TransactionContexts[0]=(struct TransactionContextData){2,0x7777,1,0};GenerationNumber=2;
    pthread_mutex_unlock(&mutex);pthread_join(waiter,NULL);
    CHECK(stale.result==-1021 && stale.value==0,"queued request keeps its original generation despite context-slot reuse");
    return failures ? 1 : 0;
}
"""


RESPONSE=r"""
static unsigned int fifo[64],head,tail,flags,TargetBufferSize;
static unsigned int *TargetBuffer,LocalCachedIntr0Register;
static int IntrEventFlag,GenerationNumber=1,critical;
@STATE@
static int CpuSuspendIntr(int *state) { *state=critical;critical=1;return 0; }
static int CpuResumeIntr(int state) { critical=state;return 0; }
static int SetEventFlag(int id,unsigned int bits) {
    (void)id;CHECK(critical,"copy and response notification are retired atomically");flags|=bits;return 0;
}
static unsigned int read_fifo(volatile unsigned int *p) {
    (void)p;CHECK(head<tail,"response parser stays within available FIFO");return head<tail ? fifo[head++] : 0;
}
@FUNCTIONS@
static void response(unsigned int code,unsigned int label,unsigned int node,unsigned int error,unsigned int bytes,int truncated) {
    head=tail=flags=0;
    fifo[tail++]=(node<<16)|(error<<12);fifo[tail++]=0;
    if(code!=IEEE1394_TCODE_WRITE_RESPONSE) fifo[tail++]=code==IEEE1394_TCODE_READQ_RESPONSE ? 0x11223344 : bytes<<16;
    if(code==IEEE1394_TCODE_READB_RESPONSE) for(unsigned int i=0;i<(bytes+3)/4;i++) fifo[tail++]=0x11223344;
    if(!truncated) fifo[tail++]=0;
    unsigned int available=tail;fifo[tail++]=0xdeadbeef;
    ResponseHandler((label<<10)|(code<<4),fifo,available);
    CHECK(head==available && fifo[head]==0xdeadbeef,"responses drain exactly their packet, preserving the next one");
}
int main(void) {
    (void)TargetBufferSize;
    struct TransactionContextData context={1,0xffc1,1,0};
    unsigned int data[3]={0xa5a5a5a5,0xcccccccc,0xcccccccc};
    iLinkPrepareResponse(&context,1,IEEE1394_TCODE_READQ_RESPONSE,data,4);
    response(IEEE1394_TCODE_READQ_RESPONSE,1,0xffc1,0,0,0);
    CHECK(flags==iLinkEventDataReceived && data[0]==BSWAP32(0x11223344u) && data[1]==0xcccccccc,
          "matching quadlet response copies exactly one word");
    CHECK(!TargetBuffer && !ResponseActive,"completed response retires its caller pointer");
    data[0]=0xa5a5a5a5;
    response(IEEE1394_TCODE_READQ_RESPONSE,1,0xffc1,0,0,0);
    CHECK(!flags && data[0]==0xa5a5a5a5,"orphan response cannot touch retired caller memory");
    iLinkPrepareResponse(&context,2,IEEE1394_TCODE_READQ_RESPONSE,data,4);
    response(IEEE1394_TCODE_READQ_RESPONSE,1,0xffc1,0,0,0);
    CHECK(!flags && data[0]==0xa5a5a5a5 && ResponseActive,"old transaction label cannot complete the current request");
    response(IEEE1394_TCODE_READQ_RESPONSE,2,0xffc2,0,0,0);
    CHECK(!flags && data[0]==0xa5a5a5a5,"foreign source node cannot complete the current request");
    response(IEEE1394_TCODE_READQ_RESPONSE,2,0xffc1,6,0,0);
    CHECK(flags==iLinkEventRequestError && data[0]==0xa5a5a5a5,"error response reports failure without copying invalid data");
    iLinkPrepareResponse(&context,63,IEEE1394_TCODE_READB_RESPONSE,data,5);
    response(IEEE1394_TCODE_READB_RESPONSE,63,0xffc1,0,8,0);
    CHECK(flags==iLinkEventRequestError && data[0]==0xa5a5a5a5,"oversized block response cannot overrun caller memory");
    iLinkPrepareResponse(&context,63,IEEE1394_TCODE_READB_RESPONSE,data,5);
    response(IEEE1394_TCODE_READB_RESPONSE,63,0xffc1,0,5,0);
    CHECK(flags==iLinkEventDataReceived && ((unsigned char *)data)[4]==0x44 && ((unsigned char *)data)[5]==0xcc,
          "partial final quadlet respects the exact caller byte count");
    iLinkPrepareResponse(&context,3,IEEE1394_TCODE_READQ_RESPONSE,data,4);
    iLinkFinishRequest();data[0]=0xa5a5a5a5;
    response(IEEE1394_TCODE_READQ_RESPONSE,3,0xffc1,0,0,0);
    CHECK(!flags && data[0]==0xa5a5a5a5,"timeout retirement ignores late response");
    iLinkPrepareResponse(&context,3,IEEE1394_TCODE_READQ_RESPONSE,data,4);GenerationNumber++;
    response(IEEE1394_TCODE_READQ_RESPONSE,3,0xffc1,0,0,0);
    CHECK(!flags && data[0]==0xa5a5a5a5,"old-generation response cannot alter caller memory");
    GenerationNumber=1;iLinkPrepareResponse(&context,63,IEEE1394_TCODE_READB_RESPONSE,data,8);
    response(IEEE1394_TCODE_READB_RESPONSE,63,0xffc1,0,8,1);
    CHECK(!flags && data[0]==0xa5a5a5a5,"truncated response cannot copy a partial payload");
    return failures ? 1 : 0;
}
"""


STARTUP=r"""
#define MODULE_RESIDENT_END 0
#define MODULE_NO_RESIDENT_END 1
#define IOP_MUTEX_UNLOCKED 1
#define IOP_IRQ_ILINK 37
#define TH_C 0
struct event { int unused; };typedef struct { int attr,option;void (*thread)(void *);int stacksize,priority; } iop_thread_t;
static struct event EventFlagData;
static int _exp_iLinkman,IntrEventFlag,UBUFTxSema,RequestSema,UBUFThreadID;
static unsigned int rom[32],*ConfigurationROM;
static u64 ConsoleGUID;static char ConsoleModelName[32];
static struct TransactionContextData TransactionContexts[MAX_CONCURRENT_TRANSACTIONS];
static void (*CallBackFunction)(int,unsigned int,unsigned int);
static int fail_case,events,mutexes,mutex_calls,threads,running,irq,library,rom_live,hardware;
void iLinkDisableIntr(void) {}
int iLinkResetHW(void) { return 0; }
void iLinkHWInitialize(void) { hardware=1; }
void iLinkShutdownHW(void) { hardware=0; }
int GetConsoleIDs(u64 *guid,char *name) { *guid=0;name[0]=0;return 0; }
void InitializeConfigurationROM(void) { ConfigurationROM=rom;rom_live=1; }
static unsigned int GetBIOSVersion(void) { return 0x160; }
void UBUFThread(void *arg) { (void)arg; }
int iLinkIntrHandler(void *arg) { (void)arg;return 0; }
static int CreateEventFlag(void *p) { (void)p;if(fail_case==1) return -1;events++;return 10; }
static int DeleteEventFlag(int id) { CHECK(id==10 && events==1,"release created event");events--;return 0; }
static int CreateMutex(int locked) {
    (void)locked;if(++mutex_calls==2 && fail_case==2) return -1;mutexes++;return 10+mutex_calls;
}
static int DeleteSema(int id) { CHECK(id>=11 && id<=12 && mutexes>0,"release created mutex");mutexes--;return 0; }
static int CreateThread(iop_thread_t *data) { (void)data;threads++;return 20; }
static int StartThread(int id,void *arg) { (void)id;(void)arg;if(fail_case==3) return -1;running++;return 0; }
static int TerminateThread(int id) { CHECK(id==20 && running==1,"terminate active receive thread");running--;return 0; }
static int DeleteThread(int id) { CHECK(id==20 && threads==1,"delete receive thread");threads--;return 0; }
static int RegisterIntrHandler(int id,int mode,void *fn,void *arg) { (void)id;(void)mode;(void)fn;(void)arg;irq=1;return 0; }
static int EnableIntr(int id) { (void)id;return 0; }
static int DisableIntr(int id,int *state) { (void)id;*state=0;return 0; }
static int ReleaseIntrHandler(int id) { (void)id;irq=0;return 0; }
static int RegisterLibraryEntries(void *table) { (void)table;if(fail_case==4) return -1;library=1;return 0; }
static int ReleaseLibraryEntries(void *table) { (void)table;library=0;return 0; }
static int FreeSysMemory(void *p) { CHECK(p==rom && rom_live,"ROM allocation is released once");rom_live=0;return 0; }
int BD_iLink_start(int argc,char **argv) { (void)argc;(void)argv;return fail_case==5 ? 1 : 0; }
int _exit(int argc,char *argv[]);
@FUNCTIONS@
int main(void) {
    for(fail_case=0;fail_case<=4+POPS_STARTUP;fail_case++) {
        events=mutexes=mutex_calls=threads=running=irq=library=rom_live=hardware=0;
        int result=_start(0,NULL);
        if(!fail_case) { CHECK(result==0,"normal startup remains resident");_exit(0,NULL); }
        else CHECK(result==1,"failed startup refuses module residency");
        CHECK(!events && !mutexes && !threads && !running && !irq && !library && !rom_live && !hardware,
              "a refused module cannot leave its IRQ, thread, export or allocation alive");
    }
    return failures ? 1 : 0;
}
"""

def run(manager):
    intr=(manager/'iLink_intr.c').read_text(encoding='utf-8')
    crom=(manager/'iLink_crom.c').read_text(encoding='utf-8')
    client=(manager/'iLink.c').read_text(encoding='utf-8')
    packets='\n'.join(function(intr,s) for s in ('static void NoResponseHandler(','static void WriteRequestHandler(','static void ReadRequestHandler('))
    packets=packets.replace('data = *buffer;', 'data = read_fifo(buffer);').replace('= *buffer;','= read_fifo(buffer);')
    packets=packets.replace('((unsigned char *)req.offset_low)', '(&ram[req.offset_low])').replace('((unsigned int *)req.offset_low)', '((unsigned int *)&ram[req.offset_low])')
    packets=packets.replace('static void ReadRequestHandler(', intr[intr.index('struct ieee1394_TrCommonRdPktHdr'):intr.index('static void ReadRequestHandler(')]+'static void ReadRequestHandler(',1)
    crom_functions='\n'.join(function(crom,s) for s in ('static void ieee1394Swab32(', 'unsigned short int iLinkCalculateCRC16(',
        'int iLinkAddCROMUnit(', 'void iLinkDeleteCROMUnit(', 'static void BuildConfigurationROM('))
    client_functions='\n'.join(function(client,s) for s in ('int iLinkTrWrite(','int iLinkTrRead('))
    response_functions='\n'.join(function(intr,x) for x in ('void iLinkPrepareResponse(', 'void iLinkFinishRequest(',
        'static void NoResponseHandler(', 'static void ResponseHandler('))
    response_functions=response_functions.replace('data = *buffer;', 'data = read_fifo(buffer);').replace('= *buffer;', '= read_fifo(buffer);')
    response_state=intr[intr.index('static unsigned int ResponseLength;'):intr.index('\nvoid iLinkPrepareResponse(')]
    programs={'packet':PACKET.replace('@FUNCTIONS@',packets),'crom':CROM.replace('@FUNCTIONS@',crom_functions),
              'client':CLIENT.replace('@FUNCTIONS@',client_functions),
              'response':RESPONSE.replace('@FUNCTIONS@',response_functions).replace('@STATE@',response_state),
              'startup':STARTUP.replace('@FUNCTIONS@','\n'.join(function(client,x) for x in ('int _start(', 'int _exit(')))}
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory)
        for name,body in programs.items():
            if name=='startup':
                body=re.sub(r'\b_start\b','manager_start',body)
                body=re.sub(r'\b_exit\b','manager_exit',body)
            cfile=folder/(name+'.c');exe=folder/(name+('.exe' if sys.platform=='win32' else ''))
            cfile.write_text(('#define POPS_CROM\n#define POPS_STARTUP 1\n' if 'bdmassault' in str(manager) else '#define POPS_STARTUP 0\n')+PREAMBLE+body,encoding='utf-8')
            subprocess.run(['gcc','-std=gnu99','-O2','-Wall','-Wextra','-Werror','-Wno-pointer-to-int-cast','-Wno-int-to-pointer-cast',
                            '-Wno-builtin-declaration-mismatch','-Wno-overflow','-pthread','-I',str(manager/'include'),str(cfile),'-o',str(exe)],check=True,timeout=60)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            if result.returncode: print(result.stdout,result.stderr);return False
        public=(manager.parent/'include/iLinkman.h').read_text(encoding='utf-8')
        if not re.search(r'#define\s+I_iLinkGetLocalNodeEUI64\s+DECLARE_IMPORT\(25,\s*iLinkGetLocalNodeEUI64\)',public):
            print('FAIL: EUI64 import must use export 25');return False
    print(str(manager)+': PASS: packet/CROM bounds, response ownership, concurrent clients and startup rollback')
    return True

if __name__=='__main__':
    results=[run(p) for p in MANAGERS]
    sys.exit(0 if all(results) else 1)
