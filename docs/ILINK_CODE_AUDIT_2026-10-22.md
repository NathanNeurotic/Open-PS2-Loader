# iLink code audit: command direction and reset recovery

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
license. Its three manager corrections also apply to POPStarter's embedded
copy. Native OPL embeds this build. Standard Neutrino packaging replaces
**both** `iLinkman.irx` and `IEEE1394_bd_mini.irx` and verifies the copies.
The RetroAchievements ORBIT package remains a separate runtime and is not
the standard-kit report under investigation.

POPStarter's combined driver must be rebuilt in the pinned PS2DEV container,
then copied to all three tracked locations. Update the validator's size and
the provenance hash together. The CI job enforces byte identity and provides
an `ilink-recovery-modules-PS2DEVPINNED` artifact with a source/hash manifest.

## Remaining gaps found during review

These remain investigation items, not proven explanations for this console:

- **Completion ownership:** both block drivers use one global status FIFO.
  `ieee1394_Sync` accepts nonzero source bits without matching the reported
  ORB address. A delayed old completion or concurrent operation can therefore
  be mistaken for the current one. Source bits also admit unsolicited status.
  A complete repair needs request identity and serialization of submission,
  status consumption and bus-reset handling.
- **Unbounded waits:** the outer TEST UNIT READY retry count is bounded, but
  a command can wait indefinitely inside `ieee1394_Sync`. Earlier notes that
  called readiness a strict 30-second deadline were too strong. `iLinkPHTSendData`
  and some hardware waits also rely on an interrupt without a software deadline.
- **Management ORB lifetime:** LOGIN uses stack storage and can return on
  a publication error or response timeout. A missing acknowledgment does not
  prove that the target rejected its pointer. Safe retry requires proving
  target quiescence or retaining storage until the target can no longer access
  it. A new timeout followed by freeing a live ORB would make this worse.
- **Failure propagation:** `scsi_connect` is void; the enclosing device setup
  can report configured despite a refused warm-up. It does not mount an invalid
  geometry now, but another attempt depends on a later bus reset. Failed
  configuration paths also need a transaction-context ownership audit.
- **Sense handling:** `ProcessStatus` shifts an 8-bit data element by 16,
  losing sense information. The older POPStarter warm-up also examines its
  sense buffer after a failed REQUEST SENSE without first clearing it.
- **Receive parsing:** unhandled FIFO draining now obeys its function contract,
  but the caller supplies the available FIFO level rather than a decoded
  packet length. Packet boundary and bounds handling need a separate pass.

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
- Existing reset/login and SBP-2 lifetime regressions must remain passing.
- Local target compilation and pinned CI builds establish buildability and
  binary provenance. They do not establish gameplay or explain a white screen.

The next useful console test uses one source-pinned standard candidate with
its matching ELF, both Neutrino modules and the rebuilt POPStarter driver.
For POPStarter, replace the old **loose** iLink pair on the actual seek path
as well as the bundled files; a higher-precedence old pair can mask the new
embedded copy. Record the source/flavour, pair hashes, logical sector size
if known, native/Neutrino/POPS result separately, first cold launch and repeat
launch, with a single iLink device first and the normal mixed-device setup
afterward. Existing saves should not be reformatted or recreated for this test.

No physical-console acceptance is claimed by this audit.
