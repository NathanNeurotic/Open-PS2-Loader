"""Validate actual shipped driver sizes through both production BDMA validators."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/vcdsupport.c').read_text()
if len(sys.argv) > 1:
    source = subprocess.check_output(['git', 'show', sys.argv[1] + ':src/vcdsupport.c'], text=True)

def function(signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]

table = re.search(r'static const bdma_pair_sig_t vcdBdmaPairSig\[[^;]+;', source, re.S).group()
suffixes = ['usbexfat', 'mx4sio', 'mmce', 'ata', 'ilink', 'udpfs']
sizes = [[(root / 'POPS' / f'{name}.{suffix}').stat().st_size
          for name in ['usbd.irx', 'usbhdfsd.irx']] for suffix in suffixes]
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
enum { VCD_BDMA_MODE_COUNT=7, VCD_BDMA_FAT32=0, VCD_BDMA_ILINK=5, O_RDONLY=0 };
#define VCD_BDMA_MARKER "bdma_config.txt"
typedef struct {int usbdSize,hdfsdSize;} bdma_pair_sig_t;
static const char *vcdBdmaModule[]={"usbd.irx","usbhdfsd.irx"};
static int pairSize[2],markerMode,markerExists,opens,closes,cardExists=1;
static int vcdFindPopstarterMc(char *out,int n) {snprintf(out,n,"mc0:/POPSTARTER");return cardExists;}
static int vcdReadBdmaMode(void) {return markerMode;}
static int vcdGetFileSize(const char *p) {return pairSize[strstr(p,"usbhdfsd")?1:0];}
static int open(const char *path,int flags) {(void)path;assert(flags==O_RDONLY);if(markerExists){opens++;return 0;}return -1;}
static int close(int fd) {assert(fd==0);closes++;return 0;}
@TABLE@
@FUNCTIONS@
static const int shipped[][2]=@SIZES@;
int main(void) {
    for(int mode=1;mode<VCD_BDMA_MODE_COUNT;mode++) {
        pairSize[0]=shipped[mode-1][0];pairSize[1]=shipped[mode-1][1];
        markerExists=1;markerMode=mode;
        assert(vcdBdmaEnvironmentValid(mode));
        assert(!vcdBdmaManualPairMatches(mode));assert(opens==closes);
        markerExists=0;assert(vcdBdmaManualPairMatches(mode));
        for(int other=1;other<VCD_BDMA_MODE_COUNT;other++)
            if(other!=mode)assert(!vcdBdmaManualPairMatches(other));
        markerMode=0;assert(!vcdBdmaEnvironmentValid(mode));
        pairSize[1]++;assert(!vcdBdmaManualPairMatches(mode));
        pairSize[1]-=2;assert(!vcdBdmaManualPairMatches(mode));
        pairSize[1]=-1;assert(!vcdBdmaManualPairMatches(mode));
        markerMode=mode;assert(!vcdBdmaEnvironmentValid(mode));
    }
    /* Reject each preceding iLink candidate, including the immediately previous rebuild. */
    const int staleIlink[]={21609,21977,22025,22185,27081,27145};
    for(unsigned i=0;i<sizeof(staleIlink)/sizeof(staleIlink[0]);i++) {
        pairSize[0]=48500;pairSize[1]=staleIlink[i];
        markerMode=VCD_BDMA_ILINK;markerExists=1;
        assert(!vcdBdmaEnvironmentValid(VCD_BDMA_ILINK));
        markerExists=0;assert(!vcdBdmaManualPairMatches(VCD_BDMA_ILINK));
    }
    pairSize[0]=pairSize[1]=-1;assert(vcdBdmaEnvironmentValid(0));
    pairSize[0]=48500;assert(!vcdBdmaEnvironmentValid(0));
    cardExists=0;assert(!vcdBdmaEnvironmentValid(1)&&!vcdBdmaManualPairMatches(1));
    assert(!vcdBdmaEnvironmentValid(-1)&&!vcdBdmaEnvironmentValid(7));
    assert(!vcdBdmaManualPairMatches(0)&&!vcdBdmaManualPairMatches(7));
    puts("BDMA: all six shipped pairs accepted; wrong family/marker/missing/truncated pairs refused");
}
'''.replace('@TABLE@', table).replace('@FUNCTIONS@', '\n'.join(function(s) for s in
    ['int vcdBdmaEnvironmentValid(', 'static int vcdBdmaManualPairMatches('])).replace(
    '@SIZES@', '{' + ','.join('{' + ','.join(map(str, pair)) + '}' for pair in sizes) + '}')
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / 'pairs.c'
    exe = Path(temp) / 'pairs.exe'
    c.write_text(program)
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)
