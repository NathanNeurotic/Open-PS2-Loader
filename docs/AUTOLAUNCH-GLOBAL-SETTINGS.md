# Auto Loading global settings (#545)

Issue [#545](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/545) tracks
[CosmicScale's upstream report](https://github.com/ps2homebrew/Open-PS2-Loader/issues/1768)
on an SCPH-50001. The reporter supplied an APA/PFS ELF path with BDM game arguments:

```text
path = hdd0:__system:pfs:/launcher/OPNPS2LD.ELF
arg = Fantavision.iso
arg = SCUS_971.05
arg = DVD
arg = bdm
```

The settings are reported at the ATA root. The reply repeats `conf_opl.cfg`;
for this investigation the intended second filename is assumed to be
`conf_game.cfg`, consistent with the original report. This is sufficient to
review the mixed layout without requiring more work from the reporter.
Nathan has not reproduced it locally. The root cause of the upstream behavior
is still unconfirmed: upstream revision `3e3f34e9` already calls
`checkLoadConfigBDM(CONFIG_ALL)` after an initial master-config miss, and that
helper attempts to read globals as well as the master config.

## Change and scope

`miniInit()` now resolves its boot/settings home for every launch mode and uses
`tryAlternateDevice(CONFIG_ALL, mode)` when the first read misses `CONFIG_OPL`, using
the GUI's recovery entry point. The three mode-specific `checkLoadConfig*` calls
are removed. Its existing BDM semaphore initialization also runs for every mode:
an APA game can have a BDM-hosted launcher or custom settings home, and the reused
transport helpers acquire that semaphore.

An APA/PFS boot with BDM argv is the deliberate exception to the initial-read
gate: the ELF's PFS data home can contain a different master config from the
game's ATA filesystem. For that combination, `tryAlternateDevice` first tries
the existing explicit `config.path` redirect, then the first ATA-backed `massN:`
root, then the existing PFS fallback. The ATA root is selected by driver identity,
not by taking the first readable USB slot. It uses the existing bounded HDD
readiness helper, and accepts a settings bundle only when its master config loads.
GUI and HDL launches pass no BDM autolaunch mode and retain their existing policy.

The shared GSM, cheats, PADEMU, pad-macro and OSD-language application code and
the on-disk meaning of Global are unchanged. Per-game CFG files still come from
the game device. An absent `conf_game.cfg` by itself does **not** trigger recovery.
The mixed-layout exception is based on the launch mode and boot device, not on
whether global settings exist. No new loading helper or filesystem writes are added.

## Source review (not runtime tests)

| Layout/state | Path through the existing helpers |
| --- | --- |
| APA/PFS ELF, BDM/ATA game, settings at ATA root | Explicit redirect first, then ATA-identified `massN:/`, then PFS. Also applies if the initial PFS home contains another master config. |
| Launcher `mc0:/APPS`, settings `mc0:/OPL` | Initial read misses; same-card recovery reads `/OPL`, including `CONFIG_GAME`. MC1 uses the same slot-preserving rule. |
| BDM launcher directory differs from `<device>:/OPL` | Resolve the boot transport, then probe that device's `/OPL` and root. No other-device hunt on a known BDM boot. |
| Custom Settings Path | On ordinary initial-master misses, or the mixed APA/BDM path, read the boot home's `config.path`, prepare its transport, and read all config sets from the target. A stale redirect falls back to discovery. |
| APA boot with GUI/HDL launch | Classify APA before recovery and resolve the existing PFS data home. Recovery retains the existing HDD ownership chain. |
| Settings beside launcher, including globals | The first read succeeds; no recovery. |
| Master exists but `conf_game.cfg` is absent | Keep global defaults. Ordinary launches do not recover; mixed APA/BDM launches use their normal redirect/ATA/PFS selection regardless of whether the globals file exists. |
| No configs on a known local boot | Same-device probes or the APA chain only. |
| Unknown/deferred boot, master missing | Existing broad recovery can load USB with a 1500 ms mount budget, then probe MMCE. Hardware timing remains unmeasured. |

`restoreRecoverySaveHome()` calls `configSetMove()` and may probe MC directories;
neither it nor `configSetMove()` writes settings. For non-MC recovery, the final
save home can be moved back to the boot directory after the config was read.
Consequently, the final home alone does not prove which directory supplied the
loaded values. A populated `CONFIG_GAME` alone also does not prove that those
values are the intended ones.

## Diagnostic build

Build `make clean` followed by `make OPLDIAG=1 release`. `__DEBUG` is unnecessary.
At the end of `miniInit`, the diagnostic displays:

- resolved `gBootDir`, home before the first read, and final `configGetHomePath()`;
- initial and final read masks (`CONFIG_OPL=0x01`, `CONFIG_GAME=0x10`);
- whether `configGetByType(CONFIG_GAME)->head` is non-null;
- elapsed configuration-read/recovery time, excluding the display itself and the
  earlier module loading/boot-directory resolution.

The diagnostic initializes only the renderer and built-in font, holds the screen
for eight seconds, and releases both before launch. Normal builds contain neither
the display nor the hold. Use normal pinned builds for launch timing and gameplay
comparisons: the diagnostic itself changes timing and initializes the GS.

The diagnostic-only baseline is commit `3e90d18f`; its functional config loading is
unchanged from base `ae1f26c5`. Compare it with the fixed revision on the same setup.
If the baseline already loads the intended globals, investigate `sbPrepare` and
the individual apply paths instead of declaring settings-home recovery causal.

## Hardware gate

Use **run-pinned nightly.link** downloads and check each archive's
`BUILD-MANIFEST.txt` against the intended source revision. Use PS2DEVPINNED for
behavior/timing and PS2DEVPINNED-DIAG for the diagnostic screen.

For each row, save the option as Global, launch the same game through the GUI and
the argv autolaunch handoff, and compare actual behavior:

| Check | Device | Status |
| --- | --- | --- |
| GSM enabled with a non-NTSC mode | APA HDD | Pending hardware |
| Cheats enabled | APA HDD | Pending hardware |
| PADEMU enabled | USB | Pending hardware |
| OSD language override | USB | Pending hardware |
| Global option with Custom Settings Path | HDD/USB | Pending hardware |
| APA/PFS ELF with `bdm`, ATA-root settings, with and without a different PFS master | ATA | Pending hardware |
| Same options set to Per Game | HDD/USB | Pending hardware |
| No `conf_game.cfg` anywhere; defaults and launch timing | HDD/USB | Pending hardware |

Cover a launcher outside the settings home, settings on the game device, and both
APA/HDL and mixed APA/BDM boot. Include an HDD game with a BDM-hosted custom home to exercise semaphore
initialization, and measure unknown-boot recovery separately. No broad-scan flag
has been introduced without timing evidence. Measure the mixed-layout ATA wait
on hardware too; it reuses the former BDM fallback's 5000 ms readiness budget.

Docker compilation and a PCSX2 GUI smoke test do not validate the real argv
handoff, GSM output, cheats or controller behavior. No unit-test scaffolding is
part of this change.
