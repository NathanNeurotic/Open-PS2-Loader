# HTTPS game-ID lookup for the RA browser (ORBIT parity) — design

Status: draft for review (2026-10-12). Part of RetroAchievements parity on the RiptOPL side.
Builds on #926 (Xerabora-mode browser).

## Goal

Look up a game's RetroAchievements ID from its hash **exactly as ORBIT does**:
`GET https://retroachievements.org/dorequest.php?r=gameid&m=<hash>` (RetroAchievements' public
connect API, no key), answered with `{"Success":true,"GameID":N}`. With the ID, the browser fetches
the full list and progress from the xeRAbora PC (`/game?id=N`, already in #926).

**Success:** from any game card in Xerabora mode, including a game the player has **never
played**, "View achievements" shows the game's full list, as in ORBIT. #926's fallback (match the
title in the account library) remains for when the console has no internet, so the feature is
never worse than #926 alone.

## Decisions already made

- **Library: mbedTLS** (Mbed-TLS/mbedtls, Apache-2.0), taken from its authoritative upstream at a
  pinned LTS tag (3.6.x). It has no GPL code, so RiptOPL stays AFL-3.0. It supports TLS 1.3 like
  ORBIT's wolfSSL, plus TLS 1.2.
- **RA builds only.** All of this compiles under `RETROACHIEVEMENTS=1`. The standard and Korium
  editions don't change, consistent with "releases differ only by theme and RA features".

## Facts this design relies on (checked 2026-10-12)

- retroachievements.org negotiates TLS 1.3 and also accepts TLS 1.2
  (`ECDHE-ECDSA-AES128-GCM-SHA256`).
- Its chain: `retroachievements.org` ← Google Trust Services **WE1** (ECDSA) ← **GTS Root R4**.
- The menu's network stack already has a DNS server configured (`netsupport.c`: `dns_setserver`),
  and `sceCdReadClock` reads the console clock (used in `OSDHistory.c`).

## Components

### 1. `third_party/mbedtls/` (vendored subset)
- Only the `library/` sources needed for a TLS client, at the pinned tag. Add a `README` with the
  tag, commit SHA and source URL, plus the upstream `LICENSE` and `NOTICE`, and a CREDITS entry.
- `riptopl_mbedtls_config.h` enables only what this needs:
  - **Protocol:** TLS 1.3 and 1.2, client side only.
  - **Key exchange and signatures:** ECDHE on X25519 and secp256r1/secp384r1; ECDSA and RSA
    signature verification.
  - **Ciphers and hashes:** AES-GCM, ChaCha20-Poly1305, SHA-256/384.
  - **Certificates:** X.509 parsing plus the SNI and hostname-verification options.
  - **Off:** server mode, PSK, renegotiation, filesystem and threading.
- It's built as an EE static library linked only into RA builds. The ELF growth gets measured in
  the plan (expected about 150–250 KB packed-size headroom; the menu ELF isn't in `ram84`).

### 2. Trust anchors (`src/ratls_roots.c`)
- Embed DER for **GTS Root R1–R4**, so a key-type rotation at Google doesn't break the lookup,
  and **ISRG Root X1/X2**, so a CA move to Let's Encrypt doesn't either.
- Each one is documented with fingerprint and expiry. A host test checks they parse, and that the
  live chain shape documented above validates against them.

### 3. Time and entropy (`src/ratls.c`)
- **Time:** certificate validity is checked against `sceCdReadClock`, converted to UTC. If the
  clock is clearly unset (year before 2025), the lookup fails closed and the browser uses the #926
  fallback with a "set the console clock" note. Certificates are never accepted unchecked.
- **Entropy:** the CTR_DRBG is seeded from every non-deterministic source available: the EE
  COP0 cycle counter sampled around network and pad events, the IOP timer, the CDVD clock, and
  network arrival timing. Mixing happens through mbedTLS's entropy accumulator. The spec records
  that the PS2 has no hardware RNG; this matches what PS2 TLS clients (ORBIT, curl ports) do.

### 4. HTTPS transport (`src/ratls.c`)
- `raHttpsGet(host, path, buf, max, &len)`: DNS via `gethostbyname`, TCP connect, then mbedTLS
  over BIO callbacks.
- Reads use lwIP's per-call `MSG_DONTWAIT` in 64-byte-aligned chunks with an overall deadline, the
  same rules as #926's `raNetHttpGet`, since `fcntl(O_NONBLOCK)` has no effect on this stack.
- SNI and hostname verification are always on.
- Requests carry `User-Agent: RiptOPL/<version>`, as RetroAchievements asks of clients.
- It runs on the I/O worker like the rest of the browser, never on the GUI thread.

### 5. Game-ID lookup and browser integration
- `raHttpsGameId(hash)` returns `GameID`, 0 for unknown, or a negative value for failures.
- In #926's image flow, after the hash: try `raHttpsGameId` first (the ORBIT path). On success
  fetch `/game?id=N`. On a network or TLS failure, fall back to the library title match. An answer
  of `GameID 0` means "unknown to RetroAchievements" (`ACH_UNSUPPORTED`).
- `ACH_NOT_PLAYED` remains only for the no-internet fallback case.

## Error handling

| Case | Result |
| --- | --- |
| DNS fails / no route to internet | #926 library fallback (logged) |
| Certificate invalid, expired or wrong host | fail closed → fallback, logged with reason |
| Clock unset | fail closed → fallback, note to set the clock |
| HTTP non-200 / malformed JSON | fallback |
| `GameID` 0 | `ACH_UNSUPPORTED` |
| Deadline exceeded | fallback |

## Testing

- **Host build of `ratls.c` plus the vendored mbedTLS** (same config):
  - a local TLS 1.3 and TLS 1.2 server (Python `ssl`) with a test CA swapped in for the anchors,
    checking a full GET, chunked reads, the deadline, a wrong hostname (rejected), an expired
    certificate (rejected) and a bad root (rejected);
  - the anchors parse.
- **Parser test:** the gameid JSON (Success true/false, GameID 0, malformed input).
- **Browser test:** #926's harness gains the HTTPS path (stubbed). It checks that a never-played
  game reaches `/game?id`, and that a TLS failure falls back to the library match.
- **CI:** standard and Korium ELFs must not contain mbedTLS symbols (the existing RA leak check).
- **Console:** the lookup on a real network for a played and a never-played game, with the clock
  set and unset.

## Alternatives considered

- **wolfSSL** (ORBIT's choice, in the SDK ports): GPL-3.0. Rejected so RiptOPL stays AFL-3.0.
- **BearSSL** (MIT): no TLS 1.3. It works with today's server, but it's less future-proof than
  mbedTLS.
- **Resolve the hash on the PC** (xeRAbora or PS2-Servers): xeRAbora has no such endpoint, and
  PS2-Servers support belongs to the later phase.
