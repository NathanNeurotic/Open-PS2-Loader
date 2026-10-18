#!/usr/bin/env python3
"""Source integration and actual preflight execution for the DESR DVR Neutrino branch."""
from pathlib import Path
import os
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
system = (root / "src/system.c").read_text(encoding="utf-8")
hdd = (root / "src/hddsupport.c").read_text(encoding="utf-8")
assert 'if (!strcmp(driver, "dvr"))' in system
assert 'return "dvr";' in system
assert '|| !strcmp(deviceName, "dvr")' in system
assert 'neutrinoArgHasActiveFlag(gNeutrinoArgs, "-qb")' in system
assert 'sysNeutrinoPreflight("dvr"' in hdd
assert 'sysLaunchNeutrino("dvr"' in hdd
assert 'hddDvrScan();' in hdd
assert 'dvrfile_fhi.irx' in system
assert 'SPD_CAPS_DVR' in hdd
assert 'sysLoadModuleBuffer(&dvrdrv_irx' in hdd
assert 'sysLoadModuleBuffer(&dvrfile_irx' in hdd
assert 'result == -2 || result == -3' in hdd
assert 'dir[strlen(dir) - 1]' in hdd
assert 'fileXioMount(roots[part], src, FIO_MT_RDONLY)' in hdd
assert 'hddPs2GameCount()' in hdd
assert 'hddDvrCleanUp(0);' in hdd
assert 'KEEP_DVR_MOUNTS_EXCEPTION' in hdd
assert 'guiLock();' in hdd and 'hddDvrPublish(candidate, count);' in hdd
assert 'if (game->partition_name[0]' in hdd
assert 'copy = *entry;' in hdd
print("DESR DVR source integration checks passed (not a hardware/build test)")


def function(signature):
    start = system.index(signature)
    return system[start:system.index('\n}', start) + 2]


functions = '\n'.join(function(signature) for signature in (
    'static const char *getDeviceName(', 'static int neutrinoArgHasActiveFlag(',
    'static int neutrinoEffectiveBsdfs(', 'static const char *sysLastPathSeparator(',
    'int sysNeutrinoPreflight(',
))
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#define LOG(...) ((void)0)
#define NET_BOOT_UDPFS 2
#define _STR_NEUTRINO_DEV_UNSUPPORTED 1
#define _STR_NEUTRINO_TOML_SYNC_FAILED 2
#define _STR_NEUTRINO_BD_NO_DEVICE_NUMBER 3
#define _STR_NEUTRINO_DVR_QUICKBOOT 4
#define _STR_NEUTRINO_DVR_FILE_MISSING 5
#define _STR_NEUTRINO_DVR_BACKEND_OVERRIDE 6
static char gNeutrinoArgs[256];
static int warning, warnings, opens, closes, missingInstall;
static int bdmGetLoadedNetProtocol(void) {return 0;}
static const char *_l(int id) {warning=id;return "message";}
static void guiWarning(const char *msg,int seconds) {(void)msg;assert(seconds==6);warnings++;}
static void guiMsgBoxMissing(const char *msg,const char *path) {(void)msg;assert(path);warnings++;}
static int sysSyncNeutrinoUdpfsToml(const char *path,const char *device) {(void)path;(void)device;return 0;}
static int mockOpen(const char *path,int flags) {
 assert(flags==O_RDONLY);opens++;
 assert(strstr(path,"bsd-dvr.toml") || strstr(path,"modules/dvrdrv.irx") ||
        strstr(path,"modules/dvrfile.irx") || strstr(path,"modules/dvrfile_fhi.irx"));
 return missingInstall?-1:10;
}
static int mockClose(int fd) {assert(fd==10);closes++;return 0;}
#define open mockOpen
#define close mockClose
@FUNCTIONS@
static void scenario(const char *global,const char *game,int picker,int wantWarning,int wantOpens) {
 snprintf(gNeutrinoArgs,sizeof(gNeutrinoArgs),"%s",global?global:"");
 warning=warnings=opens=closes=0;
 int result=sysNeutrinoPreflight("dvr","mass0:/NEUTRINO/neutrino.elf",picker,game,-1);
 if ((result<0)!=(wantWarning!=0) || warning!=wantWarning || opens!=wantOpens ||
     warnings!=(wantWarning!=0) || closes!=(missingInstall?0:opens)) {
  fprintf(stderr,"DVR global='%s' game='%s' picker=%d: result=%d warning=%d opens=%d closes=%d\n",
          global?global:"",game?game:"",picker,result,warning,opens,closes);
  assert(0);
 }
}
int main(void) {
 const char *overrides[]={"-bsd=usb","-bsd=dvr","-bsd=","-bsdfs=bd","-bsdfs=exfat","-bsdfs=hdl","-bsdfs="};
 for(int picker=0;picker<=3;picker++) {
  scenario("",NULL,picker,0,4);
  for(unsigned int i=0;i<sizeof(overrides)/sizeof(*overrides);i++) {
   scenario(overrides[i],NULL,picker,6,0);
   scenario("",overrides[i],picker,6,0);
  }
 }
 scenario(" -bsd=usb\t-dbc",NULL,0,6,0);
 scenario("-bsd=usb","-bsd=dvr",0,6,0);
 scenario("$-bsd=usb $-bsdfs=bd","$-bsd=dvr",3,0,4);
 scenario("--b -bsd=usb -bsdfs=bd",NULL,3,0,4);
 scenario("","--b -bsd=usb -bsdfs=bd",3,0,4);
 scenario("--b -bsd=usb","-bsdfs=bd",0,6,0);
 scenario("-bsdfs=bd","--b -bsd=usb",0,6,0);
 scenario("--b -bsd=usb","--b -bsdfs=bd",0,0,4);
 scenario("name-bsd=usb --bsdfs=bd -bsdfss=bd",NULL,0,0,4);
 scenario("--break -bsd=usb",NULL,0,6,0);
 scenario("-qb",NULL,0,4,0);
 scenario("","-qb",0,4,0);
 scenario("$-qb","--b -qb",0,0,4);
 scenario("-qboot",NULL,0,0,4);
 // Other backends retain their supported user overrides.
 strcpy(gNeutrinoArgs,"-bsd=usb -bsdfs=bd");warning=warnings=opens=closes=0;
 assert(sysNeutrinoPreflight("usb","mass0:/NEUTRINO/neutrino.elf",0,NULL,1)==0);
 assert(!warning && !warnings && !opens);
 missingInstall=1;scenario("",NULL,0,5,2);
 puts("DVR preflight: backend overrides rejected before file IO; disabled/game-tail flags and valid companion checks preserved");
}
'''.replace('@FUNCTIONS@', functions)
with tempfile.TemporaryDirectory() as directory:
    src = Path(directory) / 'dvr_preflight.c'
    exe = Path(directory) / ('dvr_preflight.exe' if os.name == 'nt' else 'dvr_preflight')
    src.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
