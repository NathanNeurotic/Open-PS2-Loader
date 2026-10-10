/* Caduceus CADQ2/CADR2 session bridge; telemetry remains xeRAbora's protocol.
   Wire reference: Rian6/caduceus electron/caduceus-ra-bridge.ts. */
#ifndef RA_CLIENT_H
#define RA_CLIENT_H

#define RA_CADUCEUS_PORT  18197
#define RA_PROBE_HASH     "00000000000000000000000000000000"
#define RA_CADUCEUS_PROBE "CADQ2 " RA_PROBE_HASH

/* No libc imports: this header is also built into the IOP module. */
static inline int raClientStarts(const char *text, const char *prefix)
{
    while (*prefix) {
        if (*text++ != *prefix++)
            return 0;
    }
    return 1;
}

/* A catalog miss is independent of login state. The engine's subsequent
   watch-list query remains authoritative for the game's achievements. */
static inline int raCaduceusSessionReply(const char *reply, const char *hash)
{
    const char *body;
    int ready, i;

    if (!raClientStarts(reply, "CADR2 "))
        return -3;
    for (i = 0; i < 32; i++) {
        if (!hash[i] || !reply[6 + i] || reply[6 + i] != hash[i])
            return -3;
    }
    if (hash[32] || reply[38] != ' ')
        return -3;
    body = reply + 39;
    if (raClientStarts(body, "READY ")) {
        ready = 1;
        body += 6;
    } else if (raClientStarts(body, "OFFLINE ")) {
        ready = 0;
        body += 8;
    } else {
        return -3;
    }
    if (!(raClientStarts(body, "NO") && body[2] == '\0') &&
        !(raClientStarts(body, "UNKNOWN") && body[7] == '\0') &&
        !raClientStarts(body, "OK "))
        return -3;
    return ready ? 0 : -9;
}

#endif
