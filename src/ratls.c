/*
  ratls.c -- the portable half of the RetroAchievements HTTPS lookup.

  ORBIT asks retroachievements.org for a game's ID by hash over HTTPS; the RA
  edition does the same. This file runs one TLS 1.3 / 1.2 session (vendored
  mbedTLS, third_party/mbedtls) and one HTTP GET over callbacks the caller
  supplies, so it builds unchanged on the host for tests. Sockets, DNS, the
  console clock, entropy and the embedded roots are in ratls_ps2.c.

  Certificates are always verified (VERIFY_REQUIRED, SNI, host name) against
  the anchors passed in; a clock that is not set fails closed before anything
  is sent. A body is returned only when it arrived whole: Content-Length met,
  chunked encoding terminated, or the server closed a body without either.
*/

#include "include/ratls.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mbedtls/platform_time.h"
#include "mbedtls/psa_util.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"

#define RATLS_REQUEST_MAX 512

static long long (*g_now)(void);
static int g_psaReady;

/* The PS2 RTC keeps Japan time (ps2sdk's ps2time() in ee/rpc/cdvd/src/scmd.c converts it with a
   -9 h offset), so UTC = RTC - 9 h. */
#define RATLS_RTC_ZONE_SECONDS (9 * 60 * 60)

long long raTlsRtcToUtc(int year, int month, int day, int hour, int minute, int second)
{
    /* Days from 1970-01-01 (Howard Hinnant's days_from_civil). */
    int y = year - (month <= 2);
    long long era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (153u * (unsigned)(month + (month > 2 ? -3 : 9)) + 2u) / 5u + (unsigned)day - 1u;
    unsigned doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
    long long days = era * 146097 + (long long)doe - 719468;

    return days * 86400 + hour * 3600 + minute * 60 + second - RATLS_RTC_ZONE_SECONDS;
}

int raTlsClockOk(long long (*now_utc)(void))
{
    return now_utc != NULL && now_utc() >= 0;
}

static mbedtls_time_t ratlsTime(mbedtls_time_t *timer)
{
    mbedtls_time_t now = (mbedtls_time_t)(g_now != NULL ? g_now() : -1);
    if (timer != NULL)
        *timer = now;
    return now;
}

/* Header end (index of the body) or -1. */
static int headerEnd(const char *buf, int len)
{
    int i;
    for (i = 0; i + 3 < len; i++)
        if (buf[i] == '\r' && buf[i + 1] == '\n' && buf[i + 2] == '\r' && buf[i + 3] == '\n')
            return i + 4;
    return -1;
}

/* Value of a header (case-insensitive name) within the header block, or NULL. */
static const char *headerValue(const char *buf, int bodyAt, const char *name)
{
    size_t n = strlen(name);
    const char *line = strstr(buf, "\r\n");

    while (line != NULL && line + 2 < buf + bodyAt) {
        const char *p = line + 2;
        size_t i;
        for (i = 0; i < n && p[i] && (p[i] | 0x20) == (name[i] | 0x20); i++)
            ;
        if (i == n && p[n] == ':') {
            p += n + 1;
            while (*p == ' ' || *p == '\t')
                p++;
            return p;
        }
        line = strstr(p, "\r\n");
    }
    return NULL;
}

/* De-chunks the body in place. Returns the new body length, or -1 if malformed/incomplete. */
/* Walks the chunk headers. With write set, the data is packed down in place and its length returned.
 * Without it nothing is written, and 1 means the terminating chunk and the trailer's blank line have
 * arrived, 0 that more is needed. -1 means malformed (or, when writing, cut short). */
