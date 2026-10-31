# Ecosystem fork-gap reconciliation — 2026-10-29

The C++/ps2build RiptOPL line and the legacy C Open-PS2-Loader line are compared separately at pinned defaults. This reconciliation supersedes older availability wording while retaining every historical stable ID and its evidence. It is research and documentation, not a promise to port each difference.

## Baselines and coverage

| Edition | Source baseline |
| --- | --- |
| RiptOPL, C++/ps2build | [`2b948bc32b75`](https://github.com/NathanNeurotic/RiptOPL/commit/2b948bc32b75a8f093c7dccae68e8327368a6f9c) |
| Open-PS2-Loader, legacy C | [`8f39a490c30b`](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/8f39a490c30ba0ecd796a05abcfe9b1e3dd98fc1) |

Checked **141 repository identities / 138 canonical repositories**. Of the 134 refs tracked on October 28: **10 changed, 124 unchanged, none unavailable**. Seven identities extend that inventory: the current RiptOPL edition, YAOPL new address, OPL-JUMP, and four newly discovered forks. Twelve tracked heads changed since the October 25 full source sweep. Every identity has a release-collection check (up to five entries), including TEST/prerelease entries; five redirects were resolved rather than called missing.

The searchable register has **292 stable records** in **44 stable-ID source groups** (the prefixes in the source table). It contains overlapping mechanisms, plans, experiments, tools and rejected choices. The **143 families** retain the 118 October 25 family numbers and group new child mechanisms; they are not a defect count. Parent YA1 and child YA work items are not additive independent capabilities.

| Current classification | Records |
| --- | --- |
| Source comparison candidate | 27 |
| Companion / separate scope | 29 |
| Declined / outside local scope | 1 |
| Experimental source / unvalidated | 41 |
| Historical / withdrawn | 6 |
| Intentional design difference | 3 |
| Known upstream limitation | 4 |
| Already present / equivalent scope | 27 |
| Partial overlap / remaining difference | 29 |
| Merged / hardware unverified | 36 |
| Prior source finding / reassess | 89 |

## What is already present

Both editions have the merged RIPPS2 A–H integration: All Games, last-10 Recent, Last played sort, Random Game, hidden-game management, guarded game-file cleanup without APA deletion, JPG/JPEG and OPL Manager art aliases, Arabic/Persian shaping and CJK/Thai/Lao breaks, Drive Status/DIAG.TXT, VMC Saves browsing, glyph/weight/interface improvements, reset latches and the MMCE busy-seen wait. Grid and multi-view themes were added afterwards. Generic unified-library, recents, flat-grid and basic RTL rows are no longer described as absent.

The YAOPL hardening batches ([RiptOPL #142](https://github.com/NathanNeurotic/RiptOPL/pull/142), [legacy #1114](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1114)) merged history bounds, font terminators, cheat capacity, synchronous disc-key ownership and VMC fragment diagnostics. C++ already had the CNF equals guard; its regression and the legacy guard are present. Native OPL UDPBD/UDPFS IMG launches and the 16 KiB read cap are merged in [#153](https://github.com/NathanNeurotic/RiptOPL/pull/153) / [#1123](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1123). Default still selects Neutrino on those sources. UDPFS Files games can also use the OPL core in both editions (RiptOPL [#161](https://github.com/NathanNeurotic/RiptOPL/pull/161), legacy [#1134](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1134)). Not tested on hardware.

Current POPS packages use [Okeanos](https://github.com/Okeanos86) [UDPFS Assault](https://github.com/Okeanos86/BDMAssault/releases) TEST with BIN/CUE support. This supersedes the earlier network-only 1.0.0 snapshot, not a restoration of the obsolete USB-first translator. Published driver-release metadata and packaging commits are distinct evidence from a passing network game/save test.

## Batch merged after the first snapshot

RiptOPL #162 merged these PRs at 15:18 UTC on October 29, after the first snapshot of this audit; RiptOPL is reconciled at 2b948bc3. Legacy #1133 merged the same changes. Availability is determined from merged commits at the baseline, not an unchecked tracker. The two YAOPL planning PRs use different task numbers; this report uses the RiptOPL #131 / legacy #1105 scheme and spells out each mechanism.

| Mechanism | RiptOPL | Legacy | State |
| --- | --- | --- | --- |
| YA-02: ISO9660 directory record bounds and empty-name handling | [#150](https://github.com/NathanNeurotic/RiptOPL/pull/150) | [#1122](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1122) | Merged in both; hardware unverified |
| YA-03: ZSO header/index validation and bounded large-read slices | [#151](https://github.com/NathanNeurotic/RiptOPL/pull/151) | [#1124](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1124) | Merged in both; hardware unverified |
| YA-06: DualShock 2 digital and unlocked launch handoff | [#149](https://github.com/NathanNeurotic/RiptOPL/pull/149) | [#1121](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1121) | Merged in both; hardware unverified |
| YA-07: Per-pad DS34 USB report ownership and alarm cancellation | [#147](https://github.com/NathanNeurotic/RiptOPL/pull/147) | [#1119](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1119) | Merged in both; hardware unverified |
| YA-09: MMCE silent card-switch status settling | [#146](https://github.com/NathanNeurotic/RiptOPL/pull/146) | [#1118](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1118) | Merged in both; hardware unverified |
| YA-12: One BdmIndex dot per visible mass device | [#152](https://github.com/NathanNeurotic/RiptOPL/pull/152) | [#1125](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1125) | Merged in both; hardware unverified |
| YA-14: Translated MMCE IGR slot choices and integration coverage | [#154](https://github.com/NathanNeurotic/RiptOPL/pull/154) | [#1126](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1126) | Merged in both; hardware unverified |
| YA-17: USB host shutdown before IGR IOP reset | [#144](https://github.com/NathanNeurotic/RiptOPL/pull/144) | [#1116](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1116) | Merged in both; hardware unverified |
| YA-18: Coordinated read-only UDPBD capability and write policy | [#158](https://github.com/NathanNeurotic/RiptOPL/pull/158) | [#1130](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1130) | Merged in both; hardware unverified |
| H13: Correct in-game SMAP TX descriptor buffer base | [#157](https://github.com/NathanNeurotic/RiptOPL/pull/157) | [#1129](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1129) | Merged in both; hardware unverified |
| RI44: Remembered menu-position profile per video mode | [#159](https://github.com/NathanNeurotic/RiptOPL/pull/159) | [#1131](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1131) | Merged in both; hardware unverified |

YA-18 read-only UDPBD shipped as the coordinated policy (write check, CFG fallback, no games.bin/folders/settings/VMC, hidden edit controls) together with refused-write-as-success in smap_udpbd, rather than either piece alone. The write check still uses the fixed name opl_write_test.tmp. Favorites/Recent/hidden-list writes were not re-audited here. No probe touched user storage.

YA-11 button remapping was removed upstream before release and remains deferred for an explicit product decision. UDPBD read-yield/SMAP-priority branches are A/B experiments, not demonstrated compatibility fixes.

## RIPPS2: released 121, development 124

Released **v1.2.1-beta / build 121** is pinned to [`29e455b0`](https://github.com/akilluminati47/RIPPS2/commit/29e455b0a3c0b9f42e142ee395e4db39befdc60f). GitHub marks that release `prerelease=false`, while its own product name remains beta. Development `main` is [`b682a93cfffc`](https://github.com/akilluminati47/RIPPS2/commit/b682a93cfffc9f3481a0f6dfd7b4e45a88b5be86), build 124. The review reconstructed **75 numbered patches** on pinned legacy base `65d4b89`; it did not execute upstream build/setup scripts or build a console ELF.

Builds 118–121 add ART Pack management, automatic picture cropping in 16:9, info/sidebar refinements, saved-mode boot-sky presentation and the MC boot-sound sidecar/copy offer. An early audio-start attempt was reverted after an upstream lab hang; the released ordering and later build-122 experiment are separated. Development-only additions are launch-disc spin/zoom (122), ART archive merge and recovery handling (123), and per-mode position profiles plus an opt-in thread-wait watchdog (124). The per-mode position profiles have since been ported (RI44, RiptOPL #159 / legacy #1131). None is promoted to a console compatibility fix.

New records RI41–RI47 preserve this released/development split. Existing RI1/RI5/RI19/RI21/RI23/RI35/RI36/RI38 are narrowed around the portions already ported. Disc ripping and HDD partition writes remain declined local scope; the magnified single-pass HD renderer and external-only runtime packaging remain optional design alternatives.

## LUNA: follow the wrapper pins

LUNA wrapper [`b65ec63a`](https://github.com/dnunezx/LUNA/commit/b65ec63a3b43b6cfc30e6a51786c669f5bc4d93a) pins frontend **`luna@f640a4e8cfd4`**, Neutrino `fff99d98`, native OPL `c533f939` and unchanged PSXCore `5d4de02f`. The previously tracked frontend `main` ref is unchanged; reviewing only that ref would miss 17 frontend commits. Published v3.1.3 and its separately pinned hotfix workflow are not automatically the same artifact as this development wrapper.

The actual source now unifies PS1/PS2 whole-card management with raw-format validation, staged byte-verified copies, backup/replace/recover gates and independent PS1 slots. Local creation/assignment and the merged Saves browser overlap but do not provide that entire lifecycle (LU13/LU33/LU35/LU44). Source recovery paths are not proof of power-loss durability.

Additional source comparisons are direction-aware 4 MiB decoded-cover reuse (LU41), paired resident long-argv transport (LU42), and opt-in physical-MMCE switching with session-slot restore in both paired runtimes (LU43). Local async art caching, safe kernel argument refusal, GameID and native IGR already overlap. Do not transplant LUNA loader flags or advertise larger argv without its matching runtime. Crystal menus, camera/background changes and reverted font-spacing work are presentation history, not a missing generic theme engine.

## OPL-JUMP and new forks

OPL-JUMP `414674c2` contributes narrower optional loose-shortcut discovery and filename-to-shelf classification (JUMP1/JUMP2). Local tagged Apps, PS1 launching and All Games already exist. The earlier real-function classifier probe remains historical evidence, not a test rerun here: its prefix rule misclassifies a PS2-looking SLUS name and omits SCPS. Never infer launch behavior from shelf membership.

Blayr OPL Custom `7959031a` is seven commits ahead of current upstream `b3a21997`. Source comparison adds BL1 (device-local/shared MC Favorites policy) and BL2 (bounded idle-queue COV/ICO neighbour prefetch). Local Favorites identity/failure handling and art workers overlap. The author distinguishes an older real-PS2 prefetch trial from newer Favorites/UI emulator checks; neither is acceptance for these editions.

The latest 30 upstream OPL forks and latest 30 RiptOPL forks were enumerated. Newly found taisonboxing3-code matches upstream; Diegoprofeta matches the RiptOPL baseline; 1247847495 retains ancestor `6edea174`. Blayr is the only new default branch with independent source changes in this bounded discovery. This does not enumerate all historical/private forks or analyze every advertised branch.

## Other changed projects and companion boundaries

| Project | Current assessment |
| --- | --- |
| xeRAbora | Stable 1.0.1 source/release checked. Both editions' RA docs now point at v1.0.1 (alpha.17 or later works); H13 SMAP TX fix merged in both. No wire-compatibility test was run. |
| Launchstation | Current 054be5b0 includes R3Z integration, later MMCE card contents/backup/switching, audio/toolchain and network/rename fixes. Final ordinary copy retains direct destination replacement; superseded rollback architecture is not reported as current. Companion scope. |
| POPSLoader | Current 0fc79114 includes network-only Assault 1.0.0, 1.4.0 release work and later TEST/BIN-CUE driver adoption. Source and release chronology are separate from console read/write acceptance. |
| PS2-Servers | Current 81ff0956 adds bounded opt-in recursive metadata indexing, startup guidance, DREAD skip-on-stat-failure and address hints. Unmerged compressed-image identity/achievements work is not called shipped. |
| OdysseyLauncher | Development 347671c0 adds Vita3K/title-ID launch after 0.20.0, console models, PDF manuals and presentation work. Desktop scope; not a PS2 runtime gap. |
| PS2SP | 93 commits since October 25 and 3,512 changed paths, mostly catalogue/discovery/deployment data. This is a manifest/commit-summary review, not exhaustive review of every packaged app. |
| DKWDRV / [Okeanos](https://github.com/Okeanos86) releases | DKWDRV 1.7.6u retains explicit instability cautions. Okeanos TEST is a prerelease even though the release collection lists stable 1.0.0 first. Release names/collection order are not tested compatibility. |

## Evidence files and review limits

- [Every tracked/default ref and advertised branch/tag](repository-heads.json)
- [Current release metadata, limits and redirects](releases.json)
- [Tracked comparison summaries](comparisons.json) and [complete local file manifests for capped comparisons](full-file-manifests.json)
- [Wrapper/runtime pins and reconstruction](dependency-pins.json)
- [PR snapshot with exact heads](pull-requests.json) and [new-fork comparisons](new-fork-comparisons.json)
- [Every current stable-ID disposition](id-dispositions.json) and [deduplicated family reconciliation](consolidated-gaps.json)
- [Source mechanism review notes](source-review.json) and [publication validation](validation.json)

GitHub compares cap their file list at 300; some commit lists also exceed 100. Local Git manifests recover complete path counts for RIPPS2 (569), legacy (320), Launchstation (371), Odyssey (328) and PS2SP (3,512). A complete path inventory is not a claim to have audited every changed function. RIPPS2 patch mechanisms and LUNA pinned frontend/runtime deltas received targeted source review; companion/catalogue changes received narrower review as stated.

An unchanged tracked branch preserves the earlier source evidence, not hardware acceptance and not proof that every other branch/tag is unchanged. Every carried-forward register row says so. Both editions have independent baseline SHAs; later merges require a new reconciliation. No target build, emulator/game run, physical console run, storage probe, gameplay/save-durability check or throughput benchmark was performed for this documentation update.

## Maintenance contract

The current register, metrics, consolidated families and search index are regenerated from this dated disposition set. Historical October 25/28/29-focused findings retain their URLs and anchors but are labelled historical. Stable IDs are never reassigned. Keep source date, target baseline, release/development stage, pending PR heads and evidence level with every future status change. Do not update only a new prose section while leaving the filterable register stale.
