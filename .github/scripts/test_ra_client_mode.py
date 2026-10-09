"""Compile Caduceus reply parsing and the real IOP discovery state machine."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root/'modules/network/raudp/raudp.c').read_text()
start = source.index('static int ra_discover(void)\n{')
discover = source[start:source.index('\n}', start)+2]
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>
#include <string.h>
#include "modules/network/common/ra_client.h"
typedef uint32_t u32;
typedef unsigned char u8;
typedef unsigned int socklen_t;
struct sockaddr { int unused; };
struct sockaddr_in { int sin_family; unsigned short sin_port; struct { u32 s_addr; } sin_addr; };
#define AF_INET 2
#define SOCK_DGRAM 2
#define IPPROTO_UDP 17
#define SOL_SOCKET 1
#define SO_BROADCAST 1
#define INADDR_ANY 0
#define INADDR_BROADCAST 0xffffffffU
#define MSG_DONTWAIT 1
#define RA_SRC_PORT 18195
#define RA_DST_PORT 18194
#define RA_DISC_POLLS 2
#define RA_DISC_FAST 3
#define RA_DISC_POLL_US 1
#define RA_DISC_SLOW_US 1
#define htons(x) (x)
static int ra_caduceus, ra_rx_in_game = 1, ra_sock, scenario, sent_port, bridge_sends, engine_sends, closed;
static u32 ra_src_ip = 1, ra_dst_ip, ra_disc_us, ra_server_ip, ra_gateway_ip, ra_netmask_ip;
static int arp_only_gateway;
static u8 ra_dst_mac[6];
int lwip_socket(int a,int b,int c) { return 7; }
int lwip_setsockopt(int a,int b,int c,void*d,int e) { return 0; }
int lwip_bind(int a,struct sockaddr*b,int c) { return 0; }
void lwip_close(int s) { closed++; }
static jmp_buf deadline;
static int ticks;
void DelayThread(int t) { if(scenario && ++ticks > 30) longjmp(deadline,1); }
int ra_fmt_ip(char *out,u32 ip) { strcpy(out,"1.2.3.4"); return 7; }
void ra_fmt(u8*out,unsigned int n,int len) { memcpy(out,"18195",5); }
int etharp_lookup_mac(u32 ip,u8 *mac) { return !arp_only_gateway || ip==ra_gateway_ip; }
int lwip_sendto(int s,const char *body,int n,int flags,struct sockaddr *dest,int len) {
    struct sockaddr_in *to=(struct sockaddr_in*)dest;
    sent_port=to->sin_port;
    if(sent_port==18197) { assert(n==38 && !memcmp(body,RA_CADUCEUS_PROBE,38)); bridge_sends++; }
    else { assert(sent_port==18194 && !memcmp(body,"RAP1 ",5)); engine_sends++;
           if(ra_caduceus) assert(to->sin_addr.s_addr==42); }
    return n;
}
int lwip_recvfrom(int s,void*a,int b,char*out,int max,int flags,struct sockaddr *sender,socklen_t*len) {
    struct sockaddr_in *from=(struct sockaddr_in*)sender;
    from->sin_addr.s_addr=42;
    from->sin_port=sent_port;
    if(sent_port==18197) {
        const char *msg=scenario==1?"CADR2 " RA_PROBE_HASH " OFFLINE NO":
                        scenario==2?"CADR2 ffffffffffffffffffffffffffffffff READY NO":
                                    "CADR2 " RA_PROBE_HASH " READY UNKNOWN";
        strcpy(out,msg); return strlen(msg);
    }
    if(scenario==3) from->sin_addr.s_addr=99;
    if(scenario==4) { strcpy(out,"RAO1 NO"); return 7; }
    strcpy(out,"RAO1 OK test"); return 12;
}
'''
harness += discover + r'''
int main(void) {
    assert(raCaduceusSessionReply("CADR2 " RA_PROBE_HASH " READY OK 4 Title", RA_PROBE_HASH)==0);
    assert(raCaduceusSessionReply("CADR2 " RA_PROBE_HASH " OFFLINE NO", RA_PROBE_HASH)==-9);
    assert(raCaduceusSessionReply("CADR1 " RA_PROBE_HASH " READY NO", RA_PROBE_HASH)==-3);
    assert(raCaduceusSessionReply("CADR2 " RA_PROBE_HASH " READY NOPE", RA_PROBE_HASH)==-3);
    assert(raCaduceusSessionReply("CADR2 short", RA_PROBE_HASH)==-3);
    for(int i=0;i<39;i++) { char short_reply[80]="CADR2 " RA_PROBE_HASH " READY NO"; short_reply[i]=0;
        assert(raCaduceusSessionReply(short_reply,RA_PROBE_HASH)==-3); }
    assert(ra_discover()==1 && bridge_sends==0 && engine_sends==1);
    ra_caduceus=1; engine_sends=0;
    assert(ra_discover()==1 && bridge_sends==1 && engine_sends==1 && ra_dst_ip==42);
    for(scenario=1;scenario<=4;scenario++) {
        bridge_sends=engine_sends=closed=0;
        ticks=0;
        if(!setjmp(deadline)) { ra_discover(); assert(0); }
        if(scenario<3) assert(engine_sends==0);
        if(scenario==4) assert(engine_sends>0); /* RAO1 NO must never select a peer. */
    }
    scenario=0; ra_rx_in_game = 0; ra_server_ip = 123; bridge_sends = engine_sends = 0;
    assert(ra_discover() == 1 && ra_dst_ip == 123 && !bridge_sends && !engine_sends);
    ra_server_ip = 0; assert(ra_discover() == 0);
    /* Only an off-subnet RA peer can inherit the gateway's ARP address. */
    arp_only_gateway = 1; ra_gateway_ip = 88; ra_netmask_ip = 255;
    ra_server_ip = 123; assert(ra_discover() == 1);
    ra_server_ip = 1; assert(ra_discover() == 0);
    ra_server_ip = 123; ra_netmask_ip = 0; assert(ra_discover() == 0);
    puts("PASS: Xerabora/Caduceus discovery, offline, wrong peer, subnet-aware gateway and missing-mask guards");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)
    (path/'client.c').write_text(harness)
    subprocess.run(['cc','-std=c99','-I',str(root),str(path/'client.c'),'-o',str(path/'client.exe')],check=True)
    subprocess.run([str(path/'client.exe')],check=True)
