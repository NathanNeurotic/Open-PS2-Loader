/*
  padhook.c Open PS2 Loader In Game Reset

  Copyright 2009-2010, Ifcaro, jimmikaelkael & Polo
  Copyright 2006-2008 Polo
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  Reset SPU function taken from PS2SDK freesd.
  Copyright (c) 2004 TyRaNiD <tiraniddo@hotmail.com>
  Copyright (c) 2004,2007 Lukasz Bruun <mail@lukasz.dk>

  PadOpen Hooking function inspired from ps2rd.
  Hook scePadPortOpen/scePad2CreateSocket instead of scePadRead/scePad2Read
  Copyright (C) 2009 jimmikaelkael <jimmikaelkael@wanadoo.fr>
  Copyright (C) 2009 misfire <misfire@xploderfreax.de>
*/

#include <ee_regs.h>
#include <iopcontrol.h>
#include "asm.h"
#include "ee_core.h"
#include "iopmgr.h"
#include "modmgr.h"
#include "modules.h"
#include "util.h"
#include "padhook.h"
#include "padpatterns.h"
#include "syshook.h"
#include "tlb.h"
#ifdef RETROACHIEVEMENTS
#include "ra.h"
#include "../../include/ra_features.h"
#endif
#include "gsm_api.h"
#ifdef IGS
#include "igs_api.h"
#endif
#include "cheat_api.h"
#include "cd_igr_rpc.h"
#include "coreconfig.h"
#ifdef IGR_MENU
#include "igrmenu.h"
#endif
#ifdef INGAMEDIAG
#include "freeze_diag_core.h"
#include "freeze_diag_report.h"
#endif

/* scePadPortOpen & scePad2CreateSocket prototypes */
static int (*scePadPortOpen)(int port, int slot, void *addr);
static int (*scePad2CreateSocket)(pad2socketparam_t *SocketParam, void *addr);

/* Monitored pad data */
static paddata_t Pad_Data;

/* Monitored power button data */
static powerbuttondata_t Power_Button;

#ifdef INGAMEDIAG
// Freeze watchdog: padman's thread sends the pad buffer every frame while the IOP runs. A frame counter that stopped
// this long, after it once ran, takes the report as the combo would: a stuck IOP sends no combo either. About 15 s
// (18 s on PAL); a game that closes its pad port for longer than that gets the report too.
#define FREEZE_DIAG_STALL_VBLANKS 900
static unsigned int Freeze_Stall_Vb;
static u8 Freeze_Stall_Frame;
static int Freeze_Stall_Fired;
#endif

/* How IGR watches the pad: a VBLANK_END interrupt handler, in every build (issue #984).
 *
 * The handler samples the pad and the power button each frame. On a request it stops DMA/GS,
 * suspends every game thread, then wakes the priority-127 worker at priority 0. It runs in
 * interrupt context, so no game thread, however busy or high-priority, can keep it from running.
 * This is OPL's original design, and what RiptOPL shipped until October 5, 2026.
 *
 * Two replacements failed on hardware and must not come back:
 *   - Oct 5 (upstream OPL #1762): poll from the priority-127 thread, woken by an EE alarm. A game
 *     that keeps any thread runnable never lets it run, so IGR was dead in GTA San Andreas, NFS Most
 *     Wanted, PES and others (Beta-3979; upstream #1787, PES 2013).
 *   - Oct 17 (#973, #990, #999): sample in the EE alarm callback. In-game the sampler never
 *     latched anything -- controller and physical power button both dead on Beta-4032/4080, RE4
 *     included -- while the VBLANK build worked on the same console and games.
 *
 * Known cost: #1762 reports Fatal Fury: Battle Archives Volume 2 black-screens with a VBLANK_END
 * handler registered. supportbase.c gives that title Mode 6 (IGR off) by default.
 * RetroAchievements builds also run RA_OnVblank from this handler. */

/* IGR Thread ID and interrupt handler */
static int IGR_Thread_ID = -1;
static int IGR_Intc_ID = -1;
#ifdef RETROACHIEVEMENTS
static int RA_Intc_ID = -1;
#endif

/* IGR thread stack & stack size */
#define IGR_STACK_SIZE (4 * 1024)
static u8 IGR_Stack[IGR_STACK_SIZE] __attribute__((aligned(16)));

/* Extern symbol */
extern void *_gp;
extern void *_end;

#ifdef IGR_MENU
/*
  The in-game menu (igrmenu.c, RIPPS2's, by akilluminati47). The pause is ORBIT's (danielnuld/ps2-launcher,
  third_party/neutrino-igr/igr.c, AFL-3.0), as RIPPS2 build 87 brought it here: the game's threads stop and its
  interrupts are held, and nothing is reset. The SIF stays up (SBUS, DMA channels 5-7), so padman keeps filling the
  pad buffer the menu reads. RESUME gives everything back; any other way out goes on to the IGR below, as before.
*/
#define IGR_I_MASK    ((vu32 *)0x1000f010)
#define IGR_INTC_SBUS 1
static volatile int IGR_MenuOpen = 0;
static int IGR_MenuRearm = 1;
static u32 IGR_PausedThreads[8], IGR_HeldIntc, IGR_HeldDmac;
static const u8 IGR_DmacHeld[] = {0, 1, 2, 3, 4, 8, 9}; // never SIF 5-7

