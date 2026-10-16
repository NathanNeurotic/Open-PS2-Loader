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
    end = source.index('{', start)
    depth = 1
    while depth:
        end += 1
        depth += (source[end] == '{') - (source[end] == '}')
    return source[start:end + 1]

harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef struct {int value;u32 ctrl[16];void *wrmaddr,*pwr_buf;} Sio2Packet;
typedef Sio2Packet sio2_transfer_data_t;
typedef void (*Sio2McProc)(Sio2Packet *);
typedef void (*Sio2McProc2)(void);
static Sio2McProc pSio2man25[2], pSio2man51[2];
@VMC_GLOBALS@
static int locked, calls[4];
@VMC_TRACKING@
static void CpuSuspendIntr(int *state) {assert(!locked);*state=0;locked=1;}
static void CpuResumeIntr(int state) {(void)state;assert(locked);locked=0;}
static void orig0(Sio2Packet *p) {calls[0]++;p->value=10;}
static void orig1(Sio2Packet *p) {calls[1]++;p->value=11;}
static void orig2(Sio2Packet *p) {calls[2]++;p->value=20;}
static void orig3(Sio2Packet *p) {calls[3]++;p->value=21;}
static void replacement0(Sio2Packet *p) {p->value=30;}
static void replacement1(Sio2Packet *p) {p->value=31;}
static void dummy(void) {}
@DISPATCH_DEFINITION@
@HELPERS@
@INIT_WRAPPERS@
@WRAPPERS@
@INSTALL@
static void setup(void **table,int version,int alias) {
    for (int i=0;i<70;i++) table[i]=(void *)dummy;
    table[70]=NULL;
    table[25]=alias ? (void *)(version ? replacement1 : replacement0) : (void *)(version ? orig2 : orig0);
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
    invoke(fresh,25,30);invoke(fresh,49,30);invoke(fresh,55,30);
    invoke(v2,25,20); /* late V1 library cannot overwrite V2 originals */
    InstallSio2manHook(fresh,0);invoke(fresh,49,30);
    setup(fresh,1,1);InstallSio2manHook(fresh,1);
    invoke(fresh,25,31);invoke(fresh,51,31);invoke(v1,25,30);
    InstallSio2manHook(fresh,1);invoke(fresh,51,31);
    assert(HookExportEntry(fresh,100,(void *)dummy)==NULL && !locked);
    assert(GetExportEntry(NULL,25)==NULL && GetExportTableSize(NULL)==0);
    @VMC_ASSERTIONS@
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
        init_wrappers = tracking = assertions = ''
        dispatch_definition = 'static void pademu_hookSio2man(Sio2Packet *p,Sio2McProc orig) {assert(orig);orig(p);}'
        if component == 'mcemu':
            vmc = ('static Sio2McProc2 psio2_mc_transfer_init[2], psio2_transfer_reset[2];\n'
                   'static void (*pSio2man67)();\nstatic u32 *hookSio2man67(void) {return NULL;}')
            tracking = ('static int sio2TransferVersion, lastVer, initCalls[2], resetCalls[2];\n'
                        'static void init0(void) {initCalls[0]++;}\nstatic void init1(void) {initCalls[1]++;}\n'
                        'static void reset0(void) {resetCalls[0]++;}\nstatic void reset1(void) {resetCalls[1]++;}')
            init_wrappers = '\n'.join(function(source, sig) for sig in (
                'static void sio2McUnlock(', 'static void sio2McLock(',
                'static void hookSio2McInit_1(', 'static void hookSio2McInit_2('))
            tracking += ('\nstatic struct {int mcnum;} memcards[2];\n'
                         'static void Sio2McEmu(Sio2Packet *p,int ver) {lastVer=ver;p->value=40+ver;}')
            dispatch_definition = '\n'.join(function(source,sig) for sig in (
                'static void Sio2McEmu_1(', 'static void Sio2McEmu_2(', 'void hookSio2man('))
            assertions = ('psio2_mc_transfer_init[0]=init0;psio2_mc_transfer_init[1]=init1;'
                          'psio2_transfer_reset[0]=reset0;psio2_transfer_reset[1]=reset1;'
                          'hookSio2McInit_1();assert(sio2TransferVersion==0);'
                          'sio2McUnlock(0);sio2McLock(0);'
                          'hookSio2McInit_2();assert(sio2TransferVersion==1);'
                          'sio2McUnlock(1);sio2McLock(1);'
                          'assert(initCalls[0]==2 && initCalls[1]==2 && resetCalls[0]==1 && resetCalls[1]==1);'
                          'Sio2Packet mc={0};u8 cmd=0x81;mc.ctrl[0]=0x40;mc.pwr_buf=&cmd;'
                          '((Sio2McProc)v1[25])(&mc);assert(lastVer==0 && mc.value==40);'
                          '((Sio2McProc)v2[25])(&mc);assert(lastVer==1 && mc.value==41);')
            handler = function(source, 'void Sio2McEmu(')
            assert 'sio2McUnlock(ver);' in handler and 'sio2McLock(ver);' in handler
            assert 'Sio2McEmu(temp_packet, temp_packet_version);' in source
            assert 'temp_packet_version = sio2TransferVersion;' in source
        generated = (harness.replace('@VMC_GLOBALS@', vmc).replace('@HELPERS@', helpers)
                     .replace('@WRAPPERS@', wrappers).replace('@INIT_WRAPPERS@', init_wrappers)
                     .replace('@VMC_TRACKING@', tracking).replace('@VMC_ASSERTIONS@', assertions)
                     .replace('@DISPATCH_DEFINITION@', dispatch_definition)
                     .replace('@INSTALL@', function(source, 'void InstallSio2manHook(void *exp, int ver)\n{'))
                     .replace('@DISPATCH@', 'hookSio2man' if component == 'mcemu' else 'pademu_hookSio2man'))
        path = Path(directory) / (component + '.c')
        path.write_text(generated, encoding='utf-8')
        binary = path.with_suffix('.exe')
        flags = ['-std=gnu99', '-Wall', '-Wextra', '-Werror']
        if os.name != 'nt':
            flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
        subprocess.run([os.environ.get('CC', 'gcc'), *flags, str(path), '-o', str(binary)], check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)
print('PASS: VMC and PADEMU production hook regressions; console unverified')
