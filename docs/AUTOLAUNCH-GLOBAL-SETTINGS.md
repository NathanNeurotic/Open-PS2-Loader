# Auto Loading global settings (#545)

Issue [#545](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/545) tracks
[CosmicScale's upstream report](https://github.com/ps2homebrew/Open-PS2-Loader/issues/1768)
on an SCPH-50001: options saved as **Global** did not apply when a game was started by Auto
Loading instead of the menu. The reporter's setup is PSBBN Definitive. Each game partition
starts OPL with:

```text
path = hdd0:__system:pfs:/launcher/OPNPS2LD.ELF
arg = Fantavision.iso
arg = SCUS_971.05
arg = DVD
arg = bdm
```

`conf_opl.cfg` and `conf_game.cfg` sit at the root of the exFAT volume, next to the games.

## The disk layout

PSBBN's installer builds an **"APA-Jail"** disk. Sector 0 is a valid, checksummed APA header
**and** a DOS MBR. The MBR lists the APA area, a small ext2 recovery partition, and the exFAT
volume that holds the games (partition 3).

Official OPL's probe checks the MBR signature first, so it never loads APA on such a disk. Its
settings, games, `CFG/` and `ART/` all live on the exFAT root. The APA side holds only
launchers such as `__system/launcher/OPNPS2LD.ELF`.

## What was wrong in RiptOPL

1. **Every BDM Auto Loading launch crashed.** `autoLaunchBDMGame` calls
   `bdmLaunchGame(NULL, ...)`, and the launch read `itemList->mode` for folder browsing.
   `mode` is at offset 0, so this loaded from virtual address 0, which the EE's default TLB
   leaves unmapped. The result on hardware is a TLB-miss exception and a black screen, on USB
   as well as HDD. The bug came from folder browsing (master `7b05b8a2`, 2026-07-14). It is the
   black screen reported on #545.
2. **The settings home was wrong for this disk.** RiptOPL maps every APA launch to its APA
   data home (`+OPL` or `__common/OPL`). On a hybrid disk nothing of the user's is there, so
   the menu opened with defaults and the exFAT games stayed hidden.
3. **Official's master file was never read.** RiptOPL's master settings are private
   (`settings_riptopl.cfg`, legacy `conf_riptopl.cfg`). Even when the right folder was found,
   official's `conf_opl.cfg` in it was invisible.
4. **Two ways to lose loaded settings.**
   - A missing `conf_network.cfg` re-ran the whole settings search. When that search ended in a
     miss it cleared every loaded set, including the global game settings.
   - Auto Loading also had its own exFAT probe (#642), so it did not always use the same
     settings as the menu.

## Behaviour now

The menu and Auto Loading run one discovery path. `miniInit` calls `resolveBootDirToMass` and
`tryAlternateDevice` exactly as `_loadConfig` does, with no Auto Loading-only branch.

- **APA + exFAT hybrid.** `hddIsApaMbrHybrid` reads sectors 0-1 through `xhdd0:` without
  loading `ps2hdd`. It requires a valid APA header, `0x55AA`, and a FAT/exFAT MBR entry that
  starts beyond the APA reserved area (`0x40000`). A residual `0x55AA` on a plain APA disk does
  not count. The exFAT root comes from the existing typed resolver (`ata0:/` → `massN:/`,
  5 s budget, no ELF name). Like official OPL, the settings then always live on the exFAT root:
  1. RiptOPL settings (or a Custom Settings Path redirect) on the exFAT root are used as they are.
     PFS is never mounted in this case.
  2. A Custom Settings Path saved in the APA data home is an explicit instruction, so that APA home
     is kept and the redirect decides.
  3. Otherwise the exFAT root is the home. Files an older build saved to the APA data home are
     **carried over**, read-only, wherever the exFAT root lacks them: RiptOPL's master settings (ahead
     of official's seed) and `conf_game`/`conf_last`/`conf_apps`/`conf_network.cfg`. Official's files
     on exFAT always win. The first save writes everything to exFAT. With nothing to carry over,
     official's `conf_opl.cfg` seeds the first boot, or defaults apply.

     To look for those files the APA data home is mounted, but nothing is created in it: no
     `__common/OPL/` folder on a disk that never had one. When nothing is carried over it is
     unmounted again, so the menu does not announce "`__common` partition mounted" for a partition
     it is not using. Carried-over settings are announced as loaded from the HDD, and official's
     seed as "Official OPL settings loaded from `massN:`".

  An exFAT home is an ordinary ATA-BDM boot from then on. The boot-device reconcile enables
  the ATA transport, and saves take the BDM path. Official OPL starts its BDM page Auto whenever it
  finds its config on a BDM device; RiptOPL does the same on a hybrid's exFAT home while the master
  is not its own saved file there (defaults, official's seed, or carried-over APA settings), so the
  exFAT games appear with no setup. Once RiptOPL has saved on exFAT, the saved BDM start mode stands.
- **Official `conf_opl.cfg` is a read-only seed.** If a folder holds neither RiptOPL name,
  `configRead` reads official's file from that folder.
  - The set keeps RiptOPL's filename, so the first save writes `settings_riptopl.cfg` and
    official's file is never written.
  - Official has five BDM slots, so `default_device` 5/6/7 maps to ETH/HDD/APP. Every other
    official master key has the same name and meaning, and the video-mode and GSM mode indices
    are identical.
  - A seed never picks the save home. In particular, a memory-card launch does not start
    saving into official's `mc?:/OPL`.
- **`conf_game.cfg`** already shares official's name. With the home fixed, Auto Loading applies
  the same Global GSM, cheats, PADEMU and OSD options as the menu.
- **A missing `conf_network.cfg`** now just means network defaults. Discovery is not re-run.
- **A refused Auto Loading launch returns to the menu instead of hanging.** Examples are a
  missing ISO, a fragmented image or no mass device.
  - `guiMsgBox` answers "back" before the GUI exists, as `guiWarning` already did.
  - Both entry points tear down the autolaunch session, and `configFree(NULL)` is safe.
  - The menu then starts a fresh IO worker. `ioInit` waits for the old one to leave and clears
    the queue block.
  - The `mass0:` wait is bounded to about 12 s.
- **Cheats prompt (#265).** "Continue without cheats" had cancelled the launch, because the code
  compared `guiMsgBox`'s result with 2 while accept returns 1.
- **Missing vs broken cheat files.** Only a cheat file that is not there at all counts as "no
  cheats", which is silent when cheats are on for all games. A `cht.tar` member that is empty or
  over 1 MB, or a loose `.cht` the device refuses (access denied, or held by another session), is
  reported as failing to load. A generic I/O error still counts as missing, because an SMB share
  answers a missing file with one.

Per-game CFG files still come from the game device. An absent `conf_game.cfg` never triggers
discovery by itself. Nothing here creates, formats or edits APA partitions, and on a hybrid
nothing creates folders in them either. The hybrid probe only reads, and the exFAT side is
written only when the user saves settings.

## Source review (not runtime tests)

| Layout/state | Result |
| --- | --- |
| PSBBN hybrid, official configs on exFAT, nothing from RiptOPL | Menu and Auto Loading home on `massN:/`, seeded from `conf_opl.cfg` ("Official OPL settings loaded from mass0:"); `conf_game.cfg` globals apply; exFAT games visible (`usb_mode=2`, `enable_bdm_hdd=1`). `__common` is looked at, left without a new `OPL` folder, and unmounted. First save writes `settings_riptopl.cfg` there. |
| PSBBN hybrid after a RiptOPL save on exFAT | RiptOPL's file wins; PFS is not mounted for settings. |
| Hybrid with RiptOPL settings already on `__common/OPL` or `+OPL` | Home moves to `massN:/`; those settings are carried over read-only and the BDM page starts Auto; the first save writes them to exFAT. |
| Hybrid with a Custom Settings Path file in the APA home | That APA home is kept and the redirect decides. |
| PSBBN hybrid, no settings anywhere | Home `massN:/`, defaults, BDM page Auto and HDD (exFAT) on, so the exFAT games show; no "Config loaded" notice, no new `__common/OPL` folder, `__common` unmounted; the first save writes to exFAT. |
| Hybrid whose exFAT volume never mounts within 5 s | Falls back to the APA path. |
| Hybrid whose drive is not ready until the settings retry | Same home as when the drive is ready at boot: the retry runs the same hybrid check. |
| Plain APA disk | Unchanged; a pure-APA official user's `+OPL/conf_opl.cfg` now seeds a first boot. |
| Launcher `mc0:/APPS`, official settings in `mc0:/OPL` | Same-card recovery reads the seed; the save home stays the boot directory. |
| USB/BDM root with official `conf_opl.cfg` | Read as the seed; RiptOPL saves its own file there. |
| Master found, `conf_network.cfg` missing | Network defaults; loaded sets are kept. |

## Diagnostic build

Build `make clean` followed by `make OPLDIAG=1 release`. `__DEBUG` is unnecessary. At the end
of `miniInit`, the diagnostic shows the following for eight seconds, then continues the launch:

- the resolved `gBootDir`, the home before the first read, and the final `configGetHomePath()`;
- why that home was chosen (for example `hybrid: exFAT, APA settings carried over`, or
  `APA: hybrid, but exFAT did not mount in time`);
- the initial and final read masks (`CONFIG_OPL=0x01`, `CONFIG_GAME=0x10`);
- whether `CONFIG_GAME` is populated;
- the time spent reading settings.

A menu boot of the same build shows the chosen home, the reason, the BDM start mode and the
HDD (exFAT) switch for about five seconds before the menu appears.

## Hardware gate

Use **run-pinned nightly.link** downloads and check each archive's `BUILD-MANIFEST.txt`
against the intended source revision.

| Check | Setup | Status |
| --- | --- | --- |
| Auto Loading starts the game (no black screen) | PSBBN hybrid; also a USB autolaunch | Pending hardware |
| Global GSM and cheats set in official OPL apply on Auto Loading | PSBBN hybrid, no RiptOPL settings | Pending hardware |
| Menu from APA shows exFAT games on first boot | PSBBN hybrid | Pending hardware |
| Save in the menu, then Auto Loading uses the saved globals | PSBBN hybrid | Pending hardware |
| Cheats enabled, no `.cht`: "continue" launches from the menu | Any | Pending hardware |
| Missing ISO on Auto Loading returns to the menu | Any BDM | Pending hardware |
| Plain APA and MC launchers unchanged | APA HDD, MC | Pending hardware |

A tester who pressed Save in RiptOPL's menu on a hybrid disk with an older build has
`settings_riptopl.cfg` in `__common/OPL`. Those settings are now carried over to the exFAT home,
so nothing needs deleting; remove the file only to test a true first run.
