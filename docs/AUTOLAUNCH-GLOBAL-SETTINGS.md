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

The reporter later confirmed that both `conf_opl.cfg` and `conf_game.cfg` are
at the ATA root, with no Custom Settings Path or config on another device. They
also reported that current official OPL launches from APA to exFAT through both
Auto Loading and the GUI. RiptOPL's extra PFS mount is confirmed in source;
whether it causes the black screen on this console remains unverified.

## Change and scope

`miniInit()` detects an APA/PFS-hosted ELF with BDM argv. For that combination it
starts at the normal memory-card config home, then uses `checkLoadConfigBDM()`
if the master config is absent, matching official OPL's ordering. It skips
`resolveBootDirToMass()` so loading settings does not mount PFS before exFAT is
available as `massN:`. Other auto-launch modes retain the boot-home resolver and
`tryAlternateDevice()`. BDM semaphore initialization still runs for every mode.

For a normal GUI boot from APA, the existing PFS settings home remains first
choice. If it has no master config, GUI recovery must successfully unmount `pfs0:`
before probing only the ATA BDM device. A failed unmount leaves APA ownership
intact; a failed ATA config probe remounts the original PFS home. A successful
ATA probe records BDM as the settings owner so a later Save Settings does not
remount PFS immediately before launching an exFAT game. The handoff keeps the
APA/PFS modules resident and does not force-close PFS descriptors. HDD and MMCE
auto-launches keep their existing PFS recovery path. A missing optional network
config file does not restart APA recovery after BDM ownership is selected.

The shared GSM, cheats, PADEMU, pad-macro and OSD-language application code and
the on-disk meaning of Global are unchanged. Per-game CFG files still come from
the game device. An absent `conf_game.cfg` by itself does **not** trigger recovery.
Recovery itself does not write config files or create APA partitions.

## Source review (not runtime tests)

| Layout/state | Path through the existing helpers |
| --- | --- |
| APA/PFS ELF, BDM/ATA Auto Loading, settings at ATA root | Read the normal MC home, then BDM if the MC master is absent. No PFS settings mount. A different MC master takes precedence, as in official OPL. |
| APA/PFS ELF, GUI launch of an ATA/exFAT game, settings at ATA root | Try APA first. On a master-config miss, unmount `pfs0:` before ATA-only BDM discovery; retain BDM ownership for later saves. Remount PFS if no ATA master loads. |
| Launcher `mc0:/APPS`, settings `mc0:/OPL` | Initial read misses; same-card recovery reads `/OPL`, including `CONFIG_GAME`. MC1 uses the same slot-preserving rule. |
| BDM launcher directory differs from `<device>:/OPL` | Resolve the boot transport, then probe that device's `/OPL` and root. No other-device hunt on a known BDM boot. |
| Custom Settings Path | Ordinary initial-master misses still read the boot home's `config.path`. APA-hosted BDM Auto Loading follows official MC/BDM ordering and cannot read a redirect stored inside an unmounted PFS home. |
| APA boot with GUI or HDL launch | Classify APA before recovery and resolve the existing PFS data home; only a GUI master-config miss can transfer settings ownership to ATA BDM. |
| Settings beside launcher, including globals | Ordinary boot-home reads succeed without recovery; APA-hosted BDM Auto Loading follows the MC/BDM order above. |
| Master exists but `conf_game.cfg` is absent | Keep global defaults; the missing globals file alone does not trigger recovery. |
| No configs on a known local boot | Same-device probes or the APA chain only. |
| Unknown/deferred boot, master missing | Existing broad recovery can load USB with a 1500 ms mount budget, then probe MMCE. Hardware timing remains unmeasured. |

`restoreRecoverySaveHome()` calls `configSetMove()` and may probe MC directories;
neither it nor `configSetMove()` writes settings. For ordinary non-MC recovery,
the final save home can be moved back to the boot directory after the config was
read. The APA GUI to ATA-BDM handoff keeps its separately recorded BDM owner.
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
| APA/PFS ELF GUI boot, ATA/exFAT game, then Save Settings and Remember Last Played | ATA | Pending hardware |
| Same options set to Per Game | HDD/USB | Pending hardware |
| No `conf_game.cfg` anywhere; defaults and launch timing | HDD/USB | Pending hardware |

Cover a launcher outside the settings home, settings on the game device, and both
APA/HDL and mixed APA/BDM boot. Include an HDD game with a BDM-hosted custom home to exercise semaphore
initialization, and measure unknown-boot recovery separately. No broad-scan flag
has been introduced without timing evidence. Measure the mixed-layout ATA wait
on hardware too; the BDM fallback retains its 5000 ms readiness budget.

Docker compilation and the source-level APA handoff regression do not validate
the real argv handoff, GSM output, cheats or controller behavior.
