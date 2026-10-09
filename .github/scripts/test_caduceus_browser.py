"""Run the production achievement parser/worker with a simulated paired share."""
from pathlib import Path
import re, subprocess, tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/achievements.c').read_text()
source = re.sub(r'^#include.*\n', '', source, flags=re.M)
prefix = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/achievements.h"
#define RETROACHIEVEMENTS 1
#define IO_OK 0
#define IO_CUSTOM_SIMPLEACTION 1
#define O_RDONLY 0
static void (*worker)(void);
static int queue_fail, nic_busy, file_length = 64, network_fail, hashed;
static char key_data[80], received[200];
static const char *reply = "OK\tG\t0\t1\t0\t0\t0\tUser\tLibrary\n42\t10\t2\t1\t20\t-\tGame\t\t";
static int sbHashGameBusy(void) { return 0; }
static int discCheckBusy(void) { return 0; }
static int raNetNicBusy(void) { return nic_busy; }
static int ethEnsureSMBShareConnected(void) { return 1; }
static const char *ethGetSMBPrefix(void) { return "smb0:Games/"; }
static int open(const char *path, int flags) { assert(!strcmp(path,"smb0:Games/ART/CADUCEUS.KEY")); return 1; }
static int read(int fd, void *out, int size) { int n=file_length<size?file_length:size; memcpy(out,key_data,n); return n; }
static int close(int fd) { return 0; }
static int ioPutRequest(int type, void (*fn)(void)) { worker=fn; return queue_fail?-1:0; }
static int raHashIsoDirect(const char *path, const char *startup, char *out) { hashed++; memset(out,'b',32);out[32]=0;return 0; }
static int raCaduceusPage(const char *request, unsigned serial, char *out, int size) {
    strcpy(received,request); snprintf(out,size,"%s",reply); return network_fail?-1:0;
}
"""
tests = r"""
static int parse(const char *s, achievement_page_t *p) { char b[1024];snprintf(b,sizeof(b),"%s",s); return achievementsParse(b,p); }
int main(void) {
 achievement_page_t page;
 memset(key_data,'a',64);
 assert(!achievementsParse(NULL,&page));
 assert(!parse("",&page));
 assert(parse(reply,&page) && page.state==ACH_READY && page.entries[0].id==42 && !page.entries[0].date[0]);
 assert(parse("OFFLINE",&page) && page.state==ACH_OFFLINE);
 assert(parse("UNSUPPORTED",&page) && page.state==ACH_UNSUPPORTED);
 assert(!parse("OK\tG\t-1\t0\t0\t0\t0\tu\tt",&page));
 assert(!parse("OK\tA\t0\t0\t1\t2\t1\tu\tt",&page));
 assert(!parse("OK\tG\t999999999999999999999\t0\t0\t0\t0\tu\tt",&page));
 assert(!parse("OK\tG\t0\t1\t0\t0\t0\tu\tt\n1\t0\t0\t0\t0\t../bad\tt\td\t",&page));
 queue_fail=1;assert(!achievementsRequest('G',0,0,"0") && !achievementsBusy());queue_fail=0;
 assert(achievementsRequest('G',0,0,"0"));
 assert(!achievementsRequest('G',1,0,"0"));
 achievementsSnapshot(&page);assert(page.state==ACH_LOADING);worker();
 achievementsSnapshot(&page);assert(page.state==ACH_READY && strstr(received,key_data));
 assert(!request[0] && !achievementsBusy());
 file_length=67;memset(key_data+64,' ',3);
 assert(achievementsRequest('G',0,0,"0"));worker();achievementsSnapshot(&page);assert(page.state==ACH_OFFLINE);
 file_length=66;key_data[64]='\r';key_data[65]='\n';
 assert(achievementsRequest('G',0,0,"0"));worker();achievementsSnapshot(&page);assert(page.state==ACH_READY);
 network_fail=1;assert(achievementsRequest('G',0,0,"0"));worker();achievementsSnapshot(&page);assert(page.state==ACH_ERROR);network_fail=0;
 assert(achievementsRequestImage("mass0:DVD/Game.iso","SLUS_123.45"));worker();
 assert(hashed==1 && strstr(received," A 0 0 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "));
 nic_busy=1;assert(achievementsRequest('G',0,0,"0"));worker();achievementsSnapshot(&page);assert(page.state==ACH_OFFLINE);
 puts("PASS: browser parser, empty fields, malformed data, pairing bounds, worker isolation, ISO target and network failure");
}
"""
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp);(path/'test.c').write_text(prefix+source+tests)
 subprocess.run(['cc','-std=gnu99','-I',str(root),str(path/'test.c'),'-o',str(path/'test.exe')],check=True)
 subprocess.run([str(path/'test.exe')],check=True)

# Production menu exchange: validate bridge before disclosing the capability,
# match page nonce and keep WAIT polling on the same host.
network=(root/'src/ranet.c').read_text()
a=network.index('int raCaduceusPage(');b=network.index('\n}',a)+2
network=network[a:b]
harness=r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "modules/network/common/ra_client.h"
typedef unsigned char u8;
struct sockaddr_in {int sin_family, sin_port;struct {unsigned s_addr;} sin_addr;};
#define AF_INET 2
#define INADDR_BROADCAST 0xffffffffu
#define htonl(x) (x)
#define htons(x) (x)
#define RA_MODE_CADUCEUS 1
static int gRAMode=1, scenario, calls, queries, closed;
static unsigned g_raReplyIP;
static char g_rx[2048];
static int raNetNicBusy(void) {return 0;}
static int open_pc_socket(char *a,int size,u8 *ip) {return 7;}
static void disconnect(int s) {closed++;}
static void DelayThread(int us) {}
static int ask(int s,struct sockaddr_in *to,const char *req,char *out,int max) {
 calls++;
 if(to->sin_port==18197) {
  assert(!strcmp(req,RA_CADUCEUS_PROBE));
  assert(to->sin_addr.s_addr==INADDR_BROADCAST);
  g_raReplyIP=42;
  strcpy(out,scenario==1?"garbage":scenario==2?"CADR2 " RA_PROBE_HASH " OFFLINE UNKNOWN":"CADR2 " RA_PROBE_HASH " READY UNKNOWN");
 } else {
  queries++;assert(to->sin_port==18198 && to->sin_addr.s_addr==42 && strstr(req,"secret"));
  strcpy(out,scenario==3 && queries==1?"CADB1 99 OK":queries<3?"CADB1 7 WAIT":"CADB1 7 OK\tG\t0\t0\t0\t0\t0\tu\tt");
 }
 return strlen(out);
}
"""
checks=r"""
int main(void) {
 char out[1024];
 for(scenario=0;scenario<4;scenario++) {
  queries=closed=calls=0;
  int result=raCaduceusPage("CADA1 7 G 0 0 0 secret",7,out,sizeof(out));
  assert(closed==1);
  if(scenario==1) assert(result<0 && !queries);
  else if(scenario==2) assert(!result && !queries && !strcmp(out,"OFFLINE"));
  else assert(!result && queries==3 && !strncmp(out,"OK\tG",4));
 }
 puts("PASS: bridge validation before capability, offline, nonce matching and pinned WAIT retries");
}
"""
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp);(path/'network.c').write_text(harness+network+checks)
 subprocess.run(['cc','-std=gnu99','-I',str(root),str(path/'network.c'),'-o',str(path/'network.exe')],check=True)
 subprocess.run([str(path/'network.exe')],check=True)
