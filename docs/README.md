# RiptOPL documentation

Current comparison: [Full ecosystem fork-gap refresh - October 29, 2026](FORK-GAP-FULL-REFRESH-2026-10-29.md) (301 provenance records; 152 stable families). Source/branch/release evidence and console acceptance are recorded separately.

Start with [installation and first boot](https://nathanneurotic.github.io/Open-PS2-Loader/install.html)
and [your first game](https://nathanneurotic.github.io/Open-PS2-Loader/getting-started.html).
The [website](https://nathanneurotic.github.io/Open-PS2-Loader/) provides searchable task guides;
the [wiki](https://github.com/NathanNeurotic/Open-PS2-Loader/wiki) offers the same guides in GitHub.
Use the references below for implementation details, exact limits and contributor workflows.

- [October 29 ecosystem fork-gap reconciliation](FORK-GAP-ECOSYSTEM-AUDIT-2026-10-29.md) — current refs/releases, merged and pending work, and every stable record.

## Installation and troubleshooting

| Task | Reference |
| --- | --- |
| Choose a release, SDK flavour or package | [Release reference](../ROLLING_RELEASE.md) |
| Test a PR artifact or collect freeze diagnostics | [Test builds](TEST-BUILDS.md) |
| Understand defaults and saved settings | [Fresh-start defaults](DEFAULTS.md) |
| Diagnose setup or a failed launch | [Setup questions](SETUP-QUESTIONS.md) · [Troubleshooting](https://nathanneurotic.github.io/Open-PS2-Loader/troubleshooting.html) |
| Separate package, core, transport and launch-stage failures | [Launch diagnostics](LAUNCH-DIAGNOSTICS.md) |
| Recover a failed VMC creation | [VMC creation and recovery](VMC.md) |
| Copy, move or delete files, back up saves as PSU | [File Manager](FILE_MANAGER.md) |
| Diagnose an APA disk without formatting it | [APA safety](APA-SAFETY.md) · [Recovery tool](../pc/apa-recovery/README.md) |

## Sources and game cores

| Topic | Reference |
| --- | --- |
| Game image formats | [ISO, ZSO, CHD, CSO and server decoding](GAME-FORMATS.md) |
| USB, MX4SIO and iLink | [Device setup](https://nathanneurotic.github.io/Open-PS2-Loader/usb.html) · [MX4SIO launch notes](MX4SIO.md) |
| MMCE | [MMCE setup](https://nathanneurotic.github.io/Open-PS2-Loader/mmce.html) |
| Internal HDD | [APA/exFAT guide](https://nathanneurotic.github.io/Open-PS2-Loader/hdd.html) · [exFAT and APA-Jail](EXFAT.md) |
| SMB / UDPFS / UDPBD | [SMB](https://nathanneurotic.github.io/Open-PS2-Loader/smb.html) · [Network boot](https://nathanneurotic.github.io/Open-PS2-Loader/network-boot.html) |
| HTTP | [HTTP profile and limits](HTTP.md) · [Host conformance tools](../pc/http/README.md) |
| Neutrino | [Installation, core selection, arguments, cheats and VMC](NEUTRINO.md) |
| PS1 | [POPSTARTER and Ember](VCD.md), including POPS UDPFS and device/core restrictions |
| RetroAchievements | [RA setup and runtime limits](RETROACHIEVEMENTS.md); requires its separate kit |
| Experimental hardware | [PC CARD CF](PC-CARD-CF.md) · [PSX DESR DVR](DESR-DVR.md) |

## Settings and customization

- [Controls](CONTROLS.md), [in-game reset](IGR.md), [GSM video](GSM.md) and [PADEMU](PADEMU.md).
- [Interface, folders and audio](INTERFACE.md), [theme authoring](THEME_ENGINE.md), [languages](LANGUAGES.md) and [Unicode game titles](UNICODE-GAME-TITLES.md).
- [Game library](GAME-LIBRARY.md): All Games, Recent, Sort Games, Random Game, Hide Game, Delete and JPG art.
- [Per-game parental locks](PARENTAL-LOCK.md) and [autolaunch/global settings](AUTOLAUNCH-GLOBAL-SETTINGS.md).
- [SIO2MAN compatibility](SIO2MAN-COMPATIBILITY.md) for contributors investigating VMC/pad hooks.
- [Notes for ps2sdk](PS2SDK-NOTES.md): the ps2sdk defects behind every SDK module the fork builds or
  patches itself, and whether ps2sdk master still has them.

## Documentation maintenance and history

[Maintenance](MAINTAINING-DOCS.md) explains which source owns each surface, how to validate
changes, and how to regenerate search and wiki content. The [October audit](DOCUMENTATION-AUDIT-2026-10.md)
records the reviewed revisions, corrections, link evidence and remaining validation limits.

[Fork collaboration](FORK-COLLABORATION.md) explains candidate triage and evidence boundaries;
the [October 25 audit](DOCUMENTATION-AUDIT-2026-10-25.md) records the last full refresh.
[Fork-gap status: 2026-10-28](FORK-GAP-STATUS-2026-10-28.md) is the current summary: parity with
RiptOPL, fixes landed in both editions, the RIPPS2 audit and port plan, and the open hardware checks.

Integration plans, dated audits, community-report handoffs and `docs/superpowers/` are engineering
history. Their old DONE/pending states, branches and package names describe that baseline;
they are not current installation instructions. Start with the current reference above.
Historical records remain available for provenance: [gap ledger](DOCUMENTATION-GAPS.md),
[community reports](COMMUNITY_REPORTS_HANDOFF_2026-10-02.md), [contributor roadmap](TECH_CONTRIBUTOR_ROADMAP_2026-10-03.md),
[VMC audit](VMC-AUDIT-2026-10-08.md), [Ember plan](EMBER-INTEGRATION-PLAN.md),
[HTTP plan](HTTP-INTEGRATION-PLAN.md), [RA plan](RETROACHIEVEMENTS-INTEGRATION-PLAN.md) and
[legacy changelog](OLD_DETAILED_CHANGELOG).
