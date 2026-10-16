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
    'int sysTryClaimPccf(', 'int sysIsPccfOwned(', 'void sysReleasePccf(', 'int sysInitDev9('))
candidate = function(bdm, 'static int bdmPccfCandidate(')
shutdown = function((root / 'modules/iopcore/cdvdman/device-bdm.c').read_text(), 'void DeviceDeinit(')
# Reset must never infer hardware power-off from a software reboot.
assert 'sysPccfOwned = 0' not in function(system, 'void sysReset(')
opl = (root / 'src/opl.c').read_text(encoding='utf-8')
nbd = function(opl, 'static int loadLwnbdSvr(')
assert nbd.index('ioHasPendingRequests()') < nbd.index('if (sysIsPccfOwned())') < nbd.index('*teardownStarted = 1;')
assert 'ioBlockOps(0);' in nbd[nbd.index('if (sysIsPccfOwned())'):nbd.index('*teardownStarted = 1;')]
probe = function(bdm, 'static void bdmLoadPccfModule(')
request = function(bdm, 'void bdmRequestPccfProbe(')
queue = function(bdm, 'static int bdmShouldQueueModuleLoad(')
network = function((root / 'src/netsupport.c').read_text(encoding='utf-8'), 'static int netLoadModules(')
publication = function(bdm, 'static int bdmStartModeAllowsDevice(')
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
static int gEnablePCCF = 1, pccfModLoaded, pccf_bd_irx, size_pccf_bd_irx, probeLoads, probeFailure = 1, errors;
static unsigned int pccfProbeGeneration = 1, pccfAttemptGeneration, BdmGeneration;
static int requestDuringProbe;
static void bdmRequestPccfProbe(void);
#define _STR_PCCF_UNAVAILABLE 1
static int bdmLoadOptionalModule(const char *name,void *p,int size) {
    (void)name;(void)p;(void)size;probeLoads++;
    if (requestDuringProbe) {requestDuringProbe=0;bdmRequestPccfProbe();}
    return probeFailure ? -1 : 0;
}
static void setErrorMessage(int id) {(void)id;errors++;}
static void bdmForceDeviceRefresh(void) {BdmGeneration++;}
#define START_MODE_DISABLED 0
#define BDM_TYPE_USB 0
#define BDM_TYPE_ATA 3
#define BDM_TYPE_UDPBD 4
#define BDM_TYPE_PCCF 5
static int gBDMStartMode;
@PUBLICATION@
@REQUEST@
static const char *rom;
static int psx;
static int open(const char *path,int flags) {(void)flags;return !strcmp(path,"rom0:ROMVER") ? 1 : psx ? 2 : -1;}
static int read(int fd,void *p,int n) {(void)fd;int len=(int)strlen(rom);if(len>n)len=n;memcpy(p,rom,len);return len;}
static void close(int fd) {(void)fd;}
@CANDIDATE@
@PROBE@
static int gEnableUSB, iUSBModLoaded, gEnableILK, iLinkModLoaded, gEnableMX4SIO, mx4sioModLoaded;
static int gEnableBdmHDD, hddModLoaded, gEnableUDPBD, udpbdNicClaimed;
static int ethGetModulesLoaded(void) {return 0;}
static int udpfsGetModulesLoaded(void) {return 0;}
static int bdmIsUDPBDLoaded(void) {return 0;}
@QUEUE@
#define NET_PROTO_HTTP 2
#define ERROR_ETH_MODULE_NETIF_FAILURE 99
static int netModulesLoaded, netResidentProtocol, gNetworkStartup, shutdownCalls;
static int netman_irx, size_netman_irx, smsutils_irx, size_smsutils_irx, smap_irx, size_smap_irx;
static int ps2ip_irx, size_ps2ip_irx, ps2ips_irx, size_ps2ips_irx, httpclient_irx, size_httpclient_irx;
static void sysShutdownDev9(void) {shutdownCalls++;}
static void NetManInit(void) {}
static void netApplyNetIFConfig(void) {}
static int HttpInit(void) {return 0;}
static int HttpIsInitialized(void) {return 1;}
static void ps2ip_init(void) {}
@NETWORK@
#define USE_PCCF
#define DPRINTF(...) ((void)0)
static int bdm_io_sema, stops;
struct block_device {int (*stop)(struct block_device *);};
static struct block_device *g_bd;
static int stop_cf(struct block_device *bd) {(void)bd;assert(locked);stops++;return 0;}
@SHUTDOWN@
int main(int argc,char **argv) {
    assert(argc==4);rom=argv[1];psx=atoi(argv[2]);
    assert(bdmStartModeAllowsDevice(BDM_TYPE_PCCF));
    assert(bdmStartModeAllowsDevice(BDM_TYPE_UDPBD));
    assert(!bdmStartModeAllowsDevice(BDM_TYPE_USB) && !bdmStartModeAllowsDevice(BDM_TYPE_ATA));
    gEnablePCCF=0;assert(!bdmStartModeAllowsDevice(BDM_TYPE_PCCF));gEnablePCCF=1;
    gBDMStartMode=2;assert(bdmStartModeAllowsDevice(BDM_TYPE_USB));gBDMStartMode=0;
    assert(bdmPccfCandidate()==atoi(argv[3]));
    assert(sysTryClaimPccf() && !locked && sysIsPccfOwned());
    assert(netLoadModules(1)==-1 && !netModulesLoaded && !loadCalls && shutdownCalls==1);
    assert(!sysTryClaimPccf() && !sysInitDev9() && !loadCalls && !dev9InitCount && !locked);
    sysReleasePccf();assert(sysInitDev9() && loadCalls==1 && dev9InitCount==1 && !locked);
    assert(!sysTryClaimPccf());
    dev9InitCount=0;assert(!sysTryClaimPccf()); /* resident DEV9 still owns the bus */
    dev9Loaded=dev9Initialized=0;loadFailure=1;
    assert(!sysInitDev9() && dev9InitCount==1 && !sysTryClaimPccf());
    dev9InitCount=0;assert(sysTryClaimPccf());sysReleasePccf();
    assert(!sysIsPccfOwned());
    assert(bdmShouldQueueModuleLoad());
    bdmLoadPccfModule();
    assert(!pccfModLoaded && errors==1 && !sysIsPccfOwned());
    int firstLoads=probeLoads;
    for (int i=0;i<30;i++) {BdmGeneration++;assert(!bdmShouldQueueModuleLoad());bdmLoadPccfModule();}
    assert(probeLoads==firstLoads && errors==1);
    bdmRequestPccfProbe();assert(bdmShouldQueueModuleLoad());bdmLoadPccfModule();
    assert(errors==2 && probeLoads==firstLoads*2);
    if (atoi(argv[3])) {
        requestDuringProbe=1;bdmRequestPccfProbe();bdmLoadPccfModule();
        assert(bdmShouldQueueModuleLoad()); /* a request during a failed attempt is not lost */
        bdmLoadPccfModule();assert(!bdmShouldQueueModuleLoad());
    }
    unsigned int beforeProbe=pccfProbeGeneration, beforeRefresh=BdmGeneration;
    gEnablePCCF=0;bdmRequestPccfProbe();
    assert(pccfProbeGeneration==beforeProbe && BdmGeneration==beforeRefresh);
    gEnablePCCF=1;
    int beforeSuccess=probeLoads;
    probeFailure=0;bdmRequestPccfProbe();bdmLoadPccfModule();
    if (atoi(argv[3])) {
        assert(pccfModLoaded && sysIsPccfOwned());
        beforeProbe=pccfProbeGeneration;beforeRefresh=BdmGeneration;
        bdmRequestPccfProbe();bdmLoadPccfModule();assert(probeLoads==beforeSuccess+1);
        assert(pccfProbeGeneration==beforeProbe && BdmGeneration==beforeRefresh);
    } else {assert(!pccfModLoaded && !probeLoads && errors==3);}
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
'''.replace('@OWNERSHIP@', ownership).replace('@CANDIDATE@', candidate).replace('@SHUTDOWN@', shutdown).replace('@PROBE@', probe).replace('@REQUEST@', request).replace('@QUEUE@', queue).replace('@NETWORK@', network).replace('@PUBLICATION@', publication)
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

# Compile the production stubs and exercise their import ordinals as MIPS callers
# would: surplus arguments must remain ignored and no output/callback is touched.
with tempfile.TemporaryDirectory() as directory:
    temp = Path(directory)
    source = temp / 'imports.c'
    source.write_text(r"""
#include <assert.h>
#include "modules/iopcore/cdvdman/dev9-pccf.c"
static int called;
static void callback(void) { called++; }
int main(void) {
    int (*dev9)() = pccfDev9Unavailable;
    int (*ata)() = pccfAtaUnavailable;
    unsigned short ethernet[3] = {1,2,3};
    assert(dev9(ethernet)==-1 && ethernet[0]==1 && ethernet[2]==3);
    assert(dev9(0,callback)==-1 && !called);
    assert(dev9(0,ethernet,4,0)==-1);
    assert(pccfAtaInit(0)==0);
    assert(ata(0,ethernet,0,1,0)==-505);
    return 0;
}
""", encoding='utf-8')
    binary = temp / 'imports.exe'
    subprocess.run([os.environ.get('CC', 'gcc'), '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                    '-I'+str(root), '-I'+str(root/'tests/pccf/stubs'), str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
    export_text = root / 'modules/iopcore/cdvdman/exports.tab'
    preprocessed = subprocess.check_output([os.environ.get('CC', 'gcc'), '-E', '-P', '-x', 'c',
                                          '-DUSE_PCCF', str(export_text)], text=True)
    import re
    tables = dict(re.findall(r'DECLARE_EXPORT_TABLE\((\w+),[^)]*\)(.*?)END_EXPORT_TABLE', preprocessed, re.S))
    dev9 = re.findall(r'DECLARE_EXPORT\((\w+)\)', tables['dev9'])
    ata = re.findall(r'DECLARE_EXPORT\((\w+)\)', tables['atad'])
    assert len(dev9)==14 and all(dev9[i]=='pccfDev9Unavailable' for i in (5,9,11))
    assert len(ata)==19 and ata[4]=='pccfAtaInit' and set(ata[5:])=={'pccfAtaUnavailable'}
    assert 'dev9d_init' not in preprocessed and 'sceAtaDmaTransfer' not in preprocessed
print('PASS: CF hardware-inert DEV9/ATAD exports and ordinal ABI')

refresh = function((root / "src/opl.c").read_text(encoding="utf-8"), "static void itemExecRefresh(")
assert "if (bdmModeIsPCCF(support->mode))\n            bdmRequestPccfProbe();" in refresh
