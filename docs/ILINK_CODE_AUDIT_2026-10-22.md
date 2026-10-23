# iLink code audit: command direction, completion ownership and reset recovery

Audited against `rebuild/main` at
`57c45b4fcc922ba00fed949c634caea0a2900c63`. The reporter used the **standard
Beta 4221 kit and replaced the full Neutrino folder**. The latest report says
Ember works, POPStarter fails, Neutrino did not work, and native OPL is
intermittent. Earlier native OPL successes do not establish current acceptance.

## Confirmed defects corrected

1. **POPStarter command direction was reversed.** Its older `sbp2_queue_cmd`
   set ORB bit 27 for disk writes and cleared it for disk reads. SBP-2 describes
   the target's bus operation: a disk read requires the target to write into
   the initiator's memory. Native OPL's newer block driver already used the
   correct mapping. INQUIRY and READ CAPACITY also transfer data to the host,
   so this error can prevent mounting before the first filesystem read.
   `test_ilink_command_orb.py` captures production ORBs, verifies both directions,
   and fails on the older POPStarter implementation. The mapping agrees with
   the [Linux SBP-2 driver's DMA_FROM_DEVICE direction handling](https://code.googlesource.com/linux/torvalds/linux/+/669d089a7fe1eacf4e86160297f32c678ee71ec5/drivers/firewire/sbp2.c).

2. **A stale generation leaked the manager's TX semaphore.** `iLinkSendData`
   acquired `UBUFTxSema`, then returned `-1021` from either transmit loop on a
   generation mismatch without releasing it. The next send could block
   indefinitely. Both exits now release ownership before returning; the next
   sender clears the uncommitted partial FIFO.

3. **An early response error left its alarm pending.** `iLinkSync` cancelled
   the split-response alarm only on success. An IRQ error could end the wait
   first, leaving the alarm to set the shared error flag during a later
   transaction. The alarm is cancelled after every wait.

4. **Debug-disabled builds did not drain unhandled receive data.** The volatile
   FIFO read in `NoResponseHandler` was inside `DEBUG_TTY_FEEDBACK`. With that
   flag disabled, subsequent parsing could treat leftover payload as a header.
   The read is unconditional; only printing depends on the debug flag.

5. **Transfer chunking assumed 512-byte logical sectors.** Both drivers used
   `65024 / 512` sectors per request regardless of READ CAPACITY's block size.
   With 4096-byte sectors, even 16 sectors exceed the 16-bit ORB length and
   the fixed 65024-byte write buffer. Chunking now uses the discovered size;
   the queue also refuses oversized bytes or CDBs before copying/publishing.
   A block larger than the buffer is refused. This is conditional on geometry;
   the reporter's logical sector size is unknown.

6. **Capacity was one sector short.** READ CAPACITY returns the last valid
   LBA. Both SCSI copies exposed it as the number of sectors. The count now
   adds one in 64 bits. Native RC16 selection still recognizes the RC10
   sentinel, preserves the existing RC10 range if RC16 is unsupported, and
   refuses an unrepresentable all-ones RC16 last LBA.

## Ensure the fixes actually reach the runtime

The manager previously came from the SDK rather than this repository.
`modules/ilink/iLinkman` now vendors it from the same PS2SDK revision as the
block driver (`329e2bb43287e16af16c4dde1c614e2662c24468`), retaining notices and
license. Its manager corrections also apply to POPStarter's embedded
copy. Native OPL embeds this build. Standard Neutrino packaging replaces
**both** `iLinkman.irx` and `IEEE1394_bd_mini.irx` and verifies the copies.
The RetroAchievements ORBIT package remains a separate runtime and is not
the standard-kit report under investigation.

POPStarter's combined driver must be rebuilt in the pinned PS2DEV container,
then copied to all three tracked locations. Update the validator's size and
the provenance hash together. The CI job enforces byte identity and provides
an `ilink-recovery-modules-PS2DEVPINNED` artifact with a source/hash manifest.

## Deeper lifetime and interrupt audit

The follow-up pass corrected these additional source-confirmed defects in both
runtime copies. They are credible failure mechanisms, not proof of which one
FifthFox's enclosure encountered.

7. **Interrupt errors could disappear or never wake their waiter.** The ISR
   assigned its global cached interrupt register on every sample, including its
   final zero sample. It now latches request errors until consumed. Split timeout
   wakes the PHT waiter, and bus reset wakes transaction waiters with a generation
   error. A dedicated request-error event prevents an outgoing response from
   clearing a client's error. PHT retires outbound DMA before returning.

8. **Client requests shared one PHT and reply pointer without ownership.** A
   request mutex covers each complete public read/write transaction; the receive
   thread retains its independent TX mutex for responses. Queued calls snapshot
   their context before waiting, so slot reuse cannot silently change their node
   or generation. Concurrent host clients verify that replies stay with their
   callers. Invalid context indices and unrepresentable lengths are refused.

9. **A late or oversized response could write through a retired caller pointer.**
   The response handler now checks active ownership, node, transaction label,
   generation, response type, response code and block length. Copy and retirement
   are protected from an error IRQ returning the caller halfway through. Orphan
   and foreign replies are drained without touching caller memory or completing
   another request. UBUF labels advance between requests. A PHT block read waits
   for the copied response rather than returning on packet-count IRQ alone.

10. **SBP-2 status did not identify its request.** Completion now requires the
    reported ORB address, zero high address, a populated status length and source
    0 or 1. Source 2 and 3 are unsolicited and cannot complete a request. Each
    device has its own resident status FIFO. This follows the protocol fields
    independently used by the
    [Linux SBP-2 completion path](https://code.googlesource.com/linux/torvalds/linux/+/669d089a7fe1eacf4e86160297f32c678ee71ec5/drivers/firewire/sbp2.c).

11. **LOGIN, command and dummy request lifetimes were unsafe on failure.**
    LOGIN ORBs, replies and pointer payloads now live in resident per-device
    storage. One resident command ORB and the existing 65024-byte transfer
    allocation serve both data directions. Reads no longer expose caller memory
    to later target DMA. Publication occurs once: an acknowledgment failure can
    follow acceptance, so it still waits for the matching completion. Missing
    completions return an error within a 30-second polling budget while retaining
    remotely accessible storage. New requests refuse to overwrite that storage
    until its actual matching completion arrives. LOGIN retries likewise cannot
    overwrite a pending request, and discovery skips its retained device slot.
    This adds no second large transfer allocation. The mutex is released before
    calling BDM/FS attach or detach to avoid a filesystem-lock inversion.

12. **Readiness limits and setup success were misleading.** SCSI warm-up now
    includes command time in its elapsed budget and passes each command the
    remaining time. The older 300-poll limit alone did not bound an individual
    command. `scsi_connect` returns failure to device configuration; failed setup
    releases its transaction context. Sense buffers are initialized before
    REQUEST SENSE, and status sense keys use byte 1 rather than shifting an
    8-bit byte by 16. Valid extended SCSI GOOD status is accepted; an extended
    block is not automatically an error. Its first status quadlet must arrive
    before it can complete the command. A completed DEAD status marks the command
    agent for reset before SCSI retries; otherwise the stopped agent would never
    fetch the retry.
    Agent-reset data is initialized rather than sending stack garbage.

13. **Packet start bounds did not protect the end of a transfer.** Read and write
    request parsing now checks available headers and complete payloads. Software
    writes check the entire physical range, preserve partial final quadlets and
    drain rejected payloads plus their trailer. Reads validate the entire RAM or
    CROM span. Rejected or truncated requests cannot invoke a success callback.

14. **Refused startup could leave active module resources.** Kernel-object
    creation failures release created resources. If export registration or the
    combined POPStarter block-driver start fails, the manager removes its IRQ,
    thread, semaphores and export before returning nonresident. Fault injection
    checks that a refused module leaves no callback executing unloaded code.

15. **Vendored API/CROM defects were also confirmed.** The EUI-64 import uses
    export 25 rather than transaction-allocation export 12. CROM deletion checks
    the index and occupancy and updates its count before rebuilding. Allocation
    failure preserves the installed ROM's actual size. Relative leaf offsets
    count quadlets rather than units; vendor, node-ID and model descriptors now
    point to their actual records. These were verified as API and ROM defects;
    no claim is made that a particular descriptor caused the console failure.

## Hardware cost and simplicity

The patch adds no worker thread and no second 65024-byte allocation. The existing
transfer allocation serves reads, writes and dummy fetch-agent initialization;
the dummy no longer needs a separate heap allocation or worst-case-sized BSS
array. Resident metadata holds request identity and the small per-device LOGIN
structures. Kernel semaphores serialize resources that were already global.

IOP builds use `-fno-builtin`. Aligned CDBs and sector transfers combine byte
conversion and copying in one direct word loop. A successful aligned read writes
converted words from resident staging straight into its caller after completion,
without a separate swap-then-copy pass. Unaligned buffers retain a bulk-copy
fallback and partial tails use their exact byte count. No per-word library calls
or whole-buffer clearing is added to the normal path. Caller memory is still
never advertised as the target's DMA destination.

Completion polling retains the previous 50-us fast interval for the first 2 ms,
then uses 250 us until 20 ms and 1 ms for a slow tail, capped by the remaining
budget. This reduces wakeups for stalled/spinning-up drives while bounding the
added completion-detection latency. Throughput and interrupt latency still need
measurement on the PS2; host tests do not establish their real cost.

Pinned GCC 15.2.0 module measurements, compared with the preceding `5ddab45e`
candidate from the same PS2DEVPINNED container:

| Runtime modules | Previous allocated sections | Current allocated sections | Increase | Of that, additional static state |
| --- | ---: | ---: | ---: | ---: |
| Native / standard Neutrino manager + mini block driver | 16,079 B | 20,955 B | 4,876 B | 572 B |
| POPStarter combined driver | 18,389 B | 22,773 B | 4,384 B | 576 B |

These section totals include executable code and BSS; existing stacks and kernel
semaphore bookkeeping are outside the measurement. The one-pass transfer
simplification itself adds 48 bytes of code per block-driver build and no
additional static state relative to `54517ca7`. It removes the separate
full-buffer pass on normal aligned I/O. Physical throughput and interrupt
latency remain console checks.

## Remaining limits

- A request whose completion never arrives deliberately retains its resident
  storage. A generation change alone is not treated as proof that the target
  stopped accessing it. A late matching completion permits reuse; otherwise
  this conservative refusal requires a fresh IOP/driver start. Automatic
  abort/reconnect recovery remains a separate protocol change.
- The 30-second command/warm-up budgets bound completion polling and account for
  command waits. Acquiring the shared request mutex and the underlying hardware
  transfer still depend on the kernel/controller making progress. PHT uses the
  controller's split-timeout IRQ, which this patch now handles; it has no
  independent software watchdog. Hardware reset/busy waits also retain their
  existing controller assumptions. These are not unconditional wall-clock
  guarantees if the controller or interrupt delivery itself fails.
- PHT's fixed block-transaction label and controller byte order, interrupt
  ordering, bridge firmware behavior and reset timing need physical-console
  verification. Host simulation checks the software contracts, not the chip.
- Native BDM still requires 512-byte logical sectors at its mount layer. The
  transfer geometry repairs do not establish end-to-end native 4K-sector support.

The old local C++ RiptOPL tree has the same reversed POPStarter direction and
the manager defects above. A report of an older C++ build working therefore
needs its actual runtime binaries before it can serve as a source baseline.
Neither `mass0:` ordering nor global-versus-advanced `-logo` position alone
proves a launch bug: the existing binding and argv checks cover those paths.

## Validation and console gate

- Host fault injection reproduces the manager failures before correction,
  including debug on/off, and passes with both corrected managers.
- Production ORB capture reproduces reversed POPStarter direction and byte-limit
  failures before correction and passes with both corrected block drivers.
- Both production SCSI implementations pass geometry/chunking tests for 512,
  2048, 4096 and 65024-byte blocks, exact capacity, RC16 behavior and invalid
  geometry refusal. The baseline fails the affected checks.
- Production SBP-2 fault injection covers source-0 completion, foreign ORBs,
  unsolicited status, immediate and delayed replies, lost acknowledgments,
  missing completions, late DMA, retained storage, DEAD-agent recovery and
  concurrent staging. SCSI fixtures cover slow commands and setup failure.
- Manager IRQ and packet fixtures cover split timeout, error latching, bus reset,
  response retirement, exact read/write spans, rejected/truncated packets, CROM
  rebuild failure and concurrent public API calls.
- Existing reset/login, readiness, shipped-pair and stale-pair regressions remain
  required checks. All new fixtures run in the flavour workflow.
- Local target compilation and pinned CI builds establish buildability and
  binary provenance. They do not establish gameplay or explain a white screen.
- The current one-pass POPStarter driver is reproduced by
  [pinned CI run 39910301683](https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/39910301683),
  source head `9fc75831abb25a0d8d262d9b7d6601478e3b5fe3`.
  All three shipped `usbhdfsd.irx.ilink` copies are 27,145 bytes, SHA-256
  `1a9c1baaf1dd020e35b75082b630f325b90e884819c743ddd5e1f27f106efcb6`.
  The matching recovery-modules artifact ZIP's SHA-256 is
  `107cfbe92c65bc7178a96d7a01c4c43b8a0fbbdb2e7b69877649725df66dd286`.

The next useful console test uses one source-pinned standard candidate with
its matching ELF, both Neutrino modules and the rebuilt POPStarter driver.
For POPStarter, replace the old **loose** iLink pair on the actual seek path
as well as the bundled files; a higher-precedence old pair can mask the new
embedded copy. Record the source/flavour, pair hashes, logical sector size
if known, native/Neutrino/POPS result separately, first cold launch and repeat
launch, with a single iLink device first and the normal mixed-device setup
afterward. Existing saves should not be reformatted or recreated for this test.

No physical-console acceptance is claimed by this audit.
