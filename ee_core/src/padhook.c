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

/* scePadPortOpen & scePad2CreateSocket prototypes */
static int (*scePadPortOpen)(int port, int slot, void *addr);
static int (*scePad2CreateSocket)(pad2socketparam_t *SocketParam, void *addr);

/* Monitored pad data */
static paddata_t Pad_Data;

/* Monitored power button data */
static powerbuttondata_t Power_Button;

/* How IGR watches the pad.
 *
 * Upstream OPL #1762 (L10N37): merely registering a VBLANK_END handler black-screens some games
 * (Fatal Fury: Battle Archives Volume 2), even with an empty body. So every build now polls the pad
 * from an ordinary EE thread that an alarm wakes about once a frame.
 *
 * Except RetroAchievements builds. RA_OnVblank's snapshot DMA (isceSifSetDma) and its unlock overlay
 * are interrupt-context code that must run every frame, so those builds keep the VBLANK_END handler
 * and accept that conflict. Both paths share the same input check and the same shutdown. */
#ifdef RETROACHIEVEMENTS
#define IGR_VBLANK_HANDLER
#endif

/* IGR Thread ID and interrupt handler */
static int IGR_Thread_ID = -1;
static int IGR_Intc_ID = -1;

/* IGR thread stack & stack size */
#define IGR_STACK_SIZE (4 * 1024)
static u8 IGR_Stack[IGR_STACK_SIZE] __attribute__((aligned(16)));

