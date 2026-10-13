/*
 * mstack: -- one UDP request/reply exchange for the EE, over the ministack.
 *
 * While a UDPFS chain owns the network adapter, RiptOPL's menu cannot run its lwIP stack, so the
 * RetroAchievements support check (RAP1/RAQ1/RAG1, CADQ2/CADB1) sends each request through here
 * instead: fileXioDevctl("mstack:", MSTACK_DEVCTL_UDP_XCHG, req, ..., reply, ...).
 *
 * The request goes out from the fixed port MSTACK_XCHG_PORT (bound once: the ministack has four
 * port slots and no unbind), and the PC answers to the address and port written in the request
 * text. The reply is copied in the SMAP receive context and picked up by polling, so the exchange
 * needs no kernel objects and shares no lock with UDPFS traffic.
 */
#include <errno.h>
#include <stddef.h>
#include <iomanX.h>
#include <string.h>
#include <thbase.h>

#include "mstack_xchg.h"
#include "ministack_arp.h"
#include "ministack_udp.h"
#include "smap.h"

static udp_socket_t *xchg_socket;
/* The request is sent as part of the header, starting at the 2-byte align field: SMAP's
   CopyToFIFO writes whole words, so a 42-byte header followed by separate data would put the
   align bytes on the wire and cut the request's tail (udptty and udprdma keep the header a
   multiple of 4 for the same reason). Copying also keeps the fileXio RPC buffer away from the
   FIFO's word loads and DMA. */
static struct
{
    udp_packet_t h;
    uint8_t more[MSTACK_XCHG_REQ_MAX];
} __attribute__((aligned(64))) xchg_tx;

static volatile int xchg_waiting, xchg_got;
static volatile uint32_t xchg_want_ip; /* network byte order; 0xFFFFFFFF = broadcast, any source */
static volatile uint32_t xchg_src_ip;  /* network byte order */
static volatile uint16_t xchg_len;
/* FIFO reads start at frame offset 40 (word-aligned, the UDP checksum), so the payload is at +2.
   Room for the largest reply plus that offset, rounded up to whole words. */
static uint8_t xchg_rx[MSTACK_XCHG_REPLY_MAX + 8] __attribute__((aligned(64)));

#define XCHG_FIFO_OFFSET 40 /* ETH 14 + IP 20 + UDP 8 = 42: read from the word below */
#define XCHG_ANY_SOURCE  0xFFFFFFFF

static int xchg_rx_handler(udp_socket_t *socket, void *arg, const uint8_t *hdr, uint16_t hdr_len)
{
    const udp_packet_t *pkt = (const udp_packet_t *)hdr;
    uint32_t src;
    uint16_t udplen, len;

    (void)socket;
    (void)arg;
    if (!xchg_waiting || xchg_got || hdr_len < sizeof(udp_packet_t))
        return -1;

    memcpy(&src, pkt->ip.addr_src.addr, 4); /* bytes as on the wire = network order */
    if (xchg_want_ip != XCHG_ANY_SOURCE && src != xchg_want_ip)
        return -1;

    udplen = ntohs(pkt->udp.len);
    /* The UDP length must fit the IP packet that carries it, or the FIFO read below would run
       past this frame into stale data or the next frame. */
    if (udplen < sizeof(udp_header_t) || ntohs(pkt->ip.len) < sizeof(ip_header_t) ||
        udplen > ntohs(pkt->ip.len) - sizeof(ip_header_t))
        return -1;
    len = udplen - sizeof(udp_header_t);
    if (len > MSTACK_XCHG_REPLY_MAX)
        len = MSTACK_XCHG_REPLY_MAX;

    smap_fifo_read(XCHG_FIFO_OFFSET, xchg_rx, (2 + len + 3) & ~3);
    xchg_src_ip = src;
    xchg_len = len;
    xchg_got = 1;
    return 0;
}

