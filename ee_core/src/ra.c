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

/* The snapshot is assembled in a buffer the loader placed in module
   storage (src/rawatch.c, PlaceWatchBlock) and DMA'd from there. SIF
   DMA requires 64-byte alignment; all writes go through UNCACHED_SEG so
   the data reaches RAM instead of staying in the EE cache. */
static u8 *ra_snap_buf = NULL;
static int ra_snap_dma_id = 0;
static unsigned int ra_snap_seq = 0;
static unsigned int ra_snap_skip = 0;
static unsigned int ra_snap_fail = 0;
static unsigned int ra_frames = 0;

/* The watch list, used where the loader put it. Nothing here may live
   in ee_core's own memory: it sits in 77 KB of low memory that ends at
   0x96E00, and a game loads its own code close behind, so two kilobytes
   of tables of our own are enough to stop a game from starting. Module
   storage, right behind the IOP modules, is what the kernel already
   keeps from the game, and the block there is sized to the set.

   [0 .. count)                entries, one word each
   [count .. +2N)              nodes: packed word, then offset
   [count+2N .. +3N)           what each chain read this frame
   [count+3N .. +4N)           where each chain reads its base, precomputed */
static u32 *ra_watch = NULL;
static int ra_watch_count = 0;
static int ra_watch_bytes = 0;
static int ra_node_at = 0; /* first node word in ra_watch */
static int ra_node_count = 0;

/* Send a snapshot every ra_snap_every frames: 1 while it fits three
   packets, 2 up to six, 3 up to nine. The wire carries at most three
   parts a frame either way (RA_SNAP_PARTS_PER_FRAME). */
static unsigned int ra_snap_every = 1;

/* COP0 Count, for the cost of the reads. The clock is not assumed: the
   PC gets the ticks per frame alongside. */
static u32 ra_last_vblank_ticks = 0;
static u32 ra_frame_ticks = 0;

static inline u32 ra_ticks(void)
{
    u32 t;

    asm volatile("mfc0 %0, $9"
                 : "=r"(t));
    return t;
}

#define RA_NODE_W(i)    ra_watch[ra_node_at + (i)*2]
#define RA_NODE_OFF(i)  ra_watch[ra_node_at + (i)*2 + 1]
#define RA_NODE_VAL(i)  ra_watch[ra_node_at + ra_node_count * 2 + (i)]
#define RA_NODE_BASE(i) ra_watch[ra_node_at + ra_node_count * 3 + (i)]

/* Direct values plus eight bytes per chain: what a snapshot carries. */
static int ra_snap_bytes = 0;

/* What may be read at all: the game's own memory. Below 0x80000 sits
   the EE kernel and above 32 MB there is no RAM on a retail console.

   This is not only about pointers: a set can carry a plain address
   outside that window, and reading one every frame from the interrupt
   handler can keep a game from finishing its loading. An address that
   is not read goes into the snapshot as zero, so the snapshot keeps its
   shape and the client still gets a value for every entry. */
#define RA_RAM_LOW  0x00080000
#define RA_RAM_HIGH 0x02000000

/* Chains: the loader laid them out behind the entries as (w, offset)
   pairs, with the two scratch words per node zeroed after them. The
   node list pointer must therefore be exactly that spot. A list that
   does not match keeps its direct reads and loses the chains, which
   costs achievements, not telemetry. */
