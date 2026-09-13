"""Run production ATA command setup/completion with deterministic competing callers.

The test inserts one scheduler yield between taskfile register stores. It records
commands, not physical disk behavior. No disk is opened. Pass a historical source
path and --expect-race to demonstrate the pre-fix command corruption.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
args = [arg for arg in sys.argv[1:] if arg != "--expect-race"]
source = (Path(args[0]) if args else root / "modules/hdd/atad/src/ps2atad.c").read_text()
fixed = "static int ata_io_lock(void)" in source


def function(signature):
    start = source.index(signature + "\n{")
    return source[start:source.index("\n}", start) + 2] + "\n"


prefix = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef struct { u32 lo, hi; } iop_sys_clock_t;
typedef struct { int exists; } ata_devinfo_t;
typedef struct { int type; union { void *buf; u8 *buf8; u16 *buf16; }; u32 blkcount; int dir; } ata_cmd_state_t;
static ata_cmd_state_t atad_cmd_state;
static ata_devinfo_t atad_devinfo[2] = {{1}, {0}};
#define ATA_USE_DEV9
#define USE_SPD_REGS
#define USE_ATA_REGS
#define M_PRINTF(...) ((void)0)
#define ATA_C_SCE_SECURITY_CONTROL 0x8e
#define ATA_C_SMART 0xb0
#define ATA_C_DEVICE_RESET 0x08
#define ATA_C_EXECUTE_DEVICE_DIAGNOSTIC 0x90
#define ATA_C_INITIALIZE_DEVICE_PARAMETERS 0x91
#define ATA_C_PACKET 0xa0
#define ATA_C_IDENTIFY_PACKET_DEVICE 0xa1
#define ATA_C_READ_DMA 0xc8
#define ATA_C_READ_DMA_EXT 0x25
#define ATA_C_WRITE_DMA 0xca
#define ATA_SCE_SECURITY_ERASE_UNIT 0xf4
#define ATA_SEL_LBA 0x40
#define ATA_RES_ERR_NODEV (-1)
#define ATA_RES_ERR_CMD (-2)
#define ATA_RES_ERR_NOTREADY (-3)
#define ATA_RES_ERR_TIMEOUT (-4)
#define ATA_RES_ERR_ICRC (-5)
#define ATA_RES_ERR_IO (-6)
#define ATA_EV_TIMEOUT 1
#define ATA_EV_COMPLETE 2
#define ATA_STAT_BUSY 0x80
#define ATA_STAT_ERR 1
#define ATA_ERR_ICRC 0x80
#define WEF_CLEAR 1
#define WEF_OR 2
#define SPD_INTR_ATA0 1
#define SPD_R_INTR_STAT 1
#define SPD_R_INTR_MASK 3
#define SPD_R_IF_CTRL 2
#define SPD_IF_DMA_ENABLE 8
static u16 spd[64] = {[SPD_R_INTR_STAT] = 1};
#define SPD_REG16(x) spd[x]
static int ata_evflg;
typedef struct { u8 command, type; } ata_cmd_info_t;
static const ata_cmd_info_t ata_cmd_table[] = {{ATA_C_READ_DMA,4},{ATA_C_WRITE_DMA,4},{ATA_C_DEVICE_RESET,1}};
static const ata_cmd_info_t sec_ctrl_cmd_table[] = {{0,0}}, smart_cmd_table[] = {{0,0}};
#define ATA_CMD_TABLE_SIZE 3
#define SEC_CTRL_CMD_TABLE_SIZE 1
#define SMART_CMD_TABLE_SIZE 1
static struct { u16 r_control, r_feature, r_nsector, r_sector, r_lcyl, r_hcyl, r_select, r_command, r_status; } regs = {.r_control=0x40}, *ata_hwport = &regs;
static int select_error, alarm_error, dma_error, timeout_event, cancelled, resets;
static pthread_mutex_t bus = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static _Thread_local int thread_id;
static int paused, resume_writer, contender_observed, inject;
static int GetThreadId(void) { return thread_id; }
static int WaitSema(int sema) {
    (void)sema;
    if (pthread_mutex_trylock(&bus) != 0) {
        pthread_mutex_lock(&gate);
        if (thread_id == 2) { contender_observed=1; pthread_cond_broadcast(&changed); }
        pthread_mutex_unlock(&gate);
        return pthread_mutex_lock(&bus);
    }
    return 0;
}
static int SignalSema(int sema) { (void)sema; return pthread_mutex_unlock(&bus); }
static void preempt_here(void) {
    if (!inject || thread_id != 1) return;
    pthread_mutex_lock(&gate);
    paused=1; pthread_cond_broadcast(&changed);
    while (!resume_writer) pthread_cond_wait(&changed,&gate);
    pthread_mutex_unlock(&gate);
}
static int ClearEventFlag(int a,int b) { (void)a; (void)b; return 0; }
static int ata_device_select(int d) { (void)d; return select_error; }
static unsigned int ata_alarm_cb(void *p) { (void)p; return 0; }
static void USec2SysClock(int x,iop_sys_clock_t *c) { (void)x; (void)c; }
static int SetAlarm(iop_sys_clock_t *c,unsigned int (*f)(void*),void *p) { (void)c; (void)f; (void)p; return alarm_error; }
static int CancelAlarm(unsigned int (*f)(void*),void *p) { (void)f; (void)p; cancelled++; return 0; }
static void SpdIntrEnable(int x) { (void)x; }
static void SpdSetLED(int x) { (void)x; }
static int WaitEventFlag(int a,int b,int c,u32 *bits) { (void)a; (void)b; (void)c; *bits=timeout_event ? ATA_EV_TIMEOUT : ATA_EV_COMPLETE; return 0; }
static int ata_dma_complete(void *p,u32 n,int d) { (void)p; (void)n; (void)d; return dma_error; }
static int ata_wait_busy(void) { return 0; }
static int ata_pio_transfer(ata_cmd_state_t *p) { (void)p; return 0; }
static int sceAtaGetError(void) { return 0; }
static int sceAtaWaitResult(void);
static int ata_soft_reset(void) { resets++; return 0; }
static ata_devinfo_t *ata_init(int device);
'''

production = ""
if fixed:
    production += "\n".join(re.findall(r"^static (?:int|unsigned int) ata_(?:io_sema|io_owner|io_depth|cmd_active).*;$", source, re.M)) + "\n"
    production += function("static int ata_io_lock(void)") + function("static void ata_io_unlock(void)")
signature = "(void *buf, u32 blkcount, u16 feature, u16 nsector, u16 sector, u16 lcyl, u16 hcyl, u16 select, u16 command)"
setup = function(("static int ata_exec_cmd" if fixed else "int sceAtaExecCmd") + signature)
setup = setup.replace("ata_hwport->r_sector = sector & 0xff;", "ata_hwport->r_sector = sector & 0xff; preempt_here();")
# This hardware address reads alternate status but writes device control. A RAM
# field cannot model both meanings: control writes must not clear the ready bit.
setup = setup.replace("ata_hwport->r_control & 0x40", "0x40")
production += setup
if fixed:
    production += function("int sceAtaExecCmd" + signature)
    production += function("static int ata_wait_result(void)")
production += function("int sceAtaWaitResult(void)").replace("int sceAtaWaitResult", "static int sceAtaWaitResult", 1)
if fixed:
    production += function("int sceAtaSoftReset(void)")
    production += function("ata_devinfo_t *sceAtaInit(int device)")

tests = r'''
static unsigned char record[512], probe[1024];
static struct { unsigned lba, count, command; void *buf; int dir; } issued[3];
static void *caller(void *arg) {
    thread_id=(int)(intptr_t)arg;
    int writer=thread_id==1;
    assert(sceAtaExecCmd(writer ? record : probe, writer ? 1 : 2, 0, writer ? 1 : 2,
                         writer ? 6 : 0, 0,0,0, writer ? ATA_C_WRITE_DMA : ATA_C_READ_DMA)==0);
    issued[thread_id].lba=regs.r_sector | (regs.r_lcyl<<8) | (regs.r_hcyl<<16) | ((regs.r_select&15)<<24);
    issued[thread_id].count=regs.r_nsector;
    issued[thread_id].command=regs.r_command;
    issued[thread_id].buf=atad_cmd_state.buf;
    issued[thread_id].dir=atad_cmd_state.dir;
    assert(sceAtaWaitResult()==0);
    regs.r_control=0x40; /* The simulated device is ready after completion. */
    pthread_mutex_lock(&gate);
    if (!writer) { contender_observed=1; pthread_cond_broadcast(&changed); }
    pthread_mutex_unlock(&gate);
    return NULL;
}
static ata_devinfo_t *ata_init(int device) {
#if FIXED
    assert(ata_io_depth==1 && ata_io_owner==GetThreadId());
    assert(sceAtaSoftReset()==0);
    assert(sceAtaExecCmd(record,1,0,1,6,0,0,0,ATA_C_WRITE_DMA)==0);
    assert(ata_io_depth==2);
    assert(sceAtaWaitResult()==0 && ata_io_depth==1);
#endif
    return &atad_devinfo[device];
}
int main(void) {
    pthread_t writer, reader;
#if FIXED
    ata_io_sema=1;
#endif
    inject=1;
    assert(pthread_create(&writer,NULL,caller,(void*)1)==0);
    pthread_mutex_lock(&gate);
    while(!paused) pthread_cond_wait(&changed,&gate);
    pthread_mutex_unlock(&gate);
    assert(pthread_create(&reader,NULL,caller,(void*)2)==0);
    pthread_mutex_lock(&gate);
    while(!contender_observed) pthread_cond_wait(&changed,&gate);
    resume_writer=1; pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&gate);
    pthread_join(writer,NULL); pthread_join(reader,NULL);
    printf("Requested WRITE LBA=6/count=1; programmed WRITE LBA=%u/count=%u; correct buffer=%d\n",
           issued[1].lba,issued[1].count,issued[1].buf==record);
#if EXPECT_RACE
    assert(issued[1].lba==0 && issued[1].count==2 && issued[1].buf==probe);
    puts("PASS: historical driver reproduces command corruption at injected scheduler boundary");
#else
    assert(issued[1].command==ATA_C_WRITE_DMA && issued[1].lba==6 && issued[1].count==1);
    assert(issued[1].buf==record && issued[1].dir==1);
    assert(issued[2].command==ATA_C_READ_DMA && issued[2].lba==0 && issued[2].buf==probe);
    puts("PASS: competing setup cannot change the writer's taskfile or DMA state");
#endif
#if FIXED
    inject=0; thread_id=3; regs.r_control=0x40;
    assert(ata_io_depth==0 && ata_io_owner==-1 && !ata_cmd_active);
    assert(sceAtaWaitResult()==ATA_RES_ERR_NOTREADY);
    assert(sceAtaExecCmd(record,1,0,1,6,0,0,0,ATA_C_WRITE_DMA)==0);
    assert(sceAtaExecCmd(probe,2,0,2,0,0,0,0,ATA_C_READ_DMA)==ATA_RES_ERR_NOTREADY);
    assert(sceAtaSoftReset()==ATA_RES_ERR_NOTREADY && resets==0);
    assert(sceAtaInit(0)==NULL);
    thread_id=4; assert(sceAtaWaitResult()==ATA_RES_ERR_NOTREADY); thread_id=3;
    dma_error=ATA_RES_ERR_IO;
    assert(sceAtaWaitResult()==ATA_RES_ERR_IO);
    assert(ata_io_depth==0 && !ata_cmd_active && !(spd[SPD_R_IF_CTRL]&SPD_IF_DMA_ENABLE));
    dma_error=0;
    select_error=ATA_RES_ERR_NOTREADY;
    assert(sceAtaExecCmd(record,1,0,1,6,0,0,0,ATA_C_WRITE_DMA)==ATA_RES_ERR_NOTREADY);
    select_error=0;
    assert(ata_io_depth==0 && ata_io_owner==-1 && !ata_cmd_active);
    alarm_error=-1;
    assert(sceAtaExecCmd(record,1,0,1,6,0,0,0,ATA_C_WRITE_DMA)==-1);
    alarm_error=0;
    assert(ata_io_depth==0 && ata_io_owner==-1);
    timeout_event=1;
    int before=cancelled;
    assert(sceAtaExecCmd(NULL,1,0,0,0,0,0,0,ATA_C_DEVICE_RESET)==0);
    assert(sceAtaWaitResult()==ATA_RES_ERR_TIMEOUT && cancelled==before+1);
    assert(ata_io_depth==0 && ata_io_owner==-1 && !ata_cmd_active);
    timeout_event=0; regs.r_control=0x40;
    assert(sceAtaInit(0)==&atad_devinfo[0] && resets==1);
    assert(ata_io_depth==0 && ata_io_owner==-1);
    assert(sceAtaInit(-1)==NULL && sceAtaInit(2)==NULL);
    puts("PASS: command failure, timeout cleanup, owner checks, reset exclusion and nested initialization");
#endif
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="atad-ownership-") as temp:
    c = Path(temp) / "test.c"
    exe = Path(temp) / "test"
    c.write_text(prefix + production + tests)
    subprocess.run([
        "gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
        "-Wno-unused-variable", "-pthread", f"-DFIXED={int(fixed)}",
        f"-DEXPECT_RACE={int('--expect-race' in sys.argv)}", str(c), "-o", str(exe),
    ], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