// libpad's buttons, 1 = held (its buffer is active-low), or 0 while the pad is not stable
static u16 IGR_PadButtons(void)
{
    const u8 *b;
    u8 state;

    if (Pad_Data.pad_buf == NULL)
        return 0;
    b = (const u8 *)UNCACHED_SEG(Pad_Data.pad_buf); // the IOP's padman fills it over SIF DMA, behind the cache
    state = b[Pad_Data.pos_state];
    if (!((Pad_Data.libpad == IGR_LIBPAD && state == IGR_PAD_STABLE_V1) || (Pad_Data.libpad == IGR_LIBPAD2 && state == IGR_PAD_STABLE_V2)))
        return 0;
    return ~(b[Pad_Data.pos_combo2] | b[Pad_Data.pos_combo1] << 8) & 0xFFFF;
}

// interrupt handler context: the game's interrupts and DMA completions wait, the SIF's do not
static void IGR_HoldInterrupts(void)
{
    int i;

    IGR_HeldIntc = *IGR_I_MASK;
    for (i = 0; i <= 14; i++)
        if (i != IGR_INTC_SBUS && (IGR_HeldIntc & (1 << i)))
            iDisableIntc(i);
    IGR_HeldDmac = (*R_EE_D_STAT >> 16) & 0x3ff;
    for (i = 0; i < (int)sizeof(IGR_DmacHeld); i++)
        if (IGR_HeldDmac & (1 << IGR_DmacHeld[i]))
            iDisableDmac(IGR_DmacHeld[i]);
}

// From the IGR thread at priority 0, while no game thread runs. Suspending the interrupted thread from
// the handler left it READY but never scheduled again after ResumeThread (ORBIT): so here, not there
static void IGR_PauseThreads(void)
{
    ee_thread_status_t st;
    int i;

    for (i = 1; i < 256; i++) {
        IGR_PausedThreads[i / 32] &= ~(1u << (i % 32));
        // a thread the game suspended itself stays so: only the threads paused here are resumed
        if (i == IGR_Thread_ID || ReferThreadStatus(i, &st) < 0 || (st.status & THS_SUSPEND))
            continue;
        if (SuspendThread(i) >= 0)
            IGR_PausedThreads[i / 32] |= 1u << (i % 32);
    }
}

static void IGR_ResumeGame(void) // the pause, undone in reverse
{
    int i;

    for (i = 0; i < (int)sizeof(IGR_DmacHeld); i++)
        if (IGR_HeldDmac & (1 << IGR_DmacHeld[i]))
            EnableDmac(IGR_DmacHeld[i]);
    for (i = 0; i <= 14; i++)
        if (i != IGR_INTC_SBUS && (IGR_HeldIntc & (1 << i)))
            EnableIntc(i);
    for (i = 1; i < 256; i++)
        if (IGR_PausedThreads[i / 32] & (1u << (i % 32)))
            ResumeThread(i);
}
#endif

// Load home ELF
static void t_loadElf(void)
{
    USE_LOCAL_EECORE_CONFIG;
    int ret;
    char *argv[2];
    t_ExecData elf;

    if (EnableDebug)
        DBGCOL(0x80FF00, LOADELF, "t_loadElf() begins");

    // Init RPC & CMD
    SifInitRpc(0);

    if (EnableDebug)
        DBGCOL(0x000080, LOADELF, "Patch prefix check");

    // Apply Sbv patches
    sbv_patch_disable_prefix_check();

    if (EnableDebug)
        DBGCOL(0xFF8000, LOADELF, "loading SIO2 modules and USBD if found");

    // Load basic modules
    LoadModule("rom0:SIO2MAN", 0, NULL);
    LoadModule("rom0:MCMAN", 0, NULL);

    if (config->ExitPath[1] == 'a') { // ie mass:
        ret = LoadModule("mc0:SYS-CONF/USBD.IRX", 0, NULL);
        if (ret >= 0)
            LoadModule("mc0:SYS-CONF/USBHDFSD.IRX", 0, NULL);
        else {
            LoadModule("mc1:SYS-CONF/USBD.IRX", 0, NULL);
            LoadModule("mc1:SYS-CONF/USBHDFSD.IRX", 0, NULL);
        }
        delay(5); // Wait for device to be detected.
    }

    // Load exit ELF
    argv[0] = config->ExitPath;
    argv[1] = NULL;

    // Wipe everything, even the module storage.
    WipeUserMemory((void *)&_end, (void *)GetMemorySize());

    FlushCache(0);

    ret = LoadElf(argv[0], &elf);

    if (!ret) {

        // Exit services
        LoadFileExit();
        SifExitIopHeap();
        SifExitRpc();

        FlushCache(0);
        FlushCache(2);

        if (EnableDebug)
            DBGCOL(0x0080FF, LOADELF, "ExecPS2() begins");

        // Execute BOOT.ELF
        ExecPS2((void *)elf.epc, (void *)elf.gp, 1, argv);
    }

    if (EnableDebug) {
        DBGCOL(0x0000FF, LOADELF, "LoadElf() error");
        delay(5);
    }

    // Return to PS2 Browser
    Exit(0);
}

