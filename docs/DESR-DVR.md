# PSX DESR DVR ISO support (experimental, hardware gate)

RiptOPL distinguishes **standard `hdd0:` APA/HDLoader games** from the DVRP-managed
**`dvr_hdd0:` / `dvr_pfs0:` / `dvr_pfs1:`** filesystems.

## Reference implementation

- [pcm720/neutrino: bsd-dvr](https://github.com/pcm720/neutrino/tree/bsd-dvr), commit
  `aa8d80a1a0b5323cb407c814c0568c3489597c1c` (2026-09-19).
- Uses `bsd-dvr.toml`, `dvrdrv.irx`, `dvrfile.irx`, and `dvrfile_fhi.irx`.
- The DVR Neutrino performs a **PSX-mode transition and IOP reset** before loading
  the game. `-qb` must NOT be passed; it skips the transition.
  Preflight also refuses active `-bsd=` and `-bsdfs=` overrides in global or per-game
  Neutrino arguments, including a redundant `-bsd=dvr`. The loader owns that backend
  and filesystem path. `$-` disabled tokens and game arguments after `--b` in each
  scope remain allowed. Refusal happens in the menu before companion-file checks
  or launch teardown.

## Current integration boundary

Enable **DESR DVR ISOs (experimental)** in Game Sources, along with the HDD source.
The DVR switch defaults to off and does not bypass hardware detection.

The HDD tab has an **experimental read-only scanner** for ISO files under the
already available DVRP filesystem. It probes `dvr_hdd0:` and scans the roots,
`DVD/`, and `CD/` under `dvr_pfs0:` and `dvr_pfs1:`. It mounts the two known
DESR data partitions *read-only* if the DVR namespace exists and they are not
already mounted. It does not create, rename, format or delete DVR content.

**Hardware validation is still required.** RiptOPL checks the DESR DVR capability
bit (SPD_CAPS_DVR) and, only on that hardware, loads the SDK DVRP driver modules
after the regular DEV9/ATA stack. This follows the established wLaunchELF module
initialization order and never flashes firmware. The actual module/partition
behavior is not verified on a real DESR yet; ISO discovery and launching may
still fail pending DESR testing. Normal PS2 hardware never starts those drivers.

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

Refresh also preserves the last complete list if a directory that was previously
readable cannot be reopened. Missing optional directories on the initial scan do
not prevent discovery. A successful empty scan may clear the list.

The DVR Neutrino handoff leaves DVRP mounts in place: its load environment opens
the ISO and obtains a persistent DVR-side file handle after the IOP reboot.
Ordinary cleanup unmounts only DVR filesystems mounted by RiptOPL; a keep-IOP
handoff or an abandoned artwork reader retains them. This follows the reference
backend's ownership contract, but still requires DESR hardware validation.

### Next hardware-dependent steps

1. Confirm DVR capability and SDK DVR driver initialization on actual DESR-5000
   and DESR-7000 hardware, including cold boots, repeat boots, and clean exit.
2. Confirm `dvr_hdd0:` partition labels and read-only `dvr_pfsN:` mounts for
   both hardware families. No writes, deletions, format or firmware changes.
3. Verify the external pcm720 `bsd-dvr` Neutrino handoff and PSX-mode transition.
4. Confirm game-ID extraction from `SYSTEM.CNF` for non-ID ISO filenames and
   provide any additional DVR-only settings if hardware demands them.

**Firmware modification is not a prerequisite.** Do not flash DVRPwned as part
of testing this RiptOPL integration.

The GUI's bundled initialization modules come from PS2SDK (`dvrdrv.irx` and
`dvrfile.irx`) and are independent of pcm720's custom Neutrino modules.
Credit: ps2dev / PS2SDK, wLaunchELF DVR support, pcm720's bsd-dvr branch.

Automatic launch from remembered DVR entries remains disabled until the
DVRP partition identity survives that path safely. Manually select the game
in the HDD tab during experimental testing.
