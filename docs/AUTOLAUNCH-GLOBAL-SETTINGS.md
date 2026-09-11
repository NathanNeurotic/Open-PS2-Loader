# Auto Loading global settings (#545)

Issue [#545](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/545) tracks
[CosmicScale's upstream report](https://github.com/ps2homebrew/Open-PS2-Loader/issues/1768)
on an SCPH-50001 with APA HDD games. Nathan has not reproduced it locally.
The settings-home explanation is supported by source review, not yet by a PS2 trace.

## Change and scope

`miniInit()` now resolves its boot/settings home for every launch mode and uses
`tryAlternateDevice(CONFIG_ALL)` when the first read misses `CONFIG_OPL`, matching
the GUI's recovery entry point. The three mode-specific `checkLoadConfig*` calls
are removed. Its existing BDM semaphore initialization also runs for every mode:
an APA game can have a BDM-hosted launcher or custom settings home, and the reused
transport helpers acquire that semaphore.

The shared GSM, cheats, PADEMU, pad-macro and OSD-language application code and
the on-disk meaning of Global are unchanged. Per-game CFG files still come from
the game device. An absent `conf_game.cfg` does **not** trigger recovery when the
master config loaded successfully.

## Source review (not runtime tests)

| Layout/state | Path through the existing helpers |
| --- | --- |
| Launcher `mc0:/APPS`, settings `mc0:/OPL` | Initial read misses; same-card recovery reads `/OPL`, including `CONFIG_GAME`. MC1 uses the same slot-preserving rule. |
| BDM launcher directory differs from `<device>:/OPL` | Resolve the boot transport, then probe that device's `/OPL` and root. No other-device hunt on a known BDM boot. |
| Custom Settings Path | On an initial master-config miss, read the boot home's `config.path`, prepare the target transport, and read all config sets from that target. A stale redirect falls back to the existing recovery policy. |
| APA boot | Classify APA before recovery and resolve the existing PFS data home. Recovery retains the existing HDD ownership chain. |
| Settings beside launcher, including globals | The first read succeeds; no recovery. |
| Master exists but `conf_game.cfg` is absent | Keep defaults; no extra recovery scan. This also means an existing master beside the launcher still wins over a different `config.path` target, matching the GUI's existing gate. |
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
| Same options set to Per Game | HDD/USB | Pending hardware |
| No `conf_game.cfg` anywhere; defaults and launch timing | HDD/USB | Pending hardware |

Cover a launcher outside the settings home, settings on the game device, and APA
boot. Include an HDD game with a BDM-hosted custom home to exercise semaphore
initialization, and measure unknown-boot recovery separately. No broad-scan flag
has been introduced without timing evidence.

Docker compilation and a PCSX2 GUI smoke test do not validate the real argv
handoff, GSM output, cheats or controller behavior. No unit-test scaffolding is
part of this change.
