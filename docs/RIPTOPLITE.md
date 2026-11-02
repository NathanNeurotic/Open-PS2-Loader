# RiptOPLite: one loader per game device

`rolling-lite` carries one RiptOPL loader per game device, for consoles that only play from one.
Each is the Korium edition with that device's drivers alone, so the ELF is smaller and has less to
load. Every build is Korium (built-in Korium Komblete theme); the RetroAchievements builds are Korium
with RA on. These are development builds and have not been tested on hardware before publication.

| Device | Korium | RetroAchievements | Game drivers it carries |
| --- | --- | --- | --- |
| USB | `RIPTOPLITE-USB.ELF` | `RIPTOPLITE-RA-USB-<version>.zip` | BDM, USB mass storage |
| MX4SIO | `RIPTOPLITE-MX4SIO.ELF` | `RIPTOPLITE-RA-MX4SIO-<version>.zip` | BDM, MX4SIO |
| iLink | `RIPTOPLITE-ILINK.ELF` | `RIPTOPLITE-RA-ILINK-<version>.zip` | BDM, iLinkman, IEEE1394 |
| HDD | `RIPTOPLITE-HDD.ELF` | `RIPTOPLITE-RA-HDD-<version>.zip` | APA/PFS, exFAT on the internal drive, HD Pro, DESR DVR |
| SMB | `RIPTOPLITE-SMB.ELF` | `RIPTOPLITE-RA-SMB-<version>.zip` | smbman, smb2man, NBNS, in-game SMB |
| UDPBD | `RIPTOPLITE-UDPBD.ELF` | `RIPTOPLITE-RA-UDPBD-<version>.zip` | BDM, SMAP UDPBD |
| UDPFS | `RIPTOPLITE-UDPFS.ELF` | `RIPTOPLITE-RA-UDPFS-<version>.zip` | UDPFS Files and IMG |
| MMCE | `RIPTOPLITE-MMCE.ELF` | `RIPTOPLITE-RA-MMCE-<version>.zip` | MMCE games page |

HTTP and PC Card CF have no lite build.

## What every lite build keeps

- **MMCE modules.** Game ID and the IGR boot-card switch use them whatever the game device.
- **The network stack.** netman, SMAP, ps2ip, the HTTP client and the NBD server.
- **BDM core and the USB block driver.** A lite loader started from a USB stick can still read its
  settings there.
- **RetroAchievements builds also keep** everything RA uses on any device: the in-game SMAP and
  SMSTCPIP pair that carries telemetry, the RA modules (raudp, rapops, the IGR overlay), the Disc
  page, and the SMB share drivers (smbman, smb2man, NBNS), which the achievements page reads
  `ART/CADUCEUS.KEY` and badges from.

## Why the RA builds are ZIPs

RetroAchievements needs files outside the loader: ORBIT's Neutrino RA runtime replaces upstream
Neutrino for every RA launch (see [Neutrino in the RA edition](RETROACHIEVEMENTS.md#neutrino-in-the-ra-edition)).
Each `RIPTOPLITE-RA-<DEVICE>-<version>.zip` therefore carries the ELF, `neutrino/` (copied from the
verified Korium RetroAchievements kit of the same revision), the xeRAbora shortcut, the licences, the
build record and a README. The Korium lite builds need nothing the standard Korium kit does not
already install, so they are bare ELFs that replace `RIPTOPL.ELF`.

## Settings

The game page, start mode and protocol of the one device are fixed by the build, and their rows are
not shown on Game Sources or Network. Every other setting works as in the full loader.

The settings file is shared with the full loader. A lite loader reads the full loader's device
settings when it starts and writes them back unchanged when it saves, so switching between a lite
and the full loader never changes which devices the full one uses.

A lite loader cannot read settings from a device it has no driver for. Keep the settings on its own
device, a memory card or a USB stick.

## How it is built

`make RIPTOPLITE=<device>` (add `RETROACHIEVEMENTS=1` for the RA build), from a clean tree:
`usb`, `mx4sio`, `ilink`, `hdd`, `smb`, `udpbd`, `udpfs` or `mmce`. The Makefile's `LITE_KEEP_<device>`
lists say what each device keeps; every other device's IRX is left out of the ELF, and its symbols
become zero-sized stubs that `sysLoadModuleBuffer` refuses. `make RIPTOPLITE=<device> lite-dropped`
prints what a build leaves out. `include/riptlite.h` turns the other devices' loaders off at compile
time, and `src/riptlite.c` holds their settings off whatever the settings file says.

[`lite-release.yml`](../.github/workflows/lite-release.yml) runs after each published
RetroAchievements release. It builds all sixteen loaders from that release's revision with the same
frozen Korium theme delta, checks in each ELF that no left-out module carries real data and that the
device's own drivers are present, packages them with `.github/scripts/package_lite_release.py` and
publishes `rolling-lite` with `.github/scripts/publish_lite_release.py`. It refuses a revision that
`rolling` or `rolling-ra` has moved on from, and never marks the release GitHub's Latest.
`.github/scripts/test_riptoplite.py` checks the device lists, the code gates and the channel's contents.

The same channel exists in [RiptOPL](https://github.com/NathanNeurotic/RiptOPL/blob/rebuild/main/docs/RIPTOPLITE.md).
