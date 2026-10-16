"""Compile CF production drivers and ownership/eligibility checks on the host."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
system = (root / 'src/system.c').read_text(encoding='utf-8')
bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8')

def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]

ownership = '\n'.join(function(system, name) for name in (
    'int sysTryClaimPccf(', 'void sysReleasePccf(', 'int sysInitDev9('))
candidate = function(bdm, 'static int bdmPccfCandidate(')
shutdown = function((root / 'modules/iopcore/cdvdman/device-bdm.c').read_text(), 'void DeviceDeinit(')
harness = r'''
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "modules/pccf/pccf_mbr.h"
#define LOG(...) ((void)0)
#define O_RDONLY 0
static int sysDev9BusLock, locked, sysPccfOwned, dev9Initialized, dev9Loaded, dev9InitCount;
static int ps2dev9_irx, size_ps2dev9_irx, loadCalls, loadFailure;
static void WaitSema(int s) {(void)s;assert(!locked);locked=1;}
static void SignalSema(int s) {(void)s;assert(locked);locked=0;}
static int sysLoadModuleBuffer(void *p,int n,int argc,char *argv) {
    (void)p;(void)n;(void)argc;(void)argv;assert(locked);loadCalls++;return loadFailure ? -2 : 0;
}
@OWNERSHIP@
static const char *rom;
static int psx;
static int open(const char *path,int flags) {(void)flags;return !strcmp(path,"rom0:ROMVER") ? 1 : psx ? 2 : -1;}
static int read(int fd,void *p,int n) {(void)fd;int len=(int)strlen(rom);if(len>n)len=n;memcpy(p,rom,len);return len;}
static void close(int fd) {(void)fd;}
@CANDIDATE@
#define USE_PCCF
#define DPRINTF(...) ((void)0)
static int bdm_io_sema, stops;
struct block_device {int (*stop)(struct block_device *);};
static struct block_device *g_bd;
static int stop_cf(struct block_device *bd) {(void)bd;assert(locked);stops++;return 0;}
@SHUTDOWN@
int main(int argc,char **argv) {
    assert(argc==4);rom=argv[1];psx=atoi(argv[2]);
    assert(bdmPccfCandidate()==atoi(argv[3]));
    assert(sysTryClaimPccf() && !locked);
    assert(!sysTryClaimPccf() && !sysInitDev9() && !loadCalls && !dev9InitCount && !locked);
    sysReleasePccf();assert(sysInitDev9() && loadCalls==1 && dev9InitCount==1 && !locked);
    assert(!sysTryClaimPccf());
    dev9InitCount=0;assert(!sysTryClaimPccf()); /* resident DEV9 still owns the bus */
    dev9Loaded=dev9Initialized=0;loadFailure=1;
    assert(!sysInitDev9() && dev9InitCount==1 && !sysTryClaimPccf());
    dev9InitCount=0;assert(sysTryClaimPccf());sysReleasePccf();
    struct block_device cf = {stop_cf};
    DeviceDeinit();assert(!stops && !locked);
    g_bd=&cf;DeviceDeinit();assert(stops==1 && g_bd==NULL && !locked);
    DeviceDeinit();assert(stops==1 && !locked);
    unsigned char mbr[512]={0};assert(!pccf_mbr_valid(mbr,10000));
    mbr[510]=0x55;mbr[511]=0xaa;mbr[450]=0x0c;mbr[454]=1;mbr[458]=100;
    assert(pccf_mbr_valid(mbr,101));assert(!pccf_mbr_valid(mbr,100));
    mbr[450]=0x07;assert(pccf_mbr_valid(mbr,10000));
    mbr[466]=0xee;assert(!pccf_mbr_valid(mbr,10000));mbr[466]=0;
    mbr[454]=0;assert(!pccf_mbr_valid(mbr,10000));
    mbr[454]=1;mbr[461]=0xff;assert(!pccf_mbr_valid(mbr,10000));
    puts("PASS: ROM eligibility, exclusive CF/DEV9 ownership and MBR bounds");
}
'''.replace('@OWNERSHIP@', ownership).replace('@CANDIDATE@', candidate).replace('@SHUTDOWN@', shutdown)
with tempfile.TemporaryDirectory() as directory:
    temp = Path(directory)
    compiler = os.environ.get('CC', 'gcc')
    for name in ('bd', 'profile', 'ata_rw', 'ownership'):
        source = root / 'tests/pccf' / ('test_' + name + '.c')
        if name == 'ownership':
            source = temp / 'ownership.c'
            source.write_text(harness, encoding='utf-8')
        binary = temp / (name + '.exe')
        flags = ['-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I' + str(root), '-I' + str(root / 'tests/pccf/stubs')]
        if os.name != 'nt':
            flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
        subprocess.run([compiler, *flags, str(source), '-o', str(binary)], check=True)
        if name == 'ownership':
            for rom, psx, eligible in (('0100JC20000117', 0, 1), ('0101JC20000217', 0, 1),
                                      ('0120JC20001027', 0, 1), ('0160JC20011004', 0, 0),
                                      ('0100EC20000117', 0, 0), ('', 0, 0), ('0100JC20000117', 1, 0)):
                subprocess.run([str(binary), rom, str(psx), str(eligible)], check=True, timeout=10)
        else:
            subprocess.run([str(binary)], check=True, timeout=20)
print('PASS: CF low-level and integration host regressions; hardware unverified')
