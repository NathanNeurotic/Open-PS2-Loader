# UDPFS read-stall investigation, 16 October 2026

## Evidence boundary

Eliminator reports Tekken Tag Tournament (`SLUS_200.01`) black-screening with
official Neutrino 1.8.0. His previously working PS2-Servers build was deleted;
its exact version is unknown. That means neither a RiptOPL handoff regression
nor a particular server regression range is established.

The supplied server log loads Neutrino and its modules, opens the ISO, reconnects
after the IOP reset, and processes 56 block reads. Its last server reply ends at
sequence 652. It subsequently logs six NACKs asking for 653, with no packets
retransmitted. The log lacks a packet capture and final-ACK telemetry, so it
cannot establish whether the next request was sent or lost on the wire.

Compiled production RiptOPL argument builders from `0a1a593a` and `2b838e09`
produced identical arguments in four launch cases (server-hosted/card-hosted
Neutrino, compatibility modes off/Mode 3). This narrows the launch-argument
hypothesis; it does not prove all teardown behavior is equivalent.

## Locally reproduced failure

`tools/replay_neutrino_udpfs.py` compiles the actual Neutrino socket structure,
packet definitions, interrupt receive callback, both send functions and receive
function into a host library. IOP event flags, alarms, the SMAP FIFO and network
are stubbed. The real Python server request dispatcher, packet sender, window
wait, final-ACK wait and retransmitter run in a separate worker. File reads are
replaced with a deterministic 16 KiB payload. This is a transport replay, not
PS2 execution or an emulated game boot.

Fault injection drops the first request and delivers six delayed final DATA/ACK packets
from the preceding read. Official Neutrino accepts that older ACK as success:
its masked subtraction is unsigned in effect and always meets `diff >= 0`.
It enters receive without retransmitting the missing request. The delayed DATA
also triggers a NACK for 653; the server has no reply to that unreceived request.
The client eventually disconnects. Request loss alone recovers; the delayed
packet alone recovers. Their combination reproduces the terminal log pattern.

The repaired client rejects the older ACK, retries the same request sequence,
and receives all 16,384 expected bytes. The test also asserts that the server
accepts the request exactly once. Both ordinary and scatter/gather send paths
are exercised, with request/reply sequences `(57,653)`, `(0,0)` and `(4095,4091)`.
The last two exercise wraparound, including the server response crossing 4095.

The replay runs against the server before PR #236 (`c04106c16f563e5f808474ee40bfaac7728249c6`)
and after its ACK repair (`b1238edf2900fa40fd5fe6a440f6851ebdc4ea6d`). All 144
expectations passed locally: 24 official-client failure reproductions, 72
official-client recovery controls, and 48 repaired-client successful transfers.
This includes the exact official stable 1.8.0 source (`f12b4f51b5112928eb06e29fd91511251c0b29f1`)
as well as the official development source. The stable client produces exactly
six NACKs for 653 in the injected lost-request case, matching the terminal log
pattern. These packets are injected deliberately; their actual occurrence on
the tester's network remains unproven.
The server repair alone does not repair this client-side failure.

This is a demonstrated mechanism consistent with the tester's log. It is not
proof that the missing request/delayed packet combination occurred on his PS2.

## Narrow repair and distribution

The earlier half-ring comparison fix at `a7b6736` exposed a second defect in
stress testing: each rejected stale ACK immediately consumed a retry. Four
stale packets could exhaust all retries even after the server accepted the
request. The six-packet burst reproduced that failure before this repair.

The complete repair is NathanNeurotic/neutrino commit
`e6f139240e3e64beb34807d2e9ba90a9def80ae6`. Both send paths keep the original
500 ms alarm active while ignoring stale ACKs; only a real timeout consumes a
retry. A timeout firing between the wait and ACK clearing remains latched.
Twenty-four actual-source send-loop tests cover this race, stale bursts,
genuine retries, combined ACK/timeout and wraparound. Exact-head host and
PS2 target CI passed in run `38924999677`.

Its upstream base is `7be8de2798c99af433c91993e021746a54d6800d`, also the source
commit of the current official development archive. Standard RiptOPL kits had
continued fetching the official archive, so they did not distribute either
client repair. The verified complete runtime is preserved under the separate
candidate tag `udpfs-ack-e6f1392`; the floating latest release is unchanged.

The standard kit now stages the complete repaired runtime using the archive
SHA-256 in `third_party/neutrino/release.json`. It verifies the embedded version
and required modules, includes source/module provenance and the AFL-3.0 license,
and preserves RiptOPL's UDPFS block-mode configuration. The obsolete companion
PC server inside that archive is not installed; the kit links to PS2-Servers. A changed or incomplete
archive fails packaging. The upstream watcher requires review of a changed
upstream asset instead of silently replacing the repair. RA kits continue to
stage their separate pinned ORBIT runtime.

An OPL ELF-only update cannot update an external Neutrino installation. A future
console check must identify the actual loaded runtime; another unchanged ELF
would not exercise this repair. No additional tester run is requested by this
investigation, and console acceptance remains pending.

## Reproduction

Check out the pinned official/fixed Neutrino and server revisions listed above,
then run from RiptOPL with Python 3 and GCC available:

```text
python tools/replay_neutrino_udpfs.py --official-source <official-checkout> --stable-source <stable-1.8.0-checkout> --fixed-source <fixed-checkout> --server-source <server-checkout> --output build/transport-replay
python .github/scripts/test_standard_neutrino_bundle.py
```

The server checkout needs its parent commit available. The dedicated UDPFS
transport workflow obtains these exact source revisions, runs the replay and
package checks, stages the real digest-verified runtime, and uploads both the
JSON replay evidence and the repaired runtime as CI artifacts.
