/*
  igrmbox.h the in-game menu's mailbox between ee_core and igrmbox.irx

  Copyright 2026, RIPPS2 contributors (akilluminati47)
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  RIPPS2's RIPSHOT mailbox (build 108, modules/iopcore/common/ripshot_io.h), for now without the roll: while the game
  is paused under the in-game menu its IOP side still runs, so the sound went on (a stalled stream looping), and the
  pixels under the panel were lost until the game drew again. ee_core cannot use SIF RPC then (the game owns the SIF
  command table, so a reply would land in the game's handlers), so it talks to the IOP over plain SIF DMA.

  RIPPS2 serves it from CDVDMAN. Here it is a module of its own, igrmbox.irx (modules/iopcore/igrmbox), which the
  launcher packs and ee_core loads only for a launch with In-Game Menu on: with the menu off CDVDMAN, the module
  storage and the IOP's memory are what they always were.

  - At every IOP reset ee_core loads igrmbox.irx with one argument, the EE address of its igrmbox_ack_t in eight hex
    digits. The module starts its thread and, before it returns, DMAs an igrmbox_ack_t whose result is the IOP
    address of its igrmbox_req_t (seq 0).
  - In the menu, ee_core DMAs a request into that igrmbox_req_t (seq 1, 2, ...). The thread sees seq move, does it,
    then DMAs its igrmbox_ack_t back.
  - seq is each struct's LAST word: a SIF DMA writes in address order, so a new seq means the rest has landed.

  IGRMBOX_OP_BEGIN takes an IOP buffer of `size` bytes, which ee_core fills with CopyToIop (the pixels under the
  panel) and reads back a piece at a time with IGRMBOX_OP_SEND.
*/

#ifndef IGRMBOX_H
#define IGRMBOX_H

#define IGRMBOX_BUF_MAX (320 * 252 * 4) // the panel at scale 2 in CT32

enum {
    IGRMBOX_OP_BEGIN = 1, // take an IOP buffer of size bytes (result: its address in iop_buf), poll quickly until END
    IGRMBOX_OP_SEND = 4,  // size bytes of the buffer from offset to ee_data (2 and 3: RIPPS2's roll WRITE / READ)
    IGRMBOX_OP_END,       // give the buffer back
    IGRMBOX_OP_HUSH,      // the menu opened: the SPU2's master volumes to 0 and every voice held (pitch 0), all saved
    IGRMBOX_OP_WAKE,      // RESUME: the voices' pitches back (where the game did not set a new one), then the volumes
};

typedef struct
{
    u32 op, offset, size, ee_data;
    u32 pad[3];
    u32 seq;
} __attribute__((aligned(16))) igrmbox_req_t;

typedef struct
{
    u32 iop_buf; // IGRMBOX_OP_BEGIN's buffer, 0 when none
    u32 pad;
    s32 result; // bytes moved, or < 0
    u32 seq;    // the request answered
} __attribute__((aligned(16))) igrmbox_ack_t;

#endif
