"""Exercise production UDPFS DAT population/editor code with host IO and MC faults."""
from pathlib import Path
import json
import hashlib
import io
import os
import re
import subprocess
import tempfile
import zipfile

from package_release_app import verify_udpfs_payload

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
    'int vcdPopsUdpfsNetValid(', 'static const char *vcdUdpfsConfigLine(',
    'static int vcdUdpfsParseQuad(', 'static int vcdPopsUdpfsConfigPath(',
    'static int vcdWritePopsUdpfsFile(', 'int vcdInstallPopsUdpfsNet(',
    'int vcdReadPopsUdpfsNet(', 'int vcdWritePopsUdpfsNet(',
))
HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#ifndef O_BINARY
#define O_BINARY 0
#endif
#define MAX_BDM_DEVICES 10
#define BDM_TYPE_USB 7
#define LOG(...) ((void)0)
static int writes, failWrite, failRestore, noSpace, corruptWrite;
static const char *deny;
static const char *mapped(const char *p) {
 static char b[8][512];static unsigned next;
 const char *prefix=NULL;
 if(!strncmp(p,"mc0:/",5))prefix="MC0/";
 if(!strncmp(p,"mc1:/",5))prefix="MC1/";
 if(!strncmp(p,"udpfs:/",7))prefix="GAME/";
 if(!prefix)return p;
 char *out=b[(next++)%8];snprintf(out,512,"%s%s",prefix,p+(!strncmp(p,"udpfs:",6)?7:5));return out;
}
static int hostOpen(const char *p,int f) {
 if(deny && !strcmp(p,deny)){errno=EACCES;return -1;}
 return open(mapped(p),f|O_BINARY,0644);
}
static int hostMkdir(const char *p,int mode) {
#ifdef _WIN32
 (void)mode; return mkdir(mapped(p));
#else
 return mkdir(mapped(p),mode);
#endif
}
static int hostUnlink(const char *p) {return unlink(mapped(p));}
static DIR *hostOpendir(const char *p) {return opendir(mapped(p));}
static int vcdFindPopstarterMc(char *out,int n) {
 for(int i=0;i<2;i++){snprintf(out,n,"mc%d:/POPSTARTER",i);DIR*d=hostOpendir(out);if(d){closedir(d);return 1;}}
 return 0;
}
static int vcdSafeWriteFile(const char *p,const void *buf,int len) {
 if(noSpace)return -2;
 ++writes;
 FILE*f=fopen(mapped(p),"wb");if(!f)return -3;
 if(writes==failWrite || writes==failRestore){fputs("partial",f);fclose(f);hostUnlink(p);return -3;}
 int ok=fwrite(buf,1,len,f)==(size_t)len;
 if(corruptWrite){fputc('!',f);corruptWrite=0;}
 if(fclose(f))ok=0;
 return ok?0:-3;
}
#define open hostOpen
#define mkdir hostMkdir
#define unlink hostUnlink
#define opendir hostOpendir
@TYPE@
@CODE@
static int checks;
#define CHECK(x) do {++checks;if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
static void put(const char *p,const char *text){FILE*f=fopen(mapped(p),"wb");if(!f)abort();fputs(text,f);fclose(f);}
static int equals(const char *p,const char *text){char b[512]={0};FILE*f=fopen(mapped(p),"rb");if(!f)return 0;fread(b,1,sizeof(b)-1,f);fclose(f);return !strcmp(b,text);}
static int exists(const char *p){struct stat s;return stat(mapped(p),&s)==0;}
int main(void) {
 vcd_pops_udpfs_t c,changed;
 const char *ip="192.168.1.20 255.255.255.0 0.0.0.0\n",*srv="192.168.1.21\n";
 const char *ip0="mc0:/SYS-CONF/IPCONFIG.DAT",*srv0="mc0:/SYS-CONF/UDPFSCONFIG.DAT";
 const char *ip1="mc1:/SYS-CONF/IPCONFIG.DAT",*srv1="mc1:/SYS-CONF/UDPFSCONFIG.DAT";
 mkdir("MC0",0777);mkdir("MC1",0777);mkdir("GAME",0777);mkdir("GAME/POPS",0777);
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.ipExists && !c.serverExists && !c.invalid);
 CHECK(c.ps2Ip[3]==10 && c.server[0]==0 && writes==0);
 CHECK(!exists("MC0/SYS-CONF"));
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && writes==0);
 CHECK(!exists("MC0/SYS-CONF"));
 put("udpfs:/POPS/IPCONFIG.DAT",ip);put("udpfs:/POPS/UDPFSCONFIG.DAT",srv);
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && writes==2);
 CHECK(equals(ip0,ip)&&equals(srv0,srv));
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && writes==2);
 put("udpfs:/POPS/IPCONFIG.DAT","different game config");
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && equals(ip0,ip));
 unlink(srv0);CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && writes==3);
 CHECK(equals(ip0,ip)&&equals(srv0,srv));
 // A file on MC1 is already on MC: do not create a shadow on MC0.
 mkdir("MC1/SYS-CONF",0777);unlink(srv0);put(srv1,srv);
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && writes==3 && !exists(srv0));
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && !c.invalid && c.ps2Ip[3]==20 && c.server[3]==21);
 CHECK(strstr(c.home,"mc1:")!=NULL);
 changed=c;changed.server[3]=22;
 CHECK(vcdWritePopsUdpfsNet(&changed)==0 && equals(srv1,"192.168.1.22\n") && !exists(srv0));
 // Editor updates the effective MC0 file when both cards hold one.
 put(srv0,srv);put(srv1,"192.168.1.99\n");
 CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.server[3]==21);
 changed=c;changed.server[3]=22;
 CHECK(vcdWritePopsUdpfsNet(&changed)==0 && equals(srv0,"192.168.1.22\n") && equals(srv1,"192.168.1.99\n"));
 for(int failure=1;failure<=4;failure++) {
  put(ip0,ip);put(srv0,srv);writes=0;failWrite=failure;
  CHECK(vcdWritePopsUdpfsNet(&changed)!=0);failWrite=0;
  CHECK(equals(ip0,ip)&&equals(srv0,srv));
  CHECK(!exists("mc0:/SYS-CONF/IPCONFIG.DAT.bak")&&!exists("mc0:/SYS-CONF/UDPFSCONFIG.DAT.bak"));
 }
 // A failed rollback retains the original backup and blocks another save.
 put(ip0,ip);put(srv0,srv);writes=0;failWrite=4;failRestore=5;
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);failWrite=failRestore=0;
 CHECK(equals("mc0:/SYS-CONF/IPCONFIG.DAT.bak",ip));
 CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
 unlink("mc0:/SYS-CONF/IPCONFIG.DAT.bak");put(ip0,ip);
 noSpace=1;CHECK(vcdWritePopsUdpfsNet(&changed)!=0);noSpace=0;
 CHECK(equals(ip0,ip)&&equals(srv0,srv));
 corruptWrite=1;CHECK(vcdWritePopsUdpfsNet(&changed)!=0);
 CHECK(equals(ip0,ip)&&equals(srv0,srv));
 // Population failures leave no partial destination, and retry succeeds.
 unlink(srv0);unlink(srv1);writes=0;failWrite=1;
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")!=0 && !exists(srv0));failWrite=0;
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && equals(srv0,srv));
 deny=ip0;CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")!=0);deny=NULL;
 put(ip0,"bad IP");CHECK(vcdReadPopsUdpfsNet(&c)==0 && c.invalid);
 put(ip0,"\xef\xbb\xbf#comment\r\n192.168.1.20 255.255.255.0\r\n");
 CHECK(vcdReadPopsUdpfsNet(&c)==0&&!c.invalid&&c.gateway[0]==0);
 changed=c;changed.server[2]=2;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;changed.ps2Ip[0]=127;CHECK(!vcdPopsUdpfsNetValid(&changed));
 changed=c;memset(changed.server,0,sizeof(changed.server));
 CHECK(vcdWritePopsUdpfsNet(&changed)==0 && equals(srv0,""));
 CHECK(vcdReadPopsUdpfsNet(&c)==0&&!c.invalid&&c.server[0]==0);
 // Existing MC1 installation chooses MC1 for missing DATs.
 unlink(ip0);unlink(srv0);mkdir("MC1/POPSTARTER",0777);put("udpfs:/POPS/IPCONFIG.DAT",ip);
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==0 && equals(ip1,ip)&&equals(srv1,srv));
 CHECK(!exists(ip0)&&!exists(srv0));
 unlink(srv1);char large[122];memset(large,'x',121);large[121]=0;put("udpfs:/POPS/UDPFSCONFIG.DAT",large);
 CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")!=0 && !exists(srv1));
    // An interrupted settings save must be recovered before automatic population.
    put("udpfs:/POPS/UDPFSCONFIG.DAT",srv);
    put("mc1:/SYS-CONF/UDPFSCONFIG.DAT.bak","original server config");
    CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")!=0 && !exists(srv1));
    CHECK(equals("mc1:/SYS-CONF/UDPFSCONFIG.DAT.bak","original server config"));
    unlink("mc1:/SYS-CONF/UDPFSCONFIG.DAT.bak");
    noSpace=1;CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")==-2 && !exists(srv1));noSpace=0;
    corruptWrite=1;CHECK(vcdInstallPopsUdpfsNet("udpfs:/POPS/")!=0 && !exists(srv1));
 printf("POPS UDPFS: %d population, precedence, config and rollback checks passed\n",checks);return 0;
}
'''
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    (path / 'test.c').write_text(HARNESS.replace('@TYPE@', typedef).replace('@CODE@', pieces), encoding='utf-8')
    exe = path / ('test.exe' if os.name == 'nt' else 'test')
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(path/'test.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=path, check=True)

udpfs = (ROOT/'src/udpfssupport.c').read_text(encoding='utf-8')
launch = udpfs[udpfs.index('static void udpfsLaunchVcd('):udpfs.index('static void udpfsLaunchCue(')]
assert launch.index('vcdInstallPopsUdpfsNet(') < launch.index('vcdEquipBdmaFromPops(') < launch.index('sysLaunchPopstarter(')
assert 'vcdInstallPopstarterMc(udpfsPrefix)' in launch
assert 'VCD_BDMA_UDPFS' in launch and 'VCD_PREFIX_MASS' in launch
assert 'vcdEnsureBdmaForLaunch(' not in launch
assert 'ps1FillGameList(udpfsPrefix, &udpfsPs1Games)' in udpfs
launch_harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#define VCD_BDMA_UDPFS 6
#define VCD_PREFIX_MASS 1
#define POPS_FOLDER "POPS"
#define O_RDONLY 0
enum {_STR_POPS_UDPFS_NOT_READY,_STR_ERR_FILE_INVALID,_STR_POPSTARTER_NOT_FOUND,_STR_PLEASE_WAIT,
      _STR_BDMA_ERR_SPACE,_STR_BDMA_ERR_IO,_STR_BDMA_ERR_OLD,_STR_BDMA_ERR_SRC,_STR_POPS_UDPFS_DRIVER_NOT_READY};
typedef struct {int mode;} item_list_t;
typedef int config_set_t;
static const char *udpfsPrefix="udpfs:/";
static int ready,gBdmaApplyOnLaunch,equips,configs,installs,launched,teardown,error;
static int equipError,configError,clean=1;
static int vcdBdmaLaunchReady(int m){return ready==m;}
static const char *_l(int s){(void)s;return "message";}
static int guiMsgBox(const char *s,int a,void *b){(void)s;(void)a;(void)b;error++;return 0;}
static void guiMsgBoxMissing(const char *s,const char *p){(void)s;(void)p;error++;}
static int cueOnly,opens;
static int open(const char *p,int f){assert(f==0);opens++;
 if(!strcmp(p,"udpfs:/POPS/Game.VCD"))return cueOnly?-1:0;
 assert(cueOnly&&(!strcmp(p,"udpfs:/POPS/Game.cue")||!strcmp(p,"udpfs:/POPS/Game.CUE")));
 return cueOnly==1&&!strcmp(p,"udpfs:/POPS/Game.CUE")?0:-1;}
static int close(int f){assert(f==0);return 0;}
static int vcdResolvePopstarter(const char *p,char *elf,int n){assert(!strcmp(p,udpfsPrefix));snprintf(elf,n,"udpfs:/POPS/POPSTARTER.ELF");return 1;}
static void vcdDescribePopstarterLookup(const char *p,char *out,int n){(void)p;(void)out;(void)n;}
static void guiRenderTextScreen(const char *s){(void)s;}
static int vcdInstallPopstarterMc(const char *p){assert(!strcmp(p,udpfsPrefix));installs++;return 0;}
static int vcdInstallPopsUdpfsNet(const char *p){assert(!strcmp(p,"udpfs:/POPS/"));configs++;return configError;}
static int vcdEquipBdmaFromPops(const char *p,int m,char *d,int n){(void)d;(void)n;assert(!strcmp(p,"udpfs:/POPS/"));equips++;if(!equipError)ready=m;return equipError;}
static int vcdConfirmCleanLaunch(const char *p){assert(!strcmp(p,"udpfs:/"));return clean;}
static void vcdBuildSelector(const char *p,int mode,const char *name,char *s,int n){assert(!strcmp(p,udpfsPrefix)&&mode==1&&!strcmp(name,"Game"));snprintf(s,n,"mass:/POPS/XX.Game.ELF");}
static void vcdPrepareRetroGemBarcode(const char *p){assert(!strcmp(p,"udpfs:/POPS/Game.VCD"));}
static int sbLoaderDeinitException(const char *p){(void)p;return 0;}
static int oplPath2Mode(const char *p){(void)p;return 0;}
static void deinitEx(int a,int b,int c){(void)a;(void)b;(void)c;teardown++;}
static void sysLaunchPopstarter(const char *p,const char *s){assert(!strcmp(p,"udpfs:/POPS/POPSTARTER.ELF")&&!strcmp(s,"mass:/POPS/XX.Game.ELF"));launched++;}
@LAUNCH@
static void reset(void){ready=equips=configs=installs=launched=teardown=error=equipError=configError=cueOnly=opens=0;gBdmaApplyOnLaunch=clean=1;}
int main(void){
 item_list_t list={0};
 reset();udpfsLaunchVcd(&list,"Game",NULL);
 assert(launched==1&&teardown==1&&equips==1&&configs==1&&installs==1&&ready==6);
 reset();ready=6;udpfsLaunchVcd(&list,"Game",NULL);
 assert(launched==1&&equips==0&&configs==1);
 reset();ready=6;gBdmaApplyOnLaunch=0;udpfsLaunchVcd(&list,"Game",NULL);
 assert(launched==1&&equips==0&&configs==1);
 reset();gBdmaApplyOnLaunch=0;udpfsLaunchVcd(&list,"Game",NULL);assert(error&&!launched&&!teardown);
 reset();equipError=-5;udpfsLaunchVcd(&list,"Game",NULL);assert(error&&!launched&&!teardown);
 reset();ready=6;configError=-3;udpfsLaunchVcd(&list,"Game",NULL);assert(error&&!launched&&!teardown&&!equips);
 reset();ready=6;clean=0;udpfsLaunchVcd(&list,"Game",NULL);assert(!launched&&!teardown);
 reset();ready=6;udpfsLaunchVcd(&list,"Game",NULL);assert(launched==1&&opens==1); // a .VCD is not second-guessed
 reset();ready=6;cueOnly=1;udpfsLaunchVcd(&list,"Game",NULL);assert(launched==1&&opens==3); // cue-only game
 reset();ready=6;cueOnly=2;udpfsLaunchVcd(&list,"Game",NULL);assert(error&&!launched&&!teardown&&opens==3);
 puts("POPS UDPFS: network-only launch without USB, automatic/manual pairs, skip-on-valid and pre-teardown failures passed");
}
'''
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    cfile = path/'launch.c'
    cfile.write_text(launch_harness.replace('@LAUNCH@', launch), encoding='utf-8')
    exe = path/('launch.exe' if os.name == 'nt' else 'launch')
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# The scan on a fake directory: UDPFS lists uppercase *.VCD and *.cue/*.CUE once per game; any other
# device keeps its case-insensitive .VCD-only listing.
SCAN = r"""
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
typedef unsigned int u32;
#define VCD_NAME_MAX 256
#define VCD_MAX_ITEMS 2048
#define ISO_GAME_NAME_MAX 160
#define LOG(...) ((void)0)
typedef struct { char name[VCD_NAME_MAX]; u32 sizeMB; } vcd_entry_t;
struct fake_dirent { char d_name[256]; };
typedef struct { const char **names; int at; struct fake_dirent de; } FAKE_DIR;
#define dirent fake_dirent
#define DIR FAKE_DIR
static const char **gNames;
static FAKE_DIR gDir;
static FAKE_DIR *opendir(const char *p) { (void)p; gDir.names = gNames; gDir.at = 0; return &gDir; }
static struct fake_dirent *readdir(FAKE_DIR *d) {
    if (d->names[d->at] == NULL) return NULL;
    snprintf(d->de.d_name, sizeof(d->de.d_name), "%s", d->names[d->at++]); return &d->de;
}
static int closedir(FAKE_DIR *d) { (void)d; return 0; }
static int gAutosort = 1;
static int vcdEntryCmp(const void *a, const void *b) { return strcmp(((const vcd_entry_t *)a)->name, ((const vcd_entry_t *)b)->name); }
static int vcdJoinDirFile(char *o, int n, const char *d, const char *f) { (void)o; (void)n; (void)d; (void)f; return -1; }
static void vcdNoteScanDir(const char *n, const char *d) { (void)n; (void)d; }
""" + function('static int vcdScanOpenDir(') + r"""
static int scan(const char *dir, const char **names, vcd_entry_t **list) { gNames = names; return vcdScanOpenDir(dir, list, 0); }
int main(void) {
    vcd_entry_t *l = NULL;
    const char *udp[] = {"A.cue", "A.VCD", "B.VCD", "B.CUE", "C.CUE", "C.cue", "D.Cue", "E.vcd", "F.bin", "G.VCD", NULL};
    const char *usb[] = {"A.cue", "B.VCD", "C.vcd", NULL};
    assert(scan("udpfs:/POPS", udp, &l) == 4);
    assert(!strcmp(l[0].name, "A") && !strcmp(l[1].name, "B") && !strcmp(l[2].name, "C") && !strcmp(l[3].name, "G"));
    free(l); l = NULL;
    assert(scan("mass0:/POPS", usb, &l) == 2 && !strcmp(l[0].name, "B") && !strcmp(l[1].name, "C"));
    free(l);
    puts("POPS UDPFS: the scan lists .cue/.CUE once per game on UDPFS only");
    return 0;
}
"""
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    (path/'scan.c').write_text(SCAN, encoding='utf-8')
    exe = path/('scan.exe' if os.name == 'nt' else 'scan')
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(path/'scan.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
releases = json.loads((ROOT/'POPS/UDPFS-NOTICES/PROVENANCE.json').read_text())
assert len(releases) == 1 and releases[0]['tag'] == 'UDPFS_TEST' and releases[0]['prerelease'] is True
assert releases[0]['files']['POPS/usbd.irx.udpfs']['bytes'] == 51029
for release in releases:
    for name, expected in release['files'].items():
        data = (ROOT/name).read_bytes()
        assert len(data) == expected['bytes']
        assert hashlib.sha256(data).hexdigest() == expected['sha256']
print('POPS UDPFS: game-device equip, shared launch callback and upstream binary hashes passed')

payload = {p.relative_to(ROOT).as_posix(): p.read_bytes()
           for p in (ROOT/'POPS/UDPFS-NOTICES').rglob('*') if p.is_file()}
for suffix in ('udpfs',):
    for module in ('usbd.irx', 'usbhdfsd.irx'):
        name = f'POPS/{module}.{suffix}'
        payload[name] = (ROOT/name).read_bytes()

def verify_zip(files):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as package:
        for name, data in files.items():
            package.writestr(name, data)
    archive.seek(0)
    with zipfile.ZipFile(archive) as package:
        return verify_udpfs_payload(package)

assert verify_zip(payload) == set(payload)
for missing in ('POPS/usbhdfsd.irx.udpfs', 'POPS/UDPFS-NOTICES/NETWORK/LICENSE'):
    changed = dict(payload)
    del changed[missing]
    try:
        verify_zip(changed)
    except ValueError:
        pass
    else:
        raise AssertionError(f'package accepted missing {missing}')
changed = dict(payload)
name = 'POPS/usbd.irx.udpfs'
changed[name] = bytes([payload[name][0] ^ 1]) + payload[name][1:]
try:
    verify_zip(changed)
except ValueError:
    pass
else:
    raise AssertionError('package accepted corrupted driver of the correct size')
print('POPS UDPFS: release ZIP accepts verified pairs and refuses missing notices, companions or changed bytes')
