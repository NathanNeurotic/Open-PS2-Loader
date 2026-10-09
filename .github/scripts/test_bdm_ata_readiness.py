"""Reproduce ATA spin-up discovery with APA disabled using the real load/probe code.

Compile hddLoadModules, sceAtaInit, xhddInit and xhddDevctl plus the ATA arm of
bdmLoadBlockDeviceModules. Hardware probes fail until the existing HDD settle
finishes; the resident driver must then register the disk without loading APA.
Use --baseline <bdmsupport.c> to verify the pre-fix discovery failure.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    end = source.index('\n}', start) + 2
    return source[start:end]


bdm_path = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--baseline' else root / 'src/bdmsupport.c'
bdm = bdm_path.read_text(encoding='utf-8-sig')
load = function(bdm, 'static void bdmLoadBlockDeviceModules(void)\n{')
ata_arm = load[load.index('    if (gEnableBdmHDD && !hddModLoaded) {'):load.index('    // Network block device')]
hdd = (root / 'src/hddsupport.c').read_text(encoding='utf-8')
atad = (root / 'modules/hdd/atad/src/ps2atad.c').read_text(encoding='utf-8')
xhdd = (root / 'modules/hdd/xhdd/xhdd.c').read_text(encoding='utf-8')

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stddef.h>
#define LOG(...) ((void)0)
#define HDD_PFS_DIAG_NOT_RUN -99
#define HDD_LOADMODULES_STATUS_UNK -1
#define HDD_LOADMODULES_STATUS_ERROR -2
#define HDD_LOADMODULES_STATUS_NOERROR 0
#define HDD_LOADMODULES_STATUS_BUSYLOADING 2
#define HDD_LOADMODULES_STATUS_ALREADYLOADED 1
#define _STR_HDD_NOT_CONNECTED_ERROR 1
#define ERROR_HDD_IF_NOT_DETECTED 1
#define ATA_DEVCTL_IS_48BIT 1
#define ATA_DEVCTL_SET_TRANSFER_MODE 2
#define ATA_DEVCTL_READ_PARTITION_SECTOR 3
#define ATA_DEVCTL_GET_HIGHEST_UDMA_MODE 4
#define ATA_DIR_READ 0
typedef struct { int exists, lba48; } ata_devinfo_t;
typedef struct { int unit; } iop_file_t;
typedef struct { int unused; } iop_device_t;
typedef struct { int type, mode; } hddAtaSetMode_t;
typedef struct { unsigned int UltraDMASupport; } IDENTIFY_DEVICE_DATA;
static IDENTIFY_DEVICE_DATA deviceIdentifyData;
static int isHDPro, hddHDProKitDetected, hddModulesLoaded, hddModulesLoadCount;
static int gEnableBdmHDD, hddModLoaded, ata_devinfo_init;
static int ready, present, connected, probe_calls, module_calls, dev9_refs, devctl_calls, fail_atad;
static ata_devinfo_t info;
static int bdm_irx, hdpro_atad_irx, ps2atad_irx, xhdd_irx;
static int size_bdm_irx, size_hdpro_atad_irx, size_ps2atad_irx, size_xhdd_irx;
static int ata_bus_reset(void) { return 0; }
static int ata_init_devices(ata_devinfo_t *unused) {
    (void)unused; probe_calls++;
    if (!ready || !present) return -1;
    info.exists = 1; info.lba48 = 1; connected = 1; return 0;
}
#define atad_devinfo (&info)
@ATA_INIT@
@XHDD_INIT@
static int ata_device_set_transfer_mode(int a, int b, int c) { return 0; }
static int hdproata_device_set_transfer_mode(int a, int b, int c) { return 0; }
static int sceAtaDmaTransfer(int a, void *b, int c, int d, int e) { return 0; }
static int ata_device_identify(int a, void *b) { return 0; }
@XHDD_DEVCTL@
static int fileXioDevctl(const char *path, int cmd, void *arg, unsigned int alen, void *buf, unsigned int blen) {
    iop_file_t fd = {0}; devctl_calls++;
    return xhddDevctl(&fd, path, cmd, arg, alen, buf, blen);
}
static void sysInitDev9(void) { dev9_refs++; }
static void sysShutdownDev9(void) { dev9_refs--; }
static void hddDiagBootStageBegin(const char *s) { }
static void hddDiagBootStageEnd(const char *s, int r) { }
static void hddDiagBootStageEndVoid(const char *s) { }
static void bdmDiagBootStageBegin(const char *s) { }
static void bdmDiagBootStageEnd(const char *s, int r) { }
static int hddCheckHDProKit(void) { return 0; }
static void setErrorMessageWithCode(int a, int b) { }
static void DelayThread(int us) { assert(us == 1000000); ready = 1; }
static int sysLoadModuleBuffer(void *module, int size, int argc, void *argv) {
    module_calls++;
    if (module == &ps2atad_irx) {
        if (fail_atad) return -1;
        sceAtaInit(0); sceAtaInit(1);
    }
    if (module == &xhdd_irx) xhddInit(NULL);
    return 0;
}
@HDD_LOAD@
static int hddDiagLoadModulesReady(void) {
    int r = hddLoadModules();
    return r == HDD_LOADMODULES_STATUS_NOERROR || r == HDD_LOADMODULES_STATUS_ALREADYLOADED;
}
static void load_bdm_ata(void) {
@ATA_ARM@
}
static void reset(void) {
    hddModulesLoaded = hddModulesLoadCount = hddModLoaded = ata_devinfo_init = 0;
    ready = connected = probe_calls = module_calls = dev9_refs = devctl_calls = fail_atad = 0;
    info.exists = info.lba48 = 0; present = gEnableBdmHDD = 1;
}
int main(void) {
    /* APA startup already queries partition sectors after loading the ATA stack. It must
       recover this simulated spin-up failure even without the BDM-only fix. */
    unsigned char sectors[1024];
    reset(); load_bdm_ata();
    assert(fileXioDevctl("xhdd0:", ATA_DEVCTL_READ_PARTITION_SECTOR, NULL, 0, sectors, sizeof(sectors)) == 0);
    assert(connected);
    puts("APA control: the existing partition-sector query registers the late drive");
    reset(); load_bdm_ata();
    if (!connected) { puts("FAIL: ATA resident and settled, but BDM disk was never registered (APA Off)"); return 1; }
    assert(hddModLoaded && probe_calls == 4 && module_calls == 3 && devctl_calls == 1);
    load_bdm_ata(); assert(probe_calls == 4 && module_calls == 3 && devctl_calls == 1);
    reset(); ready = 1; load_bdm_ata();
    assert(connected && probe_calls == 1 && module_calls == 3 && devctl_calls == 1);
    reset(); gEnableBdmHDD = 0; load_bdm_ata(); assert(!connected && module_calls == 0 && devctl_calls == 0);
    reset(); fail_atad = 1; load_bdm_ata(); assert(!connected && !hddModLoaded && dev9_refs == 0 && devctl_calls == 0);
    reset(); present = 0; load_bdm_ata();
    assert(!connected && hddModLoaded && devctl_calls == 1);
    load_bdm_ata(); assert(module_calls == 3 && devctl_calls == 1); /* no idle retry loop */
    puts("BDM ATA readiness: late spin-up, ready disk, disabled source, failed module, absent disk and one-shot cases passed");
    return 0;
}
'''
for marker, code in {
    '@ATA_INIT@': function(atad, 'ata_devinfo_t *sceAtaInit(int device)\n{'),
    '@XHDD_INIT@': function(xhdd, 'static int xhddInit('),
    '@XHDD_DEVCTL@': function(xhdd, 'static int xhddDevctl('),
    '@HDD_LOAD@': function(hdd, 'int hddLoadModules(void)\n{'),
    '@ATA_ARM@': ata_arm,
}.items():
    HARNESS = HARNESS.replace(marker, code)
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'ata_readiness.c'
    exe = Path(tmp) / 'ata_readiness'
    source.write_text(HARNESS, encoding='utf-8')
    result = subprocess.run(['cc', '-std=gnu99', '-w', str(source), '-o', str(exe)], capture_output=True, text=True)
    if result.returncode:
        sys.exit(result.stderr)
    result = subprocess.run([str(exe)], capture_output=True, text=True)
    print(result.stdout, end='')
    if result.returncode:
        sys.exit(result.stderr or result.returncode)
