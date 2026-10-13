# UDPFS First-Time RA Identification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let **RA: check game support** run from the menu while UDPFS (Files or IMG) owns the network adapter. The request and reply travel through RiptOPL's own `udpfs_ministack` instead of the menu's lwIP stack.

**Architecture:** `udpfs_ministack` registers an iomanX device, `mstack:`, with one request/reply devctl on the fixed local UDP port 18196. In `src/ranet.c`, `open_pc_link()` returns a sentinel "socket" when the NIC is reserved and `mstack:` answers. `ask()` and the RAP1 link test then run each attempt as one devctl instead of `sendto`/`recvfrom`. The menu's `UDPFS_MODE` refusal is deleted, so UDPFS games take the generic hash branch.

**Tech Stack:** C (IOP: ps2sdk iomanX + ministack, EE: fileXio), Python 3 static/compile tests under `.github/scripts`, host `cc` tests under `modules/network/udpfs_shared/tests`, GitHub Actions `flavours.yml`.

**Spec:** `docs/superpowers/specs/2026-10-12-udpfs-ra-identification-design.md`

## Global Constraints

- Local port **18196** (`RA_MY_PORT`); the PC replies to the `<ip> 18196` written in the request text. The port is bound **once** with `udp_bind` (ministack has 4 slots and no unbind).
- Wire protocols (`RAP1/RAQ1/RAG1/CADQ2`) stay unchanged. Retry count `RA_TRY` (12), poll `RA_POLL_MS` (25 ms × 10 per attempt), WAIT rounds and `g_raReplyIP` semantics stay the same on both transports.
- The ministack export table stays unchanged. The device is reached through iomanX only, so the `udpfs_bd`/`udpfs_ioman` imports don't move.
- No new kernel objects in the exchange (poll with `DelayThread`), and no lock shared with UDPFS operations.
- `mstack:` missing (classic UDPBD, or UDPFS selected but not loaded yet) → existing `-8` "network busy" result, unchanged.
- `raLaunchNetworkUp` stays unchanged (spec §2).
- Language labels are append-only (`lng_tmpl/_base.yml`). Keep `_STR_RA_NA_UDPFS` defined even though it loses its caller.
- clang-format 12 on every touched C file; every CI check line must pass.

**Resolved spec ambiguity.** The spec lists `raCaduceusPage` (pairing) and the #926 identify call as getting the new path. Both feed browsers whose next step needs SMB (Caduceus key) or TCP HTTP (xeRAbora `/game`), and the ministack has neither. So `raCaduceusPage` and `raNetXeraboraIdentify` **keep their `raNetNicReserved()` refusal** in this plan. The browsers under UDPFS remain a known, documented gap; a half-working page would be worse than the clear notice.

## Review Focus

1. **Reply from a stranger while waiting** (another PC answering a broadcast, a stray on 18196 to a unicast request): it must be dropped unless the destination was broadcast. Pinned in Task 1 (`stray_source_dropped`).
2. **Reply arriving when no exchange waits** (late answer to a timed-out attempt): dropped, and it must not satisfy the *next* exchange. Pinned in Task 1 (`late_reply_not_reused`).
3. **Oversized reply** (> `MSTACK_XCHG_REPLY_MAX`): truncated to the buffer, never written past it. Pinned in Task 1 (`oversize_truncated`).
4. **USB game checked while UDPFS is the network protocol**: same NIC owner, so it must also go through `mstack:` rather than refuse. Pinned in Task 2 (`reserved_with_mstack_uses_devctl` covers this; it doesn't depend on the game's device).
5. **UDPFS selected but its chain not loaded yet**: `mstack:` absent → `-8`, never `ethLoadInitModules()`. Pinned in Task 2 (`reserved_without_mstack_is_busy`).

---

### Task 1: `mstack:` exchange device in udpfs_ministack