static int walkChunks(char *body, int len, int write)
{
    int in = 0, out = 0;

    for (;;) {
        char *end;
        long size;
        int eol;

        for (eol = in; eol + 1 < len && !(body[eol] == '\r' && body[eol + 1] == '\n'); eol++)
            ;
        if (eol + 1 >= len)
            return write ? -1 : 0;
        size = strtol(body + in, &end, 16);
        if (end == body + in || end > body + eol || size < 0)
            return -1;
        in = eol + 2;
        if (size == 0) {
            if (write)
                return out;
            for (;;) { /* optional trailer lines, then the blank line */
                for (eol = in; eol + 1 < len && !(body[eol] == '\r' && body[eol + 1] == '\n'); eol++)
                    ;
                if (eol + 1 >= len)
                    return 0;
                if (eol == in)
                    return 1;
                in = eol + 2;
            }
        }
        if (size > len - in - 2)
            return write ? -1 : 0;
        if (body[in + size] != '\r' || body[in + size + 1] != '\n')
            return -1;
        if (write)
            memmove(body + out, body + in, (size_t)size);
        out += (int)size;
        in += (int)size + 2;
    }
}

/* Whether everything has arrived: by Content-Length, or by walking the chunks to the terminator
 * (a suffix test is fooled by chunk data that itself ends in "0\r\n", #1062). */
static int responseComplete(const char *buf, int len)
{
    int bodyAt = headerEnd(buf, len);
    const char *value;

    if (bodyAt < 0)
        return 0;
    if ((value = headerValue(buf, bodyAt, "Content-Length")) != NULL)
        return len - bodyAt >= atoi(value);
    if ((value = headerValue(buf, bodyAt, "Transfer-Encoding")) != NULL && !strncmp(value, "chunked", 7))
        return walkChunks((char *)buf + bodyAt, len - bodyAt, 0) == 1;
    return 0; /* delimited by the server closing */
}

static int finishResponse(char *buf, int len, int *length)
{
    int status, bodyAt = headerEnd(buf, len);
    const char *value;

    if (bodyAt < 0 || sscanf(buf, "HTTP/%*d.%*d %d", &status) != 1 || status != 200)
        return RATLS_ERR_HTTP;
    if ((value = headerValue(buf, bodyAt, "Transfer-Encoding")) != NULL && !strncmp(value, "chunked", 7)) {
        int body;
        if (walkChunks(buf + bodyAt, len - bodyAt, 0) != 1)
            return RATLS_ERR_HTTP; /* closed before the terminator's blank line */
        body = walkChunks(buf + bodyAt, len - bodyAt, 1);
        if (body < 0)
            return RATLS_ERR_HTTP;
        len = bodyAt + body;
    } else if ((value = headerValue(buf, bodyAt, "Content-Length")) != NULL) {
        int want = atoi(value);
        if (want < 0 || len - bodyAt < want)
            return RATLS_ERR_HTTP; /* cut short: never parse a partial document */
        len = bodyAt + want;
    }
    buf[len] = '\0';
    *length = len;
    return bodyAt;
}

static int mapError(int rc, const mbedtls_ssl_context *ssl)
{
    uint32_t flags;

    if (rc == MBEDTLS_ERR_SSL_TIMEOUT)
        return RATLS_ERR_TIMEOUT;
    if (rc == MBEDTLS_ERR_SSL_ALLOC_FAILED)
        return RATLS_ERR_MEM;
    flags = mbedtls_ssl_get_verify_result(ssl);
    if (rc == MBEDTLS_ERR_X509_CERT_VERIFY_FAILED || (flags != 0 && flags != (uint32_t)-1))
        return RATLS_ERR_CERT;
    return RATLS_ERR_TLS;
}

