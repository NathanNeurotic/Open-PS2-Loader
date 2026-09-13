/*
  RetroAchievements support inside the running game: a snapshot of the
  watched memory addresses is taken every frame and pushed to the IOP
  over SIF DMA, where the raudp module sends it to the PC client.

  ee_core owns no thread once the game is running. Its only periodic code
  is the VBLANK_END interrupt handler in padhook.c (in-game reset), so
  RA_OnVblank() is called from there. Apart from RA_SetupWatchList(),
  which runs during init, everything here runs in interrupt context: no
  blocking, no waiting on DMA.

  Licenced under Academic Free License version 3.0, like the rest of ee_core.
*/

#ifdef RETROACHIEVEMENTS
#include "ee_core.h"
#include "coreconfig.h"
#include "ra.h"
#include "ra_overlay.h"
#include <sifdma.h>
#include "../../modules/network/common/ra_snap.h"
#include "../../modules/network/common/ra_watch.h"

/* Interrupt-safe SIF DMA entry points. libkernel.a exports them, but
   sifdma.h does not declare them. */
extern int isceSifSetDma(SifDmaTransfer_t *dmat, int count);
extern int isceSifDmaStat(int trid);

/* Filled in by iopmgr.c while loading the IOP modules. */
extern unsigned int ra_snap_iop; /* snapshot buffer in IOP RAM, 0 if none */

/* Frames to wait after the game starts before touching its memory: the
   game must load its own ELF first. About 10 seconds at 60 frames/s. */
#define RA_START_DELAY 600

/* The snapshot is assembled here and DMA'd from here. SIF DMA requires
   64-byte alignment; all writes go through UNCACHED_SEG so the data
   reaches RAM instead of staying in the EE cache. */
static u8 ra_snap_buf[RA_SNAP_TOTAL] __attribute__((aligned(64)));
static int ra_snap_dma_id = 0;
static unsigned int ra_snap_seq = 0;
static unsigned int ra_snap_skip = 0;
static unsigned int ra_snap_fail = 0;
static unsigned int ra_frames = 0;

/* Own copy of the watch list. config->raWatchList points into loader
   memory, which the game overwrites, so the list is copied during init
   the same way SetupCheats() copies the cheat list.

   Pointer chains live in the same array, behind the entries, and so do
   the two words each chain needs while a frame is built. Nothing here
   may grow: ee_core sits in 77 KB of low memory that ends at 0x96E00,
   and a game loads its own code close behind. Two kilobytes of tables
   of our own pushed X-Men Origins over that edge -- it stopped starting
   at all, while NFS Underground 2 in the same build was fine
   (12.09.2026, lab/pointers). The array holds 1024 words and a real set
   uses a few hundred, so the chains go in the space already paid for.

   [0 .. count)                entries, one word each
   [count .. +2N)              nodes: packed word, then offset
   [count+2N .. +3N)           what each chain read this frame
   [count+3N .. +4N)           where each chain reads its base, precomputed */
static u32 ra_watch[RA_WATCH_MAX];
static int ra_watch_count = 0;
static int ra_watch_bytes = 0;
static int ra_node_at = 0; /* first node word in ra_watch */
static int ra_node_count = 0;

#define RA_NODE_W(i)    ra_watch[ra_node_at + (i)*2]
#define RA_NODE_OFF(i)  ra_watch[ra_node_at + (i)*2 + 1]
#define RA_NODE_VAL(i)  ra_watch[ra_node_at + ra_node_count * 2 + (i)]
#define RA_NODE_BASE(i) ra_watch[ra_node_at + ra_node_count * 3 + (i)]

/* Direct values plus eight bytes per chain: what a snapshot carries. */
static int ra_snap_bytes = 0;

/* Readable window for a watch address. UNCACHED_SEG puts it in the 0x20000000 mirror, which the
   kernel's default TLB maps only from 0x20080000 up to the end of the 32 MB of RAM (ps2sdk
   ee/kernel/src/tlbfunc.c). An address outside that -- a watch list can carry 0x00000000 -- takes a
   TLB miss inside the vsync interrupt and hangs the game. Such entries are sent as zero, so the
   snapshot keeps its shape and the client still gets a value for every entry. */
#define RA_RAM_LOW  0x00080000
#define RA_RAM_HIGH 0x02000000

