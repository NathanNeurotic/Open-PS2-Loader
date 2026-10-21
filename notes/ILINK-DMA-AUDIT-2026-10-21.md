# i.LINK timing and DMA audit — 2026-10-21

Audited source: `rebuild/main` / rolling tag `2808a4cd579e4294c520e35149bbfc87d79cce45`, currently packaged as Beta 4202. The two supplied Discord transcripts report builds 4107 and 4121. They are observations of those builds, not tests of current main.

Follow-up investigation: [draft PR #1031](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1031) reproduces a stale SBP-2 LOGIN completion consumed during fetch-agent initialization, premature dummy-request release, ignored initialization failure, and an endless wait after failed command submission. The candidate corrects both driver copies and rebuilds the matching POPStarter payloads. Detailed evidence is in `build/ilink-timing-investigation/docs/ILINK_TIMING_INVESTIGATION_2026-10-21.md`. The maintainer clarified that earlier boot successes were not reliable; no known-good historical baseline is assumed. This is a source/host-tested correction with console confirmation pending, not proof that all timing controls are unnecessary.

## Finding

FifthFox has already tried the fixed Mode 8 slowdown and reported failure. His request is for an adjustable timing control analogous in purpose to the HDD compatibility setting, not necessarily literal reuse of ATA controller programming. The protocol distinction below does not invalidate that request.

Do not simply extend the existing MDMA/UDMA selector to i.LINK as the proposed readiness fix. ATA transfer timing, SBP-2/SCSI readiness, and emulated optical-disc completion timing are separate controls. A carefully scoped i.LINK readiness or transport setting could be useful if diagnostics identify the failing stage; an ATA mode label would misrepresent it.

## Full reporter context and its effect on the investigation

1. Build 4107: native OPL shows the PS2 logo but does not launch; Neutrino and POPStarter also fail; Ember works.
2. FifthFox explicitly corrects the history: earlier RiptOPL revisions launched PS2 games through native OPL when the logo was enabled and particular compatibility modes were selected. The failure is therefore not established as an inherent inability of this setup to sustain PS2 gameplay. The exact successful revision, game and mode combination are not included in these pasted messages.
3. Build 4121: he reports Mode 8 is too slow, launch drops out before the handshake, and the full logo implosion appears. His speed/handshake explanation is a hypothesis; the reported failed Mode 8 test is concrete evidence and must not be treated as untried.
4. He asks whether the speed or a delay can be adjusted. Nathan proposes retaining Mode 8 for the games it targets while adding a separate per-game read-delay setting.
5. When MDMA is suggested, FifthFox explains that the existing setting applies to the internal HDD and asks for an equivalent capability for his physical i.LINK drive, with drive-specific tuning.

This supports investigating a timing-sensitive regression or compatibility condition and an adjustable control at the appropriate boundary. It does not establish that a larger delay is better, or that the control belongs at spin-up rather than reset, first-read submission, or read completion. Mode 8's failure is evidence against treating its fixed CD-rate slowdown as the solution for this report.

The two logo interpretations also need care: the earlier message associates implosion with initiation being too fast, while the later Mode 8 report describes excessive slowness with a full implosion. Preserve both reports; do not derive a speed threshold from the animation alone.

The chat's statement that MDMA inserts a few milliseconds for a physical HDD to spin up is incorrect. In OPL, the selector issues ATA SET FEATURES / transfer mode and programs the SPEED controller's MWDMA/UDMA registers. It changes ATA transfer timing. It does not implement a spin-up delay. SSDs can also have controller/bridge initialization delays, even though they have no mechanical spin-up.

Source: [xhdd/xatad.c, transfer-mode programming](https://github.com/NathanNeurotic/Open-PS2-Loader/blob/2808a4cd579e4294c520e35149bbfc87d79cce45/modules/hdd/xhdd/xatad.c#L8-L79). General protocol reference: [Linux libATA documentation, mode selection](https://www.kernel.org/doc/html/v7.0/driver-api/libata.html#set-pio-dma-mode).

## Existing support and applicability

| Target/path | Current implementation | Consequence |
| --- | --- | --- |
| Internal ATA HDD / HDL on APA | Existing MDMA/UDMA selector and ATA driver | Existing control belongs here. APA is a disk layout, not a separate transfer protocol. |
| ATA-backed BDM HDD | `BDM_TYPE_ATA` enables the selector; native launch applies the selected mode | The feature already extends beyond the legacy HDL layout. The Neutrino path branches earlier and needs its own configuration audit. |
| i.LINK enclosure | SCSI read/write commands over SBP-2; transaction speed and payload derive from iLinkman | PS2 SPEED ATA registers do not control the enclosure's disk interface. Bridge-specific ATA passthrough, if supported, would be a separate capability, not reuse of xhdd. |
| PC CARD CompactFlash | Current `pccf_bd` uses PIO polling and deliberately has no SPEED/DMA interface | Do not expose MDMA/UDMA without implementing and validating the actual controller support. A CF card attached through an ATA adapter is a different path. |
| DESR DVR ISO path | DVRP filesystem and external Neutrino `bsd-dvr` | Do not infer ATA-mode control from an HDD-shaped menu page. Audit the DVRP/Neutrino implementation separately. |

References: `src/bdmsupport.c:2747` and `:3274`, `modules/ilink/IEEE1394_bd/src/sbp2_driver.c:341` and `:563`, `modules/pccf/main.c:1`, `src/hddsupport.c:2497` in the audited revision.

## Work already merged since the quoted investigation

[PR #1022](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1022) and [PR #1024](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1024) are merged and ancestors of the current rolling tag. They add:

- An SBP-2 login retry window using elapsed time: five seconds, retrying failures at 200 ms intervals. This addresses an old login that the target may retain across an IOP reset; it is not a continuous streaming throttle.
- At most 300 SCSI TEST UNIT READY attempts with 100 ms spacing on failures, plus the existing sense/start-unit handling. Approximately 30 seconds of retry spacing is not a strict 30-second wall-clock cap because command execution also takes time.
- Refusal to publish a BDM device after failed warm-up and validation against a zero logical-block length.
- Matching changes in POPStarter's separate older driver. The standard release workflow also replaces Neutrino's `IEEE1394_bd_mini.irx` with the vendored patched build.

The existing `test_ilink_bd_reset.py` and `test_ilink_bd_assault_reset.py` both passed during this audit. These are fault-injection host tests. They do not prove FifthFox's console/enclosure works.

Published kit verification: downloaded `RIPTOPL-v1.2.0-Beta-4202.zip` from the rolling release. `POPS/usbd.irx.ilink` (48,500 bytes, SHA-256 `5ea4818ba1cf5207f6d7cadb4c13b5afa88c37c260750c21155b079a8c18f369`) and `POPS/usbhdfsd.irx.ilink` (21,977 bytes, SHA-256 `8f9a9e4e6984a58435fe7e24e1e5832f027dc537b3274bc4220245bbe1844714`) exactly match the current tracked binaries. `neutrino/modules/IEEE1394_bd_mini.irx` is 7,025 bytes, SHA-256 `fa5de3b5be8a5e1592b53e2a282895897be9ae6213d6751104a3f2fc9b0f71e1`; the successful standard release [publish log](https://github.com/NathanNeurotic/Open-PS2-Loader/actions/runs/39559975287/job/119097579006) explicitly records replacement with RiptOPL's 7,025-byte build. This is packaging/provenance evidence, not a console result.

Implementation/provenance: [vendored driver ORIGIN.txt](https://github.com/NathanNeurotic/Open-PS2-Loader/blob/2808a4cd579e4294c520e35149bbfc87d79cce45/modules/ilink/IEEE1394_bd/ORIGIN.txt), [POPStarter driver README](https://github.com/NathanNeurotic/Open-PS2-Loader/blob/2808a4cd579e4294c520e35149bbfc87d79cce45/modules/bdmassault/ilink_bd_assault/README.md).

## Interpreting the reports

- Ember success establishes that its inherited IOP/storage path can access the device. It does not exercise the same reset/reconnect sequence as native OPL or POPStarter.
- Earlier PS2 gameplay is valuable evidence against a claim that i.LINK is inherently too slow. It does not distinguish among later readiness, session, driver, or game-compatibility failures.
- Native Mode 8 changes the emulated disc-read completion timing, using 81,920 IOP ticks per 2,048-byte sector rather than DVD Mode 1's 33,512 ticks. The driver still performs the underlying read. It does not tune SBP-2 login, ATA DMA, or the enclosure's startup behavior. See `modules/iopcore/cdvdman/cdvdman.c:299` and `:359`.
- A logo appearing, looking distorted, or completing its animation is not a calibrated measurement of disk speed or handshake state. Keep those observations, but identify the driver stage and read result before assigning a cause.
- The i.LINK Neutrino path already adds `-qb`. Automatic suppression of the global `-logo` option still excludes i.LINK in the audited source (`src/system.c:2173`), so logo off/on remains a meaningful separate A/B variable. This is a source-backed investigation lead, not a confirmed fix.

## Recommended next step

Proceed from the current source and the reproduced completion-ordering failures in draft #1031. Earlier successful combinations were not reliable, per the maintainer, so recovering a historical known-good build is no longer a prerequisite. Do not repeat Mode 8 as the proposed solution. First test synchronization to the target's own completion without mixing in new delays; if it still fails, use the failing stage to select the next timing experiment.

Separately establish whether FifthFox has tested Beta 4202 with the matching updated loose POPStarter drivers and Neutrino modules. The pasted logs alone do not establish that. A newer ELF with old loose IRX files is not a complete test of the merged reconnect fixes. Version verification is bookkeeping for a controlled test, not a substitute for investigating his already reported timing-dependent results.

If failure persists, collect one diagnostic run showing: SBP-2 login result/time, TEST UNIT READY/sense result, capacity, BDM publication name/device number, native CDVD binding, and first failing sector read. Keep results separate for native OPL, Neutrino, and POPStarter and avoid logging to the failing i.LINK disk.

Choose any additional control from that evidence:

1. Failure before readiness: improve bounded retry/readiness handling at that boundary. Any override belongs to the physical device/enclosure and must reach the driver after each reset.
2. Ready device but failed transfers: investigate SBP-2 command status, negotiated speed/payload, transfer size, or command pacing. A proven transport compatibility option should use i.LINK-specific terms and retain automatic defaults.
3. Successful transfers but game-sensitive completion timing: a native-core optical read-rate override may be appropriate. Keep it separate from transport readiness and do not imply it affects Neutrino or POPStarter.

Do not add a universal sleep, automatic persistent per-game tuning, or a cross-device MDMA menu based only on logo appearance. No runtime behavior was changed by this audit, and issue #1018 remains open for console evidence.