int mstack_xchg(const mstack_xchg_req_t *req, mstack_xchg_reply_t *reply)
{
    unsigned int waited;

    if (req == NULL || reply == NULL || req->len == 0 || req->len > MSTACK_XCHG_REQ_MAX || req->dst_port == 0)
        return -EINVAL;

    if (xchg_socket == NULL) {
        xchg_socket = udp_bind(MSTACK_XCHG_PORT, xchg_rx_handler, NULL);
        if (xchg_socket == NULL)
            return -ENOMEM;
    }

    /* Resolve first: the send path ignores an ARP failure and would put the frame on whatever
       MAC the header last held. */
    if (req->dst_ip != XCHG_ANY_SOURCE) {
        uint8_t mac[6];
        if (arp_resolve(ntohl(req->dst_ip), mac) != 0)
            return -EHOSTUNREACH;
    }

    xchg_got = 0;
    xchg_want_ip = req->dst_ip;
    xchg_waiting = 1; /* armed before sending: the answer can beat the send's return */

    udp_packet_init(&xchg_tx.h, ntohl(req->dst_ip), req->dst_port);
    /* through the whole struct, so no compiler reads it as an overflow of the 2-byte field */
    memcpy((uint8_t *)&xchg_tx + offsetof(udp_packet_t, align), req->data, req->len);
    udp_packet_send(xchg_socket, &xchg_tx.h, req->len);

    for (waited = 0; !xchg_got && waited < req->timeout_ms; waited++)
        DelayThread(1000);

    xchg_waiting = 0;
    if (!xchg_got)
        return -ETIMEDOUT;

    reply->src_ip = xchg_src_ip;
    reply->len = xchg_len;
    reply->pad = 0;
    memcpy(reply->data, xchg_rx + 2, xchg_len);
    return xchg_len;
}

static int xchg_devctl(iomanX_iop_file_t *f, const char *name, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen)
{
    const mstack_xchg_req_t *req = (const mstack_xchg_req_t *)arg;

    (void)f;
    (void)name;
    if (cmd == MSTACK_DEVCTL_VERSION)
        return MSTACK_XCHG_VERSION;
    if (cmd == MSTACK_DEVCTL_GET_IP) {
        uint32_t ip = ms_ip_get_ip();
        uint8_t *out = (uint8_t *)buf;
        if (out == NULL || buflen < 4)
            return -EINVAL;
        out[0] = ip >> 24;
        out[1] = ip >> 16;
        out[2] = ip >> 8;
        out[3] = ip;
        return 4;
    }
    if (cmd != MSTACK_DEVCTL_UDP_XCHG || req == NULL || arglen < MSTACK_XCHG_REQ_HDR ||
        req->len > MSTACK_XCHG_REQ_MAX || arglen < MSTACK_XCHG_REQ_HDR + req->len ||
        buf == NULL || buflen < sizeof(mstack_xchg_reply_t))
        return -EINVAL;
    return mstack_xchg(req, (mstack_xchg_reply_t *)buf);
}

static int xchg_dev_init(iomanX_iop_device_t *d)
{
    (void)d;
    return 0;
}

static int xchg_unsupported(void)
{
    return -EIO;
}

/* iomanX order: init, deinit, format, open, close, read, write, lseek, ioctl, remove, mkdir,
   rmdir, dopen, dclose, dread, getstat, chstat, rename, chdir, sync, mount, umount, lseek64,
   devctl, symlink, readlink, ioctl2. */
static iomanX_iop_device_ops_t xchg_ops = {
    (void *)xchg_dev_init,
    (void *)xchg_dev_init,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_devctl,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported,
    (void *)xchg_unsupported};

static iomanX_iop_device_t xchg_device = {
    "mstack",
    IOP_DT_FS | IOP_DT_FSEXT,
    1,
    "ministack UDP exchange",
    &xchg_ops};

int mstack_xchg_init(void)
{
    DelDrv(xchg_device.name);
    return AddDrv(&xchg_device);
}
