# Plan: early PS2 PC CARD CompactFlash support (RiptOPL)

**Status:** Planning / agent handoff. **Scope:** Native CompactFlash PC CARD as a distinct BDM game-storage backend within RiptOPL. **Target base:** `rebuild/main`.

## Purpose and non-goals
Plan-only draft PR for native CompactFlash/SD-to-CF access via the *original PS2 PC CARD slot*, based on [mihhru/PS2CF 1.0](https://github.com/mihhru/PS2CF). Other agents should add **implementation commits to this same branch/PR**, updating this checklist as evidence accumulates. **No production code is implemented by this initial commit**. No firmware changes, memory-card image installation, FMCB packaging, blanket storage replacement, or existing save modification are in scope.

Target hardware: SCPH-10000 (PS2CF hardware tested), SCPH-15000 / SCPH-18000 (targeted but unconfirmed separately). Exclude expansion-bay PS2, Slim, and DESR unless separate hardware evidence establishes compatibility. CF/ATA through a compatible PCMCIA Type II adapter, optionally MicroSD via SD-to-CF bridge. Supported storage filesystem goal: MBR FAT32/exFAT, ordinary OPL/launcher file semantics. Hardware/bridge/card combinations remain unverified until independently tested.

## Shared architecture / detection contract
1. Reuse cached `rom0:ROMVER` and, where available, actual console model as a **cheap eligibility hint**, not proof of PCMCIA or storage. Do not assume all ROM 1.x machines are PC CARD; unknown ROMVER must not create a false positive. Preserve existing `rom0:PSXVER` special casing.
2. Do a read-only, bounded hardware-family check of DEV9 revision (`0xBF80146E` / `REV & 0xF0`): PS2CF's retail PCMCIA path expects `0x20`, whereas expansion-bay `0x30` is not this driver. Only perform register access on a compatible mapped/known-safe hardware path; reject unknown statuses rather than touching control registers.
3. **PCMCIA != CF**: an early LAN PC CARD or empty slot is not a CF device. Before any power, reset, CIS/configuration, or ATA probe, determine ownership. Never seize an active DEV9/network/HDD/other driver. Build an explicit mutually exclusive ownership policy for the PC CARD bus; if busy, report unavailable without changing it. Investigate how to obtain a truthful owner state rather than depending on ROMVER alone.
4. On the permitted path, perform a bounded, recoverable, **driver-owned** PC CARD presence + CIS/CF memory profile and ATA IDENTIFY probe; validate sector capacity, supported LBA28/48, and a FAT32/exFAT MBR partition. Reuse PS2CF's conservative timings, bounded transfers, read fallback, and write verification where applicable. Restore all modified registers on failure; never reset unrelated hardware. Only register `cf:/`/CF BDM when a compatible card is ready.
5. Device lifecycle: absent/unrecognized media -> disabled/unavailable; failed mount -> explicit reason; failed read/write/removed card -> clean error, invalidate handles, no aliasing a different storage device. Power-off/reboot/IGR paths must not leave stale registration or an active bus owner. Do not silently auto-retry destructive initialization. Support manual refresh after a failed detection; preserve other device stacks.
6. Test cross-device interaction and *boot recovery* before enabling auto-start. No global disabling of Ethernet, UDPFS, SMB, HDD, MMCE, MX4SIO, USB, iLink, Ember, or RetroAchievements. Hardware-specific conflicts may require explicitly unavailable combinations and informative UI rather than pretending unsupported concurrency works.
7. Treat PS2CF's v1 dedicated session as a compatibility baseline, **not** a drop-in global patch. Its OPL has `sysInitDev9()` short-circuited and its CF session excludes competing DEV9/HDD/SMB; our integrated builds cannot adopt that unconditionally.

## Source references and licensing
- Upstream release: https://github.com/mihhru/PS2CF
- PC CARD hardware/ownership/reset and conservative PIO: https://github.com/mihhru/PS2CF/blob/main/src/opl/modules/pccf/pccf_hw.c
- Block device and game variant: https://github.com/mihhru/PS2CF/blob/main/src/opl/modules/pccf/main.c
- Validation: https://github.com/mihhru/PS2CF/blob/main/VALIDATION.md
- Build requirements: https://github.com/mihhru/PS2CF/blob/main/BUILDING.md
- Origin and license inventory: https://github.com/mihhru/PS2CF/blob/main/THIRD_PARTY_NOTICES.md
- Preserve file-level author notices and original component licenses (OPL AFL-3.0; PS2SDK-derived PC CARD hardware AFL-2.0; FatFs its own terms; wLaunchELF upstream notices). Import only needed compatible source; do not transplant PS2CF's FMCB/Gen2 image or bundled GPLv3 mymc++ tooling into runtime.
- Keep PS2CF author credited in code, documentation, releases, and relevant GUI credit screens.

## Agent handoff discipline
- Continue this branch; use one draft PR per repository, not a PR per subfeature. Coordinate the shared low-level driver ABI and lifecycle with the companion PR in the other repository without coupling release schedules.
- Track implementation commits and host test evidence in this plan; state explicitly what is modeled, what was run on PCSX2, and what requires real early-PS2 hardware.
- Keep unrelated regressions and refactors out. Do not merge or publish CF compatibility claims without a review of conflicts, successful builds, and actual hardware evidence.


## RiptOPL implementation map
- Existing build architecture: `Makefile` builds `bdm`, `bdmfs_fatfs`, `usbmass_bd`, `mx4sio_bd`, `bdm_cdvdman`, `bdm_ata_cdvdman`, and separate network and MMCE variants. Add a distinct CF backend; **do not** alias it to USB, HDD APA, UDPFS, or MX4SIO; do not rewrite existing device selection assumptions.
- Upstream CF delta: PS2CF adds `modules/pccf` producing `pccf_bd.irx` (menu), `pccf_game.irx` (in-game read-only), and `pccf_cdvdman.irx` (dedicated game CDVD backend); see PS2CF `src/opl/Makefile`, `src/system.c`, and `modules/iopcore/cdvdman`. Port the smallest compatible set and reconcile loader module IDs, EE/IOP argument ABI, IOPRP bundling, link order, and game reload/IGR. A compile success alone is not proof of a working game pipeline.
- Detection: ROMVER/model eligibility as hint, DEV9 controller revision `0x20` confirmation, actual card/CF profile + ATA/volume probe. Defer power/adapter reset until the CF storage session explicitly owns PC CARD. Never interfere with an existing LAN PC CARD session. Report CF absent/unsupported/busy states without interrupting other game storage.
- Menu and game inventory: integrate CF as a named selection/source under existing UI, with correct `DVD/`, `CD/`, `ART/`, `CFG/` and per-game/playlist paths. Continue RiptOPL's **existing** PS2 art prefixes / PS1 VCD filename art conventions; do not silently adopt PS2CF/upstream naming or enable PS1 over CF without its own validated backend. Handle FAT32 and exFAT, >4-GiB ISO, ordinary multi-sector reads, fragmentation limitations.
- Runtime: independent CF game source selection, in-game read-only CF backend, correct module life cycle across boot, game handoff, reset/IGR and reopen. Validate per-game modes and no writes during game. Memory-card saves remain independent; **CF-hosted OPL VMC is out of scope** until a separate supported in-game write design exists.
- Network and RetroAchievements: PC CARD LAN and CF cannot be assumed concurrent; disable only incompatible per-session combinations and show reason, not a global `sysInitDev9() { return; }` patch. Preserve RA features and network loading for every existing device. CF + live RA telemetry is **unverified** and must not be advertised without an architectural solution or hardware test. Avoid breaking Mode 6, xeRAbora or PS1 features.
- Device settings: detect on demand / safe auto-discovery, clear CF source visibility, per-game/global settings only where meaningful, manual re-probe. Do not change retained settings for other sources. Keep PS2-Servers/UDPFS behavior unchanged.
- Build packaging: reconcile PS2CF's PS2DEV 2.0.0 environment with RiptOPL's current Docker builds, tool versions and unique module names. Ensure all appropriate build profiles, including RA variants, either build with an explicit *supported* CF capability or continue building unaffected without it. No firmware/card-image changes.
- Docs: README, device support matrix, site/wiki/gh-pages where applicable, credits, troubleshooting and release notes; clearly distinguish prototype host tests from hardware success.

## Work stages and acceptance
- [ ] O0: Map source enumeration to launch pipeline and DEV9/IOP ownership on `rebuild/main`. Compare PS2CF patches structurally; document necessary migrations. Add ROMVER + DEV9 family + active LAN ownership and no-CF fixtures.
- [ ] O1: Bring in licensed CF PIO/ATA+BDM menu source as optional/on-demand backend. Validate PCMCIA vs expansion bay, empty slot, network PC CARD, adapter absent, unsupported bridge, card removal, bounded timing, LBA28/48 and failure cleanup.
- [ ] O2: Integrate CF with game enumeration and disk/partition path handling; match existing RiptOPL ART/CFG/game ID naming and keep other devices' game lists unaffected.
- [ ] O3: Integrate `pccf_game` and `pccf_cdvdman` with IOPRP/runtime module dispatch and in-game read-only CD/DVD access; cross-check game launch, mode compatibility, reboot, IGR and cold restart; do not ship VMC/RA support claims without proof.
- [ ] O4: Guarantee coexistence/fail-closed behavior for other sources and global device options: USB (one and two sticks), MX4SIO, MMCE, internal HDD APA/exFAT, SMB, UDPFS/UDPBD, iLink, HTTP, and PS1 Ember/POPStarter. Specifically regression-test network/RetroAchievements builds even if CF+LAN on one PC CARD port remains unsupported.
- [ ] O5: Build each shipping variant as relevant; run upstream CF ASan/UBSan/MMIO/bounds/filesystem tests and project-specific host/build tests. Test >4-GiB exFAT ISO and FAT32 games, MBR validation, high-address LBA48 and recoveries.
- [ ] O6: Validate on actual SCPH-10000 + compatible CF adapter, separately record 15000/18000 as unconfirmed unless tested. Record games and revisions, device model/bridge, data path, cold boots, FMV behavior, save path, file hashes/diagnostics. Separate PCSX2/host evidence from real hardware.
- [ ] O7: Update documentation, capabilities, credits, and compatibility table. Preserve existing single-PR consolidation practice: this is the one CF PR, not many small follow-on PRs.

**Merge gate:** no regressions to existing loader sources, no unconditional DEV9 suppression, no false RA/VMC claims, no driver theft, reproducible builds, documented real-console validation, and review of interaction with any concurrent consolidated regression PRs (including #894 when applicable).
