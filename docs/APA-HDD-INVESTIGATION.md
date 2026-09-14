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


## Startup write-path trace, apaGetNextHeader, and error 401 mapping (2026-09-13)

### Error 401 resolved

"Error 401" is an OPL EE-side error code (`ERROR_HDD_NOT_DETECTED = 401` in
`include/iosupport.h`, enum `ERROR_CODE`). It is displayed as a numeric suffix
by `setErrorMessageWithCode()` and `setErrorMessageWithCodeAndDetail()`, paired
with one of several string IDs (`_STR_HDD_NOT_CONNECTED_ERROR`,
`_STR_HDD_UNAVAILABLE_ERROR`, or `_STR_HDD_APA_REJECTED_ERROR`).

The code fires in `src/hddsupport.c` on three distinct paths:

1. **Non-Sony probe devctl error** (transient bus fault, module missing,
   drive mid-seek): `nonSony < 0` at line 651 → `_STR_HDD_NOT_CONNECTED_ERROR`
   with code 401. The module has not yet loaded; the drive may still be
   physically healthy.

2. **`hddCheck()` returns negative** (line 682-684): `fileXioDevctl("hdd0:",
   HDIOC_STATUS)` returns a negative fileXio error. This means ps2hdd.irx
   loaded but the devctl itself failed (unusual) OR the IOP hdd module
   exited early with `MODULE_NO_RESIDENT_END` before registering `hdd0:`.
   `MODULE_NO_RESIDENT_END` fires if journal restore fails (line 328-330
   of IOP `hdd.c`), file-slot allocation fails, or cache init fails. In
   those cases `hdd0:` is never registered; `hddCheck()` sees a negative
   return from fileXio. → `_STR_HDD_NOT_CONNECTED_ERROR` with code 401.

3. **`hddCheck()` returns 2** (line 705-710): IOP `hddDevices[device].status`
   remained at 2, meaning ATA found the disk but unlock failed (password-
   locked drive). → `_STR_HDD_UNAVAILABLE_ERROR` with code 401.

4. **`hddCheck()` returns 1 with raw APA match** (line 694-696): ps2hdd
   loaded, drive detected and unlocked, but `apaGetFormat` returned 0
   (unformatted/rejected) even though the EE raw probe found an APA magic
   at sector 0. → `_STR_HDD_APA_REJECTED_ERROR` with code 401. This is the
   most diagnostically informative branch: it means sector 0 was readable
   with APA magic but `apaGetFormat`'s sector-6/7 check failed (all non-
   skipped dwords must be 0, or the sector read itself failed).

`hddCheck()` returns 0 (formatted OK) only when IOP status reaches 0: disk
detected, unlocked, and `apaGetFormat` returned 1 (all 254 checked dwords in
error-sectors 6/7 are zero, or sector read returned `rv == 0`).

The reporter's symptom ("repeated error 401, no usable listing") is consistent
with path 1 (transient probe), path 2 (IOP module exit), or path 4 (APA
rejected). Path 4 is the most probable if the drive was previously healthy and
accessible: it means the APA format signature was readable but the error-sector
check failed — which would happen if sectors 6/7 had non-zero content in the
checked positions, or if a read of sectors 6/7 itself returned an error. The
latter is consistent with sectors 6-7 being physically unreadable after
corruption or a torn write (see 512e hypothesis in the "Recovery failures"
section above).

### hddInit startup write-path: no sector-zero write on healthy mount

The full IOP startup sequence is:

```
hddInit()
  → sceAtaInit(device)     [detects disk, hddDevices[i].status: 3→2]
  → unlockDrive(device)    [unlocks, hddDevices[i].status: 2→1]
  → apaCacheInit(cacheSize)
  → if (status != 1): apaJournalRestore(i)   [SKIPPED on clean unlock]
  → apaGetFormat(i, &format)
      → apaReadHeader(device, clink->header, 0)   [reads sector 0 only — READ]
      → blkIoDmaTransfer(device, clink->header,
            APA_SECTOR_SECTOR_ERROR, 2, BLKIO_DIR_READ)  [reads sectors 6-7 — READ]
      → checks 254 dwords, returns 1 (formatted) or 0 (rejected)
  → if (apaGetFormat returned 1): status: 1→0
  → blkIoInit()   [no-op in ATAD variant]
  → iomanX_AddDrv(&hddFioDev)
```