int raTlsRequest(const ratls_io_t *io, const char *host, const char *path, const char *user_agent,
                 const ratls_anchor_t *anchors, int anchor_count, char *buf, int max, int *length)
{
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config conf;
    mbedtls_x509_crt ca;
    char request[RATLS_REQUEST_MAX];
    int rc, i, len = 0, result, sent = 0, reqlen;

    if (length != NULL)
        *length = 0;
    if (io == NULL || io->send == NULL || io->recv == NULL || host == NULL || path == NULL || user_agent == NULL ||
        anchors == NULL || anchor_count <= 0 || buf == NULL || max < 64 || length == NULL)
        return RATLS_ERR_ARG;
    if (!raTlsClockOk(io->now_utc))
        return RATLS_ERR_CLOCK;
    reqlen = snprintf(request, sizeof(request),
                      "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
                      path, host, user_agent);
    if (reqlen <= 0 || reqlen >= (int)sizeof(request))
        return RATLS_ERR_ARG;

    g_now = io->now_utc;
    mbedtls_platform_set_time(ratlsTime);
    if (!g_psaReady) {
        if (psa_crypto_init() != PSA_SUCCESS)
            return RATLS_ERR_MEM;
        g_psaReady = 1;
    }

    mbedtls_ssl_init(&ssl);
    mbedtls_ssl_config_init(&conf);
    mbedtls_x509_crt_init(&ca);

    result = RATLS_ERR_TLS;
    for (i = 0; i < anchor_count; i++)
        if (mbedtls_x509_crt_parse_der(&ca, anchors[i].der, anchors[i].len) != 0)
            goto out; /* a broken anchor is a build defect, never "trust anything" */

    if (mbedtls_ssl_config_defaults(&conf, MBEDTLS_SSL_IS_CLIENT, MBEDTLS_SSL_TRANSPORT_STREAM,
                                    MBEDTLS_SSL_PRESET_DEFAULT) != 0)
        goto out;
    mbedtls_ssl_conf_authmode(&conf, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(&conf, &ca, NULL);
    mbedtls_ssl_conf_rng(&conf, mbedtls_psa_get_random, MBEDTLS_PSA_RANDOM_STATE);
    if ((rc = mbedtls_ssl_setup(&ssl, &conf)) != 0 || (rc = mbedtls_ssl_set_hostname(&ssl, host)) != 0) {
        result = rc == MBEDTLS_ERR_SSL_ALLOC_FAILED ? RATLS_ERR_MEM : RATLS_ERR_TLS;
        goto out;
    }
    mbedtls_ssl_set_bio(&ssl, io->ctx, io->send, io->recv, NULL);

    while ((rc = mbedtls_ssl_handshake(&ssl)) != 0) {
        if (rc != MBEDTLS_ERR_SSL_WANT_READ && rc != MBEDTLS_ERR_SSL_WANT_WRITE) {
            result = mapError(rc, &ssl);
            goto out;
        }
    }

    while (sent < reqlen) {
        rc = mbedtls_ssl_write(&ssl, (const unsigned char *)request + sent, (size_t)(reqlen - sent));
        if (rc == MBEDTLS_ERR_SSL_WANT_READ || rc == MBEDTLS_ERR_SSL_WANT_WRITE)
            continue;
        if (rc <= 0) {
            result = mapError(rc, &ssl);
            goto out;
        }
        sent += rc;
    }

    for (;;) {
        if (len >= max - 1) {
            result = RATLS_ERR_HTTP; /* larger than the buffer */
            goto out;
        }
        rc = mbedtls_ssl_read(&ssl, (unsigned char *)buf + len, (size_t)(max - 1 - len));
        if (rc > 0) {
            len += rc;
            buf[len] = '\0';
            if (responseComplete(buf, len))
                break;
            continue;
        }
        if (rc == MBEDTLS_ERR_SSL_WANT_READ || rc == MBEDTLS_ERR_SSL_WANT_WRITE ||
            rc == MBEDTLS_ERR_SSL_RECEIVED_NEW_SESSION_TICKET)
            continue;
        if (rc == 0 || rc == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY)
            break; /* the server closed: whatever arrived is complete or rejected below */
        result = mapError(rc, &ssl);
        goto out;
    }
    buf[len] = '\0';
    result = finishResponse(buf, len, length);
    mbedtls_ssl_close_notify(&ssl);

out:
    mbedtls_ssl_free(&ssl);
    mbedtls_ssl_config_free(&conf);
    mbedtls_x509_crt_free(&ca);
    return result;
}
