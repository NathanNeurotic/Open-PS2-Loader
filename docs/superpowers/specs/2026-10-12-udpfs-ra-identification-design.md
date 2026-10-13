# First-time RA identification for UDPFS games — design

Status: draft for review (2026-10-12). Part of RetroAchievements parity on the RiptOPL side.

## Goal

A player whose games are on a UDPFS server can run **RA: check game support** on a game for the
first time, from the RiptOPL menu, in both RA modes (Xerabora and Caduceus), and get the same
result as on USB: the game is identified, its watch list is saved, and the next launch is tracked.

Today this is impossible. The support check sends UDP requests (`RAP1`, `RAQ1`, `RAG1`; Caduceus
also `CADQ2`) through the menu's TCP/IP stack, and while UDPFS owns the network adapter that stack
cannot run (`raNetNicReserved`). The menu refuses with a notice (`_STR_RA_NA_UDPFS` on the UDPFS
page; "network busy" for UDPFS IMG games on BDM pages). The documented workaround is to check a
local copy of the same image first.

**Success:** on the UDPFS Files page and for UDPFS IMG (`massN:`) games, the support check
completes against an unmodified xeRAbora or Caduceus PC, saves `RA/<serial>.wl` next to the game,
and the following Neutrino launch passes it to the RA runtime (#916/#923).

## Scope

In scope:
- UDPFS **Files** (`udpfs_ioman`, `udpfs:`) and UDPFS **IMG** (`udpfs_bd`, `massN:`). Both load
  RiptOPL's own `udpfs_smap` + `udpfs_ministack`.
- Both RA modes, using their existing wire protocols unchanged.
- The support check (identify + watch-list download), the link test, and the Xerabora browser's
  lookup (#926), all of which use the same request path.

Out of scope:
- Classic **UDPBD** (SUDPBDv2): its `smap_udpbd` driver is a third-party monolith without a UDP
  API. ORBIT does not support UDPBD either.
- Anything in-game (the RA runtime already handles UDP launches).
- The Caduceus achievement browser's SMB-share pairing key (`ART/CADUCEUS.KEY`), which needs SMB
  by design.

## Why the existing pieces are enough

- **Hashing already works.** `raHashIsoDirect` and `raHashVcd` read through `open()`/`read()`,
  which `udpfs:` and `massN:` serve. The PS2 hash reads only `SYSTEM.CNF` and the boot executable.
- **The protocols are plain UDP request/reply.** Every menu exchange in `ranet.c` goes through one
  helper, `ask()`: send one datagram, wait for one reply, retry. Only the transport under `ask()`
  is missing while UDPFS owns the adapter.
- **RiptOPL owns the ministack.** `udpfs_ministack` already exports `udp_bind` and
  `udp_packet_send_ll`, resolves ARP, and accepts broadcast. Adding one request/reply facility
  there serves both UDPFS variants.

## Design

### 1. ministack: a UDP exchange device (IOP)

`udpfs_ministack` registers a small iomanX device, `mstack:`, at load (alongside `tty`). It has one
devctl:

```
MSTACK_DEVCTL_UDP_XCHG
  in:  { u32 dst_ip; u16 dst_port; u16 timeout_ms; u16 len; u8 data[len ≤ 512] }
  out: { u32 src_ip; u16 len; u8 data[len ≤ 1024] }   returns len, or -ETIMEDOUT / -EINVAL
```

- **Port:** the request is sent from a fixed local port, **18196**, which is RiptOPL's existing
  menu RA port (`RA_MY_PORT`). The PC replies to the address and port written in the request text
  (`... <ip> 18196`), as the protocol already specifies. The port is bound once with `udp_bind`
  and reused, because the ministack has no `udp_unbind` and only four slots.
- **Receive:** the UDP handler runs in the SMAP receive context. It copies the payload (via
  `smap_fifo_read`) into a single reply buffer and records the source IP. A reply arriving while
  no exchange is waiting is dropped.
- **Wait:** the devctl polls for the reply with `DelayThread` until it arrives or `timeout_ms`
  passes. No new kernel objects, and no lock shared with UDPFS operations.
- **Broadcast:** `dst_ip = 255.255.255.255` is allowed (Xerabora discovery, `RAP1`), and the reply
  carries the responder's IP.
- **Export table:** unchanged. The device is reached through iomanX, not a new export, so
  `udpfs_bd`/`udpfs_ioman` imports stay as they are.

### 2. ranet.c: a second transport under `ask()` (EE)

- `ask()` becomes transport-neutral. When `raNetNicReserved()` is true and `mstack:` answers, each
  attempt calls `fileXioDevctl("mstack:", MSTACK_DEVCTL_UDP_XCHG, …)` instead of
  `sendto`/`recvfrom`. Otherwise it uses sockets exactly as today. The retry counts, WAIT rounds,
  reply filtering (reply must come from the target unless broadcast) and `g_raReplyIP` are
  unchanged.
- `open_pc_socket`'s role (own IP and port for the request text) comes from `ps2_ip` and 18196
  when on the ministack path. UDPFS always uses a static IP; DHCP is not available there.
- `raAskPC`, `raNetTestLink`, `raCaduceusPage` (pairing only) and the #926 identify call get the
  new path automatically, because they all go through `ask()`. The `raNetNicReserved()` refusals
  in those functions become "use the ministack path" rather than "refuse".
- `raLaunchNetworkUp` is unchanged. At launch the game's IOP reset frees the adapter, and #923
  already handles UDP launches.

### 3. Menu: allow the check on UDPFS

- `menuCheckSelectedGameSupport`: the `UDPFS_MODE` branch hashes `udpfs:/<CD|DVD>/<name>` with
  the existing deferred hash path (`sbHashGameDeferred`) instead of showing `_STR_RA_NA_UDPFS`.
  UDPFS IMG games on BDM pages already take the generic branch and simply stop being refused.
- The watch list is saved where the launch looks for it, `<prefix>RA/<serial>.wl`, i.e.
  `udpfs:/RA/` for Files. This needs a writable share; PS2-Servers allows writes unless started
  read-only. A write failure is reported with the existing "could not save" notice.

## Error handling

- `mstack:` missing (old driver, UDPBD) → the existing "network busy" notice, unchanged.
- No reply within the timeout → the existing "PC did not answer" result for that request.
- Reply larger than the buffer → truncated to the buffer and rejected by the protocol parsers,
  which already validate lengths (`raExpectedChunkLength`).
- A UDPFS operation and an RA exchange at the same time: both transmit through `smap_transmit`,
  which already serializes the TX ring. The exchange runs on the I/O worker like the rest of the
  support check, so it never overlaps the I/O worker's own UDPFS scans.

## Testing

- **ministack host test:** compile the real exchange code against stubbed SMAP and UDP calls.
  Cover request framing, reply copy, timeout, a stray reply with no waiter, broadcast, and that the
  fixed port is bound only once.
- **ranet host test:** `ask()` picks the ministack path only while the NIC is reserved and
  `mstack:` exists. Check the identical retry and WAIT behaviour, and the reply-source filtering,
  on both transports.
- **Menu wiring test:** the UDPFS branch hashes and defers instead of showing the notice.
- **Console:** check support on a UDPFS Files game and a UDPFS IMG game, in each mode, against a
  real xeRAbora PC and a Caduceus PC. Then launch to confirm tracking.

## Alternatives considered

- **Put the exchange in `udpfs_ioman`:** Files only. IMG (`udpfs_bd`, a BDM device) has no devctl
  path.
- **Relay through PS2-Servers:** it would add a new protocol to our server, and it belongs to the
  later PS2-Servers phase, not this RiptOPL-side parity work.
- **Swap stacks in the menu (unload UDPFS, load SMB, check, reload):** the ministack can't be
  unloaded safely without an IOP reset, and it would drop the UDPFS session mid-browse.
