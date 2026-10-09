/*
  Memory-snapshot layout for the RetroAchievements-on-hardware protocol.
  See PROTOCOL.md for the wire format. This header defines the binary
  shape of one snapshot; both the console-side agent and the PC client
  keep a matching copy of this file.

  A snapshot is a fixed header followed by the watched values, packed
  back to back in watch-list order. Addresses are not sent: the client
  generated the watch list and knows the order.

  Tear protection: the sequence number seq is repeated in a trailer word
  placed AFTER the values (RA_SNAP_TRAILER_OFF). A reader that assembles
  the snapshot from a shared buffer reads seq from the header, copies the
  values, then checks the trailer against the header; a mismatch means
  the snapshot was overwritten mid-copy and should be skipped. The
  seq_end field in the header cannot detect this on its own, since it is
  written before the values.
*/

#ifndef __RA_SNAP_H__
#define __RA_SNAP_H__

#define RA_SNAP_MAGIC 0x52415331 /* "RAS1" */

#include "ra_watch.h"

/* Snapshot header, 64 bytes, a multiple of 16 (some transports move
   quadwords). The values follow, packed back to back in watch-list
   order. Addresses are not sent: the client generated the watch list.

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

#define RA_SNAP_HDR ((int)sizeof(struct ra_snap))

/* Offset of the trailer word (a copy of seq) after the values, 4-aligned */
#define RA_SNAP_TRAILER_OFF(bytes) (RA_SNAP_HDR + (((bytes) + 3) & ~3))

/* Transfer size, trailer included, rounded up to 16 (quadword moves) */
#define RA_SNAP_DMA_SIZE(bytes) ((RA_SNAP_TRAILER_OFF(bytes) + 4 + 15) & ~15)

/* Buffer size on both sides: the largest transfer, rounded up to a
   64-byte cache line */
#define RA_SNAP_TOTAL_FOR(bytes) ((RA_SNAP_DMA_SIZE(bytes) + 63) & ~63)
#define RA_SNAP_TOTAL            RA_SNAP_TOTAL_FOR(RA_SNAP_MAX_BYTES)

#endif /* __RA_SNAP_H__ */
