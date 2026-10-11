"""Compile the production POPS UDPFS config reader/writer with real host file IO.

Check subnet validation, driver config syntax, USB identity/ambiguity, missing-file
launch refusal, edit persistence, and rollback at each rename failure point.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/vcdsupport.c').read_text(encoding='utf-8')
header = (ROOT / 'include/vcdsupport.h').read_text(encoding='utf-8')


def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


typedef = re.search(r'typedef struct\s*\{[^}]*\}\s*vcd_pops_udpfs_t;', header).group(0)
pieces = '\n'.join(function(s) for s in (
    'static int vcdReadNetFile(', 'static int vcdQuadOk(',
    'static unsigned int vcdUdpfsAddress(', 'static int vcdUdpfsHost(',
    'int vcdPopsUdpfsNetValid(', 'static int vcdPopsUdpfsUsbHomes(',
    'static const char *vcdUdpfsConfigLine(', 'static int vcdUdpfsParseQuad(',
    'static int vcdReadPopsUdpfsNetAt(',
    'static int vcdPopsUdpfsSame(', 'int vcdReadPopsUdpfsNet(',
    'int vcdWritePopsUdpfsNet(', 'int vcdPreparePopsUdpfsLaunch(',
    'int vcdBdmaLaunchReady(',
))
HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#ifndef O_BINARY
#define O_BINARY 0
#endif
#define MAX_BDM_DEVICES 10
#define BDM_TYPE_USB 7
static int volumes=1, renameCall, failRename, failWrite, failRestoreRename;
static int failPark, failReturn;
static int markedReady, manualReady;
#define LOG(...) ((void)0)
#define VCD_BDMA_UDPFS 6
static int vcdBdmaEnvironmentValid(int mode) {return mode==VCD_BDMA_UDPFS && markedReady;}
static int vcdBdmaManualPairMatches(int mode) {return mode==VCD_BDMA_UDPFS && manualReady;}
static const char *mapped(const char *p) {
 static char buffers[4][512];static int next;
 if(!strncmp(p,"mass3:/",7))return p+7;
 if(!strncmp(p,"mass4:/",7)) {char*b=buffers[(next++)%4];snprintf(b,512,"USB4/%s",p+7);return b;}
 return p;
}
static int hostOpen(const char *p,int f) { return open(mapped(p),f|O_BINARY,0644); }
static int hostMkdir(const char *p,int mode) {
#ifdef _WIN32
 (void)mode; return mkdir(mapped(p));
#else
 return mkdir(mapped(p),mode);
#endif
}
static int hostUnlink(const char *p) { return unlink(mapped(p)); }
static int hostRename(const char *a,const char *b) {
 if ((failPark && strstr(b,"IPCONFIG.DAT.tmp")) ||
     (failReturn && renameCall>=4 && strstr(a,"IPCONFIG.DAT.tmp"))) {errno=EIO;return -1;}
 // Model USB filesystems that refuse replacement, even on POSIX hosts.
 struct stat destination;
 if (stat(mapped(b),&destination)==0) {errno=EEXIST;return -1;}
 if (failRestoreRename && strstr(a,"IPCONFIG.DAT.bak")) {
  failRestoreRename=0;errno=EIO;return -1;
 }
 if (++renameCall==failRename) {errno=EIO;return -1;}
 return rename(mapped(a),mapped(b));
}
static void bdmEnsureSourceModules(int type,int timeout) { if(type!=BDM_TYPE_USB||timeout!=2000) abort(); }
static int bdmGetDeviceSlotsByType(int type,int *slots,int max) { if(type!=BDM_TYPE_USB||max<volumes)abort();for(int i=0;i<volumes;i++)slots[i]=3+i;return volumes; }
static int vcdGetFileSize(const char *p) { struct stat s;return stat(mapped(p),&s)==0?(int)s.st_size:-1; }
static int vcdSafeWriteFile(const char *p,const void *buf,int len) {
 if(failWrite) return -3;
 FILE *f=fopen(mapped(p),"wb");if(!f)return -3;
 int ok=fwrite(buf,1,len,f)==(size_t)len;fclose(f);return ok?0:-3;
}
#define open hostOpen
#define mkdir hostMkdir
#define unlink hostUnlink
#define rename hostRename
@TYPE@
@CODE@
static int checks;
#define CHECK(x) do { ++checks; if(!(x)) {fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;} } while(0)
static void put(const char *name,const char *text) {FILE*f=fopen(name,"wb");if(!f)abort();fputs(text,f);fclose(f);}
static int equals(const char *name,const char *text) {char b[512]={0};FILE*f=fopen(name,"rb");if(!f)return 0;fread(b,1,sizeof(b)-1,f);fclose(f);return !strcmp(b,text);}
int main(void) {
 vcd_pops_udpfs_t c, changed; char root[64];
 mkdir("POPS",0777);
 CHECK(!vcdBdmaLaunchReady(VCD_BDMA_UDPFS));
 markedReady=1;CHECK(vcdBdmaLaunchReady(VCD_BDMA_UDPFS));markedReady=0;
 manualReady=1;CHECK(vcdBdmaLaunchReady(VCD_BDMA_UDPFS));manualReady=0;
 CHECK(!vcdBdmaLaunchReady(VCD_BDMA_UDPFS));
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.ipExists && !c.serverExists);
 CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 put("POPS/IPCONFIG.DAT","\xef\xbb\xbf# comment\r\n; ignored\r\n192.168.1.10 255.255.255.0\r\n");
 put("POPS/UDPFSCONFIG.DAT","192.168.1.11\r\n");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.invalid && c.ipExists && c.serverExists);
 CHECK(vcdPreparePopsUdpfsLaunch(root,sizeof(root)) && !strcmp(root,"mass3:/"));
 CHECK(!vcdPreparePopsUdpfsLaunch(root,3));
 changed=c;changed.server[2]=2;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.server[3]=10;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.server[3]=255;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.ps2Ip[0]=127;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.ps2Ip[0]=224;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.ps2Ip[3]=0;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.mask[2]=127;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.mask[3]=255;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.server[3]=256;CHECK(!vcdPopsUdpfsNetValid(&changed));
 volumes=0;CHECK(vcdReadPopsUdpfsNet(&c)!=0);volumes=1;
 CHECK(vcdReadPopsUdpfsNet(&c)==0);
 changed=c;changed.ps2Ip[3]=20;changed.server[3]=21;
 const char *oldIp="192.168.1.10 255.255.255.0 0.0.0.0\n", *oldServer="192.168.1.11\n";
 for(int failure=1;failure<=4;failure++) {
  put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT",oldServer);
  renameCall=0;failRename=failure;
  CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
  CHECK(equals("POPS/IPCONFIG.DAT",oldIp));CHECK(equals("POPS/UDPFSCONFIG.DAT",oldServer));
 }
 failRename=0;failWrite=1;CHECK(vcdWritePopsUdpfsNet(&changed)!=0);failWrite=0;
 CHECK(equals("POPS/IPCONFIG.DAT",oldIp));CHECK(equals("POPS/UDPFSCONFIG.DAT",oldServer));
 CHECK(vcdWritePopsUdpfsNet(&changed)==0);
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.invalid && c.ps2Ip[3]==20 && c.server[3]==21);
 memset(changed.server,0,sizeof(changed.server));CHECK(vcdWritePopsUdpfsNet(&changed)==0);
 CHECK(equals("POPS/UDPFSCONFIG.DAT",""));CHECK(vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 put("POPS/IPCONFIG.DAT","\n");CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT","garbage");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 unlink("POPS/UDPFSCONFIG.DAT");CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 put("POPS/UDPFSCONFIG.DAT",oldServer);put("POPS/IPCONFIG.DAT.bak","recover me");
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);CHECK(equals("POPS/IPCONFIG.DAT.bak","recover me"));
 unlink("POPS/IPCONFIG.DAT.bak");
 put("POPS/IPCONFIG.DAT","999999999999999999999.1.1.1 255.255.255.0");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);
 put("POPS/IPCONFIG.DAT","-1.168.1.10 255.255.255.0");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);
 put("POPS/IPCONFIG.DAT",oldIp);
 volumes=2;mkdir("USB4",0777);mkdir("USB4/POPS",0777);
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);
 CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 CHECK(vcdWritePopsUdpfsNet(&changed)==0);
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.invalid);
 CHECK(equals("POPS/IPCONFIG.DAT","192.168.1.20 255.255.255.0 0.0.0.0\n"));
 CHECK(equals("USB4/POPS/IPCONFIG.DAT","192.168.1.20 255.255.255.0 0.0.0.0\n"));
 CHECK(equals("USB4/POPS/UDPFSCONFIG.DAT",""));
 CHECK(vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 put("USB4/POPS/UDPFSCONFIG.DAT",oldServer);
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);
 CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 unlink("POPS/IPCONFIG.DAT");unlink("POPS/UDPFSCONFIG.DAT");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid && c.ipExists && c.serverExists);
 CHECK(!vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 CHECK(vcdWritePopsUdpfsNet(&changed)==0);
 CHECK(vcdPreparePopsUdpfsLaunch(root,sizeof(root)));
 for(int failure=1;failure<=8;failure++) {
  put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT",oldServer);
  put("USB4/POPS/IPCONFIG.DAT",oldIp);put("USB4/POPS/UDPFSCONFIG.DAT",oldServer);
  renameCall=0;failRename=failure;
  CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
  CHECK(equals("POPS/IPCONFIG.DAT",oldIp));CHECK(equals("POPS/UDPFSCONFIG.DAT",oldServer));
  CHECK(equals("USB4/POPS/IPCONFIG.DAT",oldIp));CHECK(equals("USB4/POPS/UDPFSCONFIG.DAT",oldServer));
 }
 // Simulate one forward commit failing, then the first rollback restore failing.
 // The live replacement AND original backup must survive together.
 put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT",oldServer);
 put("USB4/POPS/IPCONFIG.DAT",oldIp);put("USB4/POPS/UDPFSCONFIG.DAT",oldServer);
 renameCall=0;failRename=4;failRestoreRename=1;
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
 failRename=0;failRestoreRename=0;
 CHECK(equals("POPS/IPCONFIG.DAT.bak",oldIp));
 CHECK(equals("POPS/IPCONFIG.DAT","192.168.1.20 255.255.255.0 0.0.0.0\n"));
 CHECK(equals("POPS/UDPFSCONFIG.DAT",oldServer));
 CHECK(equals("USB4/POPS/IPCONFIG.DAT",oldIp));
 CHECK(equals("USB4/POPS/UDPFSCONFIG.DAT",oldServer));
 unlink("POPS/IPCONFIG.DAT.bak");
 // A failure parking the replacement must leave live and backup untouched.
 put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT",oldServer);
 renameCall=0;failRename=4;failPark=1;
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
 failRename=0;failPark=0;
 CHECK(equals("POPS/IPCONFIG.DAT.bak",oldIp));
 CHECK(equals("POPS/IPCONFIG.DAT","192.168.1.20 255.255.255.0 0.0.0.0\n"));
 unlink("POPS/IPCONFIG.DAT.bak");
 // If restore and returning the replacement both fail, retain both snapshots.
 put("POPS/IPCONFIG.DAT",oldIp);put("POPS/UDPFSCONFIG.DAT",oldServer);
 renameCall=0;failRename=4;failRestoreRename=1;
 // Enable return failure only after forward commits have reached rollback.
 failReturn=1;
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
 failRename=0;failRestoreRename=0;failReturn=0;
 CHECK(equals("POPS/IPCONFIG.DAT.bak",oldIp));
 CHECK(equals("POPS/IPCONFIG.DAT.tmp","192.168.1.20 255.255.255.0 0.0.0.0\n"));
 printf("POPS UDPFS: %d config/rollback checks passed\n",checks);return 0;
}
'''
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    (path / 'test.c').write_text(HARNESS.replace('@TYPE@', typedef).replace('@CODE@', pieces), encoding='utf-8')
    exe = path / ('test.exe' if os.name == 'nt' else 'test')
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(path/'test.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=path, check=True)

udpfs = (ROOT/'src/udpfssupport.c').read_text(encoding='utf-8')
assert 'ps1FillGameList(udpfsPrefix, &udpfsPs1Games)' in udpfs
assert '&udpfsLaunchVcd' in udpfs
launch = udpfs[udpfs.index('static void udpfsLaunchVcd('):udpfs.index('static void udpfsLaunchCue(')]
assert launch.index('vcdPreparePopsUdpfsLaunch(') < launch.index('vcdEnsureBdmaForLaunch(') < launch.index('vcdBdmaLaunchReady(') < launch.index('sysLaunchPopstarter(')
assert 'VCD_BDMA_UDPFS' in launch and 'VCD_PREFIX_MASS' in launch
assert 'guiMsgBox(_l(_STR_POPS_UDPFS_DRIVER_NOT_READY)' in launch
assert '_STR_VCD_NOT_ON_NET' not in launch
print('POPS UDPFS: combined scan, Favorites callback and launch preparation wiring passed')
