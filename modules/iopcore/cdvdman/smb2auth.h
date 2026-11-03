/*
  smb2auth: the hashing smb2.c needs for NTLMv2 logon and SMB 2.x signing.

  MD4 (RFC 1320), MD5 (RFC 1321), SHA-256 (FIPS 180-4) and HMAC (RFC 2104), written for this
  module from the published specifications. Kept small on purpose: this code is resident in IOP
  RAM for the whole game. Licenced under Academic Free License version 3.0, like the rest of
  cdvdman.
*/

#ifndef __SMB2AUTH_H__
#define __SMB2AUTH_H__

#include <tamtypes.h>

typedef struct
{
    u32 state[8];
    u32 count; // bytes hashed so far (the inputs here are far below 4 GB)
    u8 buf[64];
    int kind; // SMB2AUTH_MD4 / SMB2AUTH_MD5 / SMB2AUTH_SHA256
} smb2auth_hash_t;

#define SMB2AUTH_MD4    0
#define SMB2AUTH_MD5    1
#define SMB2AUTH_SHA256 2

void smb2auth_init(smb2auth_hash_t *h, int kind);
void smb2auth_update(smb2auth_hash_t *h, const void *data, u32 len);
void smb2auth_final(smb2auth_hash_t *h, u8 *digest); // 16 bytes (MD4/MD5) or 32 (SHA-256)

typedef struct
{
    smb2auth_hash_t inner;
    u8 okey[64];
} smb2auth_hmac_t;

// HMAC over MD5 or SHA-256. Keys longer than 64 bytes are not supported (none are used here).
void smb2auth_hmac_init(smb2auth_hmac_t *m, int kind, const u8 *key, u32 keylen);
void smb2auth_hmac_update(smb2auth_hmac_t *m, const void *data, u32 len);
void smb2auth_hmac_final(smb2auth_hmac_t *m, u8 *digest);

#endif