**Conclusion: ordinary healthy startup performs two reads (sector 0, sectors
6-7) and zero writes. No sector-zero write, no partition-chain enumeration,
no journal flush.**

### apaGetNextHeader: conditional flush trace

`apaGetNextHeader` (apa.c:509-527) is called during partition enumeration by:
- `apaGetPartErrorName` (apa.c:83-94): walks the chain to find a partition
  by the LBA stored in the error-record sector.
- `apaFindPartition` (apa.c:187): finds a named partition during open/create.

Neither of these is called during `hddInit`. `apaGetFormat` does not call
`apaGetNextHeader` or `apaFindPartition`. Partition enumeration only occurs
when an HDD operation (open, create, rename, delete, dread) is executed after
the driver is loaded.

When called, `apaGetNextHeader` does the following:
1. Saves `clink->header->start` as local `start`.
2. Frees the current cache entry (`apaCacheFree`).
3. Reads the next header at `clink->header->next` via `apaCacheGetHeader`.
4. Compares `start` with the newly loaded header's `prev` field.
5. **If `start != header->prev`**: logs a warning, sets `header->prev = start`,
   marks the cache entry dirty, and calls `apaCacheFlushAllDirty(device)`.

The flush at step 5 writes the corrected prev-link back to disk. The
destination sector is whatever partition follows in the chain — it is not
sector 0 unless the partition chain is already arranged such that the second
partition begins at sector 0, which is the APA MBR and would be a pre-existing
structural defect.

**Conclusion: `apaGetNextHeader` can write to disk during enumeration, but
only when a prev-link mismatch already exists (pre-existing inconsistency),
and its destination is the following partition's header sector, not sector zero
unconditionally. It is not reachable during startup before `hdd0:` is
registered.**

### Causal certainty: remaining gap

After this trace, the following is established by static inspection:

| Question | Answer |
| --- | --- |
| Does healthy startup write to sector 0? | No. Only two reads (sector 0, sectors 6-7). |
| Does `apaGetNextHeader` run during startup? | No. Called only from partition enumeration, after driver loads. |
| Can `apaGetNextHeader` write sector 0? | Only if a mismatch and sector-0-adjacent chain already exist. |
| What does "error 401" mean? | OPL internal `ERROR_HDD_NOT_DETECTED = 401`. Four distinct paths. |
| Which path matches "repeated 401 on working disk"? | Most likely path 4: APA magic present but format check rejected; sector 6/7 unreadable or has non-zero checked dwords. |
| Is the exact trigger confirmed? | No. Drive model, physical sector size, prior write history, and disk image remain unknown. The 512e torn-write hypothesis is the strongest uninvestigated candidate. |

The confirmed fixes (transaction atomicity, journal preservation, dirty
eviction safety, UAF/semaphore findings) eliminate corruption paths that
could have produced the reported state under I/O failure. They do not
prove that those paths were taken in the specific incident. Causal
certainty requires a disk image or a reproducible write-sequence test
that produces sector 6/7 corruption from an ordinary OPL session.


## Sector 6-7 write-path exhaustion, deletion MBR writes, and additional UAF hardening (2026-09-13)

### Exhaustive sector 6-7 write-path analysis (probe_apa_format_rejection.py)

To determine whether any combination of normal driver writes can produce
the format-rejection state without physical hardware fault or torn write, all
write paths touching sectors 6 and 7 were analytically exhausted:

1. **`apaSaveError(APA_SECTOR_SECTOR_ERROR, err_lba)`** (called by
   `apaCacheTransfer` on any header read failure): zeroes the 512-byte buffer
   and writes `err_lba` into dword 0. Dword 0 is at offset 0 (`pDW[0]`), which
   is explicitly skipped by `apaGetFormat`'s `(i & 0x7F)` mask. All other 127
   dwords in sector 6 remain zero. Always passes `apaGetFormat`.