static void ra_setup_nodes(const struct EECoreConfig_t *config)
{
    int i;

    if (config->raNodeList == NULL || config->raNodeCount <= 0)
        return;
    if (config->raNodeCount > RA_NODE_MAX)
        return;
    if ((u32 *)config->raNodeList != &ra_watch[ra_watch_count])
        return;
    if (ra_watch_bytes + config->raNodeCount * RA_NODE_PAIR_BYTES > RA_SNAP_MAX_BYTES)
        return;

    ra_node_at = ra_watch_count;
    ra_node_count = config->raNodeCount;
    ra_snap_bytes = ra_watch_bytes + ra_node_count * RA_NODE_PAIR_BYTES;

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

void RA_SetupWatchList(void)
{
    USE_LOCAL_EECORE_CONFIG;
    int parts;

    ra_watch_count = 0;
    ra_watch_bytes = 0;
    ra_snap_bytes = 0;
    ra_node_count = 0;
    ra_node_at = 0;
    ra_snap_every = 1;
    ra_snap_buf = NULL;
    ra_watch = NULL;

    if (config->raWatchList == NULL || config->raWatchCount <= 0)
        return;
    if (config->raWatchCount > RA_WATCH_MAX)
        return;
    if (config->raSnapBytes <= 0 || config->raSnapBytes > RA_SNAP_MAX_BYTES)
        return;
    if (config->raSnapBuf == NULL || ((u32)config->raSnapBuf & 63) != 0)
        return;

    ra_watch = config->raWatchList;
    ra_snap_buf = (u8 *)config->raSnapBuf;
    ra_watch_count = config->raWatchCount;
    ra_watch_bytes = config->raSnapBytes;
    ra_snap_bytes = ra_watch_bytes;

    ra_setup_nodes(config);

    parts = (ra_snap_bytes + RA_SNAP_CHUNK_BYTES - 1) / RA_SNAP_CHUNK_BYTES;
    ra_snap_every = (unsigned int)((parts + RA_SNAP_PARTS_PER_FRAME - 1) / RA_SNAP_PARTS_PER_FRAME);
    if (ra_snap_every == 0)
        ra_snap_every = 1;
}

/* One snapshot per frame.

   If the previous DMA is still in flight the frame is skipped, not
   waited for. The SIF channel is shared with the game (audio, disc,
   pad), and waiting inside an interrupt handler stalls it. */
static void ra_snap_send(void)
{
    USE_LOCAL_EECORE_CONFIG;
    struct ra_snap *s = (struct ra_snap *)UNCACHED_SEG(ra_snap_buf);
    u8 *vals = (u8 *)UNCACHED_SEG(&ra_snap_buf[RA_SNAP_HDR]);
    SifDmaTransfer_t dmat;
    int i, off = 0;
    u32 t0;

    if (ra_snap_iop == 0 || ra_watch_count == 0 || ra_snap_buf == NULL)
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

    t0 = ra_ticks();

    /* Values are read in list order and packed back to back, little
       endian. Reads go through UNCACHED_SEG, which returns RAM: a value
       the game wrote moments ago may still sit dirty in the EE data
       cache, so a reading can lag by the time it takes that line to be
       written back, usually well under a frame in a running game.
       Cached reads would see it at once but would pull up to a thousand
       cache lines per frame through the game's 8 KB data cache. */
    for (i = 0; i < ra_watch_count && RA_PROBE != 6; i++) {
        u32 e = ra_watch[i];
        u32 addr = RA_WATCH_ADDR(e);
        u32 size = RA_WATCH_SIZE(e);
        u32 j;

        /* The entry sizes are meant to add up to ra_watch_bytes; a list
           where they do not must not write past the values. */
        if (off + size > (u32)ra_watch_bytes)
            break;

        if (addr < RA_RAM_LOW || addr + size > RA_RAM_HIGH) {
            for (j = 0; j < size; j++)
                vals[off++] = 0;
        } else if (size == 4 && (addr & 3) == 0) {
            u32 v = *(volatile u32 *)UNCACHED_SEG(addr);

            vals[off++] = (u8)v;
            vals[off++] = (u8)(v >> 8);
            vals[off++] = (u8)(v >> 16);
            vals[off++] = (u8)(v >> 24);
        } else if (size == 2 && (addr & 1) == 0) {
            u16 v = *(volatile u16 *)UNCACHED_SEG(addr);

            vals[off++] = (u8)v;
            vals[off++] = (u8)(v >> 8);
        } else {
            /* One byte, or a wider value at an address its width does
               not divide: a word or halfword load there raises an
               address error, and this runs inside an interrupt handler.
               Achievement sets carry such addresses. */
            for (j = 0; j < size; j++)
                vals[off++] = *(volatile u8 *)UNCACHED_SEG(addr + j);
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

        if (base == 0)
            size = 0;

        addr = (base + RA_NODE_OFF(i)) & 0x1FFFFFFF;

        if (size == 0 || addr < RA_RAM_LOW || addr + size > RA_RAM_HIGH) {
            addr = 0;
        } else {
            u32 j;

            for (j = 0; j < size; j++)
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

    s->read_cycles = ra_ticks() - t0;
    s->frame_cycles = ra_frame_ticks;
    s->seq_end = ra_snap_seq;

    /* Trailer after the values: the DMA copies front to back, so this is
       the last word to land on the IOP. raudp compares it with the
       header's seq to detect a snapshot overwritten mid-copy. */
    *(volatile u32 *)UNCACHED_SEG(&ra_snap_buf[RA_SNAP_TRAILER_OFF(ra_snap_bytes)]) = ra_snap_seq;

    dmat.src = (void *)ra_snap_buf;
    dmat.dest = (void *)ra_snap_iop;
    dmat.size = RA_SNAP_DMA_SIZE(ra_snap_bytes);
    dmat.attr = 0;

    if (RA_PROBE == 5)
        return;

    ra_snap_dma_id = isceSifSetDma(&dmat, 1);
    if (ra_snap_dma_id == 0)
        ra_snap_fail++;
}


void RA_OnVblank(void)
{
    u32 now = ra_ticks();

    ra_frame_ticks = now - ra_last_vblank_ticks;
    ra_last_vblank_ticks = now;
    ra_frames++;

    /* The unlock notice has its own schedule and does not wait for the
       watch list, so it runs before the start delay returns. */
    RA_OverlayOnVblank(ra_frames);

    if (ra_frames <= RA_START_DELAY)
        return;

    if ((RA_PROBE == 0 || RA_PROBE >= 5) && (ra_frames % ra_snap_every) == 0)
        ra_snap_send();
}

#endif /* RETROACHIEVEMENTS */
