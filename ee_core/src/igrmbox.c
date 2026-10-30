/*
  igrmbox.c the in-game menu's mailbox to igrmbox.irx

  Copyright 2026, RIPPS2 contributors (akilluminati47)
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  RIPPS2's ripshot.c mailbox half (build 108), without RIPSHOT's roll: the request goes to the module's igrmbox_req_t
  over SIF DMA and the answer comes back into mbAck, because the game owns SIF RPC while it is paused. RIPPS2 serves
  it from CDVDMAN; here it is igrmbox.irx, loaded only with In-Game Menu on (modules/iopcore/common/igrmbox.h).
*/

#ifdef IGR_MENU
#include "ee_core.h"
#include "modules.h"
#include "modmgr.h"
#include "util.h"
#include "igrmbox.h"
#include "../../modules/iopcore/common/igrmbox.h"
#ifdef IGR_OVERLAY_SIDE
#include "igrovl_side.h" // built into igrovl.elf (RA editions)
#endif

#define MB_SECOND 294912000u // COP0 Count ticks

static union
{
    igrmbox_ack_t a;
    u8 line[64];
} mbAckLine __attribute__((aligned(64))); // a whole cache line of its own: the IOP DMAs into it
#define mbAck (mbAckLine.a)
static u32 mbIopReq, mbIopBuf, mbSeq;

#define MB_ACK ((volatile igrmbox_ack_t *)UNCACHED_SEG(&mbAck))

static inline u32 mbCount(void)
{
    u32 c;
    __asm__ __volatile__("mfc0 %0, $9"
                         : "=r"(c));
    return c;
}

// At an IOP reset, with ee_core's own SIF RPC live: igrmbox.irx starts with the address of mbAck and answers with its
// request's IOP address before its load returns
void IGR_MboxLink(void)
{
    static const char hex[] = "0123456789ABCDEF";
    char arg[9];
    s32 r;
    int i;

    mbIopReq = mbIopBuf = mbSeq = 0; // a new IOP: nothing of the old one holds
    MB_ACK->result = 0;
    MB_ACK->seq = 0;
    for (i = 0; i < 8; i++)
        arg[i] = hex[((u32)&mbAck >> (28 - 4 * i)) & 0xF];
    arg[8] = '\0';
    if (LoadOPLModule(OPL_MODULE_ID_IGRMBOX, 0, sizeof(arg), arg) < 0)
        return;
    r = MB_ACK->result;
    mbIopReq = (r > 0 && !(r & 15)) ? (u32)r : 0;
}

static int mbPost(u32 op, u32 offset, u32 size, void *ee)
{
    igrmbox_req_t r __attribute__((aligned(64)));
    u32 t;

    if (!mbIopReq)
        return -1;
    r.op = op;
    r.offset = offset;
    r.size = size;
    r.ee_data = (u32)ee & 0x0fffffff; // a physical address for the IOP's DMA
    r.pad[0] = r.pad[1] = r.pad[2] = 0;
    r.seq = ++mbSeq;
    FlushCache(0);
    CopyToIop(&r, sizeof(r), (void *)mbIopReq);
    t = mbCount();
    while (MB_ACK->seq != mbSeq)
        if (mbCount() - t > 3 * MB_SECOND)
            return -1; // the module's thread did not answer yet: it still takes the next one (WAKE undoes a late HUSH)
    return MB_ACK->result;
}

u32 IGR_MboxBegin(u32 size)
{
    mbIopBuf = 0;
    if (mbPost(IGRMBOX_OP_BEGIN, 0, size, NULL) == 0)
        mbIopBuf = MB_ACK->iop_buf;
    return mbIopBuf;
}

int IGR_MboxSend(u32 offset, void *data, u32 size)
{
    int r;

    if (!mbIopBuf)
        return -1;
    r = mbPost(IGRMBOX_OP_SEND, offset, size, data); // mbPost flushed: no dirty line of data to land on the DMA
    FlushCache(0);                                   // and none cached from before it
    return r;
}

void IGR_MboxEnd(void)
{
    if (mbIopBuf)
        mbPost(IGRMBOX_OP_END, 0, 0, NULL);
    mbIopBuf = 0;
}

void IGR_MboxHush(void)
{
    mbPost(IGRMBOX_OP_HUSH, 0, 0, NULL);
}

void IGR_MboxWake(void)
{
    mbPost(IGRMBOX_OP_WAKE, 0, 0, NULL);
}
#endif
