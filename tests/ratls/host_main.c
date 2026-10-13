/*
 * Host driver for src/ratls.c (the portable TLS + HTTP GET of the RA HTTPS game-ID lookup).
 * Driven by .github/scripts/test_ratls_host.py. Supplies what src/ratls_ps2.c supplies on the
 * console: a connected socket as the BIO (with a deadline), the clock, the entropy source and
 * mbedtls_ms_time().
 *
 *   host_main get HOST PORT PATH MAX DEADLINE_MS NOW ANCHOR.der...   NOW: epoch, "sys", or "unset"
 *   host_main anchors FILE.der...
 *   host_main rtc Y M D h m s
 *   host_main drbg
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include <fcntl.h>
#include <io.h>
#define poll       WSAPoll
#define close_sock closesocket
typedef SOCKET sock_t;
#else
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#define close_sock close
typedef int sock_t;
#endif

#include "include/ratls.h"
#include "mbedtls/platform_time.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"

/* --- what the console's platform layer supplies -------------------------------------------- */

int mbedtls_hardware_poll(void *data, unsigned char *out, size_t len, size_t *olen)
{
    (void)data;
#ifdef _WIN32
    if (BCryptGenRandom(NULL, out, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
        return -1;
#else
    FILE *f = fopen("/dev/urandom", "rb");
    if (f == NULL || fread(out, 1, len, f) != len) {
        if (f)
            fclose(f);
        return -1;
    }
    fclose(f);
#endif
    *olen = len;
    return 0;
}

mbedtls_ms_time_t mbedtls_ms_time(void)
{
    return (mbedtls_ms_time_t)clock() * 1000 / CLOCKS_PER_SEC;
}

static long long fixed_now;
static int now_mode; /* 0 = system, 1 = fixed, 2 = unset */

static long long now_utc(void)
{
    if (now_mode == 2)
        return -1;
    if (now_mode == 1)
        return fixed_now;
    return (long long)time(NULL);
}

typedef struct
{
    sock_t sock;
    clock_t deadline;
} bio_t;

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
    bio_t *bio = ctx;
    int n = send(bio->sock, (const char *)buf, (int)len, 0);
    return n < 0 ? MBEDTLS_ERR_SSL_INTERNAL_ERROR : n;
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
    bio_t *bio = ctx;
    for (;;) {
        struct pollfd p;
        long left = (long)((bio->deadline - clock()) * 1000 / CLOCKS_PER_SEC);
        if (left <= 0)
            return MBEDTLS_ERR_SSL_TIMEOUT;
        p.fd = bio->sock;
        p.events = POLLIN;
        p.revents = 0;
        if (poll(&p, 1, (int)(left < 50 ? left : 50)) > 0) {
            int n = recv(bio->sock, (char *)buf, (int)len, 0);
            return n < 0 ? MBEDTLS_ERR_SSL_INTERNAL_ERROR : n; /* 0 = peer closed */
        }
    }
}

static unsigned char *read_file(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    unsigned char *data;
    long size;
    if (f == NULL)
        return NULL;
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    data = malloc(size > 0 ? size : 1);
    if (fread(data, 1, size, f) != (size_t)size) {
        fclose(f);
        free(data);
        return NULL;
    }
    fclose(f);
    *len = (size_t)size;
    return data;
}

static int cmd_get(int argc, char **argv)
{
    static ratls_anchor_t anchors[8];
    const char *host = argv[2], *path = argv[4];
    int port = atoi(argv[3]), max = atoi(argv[5]), deadline_ms = atoi(argv[6]);
    int count = 0, rc, length = 0, i;
    struct sockaddr_in to;
    ratls_io_t io;
    bio_t bio;
    char *buf;

    if (!strcmp(argv[7], "unset"))
        now_mode = 2;
    else if (strcmp(argv[7], "sys")) {
        now_mode = 1;
        fixed_now = atoll(argv[7]);
    }
    for (i = 8; i < argc && count < 8; i++, count++)
        anchors[count].der = read_file(argv[i], &anchors[count].len);

    /* As on the console: no DNS, no connection while the clock is unset. */
    if (!raTlsClockOk(now_utc)) {
        printf("rc=%d\n", RATLS_ERR_CLOCK);
        return 0;
    }

    bio.sock = socket(AF_INET, SOCK_STREAM, 0);
    memset(&to, 0, sizeof(to));
    to.sin_family = AF_INET;
    to.sin_port = htons((unsigned short)port);
    to.sin_addr.s_addr = htonl(0x7F000001);
    if (getenv("RATLS_LIVE") != NULL) { /* manual check against the real host, never in CI */
        struct addrinfo hints, *res = NULL;
        memset(&hints, 0, sizeof(hints));
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        if (getaddrinfo(host, NULL, &hints, &res) != 0 || res == NULL) {
            printf("rc=%d\n", RATLS_ERR_NET);
            return 0;
        }
        to.sin_addr = ((struct sockaddr_in *)res->ai_addr)->sin_addr;
        freeaddrinfo(res);
    }
    if (connect(bio.sock, (struct sockaddr *)&to, sizeof(to)) != 0) {
        printf("rc=%d\n", RATLS_ERR_NET);
        return 0;
    }
    bio.deadline = clock() + (clock_t)deadline_ms * CLOCKS_PER_SEC / 1000;
    io.send = bio_send;
    io.recv = bio_recv;
    io.ctx = &bio;
    io.now_utc = now_utc;

    buf = malloc(max);
    rc = raTlsRequest(&io, host, path, "RiptOPL/host-test", anchors, count, buf, max, &length);
    close_sock(bio.sock);
    printf("rc=%d len=%d\n", rc, length);
    if (rc >= 0) {
        printf("--BODY--\n");
        fwrite(buf + rc, 1, (size_t)(length - rc), stdout);
    }
    return 0;
}

static int cmd_anchors(int argc, char **argv)
{
    int i, bad = 0;
    for (i = 2; i < argc; i++) {
        mbedtls_x509_crt crt;
        size_t len;
        unsigned char *der = read_file(argv[i], &len);
        mbedtls_x509_crt_init(&crt);
        if (der == NULL || mbedtls_x509_crt_parse_der(&crt, der, len) != 0) {
            printf("bad %s\n", argv[i]);
            bad++;
        }
        mbedtls_x509_crt_free(&crt);
        free(der);
    }
    printf("anchors bad=%d\n", bad);
    return 0;
}

static void print_random(void)
{
    unsigned char r[32];
    int i;
    if (psa_crypto_init() != PSA_SUCCESS || psa_generate_random(r, sizeof(r)) != PSA_SUCCESS) {
        printf("drbg-failed\n");
        return;
    }
    for (i = 0; i < 32; i++)
        printf("%02x", r[i]);
    printf("\n");
    mbedtls_psa_crypto_free();
}

int main(int argc, char **argv)
{
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc >= 8 && !strcmp(argv[1], "get"))
        return cmd_get(argc, argv);
    if (argc >= 3 && !strcmp(argv[1], "anchors"))
        return cmd_anchors(argc, argv);
    if (argc == 8 && !strcmp(argv[1], "rtc")) {
        printf("%lld\n", raTlsRtcToUtc(atoi(argv[2]), atoi(argv[3]), atoi(argv[4]), atoi(argv[5]), atoi(argv[6]), atoi(argv[7])));
        return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "drbg")) {
        print_random(); /* seeded, drawn, freed ... */
        print_random(); /* ... and seeded again in the same process */
        return 0;
    }
    fprintf(stderr, "usage: see the header\n");
    return 2;
}
