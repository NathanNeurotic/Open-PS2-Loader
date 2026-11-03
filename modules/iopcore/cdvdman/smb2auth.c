/*
  smb2auth: MD4, MD5, SHA-256 and HMAC for smb2.c. See smb2auth.h.
  Licenced under Academic Free License version 3.0.
*/

#include "smb2auth.h"

#ifdef _IOP
#include "smsutils.h"
#else
#include <string.h>
#endif

#define ROL(x, n) (((x) << (n)) | ((x) >> (32 - (n))))
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static u32 ld32le(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static u32 ld32be(const u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | (u32)p[3];
}

//-------------------------------------------------------------------------
// MD4, RFC 1320 section 3.4.
static void md4_block(u32 *s, const u8 *blk)
{
    static const u8 r2[16] = {0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15};
    static const u8 r3[16] = {0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15};
    static const u8 sh[12] = {3, 7, 11, 19, 3, 5, 9, 13, 3, 9, 11, 15};
    u32 x[16], a = s[0], b = s[1], c = s[2], d = s[3], t;
    int i;

    for (i = 0; i < 16; i++)
        x[i] = ld32le(blk + i * 4);

    for (i = 0; i < 16; i++) {
        t = a + ((b & c) | (~b & d)) + x[i];
        a = d;
        d = c;
        c = b;
        b = ROL(t, sh[i & 3]);
    }
    for (i = 0; i < 16; i++) {
        t = a + ((b & c) | (b & d) | (c & d)) + x[r2[i]] + 0x5A827999;
        a = d;
        d = c;
        c = b;
        b = ROL(t, sh[4 + (i & 3)]);
    }
    for (i = 0; i < 16; i++) {
        t = a + (b ^ c ^ d) + x[r3[i]] + 0x6ED9EBA1;
        a = d;
        d = c;
        c = b;
        b = ROL(t, sh[8 + (i & 3)]);
    }

    s[0] += a;
    s[1] += b;
    s[2] += c;
    s[3] += d;
}

//-------------------------------------------------------------------------
// MD5, RFC 1321 section 3.4. T[i] = floor(abs(sin(i + 1)) * 2^32).
static const u32 md5_t[64] = {
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391};

static void md5_block(u32 *s, const u8 *blk)
{
    static const u8 sh[16] = {7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21};
    u32 x[16], a = s[0], b = s[1], c = s[2], d = s[3], f, t;
    int i, g;

    for (i = 0; i < 16; i++)
        x[i] = ld32le(blk + i * 4);

    for (i = 0; i < 64; i++) {
        switch (i >> 4) {
            case 0:
                f = (b & c) | (~b & d);
                g = i;
                break;
            case 1:
                f = (d & b) | (~d & c);
                g = (5 * i + 1) & 15;
                break;
            case 2:
                f = b ^ c ^ d;
                g = (3 * i + 5) & 15;
                break;
            default:
                f = c ^ (b | ~d);
                g = (7 * i) & 15;
                break;
        }
        t = d;
        d = c;
        c = b;
        b = b + ROL(a + f + md5_t[i] + x[g], sh[((i >> 4) << 2) | (i & 3)]);
        a = t;
    }

    s[0] += a;
    s[1] += b;
    s[2] += c;
    s[3] += d;
}

//-------------------------------------------------------------------------
// SHA-256, FIPS 180-4 section 6.2.
static const u32 sha256_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

static void sha256_block(u32 *s, const u8 *blk)
{
    // Static to keep 256 bytes off the caller's stack (smb2.c signs from MCEMU's small thread).
    // Safe because smb2.c serializes every request: no two hashes ever run at once.
    static u32 w[64];
    u32 a, b, c, d, e, f, g, h, t1, t2;
    int i;

    for (i = 0; i < 16; i++)
        w[i] = ld32be(blk + i * 4);
    for (; i < 64; i++) {
        u32 s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        u32 s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }

    a = s[0];
    b = s[1];
    c = s[2];
    d = s[3];
    e = s[4];
    f = s[5];
    g = s[6];
    h = s[7];

    for (i = 0; i < 64; i++) {
        t1 = h + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + sha256_k[i] + w[i];
        t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }

    s[0] += a;
    s[1] += b;
    s[2] += c;
    s[3] += d;
    s[4] += e;
    s[5] += f;
    s[6] += g;
    s[7] += h;
}

//-------------------------------------------------------------------------
static void hash_block(smb2auth_hash_t *h, const u8 *blk)
{
    if (h->kind == SMB2AUTH_SHA256)
        sha256_block(h->state, blk);
    else if (h->kind == SMB2AUTH_MD5)
        md5_block(h->state, blk);
    else
        md4_block(h->state, blk);
}

void smb2auth_init(smb2auth_hash_t *h, int kind)
{
    static const u32 iv_md[4] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476};
    static const u32 iv_sha256[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};

    h->kind = kind;
    h->count = 0;
    if (kind == SMB2AUTH_SHA256)
        memcpy(h->state, iv_sha256, sizeof(iv_sha256));
    else
        memcpy(h->state, iv_md, sizeof(iv_md));
}