void RA_SetupWatchList(void)
{
    USE_LOCAL_EECORE_CONFIG;
    int i;

    ra_watch_count = 0;
    ra_watch_bytes = 0;
    ra_snap_bytes = 0;
    ra_node_count = 0;
    ra_node_at = 0;

    if (config->raWatchList == NULL || config->raWatchCount <= 0)
        return;
    if (config->raWatchCount > RA_WATCH_MAX)
        return;
    if (config->raSnapBytes <= 0 || config->raSnapBytes > RA_SNAP_MAX_BYTES)
        return;

    for (i = 0; i < config->raWatchCount; i++)
        ra_watch[i] = config->raWatchList[i];

    ra_watch_count = config->raWatchCount;
    ra_watch_bytes = config->raSnapBytes;
    ra_snap_bytes = ra_watch_bytes;

    /* Chains, if they fit behind the entries: four words each. A list
       that leaves no room keeps its direct reads and loses the chains,
       which costs achievements, not telemetry. */
    if (config->raNodeList == NULL || config->raNodeCount <= 0)
        return;
    if (config->raNodeCount > RA_NODE_MAX)
        return;
    if (ra_watch_count + config->raNodeCount * 4 > RA_WATCH_MAX)
        return;
    if (ra_watch_bytes + config->raNodeCount * RA_NODE_PAIR_BYTES > RA_SNAP_MAX_BYTES)
        return;

    ra_node_at = ra_watch_count;
    ra_node_count = config->raNodeCount;
    ra_snap_bytes = ra_watch_bytes + ra_node_count * RA_NODE_PAIR_BYTES;

    for (i = 0; i < ra_node_count; i++) {
        const struct ra_node *n = &((const struct ra_node *)config->raNodeList)[i];

        RA_NODE_W(i) = n->w;
        RA_NODE_OFF(i) = n->offset;
    }

    /* Where each chain reads its base: the offset of the parent's value
       in the staged snapshot, and its width. Walking the entries once
       per chain is a few thousand steps at launch and nothing per frame. */
    for (i = 0; i < ra_node_count; i++) {
        u32 parent = RA_NODE_PARENT(RA_NODE_W(i));
        int off = 0, k;

        RA_NODE_BASE(i) = 0;
        RA_NODE_VAL(i) = 0;
        if (RA_NODE_FROM_NODE(RA_NODE_W(i)) || parent >= (u32)ra_watch_count)
            continue;

        for (k = 0; k < (int)parent; k++)
            off += (int)RA_WATCH_SIZE(ra_watch[k]);

        RA_NODE_BASE(i) = ((u32)off << 4) | RA_WATCH_SIZE(ra_watch[parent]);
    }
}

/* One snapshot per frame.

   If the previous DMA is still in flight the frame is skipped, not
   waited for. The SIF channel is shared with the game (audio, disc,
   pad), and waiting inside an interrupt handler stalls it. */
