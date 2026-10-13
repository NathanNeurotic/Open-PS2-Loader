/*
 * Host test for udpfs_ministack's mstack: UDP exchange device (ministack_xchg.c).
 *
 * The real exchange code runs against stubbed UDP and SMAP calls. A scripted "network" delivers
 * replies through the bound port handler while the exchange polls with DelayThread, exactly as
 * the SMAP receive context would.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "../../udpfs_ministack/src/ministack_xchg.c"

/* --- stubs ------------------------------------------------------------------------------- */

static int binds, bound_port;
static udp_port_handler bound_handler;
static udp_socket_t bound_socket;

udp_socket_t *udp_bind(uint16_t port_src, udp_port_handler handler, void *handler_arg)
{
    binds++;
    bound_port = port_src;
    bound_handler = handler;
    bound_socket.port_src = port_src;
    bound_socket.handler = handler;
    bound_socket.handler_arg = handler_arg;
    return &bound_socket;
}

static uint32_t sent_ip;
static uint16_t sent_port;
static uint8_t sent_data[512];
static int sent_len, sends;

void udp_packet_init(udp_packet_t *pkt, uint32_t ip_dst, uint16_t port_dst)
{
    (void)pkt;
    sent_ip = ip_dst;
    sent_port = port_dst;
}

/* Models the real transmit path: ip_packet_send_ll hands smap_transmit the 42-byte ETH+IP+UDP
   header plus pktdatasize bytes as "header", then data. SMAP's CopyToFIFO writes whole 32-bit
   words, so the header is rounded up to a word in the TX FIFO while the frame length stays exact:
   whatever the rounding pulled in goes on the wire, and the frame's tail is cut by as much. */
int udp_packet_send_ll(udp_socket_t *socket, udp_packet_t *pkt, uint16_t pktdatasize, const void *data, uint16_t datasize)
{
    static uint8_t fifo[2048];
    unsigned int header = 42 + pktdatasize, rounded = (header + 3) & ~3u, wire = header + datasize;

    assert(socket == &bound_socket);
    memcpy(fifo, pkt, rounded);
    if (datasize)
        memcpy(fifo + rounded, data, datasize);
    sent_len = (int)wire - 42;
    memcpy(sent_data, fifo + 42, sent_len);
    sends++;
    return 0;
}

/* ARP: 192.168.1.99 never answers. Broadcasts must not be resolved at all. */
static int arp_calls;
int arp_resolve(uint32_t ip, uint8_t mac[6])
{
    assert(ip != 0xFFFFFFFF);
    arp_calls++;
    memset(mac, 0x11, 6);
    return ip == IP_ADDR(192, 168, 1, 99) ? -1 : 0;
}

/* The frame currently "in the FIFO", as the SMAP RX path would see it. */
static uint8_t frame[2048];

void smap_fifo_read(uint16_t offset, void *dst, uint32_t bytes)
{
    assert(offset % 4 == 0);
    assert(bytes % 4 == 0);
    assert(bytes <= sizeof(xchg_rx));
    memcpy(dst, frame + offset, bytes);
}

/* Scripted replies: delivered on the Nth DelayThread call of the current exchange. */
typedef struct
{
    int at;
    uint8_t src[4];
    const char *text;
    int udp_payload; /* 0 = strlen(text) */
    int ip_payload;  /* 0 = consistent with the UDP length */
} script_t;

static script_t script[4];
static int script_count, delays;

static int deliver(const script_t *s)
{
    udp_packet_t *pkt = (udp_packet_t *)frame;
    int payload = s->udp_payload ? s->udp_payload : (int)strlen(s->text);

    memset(frame, 0, sizeof(frame));
    memcpy(pkt->ip.addr_src.addr, s->src, 4);
    pkt->udp.port_dst = htons(MSTACK_XCHG_PORT);
    pkt->udp.len = htons((uint16_t)(sizeof(udp_header_t) + payload));
    pkt->ip.len = htons((uint16_t)(sizeof(ip_header_t) + (s->ip_payload ? s->ip_payload : (int)sizeof(udp_header_t) + payload)));
    if (s->udp_payload) {
        for (int i = 0; i < payload && 42 + i < (int)sizeof(frame); i++)
            frame[42 + i] = (uint8_t)('a' + i % 26);
    } else
        memcpy(frame + 42, s->text, payload);
    return bound_handler(&bound_socket, NULL, frame, sizeof(udp_packet_t));
}