**Files:**
- Create: `modules/network/udpfs_ministack/include/mstack_xchg.h` (shared with the EE, so it uses `<stdint.h>` types only)
- Create: `modules/network/udpfs_ministack/src/ministack_xchg.c`
- Modify: `modules/network/udpfs_ministack/src/main.c` (call `mstack_xchg_init()` right after `udptty_init()`)
- Modify: `modules/network/udpfs_ministack/Makefile` (add `ministack_xchg.o` to `IOP_OBJS` before `imports.o`)
- Modify: `modules/network/udpfs_ministack/src/imports.lst` (add `I_memcpy`, `I_memset` to sysclib if not present; iomanX `AddDrv`/`DelDrv` already imported under `ioman_IMPORTS`)
- Create: `modules/network/udpfs_shared/tests/stubs/iomanX.h` (minimal `iomanX_iop_file_t`, `iomanX_iop_device_t`, `iomanX_iop_device_ops_t`, `IOP_DT_FS`, `IOP_DT_FSEXT`, `AddDrv` prototype)
- Create: `modules/network/udpfs_shared/tests/test_ministack_xchg.c`
- Modify: `.github/workflows/flavours.yml` (add the compile+run lines next to `test_ministack_announce`, same flags plus `-I$N/udpfs_ministack/src`)

**Interfaces:**
- Produces (header, exact):
  ```c
  #define MSTACK_XCHG_DEVICE      "mstack:"
  #define MSTACK_DEVCTL_VERSION   0x4D530000 /* returns MSTACK_XCHG_VERSION */
  #define MSTACK_DEVCTL_UDP_XCHG  0x4D530001
  #define MSTACK_XCHG_VERSION     1
  #define MSTACK_XCHG_PORT        18196
  #define MSTACK_XCHG_REQ_MAX     256
  #define MSTACK_XCHG_REPLY_MAX   1016 /* reply struct = 1024 bytes, a 64-byte multiple for the EE DMA */
  typedef struct { uint32_t dst_ip; uint16_t dst_port; uint16_t timeout_ms; uint16_t len; uint16_t pad; uint8_t data[MSTACK_XCHG_REQ_MAX]; } mstack_xchg_req_t;   /* dst_ip in network byte order, as sin_addr.s_addr */
  typedef struct { uint32_t src_ip; uint16_t len; uint16_t pad; uint8_t data[MSTACK_XCHG_REPLY_MAX]; } mstack_xchg_reply_t; /* src_ip network byte order */
  ```
- Produces (IOP, in `ministack_xchg.c`):
  - `int mstack_xchg_init(void)`: `AddDrv` of an `IOP_DT_FS | IOP_DT_FSEXT` device named `mstack`. Ops are `-EIO`/`-48` stubs except `init` (returns 0) and `devctl`.
  - `int mstack_xchg(const mstack_xchg_req_t *req, mstack_xchg_reply_t *reply)`: returns reply `len` (≥ 0), `-ETIMEDOUT`, or `-EINVAL` (`len == 0`, `len > REQ_MAX`, `dst_port == 0`).
  - devctl: `MSTACK_DEVCTL_VERSION` → 1. `MSTACK_DEVCTL_UDP_XCHG` with `arglen >= offsetof(data)+len` and `buflen >= sizeof(mstack_xchg_reply_t)` → `mstack_xchg`. Anything else → `-EINVAL`.
- Behaviour decisions:
  - Bind lazily on the first exchange: `udp_bind(MSTACK_XCHG_PORT, xchg_rx, NULL)`, kept in a static. A NULL return → `-ENOMEM`.
  - **Byte order:** the ministack takes host-order addresses (`IP_ADDR(a,b,c,d)`, `0xFFFFFFFF` = broadcast), but `dst_ip` and `src_ip` are in network order.
    - Send with `udp_packet_init(&pkt, ntohl(req->dst_ip), req->dst_port)`, then `udp_packet_send_ll(sock, &pkt, 0, req->data, req->len)`.
    - Build `src_ip` by copying the 4 bytes of `ip.addr_src` as they are.
    - `udp_packet_t.align` is 2 bytes that only go on the wire when `pktdatasize` includes them. `pktdatasize = 0` excludes them, so the test asserts the payload is exactly `req->data`.
  - Arm (`waiting = 1; got = 0; want_ip = dst`) **before** sending. Poll `got` every 1 ms (`DelayThread(1000)`) up to `timeout_ms`, then disarm. `waiting`, `got`, `reply_len` are `volatile`.
  - `xchg_rx(socket, arg, hdr, hdr_len)` runs in SMAP RX context:
    - if `!waiting || got`, return -1;
    - if `want_ip` isn't broadcast and the source IP ≠ `want_ip` (both compared in network order), return -1;
    - payload length = `ntohs(udp.len) - 8`, clamped to `REPLY_MAX`;
    - payload bytes 0–1 come from `hdr[42..43]` (the 44-byte pre-read); the rest comes from `smap_fifo_read(44, …)`, since the FIFO read pointer stays word-aligned;
    - record the source IP, set `got = 1`, return 0.

