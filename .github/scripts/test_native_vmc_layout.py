"""Execute native BDM/PFS launch checks, including actual slot writes and refusal paths."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
bdm = (root / 'src/bdmsupport.c').read_text(encoding='utf-8')
hdd = (root / 'src/hddsupport.c').read_text(encoding='utf-8')
start = bdm.index('int bdmCheckNativeVmcLayout(int iop_fd')
helper = bdm[start:bdm.index('\n}\n', start) + 3]
start = bdm.index('    char vmc_name[32], vmc_path[256];', bdm.index('void bdmLaunchGame('))
bdm_slots = bdm[start:bdm.index('    void *irx = NULL;', start)]
start = hdd.index('    if (part_valid) {', hdd.index('void hddLaunchGame('))
hdd_slots = hdd[start:hdd.index('    if (gRememberLastPlayed)', start)]
start = hdd.index('static int hddSyncForVMCMap(void)')
end = hdd.index('int hddVMCMapFits(const char *path)\n{', start)
hdd_helpers = hdd[start:hdd.index('\n}\n', end) + 3]

program = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "nativevmc.h"
typedef unsigned int u32;
typedef unsigned long long u64;
typedef struct { u64 sector; u32 count; } bd_fragment_t;
#define O_RDONLY 0
#define BDM_TYPE_PCCF 9
#define USBMASS_IOCTL_GET_LBA 1
#define USBMASS_IOCTL_GET_FRAGLIST 2
#define LOG(...) ((void)0)
enum { _STR_ERR_VMC_CONTINUE, _STR_ERR_VMC_FRAGMENTED_CONTINUE,
       _STR_ERR_VMC_LBA_RANGE_CONTINUE, _STR_ERR_VMC_LAYOUT_CONTINUE, _STR_ERR_VMC_PFS_LIMIT_CONTINUE };
typedef struct { int page_size, block_size, card_size; } specs_t;
typedef struct { int number, subpart, count; } pfs_blockinfo_t;
typedef struct { int active, flags; specs_t specs; u64 start_sector; } bdm_vmc_infos_t;
typedef struct { int active, flags; specs_t specs; pfs_blockinfo_t blocks[11]; } hdd_vmc_infos_t;
typedef struct { unsigned int start, length; } apa_sub_t;
#define APA_MAXSUB 64
#define HDD_VMC_MAP_ENTRIES 11
typedef struct { int mc_flag, page_size, pages_per_block, pages_per_cluster, clusters_per_card; } vmc_superblock_t;
typedef struct { int unused; } config_set_t;
typedef struct { int bdmDeviceType; const char *bdmPrefix; } device_t;
static device_t device = {0, "mass0:/"};
static config_set_t config;
static u32 bdm_mcemu_irx[128], hdd_mcemu_irx[128];
static int bdmMcemuSlots[2], hddMcemuSlots[2];
static int size_bdm_mcemu_irx = sizeof(bdm_mcemu_irx), size_hdd_mcemu_irx = sizeof(hdd_mcemu_irx);
static const char *gHDDPrefix = "pfs0:/";
static char *hddPrefix = "pfs0:", gOPLPart[32] = "hdd0:+OPL";
static int syncResult, syncs, mapReads, partResult;
static int fileXioSync(const char *dev, int flag) { assert(!strcmp(dev, "pfs0:") && flag == 0); syncs++; return syncResult; }
static int hddGetPartitionInfo(const char *part, apa_sub_t *parts) { assert(!strcmp(part, gOPLPart)); (void)parts; return partResult; }
static void *gAutoLaunchBDMGame, *gAutoLaunchGame;
static char names[2][32], messages[4][256];
static int sizes[2], opens[2], closes[2], open_result[2], lba_result[2], write_lba[2], frags[2], maps[2];
static u64 lbas[2];
static int write_extent[2], short_extent[2], wrong_extent[2];
static int finished, prompts, accept;
static int slot(const char *name) { return strstr(name, "card1") != NULL; }
static int open(const char *name, int flags) { (void)flags; int i=slot(name); opens[i]++; return open_result[i]; }
static int close(int fd) { assert(fd>=10 && fd<=11); closes[fd-10]++; return 0; }
static int ps2sdk_get_iop_fd(int fd) { return fd; }
static int fileXioIoctl2(int fd, int command, void *arg, int arglen, void *out, int outlen) {
    int i=fd-10; assert(i>=0 && i<2 && arg==NULL && arglen==0);
    if (command == USBMASS_IOCTL_GET_LBA) {
        assert(out && outlen==sizeof(u64) && *(u64 *)out==(u64)-1);
        if (write_lba[i]) *(u64 *)out=lbas[i];
        return lba_result[i];
    }
    assert(command==USBMASS_IOCTL_GET_FRAGLIST && out && outlen==sizeof(bd_fragment_t));
    bd_fragment_t *extent=out;
    assert(extent->sector==(u64)-1 && extent->count==0);
    if (write_extent[i]) {
        extent->sector=lbas[i]+wrong_extent[i];
        extent->count=short_extent[i] ? 1 : 8*2048;
    }
    return frags[i];
}
static int sysCheckVMC(const char *prefix, const char *sep, const char *name, int size, vmc_superblock_t *sb) {
    (void)prefix; (void)sep; assert(size==0); memset(sb,0,sizeof(*sb)); return sizes[slot(name)];
}
static void configGetVMC(config_set_t *cfg, char *name, int length, int i) { (void)cfg; snprintf(name,length,"%s",names[i]); }
static const char *_l(int id) {
    switch(id) {
        case _STR_ERR_VMC_CONTINUE: return "invalid %s slot %d";
        case _STR_ERR_VMC_FRAGMENTED_CONTINUE: return "fragmented %s slot %d";
        case _STR_ERR_VMC_LBA_RANGE_CONTINUE: return "range %s slot %d";
        case _STR_ERR_VMC_LAYOUT_CONTINUE: return "unknown %s slot %d";
        case _STR_ERR_VMC_PFS_LIMIT_CONTINUE: return "maplimit %s slot %d";
    }
    assert(0); return "";
}
static int guiMsgBox(const char *message, int type, void *dialog) {
    assert(type==1 && dialog==NULL && prompts<4);
    snprintf(messages[prompts++],sizeof(messages[0]),"%s",message); return accept;
}
static int sbMcemuSlotWord(void *image, int size, int i, int *cache) {
    (void)image; (void)size; (void)cache; return i*64;
}
static int hddGetFileBlockInfo(const char *path, void *parts, pfs_blockinfo_t *blocks, int max) {
    (void)parts; assert(max==11); mapReads++; memset(blocks,0,max*sizeof(*blocks)); return maps[slot(path)];
}
@HELPER@
@HDD_HELPERS@
static void run_bdm(void) {
    int fd, iop_fd;
    device_t *pDeviceData=&device;
    config_set_t *configSet=&config;
    @BDM_SLOTS@
    (void)size_mcemu_irx; finished=1;
}
static void run_hdd(void) {
    int part_valid=1, nparts, i, size_mcemu_irx=0, parts[65]={0};
    char vmc_name[2][32]; memcpy(vmc_name,names,sizeof(names));
    hdd_vmc_infos_t hdd_vmc_infos={0};
    @HDD_SLOTS@
    (void)size_mcemu_irx; finished=1;
}
static bdm_vmc_infos_t bdm_slot(int i) { bdm_vmc_infos_t v; memcpy(&v,bdm_mcemu_irx+i*64,sizeof(v)); return v; }
static hdd_vmc_infos_t hdd_slot(int i) { hdd_vmc_infos_t v; memcpy(&v,hdd_mcemu_irx+i*64,sizeof(v)); return v; }
static void reset(void) {
    memset(names,0,sizeof(names)); strcpy(names[0],"card0");
    memset(bdm_mcemu_irx,0,sizeof(bdm_mcemu_irx)); memset(hdd_mcemu_irx,0,sizeof(hdd_mcemu_irx));
    memset(opens,0,sizeof(opens)); memset(closes,0,sizeof(closes)); memset(messages,0,sizeof(messages));
    for(int i=0;i<2;i++) { sizes[i]=8; open_result[i]=10+i; lba_result[i]=0; write_lba[i]=write_extent[i]=1; short_extent[i]=wrong_extent[i]=0; frags[i]=1; lbas[i]=100; maps[i]=2; }
    finished=prompts=0; accept=1; gAutoLaunchGame=gAutoLaunchBDMGame=NULL;
    syncResult=syncs=mapReads=0; partResult=1; gHDDPrefix="pfs0:/";
}
int main(void) {
    reset(); run_bdm(); assert(finished && prompts==0 && bdm_slot(0).active && !bdm_slot(1).active);
    assert(bdm_slot(0).start_sector==100 && opens[0]==1 && closes[0]==1);
    reset(); frags[0]=2; run_bdm(); assert(finished && prompts==1 && !bdm_slot(0).active && closes[0]==1);
    assert(strstr(messages[0],"fragmented card0 slot 1"));
    for(int bad=-2;bad<=0;bad++) { reset(); frags[0]=bad; run_bdm(); assert(!bdm_slot(0).active && prompts==1 && strstr(messages[0],"unknown") && closes[0]==1); }
    reset(); write_lba[0]=0; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"unknown"));
    reset(); lba_result[0]=-1; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"unknown"));
    reset(); write_extent[0]=0; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"unknown"));
    reset(); short_extent[0]=1; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"unknown"));
    reset(); wrong_extent[0]=1; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"unknown"));
    reset(); lbas[0]=0x100000000ULL; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"range"));
    reset(); lbas[0]=0x100000000ULL-8*2048; run_bdm(); assert(bdm_slot(0).active && prompts==0);
    reset(); lbas[0]=0x100000000ULL-8*2048+1; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"range"));
    reset(); sizes[0]=INT_MAX; run_bdm(); assert(!bdm_slot(0).active && strstr(messages[0],"range"));
    reset(); sizes[0]=0; run_bdm(); assert(!bdm_slot(0).active && opens[0]==0 && strstr(messages[0],"invalid"));
    reset(); open_result[0]=-1; run_bdm(); assert(!bdm_slot(0).active && closes[0]==0);
    reset(); frags[0]=2; accept=0; run_bdm(); assert(!finished && prompts==1 && closes[0]==1);
    reset(); frags[0]=2; strcpy(names[1],"card1"); run_bdm(); assert(prompts==1 && !bdm_slot(0).active && bdm_slot(1).active && closes[1]==1);
    names[0][0]=names[1][0]=0; run_bdm(); assert(!bdm_slot(0).active && !bdm_slot(1).active);
    reset(); frags[0]=2; gAutoLaunchBDMGame=&config; run_bdm(); assert(finished && prompts==0 && !bdm_slot(0).active);
    reset(); run_hdd(); assert(finished && hdd_slot(0).active && !hdd_slot(1).active && prompts==0);
    reset(); maps[0]=-ENOMEM; run_hdd(); assert(!hdd_slot(0).active && strstr(messages[0],"maplimit"));
    reset(); maps[0]=-EIO; run_hdd(); assert(!hdd_slot(0).active && strstr(messages[0],"unknown"));
    reset(); maps[0]=0; run_hdd(); assert(!hdd_slot(0).active && strstr(messages[0],"unknown"));
    reset(); maps[0]=-ENOENT; accept=0; run_hdd(); assert(!finished && prompts==1);
    reset(); maps[0]=-EIO; strcpy(names[1],"card1"); run_hdd(); assert(prompts==1 && !hdd_slot(0).active && hdd_slot(1).active);
    reset(); maps[0]=-EIO; gAutoLaunchGame=&config; run_hdd(); assert(finished && prompts==0 && !hdd_slot(0).active);
    /* pfs0: is write-back: the map is read off the disk only after one committed sync. */
    reset(); strcpy(names[1],"card1"); run_hdd(); assert(syncs==1 && mapReads==2 && hdd_slot(0).active && hdd_slot(1).active);
    reset(); syncResult=-EIO; strcpy(names[1],"card1"); run_hdd();
    assert(syncs==1 && mapReads==0 && !hdd_slot(0).active && !hdd_slot(1).active && prompts==2 && strstr(messages[0],"unknown") && strstr(messages[1],"unknown"));
    /* An inode with no data segment gives mcemu nothing to write through: never active. */
    reset(); maps[0]=1; run_hdd(); assert(!hdd_slot(0).active && strstr(messages[0],"unknown"));
    reset(); maps[0]=10; run_hdd(); assert(hdd_slot(0).active && prompts==0);
    /* Completion check after creating on the HDD: the launch check's own verdict. */
    reset(); assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==1 && syncs==1);
    reset(); maps[0]=-ENOMEM; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==0);
    reset(); maps[0]=-EIO; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1);
    reset(); maps[0]=1; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1);
    reset(); syncResult=-EIO; maps[0]=-ENOMEM; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1 && mapReads==0);
    reset(); partResult=6; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1 && mapReads==0);
    reset(); partResult=-EIO; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1 && mapReads==0);
    reset(); gHDDPrefix=NULL; assert(hddVMCMapFits("pfs0:/VMC/card0.bin")==-1 && syncs==0);
    puts("native VMC: verified layouts, precise refusals, both slots, cancel and autolaunch pass");
    puts("native PFS VMC: map read only after a committed sync, empty maps refused, completion check matches launch");
    return 0;
}
'''.replace('@HELPER@', helper).replace('@HDD_HELPERS@', hdd_helpers).replace('@BDM_SLOTS@', bdm_slots).replace('@HDD_SLOTS@', hdd_slots)

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp)
    source = path / 'native_vmc.c'
    exe = path / 'native_vmc.exe'
    source.write_text(program, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                    '-I', str(root / 'include'), str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
