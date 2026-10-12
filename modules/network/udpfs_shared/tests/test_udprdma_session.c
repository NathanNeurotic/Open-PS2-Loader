/*
 * Host test for the shared UDPRDMA transport (udpfs_shared/src/udprdma.c).
 *
 * The real transport is compiled against stubbed IOP event flags, alarms and a stubbed
 * ministack. A script feeds it what the network and the alarm would deliver, and every
 * packet it transmits is recorded. Checks:
 *   - a stale ACK does not cost a retry: the request is sent once and the covering ACK
 *     that follows completes it;
 *   - a reconnect after a dead session starts again from sequence 0 (TX and RX), which
 *     is what a server that reset its session on DISCOVERY expects.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/udprdma.c"

enum {
    EV_TIMEOUT,
    EV_INFORM,
    EV_ACK,
    EV_DATA_FIN,
};

typedef struct
{
    int kind;
    int arg;
} script_ev_t;

static script_ev_t script[32];
static int script_len, script_pos;

static uint32_t flags;
static unsigned int (*alarm_cb)(void *);
static void *alarm_arg;

static udp_socket_t bound_socket;
static uint8_t frame[64];

typedef struct
{
    int type;
    int seq;
    int seq_nr_ack;
    int payload;
} sent_t;

static sent_t sent[64];
static int sent_len;

static int failures;

static void check(const char *what, int ok)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        failures++;
    }
}

static void run_script(int n, const script_ev_t *evs)
{
    memcpy(script, evs, n * sizeof(*evs));
    script_len = n;
    script_pos = 0;
}

/* --- network injection --- */

static void deliver(void)
{
    bound_socket.handler(&bound_socket, bound_socket.handler_arg, frame, 44);
}

static void inject_inform(void)
{
    udprdma_pkt_disc_t *p = (udprdma_pkt_disc_t *)frame;

    memset(frame, 0, sizeof(frame));
    p->ip.addr_src.addr[0] = 192;
    p->ip.addr_src.addr[1] = 168;
    p->ip.addr_src.addr[2] = 1;
    p->ip.addr_src.addr[3] = 2;
    p->udp.port_src = htons(57996); /* PS2-Servers' separate data port */
    p->hdr.packet_type = UDPRDMA_PT_INFORM;
    p->hdr.seq_nr = 1;
    p->disc.service_id = UDPRDMA_SVC_UDPFS;
    deliver();
}

static void inject_data(int seq, int ack, int flags_, int bytes)
{
    udprdma_pkt_data_t *p = (udprdma_pkt_data_t *)frame;

    memset(frame, 0, sizeof(frame));
    p->hdr.packet_type = UDPRDMA_PT_DATA;
    p->hdr.seq_nr = seq;
    p->data.seq_nr_ack = ack;
    p->data.flags = flags_;
    p->data.data_byte_count = bytes;
    deliver();
}

static void step(void)
{
    script_ev_t ev;

    if (script_pos >= script_len) {
        fprintf(stderr, "FAIL: transport waited past the end of the script\n");
        exit(1);
    }
    ev = script[script_pos++];
    switch (ev.kind) {
        case EV_TIMEOUT:
            if (alarm_cb == NULL) {
                fprintf(stderr, "FAIL: timeout scripted with no alarm armed\n");
                exit(1);
            }
            alarm_cb(alarm_arg);
            break;
        case EV_INFORM:
            inject_inform();
            break;
        case EV_ACK:
            inject_data(0, ev.arg, UDPRDMA_DF_ACK, 0);
            break;
        case EV_DATA_FIN:
            inject_data(ev.arg, 0, UDPRDMA_DF_FIN, 4);
            break;
    }
}

/* --- IOP stubs --- */

int CreateEventFlag(iop_event_t *event)
{
    flags = event->bits;
    return 1;
}
int DeleteEventFlag(int ef)
{
    (void)ef;
    return 0;
}
int SetEventFlag(int ef, uint32_t bits)
{
    (void)ef;
    flags |= bits;
    return 0;
}
int iSetEventFlag(int ef, uint32_t bits)
{
    return SetEventFlag(ef, bits);
}
int ClearEventFlag(int ef, uint32_t bits)
{
    (void)ef;
    flags &= bits;
    return 0;
}
int WaitEventFlag(int ef, uint32_t bits, int mode, uint32_t *resbits)
{
    (void)ef;
    while (!(flags & bits))
        step();
    *resbits = flags;
    if (mode & WEF_CLEAR)
        flags = 0;
    return 0;
}
void USec2SysClock(uint32_t usec, iop_sys_clock_t *clock)
{
    clock->lo = usec;
    clock->hi = 0;
}
int SetAlarm(iop_sys_clock_t *clock, unsigned int (*cb)(void *), void *arg)
{
    (void)clock;
    alarm_cb = cb;
    alarm_arg = arg;
    return 0;
}
int CancelAlarm(unsigned int (*cb)(void *), void *arg)
{
    (void)cb;
    (void)arg;
    alarm_cb = NULL;
    return 0;
}
int DelayThread(int usec)
{
    (void)usec;
    return 0;
}