- [ ] **Step 1: Write the failing host test** `test_ministack_xchg.c`

  It `#include "../../udpfs_ministack/src/ministack_xchg.c"` and stubs `udp_bind` (counts calls, stores the handler), `udp_packet_init`, `udp_packet_send_ll` (captures payload bytes and dst), `smap_fifo_read` (serves from a fake frame), and `DelayThread` (on the Nth call, invokes a scripted RX event through the stored handler). Cases, each an `assert` block:
  - `version_probe`: devctl `MSTACK_DEVCTL_VERSION` returns 1.
  - `unicast_roundtrip`: send `"RAQ1 abc 1.2.3.4 18196"` to 192.168.1.20:18194. The captured payload equals the request bytes; a scripted reply `"RAA1 OK 5"` from .20 → return 9, `reply->len == 9`, data matches, `src_ip` = .20.
  - `broadcast_any_source`: dst 255.255.255.255; reply from .77 → accepted, `src_ip` = .77.
  - `stray_source_dropped`: unicast to .20; a reply from .21 arrives first, then one from .20 → returns the .20 payload.
  - `timeout`: no reply, `timeout_ms = 50` → `-ETIMEDOUT`, and at most 50 + 2 `DelayThread` calls.
  - `late_reply_not_reused`: after a timeout, feed a reply with no exchange armed (handler returns -1), then a new exchange with no reply → `-ETIMEDOUT`.
  - `oversize_truncated`: a scripted UDP length of 1400 → returns 1016, and the bytes after `reply->data[1015]` in a guard region stay untouched.
  - `bind_once`: three exchanges → `udp_bind` called exactly once, with port 18196.
  - `bad_args`: `len == 0`, `len == 257`, `dst_port == 0`, short `buflen` → `-EINVAL`.

- [ ] **Step 2: Run it and confirm it fails**

  Run: `N=modules/network; cc -std=gnu99 -Wall -Wextra -Wno-unused-parameter -Werror -I$N/udpfs_shared/tests/stubs -I$N/udpfs_ministack/include -I$N/udpfs_ministack/src -I$N/udpfs_smap/include $N/udpfs_shared/tests/test_ministack_xchg.c -o /tmp/test_ministack_xchg && /tmp/test_ministack_xchg`
  Expected: compile error, `ministack_xchg.c: No such file`.

- [ ] **Step 3: Write `mstack_xchg.h`, `ministack_xchg.c`, the `main.c` call, the Makefile object and the imports.**

- [ ] **Step 4: Run the test again and confirm it passes**

  Same command. Expected: it prints `PASS: mstack exchange` and exits 0.

- [ ] **Step 5: Add the CI lines to `flavours.yml`, and confirm the IRX builds in CI** (the `udpfs-submake` step compiles the ministack, and a missing import fails at link).

- [ ] **Step 6: Commit**

  ```bash
  git add modules/network/udpfs_ministack modules/network/udpfs_shared/tests .github/workflows/flavours.yml
  git commit -m "feat(ministack): mstack: UDP request/reply device on port 18196"
  ```

---

### Task 2: second transport under `ask()` in `src/ranet.c`

**Files:**
- Modify: `src/ranet.c`: `ask()` (line ~200), a new `open_pc_link`/`close_pc_link`, `raAskPC` (~429), the `raNetTestLink` RAP1 loop (~840–870)
- Modify: `.github/scripts/test_ra_nic_reserved.py` (its "menu actions" loop slices up to `open_pc_socket(`, so slice to `open_pc_link(` for `raAskPC`/`raNetTestLink`)
- Create: `.github/scripts/test_ra_mstack_link.py`
- Modify: `.github/workflows/flavours.yml` (run the new test next to `test_ra_nic_reserved.py`)

