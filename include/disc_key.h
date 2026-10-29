/*
# _____     ___ ____     ___ ____
#  ____|   |    ____|   |        | |____|
# |     ___|   |____ ___|    ____| |    \    PS2DEV Open Source Project.
#-----------------------------------------------------------------------
## (C) 2002 Nicholas Van Veen (nickvv@xtra.co.nz)
#     2003 loser (loser@internalreality.com)
# (c) 2004 Marcus R. Brown <mrbrown@0xd6.org> Licenced under Academic Free License version 2.0
# Review ps2sdk README & LICENSE files for further details.
*/

#ifndef RIPTOPL_DISC_KEY_H
#define RIPTOPL_DISC_KEY_H

#include <kernel.h>
#include <sifrpc.h>
#include <string.h>
#include <tamtypes.h>

/* libcdvd's N-command gate and RPC client, shared with ordinary disc commands. */
#ifdef __cplusplus
extern "C" {
#endif
extern int _CdCheckNCmd(int cmd);
extern int nCmdSemaId;
extern SifRpcClientData_t clientNCmd;
#ifdef __cplusplus
}
#endif

/* Synchronous READ_KEY (NCMD 0x0b), following ps2sdk 2a18d15da1332665451a9bcf9a0d4df9029c9490
 * ee/rpc/cdvd/src/ncmd.c
 * (AFL-2.0; Nicholas Van Veen, loser, Marcus R. Brown).
 * YAOPL/belomaxorka 7f1018e7 identified the missing successful-call release.
 * Own the RPC under the SDK gate instead of repairing sceCdReadKey afterwards:
 * an already-fixed SDK could let another command acquire the lock before that
 * repair. Every successful acquisition here has exactly one release, including
 * RPC failure; a rejected acquisition never releases another command's lock.
 * Internal SDK symbols/READ_KEY wire ABI must be rechecked on SDK upgrades. */
static inline int sysReadDiscKey(unsigned char arg1, unsigned char arg2,
                                 unsigned int command, unsigned char *key)
{
    static u32 request[16] __attribute__((aligned(64)));
    static u8 response[64] __attribute__((aligned(64)));
    int result;

    if (key == NULL || _CdCheckNCmd(0x0b) == 0)
        return 0;

    request[0] = arg1;
    request[1] = arg2;
    request[2] = command;
    result = sceSifCallRpc(&clientNCmd, 0x0b, 0, request, 12,
                           response, 24, NULL, NULL);
    if (result >= 0)
        memcpy(key, UNCACHED_SEG(response + 4), 16);
    SignalSema(nCmdSemaId);
    return result >= 0;
}

#endif
