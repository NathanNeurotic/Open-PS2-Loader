/*
  ratls_ps2.c -- the console half of the RetroAchievements HTTPS lookup.

  Supplies what src/ratls.c needs on a PS2: DNS and a TCP connection through
  the menu's network stack (ps2ips), a BIO that reads with lwIP's per-call
  non-blocking flag under an overall deadline (fcntl O_NONBLOCK has no effect
  on this stack, see ranet.c), the console clock as UTC, an entropy source,
  mbedtls_ms_time(), and the six embedded roots (third_party/ca-roots, turned
  into ratls_root_<name>.c by the Makefile).

  Runs on the I/O worker. Refuses while a UDP transport owns the NIC.
*/

#include "include/ratls.h"
#include "include/ranet.h" /* raNetNicReserved, raNetTcpRecv */

#include <ps2ips.h>
#include <netdb.h>
#include <kernel.h>
#include <delaythread.h>
#include <libcdvd.h>
#include <string.h>
#include <time.h>

#include "mbedtls/net_sockets.h" /* MBEDTLS_ERR_NET_SEND_FAILED */
#include "mbedtls/platform_time.h"
#include "mbedtls/ssl.h"

#define RATLS_DEADLINE_MS 8000 /* the same budget as the xeRAbora HTTP fetch (RA_HTTP_MS) */
#define RATLS_POLL_MS     25
#define RATLS_MIN_YEAR    2025 /* an earlier RTC is unset: fail closed */

extern unsigned char ratls_root_gtsr1[], ratls_root_gtsr3[], ratls_root_gtsr4[];
extern unsigned char ratls_root_isrgrootx1[], ratls_root_isrgrootx2[];
extern unsigned int size_ratls_root_gtsr1, size_ratls_root_gtsr3, size_ratls_root_gtsr4;
extern unsigned int size_ratls_root_isrgrootx1, size_ratls_root_isrgrootx2;

static int bcd(unsigned char v)
{
    return (v >> 4) * 10 + (v & 0x0F);
}

static long long ratlsNow(void)
{
    sceCdCLOCK clk;
    int year;

    if (sceCdReadClock(&clk) == 0)
        return -1;
    year = 2000 + bcd(clk.year);
    if (year < RATLS_MIN_YEAR)
        return -1;
    return raTlsRtcToUtc(year, bcd(clk.month & 0x1F), bcd(clk.day), bcd(clk.hour), bcd(clk.minute), bcd(clk.second));
}

mbedtls_ms_time_t mbedtls_ms_time(void)
{
    return (mbedtls_ms_time_t)clock() * 1000 / CLOCKS_PER_SEC;
}

static inline unsigned int cop0Count(void)
{
    unsigned int count;
    __asm__ volatile("mfc0 %0, $9"
                     : "=r"(count));
    return count;
}

/* The PS2 has no hardware RNG. Each output byte folds 8 samples of the
   294.912 MHz COP0 count's low bits across a thread switch (interrupt and DMA
   timing make them jitter), credited at 1 bit per sample; the CDVD clock and
   clock() are mixed in once per call. mbedTLS's entropy accumulator gathers
   until the CTR_DRBG seed reaches its threshold (spec: >= 512 samples, about
   256 bits by this estimate). */
int mbedtls_hardware_poll(void *data, unsigned char *out, size_t len, size_t *olen)
{
    sceCdCLOCK clk;
    size_t i;
    int s;

    (void)data;
    for (i = 0; i < len; i++) {
        unsigned char byte = 0;
        for (s = 0; s < 8; s++) {
            unsigned int before = cop0Count();
            DelayThread(1);
            byte = (unsigned char)((byte << 1) | (byte >> 7)) ^ (unsigned char)(cop0Count() - before);
        }
        out[i] = byte ^ (unsigned char)clock();
    }
    if (len >= sizeof(clk) && sceCdReadClock(&clk) != 0) {
        const unsigned char *c = (const unsigned char *)&clk;
        for (i = 0; i < sizeof(clk); i++)
            out[i] ^= c[i];
    }
    *olen = len;
    return 0;
}