**Interfaces:**
- Consumes: `mstack_xchg.h` from Task 1, included as `#include "../modules/network/udpfs_ministack/include/mstack_xchg.h"`.
- Produces (static, in `ranet.c`):
  - `#define RA_LINK_MSTACK 0x10000`: a sentinel that is ≥ 0, so existing `sock < 0` checks still mean "failed", and that is never a real EE socket number.
  - `#define RA_LINK_BUSY (-8)`
  - `static int open_pc_link(char *myaddr, int sz, u8 ip[4])`:
    - if `!raNetNicReserved()`, return `open_pc_socket(myaddr, sz, ip)`;
    - else, if `fileXioDevctl(MSTACK_XCHG_DEVICE, MSTACK_DEVCTL_VERSION, NULL, 0, NULL, 0) == MSTACK_XCHG_VERSION`, fill `ip` from `ps2_ip`, write `myaddr = " a.b.c.d 18196"` and return `RA_LINK_MSTACK`;
    - else return `RA_LINK_BUSY`.
    - It never calls `ethLoadInitModules()` on the reserved path.
  - `static void close_pc_link(int sock)`: `disconnect(sock)` unless `sock == RA_LINK_MSTACK`.
  - `ask()` keeps its signature. When `sock == RA_LINK_MSTACK`, each of the `RA_TRY` attempts runs one devctl:
    - `dst_ip = to->sin_addr.s_addr`, `dst_port = ntohs(to->sin_port)`, `timeout_ms = 10 * RA_POLL_MS`;
    - the request and reply are static, `__attribute__((aligned(64)))`;
    - copy `min(len, asklen)` into `out`, NUL-terminate, set `g_raReplyIP = src_ip`, and keep the same source check as the socket path.
- Call-site changes:
  - In `raAskPC`, replace the `raNetNicReserved()` early return and `open_pc_socket` with `sock = open_pc_link(...)`, then `if (sock == RA_LINK_BUSY) { raHashStep("6-nic-busy-udp-transport"); return -8; } if (sock < 0) return -1;`.
  - Every `disconnect(sock)` in `raAskPC` becomes `close_pc_link(sock)`.
  - In `raNetTestLink`, make the same change, and replace the raw `sendto`/`recvfrom` RAP1 loop with `ask()` plus a check for the `"RAO1 OK "` prefix, keeping the 3 s deadline and the `ms` measurement.
  - The Caduceus `CADQ2` probe in `raNetTestLink` already uses `ask()`.
  - `raCaduceusPage`, `raNetXeraboraIdentify`, `raNetHttpGet` and `raLaunchNetworkUp` stay unchanged (see Global Constraints).

- [ ] **Step 1: Write the failing test** `test_ra_mstack_link.py`

  Using the existing `body()` slicing idiom, it compiles `ask`, `open_pc_link`, `close_pc_link` from `src/ranet.c` against C stubs:
  - `fileXioDevctl` scripted per call;
  - `sendto` and `recvfrom` count calls;
  - `raNetNicReserved` is controllable;
  - `ps2_ip` is set;
  - `DelayThread` does nothing;
  - `ethLoadInitModules` asserts it isn't called;
  - `open_pc_socket` returns 5.

  C assertions:
  - `not_reserved_uses_socket`: reserved = 0 → `open_pc_link` returns 5, and `ask()` calls `sendto`, never `fileXioDevctl(…UDP_XCHG…)`.
  - `reserved_with_mstack_uses_devctl`: reserved = 1, version probe returns 1 → `RA_LINK_MSTACK`, and `myaddr == " 192.168.1.10 18196"`. `ask()` makes no `sendto`/`recvfrom` calls. The devctl request has `dst_port == 18194`, `timeout_ms == 250`, and request bytes equal to `req`.
  - `reserved_without_mstack_is_busy`: probe returns -19 → `RA_LINK_BUSY`, with no `ethLoadInitModules` call.
  - `retry_count_matches`: the devctl times out every time → exactly `RA_TRY` (12) exchanges, and `ask()` returns -1.
  - `source_filter_matches`: unicast to .20, devctl replies from .21 → that attempt is ignored. The next attempt replies from .20 → accepted, `g_raReplyIP` = .20.
  - `broadcast_accepts_any`: to 255.255.255.255, reply from .77 → accepted.
  - `truncates_to_outmax`: reply len 1016, `outmax` 64 → 63 bytes copied plus NUL.

  Python assertions:
  - `raAskPC` and `raNetTestLink` contain `open_pc_link(` and no `open_pc_socket(`;
  - `raNetTestLink` contains no `sendto(`;
  - `raCaduceusPage` and `raNetXeraboraIdentify` still start with a `raNetNicReserved()` refusal.

