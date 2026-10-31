# Focused fork-gap refresh — 2026-10-29

This is a source comparison of newly changed YAOPL code and OPL-JUMP, not a new ecosystem-wide sweep. It supplements the dated October 25/28 register without rewriting its historical counts or stable IDs. No console/game testing was performed. The small JUMP host probe below checks classification only.

## Pinned revisions and provenance

| Project | Compared revision |
| --- | --- |
| [YAOPL](https://github.com/yaopl/yaopl), by [belomaxorka / Roman Kelesidis](https://github.com/belomaxorka) | [`fc5426469c04`](https://github.com/yaopl/yaopl/commit/fc5426469c04c9a46a936c4d89fba9c80e7c9e30), changes since previously reviewed `b0f8c2ecaa11` |
| OPL-JUMP, by juankyt505 | [`414674c24485`](https://github.com/juankyt505/OPL-JUMP/commit/414674c2448533ec3d386a31d035deb3e5b31687); implementation published in [`1e98bbf`](https://github.com/juankyt505/OPL-JUMP/commit/1e98bbf) |
| RiptOPL C++ / ps2build | `rebuild/main@b4c23bdac8f983a4b4e3456d4036b8645cf95842` |
| Open-PS2-Loader legacy C | `rebuild/main@29826585edd960b312ba58d2f6987ac345eae3a9` |

OPL-JUMP identifies its upstream base as OPL revision 2267, `4cc74baabb73be9ca43f817474b321cd70fbcc2d`. Its README reports USB/dual USB, traditional HDD, SMB1 and MX4SIO tests by its author; those reports were not reproduced here. Preserve its AFL-3.0 attribution and original OPL notices in any future port.

## New or refined differences in both editions

| ID | Classification | Difference and evidence | Recommended next step |
| --- | --- | --- | --- |
| YA-17 | Missing shutdown mechanism; console impact unverified | YAOPL [`e72c9f48`](https://github.com/yaopl/yaopl/commit/e72c9f485cfc1f99f33829cdccaf8c1dda4b3ef3) stops operational OHCI after unmount/flush and before the IGR IOP reset, reusing its UDPBD startup helper. Both our `modules/iopcore/cdvdman/cdvdman.c::oplShutdown()` paths drain VMC, lock and unmount, but lack this USB-host stop. Upstream describes an owner's DS3 USB PADEMU IGR hang; its post-fix console verification was still pending. | Investigate/adapt the lifetime fix, retaining our stronger VMC drain, shutdown ordering, USB storage and RetroAchievements hooks. Verify no-transfer, active USB/BT PADEMU, USB storage, power-off, repeated IGR and timeout cases before claiming a hang fixed. |
| YA-18 | Missing coordinated read-only UDPBD policy | YAOPL's [`093b541b`](https://github.com/yaopl/yaopl/commit/093b541bf13edcda418fd4e59c3c222a9b83fb40), [`7781959c`](https://github.com/yaopl/yaopl/commit/7781959c), [`11037583`](https://github.com/yaopl/yaopl/commit/11037583), [`c92f681d`](https://github.com/yaopl/yaopl/commit/c92f681d), [`afe59be2`](https://github.com/yaopl/yaopl/commit/afe59be2), [`7c375a09`](https://github.com/yaopl/yaopl/commit/7c375a09) and [`760d7e3c`](https://github.com/yaopl/yaopl/commit/760d7e3c) detect discarded writes, redirect per-game CFG, suppress automatic writes, block edits and disable VMC on a read-only server. Neither edition has the corresponding per-device read-only flag/policy. | Design capability detection and audit every write path, including our additional Favorites/Recent/hidden/Apps/config/cache operations. Keep gameplay readable and saves on writable media; preserve stored VMC preferences while preventing use on read-only backing. Do not copy the probing/driver patch mechanically. |
| JUMP1 | Partial overlap; automatic categorization missing | OPL-JUMP [`src/appsupport.c`](https://github.com/juankyt505/OPL-JUMP/blob/414674c2448533ec3d386a31d035deb3e5b31687/src/appsupport.c) classifies boot-name prefixes into Apps vs PS1 shortcut filters. Our Apps library already filters via the explicit `[PS1]` title tag, and separately recognizes POPSTARTER forms for launch preparation. Automatic filename-to-shelf classification is the narrower difference. | Optional display-only classification with explicit category override, documented regional IDs, extension/path validation and false-positive tests. Never use guessed shelf membership to select a launch core, bypass REBOOTIOP prompts, or turn an ordinary ELF into POPSTARTER. Preserve current tagged apps, IDs, favorites and theme families. |
| JUMP2 | Partial overlap; loose-shortcut discovery missing | OPL-JUMP [`src/menusys.c`](https://github.com/juankyt505/OPL-JUMP/blob/414674c2448533ec3d386a31d035deb3e5b31687/src/menusys.c) scans `mass0..4` roots/POPS/APPS, an HDD APPS location and SMB root/POPS/APPS into its JUMP portal. Our unified All Games/PS1 views already aggregate sources, but Apps discovery reads `conf_apps.cfg` and per-app `title.cfg`, rather than indexing those loose root/POPS shortcut ELFs. | Consider opt-in loose-shortcut discovery through the existing library/worker, not a duplicate hard-coded JUMP UI. Bound scanning, deduplicate by source/path, preserve arguments and identity, handle removal/reconnect and avoid synchronous filesystem work during rendering. Do not copy fixed five-slot assumptions or overwrite existing configured entries. |

### YA-18 port boundary: detection is a design task

YAOPL writes, reads and removes a 512-byte timer-seeded `yaopl_write_test.tmp` at the UDPBD root. Its separate [`df65546e`](https://github.com/yaopl/yaopl/commit/df65546e) patch treats an explicit refused write as completed so FatFs can continue reading; it relies on the subsequent policy suppressing writes. This is **not** a general-purpose write-success correction. Importing that patch alone could conceal lost writes. A fixed filename opened with truncation also requires collision/ownership review before adoption. Prefer negotiated server capabilities where available; otherwise specify safe probe ownership, cache bypass, error/permission vs read-only distinction and cleanup. No probe was run on user storage in this audit.

Acceptance must include servers that persist, discard, explicitly reject or time out writes; stale cached/probe data; reconnects; unavailable writable CFG locations; game and Apps rename/delete; global settings; games.bin and our other automatic writes; both VMC slots, autolaunch, physical-card fallback and Neutrino/native differences. Track shared CFG identity and avoid edits on writable copies silently affecting read-only launches.

### JUMP classification limitations verified on the host

A host C harness compiled OPL-JUMP's actual `appIsPS1Launcher()` function, with only the `app_info_t.boot` container stubbed:

| Boot name | JUMP classifier |
| --- | --- |
| `XX.Game.ELF`, `SB.Game.ELF` | PS1 shortcut |
| `SLUS_203.12.PS2.ELF` | PS1 shortcut (prefix alone cannot establish platform) |
| `SCPS_100.00.PS1.ELF` | Ordinary app (regional prefix not in the four-ID-prefix list) |
| `Tool.ELF` | Ordinary app |
| `XX.not_an_elf` | PS1 shortcut (this Apps predicate does not enforce the extension) |

The loose-file scanner's separate `ps1testIsElf()` does check `.ELF`; do not generalize the Apps predicate's extension limitation to every JUMP code path. The code checks prefix families, not a fully validated PS1 executable ID. These are categorization observations, not launch or hardware results.

## Withdrawn and experimental work — do not count as new fixes

- **YA-11 button remap was removed upstream** by [`6faa44e4`](https://github.com/yaopl/yaopl/commit/6faa44e436a50983f64b0d000b102b542b6bd0dc). It reverts the initial feature, settings and IGR correction because the owner no longer wants the complexity; upstream says it never shipped in a release. Keep our previous task ID/provenance, but defer it for an explicit local product decision rather than treating an active YAOPL feature as missing. DS34 USB ownership fixes remain separate (YA-07).
- New `test/udpbd-read-yield`, `test/udpbd-read-yield-nopadreset`, `test/udpbd-smap-prio` and `test/udpbd-smap-prio-nopadreset` branches are A/B experiments. The default branch does not contain them. Add them as investigation leads under YA-08, not established compatibility wins or mandatory imports.
- OPL-JUMP's separate portal, L3 button, device-group headings, blue cover frame, Spanish strings and author hardware-test list are presentation choices or evidence context. Our existing unified library, filters, PS1 art and language support overlap these; no separate missing PS1 engine, SMB backend, multi-USB support or generic L3 feature is established.

## Existing implementation work remains separate

The recent YA-01/04/05/10/15/16 fixes have independent PRs, not guaranteed default-branch availability. Consult the edition's YAOPL tracking PR (RiptOPL #131 / legacy #1105) and linked PR status. This audit does not mark them merged or hardware-verified and does not re-count them as new October 29 gaps.