typedef struct
{
    int sock;
    clock_t start; /* the budget runs from before DNS */
} ratls_bio_t;

/* clock() is a 32-bit microsecond counter here: compare elapsed time, which survives the wrap,
   and keep the product small (milliseconds times a full CLOCKS_PER_SEC would overflow). */
static int ratlsExpired(clock_t start)
{
    return (clock_t)(clock() - start) >= (clock_t)RATLS_DEADLINE_MS * (CLOCKS_PER_SEC / 1000);
}

static int bioSend(void *ctx, const unsigned char *buf, size_t len)
{
    ratls_bio_t *bio = ctx;
    int n = send(bio->sock, (void *)buf, len, 0);
    return n < 0 ? MBEDTLS_ERR_NET_SEND_FAILED : n;
}

/* Reads through a 64-byte-aligned bounce buffer, never more than 960 bytes at
   a time (the same rules as raNetHttpGet), polling until data, close or the
   deadline. */
static int bioRecv(void *ctx, unsigned char *buf, size_t len)
{
    static unsigned char chunk[960] __attribute__((aligned(64)));
    ratls_bio_t *bio = ctx;

    for (;;) {
        int got;
        if (ratlsExpired(bio->start))
            return MBEDTLS_ERR_SSL_TIMEOUT;
        got = raNetTcpRecv(bio->sock, chunk, len < sizeof(chunk) ? (int)len : (int)sizeof(chunk));
        if (got == 0)
            return 0; /* closed */
        if (got > 0) {
            memcpy(buf, chunk, got);
            return got;
        }
        DelayThread(RATLS_POLL_MS * 1000);
    }
}

int raHttpsGet(const char *host, const char *path, char *buf, int max, int *length)
{
    static ratls_anchor_t anchors[5];
    struct sockaddr_in to;
    struct hostent *he;
    ratls_bio_t bio;
    ratls_io_t io;
    int rc;
    clock_t start = clock();

    if (length != NULL)
        *length = 0;
    if (!raTlsClockOk(ratlsNow)) /* before any DNS lookup or connection */
        return RATLS_ERR_CLOCK;
    if (raNetNicReserved())
        return RATLS_ERR_NET;

    anchors[0].der = ratls_root_gtsr1;
    anchors[0].len = size_ratls_root_gtsr1;
    anchors[1].der = ratls_root_gtsr3;
    anchors[1].len = size_ratls_root_gtsr3;
    anchors[2].der = ratls_root_gtsr4;
    anchors[2].len = size_ratls_root_gtsr4;
    anchors[3].der = ratls_root_isrgrootx1;
    anchors[3].len = size_ratls_root_isrgrootx1;
    anchors[4].der = ratls_root_isrgrootx2;
    anchors[4].len = size_ratls_root_isrgrootx2;

    he = gethostbyname(host);
    if (he == NULL || he->h_addr_list == NULL || he->h_addr_list[0] == NULL)
        return RATLS_ERR_NET;
    memset(&to, 0, sizeof(to));
    to.sin_family = AF_INET;
    to.sin_port = htons(443);
    memcpy(&to.sin_addr, he->h_addr_list[0], sizeof(to.sin_addr));

    bio.sock = socket(AF_INET, SOCK_STREAM, 0);
    if (bio.sock < 0)
        return RATLS_ERR_NET;
    if (connect(bio.sock, (struct sockaddr *)&to, sizeof(to)) < 0) {
        disconnect(bio.sock);
        return RATLS_ERR_NET;
    }
    bio.start = start;
    if (ratlsExpired(start)) { /* DNS and connect already used the budget */
        disconnect(bio.sock);
        return RATLS_ERR_TIMEOUT;
    }
    io.send = bioSend;
    io.recv = bioRecv;
    io.ctx = &bio;
    io.now_utc = ratlsNow;

    rc = raTlsRequest(&io, host, path, "RiptOPL/" OPL_VERSION, anchors, 5, buf, max, length);
    disconnect(bio.sock);
    return rc;
}
