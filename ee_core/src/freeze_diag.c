/*
  In-game freeze report (INGAMEDIAG flavour only).

  When a game freezes, the player presses the IGR combo or the power button, or the pad data
  stops (padhook.c's watchdog: the IOP stopped sending it). If the IGR thread still gets to run,
  this records what the console was doing -- the game's threads, the IOP's heap, disc and VMC
  activity -- draws it on the TV (freeze_diag_screen.c), then writes it to the memory card as
  plain text and lets IGR exit as usual. The TV page needs nothing from the IOP; the file does.

  Nothing here exists in other builds: the whole file is only compiled with INGAMEDIAG=1.
*/

#include "ee_core.h"
#include "coreconfig.h"
#include "iopmgr.h"
#include "modmgr.h"
#include "freeze_diag_core.h"
#include "freeze_diag_report.h"
#include "freeze_diag_screen.h"
#include "cd_igr_rpc.h"

#include <iopcontrol.h>
#include "modules.h"
#include "util.h"

#define IGR_RPC_SERVER 0x80000598

// IOP RAM as the EE sees it (uncached). Readable even when the IOP itself is stuck.
#define IOP_RAM_EE 0xBC000000

// The IOP heap snapshot sits in the game's memory, which IGR is about to drop: ram84 has no room
// for it (see ee_core/linkfile), and module storage must stay intact for the reboot that writes
// the report. Below 16 MB nothing of ee_core's or the launcher's lives there.
#define HEAP_SNAPSHOT ((heap_diag_snapshot_t *)0x01000000)

// The EE count register runs at the CPU clock (294.912 MHz).
#define EE_TICKS_PER_MS           294912
// How long to wait for the IOP before declaring it stuck.
#define FREEZE_DIAG_IOP_BUDGET_MS 2000

unsigned int g_freeze_diag_polls;
unsigned int g_freeze_diag_reset_failures;

static freeze_diag_report_t report __attribute__((aligned(64)));
static int report_armed;

static freeze_diag_iop_t iop_rx __attribute__((aligned(64)));
static SifRpcClientData_t igr_cd __attribute__((aligned(64)));
static SifRpcClientData_t shutdown_cd __attribute__((aligned(64)));
static s32 shutdown_arg __attribute__((aligned(64)));
static s32 rpc_arg __attribute__((aligned(64)));

static inline u32 ee_ticks(void)
{
    u32 count;

    __asm__ __volatile__("mfc0 %0, $9"
                         : "=r"(count));
    return count;
}

static int budget_spent(u32 start)
{
    return (u32)(ee_ticks() - start) >= (u32)FREEZE_DIAG_IOP_BUDGET_MS * EE_TICKS_PER_MS;
}

// Find CDVDMAN's heap record (heap_diag.h) in IOP RAM and copy it, with the 0xFF run after each
// live block. Straight memory reads: it needs nothing from the IOP, so it also works when the IOP
// is stuck and the RPC below gets no answer.
static void heap_snapshot(void)
{
    heap_diag_snapshot_t *h = HEAP_SNAPSHOT;
    volatile const u32 *rec = NULL;
    unsigned int a, i;

    h->found = 0;
    for (a = 0x800; a <= HEAP_DIAG_IOP_RAM_SIZE - HEAP_DIAG_IOP_SIZE; a += 16) {
        volatile const u32 *p = (volatile const u32 *)(IOP_RAM_EE + a);

        if (p[0] == HEAP_DIAG_MAGIC && p[1] == HEAP_DIAG_CHECK && p[2] == a) {
            rec = p;
            break;
        }
    }
    if (rec == NULL)
        return;

    for (i = 0; i < HEAP_DIAG_IOP_SIZE / 4; i++)
        ((u32 *)&h->iop)[i] = rec[i];
    for (i = 0; i < HEAP_DIAG_BLOCKS; i++) {
        unsigned int end = h->iop.blocks[i].addr + h->iop.blocks[i].size, n = 0;

        if (h->iop.blocks[i].addr != 0) {
            while (n < HEAP_DIAG_TAIL_SCAN && end + n < HEAP_DIAG_IOP_RAM_SIZE && *(volatile const u8 *)(IOP_RAM_EE + end + n) == 0xFF)
                n++;
        }
        h->tail_ff[i] = (unsigned short)n;
    }
    h->found_at = a;
    h->found = 1;
}

