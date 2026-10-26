# BDM-UDPFS Assault

PS2 homebrew project that adds UDPFS support to the BDM Assault USB driver used by POPStarter (and, with a separate build, by the Ember emulator), so game files can be read from a UDPFS server as if it were a USB device.

Original BDM Assault description: *PS2 homebrew project to bring support for EXFAT USB devices to closed source old homebrew which loads external USB Drivers.*

## What it does

`bdm_udp_fs_assault.irx` is a drop-in replacement for `bdm_assault.irx`. It keeps everything BDM Assault does (USB mass storage through BDM + FatFs, exFAT/FAT32, read and write) and adds a read-only network fallback:

- POPStarter opens a `POPS/` or `POPS0/` ... `POPS9/` `*.VCD` file, or (Ember build) Ember opens a `EMBER/games/<folder>/*.cue` or `*.bin` file: the USB drive is tried first.
- If the file is not on the USB drive, the same path is requested from a UDPFS server over Ethernet and read with BREAD requests.
- If neither has the file, the open fails exactly as with the original driver.
- Any other file, and any write, never touches the network.

The `.VCD` extension must be uppercase (POPStarter is case-sensitive on this), on the USB drive and on the server.

Servers it has been tested with: [udpfsd](https://github.com/pcm720/udpfsd) (Go) and the original Python server (`udpfs_server.py`).

## Usage

Place the IRX binaries from the releases section of this repository into the path that POPStarter looks for.

### POPStarter

- `bdm_udp_fs_assault.irx` must be pasted into `mc?:/POPSTARTER/usbd.irx`
- `usbd_bd_assault.irx` (the USB mass storage driver, from the [BDM Assault releases](https://github.com/israpps/BDMAssault/releases)) must be pasted into `mc?:/POPSTARTER/usbhdfsd.irx`

### Ember

Ember has its own build, `make EMBER=1`, which produces `bdm_udp_fs_assault_ember.irx`. Ember is started by a launcher that loads the IRX modules, so the launcher is the one that loads this module (where it would load the BDM Assault driver). Because Ember never resets the IOP, nothing is carried across a reset, but the memory card is only readable if the launcher has loaded the memory card modules (`rom0:XSIO2MAN`, `rom0:XMCMAN`) before this module; otherwise the configuration is looked up on the USB drive and the default IP is used.

### What goes where

- **UDPFS server (POPStarter build):** only the `.VCD` files, in the folder POPStarter looks in, relative to the server's shared root: `/POPS/` or `/POPS0/` ... `/POPS9/` (for example `/POPS/Game Name.VCD`). The extension must be uppercase.
- **UDPFS server (Ember build, `make EMBER=1`, output `bdm_udp_fs_assault_ember.irx`; the POPStarter build never requests these files):** the `.cue` and `.bin` files of a game, one folder per game: `/EMBER/games/<folder>/<name>.cue` and `.bin` (for example `/EMBER/games/Game Dir/Game Name.cue`). Any `.cue`/`.bin` in that folder is served, so CDs with several `.bin` tracks work. The `/EMBER/` folder itself (`settings.txt`, `bios.bin`, the virtual memory cards, which Ember writes) must stay on the USB drive.
- **USB drive:** everything else POPStarter needs (`POPS_IOX.PAK` and any other file) stays on the USB drive and is read from there. No additional file is needed on the server, and this module does not read any other file from the network.

### Any other homebrew

- The module is built for POPStarter and for Ember (separate builds, see above). Other homebrew are out of scope.

## Network configuration

Both files are optional. Each one is looked up on the memory card first and on the USB drive second (the files are independent of each other). Full details in [docs/README_CONFIG.txt](docs/README_CONFIG.txt).

- `IPCONFIG.DAT`: the PS2's address, one line: `IP NETMASK [GATEWAY]`, for example `192.168.1.10 255.255.255.0 192.168.1.1`. If it is missing or invalid, the PS2 falls back to `192.168.1.10` / `255.255.255.0` (same default as UDPBD and Neutrino).
- `UDPFSCONFIG.DAT`: the server's address, one line: `192.168.1.11`. If present and in the same network as the PS2, it takes priority over the discovery and the server is contacted directly. If it is missing, or its address belongs to another network, it is ignored and the server is found with a broadcast discovery.

Where to put them (first found is used):

1. `mc0:` then `mc1:` files `/SYS-CONF/IPCONFIG.DAT` and `/SYS-CONF/UDPFSCONFIG.DAT`
2. `mass:/SYS-CONF/` on the USB drive (same for both builds; in the Ember build, `make EMBER=1`, the launcher must load the memory card modules before this module, otherwise only the USB folder is used)

In the POPStarter build the memory card is readable only before POPStarter resets the IOP, so the module reads the files in its first load and keeps them in IOP RAM across the reset; no system module is loaded for this. The Ember build loads once and has no reset, so it reads the files once at start (see [Ember](#ember)).

## Building

You need the [PS2SDK](https://github.com/ps2dev/ps2sdk). Build `libbdm` first, then the module:

```
cd libbdm && make
cd ../__bdm_udp_fs_assault && make
```

Builds (run `make clean` after changing any option: make does not see the compiler flags):

| Command | Output | Notes |
|---|---|---|
| `make` | `bdm_udp_fs_assault.irx` | POPStarter build, no log |
| `make EMBER=1` | `bdm_udp_fs_assault_ember.irx` | Ember build, no log |
| `make DEBUG=1` | `bdm_udp_fs_assault_debug.irx` | POPStarter, with the BDM/FatFs traces, the start-up timings and where the configuration came from |
| `make EMBER=1 DEBUG=1` | `bdm_udp_fs_assault_ember_debug.irx` | the same for Ember |
| `make TTY=1` (also with `EMBER=1`) | same names as the normal builds | release speed, with only the `UDPFS: ...` lines of the client (discovery, open, failed requests) |

The log of the `DEBUG` and `TTY` builds is sent over UDP tty (broadcast, port 18194): `nc -u -l 18194`. A normal build sends nothing.

## License

This project is distributed under the terms of the [LICENSE](../LICENSE) file of the repository (Academic Free License 2.0). It includes or derives from third-party works that keep their own licenses (PS2SDK, Neutrino/UDPBD/UDPFS, FatFs, udpfsd): the full list, with copyright notices and license texts, is in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) and [licenses/](licenses/).

## CREDITS

the softwares found here were taken and modified from [__PS2SDK__](https://github.com/ps2dev/ps2sdk)

- israpps: for BDM Assault, the project this one is based on
- krHACKen: for POPStarter
- ps2max32 ([Neutrino](https://github.com/ps2max32/neutrino)): UDPFS/UDPRDMA protocol and the original UDPBD network code
- PCM720 ([udpfsd](https://github.com/pcm720/udpfsd)): UDPFS server in Go, used as the reference to write the client
- everyone that collaborated to PS2SDK
