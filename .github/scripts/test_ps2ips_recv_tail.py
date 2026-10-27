"""The vendored ps2ips RPC server never drops TCP bytes whose unaligned tail the rests packet cannot carry.

The EE receives the rests packet into a 128-byte buffer, so only RESTS_EBUF_MAX (48) bytes of a receive's
unaligned tail can come back. The server used to take everything lwIP held and lower the returned length,
so a TCP stream silently lost up to 15 bytes. It now peeks, then takes only what fits.

do_recv and do_recvfrom are compiled from modules/network/ps2ips/ps2ips.c against a simulated lwIP 2.2
socket (MSG_PEEK returns at most the first queued buffer, as lwip_recv_tcp does; a plain receive drains
queued buffers up to its length; UDP datagrams, empty ones included, are kept whole until received), simulated SIF DMA into EE memory with the IOP's 32-bit rests layout, and
the EE's recv_intr. Pass another ps2ips.c to check it instead.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "modules/network/ps2ips/ps2ips.c"
source = path.read_text(encoding="utf-8", errors="replace")


def block(start_marker, end_marker="\n}\n"):
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start) + len(end_marker)]


pieces = [block("#define BUFF_SIZE", "\n"), block("#define MIN(a, b)", "\n"), block("#define RDOWN_64(a)", "\n"),
          block("#define RESTS_DMA_MAX", "\n"), block("#define RESTS_EBUF_MAX", "\n"),
          block("static char lwip_buffer[", "\n"), block("static rests_pkt rests;", "\n")]
if "static int rests_fit(" in source:
    pieces.append(block("static int rests_fit("))
pieces += [block("static void do_recv("), block("static void do_recvfrom(")]
# The IOP's rests_pkt is 144 bytes (32-bit pointers); the host's is larger.
pieces = [p.replace("sizeof(rests_pkt)", "RESTS_PKT_IOP_SIZE") for p in pieces]

harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
typedef int s32;
#define MSG_PEEK 0x01
#define MSG_DONTWAIT 0x08
struct sockaddr { u8 sa_len; u8 sa_family; char sa_data[14]; };
typedef struct { s32 ssize; s32 esize; u8 *sbuf; u8 *ebuf; u8 sbuffer[64]; u8 ebuffer[64]; } rests_pkt;
typedef struct { s32 socket; s32 length; s32 flags; void *ee_addr; void *intr_data; } s_recv_pkt;
typedef struct { s32 ret; struct sockaddr sockaddr; } r_recv_pkt;
struct t_SifDmaTransfer { void *src; void *dest; int size; int attr; };
#define RESTS_PKT_IOP_SIZE 144

/* EE memory: EE address a is ee[a]. The receive buffer and the 128-byte intr_data sit in guarded regions. */
#define EE_SIZE 0x4000
#define BUF_BASE 0x1000
#define INTR 0x3000
static u8 ee[EE_SIZE];
static int buf_lo, buf_hi; /* the caller's buffer [buf_lo, buf_hi) */
static int fails;
#define CHECK(c, ...) do { if(!(c)) { fails++; printf("FAIL: " __VA_ARGS__); puts(""); } } while(0)

static rests_pkt rests;
static int sceSifDmaStat(int id) { (void)id; return -1; }
static void CpuSuspendIntr(int *s) { *s = 0; }
static void CpuResumeIntr(int s) { (void)s; }
static int sceSifSetDma(struct t_SifDmaTransfer *t, int n)
{
    int dest = (int)(intptr_t)t->dest;
    (void)n;
    CHECK(dest % 16 == 0 && t->size % 16 == 0, "DMA of %d bytes to %#x is not quadword-aligned", t->size, dest);
    if(t->src == &rests) {
        /* The IOP's layout: four 32-bit words, then sbuffer and ebuffer. */
        u8 image[144];
        s32 words[4] = {rests.ssize, rests.esize, (s32)(intptr_t)rests.sbuf, (s32)(intptr_t)rests.ebuf};
        memcpy(image, words, 16);
        memcpy(image + 16, rests.sbuffer, 64);
        memcpy(image + 80, rests.ebuffer, 64);
        CHECK(dest == INTR && t->size <= 128, "rests DMA of %d bytes overruns the EE's 128-byte intr_data", t->size);
        memcpy(ee + dest, image, t->size);
    } else {
        CHECK(dest % 64 == 0 && dest >= buf_lo && dest + t->size <= buf_hi, "aligned DMA [%#x,+%d) leaves the buffer", dest, t->size);
        memcpy(ee + dest, t->src, t->size);
    }
    return 1;
}
/* The EE's recv_intr in libps2ips. */
static void recv_intr(void)
{
    s32 words[4];
    memcpy(words, ee + INTR, 16);
    for(int i = 0; i < words[0]; i++) ee[words[2] + i] = ee[INTR + 16 + i];
    for(int i = 0; i < words[1]; i++) ee[words[3] + i] = ee[INTR + 80 + i];
}

/* A socket holding queued buffers (TCP segments or UDP datagrams). */
#define QMAX 4096
static u8 q[1 << 16];
static int seg_end[QMAX], nseg, qhead, qtail, udp, calls;
static int dlen[QMAX], dhead, dcount; /* UDP datagram lengths, empty ones included, as lwIP queues them */
static void queue_bytes(const u8 *p, int n) { memcpy(q + qtail, p, n); qtail += n; seg_end[nseg++] = qtail; dlen[dcount++] = n; }
static int first_seg_end(void) { for(int i = 0; i < nseg; i++) if(seg_end[i] > qhead) return seg_end[i]; return qhead; }
static int recv_common(void *mem, int len, unsigned int flags)
{
    calls++;
    int n;
    if(udp) {
        if(dhead == dcount) return (flags & MSG_DONTWAIT) ? -1 : 0;
        n = dlen[dhead] < len ? dlen[dhead] : len;
        memcpy(mem, q + qhead, n);
        /* A peek leaves the datagram (lwIP keeps it in lastdata); a receive drops what it did not take. */
        if(!(flags & MSG_PEEK)) qhead += dlen[dhead++];
        return n;
    }
    if(qhead == qtail) return (flags & MSG_DONTWAIT) ? -1 : 0;
    int end = first_seg_end();
    if(flags & MSG_PEEK) /* lwip_recv_tcp peeks the first buffer only */
        n = end - qhead < len ? end - qhead : len;
    else
        n = qtail - qhead < len ? qtail - qhead : len;
    memcpy(mem, q + qhead, n);
    if(!(flags & MSG_PEEK)) qhead += n;
    return n;
}
static int recv(int s, void *mem, int len, unsigned int flags) { (void)s; return recv_common(mem, len, flags); }
static struct sockaddr sender = {16, 2, {0x12, 0x34, 10, 0, 0, 7}};
static int recvfrom(int s, void *mem, int len, unsigned int flags, struct sockaddr *from, int *fromlen)
{
    (void)s;
    int n = recv_common(mem, len, flags);
    if(n > 0 && from && fromlen) { memcpy(from, &sender, *fromlen < 16 ? *fromlen : 16); *fromlen = 16; }
    return n;
}

@PIECES@

/* One EE receive of len bytes at EE address addr; returns the count and leaves the bytes in ee[addr..]. */
static int ee_recv(int from, int addr, int len, int flags)
{
    union { s_recv_pkt s; r_recv_pkt r; u8 raw[64]; } rpc;
    memset(ee + BUF_BASE - 64, 0xA5, EE_SIZE - BUF_BASE + 64 - 0x1000);
    memset(ee + INTR, 0xEE, 0x200);
    buf_lo = addr; buf_hi = addr + len;
    memset(&rpc, 0, sizeof(rpc));
    rpc.s.socket = 3; rpc.s.length = len; rpc.s.flags = flags;
    rpc.s.ee_addr = (void *)(intptr_t)addr; rpc.s.intr_data = (void *)(intptr_t)INTR;
    if(from) do_recvfrom(&rpc, sizeof(rpc)); else do_recv(&rpc, sizeof(rpc));
    int ret = rpc.r.ret;
    if(ret > 0) recv_intr();
    for(int a = BUF_BASE - 64; a < addr; a++) CHECK(ee[a] == 0xA5, "byte %#x below the buffer was written", a);
    for(int a = addr + (ret > 0 ? ret : 0); a < INTR - 0x100; a++)
        if(ee[a] != 0xA5) { CHECK(0, "byte %#x past the %d bytes returned was written (len %d at %#x)", a, ret, len, addr); break; }
    for(int a = INTR + 128; a < INTR + 0x200; a++)
        if(ee[a] != 0xEE) { CHECK(0, "intr_data overrun at %#x", a); break; }
    if(from && ret > 0) CHECK(memcmp(&rpc.r.sockaddr, &sender, 16) == 0, "recvfrom lost the sender address");
    return ret;
}

static u8 pattern(int i) { return (u8)(i * 131 + (i >> 8) * 7 + 1); }
static void reset(int is_udp) { nseg = qhead = qtail = calls = dhead = dcount = 0; udp = is_udp; }

/* A TCP stream read through every buffer misalignment and several request lengths arrives whole. */
static void tcp_stream(int from, const int *segs, int nsegs, int total)
{
    static u8 sent[1 << 16], got[1 << 16];
    for(int i = 0; i < total; i++) sent[i] = pattern(i);
    reset(0);
    for(int i = 0, off = 0; off < total; i++) {
        int n = segs[i % nsegs];
        if(n > total - off) n = total - off;
        queue_bytes(sent + off, n); off += n;
    }
    static const int lens[] = {1024, 1000, 777, 200, 113, 65, 64, 17};
    int have = 0, step = 0;
    while(have < total && step < 100000) {
        int addr = BUF_BASE + (step * 37) % 64 + 64;
        int len = lens[step % 8];
        step++;
        int r = ee_recv(from, addr, len, 0);
        if(r <= 0) { CHECK(0, "TCP receive returned %d after %d of %d bytes arrived", r, have, total); return; }
        CHECK(r <= len, "returned %d for a %d-byte buffer", r, len);
        memcpy(got + have, ee + addr, r); have += r;
        if(r > 64) CHECK(((addr + r) & 63) <= 48, "returned a %d-byte tail", (addr + r) & 63);
    }
    CHECK(have == total && qhead == qtail, "TCP stream of %d bytes came back as %d", total, have);
    CHECK(memcmp(got, sent, total) == 0, "TCP stream bytes differ (segments of %d...)", segs[0]);
}

int main(void)
{
    static const int big[] = {1460}, mixed[] = {1460, 536, 100, 7, 1, 64, 65, 113, 1023}, tiny[] = {3, 61, 129};
    for(int from = 0; from < 2; from++) {
        tcp_stream(from, big, 1, 20000);
        tcp_stream(from, mixed, 9, 20000);
        tcp_stream(from, tiny, 3, 5000);
    }

    /* The case that lost bytes: 113 bytes queued, a 1024-byte buffer at a 64-aligned address. */
    reset(0);
    u8 data[200];
    for(int i = 0; i < 200; i++) data[i] = pattern(i);
    queue_bytes(data, 113);
    int r = ee_recv(0, BUF_BASE + 64, 1024, 0);
    CHECK(r == 112 && memcmp(ee + BUF_BASE + 64, data, 112) == 0, "first receive of 113 bytes returned %d", r);
    r = ee_recv(0, BUF_BASE + 64, 1024, 0);
    CHECK(r == 1 && ee[BUF_BASE + 64] == data[112], "the 113th byte was lost (second receive returned %d)", r);

    /* A caller's own MSG_PEEK consumes nothing. */
    reset(0);
    queue_bytes(data, 120);
    r = ee_recv(0, BUF_BASE + 64, 1024, MSG_PEEK);
    CHECK(r > 0 && qhead == 0, "a peek consumed %d bytes", qhead);
    r = ee_recv(0, BUF_BASE + 64, 1024, 0);
    CHECK(qhead == r && memcmp(ee + BUF_BASE + 64, data, r) == 0, "receive after a peek returned %d", r);

    /* Errors and end of stream pass through. */
    reset(0);
    CHECK(ee_recv(0, BUF_BASE + 64, 100, MSG_DONTWAIT) == -1, "an empty non-blocking receive did not fail");
    CHECK(ee_recv(1, BUF_BASE + 64, 100, 0) == 0, "end of stream was not 0");

    /* UDP: a datagram whose tail fits arrives whole; a longer tail is cut as if the buffer were shorter,
       and the next datagram is unaffected. */
    reset(1);
    queue_bytes(data, 100);
    queue_bytes(data, 113);
    queue_bytes(data + 113, 50);
    r = ee_recv(1, BUF_BASE + 64 + 12, 1024, 0); /* tail (12 + 100) & 63 = 48 */
    CHECK(r == 100 && memcmp(ee + BUF_BASE + 76, data, 100) == 0, "a datagram whose tail fits returned %d", r);
    r = ee_recv(1, BUF_BASE + 64, 1024, 0); /* tail 49 */
    CHECK(r == 112 && memcmp(ee + BUF_BASE + 64, data, 112) == 0, "a 113-byte datagram with a 49-byte tail returned %d", r);
    r = ee_recv(1, BUF_BASE + 64, 1024, 0);
    CHECK(r == 50 && memcmp(ee + BUF_BASE + 64, data + 113, 50) == 0 && qhead == qtail, "the next datagram returned %d", r);

    /* An empty datagram is returned as 0 and consumed, so the next one still arrives; a 0-byte request
       drops the datagram, as a plain receive does. */
    for(int from = 0; from < 2; from++) {
        reset(1);
        queue_bytes(data, 0);
        queue_bytes(data, 20);
        queue_bytes(data + 20, 30);
        queue_bytes(data + 50, 40);
        r = ee_recv(from, BUF_BASE + 64, 1024, MSG_DONTWAIT);
        CHECK(r == 0, "an empty datagram returned %d", r);
        r = ee_recv(from, BUF_BASE + 64, 1024, MSG_DONTWAIT);
        CHECK(r == 20 && memcmp(ee + BUF_BASE + 64, data, 20) == 0, "the datagram after an empty one returned %d", r);
        r = ee_recv(from, BUF_BASE + 64, 0, MSG_DONTWAIT);
        CHECK(r == 0, "a 0-byte request returned %d", r);
        r = ee_recv(from, BUF_BASE + 64, 1024, MSG_DONTWAIT);
        CHECK(r == 40 && memcmp(ee + BUF_BASE + 64, data + 50, 40) == 0 && dhead == dcount, "after a 0-byte request the next receive returned %d", r);
    }

    if(fails) { printf("%d failure(s)\n", fails); return 1; }
    puts("ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "recv.c"
    exe = Path(tmp) / "recv.exe"
    src.write_text(harness.replace("@PIECES@", "".join(pieces)), encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", "-Wno-pointer-to-int-cast",
                    "-Wno-int-to-pointer-cast", "-Wno-pointer-arith", str(src), "-o", str(exe)], check=True)
    result = subprocess.run([str(exe)])
    if result.returncode:
        sys.exit(f"FAIL: {path}")
print("PASS: ps2ips receives return every TCP byte and never overrun the EE buffers")