int DelayThread(int usec)
{
    assert(usec == 1000);
    delays++;
    for (int i = 0; i < script_count; i++)
        if (script[i].at == delays)
            deliver(&script[i]);
    return 0;
}

uint32_t ms_ip_get_ip(void)
{
    return IP_ADDR(192, 168, 1, 10);
}

int AddDrv(iomanX_iop_device_t *device)
{
    (void)device;
    return 0;
}

int DelDrv(const char *name)
{
    (void)name;
    return 0;
}

/* --- helpers ------------------------------------------------------------------------------ */

static uint32_t nip(int a, int b, int c, int d) /* network-order address as sin_addr.s_addr */
{
    uint32_t v;
    uint8_t bytes[4] = {(uint8_t)a, (uint8_t)b, (uint8_t)c, (uint8_t)d};
    memcpy(&v, bytes, 4);
    return v;
}

static struct
{
    mstack_xchg_reply_t reply;
    uint8_t guard[64];
} out;

static int exchange(uint32_t dst, uint16_t port, uint16_t timeout, const char *text)
{
    static mstack_xchg_req_t req;
    memset(&req, 0, sizeof(req));
    req.dst_ip = dst;
    req.dst_port = port;
    req.timeout_ms = timeout;
    req.len = (uint16_t)strlen(text);
    memcpy(req.data, text, req.len);
    delays = 0;
    memset(&out, 0x5A, sizeof(out));
    return xchg_devctl(NULL, "mstack:", MSTACK_DEVCTL_UDP_XCHG, &req, MSTACK_XCHG_REQ_HDR + req.len, &out.reply, sizeof(out.reply));
}

static void reply_at(int idx, int at, int a, int b, int c, int d, const char *text, int payload)
{
    script[idx].at = at;
    script[idx].src[0] = (uint8_t)a;
    script[idx].src[1] = (uint8_t)b;
    script[idx].src[2] = (uint8_t)c;
    script[idx].src[3] = (uint8_t)d;
    script[idx].text = text;
    script[idx].udp_payload = payload;
    script[idx].ip_payload = 0;
}

