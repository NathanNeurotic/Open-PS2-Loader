# Vapor HDD compatibility investigation - 2026-10-20

## Evidence and boundary

The supplied Discord screenshot reports Hajime no Ippo / Victorious Boxers and WinBack not
working from HDD. The user identifies official OPL 2049 as a working comparison. The screenshot
itself phrases the 2049 comparison as a belief. Exact game releases/serials, tested RiptOPL
build/flavour, settings and failure stage are not yet known. The user expects default settings
and a black screen; this is a working scenario, not a fresh console observation.

Official OPL 2049 is `513e9b3c`: its Makefile computes revision as reachable commits + 2,
and the historical upstream issue #1103 names `OPNPS2LD-v1.2.0-Beta-2049-513e9b3`.
Investigation base: `c1681d7a16d74c9b5f9d92c6da8082e8f171c0c7` on `rebuild/main`.
The primary checkout and its existing untracked files were preserved.

## Confirmed source defect

PR #962 (`ad43082f`) expanded SDK SIO2MAN packing from MX4SIO to VMC/PADEMU too.
`sysLaunchLoaderElf` still set `CORE_IRX_VMC` for every supported native launch, even when
`size_mcemu_irx == 0`. `hddLaunchGame` starts that size at zero and only makes it positive
for an active, validated VMC. Automatic VMC creation and PADEMU are off by default.

Consequently a default HDD launch packed and loaded SDK SIO2MAN despite having no consumer
that required it. Official 2049 and pre-#962 RiptOPL leave the game's SIO2MAN in charge here.
This is an unintended change to the game's IOP module environment. It is a plausible cause
of game startup regressions; it is not yet proven to cause either reported game failure.

The correction sets `CORE_IRX_VMC` only when `size_mcemu_irx > 0`, while preserving the
existing DISC/CF exclusions. Active VMC and PADEMU still select their SDK dependency.
MX4SIO still selects it independently. MMCE retains its existing SDK-SIO2MAN exclusion.
No game IDs, compatibility defaults, HDD geometry or sector reads are changed.

## Comparison findings

- Native HDD partition mapping in `device-hdd.c` remains equivalent to 2049, apart from API
  renames and the shared 64-bit logical-sector interface (the HDD media remains 32-bit).
- Other behavior differences include modern ATA readiness checks, real-media bound handling,
  safe copies for non-2048-byte reads, and EE/IOP reset/IGR changes. Source comparison alone
  does not exclude any of these as separate causes of the game reports.
- The two games must not be assumed to share one cause. Victorious Boxers also appears in
  PCSX2's timing-sensitive CDVD issue #4117; this is a lead, not OPL or console proof.

## Validation and acceptance

`test_mmce_sio2man_pack.py c1681d7a` reproduces the inappropriate dependency selection
using the actual production launch and packing conditions. The patched source passes the
same test, covering idle launches, positive/invalid MCEMU sizes, active VMC, PADEMU, MX4SIO,
MMCE and DISC/CF exclusions. Existing production SIO2MAN hook tests also pass.

A PS2 target build checks compilation/linking only. There has been no game execution,
emulator acceptance or physical-console acceptance in this investigation.

For the decisive console comparison, use the same installed game and console, same HDD,
same flavour and same effective per-game/global settings:

1. Reconfirm official 2049 reaches gameplay for each exact game release.
2. Confirm the unpatched comparison build fails under the same default configuration.
3. Run the candidate with VMC and PADEMU disabled, without changing compatibility modes.
4. Record whether it reaches title/menu/gameplay and whether real-card access works.
5. If it still fails, retain the report as unresolved; compare Mode 6 as one separate
   IGR experiment and collect a FREEZEDIAG report if the failure remains responsive.

Successful host tests or a linked ELF do not establish that Vapor's games are fixed.
Keep any PR as a candidate pending that A/B, and do not add global title defaults.

References:
- https://github.com/ps2homebrew/Open-PS2-Loader/issues/1103
- https://github.com/NathanNeurotic/Open-PS2-Loader/pull/962
- https://github.com/PCSX2/pcsx2/issues/4117
