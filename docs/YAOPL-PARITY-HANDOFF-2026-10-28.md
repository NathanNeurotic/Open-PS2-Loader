# YAOPL parity / compatibility-hardening agent handoff — 2026-10-28

**Target:** `NathanNeurotic/Open-PS2-Loader` (`legacy C edition`), branch `rebuild/main`.
**Reference:** [YAOPL](https://github.com/yaopl/yaopl), maintained by [belomaxorka](https://github.com/belomaxorka); source baseline `yaopl/yaopl@3ea3a521`, `master`, 2026-10-28.
**Sister repo:** [C++ RiptOPL](https://github.com/NathanNeurotic/RiptOPL).
**Purpose:** a reviewable tracking/checklist PR only. **This document contains no implementation.** Implement fixes in small follow-up PRs; check boxes only after code review and validation.

## Agent operating rules

1. **Compare behavior, do not blindly cherry-pick.** This fork has significant independent changes to IGR/VBLANK, RA snapshots, USB and network boot modes, MMCE card-switch settling, Neutrino/Ember/POPS support, VMC, multiple devices, and the legacy C structure. YAOPL may be older or simpler in any one path.
2. Before each task, examine the linked YAOPL commit **and current code** in this repository; mark **ported / equivalent already / not applicable / awaiting hardware**, with a source link in the implementing PR. Audit both editions independently.
3. Preserve original default behavior unless a bug requires change; avoid global SIO2MAN, IOP-reset, and controller reinitialization changes. Respect Mode 6 and RA IGR VBLANK design; do not import YAOPL's entire `ee_core` or `modules` trees.
4. For safety-sensitive parser fixes: start with malformed fixture and a host regression reproducer, then fix the narrow mechanism, then run valid-file golden cases. No unbounded retries, silent corruption, or changing on-disk formats.
5. For hardware fixes: document device, game ID, transport/core, build, reproducible steps, before/after symptoms, log, and whether behavior changes during two-USB, MMCE and mixed-device setups.
6. One self-contained PR per logical batch. Keep **both** parity tracking PRs open as the cross-repository index. Do not merge this planning PR until the handoff owner requests it. No release from this planning-only PR.

## A. Confirmed differences — implementation checklist

Each item describes a **source-level gap**, not a claim that hardware already reproduced the bug. Priority P0 means potentially dangerous on a reachable path and should be reviewed first.

### P0 — memory-safety and hang hardening

- [ ] **YA-01 — OSD history filename bounds.** In `src/OSDHistory.c`, `GetBootFilename()` copies an unchecked basename into a 17-byte record; avoid `strcpy` and cap the stored filename at 16 + NUL for both separator and no-separator paths. Reject/trim malformed `$AltStartup` without losing valid history. YAOPL [80c5558d](https://github.com/yaopl/yaopl/commit/80c5558d). **Accept:** 16/17/255-character names, path/filename-only, `;1`, empty string, sentinel guard bytes; existing history unchanged.
- [ ] **YA-02 — ISO9660 empty-name progress and directory record bounds.** `modules/isofs/isofs.c` `cdvdman_locatefile()` advances `tocPos` only inside the nonempty-filename branch; YAOPL advances past any nonzero-length entry, preventing infinite loops on valid-length/empty-name records. Check the record-length type/sign extension (one-byte ISO9660 field), minimum header size, remaining sector bounds, name length and nul termination in every in-game and game-list scan. YAOPL [ff498c19](https://github.com/yaopl/yaopl/commit/ff498c19), [af5b52b7](https://github.com/yaopl/yaopl/commit/af5b52b7), [bfe726f5](https://github.com/yaopl/yaopl/commit/bfe726f5), [a2ff76fc](https://github.com/yaopl/yaopl/commit/a2ff76fc). **Accept:** malformed/empty name or overlong record yields safe error/progress, valid DVD/CD and dual-layer image searches still work.
- [ ] **YA-03 — ZSO validation and large reads.** `modules/isofs/zso.c` currently accepts unsupported header `align`/`block_size`, can subtract descending index offsets before validating, and does not slice all >256-sector reads like YAOPL. Add header validation (`align <= 11`, `block_size == 2048`), monotonically increasing offset checks, compressed-size/buffer bounds, safe cache/index math and bounded slices. Preserve this fork's additional short-read and allocation-failure checks and ensure API return values propagate through every caller, including PS2-logo probing. YAOPL [0253f98b](https://github.com/yaopl/yaopl/commit/0253f98b), [9ad4afeb](https://github.com/yaopl/yaopl/commit/9ad4afeb), [147e2493](https://github.com/yaopl/yaopl/commit/147e2493), [4baf5921](https://github.com/yaopl/yaopl/commit/4baf5921). **Accept:** valid 2048-block ZSO including boundary crossing; invalid align/block/index or truncated data rejects safely without memory overwrite or infinite loop.
- [ ] **YA-04 — word-wrap terminator.** `src/fntsys.c` `fntFitString()` may overwrite the NUL terminator on an oversized final word then continue beyond the caller's string. Port YAOPL's terminal-word guard without affecting wrapping, newlines, UTF-8 or CFG ownership. YAOPL [a4c0830f](https://github.com/yaopl/yaopl/commit/a4c0830f). **Accept:** single long word at narrow width; long last word; UTF-8; every buffer remains NUL-terminated and no extra read/write occurs.

### P1 — compatibility, input, and data integrity

- [ ] **YA-05 — cheat table full-list semantics.** `src/cheatman.c` protects `gCheats[MAX_CODES]` against OOB writes, **but** after the table fills can still append later codes to the previous cheat entry. Stop/skip safely without contaminating the preceding entry; do not regress duplicate names, mastercodes or zero-address continuation semantics. YAOPL [44a003bd](https://github.com/yaopl/yaopl/commit/44a003bd), [6b645a00](https://github.com/yaopl/yaopl/commit/6b645a00). **Accept:** max/above-max cheat counts with distinct names, repeated names and no-LF final line; no mis-assigned codes.
- [ ] **YA-06 — DS2 game handoff.** `src/pad.c` currently closes pad ports without YAOPL's bounded wait, `padExitPressMode()`, and `PAD_MMODE_DIGITAL, PAD_MMODE_UNLOCK` reset of a stable DS2. Adapt the reset at **game handoff** to avoid Gran Turismo 4-style failures; preserve rumble flush, unplug/digital pads, and this fork's keep-IOP ELF behavior. YAOPL [c56a91b6](https://github.com/yaopl/yaopl/commit/c56a91b6). **Accept:** DS2 initializes in GT4 without replug; analog/pressure games, digital pads, IGR, PADEMU and keep-IOP launch still function.
- [ ] **YA-07 — DS3/DS4 USB PADEMU transfer isolation.** `modules/pademu/ds34usb.c` reuses `usb_buf` for asynchronous startup/control, LED/rumble and interrupt reports. YAOPL uses dedicated startup report and per-pad input buffers. Incorporate the relevant fixes while checking callback lifetime, retry ordering, stop/reconnect and multicontroller use. YAOPL [1ef5b49c](https://github.com/yaopl/yaopl/commit/1ef5b49c), [4b1106e4](https://github.com/yaopl/yaopl/commit/4b1106e4), [c4a82e95](https://github.com/yaopl/yaopl/commit/c4a82e95). **Accept:** delayed USB DS3 startup, hot-plug after game starts, 2 devices, button responsiveness, LEDs and rumble without stale or corrupted reports.
- [ ] **YA-08 — UDPBD bounded bursts / boot recovery.** `modules/network/smap_udpbd/src/udpbd.h` sets `UDPBD_MAX_SECTOR_READ` to 512 (256 KiB for 512-byte sectors); YAOPL capped read requests at 16 KiB after lost packet bursts. Test cap versus throughput; consider safe adaptive 16 KiB chunks rather than an unreviewed global reduction. Audit ATA/DEV9 driver startup order, early request/link-ready retries, and stopping residual USB host control before launching UDPBD. **Already present:** this fork's reconnect watchdog and NIC coexistence protections; preserve these. YAOPL [12cc6fb5](https://github.com/yaopl/yaopl/commit/12cc6fb5), [2a79d23b](https://github.com/yaopl/yaopl/commit/2a79d23b), [15eee615](https://github.com/yaopl/yaopl/commit/15eee615), [68de38f8](https://github.com/yaopl/yaopl/commit/68de38f8). **Accept:** late-started server, interrupted/restarted server, APA HDD simultaneously enabled, single/dual USB connected, stable game launch and readback.
- [ ] **YA-09 — MMCE busy status and card settle.** `src/mmcesupport.c` already has menu-time arming, positive-busy detection, fallback and tri-state/wait handling (including longer waits), but early negative `GET_STATUS` results may allow an **unconfirmed** launch while an SD2PSX is still swapping cards. Differentiate transient busy silence from permanently unsupported status; make polling finite and keep user START bypass, Neutrino VMC exclusion, and SIO2 contention protection. Do **not** replace the existing state machine with YAOPL's simplified 7.5-s loop. YAOPL [19578cc6](https://github.com/yaopl/yaopl/commit/19578cc6). **Accept:** cross-device launch while MMCE card becomes silent >500ms; no early boot into previous card; no infinite wait on missing/unsupported devices.
- [ ] **YA-10 — Unicode cheat names.** `src/cheatman.c` still uses `isgraph((int)*s)` in name classification; YAOPL admits bytes >= 0x80 to preserve Cyrillic/Japanese cheat labels. Avoid signed-char UB in all `ctype.h` calls and preserve meaningful UTF-8 bytes during trimming. YAOPL [23a94a8c](https://github.com/yaopl/yaopl/commit/23a94a8c). **Accept:** UTF-8 label preceding codes is not merged with mastercode; malformed sequences do not crash.
- [ ] **YA-11 — malformed SYSTEM.CNF missing '=' (legacy-specific).** `src/ps2cnf.c` checks for `(const char *)-1` after `CNFGetToken(...,"=")` but misses `NULL`. Validate both, and add a `BOOT2`-without-`=` fixture. YAOPL [43781768](https://github.com/yaopl/yaopl/commit/43781768). **Accept:** malformed file fails safely; valid startup parsing unchanged. The C++ edition already has the NULL check.

### P2 — functionality and user-facing parity

- [ ] **YA-12 — per-game PADEMU remap settings.** Add off-by-default per-game DS3/DS4 button remapping: L2/R2 ↔ Square/Cross and L2/R2 ↔ L1/R1, keeping analog pressure semantics. Update `modules/pademu/padmacro.c`, per-game settings persistence, UI/localizations, configuration migrations and tests. Never change physical DS2 button mapping. YAOPL [eb1a6c96](https://github.com/yaopl/yaopl/commit/eb1a6c96), [ae8540cb](https://github.com/yaopl/yaopl/commit/ae8540cb). Also review [fix/pademu-remap-igr](https://github.com/yaopl/yaopl/tree/fix/pademu-remap-igr), **not yet master**.
- [ ] **YA-13 — adaptive BDM index UI.** `src/themes.c` uses a fixed `Index_<mode>` indicator. YAOPL computes actual visible BDM device count/selected position and supports `Index<count>_<position>` icons; preserve older theme assets as fallback, and ensure 0, 1, 2, 3+ devices display correctly. YAOPL [f84b227d](https://github.com/yaopl/yaopl/commit/f84b227d). Verify default MMCE nav icon consistency separately ([5776873f](https://github.com/yaopl/yaopl/commit/5776873f)); this fork's device system is different.
- [ ] **YA-14 — toolchain, host fixtures, language completeness, documentation.** Cross-check [YAOPL host repro suite](https://github.com/yaopl/yaopl/tree/master/labs/host-repro), [YAOPL language set](https://github.com/yaopl/yaopl-lang), SDK digest pinning/weekly canary, build metadata, packaging completeness (including Vietnamese), translation format safety, and documentation. Bring over only useful tests/processes; preserve this fork's additional strings, CI, and package naming.

## B. Verify first, then decide (NOT confirmed missing)

Do not check these as "ported" until a focused test/code comparison confirms a behavioral gap:

- [ ] **V-01 — USB `usbd_mini` revision for Crash Bandicoot: Wrath of Cortex.** YAOPL reverts to pre-rewrite SDK USB implementation ([09179482](https://github.com/yaopl/yaopl/commit/09179482)). Compare embedded module/toolchain sources; prove regression on hardware before changing USB driver.
- [ ] **V-02 — VMC interrupted-launch slot invalidation, duplicate slot errors, modify/replace prompts, and split UL fragment budget.** YAOPL [65765cfe](https://github.com/yaopl/yaopl/commit/65765cfe), [1bf79385](https://github.com/yaopl/yaopl/commit/1bf79385), [bc35dcc8](https://github.com/yaopl/yaopl/commit/bc35dcc8), [a5cbdb06](https://github.com/yaopl/yaopl/commit/a5cbdb06). Preserve the fork's enhanced Neutrino/native VMC layouts and contiguity tests.
- [ ] **V-03 — NBD server exit and device refresh** ([340e6338](https://github.com/yaopl/yaopl/commit/340e6338)); test repeated enter/exit with device scans and game launch.
- [ ] **V-04 — config saves, truncated file reads, leading '#' without LF, oversized RGB colors, legacy IP config, and BGM format string.** YAOPL [86ca55ac](https://github.com/yaopl/yaopl/commit/86ca55ac), [8dfdd548](https://github.com/yaopl/yaopl/commit/8dfdd548), [5192529d](https://github.com/yaopl/yaopl/commit/5192529d), [51b45e09](https://github.com/yaopl/yaopl/commit/51b45e09), [e8da9c86](https://github.com/yaopl/yaopl/commit/e8da9c86), [0d28c4c5](https://github.com/yaopl/yaopl/commit/0d28c4c5). Some are already hardened; do not regress bounded parser.
- [ ] **V-05 — GUI missing-texture handling, dialogue repeat/tick-wrap, mutating saved CFG during wrap.** YAOPL [1183f4e8](https://github.com/yaopl/yaopl/commit/1183f4e8), [33f7c226](https://github.com/yaopl/yaopl/commit/33f7c226), [8a98f0fd](https://github.com/yaopl/yaopl/commit/8a98f0fd), [0f16d591](https://github.com/yaopl/yaopl/commit/0f16d591).
- [ ] **V-06 — game-list `games.bin` cache bounds, UL name hashing and split image short-read handling.** YAOPL [578ba6b5](https://github.com/yaopl/yaopl/commit/578ba6b5), [f244afff](https://github.com/yaopl/yaopl/commit/f244afff), [da9af708](https://github.com/yaopl/yaopl/commit/da9af708). This fork already uses unsigned bytes for `USBA_crc32()`; do not rename existing valid parts without compatibility analysis.
- [ ] **V-07 — selective SDK SIO2MAN and startup order.** The fork already packs SIO2MAN conditionally and excludes MMCE; compare game-side module load order with YAOPL [5ef1b9e2](https://github.com/yaopl/yaopl/commit/5ef1b9e2), do not globally preload it. Test MX4SIO/VMCE/PADEMU/RA and games that replace SIO2MAN.
- [ ] **V-08 — outstanding YAOPL experimental branches:** [fix/udpbd-game-config](https://github.com/yaopl/yaopl/tree/fix/udpbd-game-config) (2 commits ahead), [fix/pademu-remap-igr](https://github.com/yaopl/yaopl/tree/fix/pademu-remap-igr) (2 ahead), [fix/smb-io-errors](https://github.com/yaopl/yaopl/tree/fix/smb-io-errors), [fix/disc-id-ncmd-sema](https://github.com/yaopl/yaopl/tree/fix/disc-id-ncmd-sema), [fix/vmc-fragment-count](https://github.com/yaopl/yaopl/tree/fix/vmc-fragment-count) (last three diverged/old). Treat as hypotheses, not shipped capabilities.

## C. Known equivalents — **do not re-port**

- [x] Native UDPBD/UDPFS support, reconnect watchdog and NIC ownership interlock (validate failure modes separately).
- [x] LBA48 65,536-sector ATA transfer overflow handled in `modules/iopcore/cdvdman/atad.c` (YAOPL [e09f5482](https://github.com/yaopl/yaopl/commit/e09f5482)).
- [x] 2340-byte CDVD buffer overrun independently fixed in `modules/iopcore/cdvdman/cdvdman.c`.
- [x] Cheat table count/hook bounds, duplicate cheat selection persistence and `make_code` digit/last-line safeguards. **YA-05 remains** because *semantic attachment to the preceding cheat* is a separate issue.
- [x] Partial `ul.cfg` trailing-record protections, short ISO name (`.. `) guard, and unsigned-byte USBA name hashing.
- [x] Language filename validation, CWD-first external language lookup, translation placeholder checks.
- [x] Grayscale PNG, theme `ItemsList` default fallback, `GameCountText` allocation protections.
- [x] Invalid GSM preset index clamp and 48-sector PS2-logo HDD read.
- [x] **GENVMC failed-write semaphore safety already addressed independently**: fork releases abort semaphore *before* blocking seek/write, and checks seek failure. YAOPL's different critical-section structure is **not** a missing fix. Do not regress fork behavior. YAOPL [885c201f](https://github.com/yaopl/yaopl/commit/885c201f).
- [x] IGR sampled via VBLANK_END in both editions with game-specific Mode 6 fallback; RA telemetry has additional constraints. Do not import YAOPL IGR threads wholesale.
- [x] Existing MMCE cross-device Game ID and boot-card IGR support; only timing/failure edge cases require YA-09.
- [x] Existing BDM config probe uses `O_CREAT` without `O_TRUNC` to avoid emptying `conf_opl.cfg`.

## D. Implementation order / PR boundaries

Recommended independently reviewable follow-up PRs:

1. **Safety batch A:** YA-01, YA-04 and YA-11 — host-only input fixtures, smallest scope.
2. **ISO/ZSO batch B:** YA-02 and YA-03; protect API contract/callers; test malformed and valid images.
3. **Input batch C:** YA-05, YA-06, YA-07, YA-10; keep controller changes distinct from cheat parser changes, preferably separate PRs.
4. **Transport batch D:** YA-08 and YA-09 separately; requires hardware before release.
5. **Enhancement batch E:** YA-12 and YA-13; ensure config migrations, translations and theme compatibility.
6. **Test/docs batch F:** YA-14 plus evidence-backed V-series findings; follow-up PRs only where an actual behavioral gap is proven.

For each PR: link this checklist, relevant YAOPL commit(s), tested device/core/game matrix, expected/actual behavior, and explicit no-regression checks. Update the mirrored parity-plan PR with the same disposition.

## E. Mandatory hardware + host gate

- [ ] Host fixtures and sanitizer/reproducer checks for strings, ISO9660, ZSO, cheats, VMC and malformed config.
- [ ] Native OPL core: USB single + dual devices; MX4SIO; MMCE both slots; APA HDD; exFAT HDD; SMB; UDPBD; UDPFS; iLink.
- [ ] Controller: OEM DS2 analog/pressure and digital handoff, DS3/DS4 PADEMU hot-plug, two controllers, rumble shutdown.
- [ ] Game candidates: Gran Turismo 4 (DS2 handoff); Crash Bandicoot: The Wrath of Cortex (USB driver); Fatal Fury: Battle Archives Volume 2 (IGR Mode 6), plus a known good game per core/device.
- [ ] Confirm VMC data integrity on successful and aborted launches, including MMCE Game ID switching while card returns negative status.
- [ ] Compare standard, Korium/Neutrino, RetroAchievements, PS1/Ember/POPS paths as applicable; respect their different startup/IOP reset requirements.
- [ ] No changes to release artifact naming/policy, default semantics, or translations outside the intended task; record QA matrix and regression reports.
- [ ] After each implementation, update this document with commit/PR, hardware results and disposition.

## F. Attribution and boundaries

The YAOPL investigations and fixes are by **[belomaxorka](https://github.com/belomaxorka)**: [YAOPL project](https://github.com/yaopl/yaopl). Give appropriate upstream credit in individual implementation PRs and code provenance when adapting his work; maintain existing PS2SDK/OPL contributor and license notices. Attribution documentation is handled in a **separate already-approved PR**, not part of the implementation work.

**This plan is an implementation checklist, not evidence that all YAOPL changes are absent, safe to import, or validated on retail hardware.** Review source-level facts against the branch head again before coding.
