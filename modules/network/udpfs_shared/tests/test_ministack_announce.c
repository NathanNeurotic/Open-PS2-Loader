/*
 * Host test for udpfs_ministack's discovery ARP announcement (ministack_udp.c).
 *
 * A UDPRDMA DISCOVERY is a broadcast from a bound socket; the server answers it with a
 * unicast INFORM, so a gratuitous ARP must go out first. udptty's console broadcasts
 * (unbound, port 0) and ordinary unicast traffic must not announce.
 */
#include <stdio.h>
#include <string.h>

#include "../../udpfs_ministack/src/ministack_udp.c"

static int announces, transmits;

void arp_announce(void)
{
    announces++;
}

void ip_packet_init(ip_packet_t *pkt, uint32_t ip_dest)
{
    pkt->ip.addr_dst.addr[0] = (ip_dest >> 24) & 0xff;
    pkt->ip.addr_dst.addr[1] = (ip_dest >> 16) & 0xff;
    pkt->ip.addr_dst.addr[2] = (ip_dest >> 8) & 0xff;
    pkt->ip.addr_dst.addr[3] = ip_dest & 0xff;
}

int ip_packet_send_ll(ip_packet_t *pkt, uint16_t pktdatasize, const void *data, uint16_t datasize)
{
    (void)pkt;
    (void)pktdatasize;
    (void)data;
    (void)datasize;
    transmits++;
    return 0;
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
    static udp_packet_t pkt;
    udp_socket_t *bound = udp_bind(0xF5F6, NULL, NULL);
    udp_socket_t tty = {0, NULL, NULL};

    udp_packet_init(&pkt, IP_ADDR(255, 255, 255, 255), 0xF5F6);
    udp_packet_send(bound, &pkt, 6);
    check("discovery broadcast announces once", announces == 1 && transmits == 1);

    udp_packet_send(&tty, &pkt, 6);
    check("udptty broadcast does not announce", announces == 1 && transmits == 2);

    udp_packet_init(&pkt, IP_ADDR(192, 168, 1, 2), 57996);
    udp_packet_send(bound, &pkt, 6);
    check("unicast data does not announce", announces == 1 && transmits == 3);

    if (failures) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("ministack announce: all checks passed\n");
    return 0;
}
