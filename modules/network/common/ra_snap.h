/*
  RA: layout of the game-memory snapshot that ee_core writes into IOP
  memory every frame and the raudp IOP module reads from there.
  Why DMA into a buffer instead of a SIF command: a SIF command number is
  an index into the handler table, and in-game that table belongs to the
  game (OPL's own side allocates exactly one slot, see SifSetCmdBuffer in src/system.c). An
  index past the end writes into someone else's memory, and
  sceSifAddCmdHandler returns void, so the error stays silent. The shared
  tables are left alone: ee_core allocates a buffer in the IOP heap with
  SifAllocIopHeap, passes the address to the module as a load argument,
  and writes to it directly from then on.
  Torn writes: DMA is not atomic and copies from the start of the buffer
  to the end, so seq is repeated in a trailer word placed AFTER the
  values (RA_SNAP_TRAILER_OFF). The reader takes seq from the header,
  copies the values, then compares the trailer and the header again; any
  difference means the snapshot was overwritten mid-copy and is skipped.
  The seq_end field inside the header cannot detect this: it is written
  before the values arrive.
*/
#ifndef __RA_SNAP_H__
#define __RA_SNAP_H__
#define RA_SNAP_MAGIC 0x52415331 /* "RAS1" */
#include "ra_watch.h"
/* Snapshot header, 64 bytes, a multiple of 16 as SIF DMA requires. The
   values follow, packed back to back in watch list order. Addresses are
   not sent: the PC client generated the watch list and knows the order.
   The tear check uses the trailer word after the values, not seq_end. */
struct ra_snap
{
    unsigned int magic;    /* RA_SNAP_MAGIC; tells a snapshot from garbage */
    unsigned int seq;      /* increments every frame; written first */
    unsigned int frames;   /* EE frame counter since launch */
    unsigned int dma_skip; /* frames skipped: previous DMA still in flight */
    unsigned int dma_fail; /* isceSifSetDma failures */
    unsigned int count;    /* entries in the watch list */
    unsigned int bytes;    /* bytes of values that follow */
    unsigned int seq_end;  /* copy of seq (header only; see the trailer) */
    /* Serial of the running game, e.g. "SLUS_210.65". The PC client
       uses it to pick the watch list and the image hash to report to
       RetroAchievements, so the user never names the game by hand. */
    char game_id[16];
    /* What the reads cost on the EE: COP0 Count ticks spent reading the
       values and resolving chains for this snapshot, and ticks between
       the last two VBLANKs, so the PC can turn the first into a share
       of the frame without knowing the clock. */
    unsigned int read_cycles;
    unsigned int frame_cycles;
    unsigned int pad[2];
    /* followed by bytes bytes of values, then the trailer word */
};
#define RA_SNAP_HDR                  ((int)sizeof(struct ra_snap))
/* Offset of the trailer word (a copy of seq) after the values, 4-aligned */
#define RA_SNAP_TRAILER_OFF(bytes)   (RA_SNAP_HDR + (((bytes) + 3) & ~3))
/* Transfer size, trailer included, rounded up to 16: SIF DMA moves quadwords */
#define RA_SNAP_DMA_SIZE(bytes)      ((RA_SNAP_TRAILER_OFF(bytes) + 4 + 15) & ~15)
/* Buffer size on both sides: the largest transfer, rounded up to a
   64-byte cache line so the EE buffer shares no line with other data */
#define RA_SNAP_TOTAL_FOR(bytes)     ((RA_SNAP_DMA_SIZE(bytes) + 63) & ~63)
#define RA_SNAP_TOTAL                RA_SNAP_TOTAL_FOR(RA_SNAP_MAX_BYTES)
/* PC -> game side: raudp DMAs this 128-byte record into an ee_core buffer
   whose address came as a load argument; the VBLANK handler treats a new
   seq as a new event. */
#define RA_EVENT_MAGIC               0x52414531 /* "RAE1" */
#define RA_EVENT_UNLOCK              1          /* an achievement unlocked; arg is its id */
#define RA_EVENT_RESET               2          /* leave the game for the loader, as the IGR combo does */
/* Fixed cache-line isolated event with bounded ASCII title: the low byte is RA_EVENT_* and unlock
   points travel in the upper 24 bits. Old senders that leave them zero are
   still valid. */
#define RA_EVENT_KIND_MASK           0xFFu
#define RA_EVENT_POINTS(k)           ((unsigned int)(k) >> 8)
#define RA_EVENT_MAKE_UNLOCK(points) (RA_EVENT_UNLOCK | ((unsigned int)(points) << 8))
struct ra_event
{
    unsigned int magic; /* RA_EVENT_MAGIC */
    unsigned int seq;   /* increments per event; 0 means none yet */
    unsigned int kind;  /* RA_EVENT_* */
    unsigned int arg;
    char title[64];
    unsigned int reserved[11];
    unsigned int commit; /* last DMA word: must match seq */
};
/* The load argument ee_core hands raudp as argv[1], comma separated:
     RA_ARG_SNAP   eight hex digits, the snapshot buffer in IOP RAM
     RA_ARG_EVENT  eight hex digits, the event buffer in EE RAM
     RA_ARG_RX     ASCII flags 0..3: bit 0 permits network reads while
                   the game runs; bit 1 selects the Caduceus bridge.
                   Legacy 0/1 retain Xerabora discovery.
     RA_ARG_ID     the game's serial, up to RA_ARG_ID_MAX characters
   argv[2] is SMAP's ipconfig string. Both sides build and parse the
   argument by these offsets. */
#define RA_ARG_SNAP   0
#define RA_ARG_EVENT  9
#define RA_ARG_RX     18
#define RA_ARG_ID     20
#define RA_ARG_ID_MAX 15
#define RA_ARG_HOST   (RA_ARG_ID + RA_ARG_ID_MAX + 1)
#define RA_ARG_MAX    (RA_ARG_HOST + 15) /* characters before the terminator */
#endif                                   /* __RA_SNAP_H__ */
