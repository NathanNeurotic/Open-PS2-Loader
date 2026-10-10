/*
  Telemetry packets: header parsing and reassembly of a snapshot that
  the console split across several packets.
*/
#ifndef XERABORA_SNAPSHOT_H
#define XERABORA_SNAPSHOT_H

#include <stddef.h>

struct snapshot_stats
{
    unsigned long frames; /* complete snapshots delivered */
    unsigned long gaps;   /* snapshot numbers never seen */
    unsigned long dupes;  /* repeated snapshot numbers */
    unsigned long torn;   /* snapshots that never completed */
    unsigned int parts;   /* parts per snapshot, from the last packet */
    unsigned int bytes;   /* value bytes in the last complete snapshot */
    unsigned int count;   /* watch list entries reported by the console */
    unsigned int rxq;     /* console's receive FIFO depth, last packet */
    unsigned int rxq_max; /* and the highest seen this session */
};

/* Extracts the game serial from a packet header. Returns 1 on success. */
int snapshot_serial(const char *pkt, char *out, size_t out_size);

/* Forget partial state, e.g. when the game changes. */
void snapshot_reset(void);

/* Feeds one telemetry packet. Writes values into the buffer from
   watchlist_values(). Returns 1 when a complete snapshot is ready. */
int snapshot_feed(const char *pkt, size_t len);

/* 1 when the console's list (entry count or size) differs from the
   watch list built here; such packets are dropped. */
int snapshot_stale(void);

const struct snapshot_stats *snapshot_stats(void);

#endif
