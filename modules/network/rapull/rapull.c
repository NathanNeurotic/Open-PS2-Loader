/*
  rapull: the RetroAchievements snapshot of a PS1 game under POPS, read
  from the IOP.

  POPS keeps PS1 RAM in EE memory at 0x01000000. The IOP cannot read EE
  memory on its own, but the SIF RPC library every EE program links in
  serves one request that does it, "get other data" (sceSifGetOtherData
  here, command 0x8000000C there): the EE side DMAs a range of its
  memory to an IOP address. Sony's own mcserv and fileio read EE memory
  this way. This module asks for the windows the watch list touches,
  once per frame period, and builds struct ra_snap in the buffer raudp
  sends from. No code of ours runs on the EE; rapops starts this module
  with the list it got from OPL.

  Whether POPS answers the request is what the first run on hardware
  tells. So the client can tell the ways it fails apart, one snapshot
  with zero values goes out before the first read: a frame counter
  stuck at 1 means the EE never answered and the thread sleeps in the
  request; a counter that grows with dma_skip means the request
  returns an error; a counter at 0 means this module never ran.
  TODO: the EE writes PS1 RAM through its data cache and this reads
  RAM; the EE library writes the cache back before it sends, in the
  ps2sdk version at least. Whether a value can lag is not measured.
  TODO: the reads are not tied to a frame of the game; entries of one
  snapshot can be a few hundred microseconds apart.

  Licenced under Academic Free License version 3.0, like ee_core.
*/

#include <tamtypes.h>
#include <loadcore.h>
#include <thbase.h>
#include <sifcmd.h>
#include <sysmem.h>
#include "ra_snap.h"
#include "ra_watch.h"

#define MODNAME "rapull"
IRX_ID(MODNAME, 1, 0);

#define PS1_RAM_EE   0x01000000
#define PS1_RAM_SIZE 0x00200000

#define RP_FRAME_US 16667
/* Hardware 06.10: a request sent while POPS starts leaves the screen
   black before its splash. The first one waits this long. */
#define RP_START_US (25 * 1000 * 1000)

/* The SIF moves quadwords, so every read is 16-aligned and a multiple
   of 16 long. Entries closer than RP_WIN_GAP share one read; a read is
   never longer than RP_WIN_MAX_BYTES. The caps bound the memory this
   module takes for a large set. */
#define RP_CHUNK         16
#define RP_WIN_GAP       256
#define RP_WIN_MAX_BYTES 1024
#define RP_WIN_MAX       512
#define RP_STAGE_MAX     (64 * 1024)

#define RP_NONE 0xFFFFFFFF

struct rp_window
{
    u32 addr; /* PS1 address, 16-aligned */
    u32 len;  /* bytes, a multiple of 16 */
    u32 off;  /* where its bytes land in the staging buffer */
};

static volatile struct ra_snap *rp_snap;
static const u32 *rp_list;
static const struct ra_node *rp_nodes;
static u32 rp_count, rp_node_count, rp_bytes;
static char rp_game_id[16];

static struct rp_window *rp_win;
static int rp_win_count;
static u8 *rp_stage;
static u32 rp_stage_len;
static u32 *rp_entry_off; /* per entry: offset in the staging buffer, RP_NONE when out of range */
static u32 *rp_node_val;  /* per node: the value read last frame */
/* one chain target: the aligned 32 bytes around it, so a 4-byte read
   at any offset fits */
static u8 rp_chain[32] __attribute__((aligned(16)));

static u32 rp_seq, rp_frames, rp_fail;

static u32 rp_hex_at(const char *s, int off, int len)
{
    u32 v = 0;
    int i;

    for (i = 0; i < len; i++) {
        char c = s[off + i];
        u32 d;

        if (c >= '0' && c <= '9')
            d = c - '0';
        else if (c >= 'a' && c <= 'f')
            d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F')
            d = c - 'A' + 10;
        else
            break;
        v = (v << 4) | d;
    }
    return v;
}

static int rp_valid(u32 addr, u32 size)
{
    /* TODO: PS1 scratchpad (0x200000-0x2003FF) reads as zero; where
       POPS keeps it is not checked */
    return addr < PS1_RAM_SIZE && size <= PS1_RAM_SIZE - addr;
}

/* One request to the EE. 0 on success; the call blocks until the EE
   has answered, so a POPS that does not serve it parks this thread. */
static int rp_read(u32 addr, void *dest, u32 len)
{
    SifRpcReceiveData_t rd;

    return sceSifGetOtherData(&rd, (void *)(PS1_RAM_EE + addr), dest, (int)len, 0);
}

/* Marks the 16-byte chunks the list touches in a bitmap, then walks
   it into windows. Returns 0 when the set does not fit the caps. */