// Read the pad buffer and the power button once, and set Pad_Data.combo_type when either asks for
// IGR. Runs once a frame, from the VBLANK_END handler (interrupt context).
static void IGR_CheckInputs(void)
{
    USE_LOCAL_EECORE_CONFIG;
    u8 pad_pos_state, pad_pos_frame, pad_pos_combo1, pad_pos_combo2;
    int intr = DI();

    // The polling worker can be preempted by a game thread resetting the IOP or
    // reopening its pad. Keep the pointer, layout and reads in one short snapshot.
    if (Pad_Data.pad_buf != NULL) {
        // Copy values via the uncached segment, to bypass the cache.
        pad_pos_state = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_state];
        pad_pos_frame = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_frame];
        pad_pos_combo1 = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_combo1];
        pad_pos_combo2 = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_combo2];

#ifdef INGAMEDIAG
        if (padOpen_hooked && Pad_Data.combo_type == 0x00) {
            if (pad_pos_frame != Freeze_Stall_Frame) {
                Freeze_Stall_Frame = pad_pos_frame;
                Freeze_Stall_Vb = 0;
            } else if (++Freeze_Stall_Vb >= FREEZE_DIAG_STALL_VBLANKS) {
                Freeze_Stall_Fired = 1;
                Pad_Data.combo_type = IGR_COMBO_START_SELECT;
            }
        }
#endif

        // First check pad state
        if (((Pad_Data.libpad == IGR_LIBPAD) && (pad_pos_state == IGR_PAD_STABLE_V1)) ||
            ((Pad_Data.libpad == IGR_LIBPAD2) && (pad_pos_state == IGR_PAD_STABLE_V2))) {
            // Check if pad buffer is still alive with pad data frame counter.
            // Once PadOpen is patched in the game ELF, that patch stays in RAM
            // for the life of the ELF; temporary pauses in pad polling during
            // menus, prompts or loading screens must never clear padOpen_hooked
            // and trigger a full 31 MB live-RAM rescan on the next CreateThread.
            if (Pad_Data.vb_count++ >= 10) {
                if (pad_pos_frame != Pad_Data.prev_frame) {
                    padOpen_hooked = 1;
                    Pad_Data.prev_frame = pad_pos_frame;
                }
                Pad_Data.vb_count = 0;
            }

            // Combo R1 + L1 + R2 + L2
            if (pad_pos_combo1 == IGR_COMBO_R1_L1_R2_L2) {
                // Combo Start + Select, R3 + L3 or UP
                if ((pad_pos_combo2 == IGR_COMBO_START_SELECT) || // Start + Select combo, so reset
                    (pad_pos_combo2 == IGR_COMBO_R3_L3)           // R3 + L3 combo, so poweroff
#ifdef IGS
                    || ((pad_pos_combo2 == IGR_COMBO_UP) && (config->EnableGSMOp)) // UP combo, so take IGS
#endif
                )

                    Pad_Data.combo_type = pad_pos_combo2;
            }
        }
    }

#ifdef RETROACHIEVEMENTS
    // ROM CDVDMAN has no OPL shutdown RPC. Ignore the power-off combo before
    // suspending game threads, and leave the physical power button to the ROM.
    if (config->GameMode == DISC_MODE) {
        if (Pad_Data.combo_type == IGR_COMBO_R3_L3)
            Pad_Data.combo_type = 0;
    } else
#endif
    {
        // Keep interrupts disabled while KSU=0 on the user-mode worker stack.
        ee_kmode_enter();

        /* The CDVD power-off interrupt is a latched hardware condition, not
           a new tap every time the low-priority worker samples it. If its
           cancellation is delayed by gameplay or IOP activity, counting it
           on every poll turns a single press into a false double-press reset.
           Re-arm only once the status clears, preserving true double taps. */
        {
            int pending = (*CDVD_R_NDIN & 0x20) && (*CDVD_R_POFF & 0x04);
            if (pending && !Power_Button.latched) {
                if (Power_Button.press < 2)
                    Power_Button.press++;

                // Cancel hardware poweroff while waiting for a second press.
                *CDVD_R_SDIN = 0x00;
                *CDVD_R_SCMD = 0x1B;
            }
            Power_Button.latched = pending;
        }

        // Start the frame counter when power button is pressed
        if (Power_Button.press) {
            // Check number of power button press after 1 ~ sec
            if (Power_Button.vb_count++ >= 50) {
#ifdef INGAMEDIAG
                // One press or two: the report. Its page then waits for one more; holding the button still
                // powers the console off.
                Pad_Data.combo_type = IGR_COMBO_START_SELECT;
#else
                if (Power_Button.press == 1)
                    Pad_Data.combo_type = IGR_COMBO_R3_L3; // power button press 1 time, so poweroff
                else
                    Pad_Data.combo_type = IGR_COMBO_START_SELECT; // power button press 2 time, so reset
#endif
            }
        }

        ee_kmode_exit();
    }

    if (intr)
        EI();
}

