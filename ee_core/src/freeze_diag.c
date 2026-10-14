/*
  In-game freeze report (INGAMEDIAG flavour only).

  When a game freezes, the player presses the IGR combo. If the IGR thread still gets to run,
  this records what the console was doing -- the game's threads, the IOP's disc and VMC
  activity -- and writes it to the memory card as plain text, then lets IGR exit as usual.
  If the combo does nothing, the EE itself is stuck, and that is the finding.

  Nothing here exists in other builds: the whole file is only compiled with INGAMEDIAG=1.
*/

// The report goes through the IOP's ioman (fio), as IGS does: ee_core has no newlib file layer.
#define NEWLIB_PORT_AWARE

#include "ee_core.h"
#include "coreconfig.h"
#include "iopmgr.h"
#include "modmgr.h"
#include "freeze_diag_core.h"
#include "freeze_diag_report.h"
#include "cd_igr_rpc.h"

#include <fileio.h>
#include <io_common.h>
#include <iopcontrol.h>

#ifndef FREEZEDIAG_BUILD
#define FREEZEDIAG_BUILD "unknown"
#endif

#define IGR_RPC_SERVER 0x80000598

// The EE count register runs at the CPU clock (294.912 MHz).
#define EE_TICKS_PER_MS           294912
// How long to wait for the IOP before declaring it stuck.
#define FREEZE_DIAG_IOP_BUDGET_MS 2000

// The text is built in game memory: by the time it is written the game is finished, and ee_core
// has no room for a 4 KB buffer. IGR has re-initialised the TLB before FreezeDiag_Write runs.
#define FREEZE_DIAG_TEXT     ((char *)0x01E00000)
#define FREEZE_DIAG_TEXT_CAP 4096

unsigned int g_freeze_diag_polls;
unsigned int g_freeze_diag_reset_failures;

static freeze_diag_report_t report;
static int report_armed;

static freeze_diag_iop_t iop_rx __attribute__((aligned(64)));
static SifRpcClientData_t igr_cd __attribute__((aligned(64)));
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

void FreezeDiag_Begin(unsigned int libpad, unsigned int pad_state, unsigned int pad_frame)
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
    report.iop_resets = iop_reboot_count;
    report.iop_reset_failures = g_freeze_diag_reset_failures;
    report.igr_polls = g_freeze_diag_polls;
    report.padopen_hooked = padOpen_hooked;
    report.libpad = libpad;
    report.pad_state = pad_state;
    report.pad_frame = pad_frame;
    report.iop_status = FREEZE_DIAG_IOP_NO_BIND;

    // The game's threads as they were when the combo was pressed. The IGR thread is at priority 0
    // here, so none of them runs while this walks the table.
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

    report_armed = 1;
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

    FlushCache(0);
    *(s32 *)UNCACHED_SEG(&rpc_arg) = 0; // 0 = shut down, do not power off
    if (SifCallRpc(&igr_cd, 1, SIF_RPC_M_NOWAIT | SIF_RPC_M_NOWBDC, &rpc_arg, sizeof(rpc_arg), NULL, 0, NULL, NULL) < 0) {
        report.shutdown_status = FREEZE_DIAG_SHUTDOWN_TIMEOUT;
        return;
    }
    while (SifCheckStatRpc(&igr_cd)) {
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

    if (!fetch_iop()) {
        // The shutdown RPC goes to the same IOP that just did not answer.
        report.shutdown_status = FREEZE_DIAG_SHUTDOWN_SKIPPED;
        return;
    }
    shutdown_with_deadline();
}

static int write_report(const char *path, const char *text, int len)
{
    int fd, written;

    fd = fioOpen(path, FIO_O_WRONLY | FIO_O_CREAT | FIO_O_TRUNC);
    if (fd < 0)
        return 0;
    written = fioWrite(fd, text, len);
    fioClose(fd);
    return written == len;
}

// Runs after the IGR IOP reboot, with SIF RPC, the IOP heap and LOADFILE up. Writes the report
// with the console's own memory card drivers (as IGS does), then reboots the IOP again so the
// rest of IGR starts from the same clean IOP it always had.
void FreezeDiag_Write(void)
{
    int len;

    if (!report_armed)
        return;
    report_armed = 0;

    LoadModule("rom0:SIO2MAN", 0, NULL);
    LoadModule("rom0:MCMAN", 0, NULL);

    len = freeze_diag_format(&report, FREEZEDIAG_BUILD, FREEZE_DIAG_TEXT, FREEZE_DIAG_TEXT_CAP);
    if (!write_report("mc0:/RIPTFRZ.TXT", FREEZE_DIAG_TEXT, len))
        write_report("mc1:/RIPTFRZ.TXT", FREEZE_DIAG_TEXT, len);

    fioExit();
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