static int rp_setup(void)
{
    const u32 chunks = PS1_RAM_SIZE / RP_CHUNK;
    u32 *bits;
    u32 i, c, start = RP_NONE, last = 0;
    int ok = 1;

    bits = AllocSysMemory(ALLOC_FIRST, chunks / 8, NULL);
    rp_win = AllocSysMemory(ALLOC_FIRST, RP_WIN_MAX * sizeof(*rp_win), NULL);
    rp_entry_off = AllocSysMemory(ALLOC_FIRST, rp_count * sizeof(u32), NULL);
    rp_node_val = AllocSysMemory(ALLOC_FIRST, (rp_node_count > 0 ? rp_node_count : 1) * sizeof(u32), NULL);
    if (bits == NULL || rp_win == NULL || rp_entry_off == NULL || rp_node_val == NULL) {
        if (bits)
            FreeSysMemory(bits);
        return 0;
    }

    for (i = 0; i < chunks / 32; i++)
        bits[i] = 0;
    for (i = 0; i < rp_count; i++) {
        u32 addr = RA_WATCH_ADDR(rp_list[i]);
        u32 size = RA_WATCH_SIZE(rp_list[i]);

        if (!rp_valid(addr, size) || size == 0)
            continue;
        for (c = addr / RP_CHUNK; c <= (addr + size - 1) / RP_CHUNK; c++)
            bits[c / 32] |= 1u << (c % 32);
    }

    rp_win_count = 0;
    rp_stage_len = 0;
    for (c = 0; c <= chunks; c++) {
        int marked = c < chunks && (bits[c / 32] >> (c % 32)) & 1;

        if (marked && start == RP_NONE) {
            start = c;
            last = c;
            continue;
        }
        if (start == RP_NONE)
            continue;
        if (marked && (c - last) * RP_CHUNK <= RP_WIN_GAP && (c - start + 1) * RP_CHUNK <= RP_WIN_MAX_BYTES) {
            last = c;
            continue;
        }
        if (!marked && (c - last) * RP_CHUNK <= RP_WIN_GAP && c < chunks)
            continue;

        /* close the window at last */
        if (rp_win_count >= RP_WIN_MAX) {
            ok = 0;
            break;
        }
        rp_win[rp_win_count].addr = start * RP_CHUNK;
        rp_win[rp_win_count].len = (last - start + 1) * RP_CHUNK;
        rp_win[rp_win_count].off = rp_stage_len;
        rp_stage_len += rp_win[rp_win_count].len;
        rp_win_count++;
        if (marked) {
            start = c;
            last = c;
        } else {
            start = RP_NONE;
        }
    }
    FreeSysMemory(bits);

    if (!ok || rp_stage_len > RP_STAGE_MAX || rp_stage_len == 0)
        return 0;
    rp_stage = AllocSysMemory(ALLOC_FIRST, rp_stage_len, NULL);
    if (rp_stage == NULL)
        return 0;

    /* windows come out in address order: a binary search per entry */
    for (i = 0; i < rp_count; i++) {
        u32 addr = RA_WATCH_ADDR(rp_list[i]);
        u32 size = RA_WATCH_SIZE(rp_list[i]);
        int lo = 0, hi = rp_win_count - 1;

        rp_entry_off[i] = RP_NONE;
        if (!rp_valid(addr, size) || size == 0)
            continue;
        while (lo <= hi) {
            int mid = (lo + hi) / 2;

            if (addr < rp_win[mid].addr)
                hi = mid - 1;
            else if (addr >= rp_win[mid].addr + rp_win[mid].len)
                lo = mid + 1;
            else {
                rp_entry_off[i] = rp_win[mid].off + (addr - rp_win[mid].addr);
                break;
            }
        }
    }
    for (i = 0; i < rp_node_count; i++)
        rp_node_val[i] = 0;

    return 1;
}

static void rp_put32(volatile u8 *at, u32 v)
{
    at[0] = (u8)v;
    at[1] = (u8)(v >> 8);
    at[2] = (u8)(v >> 16);
    at[3] = (u8)(v >> 24);
}

static u32 rp_get(const u8 *at, u32 size)
{
    u32 v = 0, j;

    for (j = 0; j < size; j++)
        v |= (u32)at[j] << (8 * j);
    return v;
}

/* seq first, the body, the trailer last: raudp compares the two and
   copies again when they differ, as it does for the EE's DMA. */