// Stop every DMA channel except SIF0-2 and reset the GS. While ExecPS2() would also do some of this
// (it also calls ResetEE), initialization seems to sometimes get stuck at "Initializing GS", perhaps
// when waiting for the V-Sync start interrupt. That happens before ResetEE is called, so ResetEE has
// to be called earlier -- which both callers do right after this.
static void IGR_StopDmaAndGs(void)
{
    // Wait for preceding loads & stores to complete.
    asm volatile("sync.l\n");

    // Stop all ongoing transfers (except for SIF0, SIF1 & SIF2 - DMA CH 5, 6 & 7).
    u32 dmaEnableR = *R_EE_D_ENABLER;
    *R_EE_D_ENABLEW = dmaEnableR | 0x10000;
    *R_EE_D_CTRL;
    *R_EE_D_STAT;
    *R_EE_D0_CHCR = 0;
    *R_EE_D1_CHCR = 0;
    *R_EE_D2_CHCR = 0;
    *R_EE_D3_CHCR = 0;
    *R_EE_D4_CHCR = 0;
    *R_EE_D8_CHCR = 0;
    *R_EE_D9_CHCR = 0;
    *R_EE_D_ENABLEW = dmaEnableR;

    // Wait for preceding loads & stores to complete.
    asm volatile("sync.l\n");

    *R_EE_GS_CSR = 0x100; // Reset GS
    asm volatile("sync.l\n");
    while (*R_EE_GS_CSR & 0x100) {
    };
}

#ifdef RETROACHIEVEMENTS
void IGR_RequestReset(void)
{
    /* The existing IGR loop reads combo_type on its next iteration and
       runs the reset from there; this only leaves the request. A reset
       already under way is not replaced. */
    /* Mode 6 has no IGR worker: client reset must not queue an inert combo. */
    if (IGR_Thread_ID < 0)
        return;
    if (Pad_Data.combo_type == 0x00)
        Pad_Data.combo_type = IGR_COMBO_START_SELECT;
}
#endif

// In Game Reset Thread
static void IGR_Thread(void *arg)
{
    USE_LOCAL_EECORE_CONFIG;
    u32 Cop0_Perf;

    // Wait for the VBLANK_END handler. It latches the request, stops DMA/GS, suspends every other
    // thread and raises this one to priority 0 before waking it. Recheck the latch so a stray
    // wakeup cannot start a shutdown nobody asked for.
#ifdef IGR_MENU
    // With In-Game Menu on the handler wakes this thread for the menu too (IGR_MenuOpen), with the game's
    // interrupts held but nothing stopped; RESUME sends it back to sleep. Any other way out goes on below.
    for (;;) {
        int choice;

        while (Pad_Data.combo_type == 0x00 && !IGR_MenuOpen)
            SleepThread();
        if (!IGR_MenuOpen)
            break; // the power button, or the plain combo: the handler stopped DMA/GS and the game

        IGR_PauseThreads();
        choice = IGR_MenuRun(IGR_PadButtons);
        if (choice == IGR_MENU_RESUME) {
            IGR_ResumeGame();
            IGR_MenuOpen = 0;
            ChangeThreadPriority(IGR_Thread_ID, 127);
            continue;
        }
        // EXIT GAME, POWER OFF, the power button, or a frame the menu could not draw on: what the combo did
        // before. ResetEE leaves the DMAC alone (0x7E, not 0x7F): a SIF transfer in flight would stick (ORBIT)
        IGR_StopDmaAndGs();
        ResetEE(0x7E);
        if (EnableDebug && choice >= IGR_MENU_CANNOT_DRAW) {
            // Debug Colors: why the menu did not open, three blinks before the reset goes on (docs/IGR.md)
            // GS BGCOLOR is 0xBBGGRR: purple, yellow, mint, grey
            u32 why = choice == IGR_MENU_NO_FRAME ? 0xFF0080 : choice == IGR_MENU_GS_BUSY ? 0x00FFFF :
                                                           choice == IGR_MENU_DRAW_FAILED ? 0x80FF00 :
                                                                                            0x808080;
            DBGCOL_BLNK(3, why, 0, IGR, "In-Game Menu could not draw: purple = no frame seen, yellow = GS busy, mint = first page failed, grey = no menu");
        }
        Pad_Data.combo_type = choice == IGR_MENU_POWEROFF ? IGR_COMBO_R3_L3 : IGR_COMBO_START_SELECT;
        break;
    }
#else
    while (Pad_Data.combo_type == 0x00)
        SleepThread();
#endif

    DPRINTF("IGR thread woken up!\n");

#ifdef INGAMEDIAG
    // Freeze report: the handler has suspended the game's threads, so this records their state.
    if (Pad_Data.combo_type == IGR_COMBO_START_SELECT) {
        unsigned int pad_state = 0, pad_frame = 0;

        if (Pad_Data.pad_buf != NULL) {
            pad_state = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_state];
            pad_frame = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_frame];
        }
        FreezeDiag_Begin(Pad_Data.libpad, pad_state, pad_frame,
                         Freeze_Stall_Fired ? FREEZE_DIAG_TRIGGER_STALL :
                         Power_Button.press ? FREEZE_DIAG_TRIGGER_POWER :
                                              FREEZE_DIAG_TRIGGER_COMBO);
    }
