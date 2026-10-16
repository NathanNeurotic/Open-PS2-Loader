"""Compile production SIO2MAN hook installation and dispatch for VMC/PADEMU.

Two live versions, aliased exports, repeated installation, fresh replacement
libraries, missing entries and independent original callback dispatch are exercised.
Linux CI enables ASan/UBSan; this is a host regression, not console acceptance.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]

def function(source, signature):
    start = source.index(signature)
    while source.index(";", start) < source.index("{", start):
        start = source.index(signature, start + len(signature))
    return source[start:source.index('\n}', start) + 2]

harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef struct {int value;} Sio2Packet;
typedef Sio2Packet sio2_transfer_data_t;
typedef void (*Sio2McProc)(Sio2Packet *);
typedef void (*Sio2McProc2)(void);
static Sio2McProc pSio2man25[2], pSio2man51[2];
@VMC_GLOBALS@
static int locked, calls[4];
static void CpuSuspendIntr(int *state) {assert(!locked);*state=0;locked=1;}
static void CpuResumeIntr(int state) {(void)state;assert(locked);locked=0;}
static void orig0(Sio2Packet *p) {calls[0]++;p->value=10;}
static void orig1(Sio2Packet *p) {calls[1]++;p->value=11;}
static void orig2(Sio2Packet *p) {calls[2]++;p->value=20;}
static void orig3(Sio2Packet *p) {calls[3]++;p->value=21;}
static void dummy(void) {}
static void @DISPATCH@(Sio2Packet *p,Sio2McProc orig) {assert(orig);orig(p);}
@HELPERS@
@WRAPPERS@
@INSTALL@
static void setup(void **table,int version,int alias) {
    for (int i=0;i<70;i++) table[i]=(void *)dummy;
    table[70]=NULL;
    table[25]=(void *)(version ? orig2 : orig0);
    table[version ? 51 : 49]=alias ? table[25] : (void *)(version ? orig3 : orig1);
    table[55]=table[25]; /* a third SDK export aliases the same function */
}
static void invoke(void **table,int slot,int expected) {
    Sio2Packet p={0};((Sio2McProc)table[slot])(&p);assert(p.value==expected);
}
int main(void) {
    void *v1[71],*v2[71],*fresh[71];
    setup(v1,0,0);setup(v2,1,0);
    InstallSio2manHook(v1,0);InstallSio2manHook(v2,1);
    invoke(v1,25,10);invoke(v1,49,11);invoke(v1,55,10);
    invoke(v2,25,20);invoke(v2,51,21);invoke(v2,55,20);
    assert(calls[0]==2 && calls[1]==1 && calls[2]==2 && calls[3]==1);
    InstallSio2manHook(v1,0);InstallSio2manHook(v2,1);
    invoke(v1,25,10);invoke(v2,51,21); /* repeated install cannot save self */
    setup(fresh,0,1);InstallSio2manHook(fresh,0);
    invoke(fresh,25,10);invoke(fresh,49,10);invoke(fresh,55,10);
    invoke(v2,25,20); /* late V1 library cannot overwrite V2 originals */
    InstallSio2manHook(fresh,0);invoke(fresh,49,10);
    setup(fresh,1,1);InstallSio2manHook(fresh,1);
    invoke(fresh,25,20);invoke(fresh,51,20);invoke(v1,25,10);
    InstallSio2manHook(fresh,1);invoke(fresh,51,20);
    assert(HookExportEntry(fresh,100,(void *)dummy)==NULL && !locked);
    assert(GetExportEntry(NULL,25)==NULL && GetExportTableSize(NULL)==0);
    puts("PASS: independent v1/v2 originals, aliased exports, repeated hooks and replacement tables");
}
"""
with tempfile.TemporaryDirectory() as directory:
    for component, helper in [('mcemu', 'mcemu_sys.c'), ('pademu', 'sys_utils.c')]:
        source = (root / 'modules' / component / (component + '.c')).read_text(encoding='utf-8')
        utils = (root / 'modules' / component / helper).read_text(encoding='utf-8')
        helpers = '\n'.join(function(utils, sig) for sig in (
            'u32 GetExportTableSize(', 'void *GetExportEntry(', 'void *HookExportEntry('))
        wrappers = '\n'.join(function(source, 'static void ' + name + '(') for name in (
            'hookSio2man25_1', 'hookSio2man25_2', 'hookSio2man51_1', 'hookSio2man51_2'))
        # The first occurrence is a prototype; function() deliberately finds definitions below.
        vmc = ''
        if component == 'mcemu':
            vmc = ('static Sio2McProc2 psio2_mc_transfer_init[2], psio2_transfer_reset[2];\n'
                   'static void (*pSio2man67)();\nstatic u32 *hookSio2man67(void) {return NULL;}')
        generated = (harness.replace('@VMC_GLOBALS@', vmc).replace('@HELPERS@', helpers)
                     .replace('@WRAPPERS@', wrappers)
                     .replace('@INSTALL@', function(source, 'void InstallSio2manHook(void *exp, int ver)\n{'))
                     .replace('@DISPATCH@', 'hookSio2man' if component == 'mcemu' else 'pademu_hookSio2man'))
        path = Path(directory) / (component + '.c')
        path.write_text(generated, encoding='utf-8')
        binary = path.with_suffix('.exe')
        flags = ['-std=gnu99', '-Wall', '-Wextra', '-Werror']
        if os.name != 'nt':
            flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
        subprocess.run([os.environ.get('CC', 'gcc'), *flags, str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)
print('PASS: VMC and PADEMU production hook regressions; console unverified')