2. **`apaSetPartErrorSector(lba)`** (called by `HIOCSETPARTERROR` and
   `apaGetPartErrorName` error-clear): zeroes the 512-byte buffer and writes
   `lba` into dword 0 of sector 7. This corresponds to `pDW[128]` in the
   two-sector read, which is also skipped by `(128 & 0x7F) == 0`. All other
   127 dwords in sector 7 remain zero. Always passes `apaGetFormat`.
3. **`hddFormat`**: zeroes a full 1024-byte buffer and writes 512 bytes of
   zeros to sector 6, then 512 bytes of zeros to sector 7. Always passes.
4. **Sequences of error writes**: because each error write zeroes the full
   512-byte sector before placing the LBA in dword 0, repeated error writes
   never accumulate dirty dwords in non-skipped slots.
5. **No other normal driver path writes to sectors 6 or 7**:
   - Journal writes: sector 8+ (`APA_SECTOR_APAL`).
   - Partition creation writes: `partition_start + 8` and `partition_start +
     0x2000` (always $\ge 256 \times 1024$ sectors).
   - Data / file transfers (`ioctl2Transfer`, `fioDataTransfer`): guarded by
     APA reserved-area limits ($\ge 0x2000$ for main, $\ge 2$ for sub).

**Proved**: Normal OPL driver operation *cannot* produce non-zero checked dwords
in sectors 6 or 7. Format rejection (path 4 of error 401) requires either:
- A pre-existing structural defect (e.g. an APA partition starting at LBA 6,
  causing a 1024-byte partition header to be flushed across sectors 6 and 7); OR
- A physical write event outside the driver's intentional semantics, notably
  the **512e torn-write hypothesis** (power loss or reset during a 4KiB
  read-modify-write cycle encompassing logical sectors 0 through 7).

The analytical probe is added to `.github/scripts/probe_apa_format_rejection.py`
and wired into `.github/workflows/flavours.yml`.

### Partition deletion writes to sector zero (MBR)

The reporter's narrative specifically notes: *"repeated RiptOPL error 401,
unsuccessful configuration/data deletion, and then loss of access"*.

Investigation of `apaDelete` (`apa.c:365-411`) reveals that deleting a
partition at the tail of the disk (`clink->header->next == 0`) executes:

```c
clink_mbr = apaCacheGetHeader(device, APA_SECTOR_MBR, APA_IO_MODE_READ, &rv);
do {
    ...
    clink_mbr->header->prev = clink->header->start;
    clink_mbr->flags |= APA_CACHE_FLAG_DIRTY;
    apaCacheFlushAllDirty(device);
} while (clink->header->type == 0);
```

Because APA maintains a doubly-linked ring where the MBR's `prev` pointer
identifies the last partition on disk, **deleting the tail partition modifies
and flushes Sector 0 (APA_SECTOR_MBR)**. If an I/O failure or power loss
occurred during this deletion flush prior to the transaction atomicity fixes in
this PR, sector 0 was directly exposed to partial writes and uncommitted journal
state.

### Three additional use-after-free defects in apa.c

Auditing all `apaCacheFree` call sites revealed three further use-after-free
defects in `modules/hdd/apa/src/apa.c`:

1. **`apaGetNextHeader` (lines 513-520)**:
   `apaCacheFree(clink)` was called *before* evaluating `clink->header->next`
   and `clink->device` for the next header read. Because `apaGetNextHeader` is
   the core traversal function used by `apaFindPartition`, `apaGetFreeSectors`,
   and `fioDread`, every single partition enumeration step accessed freed
   memory. If the buffer was recycled by `apaCacheAlloc` during the traversal,
   the link address was read from modified memory.
   *Fix*: Save `start`, `next = clink->header->next`, and `device =
   clink->device` into local variables before calling `apaCacheFree(clink)`.

2. **`apaDeleteFixNext` (lines 343-344)**:
   `apaCacheFree(clink1)` was called *before* evaluating `lnext = header->next`
   (where `header = clink1->header`).
   *Fix*: Read `lnext = header->next` before calling `apaCacheFree(clink1)`.