#endif

    if (EnableDebug)
        DBGCOL(0xFFFFFF, IGR, "Thread WakeUp");

    // Re-Init RPC & CMD
    SifInitRpc(0);

    // If Pad Combo is Start + Select then Return to Home, else if Pad Combo is UP then take IGS
    if ((Pad_Data.combo_type == IGR_COMBO_START_SELECT)
#ifdef IGS
        || ((Pad_Data.combo_type == IGR_COMBO_UP) && (config->EnableGSMOp))
#endif
    ) {

        if (EnableDebug)
            DBGCOL(0xFF8000, IGR, "oplIGRShutdown()");

#ifdef INGAMEDIAG
        // Freeze report: fetch the IOP's record, then shut down with a deadline. A stuck IOP must
        // not hang IGR before the report is written. Without a report this is oplIGRShutdown(0).
        FreezeDiag_FetchAndShutdown();
#else
#ifdef RETROACHIEVEMENTS
        // The shutdown RPC belongs to OPL CDVDMAN, absent in physical-disc mode.
        if (config->GameMode != DISC_MODE)
#endif
            oplIGRShutdown(0);
#endif

        if (EnableDebug)
            DBGCOL(0x0000FF, IGR, "Reset IOP");

        // Reset IO Processor
        while (!Reset_Iop("", 0)) {
            ;
        }

        // Remove kernel hooks
        Remove_Kernel_Hooks();

        // Initialize Translation Look-Aside Buffer, like the updated ExecPS2() library function does.
        // Some game (GT4, GTA) modify memory map
        // A re-init is needed to properly access memory
        InitializeTLB();

        // Check Performance Counter
        // Some game (GT4) start performance counter
        // When counter overflow, an exception occur, so stop them
        Cop0_Perf = GetCop0(25);

        // Stop Performance Counter
        if (Cop0_Perf & 0x80000000) {
            __asm__ __volatile__(
                " mfc0  $3, $25;"
                " lui   $2, 0x8000;"
                " or    $3, $3, $2;"
                " xor   $3, $3, $2;"
                " mtc0  $3, $25;"
                " sync.p;");
        }

        if (config->EnableGSMOp) {
            if (EnableDebug)
                DBGCOL(0x00FF00, IGR, "Stopping GSM");
            DPRINTF("Stopping GSM...\n");
            DisableGSM();
        }
#if defined(RETROACHIEVEMENTS) && RA_EXPERIMENTAL_CARD_DMA
        else if (config->raOverlayBuf)
            DisableGSTracker();
#endif
#ifdef IGR_MENU
        else if (config->IgrMenu)
            DisableGSTracker();
#endif

        if (config->gCheatList) {
            if (EnableDebug)
                DBGCOL(0xFF0000, IGR, "Stopping CheatEngine");
            DPRINTF("Stopping PS2RD Cheat Engine...\n");
            DisableCheats();
        }

        if (EnableDebug)
            DBGCOL(0x00FFFF, IGR, "Waiting for IOP Reboot");

        while (!SifIopSync()) {
            ;
        }

        if (EnableDebug)
            DBGCOL(0xFF80FF, IGR, "Initializing RPC and services");

        // Init RPC & CMD
        SifInitRpc(0);
        SifInitIopHeap();
        LoadFileInit();
        sbv_patch_enable_lmb();

#ifdef INGAMEDIAG
        // Freeze report: write it with the clean IOP, which FreezeDiag_Write reboots again after.
        FreezeDiag_Write();
#endif

        if (EnableDebug)
            DBGCOL(0x800000, IGR, "Execute RESETSPU.IRX");

        // Reset SPU - do it after the IOP reboot, so nothing will compete with the EE for it.
        LoadOPLModule(OPL_MODULE_ID_RESETSPU, 0, 0, NULL);

        if (config->MMCEIGRSettings != 0) {
            // Trigger switch to bootcard on MMCE's
            char slots[3] = "00";
            if ((config->MMCEIGRSettings & 1))
                slots[0] = '1';

            if ((config->MMCEIGRSettings & 2))
                slots[1] = '1';

            LoadOPLModule(OPL_MODULE_ID_MMCEDRV, 0, 0, NULL);
            LoadOPLModule(OPL_MODULE_ID_MMCEIGR, 0, sizeof(slots), slots);
        }

#ifdef IGS
        if ((Pad_Data.combo_type == IGR_COMBO_UP) && (config->EnableGSMOp))
            InGameScreenshot();
#endif

        if (EnableDebug)
            DBGCOL(0x008000, IGR, "Exiting services");

        // Exit services
        SifExitIopHeap();
        LoadFileExit();
        SifExitRpc();

        IGR_Exit(0);
    } else {
        if (EnableDebug)
            DBGCOL(0x0000FF, IGR, "oplIGRShutdown(1)");

            // If combo is R3 + L3, Poweroff PS2
#ifdef RETROACHIEVEMENTS
        // The shutdown RPC belongs to OPL CDVDMAN, absent in physical-disc mode.
        if (config->GameMode != DISC_MODE)
#endif
            oplIGRShutdown(1);
    }
}

void IGR_Exit(s32 exit_code)
{
    USE_LOCAL_EECORE_CONFIG;
    // Execute home loader
    if (config->ExitPath[0] != '\0')
        ExecPS2(t_loadElf, &_gp, 0, NULL);

    // Return to PS2 Browser
    Exit(exit_code);
}

