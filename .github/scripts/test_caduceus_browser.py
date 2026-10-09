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