void smap_fifo_read(uint16_t offset, void *dst, uint32_t bytes)
{
    memcpy(dst, frame + offset, bytes);
}

udp_socket_t *udp_bind(uint16_t port_src, udp_port_handler handler, void *handler_arg)
{
    bound_socket.port_src = port_src;
    bound_socket.handler = handler;
    bound_socket.handler_arg = handler_arg;
    return &bound_socket;
}
void udp_packet_init(udp_packet_t *pkt, uint32_t ip_dst, uint16_t port_dst)
{
    (void)ip_dst;
    pkt->udp.port_dst = htons(port_dst);
}
int udp_packet_send_ll(udp_socket_t *socket, udp_packet_t *pkt, uint16_t pktdatasize, const void *data, uint16_t datasize)
{
    udprdma_pkt_data_t *p = (udprdma_pkt_data_t *)pkt;

    (void)socket;
    (void)pktdatasize;
    (void)data;
    if (sent_len < (int)(sizeof(sent) / sizeof(sent[0]))) {
        sent[sent_len].type = p->hdr.packet_type;
        sent[sent_len].seq = p->hdr.seq_nr;
        sent[sent_len].seq_nr_ack = p->hdr.packet_type == UDPRDMA_PT_DATA ? (int)p->data.seq_nr_ack : -1;
        sent[sent_len].payload = datasize;
        sent_len++;
    }
    return 0;
}

static int count_requests(int from)
{
    int i, n = 0;
    for (i = from; i < sent_len; i++)
        if (sent[i].type == UDPRDMA_PT_DATA && sent[i].payload > 0)
            n++;
    return n;
}

static int first_request(int from)
{
    int i;
    for (i = from; i < sent_len; i++)
        if (sent[i].type == UDPRDMA_PT_DATA && sent[i].payload > 0)
            return i;
    return -1;
}

int main(void)
{
    static const script_ev_t connect[] = {{EV_INFORM, 0}};
    static const script_ev_t stale_then_ack1[] = {{EV_ACK, 0}, {EV_ACK, 1}};
    static const script_ev_t reply_seq0[] = {{EV_DATA_FIN, 0}};
    static const script_ev_t ack2[] = {{EV_ACK, 2}};
    static const script_ev_t dead[] = {{EV_TIMEOUT, 0}, {EV_TIMEOUT, 0}, {EV_TIMEOUT, 0}, {EV_TIMEOUT, 0}};
    static const script_ev_t ack0[] = {{EV_ACK, 0}};
    static const script_ev_t timeout_then_ack0[] = {{EV_TIMEOUT, 0}, {EV_ACK, 0}};
    uint8_t req[16] = {0}, reply[16];
    udprdma_socket_t *s;
    int mark, idx;

    s = udprdma_create(0, UDPRDMA_SVC_UDPFS);
    check("socket created", s != NULL);

    /* A fresh socket must not treat the first request as already acknowledged. */
    run_script(1, connect);
    check("first discovery connects", udprdma_discover(s, 2000) == UDPRDMA_OK);
    mark = sent_len;
    run_script(2, timeout_then_ack0);
    check("first request survives one timeout", udprdma_send(s, req, sizeof(req)) == UDPRDMA_OK);
    check("unacknowledged first request is resent once", count_requests(mark) == 2);

    /* Stale ACK: keep waiting for the covering ACK, do not resend. */
    mark = sent_len;
    run_script(2, stale_then_ack1); /* ACK 0 is stale for request 1 */
    check("request with a stale ACK first completes", udprdma_send(s, req, sizeof(req)) == UDPRDMA_OK);
    check("a stale ACK does not cost a retry", count_requests(mark) == 1);
    check("stale ACK leaves the script fully consumed", script_pos == script_len);

    /* Receive one reply so RX state is non-zero too. */
    udprdma_set_rx_buffer(s, reply, sizeof(reply));
    run_script(1, reply_seq0);
    check("reply received", udprdma_recv(s, reply, sizeof(reply), 1000) == 4);

    run_script(1, ack2);
    check("second request completes", udprdma_send(s, req, sizeof(req)) == UDPRDMA_OK);

    /* The session dies: four timeouts disconnect it. */
    mark = sent_len;
    run_script(4, dead);
    check("dead session returns an error", udprdma_send(s, req, sizeof(req)) == UDPRDMA_ERR_NACK);
    check("dead session sent four tries", count_requests(mark) == 4);
    check("dead session disconnects", !udprdma_is_connected(s));

    /* Reconnect: the server reset its session on DISCOVERY, so start again from zero. */
    run_script(1, connect);
    check("rediscovery connects", udprdma_discover(s, 2000) == UDPRDMA_OK);
    mark = sent_len;
    run_script(1, ack0);
    check("first request after reconnect completes", udprdma_send(s, req, sizeof(req)) == UDPRDMA_OK);
    idx = first_request(mark);
    check("a request was sent after reconnect", idx >= 0);
    if (idx >= 0) {
        check("reconnect restarts TX at sequence 0", sent[idx].seq == 0);
        check("reconnect restarts RX expectation at 0", sent[idx].seq_nr_ack == 0xFFF);
    }

    if (failures) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("udprdma session: all checks passed\n");
    return 0;
}
