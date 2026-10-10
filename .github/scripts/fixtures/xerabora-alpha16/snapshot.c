#include "snapshot.h"

#include <string.h>

#include "protocol.h"
#include "watchlist.h"

static struct snapshot_stats g_stats;

static unsigned int g_last_sq = 0;
static int g_have_last = 0;

/* Reassembly of the snapshot in progress. */
static unsigned int g_asm_sq = 0;
static unsigned int g_asm_np = 0;
static unsigned int g_asm_seen = 0; /* bit mask of parts received */
static unsigned int g_asm_full = 0; /* bit mask when complete */
static unsigned int g_asm_bytes = 0;
static unsigned int g_asm_chunk = RA_SNAP_CHUNK_BYTES;
static int g_stale = 0;

int snapshot_stale(void)
{
    return g_stale;
}

/* The serial is a fixed-width field padded with '~' (not '_', which
   serials contain). */
int snapshot_serial(const char *pkt, char *out, size_t out_size)
{
    const char *p = strstr(pkt, " id=");
    size_t i;

    if (p == NULL)
        return 0;

    p += 4;
    for (i = 0; i + 1 < out_size && i < 15; i++) {
        if (p[i] == '~' || p[i] == ' ' || p[i] == '\0')
            break;
        out[i] = p[i];
    }
    out[i] = '\0';
    return i > 0;
}

static int field_dec(const char *pkt, const char *label, int width, unsigned int *out)
{
    const char *p = strstr(pkt, label);
    unsigned int v = 0;
    int i;

    if (p == NULL)
        return 0;

    p += strlen(label);
    for (i = 0; i < width; i++) {
        if (p[i] < '0' || p[i] > '9')
            return 0;
        v = v * 10 + (unsigned int)(p[i] - '0');
    }
    *out = v;
    return 1;
}

void snapshot_reset(void)
{
    memset(&g_stats, 0, sizeof(g_stats));
    g_stale = 0;
    g_have_last = 0;
    g_asm_seen = 0;
    g_asm_sq = 0;
    g_asm_np = 0;
}

const struct snapshot_stats *snapshot_stats(void)
{
    return &g_stats;
}

int snapshot_feed(const char *pkt, size_t len)
{
    unsigned int sq, vb, cnt, pt, np;
    const char *idp;
    size_t off, dst;
    unsigned char *values = watchlist_values();

    if (!field_dec(pkt, " sq=", 6, &sq) ||
        !field_dec(pkt, " vb=", 4, &vb) ||
        !field_dec(pkt, " n=", 4, &cnt) ||
        !field_dec(pkt, " pt=", 1, &pt) ||
        !field_dec(pkt, " np=", 1, &np))
        return 0;

    /* vb == 0 means the console has no watch list loaded. */
    if (vb == 0 || cnt == 0 || np == 0 || pt >= np)
        return 0;

    /* The binary tail starts after the last header field. */
    idp = strstr(pkt, " id=");
    if (idp == NULL)
        return 0;
    off = (size_t)(idp - pkt) + 4 + 15 + 1;
    if (off + vb > len || vb > RA_SNAP_MAX_BYTES)
        return 0;

    /* The console's receive FIFO depth rides in every packet; a depth
       that sticks above zero means frames arrive at the controller and
       nobody drains them. Optional: old consoles may not send it. */
    {
        unsigned int rxq;

        if (field_dec(pkt, " rxq=", 3, &rxq)) {
            g_stats.rxq = rxq;
            if (rxq > g_stats.rxq_max)
                g_stats.rxq_max = rxq;
        }
    }

    g_stats.count = cnt;
    g_stats.parts = np;

    /* The console reads the list it stored when the image was checked;
       this client rebuilt its list from the current achievement set. If
       the two differ, values would land on the wrong addresses. */
    if ((int)cnt != watchlist_count()) {
        g_stale = 1;
        return 0;
    }
    g_stale = 0;

    /* The console repeats a snapshot when it sends faster than the EE
       produces them. Feeding the same frame twice would erase deltas. */
    if (g_have_last && sq == g_last_sq) {
        g_stats.dupes++;
        return 0;
    }

    /* Only a complete snapshot is delivered. Mixing a fresh part with a
       stale one would make "A == 1 and B == 2 in the same frame" fire on
       two different moments. */
    if (g_asm_sq != sq || g_asm_np != np) {
        if (g_asm_seen != 0 && g_asm_seen != g_asm_full)
            g_stats.torn++;
        g_asm_sq = sq;
        g_asm_np = np;
        g_asm_seen = 0;
        g_asm_bytes = 0;
        g_asm_full = (np >= 32) ? 0xFFFFFFFFu : ((1u << np) - 1u);
        g_asm_chunk = RA_SNAP_CHUNK_BYTES;
    }

    /* Every part but the last carries a full chunk, which gives the
       real chunk size. A part already placed with a different chunk
       size would sit at the wrong offset, so the snapshot restarts. */
    if (pt + 1 < np && vb != g_asm_chunk) {
        if (g_asm_seen != 0) {
            g_asm_seen = 0;
            g_asm_bytes = 0;
        }
        g_asm_chunk = vb;
    }

    dst = (size_t)pt * g_asm_chunk;
    if (dst + vb > RA_SNAP_MAX_BYTES)
        return 0;

    memcpy(values + dst, pkt + off, vb);
    g_asm_seen |= 1u << pt;
    if (dst + vb > g_asm_bytes)
        g_asm_bytes = (unsigned int)(dst + vb);

    if (g_asm_seen != g_asm_full)
        return 0;

    /* Two sizes are right: direct values only, from a console that does
       not follow pointers, and direct values plus one pair per chain
       from one that does. The size says which, so no handshake is
       needed; the two are equal when the set has no chains. */
    if ((int)g_asm_bytes == watchlist_bytes()) {
        watchlist_set_have_nodes(0);
    } else if ((int)g_asm_bytes == watchlist_snapshot_bytes()) {
        watchlist_set_have_nodes(1);
    } else {
        g_stale = 1;
        g_asm_seen = 0;
        return 0;
    }

    if (g_have_last && sq > g_last_sq + 1)
        g_stats.gaps += sq - g_last_sq - 1;

    g_last_sq = sq;
    g_have_last = 1;
    g_asm_seen = 0;
    g_stats.frames++;
    g_stats.bytes = g_asm_bytes;
    watchlist_set_have_values(1);
    return 1;
}