3. **`apaDelete` (lines 384-386)**:
   In the backward-merge loop for tail partition deletion, `apaCacheFree(clink)`
   was called *before* evaluating `clink->header->prev` and `clink->device`.
   *Fix*: Save `u32 prev = clink->header->prev;` before calling
   `apaCacheFree(clink)`, and pass saved `device` and `prev` to
   `apaCacheGetHeader`.

### Subpartition array bounds hardening in hdd_fio.c

Four subpartition array access paths lacked validation against `APA_MAXSUB`:
- **`apaRemove`**: checked password but not `clink->header->nsub > APA_MAXSUB`
  before decrementing loop; would read out-of-bounds `subs` indices if corrupted;
  returns `-EINVAL`.
- **`fioGetStatFiller`**: computed `totalsize` by summing up to
  `clink->header->nsub` without bounding to `APA_MAXSUB`; clamped to
  `APA_MAXSUB`.
- **`ioctl2AddSub`**: checked `fileSlot->nsub < APA_MAXSUB` but not
  `clink->header->nsub >= APA_MAXSUB` before indexing
  `clink->header->subs[clink->header->nsub]`; added check returning `-EFBIG`.
- **`ioctl2DeleteLastSub`**: did not check `fileSlot->nsub > APA_MAXSUB` or
  `mainPart->header->nsub == 0 || mainPart->header->nsub > APA_MAXSUB`; would
  underflow or index out-of-bounds; added checks.


## Error propagation, leak fixes, GPT layout incompatibility, and volatile cache trace (2026-09-13)

### Flush error propagation and resource leak hardening (apa.c & hdd_fio.c)

A systematic audit of all `apaCacheFlushAllDirty` calls and error return paths identified several unhandled failure points and resource leaks:

1. **`apaInsertPartition` (`apa.c`)**:
   - `apaRemovePartition()` return value was dereferenced unconditionally without checking for `NULL` (`clink_empty->header->start`). If memory allocation or header reading failed during partition splitting, this triggered an immediate NULL pointer dereference crash. Added NULL check returning `-ENOMEM` after freeing allocated headers.
   - Return values of `apaCacheFlushAllDirty()` during block splitting and header initialization were previously ignored. They are now captured into `*err` with proper cleanup and early return on failure.

2. **`apaDelete` (`apa.c`)**:
   - When backward-traversing partitions during tail deletion (`clink->header->next == 0`), if `apaCacheGetHeader(device, prev, ...)` failed, the loop previously executed `return 0;`. This leaked the allocated `clink_mbr` header and falsely reported success for an unapplied deletion. Fixed to call `apaCacheFree(clink_mbr)` and return `rv`.
   - `apaCacheFlushAllDirty()` errors during tail deletion backward merge and non-tail deletion are now captured and propagated instead of returning success.
   - Non-tail partition fix loops (`apaDeleteFixPrev` / `apaDeleteFixNext`) previously returned `0` on NULL return. They now propagate the actual error code `rv`.

3. **`hdd_fio.c` flush error propagation**:
   - `apaRemove`, `apaRename`, `ioctl2AddSub`, `ioctl2DeleteLastSub`, and `devctlSwapTemp` now check and return the result of `apaCacheFlushAllDirty(device)` rather than returning 0.
   - `devctlSetOsdMBR`: on GPT builds (`#ifdef APA_SUPPORT_GPT`), if `mbrInfo->start < APA_SECTOR_MIN_OSDSTART`, the function previously returned `-EINVAL` without freeing `clink`. Fixed to call `apaCacheFree(clink)`. The return value of `apaCacheFlushAllDirty(device)` is now captured and returned.

### Architectural finding: GPT layout incompatibility causes false Error 401

Investigation of the interplay between the EE-side `hddDetectNonSonyFileSystem()` probe and IOP-side `ps2hdd` revealed an architectural defect that produces a false "HDD APA format rejected (401)" on modern GPT-partitioned drives:

