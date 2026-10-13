/* RetroAchievements edition: verified HTTPS GET for the game-ID lookup. See src/ratls.c
   (portable TLS + HTTP over callbacks) and src/ratls_ps2.c (DNS, TCP, clock, entropy, roots). */
#ifndef __RATLS_H__
#define __RATLS_H__

#include <stddef.h>

enum {
    RATLS_ERR_NET = -1,     /* no network, DNS failed, or connect refused */
    RATLS_ERR_CLOCK = -2,   /* console clock unset (before 2025): nothing was sent */
    RATLS_ERR_TLS = -3,     /* handshake or record failure */
    RATLS_ERR_CERT = -4,    /* certificate invalid, expired, untrusted or for another host */
    RATLS_ERR_HTTP = -5,    /* not 200, malformed, or larger than the buffer */
    RATLS_ERR_TIMEOUT = -6, /* the deadline passed */
    RATLS_ERR_MEM = -7,     /* out of memory, or the crypto library failed to start */
    RATLS_ERR_ARG = -8      /* bad arguments */
};

typedef struct
{
    int (*send)(void *ctx, const unsigned char *buf, size_t len); /* mbedTLS BIO contract */
    int (*recv)(void *ctx, unsigned char *buf, size_t len);       /* MBEDTLS_ERR_SSL_TIMEOUT at the deadline, 0 = closed */
    void *ctx;
    long long (*now_utc)(void); /* seconds since 1970 UTC, -1 = clock unset */
} ratls_io_t;

typedef struct
{
    const unsigned char *der;
    size_t len;
} ratls_anchor_t;

/* 1 when now_utc() gives a usable time. Callers check it before any DNS or connection. */
int raTlsClockOk(long long (*now_utc)(void));

/* One HTTPS GET over an already-connected io. Returns the body offset in buf (>= 0) with
   *length = total bytes in buf (headers + body, NUL-terminated), or RATLS_ERR_*. */
int raTlsRequest(const ratls_io_t *io, const char *host, const char *path, const char *user_agent,
                 const ratls_anchor_t *anchors, int anchor_count, char *buf, int max, int *length);

/* The console RTC (already decoded from BCD, full year) to seconds since 1970 UTC. */
long long raTlsRtcToUtc(int year, int month, int day, int hour, int minute, int second);

/* PS2: clock check, DNS, TCP and raTlsRequest with the six embedded roots, 8 s deadline.
   Refuses while a UDP transport owns the NIC. Same return convention as raTlsRequest. */
int raHttpsGet(const char *host, const char *path, char *buf, int max, int *length);

#endif