// IGR VBLANK_END interrupt handler install to monitor combo trick in pad data aera.
static int IGR_Intc_Handler(int cause)
{
#ifdef IGR_MENU
    USE_LOCAL_EECORE_CONFIG;
#endif
    int i;

#ifdef RETROACHIEVEMENTS
    RA_OnVblank(); /* RetroAchievements: per-frame memory snapshot */
#endif

#ifdef INGAMEDIAG
    g_freeze_diag_polls++;
#endif
    IGR_CheckInputs();

#ifdef IGR_MENU
    // With In-Game Menu on, the reset combo pauses the game under the menu (igrmenu.c) instead. The power
    // button pressed twice still leaves at once.
    if (Pad_Data.combo_type == IGR_COMBO_START_SELECT && config->IgrMenu && !Power_Button.press) {
        Pad_Data.combo_type = 0x00;
        if (IGR_MenuRearm && !IGR_MenuOpen) { // once per press: a menu closed at once must not reopen
            IGR_MenuOpen = 1;
            IGR_MenuRearm = 0;
            IGR_HoldInterrupts(); // this handler's VBLANK too: the menu reads the pad itself
            iChangeThreadPriority(IGR_Thread_ID, 0);
            iWakeupThread(IGR_Thread_ID);
        }
    } else if (Pad_Data.combo_type == 0x00)
        IGR_MenuRearm = 1;
#endif

    // If power button or combo is press
    // Disable all interrupts & reset some peripherals.
    // Suspend and Change priority of all threads other then our IGR thread
    // Wakeup and Change priority of our IGR thread
    if (Pad_Data.combo_type != 0x00) {
        IGR_StopDmaAndGs();

        // Disable interrupts & reset some peripherals, back to a standard state.
        // Call ResetEE(0x7F) from an interrupt handler.
        iResetEE(0x7F);

        // Loop for each threads, skipping the idle & IGR threads.
        for (i = 1; i < 256; i++) {
            if (i != IGR_Thread_ID) {
                // Suspend all threads
                iSuspendThread(i);
            }
        }

        DPRINTF("IGR: trying to wake IGR thread...\n");
        iChangeThreadPriority(IGR_Thread_ID, 0);
        // WakeUp IGR thread
        iWakeupThread(IGR_Thread_ID);
    }

    ExitHandler();

    return 0;
}

// An IOP reset invalidates the old libpad DMA buffer, even when the EE worker
// survives. Do not read that memory until the game opens its pad again. Keep
// pending reset requests, physical power-button state, and the already-installed
// EE PadOpen patch status independent of it.
void Invalidate_PadBuffer(void)
{
    int intr = DI();

    Pad_Data.pad_buf = NULL;
    Pad_Data.vb_count = 0;
    Pad_Data.prev_frame = 0;
#ifdef INGAMEDIAG
    Freeze_Stall_Vb = 0; // a new buffer starts its own count
#endif

    if (intr)
        EI();
}

// Install_IGR() must be run first.
static void Set_libpad_Params(void *addr)
{
    int intr = DI();

    // Set positions of pad data and pad state in buffer
    if (Pad_Data.libpad == IGR_LIBPAD) {
        if (Pad_Data.libversion >= 0x0160) {
            Pad_Data.pos_combo1 = 3;
            Pad_Data.pos_combo2 = 2;
            Pad_Data.pos_state = 112;
            Pad_Data.pos_frame = 88;
        } else {
            Pad_Data.pos_combo1 = 11;
            Pad_Data.pos_combo2 = 10;
            Pad_Data.pos_state = 4;
            Pad_Data.pos_frame = 0;
        }
    } else if (Pad_Data.libpad == IGR_LIBPAD2) {
        Pad_Data.pos_combo1 = 29;
        Pad_Data.pos_combo2 = 28;
        Pad_Data.pos_state = 4;
        Pad_Data.pos_frame = 124;
    }

    Pad_Data.vb_count = 0;
    Pad_Data.prev_frame = 0;
    Pad_Data.pad_buf = addr;
#ifdef INGAMEDIAG
    Freeze_Stall_Vb = 0;
#endif

    if (intr)
        EI();
}

// Install IGR thread, and Pad interrupt handler
void Install_IGR(void)
{
    // Pad-open hooks call this again when a game changes or reopens its pad buffer. Once the
    // worker is running, do not erase its live pad pointer, pending combo or power-button
    // counter: doing so can cancel a shutdown request without creating another worker.
    if (IGR_Thread_ID < 0) {
        // The kernel reads the whole ee_thread_t, including attr/option/current_priority.
        // Stack garbage in those fields can make CreateThread fail on real hardware.
        ee_thread_t thread_param = {0};

        Power_Button.press = 0;
        Power_Button.vb_count = 0;
        Power_Button.latched = 0;
        Pad_Data.pad_buf = NULL;
        Pad_Data.vb_count = 0;
        Pad_Data.combo_type = 0x00;
        Pad_Data.prev_frame = 0x00;

        thread_param.gp_reg = &_gp;
        thread_param.func = IGR_Thread;
        thread_param.stack = (void *)IGR_Stack;
        thread_param.stack_size = IGR_STACK_SIZE;
        thread_param.initial_priority = 127;
        IGR_Thread_ID = CreateThread(&thread_param);

        if (IGR_Thread_ID >= 0 && StartThread(IGR_Thread_ID, NULL) < 0) {
            // The thread exists but is not running. Discard it so a later pad-open
            // or reset hook can retry rather than permanently latching a dead worker.
            DeleteThread(IGR_Thread_ID);
            IGR_Thread_ID = -1;
        }
        if (IGR_Thread_ID < 0)
            DPRINTF("IGR: could not start IGR thread; will retry on next hook\n");
    }

    // Never arm the VBLANK interrupt if the worker it would wake did not start.
    if (IGR_Thread_ID >= 0 && IGR_Intc_ID < 0) {
        int handler = AddIntcHandler(kINTC_VBLANK_END, IGR_Intc_Handler, 0);
        if (handler >= 0) {
            IGR_Intc_ID = handler;
            EnableIntc(kINTC_VBLANK_END);
        }
    }
}

