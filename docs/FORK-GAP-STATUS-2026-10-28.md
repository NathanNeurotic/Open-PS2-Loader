# Fork-gap status: 2026-10-28

> **This is the legacy version of RiptOPL.** Development has moved to ps2build's C++ Edition at
> [NathanNeurotic/RiptOPL](https://github.com/NathanNeurotic/RiptOPL). This repository gets legacy
> maintenance and the fixes that land in both editions. RiptOPL carries the same page in its `docs/`.

This page records where the two RiptOPL repositories stand against each other, which fixes
landed in both on October 27 and 28, what the RIPPS2 audit found, and what still has no hardware
result. The full ecosystem register (LUNA, YAOPL, PSXCore, wOPL and the rest), refreshed on
October 25 and head-checked on October 28 (section 5), is on the
[fork feature gaps page](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html), and
the same register is on [RiptOPL's site](https://nathanneurotic.github.io/RiptOPL/fork-gaps.html).

| Tree | Ref | Commit |
| --- | --- | --- |
| RiptOPL (C++ / ps2build, main line) | `rebuild/main` | [`4dab9cc0`](https://github.com/NathanNeurotic/RiptOPL/commit/4dab9cc0c79f1393f1f70ba80b954463e06a2803), merge of #96 |
| Open-PS2-Loader (C, legacy edition) | `rebuild/main` | [`94e82f2b`](https://github.com/NathanNeurotic/Open-PS2-Loader/commit/94e82f2b2795fc8faf5ff87dce8e39d63030e073), merge of #1080 |
| Korium skin branch (legacy) | `test/korium-audit-remediation` | `285b6f59` |
| [RIPPS2](https://github.com/akilluminati47/RIPPS2) by akilluminati47 | `main` | `95299389`, build 119 (v1.1.8-beta) |

**Evidence level.** Every status below comes from reading the source at those commits, host
tests and CI builds. **Nothing on this page has been tested on real PS2 hardware.** A green
build is not a hardware result. Status words: PRESENT, PARTIAL, MISSING, INTENTIONAL
DIFFERENCE, UNKNOWN.

## 1. RiptOPL and Open-PS2-Loader

The parity port is merged. RiptOPL
[#77](https://github.com/NathanNeurotic/RiptOPL/pull/77) (merge `894dca36`, 2026-10-27) brought
the C++ edition to parity with Open-PS2-Loader `38ea46a`, and
[#78](https://github.com/NathanNeurotic/RiptOPL/pull/78) (merge `f79a4ea6`) added the
matching site pages. A final sweep against Open-PS2-Loader `4cfde79c` found every merged change
present, apart from three Korium-edition items that lived only on the Korium skin branch. They
were ported inside #77 (`7c21f5c0`, with `test_korium_builtin_assets.py`) and are present at
`4dab9cc0`:

| # | Korium item | RiptOPL at `4dab9cc0` |
| --- | --- | --- |
| K1 | "Players" badge glyphs for the built-in theme | PRESENT: `src/gfx/themes.cpp` loads `PLAYERS_1..PLAYERS_4` under `BUILTIN_KORIUM` |
| K2 | Background Art off on a fresh Korium install | PRESENT: `src/core/settings.cpp` defaults `gEnableBGArt` to 0 for Korium (and the RA edition), 1 for inceBtion |
| K3 | Korium app placeholder and no foliage layer | PRESENT: `src/gfx/textures.cpp` maps `COVERAPP_DEFAULT` to the Korium cover and `CASE_OVERLAY2` to NULL |

Open defect and feature issues were moved from Open-PS2-Loader to RiptOPL, each original linking
its new issue: #1018 to [RiptOPL#86](https://github.com/NathanNeurotic/RiptOPL/issues/86), #1036
to #81, #525 to #79, #433 to #80, #987 to #87, #972 to #88, #763 to #82, #690 to #83, #611 to #84
and #331 to #85. The RiptOPL parity tracker, issue #20, is closed.

Intentional differences, not gaps:

- One SDK (ps2build) in RiptOPL. Open-PS2-Loader's toolchain flavours (OFFICIALROLLING,
  PS2DEVPINNED and the rest), MEGA archival, wiki sync and rolling-order CI belong to the old
  Makefile release.
- Open-PS2-Loader keeps a pinned `current-fan-favorite` release. RiptOPL has no equivalent.
- The English label for GameID mode 1 differs: Open-PS2-Loader says "On (PS1 only)", RiptOPL
  "On (POPSTARTER only)". "PS1 only" is the more accurate one, since the barcode covers Ember too.
  Not changed yet.

## 2. Fixes merged on 2026-10-27 and 2026-10-28

A cross-check of every PR merged into either repository since 2026-10-26 found each fix in both,
after three follow-ups (RiptOPL #96, #97 and Open-PS2-Loader #1080).

| Fix | Open-PS2-Loader | RiptOPL |
| --- | --- | --- |
| Settings save on an empty USB slot: save to the booted ELF's slot, name the real error instead of "error 12" | [#1077](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1077) | [#94](https://github.com/NathanNeurotic/RiptOPL/pull/94) |
| Skip MX4SIO on a `host:` boot (it hung the boot screen under PCSX2) | [#1080](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1080) | [#95](https://github.com/NathanNeurotic/RiptOPL/pull/95) |
| `test_mx4sio_host_boot.py` runs in CI | #1080 | [#96](https://github.com/NathanNeurotic/RiptOPL/pull/96) |
| `DEFAULTS.md` GameID barcode row (the PS1 half ships on) | #1080 | [#92](https://github.com/NathanNeurotic/RiptOPL/pull/92) |
| Neutrino kits replace the i.LINK manager too; no untracked warning after a declined preview | already present | [#90](https://github.com/NathanNeurotic/RiptOPL/pull/90) |
| RA handoff marker, overflow launches untracked, RA kit keeps the i.LINK pair (#1065); Okeanos credit (#1069); RA sender check (#1071); compat default core (#1072) | [#1075](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1075) | in #77 |
| Site page errors (#1073) | [#1076](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1076) (gh-pages) | in [#91](https://github.com/NathanNeurotic/RiptOPL/pull/91) |
| Cheats page: Neutrino cheat runtime and the mastercode requirement | [#1078](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1078) (gh-pages) | #91, wording fixed in [#97](https://github.com/NathanNeurotic/RiptOPL/pull/97) |
| One tap moving two rows on the first press after boot | [#1074](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1074) | `1c16f063` in #77 |
| smbman write count and ByteCount, i.LINK SBP-2 status decode, ps2ips receive tail, `ul.cfg` safe rewrite (#1068) | [#1064](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1064) | in #77 |
| Per-core title compat defaults, menu rumble off, UDPFS ART-index skip (#1070) | [#1066](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1066) | in #77 |

One-sided by design: the legacy notices (Open-PS2-Loader #1064, #1067, #1079) belong to the
legacy edition only, and RiptOPL's LLVM CI job (#89) and main-line framing (#91, #92) to the C++
edition only.

## 3. RIPPS2

[RIPPS2](https://github.com/akilluminati47/RIPPS2) is **akilluminati47**'s RiptOPL-derived
frontend. The findings in this section are theirs: the audit read RIPPS2's own source and
changelog reasons and checked each one against our code. RIPPS2 is a patch stack (71 patches) on
the legacy C tree (`65d4b89`, upstream mark `57c45b4`), so nothing cherry-picks into the C++
edition; every item is a port by hand. RIPPS2 and RiptOPL share code freely. Every port carries
credit to akilluminati47 in its commits.

**Rule for these ports:** each one lands in both RiptOPL and Open-PS2-Loader. An item that
cannot be ported to one of them gets an issue instead.

### Backend fixes from RIPPS2

Status as of the merge of RiptOPL #99 (`09ea7d83`) and Open-PS2-Loader #1084 (`fcafb991`) on
2026-10-28. Shipped means merged in both; none of it is tested on hardware.

| Item | Where the gap was | Status | Where |
| --- | --- | --- | --- |
| Clear the BDM "module loaded" flags after an IOP reset (after the NBD server stops, iLink, MX4SIO, HDD-BDM, PC CARD CF and UDPBD otherwise never reload until reboot) | RiptOPL `src/sources/bdmsupport.cpp` flags were never cleared; same in the C `bdmsupport.c` | SHIPPED (BDM, HDD, MMCE and UDPFS latches) | RiptOPL #99, OPL #1084 |
| mmceman upstream fix `21dbc0a` "don't block mc1 (2nd port)" | Both pinned `db3e93f0`; RiptOPL ships its own `mmceman_fork` | SHIPPED: pin moved to `de28936f`, only `sio2man_hook.c` changed | RiptOPL #99, OPL #1084 |
| MMCE Game ID: wait to see "busy" before waiting for "not busy", with a longer budget and a skip | RiptOPL `src/sources/mmcesupport.cpp` polled 15 x 200 ms (about 3 s) and stopped at the first not-busy read | SHIPPED: up to 2 s to see busy, then an on-screen wait (START skips, 180 s cap). The Burnout 3 link is RIPPS2's report, not verified here | RiptOPL #99, OPL #1084 |
| FreeType built with only the modules the fonts need | RiptOPL `fntsys.cpp` linked every module | SHIPPED: TrueType and CFF only (about 120 KB smaller unpacked) | RiptOPL #99, OPL #1084 |
| POPS file sets (`POPS_IOX.PAK` + `POPS.PAK`, or `POPS.ELF` + `IOPRP252.IMG`) and a warning when files are missing | Neither name was in RiptOPL's source | SHIPPED: a launch asks first when the files are missing, and offers to copy them from another started drive | RiptOPL #99, OPL #1084 |
| Ogg pages whose serial has the top bit set (refused by the PS2 Vorbis library) | `bgm.cpp` has no workaround | NOT NEEDED: upstream libogg 1.3.5 and libvorbis 1.3.7 (what ps2build ships) decode such a file | Checked in RiptOPL #99; not ported |
| Neutrino options read from the `neutrino.elf` actually installed | `sysNeutrinoPreflight` does not check the version | MISSING | Not scheduled |
| IGR exit path checked before use, else Browser | ee_core loads only rom0 SIO2MAN/MCMAN and USB before the exit path, so MMCE and HDD exit paths cannot work | PARTIAL | Not scheduled |
| exFAT lost clusters when two files grow at once (RIPPS2's claim against the ps2sdk driver) | Not investigated; RiptOPL ships its own bdmfs FatFs fork | UNKNOWN | Reproduce on a PC image first |
| PCSX2 `host:` launch: rename the `imgdrv` device from `host` to `iprp` | `imgdrv.c` and `ee_core iopmgr.c` still use `host` in both | INTENTIONAL DIFFERENCE | Owner decision 2026-10-28: not planned |
| Pad missed-read hold, pad idle gate before `padSetActAlign`, analog-mode re-request | `src/core/pad.cpp` | INTENTIONAL DIFFERENCE | Owner decision 2026-10-28: not planned |

Already PRESENT, no action: the ps2ips receive tail (#1064), the exFAT HDD device number on a USB
boot, ee_core `gc-sections`, and the single-shape save icon. RiptOPL's hires HD drawing is sharper than RIPPS2's
single-pass 640-wide drawing; that difference is intentional.

### Feature port (shipped)

Agreed with the owner on 2026-10-28. Groups A to H all landed in one PR per repository, both
merged on 2026-10-28: [RiptOPL#99](https://github.com/NathanNeurotic/RiptOPL/pull/99) (`09ea7d83`)
and [Open-PS2-Loader#1084](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1084)
(`fcafb991`), plus the translations in
[Open-PS2-Loader-lang#2](https://github.com/NathanNeurotic/Open-PS2-Loader-lang/pull/2). Host tests
only: NOT TESTED on hardware.

| Group | Scope | User docs |
| --- | --- | --- |
| A | Backend fixes above, plus the POPS missing-files question | [Launch diagnostics](LAUNCH-DIAGNOSTICS.md), [PS1](VCD.md) |
| B | Art: JPG and JPEG, OPL Manager names (`_BG_00`, `_SCR_00`, `_SCR_01`), any letter case in listed `ART` folders | [Game library](GAME-LIBRARY.md#game-art-jpg-any-letter-case-and-opl-manager-names) |
| C | All Games List (device tabs step aside, L3 cycles All/PS2/PS1/Apps/Favourites/Recent, duplicates tagged by device), Sort Games: Last played, Recent (last 10), Random Game in the Start menu | [Game library](GAME-LIBRARY.md) |
| D | `hidden.txt` and Hide Game; Delete removes a game's parts, CFG, art and cheats (no APA partition delete) | [Game library](GAME-LIBRARY.md#hide-game) |
| E | Arabic and Persian shaping, right-to-left lines, CJK/Thai/Lao line breaks; 13 missing translations from akilluminati47's language files | [Languages](LANGUAGES.md#right-to-left-and-cjk-text) |
| F | Drive Status page and `DIAG.TXT` | [Launch diagnostics](LAUNCH-DIAGNOSTICS.md#drive-status-and-diagtxt) |
| G | Dimmed switched-off rows, scroll bar, right-stick peek, return to the opening button, button glyph sets, `<font>_weight` | [Controls](CONTROLS.md), [Interface](INTERFACE.md#button-glyphs), [Theme engine](THEME_ENGINE.md) |
| H | Offer to copy Sony's POPS files from another drive; a Saves page that treats a VMC like a folder | [PS1](VCD.md#sonys-pops-files), [VMC](VMC.md#saves-on-a-card) |

### Not taken

- Declined by the owner: disc ripping, the CD player, and every HDD partition change (the
  relaxed APA fence in `hdd_fio.c`, BOOT LOCK's rewrite of FMCB/PS2BBL/OSDMenu configs, and
  BIBLE's MBR write). RiptOPL's APA fence exists to protect PSBBN and OSD installs.
- The Planet N fonts (Iconian) are third-party and stay out.
- RIPPS2's `elf/tests/expected_failures.txt` lists RiptOPL tests it breaks on purpose
  (`apa_table_safety`, `sfx_oneshot_cut`, `psbbn_flow`, `ra_cards_setting`, `igr_polling`,
  `ingame_freeze_diag`, `net_protocol_pick` and others). Any port keeps them green.
- RIPPS2's mmceman pin lacks Open-PS2-Loader's `mmceman-fs-dread-eof.patch`; only the upstream
  hunk is ported.

## 4. Not tested on hardware

Everything above. The open console checks, in priority order:

1. The parity port's 14-row matrix: fresh install of each kit; USB FAT32 and exFAT ISO and ZSO
   launches (native and Neutrino); internal HDD APA and exFAT games; USBLD rename and delete;
   switching SMB to UDPFS; SMB VMC saves; the RA kits (login and unlock, USB and Neutrino); the
   pademu0, DualSense, debug freeze-report and language packages; POPS VCD over USB and UDPFS.
2. Korium: a game whose CFG has `Players=2` shows the badge; a fresh install starts with
   Background Art off.
3. Settings save on an empty USB slot. The reporter still owes the full error text and launcher.
4. MX4SIO skip on `host:`: PCSX2 boot from `host:` no longer hangs; a real-console MX4SIO boot is
   unchanged.
5. One tap moves one row on the first press after boot (the original reporter's pad and console).
6. i.LINK after reset ([RiptOPL#86](https://github.com/NathanNeurotic/RiptOPL/issues/86), was
   #1018), in this order: native, Neutrino, POPStarter.
7. UDPFS covers on the first connect ([RiptOPL#81](https://github.com/NathanNeurotic/RiptOPL/issues/81),
   was #1036), Neutrino core, OPL Manager art.
8. The RIPPS2 port (RiptOPL #99, Open-PS2-Loader #1084): every group A to H above. The MMCE Game ID wait and mmceman `21dbc0a` need an SD2PSX with
   sd2psXtd firmware (8 MB card, Burnout 3) and an MMCE in slot 1 with a normal card in slot 2.

## 5. Ecosystem head check

On 2026-10-28 at 06:28 UTC every repository ref from the October 25 sweep, 134 in all, was
checked again with `git ls-remote`: 10 changed, 124 unchanged, none unavailable. The ref list is
[`audit/2026-10-28/repository-heads.json`](https://nathanneurotic.github.io/Open-PS2-Loader/audit/2026-10-28/repository-heads.json) on the site.
Three of the changed repositories are ours (Open-PS2-Loader, Launchstation, PS2-Servers). The
others:

| Project | Head | What changed |
| --- | --- | --- |
| [RIPPS2](https://github.com/akilluminati47/RIPPS2) | [`e1e3504f` to `1f356eec`](https://github.com/akilluminati47/RIPPS2/compare/e1e3504f4a8bfd6b2f88425d284eb845393cfcb9...1f356eecfeda6e11e018ed8c03b320862455c659) | Builds 115 to 119. Up to `95299389` is covered by section 3. Newer and not yet checked against our code: 16:9 art crop (`c2b94d6`), boot sound sent by the IO worker only and media with Music off (`1f356ee`). |
| [YAOPL](https://github.com/belomaxorka/yaopl) | [`33a2b19a` to `ac3cf25c`](https://github.com/belomaxorka/yaopl/compare/33a2b19a8afa37b50015eeb1414f575b2270ac7d...ac3cf25c6dd05570e75b2dffff44ee46dd4d6361) | UDP block device in the OPL core (`b3ff109`): RiptOPL only had it in the menu, and now also runs UDPBD and UDPFS IMG games on `<OPL>` per game, with YAOPL's 16 KiB UDPBD read cap (`12cc6fb`); the LBA48 ATA fix (`e09f548`), see YA2 below; docs site, CI, changelog. |
| [LUNA](https://github.com/dnunezx/LUNA) | [`78096fb3` to `193f1879`](https://github.com/dnunezx/LUNA/compare/78096fb32900d561b2fca7716a2d029cbce11caa...193f1879c5cecaf931f8ffa6dcb897cd981e97c6) | Crystal menus, unified PS1/PS2 memory cards, widescreen cheat fixes with a paired Neutrino handoff, manual CI builds (commit messages only). |
| [neutrino-luna](https://github.com/dnunezx/neutrino-luna) | [`02cbf4f2` to `833344a5`](https://github.com/dnunezx/neutrino-luna/compare/02cbf4f2a0bafcba71904f7d9d8fcda6ddd65f15...833344a570e3622ea315091284c8444f7e06bc88) | Long LUNA launch arguments survive PS2 startup (commit message only). |
| [xeRAbora](https://github.com/hacan359/xerabora) | [`faf24cdd` to `41dacb12`](https://github.com/hacan359/xerabora/compare/faf24cdd4e2790868c880899bd58c8f775539d50...41dacb12f0050fe693fb99a215f171a252e32cfd) | Release 1.0.1 of the desktop companion. |
| [OdysseyLauncher](https://github.com/GeekRhapsody/OdysseyLauncher) | [`bc1b8593` to `ac21ee45`](https://github.com/GeekRhapsody/OdysseyLauncher/compare/bc1b85931871a65b6948764d00cd5182e2e873b8...ac21ee45ef77f96f7eadd42468988237192dbb50) | v0.20.0, 3D console models; desktop frontend. |
| [PS2SP](https://github.com/johnson-cooper/PS2SP) | [`cb040e79` to `7f6fb2d4`](https://github.com/johnson-cooper/PS2SP/compare/cb040e79dfd467aa99252575c9d6fd97684116de...7f6fb2d404abcf8cd12e709e3b0441f011adea48) | Catalogue automation; not a loader feature. |

New register record **YA2**. `modules/iopcore/cdvdman/atad.c` counted the sectors of one LBA48
command in a 16-bit `len` (line 675). A request of 65,536 sectors or more stored 0, advanced by
nothing and repeated forever while holding the ATA semaphore. RiptOPL and Open-PS2-Loader both
had it. YAOPL `e09f548` and [ps2sdk PR 913](https://github.com/ps2dev/ps2sdk/pull/913) fix it by
counting each command in a 32-bit chunk. No known caller sends a request that large, so this is
hardening. Source review only; not tested on hardware.

**Fixed 2026-10-28** in both editions with the same 32-bit chunk, credited to YAOPL and ps2sdk:
RiptOPL [#105](https://github.com/NathanNeurotic/RiptOPL/pull/105) and Open-PS2-Loader [#1087](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1087). Not tested on hardware.

Sources: the parity switch-readiness report and final sweep (2026-10-27), the fix cross-check
(2026-10-28), the RIPPS2 audit (2026-10-28) and the ecosystem head check (2026-10-28), rechecked
against the commits in the table at the top.