1. **Checksum scope divergence**:
   - `hddApaHeaderValid()` in `src/hddsupport.c` sums only the first 128 dwords (`i < 128`, sector 0), treating this as sufficient to detect APA magic.
   - On a disk formatted with GPT-APA support (e.g. via modern wLaunchELF or ps2sdk's `apa-gpt`), Sector 0 (Protective MBR) is stamped with an APA header whose checksum is computed with `fullcheck = 0` (128 dwords) because Sector 1 is the Primary GPT Header (`"EFI PART"`), not an APA subpartition table.
   - However, OPL's `modules/hdd/apa` is compiled *without* `APA_SUPPORT_GPT`. In `apaReadHeader()`, without `APA_SUPPORT_GPT`, the driver strictly checks `apaCheckSum(header, 1)` (256 dwords / 1024 bytes). Sector 1 containing the GPT header causes this checksum to fail with `-EIO`.

2. **Sector 6-7 layout collision**:
   - On a legacy APA disk, Sectors 6 and 7 are reserved for `APA_SECTOR_SECTOR_ERROR` and `APA_SECTOR_PART_ERROR`.
   - On a GPT-partitioned disk, Sectors 2 through 33 contain the GPT Partition Array (each entry is 128 bytes; Sectors 6 and 7 hold Partition Entries 17 through 24).
   - In GPT-APA (`libapa.h`), `APA_SECTOR_SECTOR_ERROR` is moved to Sector **34**.
   - When OPL's non-GPT driver boots, `apaGetFormat()` reads Sectors 6 and 7. If the drive has GPT partition entries or non-zero initialization in those sectors, `apaGetFormat()` finds non-zero dwords and rejects the drive (`status = 1`).

3. **The Error 401 symptom**:
   - EE-side `hddDetectNonSonyFileSystem()` checks Sector 0, finds valid APA magic and matching 128-dword checksum, and returns `0` (APA detected).
   - IOP-side `ps2hdd` rejects the drive (`status = 1`) due to the checksum mismatch or non-zero data in Sectors 6-7.
   - OPL EE observes `status == 1` but `hddDetectNonSonyFileSystem() == 0`, logs `"HDD: raw APA probe matched but ps2hdd reports unformatted; cause unknown."`, and displays **`_STR_HDD_APA_REJECTED_ERROR` with code `ERROR_HDD_NOT_DETECTED` (Error 401)**!

### Volatile write cache and power-down without cache barrier

Analysis of disk shutdown and standby behavior revealed an additional vulnerability:
- Modern HDDs (particularly Advanced Format 512e drives like Western Digital Caviar Green/Blue/Red) enable volatile onboard write caching by default.
- In `hddShutdown()` (`src/hddsupport.c`), when tearing down HDD support or shutting down the console, `hddSetIdleImmediate()` is called to issue `HDIOC_IDLEIMM` (`ATA_C_IDLE_IMMEDIATE`), followed by `sysShutdownDev9()` to power off the DEV9 controller.
- `fileXioDevctl("hdd0:", HDIOC_FLUSH)` (`ATA_C_FLUSH_CACHE` / `ATA_C_FLUSH_CACHE_EXT`) is **not** called during `hddShutdown()`.
- If uncommitted data remains in the drive's volatile cache when DEV9 power is cut, or if an internal 4KiB Read-Modify-Write cycle is interrupted by power loss, sectors 0-7 (sharing the first physical 4KiB sector) are subject to torn writes and physical corruption.


## GPT probe priority fix, shutdown write cache flush, and subpartition removal guard (2026-09-13)

### 1. Root Cause Resolution: GPT "EFI PART" Priority (Fixing Commit ad6a8d5ae Regression)

On August 20, 2026, commit `ad6a8d5ae` (*"hdd: let a valid APA header outrank the MBR/GPT signature in the probe"*) moved the APA header check ahead of the MBR and GPT checks in `hddDetectNonSonyFileSystem()`.

On any drive formatted with GPT-APA partitioning (common with modern wLaunchELF builds and PC management tools):
- Sector 0 contains an APA protective MBR with a valid 128-dword checksum.
- Sector 1 contains the Primary GPT Header (`"EFI PART"`).
- Sectors 2 through 33 contain the GPT Partition Entry Array (Sectors 6 and 7 hold Partition Entries 17 through 24).

Because OPL's vendored `modules/hdd/apa` is built **without** `APA_SUPPORT_GPT`:
1. `apaReadHeader` strictly validates 256 dwords (`apaCheckSum(header, 1)`), which fails with `-EIO` because Sector 1 is a GPT header rather than an APA subpartition table.
2. Even if header reading succeeded, `apaGetFormat` reads Sectors 6 and 7. Because these sectors contain GPT partition entries, the non-zero dwords fail the format check (`status = 1`).
3. OPL EE's probe sees `hddDetectNonSonyFileSystem() == 0` (APA matched) but IOP `status == 1` (unformatted). It logs `"raw APA probe matched but ps2hdd reports unformatted"` and raises **Error 401 (`_STR_HDD_APA_REJECTED_ERROR`)**.
4. **Destructive Corruption Vector**: If non-GPT `ps2hdd` is loaded on this disk and any write operation occurs:
   - Writing an error record (`apaSaveError`) writes to Sector 6 (`APA_SECTOR_SECTOR_ERROR`), destroying GPT Partition Entries 17–20.
   - Writing an APA journal (`APAL`) writes to Sector 8+, destroying GPT Partition Entries 25+.
   - Once GPT partition entries are overwritten, even wLaunchELF GetHddInfo reports: **Connected: YES, Formatted: NO**, matching the exact state reported in the incident!

**Fix**: In `hddDetectNonSonyFileSystem()`, check Sector 1 for `"EFI PART"` (`strncmp(&pSectorData[0x200], "EFI PART", 8) == 0`) *before* evaluating Sector 0 APA magic. If `"EFI PART"` is present, the disk is immediately classified as GPT (`result = 1`), preventing non-GPT `ps2hdd.irx` from loading, preventing false Error 401, and protecting GPT partition tables from destructive writes.

### 2. Volatile Write Cache Flush in `hddShutdown`

`hddShutdown()` now ensures that:
1. All open file descriptors on `pfs:` are closed via `PDIOC_CLOSEALL`.
2. Active PFS partitions (`pfs0:`, `pfs1:`) are unmounted via `fileXioUmount`.
3. An ATA write cache flush barrier (`HDIOC_FLUSH` / `ATA_C_FLUSH_CACHE` / `ATA_C_FLUSH_CACHE_EXT`) is issued via `hddFlush()` before `hddSetIdleImmediate()` and `sysShutdownDev9()`.
This eliminates torn writes and lost dirty blocks in drive onboard RAM during console shutdown or sleep on Advanced Format 512e drives.

### 3. Subpartition Removal Guard in `apaRemove`

In `modules/hdd/apa/src/hdd_fio.c`, `apaRemove()` previously looped through subpartitions and called `clink2 = apaCacheGetHeader(...)`. If reading a subpartition header failed, the loop silently skipped that subpartition and proceeded to delete the main partition. This left the subpartition orphaned and leaked on disk.
Fixed to check `!(clink2 = apaCacheGetHeader(...))` and immediately abort returning `rv`.

### 4. Partition Creation & Link Fix Error Propagation (apa.c & hdd.c)

A complete audit of all remaining `apaCacheFlushAllDirty` invocations identified three unhandled flush points:
- In `apaDeleteFixPrev` and `apaDeleteFixNext` (`apa.c`), merging adjacent empty partitions during deletion ignored flush failures, returning `clink` as success even when header flushes failed. Fixed to capture `*err = apaCacheFlushAllDirty(device)` and return `NULL` on error.
- In `apaGetNextHeader` (`apa.c`), auto-correcting an inconsistent `prev` link flushed without error checking. Fixed to propagate `flush_rv` into `*err` and return `NULL` on failure.
- In `hddAddPartitionHere` (`hdd.c`), `clink_new = apaRemovePartition(...)` was dereferenced without checking for `NULL`, and flush failures during intermediate block splitting and header filling were discarded. Fixed with NULL checks and flush error propagation.