static void ra_snap_send(void)
{
    USE_LOCAL_EECORE_CONFIG;
    struct ra_snap *s = (struct ra_snap *)UNCACHED_SEG(&ra_snap_buf);
    u8 *vals = (u8 *)UNCACHED_SEG(&ra_snap_buf[RA_SNAP_HDR]);
    SifDmaTransfer_t dmat;
    int i, off = 0;

    if (ra_snap_iop == 0 || ra_watch_count == 0)
        return;

    if (ra_snap_dma_id != 0 && isceSifDmaStat(ra_snap_dma_id) >= 0) {
        ra_snap_skip++;
        return;
    }

    ra_snap_seq++;

    s->magic = RA_SNAP_MAGIC;
    s->seq = ra_snap_seq;
    s->frames = ra_frames;
    s->dma_skip = ra_snap_skip;
    s->dma_fail = ra_snap_fail;
    s->count = (unsigned int)ra_watch_count;
    /* The client matches count against its own list and reads bytes to
       tell whether this console resolves chains. */
    s->bytes = (unsigned int)ra_snap_bytes;

    for (i = 0; i < (int)sizeof(s->game_id); i++)
        s->game_id[i] = config->GameID[i];

    /* Values are read in list order and packed back to back, little
       endian. Reads go through UNCACHED_SEG, which returns RAM: a value
       the game wrote moments ago may still sit dirty in the EE data
       cache, so a reading can lag by the time it takes that line to be
       written back, usually well under a frame in a running game.
       Cached reads would see it at once but would pull up to a thousand
       cache lines per frame through the game's 8 KB data cache. */
    /* RA_PROBE 6: the transfer without the reads, to tell the cost of
       the reads from the cost of the DMA. */
    for (i = 0; i < ra_watch_count && off < ra_watch_bytes && RA_PROBE != 6; i++) {
        u32 e = ra_watch[i];
        u32 addr = RA_WATCH_ADDR(e);
        u32 size = RA_WATCH_SIZE(e);

        if (addr < RA_RAM_LOW || addr >= RA_RAM_HIGH || size > RA_RAM_HIGH - addr) {
            u32 n = (size == 4 || size == 2) ? size : 1; // exactly what the read below would pack

            while (n-- > 0)
                vals[off++] = 0;
        } else if (size == 4) {
            u32 v = *(volatile u32 *)UNCACHED_SEG(addr);

            vals[off++] = (u8)v;
            vals[off++] = (u8)(v >> 8);
            vals[off++] = (u8)(v >> 16);
            vals[off++] = (u8)(v >> 24);
        } else if (size == 2) {
            u16 v = *(volatile u16 *)UNCACHED_SEG(addr);

            vals[off++] = (u8)v;
            vals[off++] = (u8)(v >> 8);
        } else {
            vals[off++] = *(volatile u8 *)UNCACHED_SEG(addr);
        }
    }

    /* Pointer chains. Each one takes its base from what was just staged
       -- the same value the client will see -- adds the static offset
       and reads there, byte at a time so an odd address cannot raise an
       address error inside an interrupt handler.

       The pair carries the address as well as the value, so the client
       answers rcheevos by lookup instead of walking the chain a second
       time: a pointer that moved between the two sides costs one read,
       not a wrong value. Address 0 means the chain led outside memory.

       The list was checked when it was loaded, but it arrives over the
       network and this runs inside the game, so every index and size is
       checked again here. */
    off = ra_watch_bytes;
    for (i = 0; i < ra_node_count && off + RA_NODE_PAIR_BYTES <= ra_snap_bytes && RA_PROBE != 6; i++) {
        u32 w = RA_NODE_W(i);
        u32 parent = RA_NODE_PARENT(w);
        u32 size = RA_NODE_SIZE(w);
        u32 base, addr, v = 0;
        int j;

        if (size != 1 && size != 2 && size != 4) {
            size = 0;
            base = 0;
        } else if (RA_NODE_FROM_NODE(w)) {
            base = parent < (u32)i ? RA_NODE_VAL(parent) : 0;
        } else if (RA_NODE_BASE(i) == 0) {
            base = 0; /* the parent was out of range at setup */
        } else {
            u32 psize = RA_NODE_BASE(i) & 0xF;
            const u8 *at = &vals[RA_NODE_BASE(i) >> 4];

            base = at[0];
            if (psize >= 2)
                base |= (u32)at[1] << 8;
            if (psize == 4)
                base |= ((u32)at[2] << 16) | ((u32)at[3] << 24);
        }

        addr = (base + RA_NODE_OFF(i)) & 0x1FFFFFFF;

        if (size == 0 || addr < RA_RAM_LOW || addr + size > RA_RAM_HIGH) {
            addr = 0;
        } else {
            for (j = 0; j < (int)size; j++)
                v |= (u32)(*(volatile u8 *)UNCACHED_SEG(addr + j)) << (8 * j);
        }

        RA_NODE_VAL(i) = v;

        vals[off++] = (u8)addr;
        vals[off++] = (u8)(addr >> 8);
        vals[off++] = (u8)(addr >> 16);
        vals[off++] = (u8)(addr >> 24);
        vals[off++] = (u8)v;
        vals[off++] = (u8)(v >> 8);
        vals[off++] = (u8)(v >> 16);
        vals[off++] = (u8)(v >> 24);
    }

    s->seq_end = ra_snap_seq;

    /* Trailer after the values: the DMA copies front to back, so this is
       the last word to land on the IOP. raudp compares it with the
       header's seq to detect a snapshot overwritten mid-copy. */
    *(volatile u32 *)UNCACHED_SEG(&ra_snap_buf[RA_SNAP_TRAILER_OFF(ra_snap_bytes)]) = ra_snap_seq;

    dmat.src = (void *)&ra_snap_buf;
    dmat.dest = (void *)ra_snap_iop;
    dmat.size = RA_SNAP_DMA_SIZE(ra_snap_bytes);
    dmat.attr = 0;

    /* RA_PROBE 5: the reads without the transfer. */
    if (RA_PROBE == 5)
        return;

    ra_snap_dma_id = isceSifSetDma(&dmat, 1);
    if (ra_snap_dma_id == 0)
        ra_snap_fail++;
}


void RA_OnVblank(void)
{
    ra_frames++;

    /* The unlock notice has its own schedule and does not wait for the
       watch list, so it runs before the start delay returns. */
    RA_OverlayOnVblank(ra_frames);

    if (ra_frames <= RA_START_DELAY)
        return;

    /* The probe ladder stops here: levels 1-3 have no raudp to send to
       anyway, level 4 has one and must stay quiet. */
    if (RA_PROBE == 0 || RA_PROBE >= 5)
        ra_snap_send();
}

#endif /* RETROACHIEVEMENTS */