void smb2auth_update(smb2auth_hash_t *h, const void *data, u32 len)
{
    const u8 *p = (const u8 *)data;
    u32 used = h->count & 63;

    h->count += len;
    while (len > 0) {
        u32 n = 64 - used;
        if (n > len)
            n = len;
        memcpy(&h->buf[used], p, n);
        used += n;
        p += n;
        len -= n;
        if (used == 64) {
            hash_block(h, h->buf);
            used = 0;
        }
    }
}

void smb2auth_final(smb2auth_hash_t *h, u8 *digest)
{
    u32 bits = h->count << 3, hi = h->count >> 29;
    u32 used = h->count & 63;
    int i, words;
    u8 lenbytes[8];

    // Pad with 0x80, zeros, then the 64-bit bit count: little-endian for MD4/MD5, big for SHA-256.
    h->buf[used++] = 0x80;
    if (used > 56) {
        memset(&h->buf[used], 0, 64 - used);
        hash_block(h, h->buf);
        used = 0;
    }
    memset(&h->buf[used], 0, 56 - used);
    for (i = 0; i < 4; i++) {
        lenbytes[i] = (u8)(bits >> (8 * i));
        lenbytes[4 + i] = (u8)(hi >> (8 * i));
    }
    if (h->kind == SMB2AUTH_SHA256) {
        for (i = 0; i < 8; i++)
            h->buf[56 + i] = lenbytes[7 - i];
    } else {
        memcpy(&h->buf[56], lenbytes, 8);
    }
    hash_block(h, h->buf);

    words = (h->kind == SMB2AUTH_SHA256) ? 8 : 4;
    for (i = 0; i < words; i++) {
        u32 v = h->state[i];
        if (h->kind == SMB2AUTH_SHA256) {
            digest[i * 4 + 0] = (u8)(v >> 24);
            digest[i * 4 + 1] = (u8)(v >> 16);
            digest[i * 4 + 2] = (u8)(v >> 8);
            digest[i * 4 + 3] = (u8)v;
        } else {
            digest[i * 4 + 0] = (u8)v;
            digest[i * 4 + 1] = (u8)(v >> 8);
            digest[i * 4 + 2] = (u8)(v >> 16);
            digest[i * 4 + 3] = (u8)(v >> 24);
        }
    }
}

//-------------------------------------------------------------------------
// HMAC, RFC 2104. Every key used by smb2.c is 16 bytes, well under the 64-byte block.
void smb2auth_hmac_init(smb2auth_hmac_t *m, int kind, const u8 *key, u32 keylen)
{
    u8 ikey[64];
    u32 i;

    memset(ikey, 0, sizeof(ikey));
    if (keylen > 64)
        keylen = 64;
    memcpy(ikey, key, keylen);
    for (i = 0; i < 64; i++) {
        m->okey[i] = ikey[i] ^ 0x5c;
        ikey[i] ^= 0x36;
    }
    smb2auth_init(&m->inner, kind);
    smb2auth_update(&m->inner, ikey, 64);
}

void smb2auth_hmac_update(smb2auth_hmac_t *m, const void *data, u32 len)
{
    smb2auth_update(&m->inner, data, len);
}

void smb2auth_hmac_final(smb2auth_hmac_t *m, u8 *digest)
{
    u8 ihash[32];
    smb2auth_hash_t outer;
    int kind = m->inner.kind;

    smb2auth_final(&m->inner, ihash);
    smb2auth_init(&outer, kind);
    smb2auth_update(&outer, m->okey, 64);
    smb2auth_update(&outer, ihash, (kind == SMB2AUTH_SHA256) ? 32 : 16);
    smb2auth_final(&outer, digest);
}