void FreezeDiag_Begin(unsigned int libpad, unsigned int pad_state, unsigned int pad_frame, unsigned int trigger)
{
    USE_LOCAL_EECORE_CONFIG;
    ee_thread_status_t status;
    int id, i;

    for (i = 0; i < (int)sizeof(report.game_id); i++)
        report.game_id[i] = config->GameID[i];
    report.game_mode = (unsigned char)config->GameMode;
    report.compat = g_compat_mask;
    report.cheats = config->gCheatList != NULL;
    report.gsm = config->EnableGSMOp != 0;
    report.pademu = config->EnablePadEmuOp != 0;
    report.trigger = trigger;
    report.iop_resets = iop_reboot_count;
    report.iop_reset_failures = g_freeze_diag_reset_failures;
    report.igr_polls = g_freeze_diag_polls;
    report.padopen_hooked = padOpen_hooked;
    report.libpad = libpad;
    report.pad_state = pad_state;
    report.pad_frame = pad_frame;
    report.iop_status = FREEZE_DIAG_IOP_NO_BIND;

    // The sampler suspended game threads before waking us, including priority-0
    // competitors. Their status includes that suspension when this walks the table.
    report.thread_count = 0;
    report.threads_total = 0;
    for (id = 1; id < 256; id++) {
        if (ReferThreadStatus(id, &status) < 0)
            continue;
        report.threads_total++;
        if (report.thread_count < FREEZE_DIAG_MAX_THREADS) {
            freeze_diag_thread_t *t = &report.threads[report.thread_count++];
            t->id = id;
            t->status = status.status;
            t->prio = status.current_priority;
            t->wait_type = status.waitType;
            t->wait_id = status.waitId;
            t->wakeup = status.wakeupCount;
            t->entry = (unsigned int)status.func;
        }
    }

    heap_snapshot();

    report_armed = 1;

    // A stuck IOP answers none of what follows: the TV gets the report first.
    FreezeDiag_Screen(&report, HEAP_SNAPSHOT);
}

// Ask CDVDFSV for CDVDMAN's record over the IGR RPC, with a deadline: a stuck IOP must not hang
// IGR. Returns 1 when the IOP answered, 0 when it did not.
static int fetch_iop(void)
{
    u32 start;
    int i;

    start = ee_ticks();
    igr_cd.server = NULL;
    for (;;) {
        if (SifBindRpc(&igr_cd, IGR_RPC_SERVER, SIF_RPC_M_NOWAIT) < 0) {
            report.iop_status = FREEZE_DIAG_IOP_NO_BIND;
            return 0;
        }
        while (SifCheckStatRpc(&igr_cd)) {
            if (budget_spent(start)) {
                report.iop_status = FREEZE_DIAG_IOP_NO_BIND;
                return 0;
            }
            nopdelay();
        }
        if (igr_cd.server != NULL)
            break;
        if (budget_spent(start)) {
            report.iop_status = FREEZE_DIAG_IOP_NO_BIND;
            return 0;
        }
        nopdelay();
    }

    // Nothing of iop_rx may sit dirty in the cache while the SIF writes it.
    FlushCache(0);
    *(s32 *)UNCACHED_SEG(&rpc_arg) = 0;
    if (SifCallRpc(&igr_cd, FREEZE_DIAG_RPC_FNO, SIF_RPC_M_NOWAIT | SIF_RPC_M_NOWBDC, &rpc_arg, sizeof(rpc_arg), &iop_rx, sizeof(iop_rx), NULL, NULL) < 0) {
        report.iop_status = FREEZE_DIAG_IOP_CALL_FAILED;
        return 0;
    }
    while (SifCheckStatRpc(&igr_cd)) {
        if (budget_spent(start)) {
            report.iop_status = FREEZE_DIAG_IOP_TIMEOUT;
            return 0;
        }
        nopdelay();
    }

    for (i = 0; i < (int)(sizeof(iop_rx) / sizeof(u32)); i++)
        ((u32 *)&report.iop)[i] = ((volatile u32 *)UNCACHED_SEG(&iop_rx))[i];
    report.iop_status = FREEZE_DIAG_IOP_ANSWERED; // the formatter still checks magic/version
    return 1;
}

