/*
  igrmbox.c the in-game menu's mailbox on the IOP

  Copyright 2026, RIPPS2 contributors (akilluminati47)
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  RIPPS2's ripshot_iop.c (build 108) as a module of its own, without RIPSHOT's roll; see ../common/igrmbox.h. ee_core
  posts requests into mbReq over SIF DMA while the game is paused, this thread does them and DMAs the answers back. It
  looks every 20 ms, and every 0.5 ms while a buffer is held, sleeping in between. ee_core loads it at each IOP reset
  of a launch with In-Game Menu on, and only then: with the menu off it is not even packed.

  The silent menu: RIPPS2's RS_OP_HUSH saves both cores' master volumes and all 48 voices' pitches and sets them to
  0: nothing is heard, and a voice with pitch 0 does not move, so a sound (or a stream played through a voice ring,
  whose refill interrupt then never comes) starts again where it stopped. WAKE puts the pitches back first, leaving
  any voice the game keyed with a new pitch during the pause as the game set it, then the volumes. What it cannot
  hold: AutoDMA input (a PCM stream fed straight to the cores) and envelopes keep going, silently.
*/

#include "irx_imports.h"
#include "igrmbox.h"

#define MODNAME "igrmbox"
IRX_ID(MODNAME, 1, 1);
#include <spu2regs.h>

static igrmbox_req_t mbReq;
static igrmbox_ack_t mbAck;
static u32 mbEeAck, mbBufSize;
static u8 *mbBuf;
static int mbThreadId;
static u16 mbMvol[2][2], mbPitch[2][24];
static int mbHushed;

static void mbHush(void)
{
    int c, v;

    if (mbHushed)
        return;
    for (c = 0; c < 2; c++) {
        mbMvol[c][0] = *SD_P_MVOLL(c);
        mbMvol[c][1] = *SD_P_MVOLR(c);
        *SD_P_MVOLL(c) = 0;
        *SD_P_MVOLR(c) = 0;
    }
    for (c = 0; c < 2; c++)
        for (v = 0; v < 24; v++) {
            mbPitch[c][v] = *SD_VP_PITCH(c, v);
            *SD_VP_PITCH(c, v) = 0;
        }
    mbHushed = 1;
}

static void mbWake(void)
{
    int c, v;

    if (!mbHushed)
        return;
    for (c = 0; c < 2; c++)
        for (v = 0; v < 24; v++)
            if (*SD_VP_PITCH(c, v) == 0) // still ours: a voice the game keyed meanwhile keeps the game's pitch
                *SD_VP_PITCH(c, v) = mbPitch[c][v];
    for (c = 0; c < 2; c++) {
        *SD_P_MVOLL(c) = mbMvol[c][0];
        *SD_P_MVOLR(c) = mbMvol[c][1];
    }
    mbHushed = 0;
}

static void mbSendEE(void *buf, u32 ee_addr, u32 size)
{
    SifDmaTransfer_t dmat;
    int oldstate, id;

    dmat.dest = (void *)ee_addr;
    dmat.size = size;
    dmat.src = buf;
    dmat.attr = 0;
    do {
        CpuSuspendIntr(&oldstate);
        id = sceSifSetDma(&dmat, 1);
        CpuResumeIntr(oldstate);
    } while (!id);
    while (sceSifDmaStat(id) >= 0)
        ;
}

static void mbFree(void)
{
    if (mbBuf != NULL)
        FreeSysMemory(mbBuf);
    mbBuf = NULL;
    mbBufSize = 0;
    mbAck.iop_buf = 0;
}

static s32 mbDo(const igrmbox_req_t *r)
{
    switch (r->op) {
        case IGRMBOX_OP_BEGIN:
            mbFree();
            if (r->size == 0 || r->size > IGRMBOX_BUF_MAX || (r->size & 15))
                return -1;
            // the game's IOP side keeps running: a buffer it cannot spare is simply not there (no exact frame)
            mbBuf = AllocSysMemory(ALLOC_FIRST, r->size, NULL);
            if (mbBuf == NULL)
                return -1;
            mbBufSize = r->size;
            mbAck.iop_buf = (u32)mbBuf;
            return 0;
        case IGRMBOX_OP_SEND:
            if (mbBuf == NULL || r->size == 0 || (r->size & 15) || (r->offset & 15) || r->offset > mbBufSize ||
                r->size > mbBufSize - r->offset)
                return -1;
            mbSendEE(mbBuf + r->offset, r->ee_data, r->size); // before the ack: a new seq means the data is there
            return r->size;
        case IGRMBOX_OP_END:
            mbFree();
            return 0;
        case IGRMBOX_OP_HUSH:
            mbHush();
            return 0;
        case IGRMBOX_OP_WAKE:
            mbWake();
            mbFree(); // the menu is gone: a buffer whose BEGIN ee_core gave up waiting on goes back too
            return 0;
    }
    return -1;
}

static void mbThread(void *arg)
{
    u32 seen = 0;

    (void)arg;
    for (;;) {
        u32 seq = *(volatile u32 *)&mbReq.seq;
        if (seq != seen) {
            igrmbox_req_t r = mbReq;
            seen = seq;
            mbAck.result = mbDo(&r);
            mbAck.seq = seq;
            mbSendEE(&mbAck, mbEeAck, sizeof(mbAck));
        }
        DelayThread(mbBuf != NULL ? 500 : 20000);
    }
}

static u32 mbHex8(const char *s)
{
    u32 v = 0;
    int i;

    for (i = 0; i < 8; i++) {
        char c = s[i];
        if (c >= '0' && c <= '9')
            v = (v << 4) | (u32)(c - '0');
        else if (c >= 'A' && c <= 'F')
            v = (v << 4) | (u32)(c - 'A' + 10);
        else
            return 0;
    }
    return v;
}

// argv[1]: the EE address of ee_core's igrmbox_ack_t, eight hex digits. The answer (our igrmbox_req_t's address) is
// there before this returns, so ee_core reads it as soon as its module load is done.
int _start(int argc, char *argv[])
{
    iop_thread_t t;

    if (argc < 2 || argv[1] == NULL || (mbEeAck = mbHex8(argv[1])) == 0 || (mbEeAck & 15))
        return MODULE_NO_RESIDENT_END;
    t.attr = TH_C;
    t.option = 0;
    t.thread = &mbThread;
    t.stacksize = 0x800;
    t.priority = 0x30;
    if ((mbThreadId = CreateThread(&t)) < 0)
        return MODULE_NO_RESIDENT_END;
    StartThread(mbThreadId, NULL);
    mbAck.result = (s32)&mbReq;
    mbAck.seq = 0;
    mbSendEE(&mbAck, mbEeAck, sizeof(mbAck));
    return MODULE_RESIDENT_END;
}
