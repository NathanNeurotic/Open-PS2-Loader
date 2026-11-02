# Fork-gap status - November 1, 2026

> This is the legacy C edition of RiptOPL. New development happens in [NathanNeurotic/RiptOPL](https://github.com/NathanNeurotic/RiptOPL); this status is kept in both repositories in tandem.

This refresh re-reads every record of the [October 29 register](FORK-GAP-FULL-REFRESH-2026-10-29.md) against the code as it stands today, rechecks every tracked upstream head, and names the wins taken since. It supersedes the availability conclusions of the October 29 refresh; the October 29 document stays as dated evidence and its 301 records keep their IDs. Differences are comparison opportunities with shared work credited; they are not promised ports or a defect count.

## Baselines

| Edition | Source baseline read | Notes |
| --- | --- | --- |
| RiptOPL C++/ps2build | [rebuild/main 96852359](https://github.com/NathanNeurotic/RiptOPL/commit/96852359da353a5de5a3244c2fdc611c7b3bd30a) | Boot Theme Wait (#256) and start-up timing (#254) merged the same day |
| Open-PS2-Loader legacy C | [rebuild/main b2d6b3b1](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/b2d6b3b1) | tandem of the above (#1218, #1216) |

Everything marked **NOT TESTED** is merged in both editions and has had no console run; source presence is not acceptance.

## Status vocabulary

Every record now carries one of seven statuses: **PRESENT**, **PARTIAL**, **MISSING**, **REGRESSED**, **INTENTIONAL DIFFERENCE**, **BLOCKED**, **UNKNOWN**. The October 29 classification buckets map onto them as follows; the per-record result, with the records re-read by hand called out, is in [`id-status.json`](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-11-01/id-status.json).

| October 29 bucket | November 1 status |
| --- | --- |
| Already present / equivalent scope; Merged / hardware unverified | PRESENT (merged records stay NOT TESTED) |
| Partial overlap / remaining difference | PARTIAL |
| Prior source finding / reassess; Source comparison candidate | MISSING |
| Companion / separate scope; Declined; Historical / withdrawn; Intentional design difference | INTENTIONAL DIFFERENCE |
| Known upstream limitation | BLOCKED |
| Experimental source / unvalidated | UNKNOWN |

| Status | Records (311: 301 carried + 10 new) |
| --- | --- |
| PRESENT | 72 |
| PARTIAL | 37 |
| MISSING | 114 |
| REGRESSED | 0 |
| INTENTIONAL DIFFERENCE | 44 |
| BLOCKED | 4 |
| UNKNOWN | 40 |

No regression was found: nothing that the October 29 register recorded as present is absent at today's baselines.

## What closed since October 29

All of the work the October 30 publication note listed as pending is merged in both editions: the list-rebuild follow-up, Coverflow variants (#199 / #1167), Grid (#196 / #1164), silent in-game pause (#200 / #1168), official-config import (#190 / #1159) and menu-freeze diagnostics (#191 / #1160). On top of those:

| Record | Status | Where |
| --- | --- | --- |
| YA-20 shared message wrapping | PRESENT | RiptOPL #215 / legacy #1177 |
| YA-24 (new) PNG decode hardening | PRESENT | #245 / #1207, from [YAOPL](https://github.com/yaopl/yaopl) |
| YA-23 (new) delete/rename/launch act on the row the dialog was opened for | PRESENT | #251 / #1213, from YAOPL 5211110 |
| RI52 (new) game size via lseek64 when stat reports 0 on MMCE | PRESENT | #255 / #1217, from [RIPPS2](https://github.com/akilluminati47/RIPPS2) bd7615f |
| RI53 (new) PS1 Duplicates setting | PRESENT | #255 / #1217, from RIPPS2 a53f936 |
| RI1 / B1 / LU14 file manager and PSU export/import | PRESENT | #219 / #1180 |
| RI3 / RI12 in-game menu, RA pages, power off | PRESENT | #184 / #1155, #200 / #1168 |
| NV2 (new) Neutrino SMB launch path | PRESENT | #234 / #1196, #243 / #1205 |
| YA-06 DualShock launch handoff | INTENTIONAL DIFFERENCE | analog-lock follow-up #246 / #1208 |
| S1 ATA DRDY wait | INTENTIONAL DIFFERENCE | ours is bounded (30 s BSY + 5 s DRDY); Stable OPL waits without bound |

Every one of these is NOT TESTED on hardware.

## Wins taken in this refresh

Two YAOPL fixes by [Roman Kelesidis (belomaxorka)](https://github.com/belomaxorka) were still open and are now draft tandem PRs [RiptOPL #264](https://github.com/NathanNeurotic/RiptOPL/pull/264) / [legacy #1225](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1225) (records YA-21, YA-22, PARTIAL until merged):

- **Dialogs draw under the GUI lock** ([ce6323f](https://github.com/yaopl/yaopl/commit/ce6323f)). The IO thread frees a replaced theme or language under `guiLock`; the settings dialogs, keyboard, number pad and colour picker drew without it, so a dialog open while a device with the configured theme or language came up could draw freed strings, icons and font slots.
- **IO-thread list operations under the GUI lock** ([4c713a3](https://github.com/yaopl/yaopl/commit/4c713a3)). `updateMenuFromGameList` and `menuDeferredUpdate` drained the queued row operations without the lock while the GUI thread drew the same rows.

A host test now checks both invariants on the source in CI. NOT TESTED on hardware.

## Upstream heads rechecked

All **141 tracked identities** were rechecked with `git ls-remote` on November 1 (UTC 17:00): **20 tracked heads moved, 91 identities gained or changed some ref, none unavailable**. The full result is [`repository-heads.json`](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-11-01/repository-heads.json). What moved that matters:

| Project | Head | Assessment |
| --- | --- | --- |
| [RIPPS2](https://github.com/akilluminati47/RIPPS2) ([akilluminati47](https://github.com/akilluminati47)) | main c0d30866; v1.2.8-beta released (b126-b128); branch b129 | b126's card-Neutrino icon and 75 s launch wait are RIPPS2-specific. **RI54 List Title / Description** (released) and **RI55 .pad controller profiles / Set Up A USB Pad** (b129, unreleased) are MISSING and are product calls, not oversights. |
| [YAOPL](https://github.com/yaopl/yaopl) ([belomaxorka](https://github.com/belomaxorka)) | master 6955d0be; branches fix/stale-current, debug/ds3-metrics | PNG hardening and the row race are in; the two lock fixes are the drafts above. Nothing else outstanding. |
| [LUNA](https://github.com/dnunezx/LUNA) ([dnunezx](https://github.com/dnunezx)) | main ab52117; hotfix/3.1.3-mmce-gameid | Wrapper-side MMCE GameID hotfix; not applicable to this frontend. Register LU records unchanged. |
| [OPL-DualSense-BT](https://github.com/rodrigoGalvanDev/OPL-DualSense-BT) ([rodrigoGalvanDev](https://github.com/rodrigoGalvanDev)) | 7188a53, tag 1.2 | 8bb581a adds DS4 clones, RTL8761B, multi-pad, a Controller Setup page and multitap. **DT6 (new)**: in-game IOP memory relief for KH2 over SMB (lwIP IP_REASSEMBLY/IP_FRAG off, about 7.3 KB; USBD pool trim when only PADEMU loads, about 28 KB). MISSING; turning IP fragmentation off changes behaviour on large-MTU SMB paths, so it needs a decision before any port. |
| [DKWDRV](https://github.com/DKWDRV/DKWDRV) | 1.7.6v | Documentation and release only. |
| [OPL-JUMP](https://github.com/juankyt505/OPL-JUMP) | 5e103b9 | Content unchanged; JUMP1 filename filter stays PARTIAL (product call). |
| [OrbitPS2-Manager](https://github.com/Luden02/OrbitPS2-Manager) | moved | Desktop companion; INTENTIONAL DIFFERENCE. |
| [neutrino](https://github.com/rickgaiser/neutrino) | 1bff25b | The SMB work is already taken (NV2). |
| ps2homebrew/Open-PS2-Loader | unchanged | No new upstream master commits to compare. |

Our own repositories (RiptOPL, Open-PS2-Loader, Launchstation, launcHER, POPSLoader, PS2-Servers, PS2SP) account for seven of the twenty moved heads.

## Still MISSING and worth a look

In rough order of value; none is claimed by another thread:

1. **RI38 Recent Games capacity**: ours holds 10 entries, RIPPS2 holds 99. PARTIAL, small.
2. **DT6 in-game IOP memory relief** (above): needs the MTU decision first.
3. **RI54 List Title / Description** and **RI55 .pad profiles**: RIPPS2 feature work, product calls.
4. **RI10 / RI37** persistent library snapshot with Trust Cache: large; stays a comparison.
5. **O8 VRAM texture budget clamp, BL2 bounded artwork prefetch, LU37 / LU41 budgeted and direction-aware cover loading**: artwork pipeline comparisons, medium.
6. **RI25 / 27 / 29 / 34 / 39 / 40 / 41 / 42 / 43 / 45 / 46, NV1, H14**: unchanged source comparison candidates from October 29.

Work owned by other threads and deliberately left alone here: SMB2 restore (#257 / #258, #1219 / #1220), MMCE launch regression, the Tales of the Abyss freeze (#262 / #1222), GSM 1080p 4:3 (#260 / #1221) and the bug-report build (#261 / #1223).

## Method and limits

Per-record verdicts come from reading the current source of both editions, not from PR titles. The head recheck is `git ls-remote --heads --tags --symref` from the cloud container, compared with the October 29 heads file; a moved head was inspected only where this document says so. Rolling release assets can change without a tag; release metadata was not re-pulled. No console code ran.

Evidence set: [FORK-GAP-STATUS-2026-11-01.md](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-11-01/FORK-GAP-STATUS-2026-11-01.md) · [id-status.json](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-11-01/id-status.json) · [repository-heads.json](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-11-01/repository-heads.json). The searchable register stays at [fork-gaps.html#at-a-glance](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html#at-a-glance).
