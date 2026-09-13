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
