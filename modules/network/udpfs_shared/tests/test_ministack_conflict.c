/*
 * Host test for udpfs_ministack's IP-conflict detection (ministack_arp.c).
 *
 * Another device answering ARP for the PS2's own IP -- typically the reply to the gratuitous ARP sent
 * before each UDPRDMA DISCOVERY -- must be recorded with its MAC so the loader can tell the user.
 * Our own frames and other addresses must not count, and our own IP is never cached as a neighbour.
 */
#include <stdio.h>
#include <string.h>

#include "../../udpfs_ministack/src/ministack_arp.c"

static const uint8_t our_mac[6] = {0x00, 0x04, 0x1f, 0x11, 0x22, 0x33};
static const uint8_t other_mac[6] = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff};
static const uint8_t server_mac[6] = {0x10, 0x20, 0x30, 0x40, 0x50, 0x60};
#define OUR_IP    IP_ADDR(192, 168, 1, 10)
#define SERVER_IP IP_ADDR(192, 168, 1, 2)

static int transmits;

int SMAPGetMACAddress(uint8_t *buffer)
{
    memcpy(buffer, our_mac, 6);
    return 0;
}
int eth_packet_send_ll(eth_packet_t *pkt, uint16_t pktdatasize, const void *data, uint16_t datasize)
{
    (void)pkt;
    (void)pktdatasize;
    (void)data;
    (void)datasize;
    transmits++;
    return 0;
}
uint32_t ms_ip_get_ip(void)
{
    return OUR_IP;
}
int DelayThread(int usec)
{
    (void)usec;
    return 0;
}

static void deliver(int oper, const uint8_t mac[6], uint32_t sender, uint32_t target)
{
    static arp_packet_t pkt;

    memset(&pkt, 0, sizeof(pkt));
    pkt.arp.oper = htons(oper);
    memcpy(pkt.arp.sender_mac, mac, 6);
    pkt.arp.sender_ip = htonl(sender);
    pkt.arp.target_ip = htonl(target);
    handle_rx_arp((const uint8_t *)&pkt);
}

static int failures;

static void check(const char *what, int ok)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        failures++;
    }
}

int main(void)
{
    uint8_t mac[6], seen[6];

    /* Ordinary traffic: the server asks for us. We answer and learn it; no conflict. */
    deliver(1, server_mac, SERVER_IP, OUR_IP);
    check("a request for our IP is answered", transmits == 1);
    check("the asking server is learned", arp_lookup(SERVER_IP, mac) == 0 && !memcmp(mac, server_mac, 6));
    check("ordinary traffic is not a conflict", arp_ip_conflict(NULL) == 0);

    /* Our own address from our own MAC (a looped-back announce) is not a conflict. */
    deliver(1, our_mac, OUR_IP, OUR_IP);
    check("our own announce is not a conflict", arp_ip_conflict(NULL) == 0);

    /* Another device replies for our IP: record it and its MAC; never cache our own IP. */
    deliver(2, other_mac, OUR_IP, OUR_IP);
    check("another device claiming our IP is a conflict", arp_ip_conflict(seen) == 1);
    check("the conflicting MAC is reported", !memcmp(seen, other_mac, 6));
    check("our own IP is never cached as a neighbour", arp_lookup(OUR_IP, mac) != 0);
    check("a NULL MAC buffer is allowed", arp_ip_conflict(NULL) == 1);

    if (failures) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("ministack conflict: all checks passed\n");
    return 0;
}
