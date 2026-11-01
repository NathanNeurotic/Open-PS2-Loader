"""Compile production scan, preflight, POPS startup and raw ARP counterexamples."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]


def read(path):
    return (root / path).read_text(encoding="utf-8")


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(signature)


def run(name, program):
    with tempfile.TemporaryDirectory(prefix="pr894-") as tmp:
        src = Path(tmp) / (name + ".c")
        exe = Path(tmp) / (name + ".exe")
        src.write_text(program, encoding="utf-8")
        subprocess.run(["cc", "-std=gnu99", "-Wall", "-Werror",
                        "-Wno-pointer-to-int-cast", "-Wno-int-to-pointer-cast",
                        "-I", str(root), str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


cue = read("src/cuesupport.c")
run("merge", r'''
#include <assert.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
typedef struct { int tag; char name[64]; } base_game_info_t; /* name: the PS1 Duplicates twin check reads it */
enum { PS1_DUP_BOTH = 0, PS1_DUP_EMBER, PS1_DUP_POPSTARTER };
static int gPs1Duplicates;
static int gAutosort, vc, cc, oom;
#define LOG(...) ((void)0)
static int ps1RowCmp(const void *a,const void *b) { (void)a;(void)b;return 0; }
static void *memalign(int a,size_t n) { (void)a;return oom ? NULL : malloc(n); }
static int half(int count,base_game_info_t **out) {
    *out=count>0 ? calloc(count,sizeof(**out)) : NULL; return count;
}
static int vcdFillGameList(const char *p,base_game_info_t **out) { (void)p;return half(vc,out); }
static int cueFillGameListUnsorted(const char *p,base_game_info_t **out) { (void)p;return half(cc,out); }
''' + cue[cue.index("static int ps1ScanIncomplete;"):] + r'''
int main(void) {
    for(vc=-1;vc<=1;vc++) for(cc=-1;cc<=1;cc++) {
        base_game_info_t *rows=malloc(sizeof(*rows)), *old=rows; rows->tag=123;
        int got=ps1FillGameList("mass0:/",&rows);
        assert(ps1GameListNeedsRetry()==(vc<0 || cc<0));
        if((vc<0 && cc<=0)||(cc<0 && vc<=0)) assert(got==-1 && rows==old && rows->tag==123);
        else if(vc==0 && cc==0) assert(got==0 && rows==NULL);
        else assert(got==(vc>0?vc:0)+(cc>0?cc:0) && rows!=NULL);
        free(rows);
    }
    base_game_info_t *rows=malloc(sizeof(*rows)), *old=rows;
    vc=cc=1;oom=1;
    assert(ps1FillGameList("mass0:/",&rows)==-1 && rows==old);free(rows);
    puts("PASS: failed/empty merge retains old rows; nonempty half publishes; OOM preserves ownership");
}
''')

fav = read("src/favsupport.c")
run("favorites", r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct item_list item_list_t;
struct item_list { int mode,viewOverride; int (*itemGetCount)(item_list_t*); char *(*itemGetName)(item_list_t*,int); };
#define ITEM_VIEW_FORCE_PS1 1
#define ITEM_VIEW_FORCE_ISO 2
#define ETH_MODE 1
#define APP_MODE 2
#define FAV_KIND_ISO 0
static int count=2;
static char *names[]={"Alpha","Beta"};
static int getCount(item_list_t *o) { assert(o->viewOverride==2);return count; }
static char *getName(item_list_t *o,int id) { (void)o;return names[id]; }
static item_list_t source={3,1,getCount,getName};
static struct { item_list_t *owner; int id,kind; const char *text; } storage[]={{&source,1,0,"Beta"}};
static typeof(storage[0]) *favArray=storage;
static int favCount=1;
static int favKindIsNameAddressed(int kind) { return kind!=0; }
static int ethResolveIsoFavourite(int id,const char *s,int *out) { (void)s;*out=id;return 1; }
''' + function(fav, "static int favValidIndex(") + "\n" +
    function(fav, "static item_list_t *favOwnerView(") + "\n" +
    function(fav, "static int favResolveStoredId(") + "\n" +
    function(fav, "item_list_t *favGetSourceItem(") + r'''
int main(void) {
    item_list_t view;int id=-1;
    assert(favGetSourceItem(0,&view,&id)==&view && id==1 && view.mode==3);
    assert(source.viewOverride==1 && view.viewOverride==2);
    names[1]="Replacement";assert(!favGetSourceItem(0,&view,&id));
    names[1]="Beta";count=1;assert(!favGetSourceItem(0,&view,&id));
    assert(!favGetSourceItem(-1,&view,&id) && !favGetSourceItem(1,&view,&id));
    puts("PASS: Favorites checks resolve the real source view and reject stale row identity");
}
''')

for module, worker, registered in (("raudp", "ra_thread", True), ("rapull", "rp_thread", False)):
    source = read(f"modules/network/{module}/{module}.c")
    start = function(source, "int _start(")
    tail = start[start.index("    thread.attr = TH_C;"):]
    run(module + "_thread", r'''
#include <assert.h>
#include <stdio.h>
#define TH_C 1
#define MODULE_NO_RESIDENT_END 1
#define MODULE_RESIDENT_END 0
typedef struct { int attr,option,stacksize,priority; void (*thread)(void*); } iop_thread_t;
static int create_fail,start_fail,deleted,started;
static void WORKER(void *p) { (void)p; }
static int CreateThread(iop_thread_t *t) { (void)t;return create_fail?-1:7; }
static int StartThread(int id,void *p) { (void)p;assert(id==7);started++;return start_fail?-1:0; }
static void DeleteThread(int id) { assert(id==7);deleted++; }
'''.replace("WORKER", worker) + (r'''
static int _exp_raudp,register_fail,released;
static int RegisterLibraryEntries(int *p) { (void)p;return register_fail?-1:0; }
static void ReleaseLibraryEntries(int *p) { (void)p;released++; }
''' if registered else "") + "static int launch(void) { iop_thread_t thread;int tid;\n" + tail + r'''
int main(void) {
    create_fail=1;assert(launch()==1 && !deleted && !started);
    create_fail=0;start_fail=1;assert(launch()==1 && deleted==1 && started==1);
    start_fail=0;assert(launch()==0 && deleted==1 && started==2);
''' + (r'''
    assert(released==1);register_fail=1;
    assert(launch()==1 && deleted==2 && started==2 && released==1);
''' if registered else "") + f'    puts("PASS: {module} thread startup failure releases dormant thread and exports");\n}}\n')

net = read("src/ranet.c")
assert "extern int pc_ip[4]" in read("include/opl.h")
run("preflight", r'''
#include <assert.h>
#include <stdio.h>
typedef unsigned char u8;
#define AF_INET 2
#define SOCK_DGRAM 2
#define NETMAN_NETIF_IOCTL_GET_LINK_STATUS 1
#define NETMAN_NETIF_ETH_LINK_STATE_UP 1
#define RA_MODE_CADUCEUS 1
#define RA_CADUCEUS_PROBE "probe"
#define RA_PROBE_HASH "hash"
#define _STR_CAD_UNTRACKED 1
#define _STR_RA_NO_LINK_UNTRACKED 2
#define _l(x) "warning"
#define LOG(...) ((void)0)
struct sockaddr_in { int unused; };
static int gRATelemetry=1,gRAMode,count=1,busy,link=1,dhcp=1,ps2_ip_use_dhcp=1;
static int session,probes,forgot,remembered;
static unsigned int g_raReplyIP=42;
static char g_rx[128];
static int GetWatchCount(void) { return count; }
static int raNetNicBusy(void) { return busy; }
static void raNetForgetPeer(void) { forgot++; }
static void ClearWatchList(void) { count=0; }
static int socket(int a,int b,int c) { (void)a;(void)b;(void)c;return 7; }
static void disconnect(int s) { (void)s; }
static int NetManIoctl(int a,void*b,int c,void*d,int e) { (void)a;(void)b;(void)c;(void)d;(void)e;return link; }
static int ethLoadInitModules(void) { return link?0:-1; }
static int ethGetNetConfig(u8 *ip,u8 *mask,u8 *gw) { (void)mask;(void)gw;ip[0]=192;ip[1]=168;ip[2]=1;ip[3]=2;return 0; }
static int ethGetDHCPStatus(void) { return dhcp; }
static int open_pc_socket(char*a,int n,u8*ip) { (void)a;(void)n;(void)ip;return 7; }
static int caduceus_target(struct sockaddr_in *to) { (void)to;return 1; }
static int ask(int s,struct sockaddr_in *to,const char*p,char*rx,int n) { (void)s;(void)to;(void)p;(void)rx;(void)n;probes++;return 1; }
static int raCaduceusSessionReply(const char *rx,const char *hash) { (void)rx;(void)hash;return session; }
static void guiWarning(const char *s,int n) { (void)s;(void)n; }
static void raNetRememberPeer(unsigned int ip) { assert(ip==42);remembered++; }
''' + function(net, "void raLaunchNetworkUp(") + r'''
int main(void) {
    link=0;raLaunchNetworkUp();assert(!count && forgot==1 && !probes);
    count=1;link=1;dhcp=0;raLaunchNetworkUp();assert(!count && !probes);
    count=1;dhcp=1;gRAMode=1;session=-9;raLaunchNetworkUp();assert(!count && probes==1);
    count=1;session=0;raLaunchNetworkUp();assert(count==1 && remembered==1);
    busy=1;raLaunchNetworkUp();assert(!count && probes==2);
    puts("PASS: retained address with disconnected link, pending DHCP, offline session and NIC ownership fail open");
}
''')

rapops = re.sub(r"^#include.*$", "", read("modules/network/rapops/rapops.c"), flags=re.M)
run("startup", r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "modules/network/common/ra_snap.h"
#include "modules/network/common/rapops_cfg.h"
typedef uint32_t u32;
typedef unsigned char u8;
#define IRX_ID(a,b,c)
#define MODULE_RESIDENT_END 0
#define MODULE_NO_RESIDENT_END 1
#define ALLOC_FIRST 0
#define _start rapops_start
u8 rp_dev9[4],rp_smsutils[4],rp_smstcpip[4],rp_smap[4],rp_raudp[4],rp_rapull[4];
static void *buffers[]={rp_dev9,rp_smsutils,rp_smstcpip,rp_smap,rp_raudp,rp_rapull};
static void *owned[4];
static int allocated,freed,fail_module=-1,fail_alloc=-1,sender_flags,started[6],start_error;
static size_t snap_size;
static void *AllocSysMemory(int a,size_t n,void *p) {
    (void)a;(void)p;if(allocated==fail_alloc)return NULL;
    if(!allocated)snap_size=n;
    return owned[allocated++]=malloc(n);
}
static void FreeSysMemory(void *p) {
    for(int i=0;i<allocated;i++)if(owned[i]==p){free(p);owned[i]=NULL;freed++;return;}
    assert(0);
}
static int LoadModuleBuffer(void *p) { for(int i=0;i<6;i++)if(buffers[i]==p)return i;assert(0);return -1; }
static int StartModule(int id,const char *name,int n,const char *args,int *result) {
    (void)name;(void)n;started[id]++;
    if(id==4)sender_flags=args[RA_ARG_RX]-'0';
    if(start_error && id==fail_module)return -1;
    *result=id==fail_module ? MODULE_NO_RESIDENT_END : MODULE_RESIDENT_END;
    return 0;
}
''' + rapops + r'''
static void reset(void) {
    for(int i=0;i<allocated;i++)free(owned[i]);
    memset(owned,0,sizeof(owned));memset(started,0,sizeof(started));
    allocated=freed=start_error=0;fail_module=fail_alloc=-1;
    g_cfg.ipcfg_len=3;g_cfg.count=1;g_cfg.bytes=4;g_cfg.node_count=0;
}
int main(void) {
    for(int mode=0;mode<2;mode++)for(int pin=0;pin<2;pin++) {
        reset();g_cfg.client_mode=mode;g_cfg.host_pinned=pin;
        assert(rapops_start(0,NULL)==MODULE_NO_RESIDENT_END);
        assert(sender_flags==1+mode*2+pin*4 && started[5]==1);
        assert(snap_size==RA_SNAP_TOTAL_FOR(4) && snap_size<RA_SNAP_TOTAL);
    }
    for(int id=1;id<=3;id++) { reset();fail_module=id;rapops_start(0,NULL);assert(!allocated && !started[4]); }
    reset();fail_module=4;rapops_start(0,NULL);assert(allocated==1 && freed==1 && !started[5]);
    reset();fail_module=5;rapops_start(0,NULL);assert(allocated==2 && freed==1 && owned[0]!=NULL);
    reset();fail_alloc=0;rapops_start(0,NULL);assert(!started[4]);
    reset();fail_alloc=1;rapops_start(0,NULL);assert(started[4] && !started[5]);
    reset();fail_module=4;start_error=1;rapops_start(0,NULL);assert(freed==1 && !started[5]);
    reset();puts("PASS: POPS pinned ABI, proportional allocation, dependency/sender/reader failure ownership");
}
''')

udp = read("modules/network/raudp/raudp.c")
run("arp", r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned int u32;
typedef unsigned char u8;
#define USE_SMAP_EMAC3_REGS
#define SMAP_R_EMAC3_ADDR_HI 0
#define SMAP_R_EMAC3_ADDR_LO 1
#define SMAP_EMAC3_GET32(x) ((x)==0 ? 0x0011U : 0x22334455U)
static u32 ra_src_ip=0x0200000a;
static int busy,sent;
static u8 packet[60];
static int ra_tx_busy(void) { return busy; }
static int SMAPSendPacket(void *p,int n) { assert(n==60);memcpy(packet,p,n);sent++;return 0; }
''' + function(udp, "static int ra_request_mac(") + r'''
int main(void) {
    busy=1;assert(!ra_request_mac(0x0700000a) && !sent);
    busy=0;assert(ra_request_mac(0x0700000a) && sent==1);
    for(int i=0;i<6;i++)assert(packet[i]==255 && packet[32+i]==0);
    const u8 mac[]={0,0x11,0x22,0x33,0x44,0x55};
    assert(!memcmp(packet+6,mac,6) && !memcmp(packet+22,mac,6));
    assert(packet[12]==8 && packet[13]==6 && packet[15]==1 && packet[16]==8);
    assert(packet[18]==6 && packet[19]==4 && packet[21]==1);
    const u8 src[]={10,0,0,2},dst[]={10,0,0,7};
    assert(!memcmp(packet+28,src,4) && !memcmp(packet+38,dst,4));
    puts("PASS: raw ARP requests use correct addresses and yield to busy game TX");
}
''')
