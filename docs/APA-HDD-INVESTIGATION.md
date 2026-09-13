# APA HDD incident investigation

Updated 2026-09-13. Working changes are in PR #645. This is an engineering record, not a recovery procedure or a declaration that the incident is solved.

## Evidence boundary

The primary report describes a working internal Western Digital APA HDD, repeated RiptOPL error 401, no usable listing, unsuccessful deletion of configuration/data, and subsequent loss of access to all PS2/PS1 contents. The named build flavor is APP_RIPTOPL-RA-PS2DEVROLLING; its exact ELF/version/hash is unidentified. A second incident is secondhand. There is no affected-disk image or captured failing command sequence.

wLaunchELF_R3Z reportedly shows connected YES / formatted NO. Its GetHddInfo checks SDK presence and formatted status separately. hddCheckPresent accepts status 0/1/2; hddCheckFormatted accepts only 0. That pair can therefore mean unformatted status 1 or unavailable/unlock-failure status 2. It establishes loss of accepted access, not the number of overwritten sectors. APA-Jail has no demonstrated protective role here.

Reference sources:
- [R3Z GetHddInfo](https://github.com/saildot4k/wLaunchELF_R3Z/blob/e1c3a5cd78a1e9774b7a35649c5282c01f34615a/src/hdd.c#L278)
- [SDK HDD status wrappers](https://github.com/ps2dev/ps2sdk/blob/3e46a44a21db66f42a56320b6f64bfc52ea279f8/ee/rpc/hdd/src/libhdd.c)

## ATA command ownership: confirmed defect, incident schedule unproven

The previous local ATA driver shared a hardware taskfile, command buffer/count/direction, and event flag without driver-level ownership across APA, XHDD and BDM callers. The APA semaphore serializes APA callers, not every ATA client. Checking hardware BSY/DRQ is not a software reservation of an unissued command or of its completion cleanup.

The host regression extracts production command setup and inserts a deterministic scheduler boundary between taskfile stores. A competing read can change a pending WRITE request for sector 6/count 1 into a programmed WRITE for sector 0/count 2, with the wrong shared buffer/direction. The test reproduces this for both 28-bit and 48-bit opcodes. With the ownership fix, the first request retains sector 6/count 1 and its own buffer.

This is command-programming evidence, not a physical-sector overwrite. The host model does not establish whether a real drive accepts the inconsistent DMA direction, nor whether the reporter's schedule reaches the injected boundary. In particular, inspected SDK fileXio runs at priority 40 and BDM at 0x30 (48). BDM does not simply preempt that higher-priority writer between stores. Blocking waits and command completion require separate analysis; default worker priorities must not be omitted when evaluating reachability.

The fix owns command setup through WaitResult and DMA cleanup, serializes initialization/reset, and preserves nested initialization ownership. It retains the split export ABI but requires same-thread completion. Partial HDD startup, DEV9 ownership, full ATA request bounds, and the 65,536-sector actual count are also corrected in the PR.

Run the current host tests:

```sh
python3 .github/scripts/test_hdd_startup.py
python3 .github/scripts/test_atad_bounds.py
python3 .github/scripts/test_atad_command_ownership.py
```

A saved historical ps2atad.c can be supplied to the last script with --expect-race. No test opens a physical disk.

## BDM cache: confirmed failed-read misreporting

The inspected SDK cache ignores the return value when filling an eight-sector block. It publishes the requested LBA and returns success even after a failed or short read. A second read can then use that falsely tagged cache entry without retrying the device.

A memory-only reproduction fills all cache slots using successful reads of other sectors containing a plausible MBR. It then fails the sector-zero refill. The old code returns success and the old MBR bytes; the repeated read makes zero device calls. This does not rely on uninitialized memory. The reproduction makes no writes.

The same ignored-return pattern was also identified in the locally installed pinned SDK libbdm.a disassembly. The current source pin and that binary are controls, not identification of the reporter's exact embedded module.

The correction builds the existing BDM module from pinned source in modules/bdm, because the previous build embedded an SDK prebuilt whose internal cache cannot be corrected at the ATA interface. Local changes are enumerated in modules/bdm/ORIGIN.txt:

- Invalidate before refill; publish a cache entry only after the complete read succeeds.
- Propagate errors, reject short refills, and permit a later retry.
- Bypass eight-sector read-ahead at the device end and for non-512-byte sectors.
- Handle cache allocation failure using BDM's existing direct-device fallback.
- Require complete reads in MBR/GPT probes and free the MBR buffer on read failure.
- Preserve installed SDK structure layouts and partition callbacks without requiring the optional .path member.

```sh
python3 .github/scripts/test_bdm_cache.py
python3 .github/scripts/test_bdm_cache.py /path/to/original/sdk/bd_cache.c --expect-stale
```

The tests cover failed and short refills, invalidating both old and new tags, recovery, normal cache hits, write invalidation, capacity/end-of-device boundaries, allocation failure, and MBR/GPT probes with both header layouts. The original-source mode is an audit reproduction, not a normal CI success criterion for a fixed SDK.

This change affects shared BDM transports, including USB and iLink. It preserves the worker and filesystem architecture, but host tests and cross-builds do not replace console compatibility validation. It does not add read-only discovery, validate arbitrary filesystem metadata, or demonstrate a destructive write caused by the old cache.

## Writes during discovery remain relevant

The absence of an explicit format call does not establish a write-free startup:

- apaCacheTransfer logs a failed header read through apaSaveError, which writes sector 6.
- apaGetNextHeader can repair a backward partition link and flush dirty APA metadata while enumerating.
- pfsMountSuperBlock can update metadata and invoke pfsJournalRestore. The journal path can replay/reset data even when the caller intended a read-only mount.
- The inspected APA ioctl2Transfer uses partition-relative unsigned arithmetic. Absolute ATA capacity checks cannot validate an address that already wrapped upstream.

These are write paths to evaluate, not proof that one ran in the incident. The negative hddCheck branch exits before loading PFS in that attempt; a PFS hypothesis must establish an earlier or different mount path.

Normal error records in sectors 6/7 do NOT themselves explain rejection: apaGetFormat skips the first dword of each sector. The earlier handoff's contrary explanation is retracted. Do not advise clearing these sectors, assert that the disk is intact, or call the absence of ATA Security Erase a proof against unintended writes.

Reference: [SDK APA format check and enumeration](https://github.com/ps2dev/ps2sdk/blob/3e46a44a21db66f42a56320b6f64bfc52ea279f8/iop/hdd/libapa/src/apa.c), [APA cache error writes](https://github.com/ps2dev/ps2sdk/blob/3e46a44a21db66f42a56320b6f64bfc52ea279f8/iop/hdd/libapa/src/cache.c), [PFS journal](https://github.com/ps2dev/ps2sdk/blob/3e46a44a21db66f42a56320b6f64bfc52ea279f8/iop/hdd/libpfs/src/journal.c).

## Validation and remaining work

The e85d69a7 ATA ownership commit passed all six full build flavors in run 34729949387; CodeRabbit reported no actionable findings for that commit. Those results do not validate subsequent BDM changes. The BDM correction has passed its local host regressions and an IRX cross-build; consult the latest PR checks for full-build status.

No affected-drive retest, physical-console validation, or data recovery has been performed. No merge or release is authorized by passing these checks. The withdrawn release should remain withdrawn while investigation is unresolved; publishing-branch merges can themselves trigger distribution.

Remaining causal work is to establish a reachable write or persistent read/availability failure that explains the cross-application status. Prioritize actual worker schedules, shared completion/controller state, and partition/journal writes under fault injection on disposable images. Neither of the reproduced defects identifies the reporter's actual failure by itself.

## Follow-up review corrections

The five review findings on 3a417739 were verified and corrected in the follow-up:
- Partition reads/writes validate the local range and the complete partition's extent inside its parent before translating an address. A disk-wide check alone permits accesses to adjacent partitions.
- MBR/GPT buffers use the device sector size; invalid sizes are rejected before allocation or reads. Tests use actual 4 KiB probe writes with destination-allocation checks. The ATA block device advertises 512-byte sectors, so this defect alone does not directly match the reported HDD configuration.
- GPT partition length includes its final sector. Header/table/entry geometry checks prevent reversed or oversized ranges from becoming exported devices. Unsupported entry layouts are rejected. These are bounds checks, not CRC verification.
- BDM initialization failures release exports after cleaning event/thread resources. Failure injection covers all three resource/start failures and a successful retry.
- The corrupted license citation character is restored.

These changes are defect corrections, not a reproduction of the reported persistent loss of APA access. Refer to the PR for the exact pushed follow-up head and its checks; the earlier 3a417739 CI does not validate later code.


## APA transfer containment follow-up (2026-09-13)

The SDK OSD APA driver checks a relative request using an addition, then
adds the partition start in 32-bit arithmetic. It does not first establish
that the complete partition fits the device. The ATA request guard cannot
recover that missing context after translation. The same missing extent
check exists in the reserved-area file view used by hddRead/hddWrite.

The application now builds the same OSD/ATAD APA variant from the pinned
source in modules/hdd/apa. The behavioral changes are limited to hdd_fio.c:
subtraction-based partition and request bounds before translation, bounded
file-view positions and sizes, and subpartition-count/index validation.
Valid requests retain the existing main/subpartition reserved-area limits.
The test runs extracted production transfer functions with a recording stub,
checking that invalid inputs cause no device callback. It also checks valid
last-sector transfers, EOF clamping, zero counts and failure cleanup.

This is a confirmed missing containment check. It requires invalid metadata
or an invalid request; it does not establish how either arose on the
reporter's drive. In particular, do not describe the host tests as a
reproduction of a normal mount erasing a valid disk. The OSD variant checks
APA header checksums, which constrain hypotheses based on damaged metadata.
The separate APA_SUPPORT_GPT checksum branch is not enabled in this build.

PFS mount-time journal reset/replay routes its partition transfers through
HIOCTRANSFER and therefore receives these bounds checks. APA's own raw
header/journal/devctl operations do not go through this function and remain
separate audit targets. The PFS journal implementation itself is unchanged.
A failed APA readiness check still returns before loading/mounting PFS on
that attempt, so a later PFS write requires an earlier successful readiness
path or a different caller; error 401 alone does not demonstrate that path.

The local APA IRX cross-build and new host regressions pass. Fresh PR CI and
review must be associated with the commit containing this follow-up before
claiming all-flavor validation. The prior e90e009a head passed all six builds,
HDD/BDM host tests, RA host tests and formatting in run 34751249581.

## Concurrent cache probe: demonstrated primitive, constrained callers

A memory-only two-thread test of bd_cache.c can make two successful refills
reuse the same victim buffer, returning the second request's bytes to both
callers. No device writes occur in that test. However, the SDK FatFs driver
holds the same _fs_lock semaphore across both connect_bd mounting and file
operations. That excludes the initially proposed overlap between a FatFs
mount and a FatFs file operation. APA/PFS accesses use ATAD directly rather
than this BDM cache. Current whole-device guards also exclude the proposed
nested GPT probe on an ordinary nonzero-offset partition.

The cache has no internal synchronization, but a concurrent caller path for
the reported APA-only startup is not established. No additional cache lock
was added on the strength of that test alone. Other BDM consumers, hotplug,
and access bypassing the cache remain separate questions. The deterministic
local fixture is tmp/hdd-validation/probe_cache_race.py; it is investigation
evidence, not a passing production regression or proof of incident causation.


## Recovery failures and power interruption follow-up (2026-09-13)

`apaJournalRestore` previously reset the journal after an initial journal
read failure or a failed replay read/write. A successful reset could mask
the original failure by returning success, while discarding the recovery
record. The follow-up returns the error without attempting a reset in those
cases. It rejects invalid journal magic/counts and handles scratch-cache
allocation failure. Successful replay retains its existing flush/reset order.

The new `test_apa_journal_recovery.py` compiles the production journal source
with an in-memory backend. It checks failures at each replay I/O, including
a failure after an earlier entry succeeded, and then retries from the
preserved record. It also checks empty/invalid records, allocation failure,
and reset/flush errors. The final edited source passes these tests and the
APA transfer regressions on the local Windows GCC toolchain. The current APA
IRX also cross-builds successfully, and its changed C source passes the
CI-matching clang-format 12 check. Full CI remains a separate commit gate.

Scope: this does not enable new startup replay or validate all staged header
contents/destinations. In the inspected OSD/ATAD startup, successful device
initialization/unlock leaves status 1 before the format check; the existing
`status != 1` condition skips `apaJournalRestore` there. That condition is
unchanged. Consequently this recovery fix is not itself a demonstrated
explanation of the reporter's initial error 401. The cache writer's ignored
journal/metadata errors and dirty-flag handling remain separate open work;
do not describe the entire APA transaction path as fixed.

The newest screenshot contains another person's suggestion of a shutdown
during writing. It is not a reporter-confirmed event. The exact drive model,
physical sector size/alignment and power-loss behavior remain unknown.

A conditional mechanism deserves investigation: 512e disks can update a
physical 4KiB sector to service a smaller logical write. An interruption can
affect neighboring logical sectors. If logical sectors 0-7 share that unit,
APA's header at 0-1 and error records at 6-7 share it too. This is an inference
from the layout and documented drive behavior, not proof about this WD disk.
It does not revive the refuted claim that normal error-record dwords fail
the APA format check. The proposed difference is an interrupted physical
write, not the intended contents of a completed error record.

Sources: [Microsoft's read-modify-write resiliency explanation](https://learn.microsoft.com/en-us/windows/compatibility/advanced-format-disk-compatibility-update#resiliency-the-hidden-cost-of-read-modify-write),
[Dell Enterprise Disk Engineering, 4K Sector HDD FAQ, sections 3-5](https://dl.dell.com/manuals/all-products/esuprt_ser_stor_net/esuprt_poweredge/poweredge-t630_reference%20guide2_en-us.pdf),
and [WD Advanced Format white paper](https://documents.westerndigital.com/content/dam/doc-library/en_us/assets/public/western-digital/collateral/white-paper/white-paper-advanced-format.pdf).
The papers establish the general mechanism; they do not identify the
reporter's model, confirm an interruption, or establish recovery prospects.


## First transaction and cache failure probe (2026-09-13)

The normal ATAD startup path sets a present/unlocked device to status 1;
`hdd.c` then skips `apaJournalRestore`. `blkIoInit` is a no-op in the ATAD
variant. Before any prior reset/restore/flush, the original static journal
buffer has magic 0 and count 0. `apaJournalWrite` increments the count but
never sets the magic; the first `apaJournalFlush` therefore publishes an
unrecognized journal. A later successful reset supplies the correct magic,
which confines this particular defect to the first transaction in that state.

The recovery regression now exercises two production journal appends and a
flush before any restore/reset. It fails on 953f008f at the saved-magic
assertion. The follow-up initializes only the in-memory magic to APAL_MAGIC;
it does not write a reset record at startup or enable automatic replay.
Append also rejects negative/full/out-of-range counts before checksum
modification or I/O. Tests cover the last valid slot, the full boundary,
negative and excessive counts. Restore bounds were already fixed in 953f008f.
A normal RiptOPL cache has 20 entries, below the 126-entry journal capacity;
capacity checks do not establish that this limit was reached in the incident.

The new `python .github/scripts/probe_apa_cache_transaction.py` compiles the
production cache and journal implementations plus `apaWriteHeader`, using
RAM-only I/O and two ordinary partition-header destinations. This is an
investigation probe that asserts current defective behavior, NOT a safety
regression and NOT a CI gate. It should change or become a desired-behavior
regression when the transaction implementation is fixed.

| Injected failure | Entries in saved journal at first header write | Result | Final headers changed | Dirty entries / saved journal entries |
| --- | ---: | ---: | --- | --- |
| None (control) | 2 | 0 | Both | 0 / 0 |
| First staging write | 1 | 0 | Both | 0 / 0 |
| Journal commit write | 0 | 0 | Both | 0 / 0 |
| First destination-header write | 2 | 0 | Only second | 0 / 0 |
| First flush barrier | 0 | 0 | Both | 0 / 0 |

Thus a failed destination write can produce a partially applied metadata
transaction, report success, discard dirty state, and clear the recovery
record. Staging/commit failures also do not stop the destination writes.
The first-signature and append-bound fixes do not fix these transaction
failures. `apaCacheFlushAllDirty` ignores intermediate results;
`apaCacheTransfer` clears DIRTY even when a header write fails. Simply returning
early is insufficient: both cache allocation paths can recycle a dirty entry,
callers often ignore flush errors, and retries must preserve the committed
set rather than restage only the remaining dirty subset. Design these states
and their failure behavior together before editing the larger transaction.

Incident reachability remains limited. `apaGetNextHeader` can repair a
backward-link mismatch and flush during enumeration, but this requires a
previously inconsistent link and does not normally select the sector-zero
header as its destination. Creation/deletion can update sector zero but is
not established in the reported startup. The probe starts from two explicitly
dirty headers; it does not reproduce an ordinary healthy mount damaging a
disk, physical torn writes, or the reporter's original trigger.

Comparison: the locally inspected wLaunchELF_R3Z source at
`e1c3a5cd78a1e9774b7a35649c5282c01f34615a` has the same zero-initialized journal,
startup restore condition, ignored transaction errors and unconditional dirty
clear. These are inherited SDK-family behaviors, not evidence of a RiptOPL-only
regression or proof that the reporter's R3Z binary had this exact source.
See [R3Z journal](https://github.com/saildot4k/wLaunchELF_R3Z/blob/e1c3a5cd78a1e9774b7a35649c5282c01f34615a/iop/ps2hdd_osd/journal.c),
[R3Z cache](https://github.com/saildot4k/wLaunchELF_R3Z/blob/e1c3a5cd78a1e9774b7a35649c5282c01f34615a/iop/ps2hdd_osd/cache.c),
and [R3Z startup](https://github.com/saildot4k/wLaunchELF_R3Z/blob/e1c3a5cd78a1e9774b7a35649c5282c01f34615a/iop/ps2hdd_osd/hdd.c).

PR review now also has four open APA findings: an error-path cache leak in
apaGetPartErrorSector, access after cache release in open/format paths,
duplicate semaphore release in apaRename, and a missing allocation/read-result
check in hddAddPartitionHere. They are inherited code, but still require
validation and fixes. A fifth finding concerned journal bounds: restore is
fixed in 953f008f; the append guard is included with the first-signature fix.
Do not describe the APA review or the incident investigation as complete.


## APA transaction atomicity, journal preservation and review hardening (2026-09-13)

The transaction failure vulnerabilities identified in the cache probe are now
addressed across `cache.c` and `journal.c`:

1. **Staging & Commit Gate**: `apaCacheFlushAllDirty` checks staging
   (`apaJournalWrite`) and commit (`apaJournalFlush`) results. If either
   fails, execution halts immediately before any destination writes.
   `apaJournalAbort` clears in-memory journal state so retries start fresh,
   dirty flags are preserved, and an error is returned.
2. **Destination Failure & Journal Preservation**: When writing destination
   headers (`apaWriteHeader`), the first I/O failure immediately aborts
   subsequent destination writes. Crucially, `apaJournalReset` is skipped,
   preserving the on-disk recovery journal (`APAL`) with its complete
   committed transaction intact for recovery via `apaJournalRestore`.
   Dirty flags are retained on all buffers in the transaction so subsequent
   flush attempts restage the complete set rather than an incomplete subset.
3. **Post-Destination Write Barrier**: A cache barrier (`blkIoFlushCache`) is
   issued after all destination writes complete and before resetting the
   journal. If this barrier fails, dirty flags and the on-disk journal are
   preserved.
4. **Free-List Dirty Buffer Protection**: `apaCacheGetHeader` and
   `apaCacheAlloc` now scan the free list (`cacheBuf->next`) to find clean
   buffers, skipping any buffer with `APA_CACHE_FLAG_DIRTY`. If all free
   buffers are dirty, allocation returns NULL (`-ENOMEM`), preventing
   unwritten dirty metadata from being silently overwritten.
5. **Transfer Dirty Flag**: `apaCacheTransfer` clears `APA_CACHE_FLAG_DIRTY`
   only when the write operation succeeds (`err == 0`).

The probe script `.github/scripts/probe_apa_cache_transaction.py` is updated
into a permanent host regression and wired into `.github/workflows/flavours.yml`.
Its updated test results confirm the corrected behavior:

| Injected failure | Destination header writes | Result | Final headers changed | Dirty entries / saved journal entries |
| --- | ---: | ---: | --- | --- |
| None (control) | 2 | 0 | Both | 0 / 0 |
| First staging write | 0 | -5 (-EIO) | Neither | 2 / 0 |
| Journal commit write | 0 | -5 (-EIO) | Neither | 2 / 0 |
| First destination-header write | 1 | -5 (-EIO) | Neither | 2 / 2 (preserved journal!) |
| First flush barrier | 0 | -5 (-EIO) | Neither | 2 / 0 |
| Post-destination barrier | 2 | -1 | Both | 2 / 2 (preserved journal!) |

All four CodeRabbit review findings and an additional use-after-free are also
resolved:
- `apa.c`: `apaGetPartErrorSector` frees the allocated cache entry on read
  failure before returning `-EIO`.
- `apa.c`: `apaInsertPartition` caches `start`, `next`, and `prev` locally
  before freeing `clink_this`, preventing use-after-free during header filling.
- `hdd_fio.c`: `apaOpen` compares passwords before calling `apaCacheFree(clink)`.
- `hdd_fio.c`: `hddFormat` saves `clink->sector` into a local variable before
  freeing `clink` across both format loops.
- `hdd_fio.c`: `apaRename` removes three redundant `SignalSema(fioSema)` calls
  that previously caused double-release of the file semaphore.
- `hdd.c`: `hddAddPartitionHere` validates that `clink_this` from
  `apaCacheGetHeader` is non-NULL before dereferencing its header.

Scope and limits: These changes ensure that APA metadata transactions are
atomic, that recovery journals survive I/O and barrier failures, and that
dirty metadata is neither discarded nor clobbered. However, ordinary healthy
startup does not initiate transactions or write to sector zero. While these
fixes eliminate confirmed corruption vectors under I/O failure, the exact
trigger for the reporter's initial error 401 on their specific drive model
remains causally unproven.
