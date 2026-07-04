/*
# _____     ___ ____     ___ ____
#  ____|   |    ____|   |        | |____|
# |     ___|   |____ ___|    ____| |    \    PS2DEV Open Source Project.
#-----------------------------------------------------------------------
# (c) 2020 Francisco Javier Trujillo Mata <fjtrujy@gmail.com>
# Licenced under Academic Free License version 2.0
# Review ps2sdk README & LICENSE files for further details.
#
# Modified for RiptOPL: NO IOP reset (same approach as NHDDL's neutrino
# handoff). This child loader runs from BIOS-unused memory (0x84000), loads
# the target ELF through the STILL-LIVE IOP -- OPL's drivers and mounts stay
# up -- and jumps into it. The target (Neutrino) reads its config/modules and
# the game ISO through those mounts, then performs its own IOP reset. The
# ps2sdk loader's SifIopReset + rom0:SIO2MAN/MCMAN/MCSERV reload is exactly
# what broke every launch whose files lived on a BDM device.
*/

#include <kernel.h>
#include <loadfile.h>
#include <ps2sdkapi.h>
#include <sifrpc.h>
#include <errno.h>

//--------------------------------------------------------------
// Redefinition of init/deinit libc:
//--------------------------------------------------------------
// DON'T REMOVE is for reducing binary size.
// These functions are defined as weak in /libc/src/init.c
//--------------------------------------------------------------
void _libcglue_init() {}
void _libcglue_deinit() {}
void _libcglue_args_parse(int argc, char **argv) {}

DISABLE_PATCHED_FUNCTIONS();
DISABLE_EXTRA_TIMERS_FUNCTIONS();
PS2_DISABLE_AUTOSTART_PTHREAD();

//--------------------------------------------------------------
// Clear user memory
// PS2Link (C) 2003 Tord Lindstrom (pukko@home.se)
//         (C) 2003 adresd (adresd_ps2dev@yahoo.com)
//--------------------------------------------------------------
static void wipeUserMem(void)
{
    int i;
    for (i = 0x100000; i < GetMemorySize(); i += 64) {
        __asm__ __volatile__(
            "\tsq $0, 0(%0) \n"
            "\tsq $0, 16(%0) \n"
            "\tsq $0, 32(%0) \n"
            "\tsq $0, 48(%0) \n" ::"r"(i));
    }
}

// argv[0] = path to the target ELF; the full argv is forwarded to it verbatim
// (the ExecPS2 syscall marshals the strings, so wiping user memory is safe).
int main(int argc, char *argv[])
{
    static t_ExecData elfdata;
    int ret;

    elfdata.epc = 0;

    if (argc < 1)
        return -EINVAL;

    SifInitRpc(0);
    wipeUserMem();

    // Writeback data cache before loading ELF.
    FlushCache(0);
    SifLoadFileInit();
    ret = SifLoadElf(argv[0], &elfdata);
    SifLoadFileExit();
    if (ret == 0 && elfdata.epc != 0) {
        FlushCache(0);
        FlushCache(2);
        return ExecPS2((void *)elfdata.epc, (void *)elfdata.gp, argc, argv);
    } else {
        SifExitRpc();
        return -ENOENT;
    }
}
