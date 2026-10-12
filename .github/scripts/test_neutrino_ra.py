"""Execute the production ORBIT handoff with deterministic filesystem/network failures."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/system.c").read_text()


def function(signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


functions = "\n".join(function(s) for s in (
    "static const char *sysLastPathSeparator(",
    "static int neutrinoArgActiveValue(",
    "static int sysNeutrinoCheatPath(",
    "static int sysNeutrinoCfgNameSafe(",
    "static int sysNeutrinoRAWrite(",
    "void sysNeutrinoPrepareRA(",
))

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include "modules/network/common/ra_watch.h"
#define NEUTRINO_CHEAT_CFG "riptopl-cheats"
#define RA_MODE_XERABORA 0
#define _STR_RA_NEUTRINO_UNTRACKED 1
#define LOG(...) ((void)0)
static char gNeutrinoArgs[256], sysNeutrinoCheatArg[24], sysNeutrinoCheatStartup[32];
static char sysNeutrinoRAArg[336], sysNeutrinoRAStartup[32];
static int gRATelemetry=1, gRAMode, gRAHostIp[4]={192,168,1,2}, ps2_ip[4]={192,168,1,10}, ps2_ip_use_dhcp;
static int count=2, bytes=5, nodes, warning, networkCalls, writes, missingMarker, badMarker, failWrite, failClose;
static unsigned int entries[2]={RA_WATCH_PACK(0x100000,4),RA_WATCH_PACK(0x100004,1)};
static char cfg[2048], watch[128], lastPath[512];
static int cfgLen, watchLen;
static int fake_open(const char *path,int flags,...) {
    snprintf(lastPath,sizeof(lastPath),"%s",path);
    if (flags & O_WRONLY) { writes++; return strstr(path,".wl") ? 3 : 4; }
    if (strstr(path,"ORBIT-RA.txt")) return missingMarker ? -1 : 1;
    return 2;
}
static int fake_read(int fd,void *out,int size) {
    (void)fd; const char *s=badMarker ? "not a supported runtime" : "RiptOPL ORBIT RA handoff v1\nORBIT credits\n";
    int n=strlen(s); if(n>size)n=size; memcpy(out,s,n);return n;
}
static int fake_write(int fd,const void *in,int size) {
    if(failWrite)return size-1;
    if(fd==3) { assert(size<128); memcpy(watch,in,size);watchLen=size; }
    else { assert(size<2048);memcpy(cfg,in,size);cfg[size]=0;cfgLen=size; }
    return size;
}
static int fake_close(int fd) { return failClose && fd>=3 ? -1 : 0; }
static int fake_unlink(const char *path) { (void)path;return 0; }
#define open fake_open
#define read fake_read
#define write fake_write
#define close fake_close
#define unlink fake_unlink
static int sbReadWatchList(const char *prefix,const char *startup) { assert(prefix); return strcmp(startup,"SLUS_123.45") ? 0 : count; }
static int GetWatchCount(void){return count;}
static int GetWatchBytes(void){return bytes;}
static int GetNodeCount(void){return nodes;}
static unsigned int *GetWatchList(void){return entries;}
static void raLaunchNetworkUp(void){networkCalls++;}
static int ethGetNetConfig(unsigned char *ip,unsigned char *mask,unsigned char *gateway) {
    (void)mask;(void)gateway;for(int i=0;i<4;i++)ip[i]=ps2_ip[i];return 0;
}
static unsigned int raNetPeerIP(void){return 0;}
static const char *_l(int x){(void)x;return "untracked";}
static void guiWarning(const char *s,int seconds){(void)s;(void)seconds;warning++;}
@FUNCTIONS@
static void prepare(const char *driver,const char *args) {
    writes=networkCalls=warning=0;cfgLen=watchLen=0;
    sysNeutrinoPrepareRA("mmce1:/Games/","SLUS_123.45",driver,"mmce1:/neutrino/neutrino.elf",args);
}
int main(void) {
    prepare("mmce", "-cfg=mine");
    assert(sysNeutrinoRAArg[0]);assert(networkCalls==1 && writes==2 && !warning);
    assert(strstr(sysNeutrinoRAArg,"mmce1:/neutrino/config/ript-ra.wl"));
    assert(strstr(cfg,"\"i_dev9_hidden\", \"mine\""));assert(strstr(cfg,"file = \"smap.irx\""));
    struct ra_watch_file h;memcpy(&h,watch,sizeof(h));
    assert(h.magic==RA_WATCH_MAGIC && h.version==RA_WATCH_VERSION && h.count==2 && h.bytes==5);
    assert(watchLen==(int)sizeof(h)+8 && !memcmp(watch+sizeof(h),entries,8));
    prepare("udpfs", "");
    assert(sysNeutrinoRAArg[0] && networkCalls==0);
    assert(!strstr(cfg,"smap.irx") && !strstr(cfg,"ministack.irx") && strstr(cfg,"load_order = 30"));
    assert(strstr(cfg,"srv=192.168.1.2") && strstr(cfg,"me=192.168.1.10"));
    prepare("usb", "-cwd=mass1:/custom");
    assert(strstr(sysNeutrinoRAArg,"mass1:/custom/config/ript-ra.wl"));
    strcpy(sysNeutrinoCheatArg,"-cfg=riptopl-cheats");strcpy(sysNeutrinoCheatStartup,"SLUS_123.45");
    prepare("usb", "-cfg=mine");assert(strstr(cfg,"riptopl-cheats"));
    sysNeutrinoCheatArg[0]=0;
    bytes=1217;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && warning);bytes=5;
    nodes=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && warning);nodes=0;
    missingMarker=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && warning);missingMarker=0;
    /* A game with no watch list launches quietly, even where the RA runtime is absent. */
    missingMarker=1;warning=0;sysNeutrinoPrepareRA("mmce1:/Games/","SLUS_999.99","usb","mmce1:/neutrino/neutrino.elf","");
    assert(!sysNeutrinoRAArg[0] && !warning);missingMarker=0;
    badMarker=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && warning);badMarker=0;
    ps2_ip_use_dhcp=1;prepare("udpfs", "");assert(!sysNeutrinoRAArg[0] && !writes && !networkCalls);ps2_ip_use_dhcp=0;
    failWrite=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && warning);failWrite=0;
    failClose=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && warning);failClose=0;
    prepare("usb", "-cwd=hdd0:");assert(!sysNeutrinoRAArg[0] && !writes);
    prepare("usb", "-cfg=bad\"name");assert(!sysNeutrinoRAArg[0]);
    gRAHostIp[0]=0;gRAHostIp[1]=0;gRAHostIp[2]=0;gRAHostIp[3]=0;
    prepare("udpfs", "");assert(!sysNeutrinoRAArg[0] && warning);gRAHostIp[0]=192;gRAHostIp[1]=168;gRAHostIp[2]=1;gRAHostIp[3]=2;
    gRATelemetry=0;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && !warning && !networkCalls);gRATelemetry=1;
    gRAMode=1;prepare("usb", "");assert(!sysNeutrinoRAArg[0] && !writes && !warning);
    puts("ORBIT handoff: device paths, network ownership, config/cheats, watch limits and failures passed");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "handoff.c"
    exe = Path(tmp) / "handoff.exe"
    c.write_text(harness.replace("@FUNCTIONS@", functions))
    result = subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Werror", "-I", str(root), str(c), "-o", str(exe)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    subprocess.run([str(exe)], check=True)

for name in ("bdmsupport.c", "mmcesupport.c", "hddsupport.c", "udpfssupport.c"):
    leg = (root / "src" / name).read_text()
    call = leg.index("sysNeutrinoPrepareRA(")
    assert leg.rfind("#ifdef RETROACHIEVEMENTS", 0, call) > leg.rfind("#endif", 0, call)
    assert call < leg.index("sysNeutrinoArgsPreflight(") < leg.index("sysLaunchNeutrino(")
print("PASS: all four launch legs prepare RA before argument-budget validation and teardown")