int main(void)
{
    int rc;

    /* version_probe */
    assert(xchg_devctl(NULL, "mstack:", MSTACK_DEVCTL_VERSION, NULL, 0, NULL, 0) == 1);

    /* unicast_roundtrip */
    script_count = 1;
    reply_at(0, 3, 192, 168, 1, 20, "RAA1 OK 5", 0);
    rc = exchange(nip(192, 168, 1, 20), 18194, 250, "RAQ1 abc 1.2.3.4 18196");
    assert(rc == 9);
    assert(out.reply.len == 9 && memcmp(out.reply.data, "RAA1 OK 5", 9) == 0);
    assert(out.reply.src_ip == nip(192, 168, 1, 20));
    assert(sent_len == 22 && memcmp(sent_data, "RAQ1 abc 1.2.3.4 18196", 22) == 0);
    assert(sent_ip == IP_ADDR(192, 168, 1, 20) && sent_port == 18194);

    /* odd lengths go on the wire exactly */
    for (int n = 1; n <= 8; n++) {
        static const char text[] = "RAP1 192.168.1.10 18196";
        char req[16];
        memcpy(req, text, n);
        req[n] = 0;
        script_count = 0;
        exchange(nip(192, 168, 1, 20), 18194, 1, req);
        assert(sent_len == n && memcmp(sent_data, req, n) == 0);
    }

    /* bind_once (with the roundtrip above and two more below) */
    assert(binds == 1 && bound_port == 18196);

    /* broadcast_any_source */
    script_count = 1;
    reply_at(0, 2, 192, 168, 1, 77, "RAO1 OK", 0);
    rc = exchange(0xFFFFFFFF, 18194, 250, "RAP1 192.168.1.10 18196");
    assert(rc == 7 && out.reply.src_ip == nip(192, 168, 1, 77));
    assert(sent_ip == 0xFFFFFFFF);

    /* stray_source_dropped */
    script_count = 2;
    reply_at(0, 2, 192, 168, 1, 21, "STRANGER", 0);
    reply_at(1, 4, 192, 168, 1, 20, "RAA1 NO", 0);
    rc = exchange(nip(192, 168, 1, 20), 18194, 250, "RAQ1 x");
    assert(rc == 7 && memcmp(out.reply.data, "RAA1 NO", 7) == 0);
    assert(out.reply.src_ip == nip(192, 168, 1, 20));
    assert(binds == 1);

    /* timeout */
    script_count = 0;
    rc = exchange(nip(192, 168, 1, 20), 18194, 50, "RAQ1 x");
    assert(rc == -ETIMEDOUT);
    assert(delays <= 52);

    /* late_reply_not_reused: a reply with no exchange armed is dropped ... */
    script[0].at = 0;
    reply_at(0, 0, 192, 168, 1, 20, "LATE", 0);
    assert(deliver(&script[0]) == -1);
    /* ... and does not satisfy the next exchange. */
    script_count = 0;
    rc = exchange(nip(192, 168, 1, 20), 18194, 20, "RAQ1 x");
    assert(rc == -ETIMEDOUT);

    /* oversize_truncated */
    script_count = 1;
    reply_at(0, 1, 192, 168, 1, 20, "", 1400);
    rc = exchange(nip(192, 168, 1, 20), 18194, 250, "RAG1 x");
    assert(rc == MSTACK_XCHG_REPLY_MAX && out.reply.len == MSTACK_XCHG_REPLY_MAX);
    assert(out.reply.data[0] == 'a' && out.reply.data[MSTACK_XCHG_REPLY_MAX - 1] == (uint8_t)('a' + (MSTACK_XCHG_REPLY_MAX - 1) % 26));
    for (unsigned i = 0; i < sizeof(out.guard); i++)
        assert(out.guard[i] == 0x5A);

    /* unreachable_unicast: ARP fails -> no frame to a stale or zero MAC, no wait */
    {
        int before = sends;
        script_count = 0;
        rc = exchange(nip(192, 168, 1, 99), 18194, 250, "RAQ1 x");
        assert(rc == -EHOSTUNREACH && sends == before && delays == 0);
    }

    /* udp_length_beyond_ip: a datagram claiming more than its IP packet carries is dropped
       instead of reading past the frame in the FIFO */
    script_count = 1;
    reply_at(0, 1, 192, 168, 1, 20, "", 1000);
    script[0].ip_payload = 8 + 10;
    rc = exchange(nip(192, 168, 1, 20), 18194, 20, "RAQ1 x");
    assert(rc == -ETIMEDOUT);

    /* get_ip: the address the ministack was really loaded with, network byte order */
    {
        uint8_t ip[8];
        memset(ip, 0, sizeof(ip));
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_GET_IP, NULL, 0, ip, 4) == 4);
        assert(ip[0] == 192 && ip[1] == 168 && ip[2] == 1 && ip[3] == 10);
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_GET_IP, NULL, 0, ip, 3) == -EINVAL);
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_GET_IP, NULL, 0, NULL, 4) == -EINVAL);
    }

    /* bad_args */
    {
        static mstack_xchg_req_t req;
        static mstack_xchg_reply_t reply;
        memset(&req, 0, sizeof(req));
        req.dst_ip = nip(192, 168, 1, 20);
        req.dst_port = 18194;
        req.timeout_ms = 10;
        req.len = 0;
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_UDP_XCHG, &req, sizeof(req), &reply, sizeof(reply)) == -EINVAL);
        req.len = MSTACK_XCHG_REQ_MAX + 1;
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_UDP_XCHG, &req, sizeof(req), &reply, sizeof(reply)) == -EINVAL);
        req.len = 4;
        req.dst_port = 0;
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_UDP_XCHG, &req, sizeof(req), &reply, sizeof(reply)) == -EINVAL);
        req.dst_port = 18194;
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_UDP_XCHG, &req, sizeof(req), &reply, sizeof(reply) - 1) == -EINVAL);
        assert(xchg_devctl(NULL, "", MSTACK_DEVCTL_UDP_XCHG, &req, MSTACK_XCHG_REQ_HDR + 3, &reply, sizeof(reply)) == -EINVAL);
        assert(xchg_devctl(NULL, "", 0x1234, &req, sizeof(req), &reply, sizeof(reply)) == -EINVAL);
    }

    assert(binds == 1);
    printf("PASS: mstack exchange\n");
    return 0;
}