/* Extern symbol */
extern void *_gp;
extern void *_end;

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
// IGR. Runs about once a frame: from the VBLANK_END handler in RA builds, from the polling thread
// otherwise. Interrupt-safe -- it makes no kernel call besides the kernel-mode switch.
static void IGR_CheckInputs(void)
{
    USE_LOCAL_EECORE_CONFIG;
    u8 pad_pos_state, pad_pos_frame, pad_pos_combo1, pad_pos_combo2;

    if (Pad_Data.pad_buf != NULL) {
        // Copy values via the uncached segment, to bypass the cache.
        pad_pos_state = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_state];
        pad_pos_frame = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_frame];
        pad_pos_combo1 = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_combo1];
        pad_pos_combo2 = ((u8 *)UNCACHED_SEG(Pad_Data.pad_buf))[Pad_Data.pos_combo2];

        // First check pad state
        if (((Pad_Data.libpad == IGR_LIBPAD) && (pad_pos_state == IGR_PAD_STABLE_V1)) ||
            ((Pad_Data.libpad == IGR_LIBPAD2) && (pad_pos_state == IGR_PAD_STABLE_V2))) {
            // Check if pad buffer is still alive with pad data frame counter
            // If pad frame change save it, otherwise tell to syshook to re-install padOpen hook
            if (Pad_Data.vb_count++ >= 10) {
                if (pad_pos_frame != Pad_Data.prev_frame) {
                    padOpen_hooked = 1;
                    Pad_Data.prev_frame = pad_pos_frame;
                } else {
                    padOpen_hooked = 0;
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
        ee_kmode_enter();

        // Check power button press
        if ((*CDVD_R_NDIN & 0x20) && (*CDVD_R_POFF & 0x04)) {
            // Increment button press counter
            Power_Button.press++;

            // Cancel poweroff to catch the second button press
            *CDVD_R_SDIN = 0x00;
            *CDVD_R_SCMD = 0x1B;
        }

        // Start the frame counter when power button is pressed
        if (Power_Button.press) {
            // Check number of power button press after 1 ~ sec
            if (Power_Button.vb_count++ >= 50) {
                if (Power_Button.press == 1)
                    Pad_Data.combo_type = IGR_COMBO_R3_L3; // power button press 1 time, so poweroff
                else
                    Pad_Data.combo_type = IGR_COMBO_START_SELECT; // power button press 2 time, so reset
            }
        }

        ee_kmode_exit();
    }
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

#ifndef IGR_VBLANK_HANDLER
// Wake the polling IGR thread at approximately one-frame intervals. SetAlarm() counts
// horizontal-sync ticks; 256 is close to one frame for both NTSC and PAL.
static void IGR_Poll_Alarm(s32 alarm_id, u16 time, void *common)
{
    (void)alarm_id;
    (void)time;

    iWakeupThread(*(int *)common);
}

// Poll until a combo or the power button asks for IGR, then stop the game the way the VBLANK_END
// handler used to -- but from thread context, so with the ordinary kernel calls.
//
// The thread keeps OPL's original priority 127 between polls, exactly as upstream tested it: the
// alarm wakes it, it reads a few bytes and sleeps again. A game that never yields the EE to a
// priority-127 thread would therefore never let IGR run; watch for that on hardware.
static void IGR_PollUntilRequested(void)
{
    int i, alarm_id;

    for (;;) {
        IGR_CheckInputs();
        if (Pad_Data.combo_type != 0x00)
            break;

        // Sleep until the alarm wakes this thread: no busy loop, and nothing on VBLANK.
        alarm_id = SetAlarm(256, IGR_Poll_Alarm, &IGR_Thread_ID);
        if (alarm_id >= 0)
            SleepThread();
        else
            nopdelay(); // an alarm slot should be free; never sleep forever without one
    }

    DPRINTF("IGR combination detected by polling thread.\n");

    // The priority the interrupt handler used to give this thread before waking it.
    ChangeThreadPriority(TH_SELF, 0);

    IGR_StopDmaAndGs();

    // Thread context: ResetEE, not the interrupt-only iResetEE wrapper.
    ResetEE(0x7F);

    // Suspend every game thread except this one.
    for (i = 1; i < 256; i++) {
        if (i != IGR_Thread_ID)
            SuspendThread(i);
    }
}
#endif

#ifdef RETROACHIEVEMENTS
void IGR_RequestReset(void)
{
    /* The existing IGR loop reads combo_type on its next iteration and
       runs the reset from there; this only leaves the request. A reset
       already under way is not replaced. */
    if (Pad_Data.combo_type == 0x00)
        Pad_Data.combo_type = IGR_COMBO_START_SELECT;
}
#endif

// In Game Reset Thread
static void IGR_Thread(void *arg)
{
    USE_LOCAL_EECORE_CONFIG;
    u32 Cop0_Perf;

#ifdef IGR_VBLANK_HANDLER
    // Place our IGR thread in WAIT state
    // It will be woken up by our IGR interrupt handler
    SleepThread();

    DPRINTF("IGR thread woken up!\n");
#else
    IGR_PollUntilRequested();
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

#ifdef RETROACHIEVEMENTS
        // The shutdown RPC belongs to OPL CDVDMAN, absent in physical-disc mode.
        if (config->GameMode != DISC_MODE)
#endif
            oplIGRShutdown(0);

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

#ifdef IGR_VBLANK_HANDLER
// IGR VBLANK_END interrupt handler install to monitor combo trick in pad data aera.
// RetroAchievements builds only (see IGR_VBLANK_HANDLER): every other build polls from IGR_Thread.
static int IGR_Intc_Handler(int cause)
{
    int i;

#ifdef RETROACHIEVEMENTS
    RA_OnVblank(); /* RetroAchievements: per-frame memory snapshot */
#endif

    IGR_CheckInputs();

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
#endif

// Install_IGR() must be run first.
static void Set_libpad_Params(void *addr)
{
    DI();

    Pad_Data.pad_buf = addr;

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
            DPRINTF("IGR: could not start polling thread; will retry on next hook\n");
    }

#ifdef IGR_VBLANK_HANDLER
    // Never arm the RA VBLANK interrupt if the worker it would wake did not start.
    if (IGR_Thread_ID >= 0 && IGR_Intc_ID < 0) {
        int handler = AddIntcHandler(kINTC_VBLANK_END, IGR_Intc_Handler, 0);
        if (handler >= 0) {
            IGR_Intc_ID = handler;
            EnableIntc(kINTC_VBLANK_END);
        }
    }
#else
    // Standard builds must not register a VBLANK handler (upstream OPL #1762).
    IGR_Intc_ID = -1;
#endif
}

void Reset_Padhook(void)
{
    IGR_Intc_ID = -1;
    IGR_Thread_ID = -1;
}

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

    // Done
    if (EnableDebug)
        BGCOLND(0x000000); // Black

    return patched;
}
