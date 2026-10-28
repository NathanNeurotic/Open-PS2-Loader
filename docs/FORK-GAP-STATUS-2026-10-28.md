# Fork-gap status: 2026-10-28

> **This is the legacy version of RiptOPL.** Development has moved to ps2build's C++ Edition at
> [NathanNeurotic/RiptOPL](https://github.com/NathanNeurotic/RiptOPL). This repository gets legacy
> maintenance and the fixes that land in both editions. RiptOPL carries the same page in its `docs/`.

This page records where the two RiptOPL repositories stand against each other, which fixes
landed in both on October 27 and 28, what the RIPPS2 audit found, and what still has no hardware
result. The broader ecosystem register (LUNA, YAOPL, PSXCore, wOPL and the rest) is unchanged
since its October 25 refresh; see the
[fork feature gaps page](https://nathanneurotic.github.io/Open-PS2-Loader/fork-gaps.html).

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

### Backend fixes RIPPS2 has and both RiptOPL repositories lack

| Item | Where the gap is | Status | Plan |
| --- | --- | --- | --- |
| Clear the BDM "module loaded" flags after an IOP reset (after the NBD server stops, iLink, MX4SIO, HDD-BDM, PC CARD CF and UDPBD otherwise never reload until reboot) | RiptOPL `src/sources/bdmsupport.cpp` flags are never cleared; same in the C `bdmsupport.c` | MISSING | PR A |
| mmceman upstream fix `21dbc0a` "don't block mc1 (2nd port)" | Both pin `db3e93f0`; RiptOPL ships its own `mmceman_fork` | MISSING | PR A: port the hunk into the fork, keep the pin |
| MMCE Game ID: wait to see "busy" before waiting for "not busy", with a longer budget and a skip | RiptOPL `src/sources/mmcesupport.cpp` polls 15 x 200 ms (about 3 s) and stops at the first not-busy read | MISSING (the link to the Burnout 3 hang is RIPPS2's report, not verified here) | PR A, with a visible skip; needs MMCE hardware before merge |
| FreeType built with only the modules the fonts need | RiptOPL `fntsys.cpp` links every module | MISSING | PR A |
| POPS file sets (`POPS_IOX.PAK` + `POPS.PAK`, or `POPS.ELF` + `IOPRP252.IMG`) and a warning when files are missing | Neither name is in RiptOPL's source; it may reach POPS another way | UNKNOWN | PR A: missing-files warning |
| Ogg pages whose serial has the top bit set (refused by the PS2 Vorbis library) | `bgm.cpp` has no workaround; ps2build's libogg may not have the problem | UNKNOWN | PR A only if it reproduces |
| Neutrino options read from the `neutrino.elf` actually installed | `sysNeutrinoPreflight` does not check the version | MISSING | Not scheduled |
| IGR exit path checked before use, else Browser | ee_core loads only rom0 SIO2MAN/MCMAN and USB before the exit path, so MMCE and HDD exit paths cannot work | PARTIAL | Not scheduled |
| exFAT lost clusters when two files grow at once (RIPPS2's claim against the ps2sdk driver) | Not investigated; RiptOPL ships its own bdmfs FatFs fork | UNKNOWN | Reproduce on a PC image first |
| PCSX2 `host:` launch: rename the `imgdrv` device from `host` to `iprp` | `imgdrv.c` and `ee_core iopmgr.c` still use `host` in both | INTENTIONAL DIFFERENCE | Owner decision 2026-10-28: not planned |
| Pad missed-read hold, pad idle gate before `padSetActAlign`, analog-mode re-request | `src/core/pad.cpp` | INTENTIONAL DIFFERENCE | Owner decision 2026-10-28: not planned |

Already PRESENT, no action: the ps2ips receive tail (#1064), the exFAT HDD device number on a USB
boot, ee_core `gc-sections`, and the single-shape save icon. RiptOPL's hires HD drawing is sharper than RIPPS2's
single-pass 640-wide drawing; that difference is intentional.

### Feature port plan (in progress)

Agreed with the owner on 2026-10-28. Each PR lands in both repositories. As of this page, no port
PR has been opened; this table is the plan, not shipped work.

| PR | Scope |
| --- | --- |
| A | Backend fixes above, plus the POPS missing-files warning |
| B | Art: JPG covers, OPL Manager art names (`_BG_00`, `_SCR_00`, `_SCR_01`), case-insensitive names on PFS |
| C | One unified library setting: hides the device icons, L3 cycles All/PS2/PS1/APP, duplicates tagged by device, sort by last played, Recents (last 10), Random Game in the start menu under Launch Disc |
| D | `hidden.txt` to hide games, and a full delete of a game's parts, CFG, art and cheats (no APA partition delete) |
| E | Right-to-left (Arabic, Persian) shaping and CJK/Lao line breaking; akilluminati47's translations offered to the language repository |
| F | STATUS page for drives and a `DIAG.TXT` boot report |
| G | Smaller GUI items (scroll bar, dimmed disabled rows, glyph sets and similar) |
| H | Offer to copy a PS1 game into POPS format, and a minimal manager that shows a VMC as a folder |

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
8. Each RIPPS2 port as it lands. The MMCE Game ID wait and mmceman `21dbc0a` need an SD2PSX with
   sd2psXtd firmware (8 MB card, Burnout 3) and an MMCE in slot 1 with a normal card in slot 2.

Sources: the parity switch-readiness report and final sweep (2026-10-27), the fix cross-check
(2026-10-28) and the RIPPS2 audit (2026-10-28), rechecked against the commits in the table at the
top.
