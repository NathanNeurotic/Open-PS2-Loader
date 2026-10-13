# RA HTTPS Game-ID Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Xerabora mode, look up a game's RetroAchievements ID over HTTPS exactly as ORBIT does: `GET https://retroachievements.org/dorequest.php?r=gameid&m=<hash>`. The browser then shows the full list for any game, including a never-played one, with #926's library-title match kept as the offline fallback.

**Architecture:** mbedTLS 3.6.7 (Apache-2.0) is vendored under `third_party/mbedtls` and compiled into **RA builds only** with a minimal config. The code splits into three parts:
- `src/ratls.c` is portable: it runs one TLS session plus an HTTP GET over caller-supplied I/O callbacks, and the host tests use it.
- `src/ratls_ps2.c` holds everything PS2-specific: DNS, TCP, `MSG_DONTWAIT` reads, the RTC→UTC clock, entropy and the embedded roots.
- `src/achievements.c` parses `{"Success":true,"GameID":N}` and puts the lookup ahead of #926's title match.

**Tech Stack:** C (EE, ps2sdk lwIP `ps2ips` + libcglue `gethostbyname`), mbedTLS 3.6.7 with PSA crypto (required by TLS 1.3), Makefile `BIN2C`, Python 3 + `openssl` CLI host tests in CI.

**Spec:** `docs/superpowers/specs/2026-10-12-ra-https-gameid-design.md`

## Global Constraints

