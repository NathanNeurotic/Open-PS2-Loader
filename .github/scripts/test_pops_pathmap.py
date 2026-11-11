"""Exercise the production PATHMAP.INI reader/writer (UDPFS Assault 1.0.1 options) on host files.

Compiles vcdReadNetFile and the vcdPathmap* functions from src/vcdsupport.c against a
fake mc0:/mc1: tree, then checks the driver's parse rules, that unknown lines survive a write, that
nothing is written when nothing changed, the 512-byte limit and the restore after a failed write.
It also checks the POPS UDPFS page wiring in dialogs.c and gui.c.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/vcdsupport.c').read_text(encoding='utf-8')
header = (ROOT / 'include/vcdsupport.h').read_text(encoding='utf-8')
dialogs = (ROOT / 'src/dialogs.c').read_text(encoding='utf-8')
gui = (ROOT / 'src/gui.c').read_text(encoding='utf-8')
base = (ROOT / 'lng_tmpl/_base.yml').read_text(encoding='utf-8')


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


keys = re.search(r'static const char \*const vcdPathmapKeys\[VCD_PATHMAP_KEYS\] = \{[^}]*\};', source).group(0)
defines = '\n'.join(re.findall(r'#define VCD_PATHMAP_\w+\s+\d+', header))
pieces = '\n'.join(function(source, s) for s in (
    'static int vcdReadNetFile(', 'static int vcdPathmapPath(', 'static int vcdPathmapLine(',
    'static int vcdPathmapBits(', 'int vcdReadPopsPathmap(', 'int vcdWritePopsPathmap(',
))

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#ifndef O_BINARY
#define O_BINARY 0
#endif
static int writes, failWrite, noSpace;
static const char *mapped(const char *p) {
 static char b[8][512];static unsigned next;
 const char *prefix=NULL;
 if(!strncmp(p,"mc0:/",5))prefix="MC0/";
 if(!strncmp(p,"mc1:/",5))prefix="MC1/";
 if(!prefix)return p;
 char *out=b[(next++)%8];snprintf(out,512,"%s%s",prefix,p+5);return out;
}
static int hostOpen(const char *p,int f) {return open(mapped(p),f|O_BINARY,0644);}
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
 if(writes==failWrite){fputs("partial",f);fclose(f);hostUnlink(p);return -3;}
 int ok=fwrite(buf,1,len,f)==(size_t)len;
 if(fclose(f))ok=0;
 return ok?0:-3;
}
#define open hostOpen
#define unlink hostUnlink
#define opendir hostOpendir
@DEFS@
int vcdReadPopsPathmap(void);
int vcdWritePopsPathmap(int bits);
@KEYS@
@CODE@
static int checks;
#define CHECK(x) do {++checks;if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
static void put(const char *p,const char *text){FILE*f=fopen(mapped(p),"wb");if(!f)abort();fputs(text,f);fclose(f);}
static int equals(const char *p,const char *text){char b[1024]={0};FILE*f=fopen(mapped(p),"rb");if(!f)return 0;size_t n=fread(b,1,sizeof(b)-1,f);fclose(f);return n==strlen(text)&&!memcmp(b,text,n);}
static int exists(const char *p){struct stat s;return stat(mapped(p),&s)==0;}
int main(void) {
 const char *f0="mc0:/POPSTARTER/PATHMAP.INI",*f1="mc1:/POPSTARTER/PATHMAP.INI";
 mkdir("MC0",0777);mkdir("MC1",0777);
 // No POPSTARTER folder: nothing to read, nowhere to write, and no folder is made.
 CHECK(vcdReadPopsPathmap()==-3);
 CHECK(vcdWritePopsPathmap(1)==-3 && writes==0 && !exists("mc0:/POPSTARTER"));
 mkdir("MC1/POPSTARTER",0777);
 CHECK(vcdReadPopsPathmap()==0);
 // All off with no file writes nothing; turning one on creates only that key.
 CHECK(vcdWritePopsPathmap(0)==0 && writes==0 && !exists(f1));
 CHECK(vcdWritePopsPathmap(2)==0 && writes==1 && equals(f1,"DISCS_DIR=1\r\n"));
 CHECK(vcdReadPopsPathmap()==2);
 CHECK(vcdWritePopsPathmap(2)==0 && writes==1); // unchanged: no write
 // The driver's rules: case-free keys, spaces, comments, only "1", the last line wins.
 put(f1,"# mine\r\n gameid_dir = 1 ; note\r\nCHEATS_WS=yes\r\nDISCS_DIR=1\r\nDISCS_DIR=0\r\nOTHER=1\r\n;CHEATS_WS=1\r\n");
 CHECK(vcdReadPopsPathmap()==1);
 put(f1,"CHEATS_WS=1#c\nDISCS_DIR= 1 \n");CHECK(vcdReadPopsPathmap()==6);
 put(f1,"CHEATS_WS=11\nDISCS_DIR=01\nGAMEID_DIR\n=1\n");CHECK(vcdReadPopsPathmap()==0);
 // A write keeps every other line byte for byte, sets every line of a key, appends what is missing.
 put(f1,"# mine\r\n gameid_dir = 1 ; note\r\nOTHER=1\nDISCS_DIR=1\r\nDISCS_DIR=0");
 writes=0;CHECK(vcdWritePopsPathmap(4)==0 && writes==1);
 CHECK(equals(f1,"# mine\r\nGAMEID_DIR=0\r\nOTHER=1\nDISCS_DIR=0\r\nDISCS_DIR=0\r\nCHEATS_WS=1\r\n"));
 CHECK(vcdReadPopsPathmap()==4);
 // mc0's file is the one the driver reads, so it is the one edited.
 mkdir("MC0/POPSTARTER",0777);put(f0,"GAMEID_DIR=1\n");
 CHECK(vcdReadPopsPathmap()==1);
 CHECK(vcdWritePopsPathmap(3)==0 && equals(f0,"GAMEID_DIR=1\nDISCS_DIR=1\r\n"));
 CHECK(equals(f1,"# mine\r\nGAMEID_DIR=0\r\nOTHER=1\nDISCS_DIR=0\r\nDISCS_DIR=0\r\nCHEATS_WS=1\r\n"));
 // Over 512 bytes the driver ignores the file: an existing one is refused, never rewritten.
 char big[600];memset(big,'#',sizeof(big)-2);big[sizeof(big)-2]='\n';big[sizeof(big)-1]=0;
 put(f0,big);writes=0;
 CHECK(vcdReadPopsPathmap()==-3 && vcdWritePopsPathmap(1)==-3 && writes==0 && equals(f0,big));
 // A write that would grow past 512 bytes is refused and the file is left as it was.
 char edge[520];memset(edge,'#',509);edge[509]='\n';edge[510]=0; // 510 bytes
 put(f0,edge);CHECK(vcdReadPopsPathmap()==0);
 CHECK(vcdWritePopsPathmap(1)==-4 && writes==0 && equals(f0,edge));
 // A failed write puts the old file back; a full card leaves it untouched.
 put(f0,"KEEP=1\nGAMEID_DIR=1\n");writes=0;failWrite=1;
 CHECK(vcdWritePopsPathmap(0)==-3 && equals(f0,"KEEP=1\nGAMEID_DIR=1\n"));
 failWrite=0;noSpace=1;
 CHECK(vcdWritePopsPathmap(0)==-2 && equals(f0,"KEEP=1\nGAMEID_DIR=1\n"));
 noSpace=0;
 // A failed write of a new file leaves no file behind.
 unlink(f0);unlink(f1);writes=0;failWrite=1;
 CHECK(vcdWritePopsPathmap(1)==-3 && !exists(f0) && !exists(f1));
 failWrite=0;
 printf("PATHMAP.INI: %d checks passed\n",checks);
 return 0;
}
'''

code = HARNESS.replace('@DEFS@', defines).replace('@KEYS@', keys).replace('@CODE@', pieces)
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'pathmap.c'
    exe = Path(tmp) / 'pathmap'
    src.write_text(code, encoding='utf-8')
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=address,undefined', '-g', '-o', str(exe), str(src)], check=True)
    subprocess.run([str(exe)], check=True, cwd=tmp)

# The page: three rows with the file's own key names, a consecutive id run, written only on change.
assert '{.label = {"mc?:/POPSTARTER/PATHMAP.INI", -1}}' in dialogs
for i, key in enumerate(('GAMEID_DIR', 'DISCS_DIR', 'CHEATS_WS')):
    assert '{.label = {"%s", -1}}' % key in dialogs
    assert 'UI_BOOL, NETCFG_POPS_PATHMAP_%d, 1, 1, _STR_HINT_POPS_%s,' % (i, key) in dialogs
    assert 'label: HINT_POPS_%s\n' % key in base
assert 'label: POPS_PATHMAP_ERR\n' in base
page = function(gui, 'static void guiShowPopsUdpfsConfig(void)')
assert page.index('vcdReadPopsPathmap()') < page.index('diaExecuteDialog(diaPopsUdpfsConfig')
cmp = 'if (bits != (pathmap < 0 ? 0 : pathmap)) {'
assert cmp in page and page.index(cmp) < page.index('vcdWritePopsPathmap(bits)')
# An unreadable file (< 0) shows as all off, a network-only edit still returns, and it is never written.
assert 'pathmap > 0 && ((pathmap >> i) & 1)' in page
assert 'if (pathmap < 0 || vcdWritePopsPathmap(bits) != 0) {' in page
assert page.index('vcdWritePopsUdpfsNet(&cfg)') < page.index('vcdWritePopsPathmap(bits)')
# After a failed write the baseline is re-read, so undoing the switches cannot skip a needed write.
fail = page[page.index('if (pathmap < 0 || vcdWritePopsPathmap(bits) != 0) {'):]
assert fail.index('vcdReadPopsPathmap()') < fail.index('_STR_POPS_PATHMAP_ERR')
# Only a readable baseline is re-read: a file that became readable must not take switches shown as off.
assert 'if (pathmap >= 0)\n                    pathmap = vcdReadPopsPathmap();' in fail[:fail.index('_STR_POPS_PATHMAP_ERR')]
for key in ('GAMEID_DIR', 'DISCS_DIR'):
    hint = base[base.index('label: HINT_POPS_%s\n' % key):]
    assert 'SLOT0/SLOT1.VMC' in hint[:hint.index('\n- label:')]
# ee_core never sees it: the options live in the menu only.
assert 'PATHMAP' not in ''.join(p.read_text(encoding='utf-8', errors='ignore') for p in (ROOT / 'ee_core').rglob('*.[ch]'))
print('PATHMAP.INI: POPS UDPFS page wiring passed')