void Reset_Padhook(void)
{
    IGR_Intc_ID = -1;
    IGR_Thread_ID = -1;
}

#ifdef RETROACHIEVEMENTS
/* Compatibility Mode 6 disables IGR, including pad and worker hooks.
   Achievement snapshots still require a VBLANK tick. Do not install this
   handler unless the IOP telemetry snapshot allocation actually succeeded. */
static int RA_Intc_Handler(int cause)
{
    (void)cause;
    RA_OnVblank();
    ExitHandler();
    return 0;
}

void Install_RA_Vblank(void)
{
    int handler;

    if (RA_Intc_ID >= 0)
        return;

    handler = AddIntcHandler(kINTC_VBLANK_END, RA_Intc_Handler, 0);
    if (handler < 0)
        return; /* A failed registration must remain retryable. */

    RA_Intc_ID = handler;
    EnableIntc(kINTC_VBLANK_END);
}
#endif

// Hook function for libpad scePadPortOpen
static int Hook_scePadPortOpen(int port, int slot, void *addr)
{
    int ret;

    // Make sure scePadPortOpen function is still available
    if (port == 0 && slot == 0) {
        DPRINTF("IGR: Hook_scePadPortOpen - padOpen hooking check...\n");
        Install_PadOpen_Hook(0x00100000, 0x01ff0000, PADOPEN_CHECK);
    }

    // Call original scePadPortOpen function
    ret = scePadPortOpen(port, slot, addr);

    // Install IGR with libpad1 parameters
    if (port == 0 && slot == 0) {
        DPRINTF("IGR: Hook_scePadPortOpen - installing IGR...\n");
        padOpen_hooked = 1;
        Install_IGR();
        Set_libpad_Params(addr);
    }

    return ret;
}

// Hook function for libpad2 scePad2CreateSocket
static int Hook_scePad2CreateSocket(pad2socketparam_t *SocketParam, void *addr)
{
    int ret;

    // Make sure scePad2CreateSocket function is still available
    if ((SocketParam == NULL) || (SocketParam->port == 0 && SocketParam->slot == 0))
        Install_PadOpen_Hook(0x00100000, 0x01ff0000, PADOPEN_CHECK);

    // Call original scePad2CreateSocket function
    ret = scePad2CreateSocket(SocketParam, addr);

    // Install IGR with libpad2 parameters
    if ((SocketParam == NULL) || (SocketParam->port == 0 && SocketParam->slot == 0)) {
        padOpen_hooked = 1;
        Install_IGR();
        Set_libpad_Params(addr);
    }

    return ret;
}