static void rp_frame_values(int read)
{
    volatile struct ra_snap *s = rp_snap;
    volatile u8 *vals = (volatile u8 *)rp_snap + RA_SNAP_HDR;
    u32 i, j, off = 0;
    int w;

    for (w = 0; read && w < rp_win_count; w++) {
        if (rp_read(rp_win[w].addr, &rp_stage[rp_win[w].off], rp_win[w].len) != 0) {
            rp_fail++;
            return;
        }
    }

    rp_seq++;
    s->seq = rp_seq;
    s->frames = rp_frames;
    s->dma_skip = rp_fail; /* the client shows this one as "skipped by console" */
    s->dma_fail = 0;
    s->count = rp_count;
    s->bytes = rp_bytes + rp_node_count * RA_NODE_PAIR_BYTES;
    for (i = 0; i < sizeof(s->game_id); i++)
        s->game_id[i] = rp_game_id[i];
    s->read_cycles = 0;
    s->frame_cycles = 0;

    for (i = 0; i < rp_count; i++) {
        u32 size = RA_WATCH_SIZE(rp_list[i]);
        const u8 *src = rp_entry_off[i] != RP_NONE ? &rp_stage[rp_entry_off[i]] : NULL;

        if (off + size > rp_bytes)
            break;
        for (j = 0; j < size; j++)
            vals[off++] = src != NULL ? src[j] : 0;
    }

    /* chains as in ee_core/src/ra.c: the base is what was just staged
       or an earlier node; PS1 pointers are KSEG0, the mask takes them
       to RAM addresses */
    off = rp_bytes;
    for (i = 0; i < rp_node_count; i++) {
        u32 nw = rp_nodes[i].w;
        u32 parent = RA_NODE_PARENT(nw);
        u32 size = RA_NODE_SIZE(nw);
        u32 base = 0, addr, v = 0;

        if (RA_NODE_FROM_NODE(nw)) {
            base = parent < i ? rp_node_val[parent] : 0;
        } else if (parent < rp_count && rp_entry_off[parent] != RP_NONE) {
            base = rp_get(&rp_stage[rp_entry_off[parent]], RA_WATCH_SIZE(rp_list[parent]));
        }

        addr = (base + rp_nodes[i].offset) & 0x1FFFFFFF;
        if (!read) {
            addr = 0;
        } else if ((size == 1 || size == 2 || size == 4) && rp_valid(addr, size)) {
            u32 at = addr & ~(RP_CHUNK - 1);
            u32 len = at + sizeof(rp_chain) <= PS1_RAM_SIZE ? sizeof(rp_chain) : RP_CHUNK;

            if (rp_read(at, rp_chain, len) == 0)
                v = rp_get(&rp_chain[addr - at], size);
            else {
                rp_fail++;
                s->magic = 0;
                return;
            }
        } else {
            addr = 0;
        }

        rp_node_val[i] = v;
        rp_put32(&vals[off], addr);
        rp_put32(&vals[off + 4], v);
        off += RA_NODE_PAIR_BYTES;
    }

    s->seq_end = rp_seq;
    *(volatile u32 *)((volatile u8 *)rp_snap + RA_SNAP_TRAILER_OFF(s->bytes)) = rp_seq;
    s->magic = RA_SNAP_MAGIC;
}

static void rp_thread(void *arg)
{
    (void)arg;

    DelayThread(RP_START_US);

    if (!rp_setup()) {
        if (rp_win)
            FreeSysMemory(rp_win);
        if (rp_entry_off)
            FreeSysMemory(rp_entry_off);
        if (rp_node_val)
            FreeSysMemory(rp_node_val);
        if (rp_stage)
            FreeSysMemory(rp_stage);
        ExitDeleteThread();
        return;
    }

    for (;;) {
        rp_frames++;
        rp_frame_values(1);
        DelayThread(RP_FRAME_US);
    }
}

/* Arguments, built by rapops: argv[1] is five hex words separated by
   commas, the snapshot buffer, the list, its count, its node count and
   its bytes of direct values; argv[2] is the game's serial. */
int _start(int argc, char *argv[])
{
    iop_thread_t thread;
    int tid, i;

    if (argc < 2 || argv[1] == NULL)
        return MODULE_NO_RESIDENT_END;

    {
        for (i = 0; i < 44 && argv[1][i] != '\0'; i++) {}
        if (i != 44 || argv[1][44] != '\0')
            return MODULE_NO_RESIDENT_END;
        rp_snap = (volatile struct ra_snap *)rp_hex_at(argv[1], 0, 8);
        rp_list = (const u32 *)rp_hex_at(argv[1], 9, 8);
        rp_count = rp_hex_at(argv[1], 18, 8);
        rp_node_count = rp_hex_at(argv[1], 27, 8);
        rp_bytes = rp_hex_at(argv[1], 36, 8);
        rp_nodes = (const struct ra_node *)&rp_list[rp_count];

        if (rp_snap == NULL || rp_list == NULL || rp_count == 0 || rp_count > RA_WATCH_MAX || rp_node_count > RA_NODE_MAX)
            return MODULE_NO_RESIDENT_END;
        if (rp_bytes == 0 || rp_bytes > RA_SNAP_MAX_BYTES || rp_bytes + rp_node_count * RA_NODE_PAIR_BYTES > RA_SNAP_MAX_BYTES)
            return MODULE_NO_RESIDENT_END;
    }

    for (i = 0; i < (int)sizeof(rp_game_id); i++)
        rp_game_id[i] = '\0';
    if (argc >= 3 && argv[2] != NULL) {
        for (i = 0; i < (int)sizeof(rp_game_id) - 1 && argv[2][i] != '\0'; i++)
            rp_game_id[i] = argv[2][i];
    }

    thread.attr = TH_C;
    thread.option = 0;
    thread.thread = rp_thread;
    thread.stacksize = 0x1000;
    thread.priority = 0x70; /* below raudp: the sender goes first when both are ready */

    tid = CreateThread(&thread);
    if (tid < 0)
        return MODULE_NO_RESIDENT_END;

    StartThread(tid, NULL);

    return MODULE_RESIDENT_END;
}
