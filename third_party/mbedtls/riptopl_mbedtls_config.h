/*
 * RiptOPL RetroAchievements edition: mbedTLS build configuration.
 *
 * One job: a TLS 1.3 / TLS 1.2 client that fetches one small HTTPS document
 * (retroachievements.org dorequest.php?r=gameid) with full certificate
 * verification against six embedded roots. Client only; no files, sockets,
 * threads or timers from mbedTLS -- RiptOPL supplies the BIO, the clock and
 * the entropy (src/ratls_ps2.c). RA builds only.
 */
#ifndef RIPTOPL_MBEDTLS_CONFIG_H
#define RIPTOPL_MBEDTLS_CONFIG_H

/* Platform: time and entropy come from RiptOPL. */
#define MBEDTLS_PLATFORM_C
#define MBEDTLS_HAVE_TIME
#define MBEDTLS_HAVE_TIME_DATE
#define MBEDTLS_PLATFORM_TIME_ALT    /* mbedtls_platform_set_time(): console RTC as UTC */
#define MBEDTLS_PLATFORM_MS_TIME_ALT /* mbedtls_ms_time() supplied by RiptOPL */
#define MBEDTLS_NO_PLATFORM_ENTROPY
#define MBEDTLS_ENTROPY_HARDWARE_ALT /* mbedtls_hardware_poll() supplied by RiptOPL */
#define MBEDTLS_ENTROPY_C
#define MBEDTLS_CTR_DRBG_C

/* TLS client, 1.3 and 1.2. */
#define MBEDTLS_SSL_TLS_C
#define MBEDTLS_SSL_CLI_C
#define MBEDTLS_SSL_PROTO_TLS1_2
#define MBEDTLS_SSL_PROTO_TLS1_3
#define MBEDTLS_SSL_TLS1_3_COMPATIBILITY_MODE
#define MBEDTLS_SSL_TLS1_3_KEY_EXCHANGE_MODE_EPHEMERAL_ENABLED
#define MBEDTLS_SSL_SERVER_NAME_INDICATION
#define MBEDTLS_SSL_KEEP_PEER_CERTIFICATE /* required by TLS 1.3 in 3.6 */
#define MBEDTLS_SSL_ENCRYPT_THEN_MAC
#define MBEDTLS_SSL_EXTENDED_MASTER_SECRET
#define MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED
#define MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED
#define MBEDTLS_SSL_IN_CONTENT_LEN  16384 /* a server may send full-size records */
#define MBEDTLS_SSL_OUT_CONTENT_LEN 4096  /* one GET request */

/* PSA crypto: required by TLS 1.3, used by TLS 1.2 too. No key storage. */
#define MBEDTLS_PSA_CRYPTO_C
#define MBEDTLS_USE_PSA_CRYPTO

/* Ciphers and hashes. */
#define MBEDTLS_CIPHER_C
#define MBEDTLS_AES_C
#define MBEDTLS_GCM_C
#define MBEDTLS_CHACHA20_C
#define MBEDTLS_POLY1305_C
#define MBEDTLS_CHACHAPOLY_C
#define MBEDTLS_MD_C
#define MBEDTLS_SHA224_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_SHA384_C
#define MBEDTLS_SHA512_C
#define MBEDTLS_HKDF_C

/* Key exchange and signatures. */
#define MBEDTLS_BIGNUM_C
#define MBEDTLS_ECP_C
#define MBEDTLS_ECDH_C
#define MBEDTLS_ECDSA_C
#define MBEDTLS_ECP_DP_SECP256R1_ENABLED
#define MBEDTLS_ECP_DP_SECP384R1_ENABLED
#define MBEDTLS_ECP_DP_CURVE25519_ENABLED
#define MBEDTLS_ECP_NIST_OPTIM
#define MBEDTLS_RSA_C
#define MBEDTLS_PKCS1_V15
#define MBEDTLS_PKCS1_V21

/* Certificates (DER only). */
#define MBEDTLS_ASN1_PARSE_C
#define MBEDTLS_ASN1_WRITE_C
#define MBEDTLS_OID_C
#define MBEDTLS_PK_C
#define MBEDTLS_PK_PARSE_C
#define MBEDTLS_X509_USE_C
#define MBEDTLS_X509_CRT_PARSE_C
#define MBEDTLS_X509_CHECK_KEY_USAGE
#define MBEDTLS_X509_CHECK_EXTENDED_KEY_USAGE
/* The PS2 libc defines AF_INET6 but has no inet_pton(): use mbedTLS's own
   parser for IP-address names in certificates (x509_crt.c). */
#define MBEDTLS_TEST_SW_INET_PTON

#endif /* RIPTOPL_MBEDTLS_CONFIG_H */