- [ ] **Step 2: Run it and confirm it fails**

  Run: `python3 .github/scripts/test_ra_mstack_link.py`
  Expected: FAIL. The `ValueError` from `body()` reports that `open_pc_link` isn't found.

- [ ] **Step 3: Implement `open_pc_link`, `close_pc_link`, the `ask()` branch and the call-site changes in `src/ranet.c`.**

- [ ] **Step 4: Update `test_ra_nic_reserved.py`.** For `int raAskPC(` and `int raNetTestLink(`, slice to `open_pc_link(` and assert `raNetNicReserved()` appears in `open_pc_link`'s body instead. Keep the `raCaduceusPage` assertion as it is.

- [ ] **Step 5: Run both tests and confirm they pass**

  Run: `python3 .github/scripts/test_ra_mstack_link.py && python3 .github/scripts/test_ra_nic_reserved.py`
  Expected: two `PASS:` lines.

- [ ] **Step 6: Commit**

  ```bash
  git add src/ranet.c .github/scripts/test_ra_mstack_link.py .github/scripts/test_ra_nic_reserved.py .github/workflows/flavours.yml
  git commit -m "feat(ra): ask the PC through mstack: while UDPFS owns the NIC"
  ```

---

### Task 3: allow the check on UDPFS, plus docs

**Files:**
- Modify: `src/menusys.c:2122-2124`: delete the `else if (support->mode == UDPFS_MODE)` branch, so UDPFS games reach the generic `itemGet`/`itemGetPrefix` branch (`udpfsPrefix` is `"udpfs:/"`, and `sbHashGameDeferred` saves `<prefix>RA/<serial>.wl`).
- Create: `.github/scripts/test_ra_udpfs_check.py`
- Modify: `.github/workflows/flavours.yml`
- Modify: `docs/RETROACHIEVEMENTS.md`. Replace the "check a local copy first" UDPFS workaround text with:
  - the check now works on UDPFS Files and IMG in both modes;
  - it needs a writable share (PS2-Servers not started read-only);
  - classic UDPBD still can't run it;
  - neither achievement browser runs during a UDPFS session.
- Modify: the matching site page, if `docs-sync`/`site_sync` doesn't regenerate it. Check `docs/` for the UDPFS RA wording with `grep -rn "local copy" docs/ *.html`, and edit only hand-maintained files.

**Interfaces:**
- Consumes: Task 2's `raAskPC` behaviour (no code interface).

- [ ] **Step 1: Write the failing test** `test_ra_udpfs_check.py`. It slices `menuCheckSelectedGameSupport` from `src/menusys.c` and asserts:
  - `"UDPFS_MODE"` doesn't occur in the function;
  - `_STR_RA_NA_UDPFS` doesn't occur in it;
  - the generic branch `support->itemGet != NULL && support->itemGetPrefix != NULL` followed by `sbHashGameDeferred(prefix, g->name, g->extension, g->startup, g->format)` is still present;
  - `udpfsSupport`'s item table in `src/udpfssupport.c` sets both `&udpfsGetGame` and `&udpfsGetPrefix` (so the generic branch is reachable);
  - `lng_tmpl/_base.yml` still defines `RA_NA_UDPFS` (append-only rule).

- [ ] **Step 2: Run it and confirm it fails**

  Run: `python3 .github/scripts/test_ra_udpfs_check.py`
  Expected: FAIL on "UDPFS_MODE still refused".

- [ ] **Step 3: Delete the branch, and update the docs.**

- [ ] **Step 4: Run it and confirm it passes, then run the RA suite**

  Run: `for t in test_ra_udpfs_check test_ra_mstack_link test_ra_nic_reserved test_ra_xerabora_browser test_caduceus_browser test_udpfs_network_hardening; do python3 .github/scripts/$t.py || exit 1; done`
  Expected: all PASS.

- [ ] **Step 5: Commit, then open the PR against `rebuild/main`.** The body must state "ZERO HW", the console checklist from the spec §Testing, and the browser gap.

  ```bash
  git add src/menusys.c .github/scripts/test_ra_udpfs_check.py .github/workflows/flavours.yml docs
  git commit -m "feat(ra): RA support check on UDPFS Files and IMG games"
  ```