// This function patch the padOpen calls. (scePadPortOpen or scePad2CreateSocket)
int Install_PadOpen_Hook(u32 mem_start, u32 mem_end, int mode)
{
    u32 *ptr, *ptr2;
    u32 inst, fncall;
    u32 mem_size, mem_size2;
    u32 pattern[1], mask[1];
    int i, found, patched;

    pattern_t padopen_patterns[NB_PADOPEN_PATTERN] = {
        {padPortOpenpattern0, padPortOpenpattern0_mask, sizeof(padPortOpenpattern0), 1, 0x0211},
        {pad2CreateSocketpattern0, pad2CreateSocketpattern0_mask, sizeof(pad2CreateSocketpattern0), 2, 0x0200},
        {pad2CreateSocketpattern1, pad2CreateSocketpattern1_mask, sizeof(pad2CreateSocketpattern1), 2, 0x0200},
        {pad2CreateSocketpattern2, pad2CreateSocketpattern2_mask, sizeof(pad2CreateSocketpattern2), 2, 0x0200},
        {padPortOpenpattern1, padPortOpenpattern1_mask, sizeof(padPortOpenpattern1), 1, 0x0210},
        {padPortOpenpattern2, padPortOpenpattern2_mask, sizeof(padPortOpenpattern2), 1, 0x0160},
        {padPortOpenpattern3, padPortOpenpattern3_mask, sizeof(padPortOpenpattern3), 1, 0x0150}};

    found = 0;
    patched = 0;

    // Loop for each libpad version
    for (i = 0; i < NB_PADOPEN_PATTERN; i++) {
        ptr = (u32 *)mem_start;
        while (ptr) {
            // Purple while PadOpen pattern search
            if (EnableDebug)
                DBGCOL(0x800080, PADHOOK, "Searching PadOpen() pattern");

            mem_size = mem_end - (u32)ptr;

            // First try to locate the orginal libpad's PadOpen function
            ptr = find_pattern_with_mask(ptr, mem_size, padopen_patterns[i].pattern, padopen_patterns[i].mask, padopen_patterns[i].size);
            if (ptr) {
                DPRINTF("IGR: found padopen pattern%d at 0x%08x mode=%d\n", i, (int)ptr, mode);
                found = 1;

                // Green while PadOpen patches
                if (EnableDebug)
                    DBGCOL(0x008000, PADHOOK, "Patching PadOpen()");

                // Save original PadOpen function
                if (padopen_patterns[i].type == IGR_LIBPAD)
                    scePadPortOpen = (void *)ptr;
                else
                    scePad2CreateSocket = (void *)ptr;

                if (mode == PADOPEN_HOOK) {
                    // Generate generic instruction pattern & mask for a J/JAL to PadOpen()
                    // Use 000010 as the operation, to match both J & JAL.
                    inst = 0x08000000 | (0x03ffffff & ((u32)ptr >> 2));

                    // Ignore bit 26 for the mask because the jump type can be either J (000010) or JAL (000011)
                    pattern[0] = inst;
                    mask[0] = 0xfbffffff;

                    DPRINTF("IGR: searching opcode %08x witk mask %08x\n", (int)pattern[0], (int)mask[0]);

                    // Search & patch for calls to PadOpen
                    ptr2 = (u32 *)mem_start;
                    while (ptr2) {
                        mem_size2 = (u32)((u8 *)mem_end - (u8 *)ptr2);

                        ptr2 = find_pattern_with_mask(ptr2, mem_size2, pattern, mask, sizeof(pattern));
                        if (ptr2) {
                            DPRINTF("IGR: found padOpen call at 0x%08x\n", (int)ptr2);

                            patched = 1;

                            fncall = (u32)ptr2;

                            // Get PadOpen call Jump Instruction type (JAL or J).
                            inst = (ptr2[0] & 0xfc000000);

                            // Get Hook_PadOpen call Instruction code
                            if (padopen_patterns[i].type == IGR_LIBPAD) {
                                DPRINTF("IGR: Hook_scePadPortOpen addr 0x%08x\n", (int)Hook_scePadPortOpen);
                                inst |= 0x03ffffff & ((u32)Hook_scePadPortOpen >> 2);
                            } else {
                                DPRINTF("IGR: Hook_scePad2CreateSocket addr 0x%08x\n", (int)Hook_scePad2CreateSocket);
                                inst |= 0x03ffffff & ((u32)Hook_scePad2CreateSocket >> 2);
                            }

                            DPRINTF("IGR: patching padopen call at addr 0x%08x with opcode %08x\n", (int)fncall, (int)inst);
                            // Overwrite the original PadOpen function call with our function call
                            _sw(inst, fncall);

                            Pad_Data.libpad = padopen_patterns[i].type;
                            Pad_Data.libversion = padopen_patterns[i].version;
                        }
                    }

                    // Locate pointers to scePadOpen(), likely used for JALR.
                    if (!patched) {
                        DPRINTF("IGR: 2nd padOpen patch attempt...\n");

                        // Make pattern with function address saved above
                        pattern[0] = (u32)ptr;
                        mask[0] = 0xffffffff;

                        DPRINTF("IGR: searching opcode %08x witk mask %08x\n", (int)pattern[0], (int)mask[0]);

                        // Search & patch for PadOpen function address
                        ptr2 = (u32 *)mem_start;
                        while (ptr2) {
                            mem_size2 = (u32)((u8 *)mem_end - (u8 *)ptr2);

                            ptr2 = find_pattern_with_mask(ptr2, mem_size2, pattern, mask, sizeof(pattern));
                            if (ptr2) {
                                DPRINTF("IGR: found padOpen call at 0x%08x\n", (int)ptr2);

                                patched = 1;

                                fncall = (u32)ptr2;

                                // Get Hook_PadOpen function address
                                if (padopen_patterns[i].type == IGR_LIBPAD) {
                                    DPRINTF("IGR: Hook_scePadPortOpen addr 0x%08x\n", (int)Hook_scePadPortOpen);
                                    inst = (u32)Hook_scePadPortOpen;
                                } else {
                                    DPRINTF("IGR: Hook_scePad2CreateSocket addr 0x%08x\n", (int)Hook_scePad2CreateSocket);
                                    inst = (u32)Hook_scePad2CreateSocket;
                                }

                                DPRINTF("IGR: patching padopen call at addr 0x%08x with opcode %08x\n", (int)fncall, (int)inst);
                                // Overwrite the original PadOpen function address with our function address
                                _sw(inst, fncall);

                                Pad_Data.libpad = padopen_patterns[i].type;
                                Pad_Data.libversion = padopen_patterns[i].version;
                            }
                        }
                    }
                } else {
                    DPRINTF("IGR: no hooking requested, breaking loop...\n");
                    // Hooking is not required and padOpen function was found, so stop searching
                    break;
                }

                // Increment search pointer
                // ptr += padopen_patterns[i].size;
                ptr += (padopen_patterns[i].size >> 2);
            }
        }

        // If a padOpen function call was patched or ( hooking is not required and a padOpen function was found ), so stop the libpad version search loop
        if (patched == 1 || (mode == PADOPEN_CHECK && found == 1)) {
            DPRINTF("IGR: job done exiting...\n");
            break;
        }
    }

    if (patched) {
        iFlushCache(0);
        iFlushCache(2);
    }

    // Done
    if (EnableDebug)
        BGCOLND(0x000000); // Black

    return patched;
}