- **No GPL code.** mbedTLS is taken under **Apache-2.0** (it's dual-licensed; README states the choice). wolfSSL and BearSSL are not used.
- Pin **`mbedtls-3.6.7`**, vendored from the **release archive** (`mbedtls-3.6.7.tar.bz2` on GitHub Releases), not the git tag. The archive carries the generated sources (`psa_crypto_driver_wrappers*.h`, `error.c`, `version_features.c`, `ssl_debug_helpers_generated.c`) that the tag doesn't. Record the archive SHA-256 in `third_party/mbedtls/README.md` and check it against the release notes. Vendor only `library/`, `include/`, `LICENSE`, and `NOTICE` if present.
- **RA builds only:** every object, `-I`, and `-D` sits under `ifeq ($(RETROACHIEVEMENTS),1)`. The standard and Korium ELFs must contain no `mbedtls_`/`psa_` symbols and no `retroachievements.org` text.
- TLS 1.3 **and** 1.2, client only. Key exchange is ECDHE on X25519/secp256r1/secp384r1. Signatures are ECDSA plus RSA (PKCS#1 v1.5 and PSS). AES-GCM, ChaCha20-Poly1305, SHA-256/384. SNI and hostname verification are **always on**, with `MBEDTLS_SSL_VERIFY_REQUIRED`.
- **Trust anchors:** GTS Root R1, R2, R3, R4 and ISRG Root X1, X2 only. Each DER is fetched from its issuer (`https://pki.goog/repo/certs/gtsr{1..4}.der`, `https://letsencrypt.org/certs/isrgrootx1.der`, `https://letsencrypt.org/certs/isrg-root-x2.der`), its SHA-256 fingerprint compared with the issuer's published value, and both recorded in `third_party/ca-roots/README.md` with the expiry.
- **Time:** console RTC converted to UTC. A year < **2025** means the clock is unset: fail closed **before** connecting. A certificate is never accepted unchecked.
- **Entropy:** no hardware RNG. Seed from the EE COP0 Count register (sampled across thread switches), `clock()`, the CDVD clock bytes and network arrival timing. The source is `mbedtls_hardware_poll` (`MBEDTLS_ENTROPY_HARDWARE_ALT`), mixed by mbedTLS's entropy accumulator.
- Request header `User-Agent: RiptOPL/<OPL_VERSION>` (the `OPL_VERSION` macro is already in `EE_CFLAGS`).
- Overall deadline **8000 ms** per request, the same as #926's `RA_HTTP_MS`. Reads go through a 64-byte-aligned bounce buffer of at most `RA_RECV_MAX` (992) bytes with `RA_MSG_DONTWAIT` (0x08) (`fcntl(O_NONBLOCK)` has no effect on this stack).
- Runs on the I/O worker only, and is refused while `raNetNicReserved()`.
- `GameID 0` → `ACH_UNSUPPORTED`. Any HTTPS failure → #926 library fallback, which never makes things worse than #926.
- New language labels are appended at the end of `lng_tmpl/_base.yml`.
- Releases stay in sync: only RA features differ. The RA package ships the Apache-2.0 text.

## Review Focus

1. **A hash that isn't 32 lowercase hex characters** reaches the URL builder (a corrupted or partial hash): refuse without sending anything, so nothing can be injected into the request line. Pinned in Task 3 (`gameid_rejects_bad_hash`).
2. **Server answers `Transfer-Encoding: chunked` or with no `Content-Length`** (dorequest.php behind a CDN): the body must still be read whole or refused, never parsed as a partial document. Pinned in Task 2 (`chunked_body`, `no_length_until_close`).
3. **Console clock set but wrong by a few hours** (JST vs UTC confusion): a certificate issued a few hours ago would fail. The RTC offset is pinned by a test against ps2sdk's own conversion (Task 2 Step 1, `rtc_to_utc`).
4. **DNS fails or no default route** (LAN-only setups, the common case for xeRAbora users): the fallback must kick in within the deadline and the browser behave exactly as #926. Pinned in Task 3 (`https_failure_falls_back`).
5. **ELF growth pushes the RA menu ELF past what the console loads comfortably:** measure and report it. Task 1 adds a size print to CI and states the delta in the PR body. There's no hard gate (none exists for other features), but the reviewer sees it.

---

### Task 1: vendor mbedTLS and build it into RA builds only

**Files:**
- Create: `third_party/mbedtls/{library/,include/,LICENSE,README.md}` from the 3.6.7 release archive
- Create: `third_party/mbedtls/riptopl_mbedtls_config.h`
- Create: `third_party/ca-roots/{gtsr1,gtsr2,gtsr3,gtsr4,isrgrootx1,isrg-root-x2}.der` and `third_party/ca-roots/README.md`
- Modify: `Makefile` (inside `ifeq ($(RETROACHIEVEMENTS),1)` blocks only)
- Modify: `CREDITS` (Mbed TLS, Apache-2.0, link)
- Modify: `.github/workflows/flavours.yml`: extend the leak check, add a size print, and add the host smoke test
- Create: `.github/scripts/test_mbedtls_vendor.py`

**Interfaces:**
- Produces:
  - Makefile variable `MBEDTLS_DIR = third_party/mbedtls`.
  - Objects `$(EE_OBJS_DIR)mbedtls/%.o`, built from every `$(MBEDTLS_DIR)/library/*.c`. Modules the config disables compile to nothing.
  - Flags: `EE_INCS += -I$(MBEDTLS_DIR)/include -I$(MBEDTLS_DIR)` and `EE_CFLAGS += -DMBEDTLS_CONFIG_FILE=\"riptopl_mbedtls_config.h\"`, both RA-only.
  - `BIN2C` sources `$(EE_ASM_DIR)ratls_root_<name>.c` with symbols `ratls_root_<name>` / `size_ratls_root_<name>` for `gtsr1 gtsr2 gtsr3 gtsr4 isrgrootx1 isrgrootx2`, added to `EE_OBJS` RA-only. Task 2 consumes them.
- Config decisions (`riptopl_mbedtls_config.h`):
  - Protocol: `MBEDTLS_SSL_CLI_C`, `MBEDTLS_SSL_PROTO_TLS1_2`, `MBEDTLS_SSL_PROTO_TLS1_3`, `MBEDTLS_SSL_TLS1_3_COMPATIBILITY_MODE`, `MBEDTLS_SSL_TLS1_3_KEY_EXCHANGE_MODE_EPHEMERAL_ENABLED`, `MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED`, `MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED`, `MBEDTLS_SSL_SERVER_NAME_INDICATION`.
  - PSA: `MBEDTLS_PSA_CRYPTO_C`, `MBEDTLS_USE_PSA_CRYPTO`.
  - Entropy and time: `MBEDTLS_ENTROPY_C`, `MBEDTLS_CTR_DRBG_C`, `MBEDTLS_NO_PLATFORM_ENTROPY`, `MBEDTLS_ENTROPY_HARDWARE_ALT`, `MBEDTLS_HAVE_TIME`, `MBEDTLS_HAVE_TIME_DATE`, `MBEDTLS_PLATFORM_C`, `MBEDTLS_PLATFORM_TIME_ALT`.
  - Certificates: the X.509 CRT parse and verify set (`MBEDTLS_X509_CRT_PARSE_C`, `MBEDTLS_X509_USE_C`, `MBEDTLS_PK_C`, `MBEDTLS_PK_PARSE_C`, `MBEDTLS_ASN1_PARSE_C`, `MBEDTLS_ASN1_WRITE_C`, `MBEDTLS_OID_C`).
  - Algorithms: ECC curves `SECP256R1`, `SECP384R1`, `CURVE25519` (`MBEDTLS_ECP_C`, `MBEDTLS_ECDH_C`, `MBEDTLS_ECDSA_C`, `MBEDTLS_BIGNUM_C`); `MBEDTLS_RSA_C`, `MBEDTLS_PKCS1_V15`, `MBEDTLS_PKCS1_V21`; `MBEDTLS_AES_C`, `MBEDTLS_GCM_C`, `MBEDTLS_CHACHA20_C`, `MBEDTLS_POLY1305_C`, `MBEDTLS_CHACHAPOLY_C`, `MBEDTLS_MD_C`, `MBEDTLS_SHA224_C`, `MBEDTLS_SHA256_C`, `MBEDTLS_SHA384_C`, `MBEDTLS_SHA512_C`, `MBEDTLS_HKDF_C`, `MBEDTLS_CIPHER_C`.
  - Records: `MBEDTLS_SSL_IN_CONTENT_LEN 16384`, `MBEDTLS_SSL_OUT_CONTENT_LEN 4096`.
  - **Off:** server, PSK, renegotiation, `MBEDTLS_FS_IO`, threading, `MBEDTLS_NET_C` (we supply BIO), `MBEDTLS_TIMING_C`, debug.
  - End the config with `#include "mbedtls/check_config.h"`-compatible settings. 3.6 runs the check automatically, so a broken combination fails the compile.

- [ ] **Step 1: Write the failing test** `test_mbedtls_vendor.py`:
  - `third_party/mbedtls/README.md` names `3.6.7`, a 64-hex SHA-256 and `Apache-2.0`;
  - `LICENSE` exists, and `library/psa_crypto_driver_wrappers_no_static.c` exists (proof that the release archive was used, not the tag);
  - the README contains the exact sentence `Used under the Apache-2.0 licence.`, and every `library/*.c` has an `SPDX-License-Identifier` line that includes `Apache-2.0`;
  - every `Makefile` line matching `mbedtls|ratls_root_|ratls|MBEDTLS_DIR` **case-insensitively** (so `-DMBEDTLS_CONFIG_FILE`, `-I$(MBEDTLS_DIR)…`, the object lists and the `BIN2C` rules all count) sits between an `ifeq ($(RETROACHIEVEMENTS),1)` and its `endif` (scan the line ranges, nested conditionals included);
  - all six DER files exist, and each SHA-256 equals an **issuer-published fingerprint pinned in the test source itself** (a dict of six values, copied from pki.goog and letsencrypt.org when vendoring); the README must list the same values, but the README alone never satisfies the check;
  - `riptopl_mbedtls_config.h` defines `MBEDTLS_SSL_PROTO_TLS1_3`, `MBEDTLS_SSL_PROTO_TLS1_2`, `MBEDTLS_ENTROPY_HARDWARE_ALT` and `MBEDTLS_PLATFORM_TIME_ALT`, and does **not** define `MBEDTLS_SSL_SRV_C`, `MBEDTLS_FS_IO` or `MBEDTLS_SSL_RENEGOTIATION`.

- [ ] **Step 2: Run it and confirm it fails**

  Run: `python3 .github/scripts/test_mbedtls_vendor.py`
  Expected: FAIL, "third_party/mbedtls/README.md missing".

- [ ] **Step 3: Vendor the sources:** download the archive, verify the SHA-256, and copy `library/`, `include/` and `LICENSE`. Fetch the six roots and verify their fingerprints. Write both READMEs, the config, and the Makefile rules. Add the CREDITS line.

- [ ] **Step 4: Host compile smoke.** In `flavours.yml`, compile every `third_party/mbedtls/library/*.c` with host `cc -c -I third_party/mbedtls/include -I third_party/mbedtls -DMBEDTLS_CONFIG_FILE='"riptopl_mbedtls_config.h"'`. This catches config-check errors without the PS2 toolchain. Task 2 reuses the objects.

- [ ] **Step 5: CI checks.**
  - Add `mbedtls_[A-Za-z0-9_]*|psa_[A-Za-z0-9_]*` to the standard-ELF symbol regex, and `retroachievements\.org` to the text grep (flavours.yml ~line 396).
  - In the RA branch, add `grep -q ' mbedtls_ssl_handshake$' menu-symbols.txt`. This line lands in Task 2, when the first caller exists; until then the linker drops the symbol.
  - Print `stat -c %s opl.elf` for each flavour.

- [ ] **Step 6: Run the test and confirm it passes**

  Run: `python3 .github/scripts/test_mbedtls_vendor.py`
  Expected: `PASS: mbedTLS 3.6.7 vendored (Apache-2.0), RA-only, six pinned roots`.

- [ ] **Step 7: Commit**

  ```bash
  git add third_party/mbedtls third_party/ca-roots Makefile CREDITS .github/scripts/test_mbedtls_vendor.py .github/workflows/flavours.yml
  git commit -m "build(ra): vendor mbedTLS 3.6.7 (Apache-2.0) and six CA roots for RA builds"
  ```

---

### Task 2: `ratls`: an HTTPS GET with verified TLS

**Files:**
- Create: `include/ratls.h`, `src/ratls.c` (portable), `src/ratls_ps2.c` (PS2 platform)
- Modify: `Makefile`: add `ratls.o ratls_ps2.o` to the RA `FRONTEND_OBJS` line with `rawatch.o ranet.o …`
- Create: `tests/ratls/host_main.c` (host driver), `.github/scripts/test_ratls_host.py`
- Modify: `.github/workflows/flavours.yml`: run the host test, and add the RA `mbedtls_ssl_handshake` symbol check deferred from Task 1

**Interfaces:**
- Consumes: Task 1's objects, flags and `ratls_root_*` symbols.
- Produces (`include/ratls.h`):
  ```c
  enum { RATLS_ERR_NET = -1, RATLS_ERR_CLOCK = -2, RATLS_ERR_TLS = -3, RATLS_ERR_CERT = -4,
         RATLS_ERR_HTTP = -5, RATLS_ERR_TIMEOUT = -6, RATLS_ERR_MEM = -7, RATLS_ERR_ARG = -8 };
  typedef struct {
      int (*send)(void *ctx, const unsigned char *buf, size_t len); /* mbedTLS BIO contract */
      int (*recv)(void *ctx, unsigned char *buf, size_t len);       /* MBEDTLS_ERR_SSL_TIMEOUT at the deadline */
      void *ctx;
      long long (*now_utc)(void);                                   /* seconds since 1970, -1 = clock unset */
  } ratls_io_t;
  typedef struct { const unsigned char *der; size_t len; } ratls_anchor_t;
  /* Returns the body offset in buf (>= 0) with *length = total bytes in buf, or RATLS_ERR_*. */
  int raTlsRequest(const ratls_io_t *io, const char *host, const char *path, const char *user_agent,
                   const ratls_anchor_t *anchors, int anchor_count, char *buf, int max, int *length);
  /* PS2: DNS + TCP + raTlsRequest with the six embedded roots; refuses while raNetNicReserved(). */
  int raHttpsGet(const char *host, const char *path, char *buf, int max, int *length);
  long long raTlsRtcToUtc(int year, int month, int day, int hour, int minute, int second); /* inputs already decoded from BCD; RTC zone → UTC */
  ```
- `raTlsRequest` behaviour decisions:
  - `int raTlsClockOk(long long (*now_utc)(void))` (portable, in `ratls.c`) returns 0 when the clock is unset. `raHttpsGet` calls it **first, before `gethostbyname`**, and returns `RATLS_ERR_CLOCK`; the host driver calls it before connecting, the same way. `raTlsRequest` also refuses with `RATLS_ERR_CLOCK` before any `send`, as a second guard.
  - Error mapping:
    - certificate verify flags ≠ 0 → `RATLS_ERR_CERT`, logged with `mbedtls_x509_crt_verify_info`;
    - `MBEDTLS_ERR_SSL_TIMEOUT` → `RATLS_ERR_TIMEOUT`;
    - other handshake errors → `RATLS_ERR_TLS`.
  - Request text: `GET <path> HTTP/1.1\r\nHost: <host>\r\nUser-Agent: <ua>\r\nAccept: application/json\r\nConnection: close\r\n\r\n`.
  - Response:
    - Status must be `200`, else `RATLS_ERR_HTTP`.
    - Body framing: `Content-Length`, **or** `Transfer-Encoding: chunked` (de-chunked in place), **or** read-until-close when neither is present. `close_notify` and a peer close are both a clean end.
    - A body that would overflow `max - 1` → `RATLS_ERR_HTTP`, never a partial result.
    - NUL-terminate.
  - Free every mbedTLS context on every return path.
- `ratls_ps2.c` decisions:
  - `mbedtls_platform_set_time()` points at a wrapper over `raTlsRtcToUtc(sceCdReadClock…)`, returning -1 if the year < 2025.
  - **RTC zone:** before writing `raTlsRtcToUtc`, read ps2sdk's libcglue time conversion. `grep -rn "JST\|9 \* 60 \* 60\|32400" $PS2SDK/../ee/libcglue` in the ps2sdk sources used by the CI image (`ps2dev/ps2dev` tag in `flavours.yml`). Mirror its offset exactly and cite the file and line in a comment. If libcglue's `time()` already returns UTC from the RTC, use `time()` instead and drop the manual conversion. Record the decision in the test.
  - `mbedtls_hardware_poll(void *data, unsigned char *out, size_t len, size_t *olen)`: per output byte, mix the low byte of `mfc0 $9` (COP0 Count) taken before and after a `DelayThread(0)`, XORed with `clock()`. Once per call, XOR in the CDVD clock bytes. Report `*olen = len`.
  - DNS via `gethostbyname`. TCP `socket/connect/send` follows `raNetHttpGet`'s pattern. `recv` callback: loop `recv(sock, bounce64, min(len, RA_RECV_MAX), RA_MSG_DONTWAIT)` with `DelayThread(RA_POLL_MS*1000)` until there is data, a close (return 0), or the 8000 ms deadline (`MBEDTLS_ERR_SSL_TIMEOUT`).
  - Call `psa_crypto_init()` once, lazily.

- [ ] **Step 1: Write the failing host test** `test_ratls_host.py`. The driver is `tests/ratls/host_main.c` (POSIX sockets, `poll()` deadline, `/dev/urandom` for `mbedtls_hardware_poll`, `now_utc` = `time(NULL)` or -1 by flag). It's compiled with `src/ratls.c` and Task 1's host objects. The Python side uses `openssl` CLI to make a test CA, a leaf for `ra.test`, an expired leaf, and a leaf for `other.test`, with **ECDSA P-256** keys (needed for the TLS 1.2 ECDHE-ECDSA suite), then serves with `ssl.SSLContext`, mapping `ra.test` to 127.0.0.1 through the driver's address argument. Cases:
  - `tls13_get`: TLS 1.3-only server, `Content-Length` JSON body → exit 0, and the body printed equals the served bytes.
  - `tls12_get`: TLS 1.2-only server (`ECDHE-ECDSA-AES128-GCM-SHA256`) → same.
  - `chunked_body`: chunked response → de-chunked body equal.
  - `no_length_until_close`: no length, then close → whole body.
  - `oversize_refused`: body larger than `max` → `RATLS_ERR_HTTP` (-5).
  - `wrong_host`: leaf for `other.test` → `RATLS_ERR_CERT` (-4).
  - `expired`: expired leaf → -4.
  - `untrusted_root`: the anchor list holds only an unrelated CA → -4.
  - `clock_unset`: `now_utc` returns -1 → -2, and the server **accepted no connection at all**. A Python static check also asserts that `raTlsClockOk(` precedes `gethostbyname(` in `raHttpsGet`.
  - `drbg_distinct`: seed and draw 32 bytes twice in one process and once in a second process run → all three outputs differ (spec §3 entropy test).
  - `stall_deadline`: the server accepts and sends nothing, with a 1000 ms driver deadline → -6 within 1500 ms.
  - `http_404`: status 404 → -5.
  - `anchors_parse`: all six real DERs from `third_party/ca-roots` parse with `mbedtls_x509_crt_parse_der`.
  - `rtc_to_utc`: `raTlsRtcToUtc(2026,10,12,9,0,0)` equals the value the decision in `ratls_ps2.c` implies, asserted from Python by compiling just that function. For JST that's `1791763200` (2026-10-12 00:00 UTC).

- [ ] **Step 2: Run it and confirm it fails**

  Run: `python3 .github/scripts/test_ratls_host.py`
  Expected: FAIL, compile error "ratls.h: No such file".

- [ ] **Step 3: Implement `include/ratls.h`, `src/ratls.c` and `src/ratls_ps2.c`, and add the objects to the RA `FRONTEND_OBJS`.**

- [ ] **Step 4: Run the test and confirm it passes**

  Run: `python3 .github/scripts/test_ratls_host.py`
  Expected: `PASS: ratls 14/14`.

- [ ] **Step 5: CI.** Add the host test to `flavours.yml`, plus the RA symbol check `grep -q ' mbedtls_ssl_handshake$' menu-symbols.txt` and `grep -q ' raHttpsGet$' menu-symbols.txt`. Confirm that the RA and standard ELF builds both pass, and record the RA `opl.elf` size delta from the CI size print.

- [ ] **Step 6: Commit**

  ```bash
  git add include/ratls.h src/ratls.c src/ratls_ps2.c tests/ratls Makefile .github/scripts/test_ratls_host.py .github/workflows/flavours.yml
  git commit -m "feat(ra): verified HTTPS GET over mbedTLS (TLS 1.3/1.2) for RA builds"
  ```

---

### Task 3: game-ID lookup in the Xerabora browser, licence shipping, docs

**Files:**
- Modify: `src/achievements.c`: `loadXerabora()` (~line 444), a new parser and lookup
- Modify: `include/achievements.h`
- Modify: `lng_tmpl/_base.yml`: append `XERA_SET_CLOCK`
- Modify: `src/menusys.c`: the state-message selection gains the clock note (below)
- Modify: `.github/scripts/package_release_app.py`: RA package requires `APPS/<app>/LICENSE-MBEDTLS.txt`, and the ordinary package refuses it. Copy it from `third_party/mbedtls/LICENSE` wherever the RA package adds `neutrino/RA-EDITION-NEUTRINO.txt`.
- Modify: `.github/scripts/test_ra_xerabora_browser.py` (harness gains the HTTPS stub), `.github/scripts/test_package_orbit_neutrino.py` or the package test that covers `args.ra`
- Modify: `docs/RETROACHIEVEMENTS.md`: replace #926's paragraph ("ORBIT looks the game up with RetroAchievements' HTTPS API, which RiptOPL's menu cannot reach…") with:
  - RiptOPL now does the same lookup, so never-played games show their full list;
  - the console needs internet access and a set clock;
  - otherwise it falls back to the library match.

**Interfaces:**
- Consumes: `raHttpsGet` and `RATLS_ERR_*` from Task 2. The host-only path `raNetXeraboraIdentify(NULL, NULL, &host, title, sizeof(title), &count)` (already in #926).
- Produces:
  - `int achievementsParseGameId(const char *json, int length);` → `GameID` (≥ 0), or -1 when `Success` isn't `true`, `GameID` is missing or negative, or the JSON is malformed. Uses #926's `jsonObject`/`jsonSkip` reader.
  - `static int raHttpsGameId(const char *hash, int *clockUnset)`:
    - returns `GameID` ≥ 0, or < 0 on any failure;
    - refuses (-1, no request) unless `hash` is exactly 32 chars of `[0-9a-f]`;
    - path `/dorequest.php?r=gameid&m=<hash>`, host `retroachievements.org`, 2048-byte static buffer;
    - sets `*clockUnset = 1` on `RATLS_ERR_CLOCK`.
  - `static int xeraClockNote`: when set, the fallback's result carries the note.
- New image flow in `loadXerabora()`, replacing the block after hashing:
  1. Call `raNetXeraboraIdentify(NULL, NULL, &host, …)` for the host (this also brings the network up). On failure → `ACH_OFFLINE`, as today.
  2. `gid = raHttpsGameId(hash, &clockUnset)`.
  3. `gid == 0` → `ACH_UNSUPPORTED`.
  4. `gid > 0` → `xeraFetch(host, 'A', gid)` then `achievementsXeraboraPage(&result, 'A', 0, 0)`. If the fetch fails, report `xeraState(rc)`.
  5. `gid < 0` → the existing #926 path, unchanged (`raNetXeraboraIdentify(hash, …)` → library → `xeraFindGame` → `ACH_NOT_PLAYED`). When `clockUnset`, `ACH_NOT_PLAYED` and `ACH_UNSUPPORTED` messages use `_STR_XERA_SET_CLOCK`.
- Label (appended): `XERA_SET_CLOCK`: "Could not look this game up online: set the console clock in the system settings. Showing your library instead."

- [ ] **Step 1: Write the failing tests.**

  `test_ra_xerabora_browser.py` gains the following. Its stubs: `raHttpsGet` scripted (returns body / `RATLS_ERR_NET` / `RATLS_ERR_CLOCK`); `raNetXeraboraIdentify` records whether `hash` was NULL; `raNetHttpGet` serves `/game?id=N` and `/library`.
  - `gameid_parse`: `{"Success":true,"GameID":2791}` → 2791; `{"Success":true,"GameID":0}` → 0; `{"Success":false}` → -1; `{"GameID":5}` → -1; `{"Success":true,"GameID":"x"}` → -1; truncated `{"Success":tr` → -1; `{"Success":true,"GameID":-3}` → -1.
  - `never_played_reaches_game`: HTTPS returns GameID 2791 and the library lacks the title → the request path was `/game?id=2791`, `result.state == ACH_READY`, and no `/library` fetch.
  - `gameid_zero_unsupported`: GameID 0 → `ACH_UNSUPPORTED`, with no `/game` fetch.
  - `https_failure_falls_back`: `RATLS_ERR_NET` → `raNetXeraboraIdentify` called with the hash, `/library` fetched, and the title-match path taken (`ACH_NOT_PLAYED` when absent).
  - `clock_unset_notes`: `RATLS_ERR_CLOCK` → fallback taken and `xeraClockNote == 1`.
  - `gameid_rejects_bad_hash`: hash `"ABC"` and a 32-char hash with `G` → `raHttpsGet` never called.

  The package test covers two cases: an RA zip without `APPS/<app>/LICENSE-MBEDTLS.txt` → `ValueError`; an ordinary zip containing it → `ValueError`.

- [ ] **Step 2: Run them and confirm they fail**

  Run: `python3 .github/scripts/test_ra_xerabora_browser.py`
  Expected: FAIL, `achievementsParseGameId` undefined.

- [ ] **Step 3: Implement the parser, `raHttpsGameId`, the new flow, the label, the state message and the packaging change. Then update the docs.**

- [ ] **Step 4: Run the RA suite and confirm it passes**

  Run: `for t in test_ra_xerabora_browser test_caduceus_browser test_ra_nic_reserved test_ratls_host test_mbedtls_vendor test_package_orbit_neutrino test_ra_release; do python3 .github/scripts/$t.py || exit 1; done`
  Expected: all PASS.

- [ ] **Step 5: Commit and open the PR against `rebuild/main`.** The body must state "ZERO HW", the RA `opl.elf` size delta, and the console checklist from spec §Testing (played and never-played games, clock set and unset).

  ```bash
  git add src/achievements.c include/achievements.h src/menusys.c lng_tmpl/_base.yml .github/scripts docs
  git commit -m "feat(ra): look games up by hash over HTTPS like ORBIT, library match as fallback"
  ```
