/*
  RA: the watch list (the memory addresses read every frame) and the
  layout of the snapshot built from it.

  Why a list: achievement addresses differ per game, and hard-coding
  them would mean rebuilding the firmware for every title. The PC client
  derives the list from the game's achievement set when the console asks
  about an image; the console keeps it in memory and as a file next to
  the game, the same way OPL keeps cheats in CHT/.

  Why a list of values instead of memory ranges: NFS Underground 2 has
  482 addresses spread over 192 KB in tight clusters. As contiguous
  ranges that is 24 ranges and 3152 bytes, three packets per frame. As
  individual values it is about 1350 bytes, two packets.

  Values in the snapshot follow watch list order, so addresses are not
  sent over the wire: the PC client generated the list and knows it.
*/

#ifndef __RA_WATCH_H__
#define __RA_WATCH_H__

#define RA_WATCH_MAGIC   0x4C574152 /* "RAWL" in little-endian */
#define RA_WATCH_VERSION 1

/* Entry ceiling. NFS Underground 2 needs 482, X-Men 39. This leaves
   headroom over both, and at four bytes per entry the array stays at
   4 KB. */
#define RA_WATCH_MAX 1024

/* A snapshot is split across several UDP packets. One packet carries
   1472 bytes: 1500 MTU minus 20 IP minus 8 UDP, the limit without
   fragmentation.

   HEADER. Ceiling for the text header built in raudp.c (162 bytes with
   the current field table). raudp measures the real header length in
   ra_head_build() and derives the value bytes per packet from it, so
   this constant only sizes buffers; it must not be smaller than the
   real header. */
#define RA_SNAP_HEAD_BYTES 167

/* Bytes of values in one packet. */
#define RA_SNAP_CHUNK_BYTES (1472 - RA_SNAP_HEAD_BYTES)

/* Packets per snapshot.

   The measured send ceiling is 215 packets per second at 1472 bytes
   (see the raudp.c header). Four parts per frame at 60 fps would need
   240 and drop packets; three need 180 and leave headroom. */
#define RA_SNAP_PARTS 3

#define RA_SNAP_MAX_BYTES (RA_SNAP_CHUNK_BYTES * RA_SNAP_PARTS)

/* A watch list entry packs into one word: the address in the low 28
   bits (the PS2 memory map ends at 0x02003FFF, which fits with room to
   spare) and the read size in the high four. */
#define RA_WATCH_ADDR(e)          ((e)&0x0FFFFFFF)
#define RA_WATCH_SIZE(e)          ((e) >> 28)
#define RA_WATCH_PACK(addr, size) (((unsigned int)(size) << 28) | ((addr)&0x0FFFFFFF))

/* Watch list file header. count words follow. */
struct ra_watch_file
{
    unsigned int magic;   /* RA_WATCH_MAGIC */
    unsigned int version; /* RA_WATCH_VERSION */
    unsigned int count;   /* entries that follow */
    unsigned int bytes;   /* snapshot size in bytes: sum of the entry sizes */
};

/* ---- Pointer chains ----------------------------------------------------

   Some achievements read through a pointer: the address is not fixed,
   it is held in memory and changes as the game runs. rcheevos calls
   these AddAddress chains. The console resolves them itself, in the
   same frame: reading the pointer on the PC and asking for the target
   next frame would give a value from a frame that no longer exists.

   The chains travel as an optional tail after the entries. A build that
   does not know about them stops at count entries and never sees it,
   which is why the version stays 1: an old console keeps working on a
   list from a new client, it just cannot follow pointers, exactly as
   before. The same holds the other way: a new console on a list without
   the tail reads nodes as zero.

   struct ra_watch_file
   unsigned int entries[count]      direct addresses
   struct ra_node_file              only if more bytes follow
   struct ra_node nodes[count]

   Nodes come in dependency order: a node's parent is always earlier in
   the list, so one pass resolves every chain however deep.

   A snapshot then carries the direct values, as before, followed by one
   (address, value) pair per node. The pair states the address the
   console ended up reading, so the client looks its answer up rather
   than walking the chain a second time and hoping both sides agree. An
   unresolved chain -- a null or out-of-range pointer -- reports address
   0, and the client answers that read with zeros, which is what
   rcheevos expects from a pointer that leads nowhere.

   Why the total snapshot size is not in ra_watch_file.bytes: that field
   means "direct values" to every build ever shipped. The console adds
   8 bytes per node to it and reports the total in the snapshot header,
   so the client can tell from the first snapshot whether it is talking
   to a console that follows pointers. */

#define RA_NODE_MAGIC 0x4C4E4152 /* "RANL" in little-endian */

/* Node ceiling. ee_core resolves chains from its own copy, and it lives
   in 77 KB of low memory shared with everything else the loader leaves
   behind, so this number is what its arrays cost: 16 bytes per node
   there. The snapshot ceiling binds next, at 8 bytes per node. */
#define RA_NODE_MAX 128

/* Bytes one node adds to a snapshot: the resolved address and the value. */
#define RA_NODE_PAIR_BYTES 8

struct ra_node_file
{
    unsigned int magic; /* RA_NODE_MAGIC */
    unsigned int count; /* nodes that follow */
};

/* One node: parent + offset -> read size bytes.

   parent is an index, into the entry list when from_node is 0 and into
   the node list when it is 1. offset is added to the value read there;
   it is the static part of the address and can be any 32-bit value. */
struct ra_node
{
    unsigned int w;      /* parent index, from_node flag, read size */
    unsigned int offset; /* added to the parent value */
};

#define RA_NODE_PARENT(w)    ((w)&0x0FFF)
#define RA_NODE_FROM_NODE(w) (((w) >> 12) & 1)
#define RA_NODE_SIZE(w)      (((w) >> 13) & 7)
#define RA_NODE_PACK(parent, from_node, size) \
    (((unsigned int)(size) << 13) | ((unsigned int)(from_node) << 12) | ((parent)&0x0FFF))

#endif /* __RA_WATCH_H__ */
