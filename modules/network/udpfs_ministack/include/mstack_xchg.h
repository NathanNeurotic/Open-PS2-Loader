#ifndef MSTACK_XCHG_H
#define MSTACK_XCHG_H

/*
 * One UDP request/reply exchange through the ministack, for RiptOPL's menu RA requests while a
 * UDPFS chain owns the network adapter (the menu's lwIP stack cannot run then). Reached from the
 * EE with fileXioDevctl("mstack:", ...); shared with src/ranet.c, so plain <stdint.h> types only.
 */

#include <stdint.h>

#define MSTACK_XCHG_DEVICE     "mstack:"
#define MSTACK_DEVCTL_VERSION  0x4D530000 /* returns MSTACK_XCHG_VERSION */
#define MSTACK_DEVCTL_UDP_XCHG 0x4D530001
#define MSTACK_DEVCTL_GET_IP   0x4D530002 /* buf <- the ministack's own IPv4, 4 bytes, network order */
#define MSTACK_XCHG_VERSION    1
#define MSTACK_XCHG_PORT       18196 /* RA_MY_PORT: the PC replies to the port written in the request */
#define MSTACK_XCHG_REQ_MAX    256
#define MSTACK_XCHG_REPLY_MAX  1016 /* reply struct = 1024 bytes, a 64-byte multiple for the EE DMA */

/* dst_ip and src_ip are in network byte order, as sin_addr.s_addr. */
typedef struct
{
    uint32_t dst_ip;
    uint16_t dst_port;
    uint16_t timeout_ms;
    uint16_t len;
    uint16_t pad;
    uint8_t data[MSTACK_XCHG_REQ_MAX];
} mstack_xchg_req_t;

typedef struct
{
    uint32_t src_ip;
    uint16_t len;
    uint16_t pad;
    uint8_t data[MSTACK_XCHG_REPLY_MAX];
} mstack_xchg_reply_t;

#define MSTACK_XCHG_REQ_HDR ((unsigned int)(sizeof(mstack_xchg_req_t) - MSTACK_XCHG_REQ_MAX))

#endif /* MSTACK_XCHG_H */