// OPL's IGR shutdown request (the same RPC oplIGRShutdown(0) sends), with a deadline. CDVDMAN's
// shutdown waits for its device: behind a stalled read it would never return, and IGR would
// never reach the point where the report is written.
static void shutdown_with_deadline(void)
{
    u32 start = ee_ticks();

    // Keep a timed-out report request on its own client and buffers.
    shutdown_cd.server = igr_cd.server;
    FlushCache(0);
    *(s32 *)UNCACHED_SEG(&shutdown_arg) = 0; // 0 = shut down, do not power off
    if (SifCallRpc(&shutdown_cd, 1, SIF_RPC_M_NOWAIT | SIF_RPC_M_NOWBDC, &shutdown_arg, sizeof(shutdown_arg), NULL, 0, NULL, NULL) < 0) {
        report.shutdown_status = FREEZE_DIAG_SHUTDOWN_TIMEOUT;
        return;
    }
    while (SifCheckStatRpc(&shutdown_cd)) {
        if (budget_spent(start)) {
            report.shutdown_status = FREEZE_DIAG_SHUTDOWN_TIMEOUT;
            return;
        }
        nopdelay();
    }
    report.shutdown_status = FREEZE_DIAG_SHUTDOWN_DONE;
}

// Replaces oplIGRShutdown(0) in this flavour. Without a report to take (IGS, power-off) it is
// exactly oplIGRShutdown(0).
void FreezeDiag_FetchAndShutdown(void)
{
    if (!report_armed) {
        oplIGRShutdown(0);
        return;
    }

    fetch_iop();
    if (report.iop_status == FREEZE_DIAG_IOP_NO_BIND) {
        // No server was bound; a shutdown call cannot be issued.
        report.shutdown_status = FREEZE_DIAG_SHUTDOWN_SKIPPED;
        return;
    }
    shutdown_with_deadline();
}

// Runs after the IGR IOP reboot, with SIF RPC, the IOP heap and LOADFILE up. ee_core has no room
// for a formatter or the EE file client, so it copies the raw record to the IOP and loads
// freezediag.irx, which formats it and writes mc0:/RIPTFRZ.TXT with the ROM card driver (MCMAN,
// as IGS uses). Then the IOP is rebooted again so the rest of IGR starts from a clean IOP.
void FreezeDiag_Write(void)
{
    static const char hex[] = "0123456789ABCDEF";
    unsigned int size = (sizeof(report) + 15) & ~15;
    char arg[18]; // two IOP addresses: the report, then the heap snapshot right after it
    u8 *iop;
    int i;

    if (!report_armed)
        return;
    report_armed = 0;

    LoadModule("rom0:SIO2MAN", 0, NULL);
    LoadModule("rom0:MCMAN", 0, NULL);

    iop = SifAllocIopHeap(size + sizeof(heap_diag_snapshot_t));
    if (iop != NULL) {
        FlushCache(0); // CopyToIop DMAs from memory, not from the cache
        CopyToIop(&report, size, iop);
        CopyToIop(HEAP_SNAPSHOT, sizeof(heap_diag_snapshot_t), iop + size);
        for (i = 0; i < 8; i++) {
            arg[i] = hex[((u32)iop >> (28 - 4 * i)) & 0xF];
            arg[9 + i] = hex[((u32)(iop + size) >> (28 - 4 * i)) & 0xF];
        }
        arg[8] = '\0';
        arg[17] = '\0';
        LoadOPLModule(OPL_MODULE_ID_FREEZEDIAG, 0, sizeof(arg), arg);
        SifFreeIopHeap(iop);
    }

    SifExitIopHeap();
    LoadFileExit();
    SifExitRpc();

    SifInitRpc(0);
    while (!Reset_Iop("", 0)) {
        ;
    }
    while (!SifIopSync()) {
        ;
    }
    SifInitRpc(0);
    SifInitIopHeap();
    LoadFileInit();
    sbv_patch_enable_lmb();
}
