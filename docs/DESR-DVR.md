# PSX DESR DVR ISO support (experimental, hardware gate)

RiptOPL distinguishes **standard `hdd0:` APA/HDLoader games** from the DVRP-managed
**`dvr_hdd0:` / `dvr_pfs0:` / `dvr_pfs1:`** filesystems.

## Reference implementation

- [pcm720/neutrino: bsd-dvr](https://github.com/pcm720/neutrino/tree/bsd-dvr), commit
  `aa8d80a1a0b5323cb407c814c0568c3489597c1c` (2026-09-19).
- Uses `bsd-dvr.toml`, `dvrdrv.irx`, `dvrfile.irx`, and `dvrfile_fhi.irx`.
- The DVR Neutrino performs a **PSX-mode transition and IOP reset** before loading
  the game. `-qb` must NOT be passed; it skips the transition.

## Current integration boundary

The HDD tab has an **experimental read-only scanner** for ISO files under the
already available DVRP filesystem. It probes `dvr_hdd0:` and scans the roots,
`DVD/`, and `CD/` under `dvr_pfs0:` and `dvr_pfs1:`. It mounts the two known
DESR data partitions *read-only* if the DVR namespace exists and they are not
already mounted. It does not create, rename, format or delete DVR content.

**This is NOT full out-of-box DESR support yet.** RiptOPL currently does not
bootstrap the DVRP modules into the GUI after its normal IOP reset / PSX-mode
switch. Consequently a normal installation may show no DVR entries even though
the disk holds ISOs. Driver initialization and hardware validation are still
required before this capability can be called supported.

Only the external pcm720 `bsd-dvr` Neutrino implementation can launch these ISO
rows. The regular bundled Neutrino typically does not contain DVR modules.
Install the FULL DVR-capable Neutrino directory on an accessible device and
select its `neutrino.elf` using RiptOPL's **Neutrino Path** setting.
A launch emits `-bsd=dvr -dvd=dvr_pfsN:/path/file.iso`; it never falls back to
the embedded OPL HDD core. Existing APA games are unchanged.

The DVR scanner presently limits its complete list to 128 titles, preserves the
last valid list after unreadable scans, and rejects truncated paths. Ordinary
APA/HDL game cache files are never modified by DVR discovery. PS1 VCD, virtual
memory card, and DVR-side write support are **not** claimed.

### Next hardware-dependent steps

1. Detect DESR hardware and explicitly initialize the DVRP drivers in PSX mode
   without disrupting the already active GUI/APA clients.
2. Confirm how `dvr_hdd0:` and the `__xcontents` / `__xdata` mount points are
   exposed on DESR-5000 and DESR-7000 families and never mount over a user's data.
3. Validate actual ISO enumeration, Neutrino module availability and the PSX
   transition with a DESR tester.
4. Confirm game-ID extraction from `SYSTEM.CNF` for non-ID ISO filenames and
   provide any additional DVR-only settings if the hardware tests demand them.

**Firmware modification is not a prerequisite.** Do not flash DVRPwned as part
of testing this RiptOPL integration.
