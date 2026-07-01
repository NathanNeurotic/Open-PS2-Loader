# Neutrino Core (External Loader)

This fork can hand a game off to an **external [Neutrino](https://github.com/rickgaiser/neutrino) ELF**
instead of OPL's built-in EE core, on a **per-game** basis. This is useful for titles that
boot better under Neutrino, or for users who prefer Neutrino's loader and its launch flags.

> The core selector and the launch-args fields described here are specific to this fork.

## 1. Install Neutrino

Neutrino is **not bundled** with OPL — you supply it. Place the ELF on a memory card at one
of these paths (OPL checks them in order):

| Priority | Path |
|---|---|
| 1 | `mc0:NEUTRINO/neutrino.elf` |
| 2 | `mc1:NEUTRINO/neutrino.elf` |

If neither exists when you launch a game set to the Neutrino core, OPL shows a warning and
falls back to the `<OPL>` core for that launch.

You can also point OPL at a **custom location** via **Settings → General Settings → Neutrino
ELF Path**. When that field is set and the file exists it takes **priority** over the table
above; leave it blank to use the auto-detection (which also checks a few lowercase /
`NEUTRINO.ELF` spelling variants on `mc0:`/`mc1:`). For a path longer than the on-screen
31-character editor, set `neutrino_path` in `settings_riptopl.cfg` directly.

> **Network boot is the exception:** the UDPFS feature (§4) ships its **own bundled
> Neutrino** (a ready-to-use `neutrino/` folder inside the release's installable package, pre-populated with the
> UDPFS config). The per-game Neutrino use described in this section still needs you to supply
> `neutrino.elf` at the paths above.

## 2. Pick the core per game

1. Highlight a game and open **Game Settings → Compatibility Settings**.
2. Set **Loader Core** to one of:
   - **`<OPL>`** — OPL's built-in core (default).
   - **`Neutrino`** — chain to the external `neutrino.elf`.
3. Save. The choice is stored per title (`$CoreLoader` in the game's `.cfg`).

### Where Neutrino works

| Source | Neutrino? |
|---|---|
| USB / iLink / MX4SIO / internal ATA (BDM) | ✅ |
| Internal HDD (APA → HDL) | ✅ |
| MMCE | ✅ |
| UDPFS (network boot — Files or Image) | ✅ **required** — no OPL core, Neutrino only (see §4) |
| SMB / ETH | ❌ (falls back to `<OPL>`) |
| USB Extreme split images (`.ul`) | ❌ (falls back to `<OPL>`) |
| Compressed ISO (`.zso`) | ❌ (falls back to `<OPL>`) |

Unsupported cases fall back to the `<OPL>` core automatically with an on-screen warning.

> **PS1 games are a separate path.** PlayStation 1 titles (`*.VCD`, shown via the **L3 "VCD"
> per-device view**) always boot through **POPSTARTER.ELF** — never OPL's core and never Neutrino
> — so the per-game Loader Core selector is locked/inert for them. See **[VCD.md](VCD.md)**.

## 3. Launch arguments

OPL always builds the **mandatory** Neutrino arguments for you from the game and its
settings:

| Auto argument | When |
|---|---|
| `-bsd=<usb\|ilink\|mx4sio\|ata\|mmce\|udpfs\|udpfsbd>` | always (the storage backend) |
| `-bsdfs=hdl` | internal HDD (APA) only |
| `-dvd=<path>` / `-dvd=hdl:<partition>` | always (the game image/partition) |
| `-gc=<modes>` | only if the game has OPL compatibility modes set |
| `-dbc` | only if **Debug Colors** is enabled |
| `-logo` | only if **PS2 Logo** is enabled |
| `-gsm=<mode>` | only if a per-game **Neutrino Video** mode is set (Compatibility screen) |

On top of those, you can pass **extra Neutrino flags** (e.g. media-type or video tweaks)
in two places. Both are **appended after** the auto-built arguments; **global first, then
per-game**, so a game can extend the global set.

### Global default args — applies to every Neutrino launch

**Settings → General Settings → Neutrino Launch Args** (config key `neutrino_args` in
`settings_riptopl.cfg`).

### Per-game args — applies to one title

**Game Settings → Compatibility Settings → Neutrino Launch Args** (config key
`$NeutrinoArgs` in the game's `.cfg`).

Arguments are space-separated, e.g.:

```
-mt=dvd -gsm=1
```

> **Editor length:** OPL's in-app text fields hold up to 31 characters (the same limit as
> Alt-Startup / Game-ID). If you need a longer argument string, edit the value directly in
> the config file — OPL reads and forwards the full string at launch even though the on-screen
> editor caps the visible length.

For the full list of flags Neutrino accepts, see the
[Neutrino documentation](https://github.com/rickgaiser/neutrino).

## 4. Network boot — the Network Protocol selector

RiptOPL streams games from a PC over the LAN, chosen with a single **Device Settings → Network
Protocol** selector with just **three** choices — **Off / SMB / UDPFS**. **UDPFS** is the one modern
network-boot protocol (Rick Gaiser's **UDPRDMA** transport); it appears in OPL as its own games list —
with covers and per-game settings — just like a local drive, and boots via the external Neutrino core.
**SMB** is the exception: it's a mounted SMBv1 file share served by OPL's **own** core (no Neutrino),
and it keeps its own address / port / share / credentials fields.

| Choice | Wire protocol | On the PS2 | Core | PC server |
|---|---|---|---|---|
| **Off** | — | no network device (default) | — | — |
| **SMB** | SMBv1 | a mounted file share | OPL's *own* core (not Neutrino) | Samba / `smbserver_opl.py` |
| **UDPFS** | UDPRDMA | a games source served over UDP (see **UDPFS Access** below) | Neutrino only | `udpfsd` / `udpfs_server.py` |

Because the PS2 has a **single** network adapter, only ONE of these is active per session — the
selector is exclusive *by construction* (the old separate ETH start-mode + "Network Boot" toggle +
"Net Boot Protocol" picker, and their live interlock, are all gone). Local devices (USB / internal
HDD / MMCE) are independent and browse alongside whichever network protocol you pick.

> **UDPBD is retired.** The old SUDPBDv2 `udpbd.irx` protocol is gone from the UI — Rick's `udpfs_bd`
> is its intended successor (the commented `#file = "udpfs_bd.irx"` line in stock `bsd-udpbd.toml`).
> Any existing config that resolved to UDPBD **migrates to UDPFS Access = Image on load**; those users
> just switch their PC server from `udpbd-server` to `udpfsd -b` (or `udpfs_server.py -b`). There is no
> longer any standalone UDPBD option anywhere.

### UDPFS Access — Files vs Image

When **UDPFS** is selected, a second sub-setting **"UDPFS Access"** appears with two values — **Files**
(default) and **Image**. They are the **same UDPFS protocol** in two shapes: Files is the `udpfs_ioman`
FILESYSTEM (`udpfs:`), Image is the `udpfs_bd` BLOCK device (`massN:`).

| | **Files** (default) | **Image** |
|---|---|---|
| IOP driver | `udpfs_ioman.irx` → `udpfs:` (filesystem) | `udpfs_bd.irx` → `massN:` (block device) |
| PC serves | a **folder of loose ISOs** | a **FAT/exFAT disk image** |
| Server command | `udpfsd -d <dir>` / `udpfs_server.py -d <dir>` | `udpfsd -b <image>` / `udpfs_server.py -b <image>` |
| Launch | by name (`-dvd=udpfs:<name>`, stock `-bsd=udpfs`) — no `massN:`, no fragment list | mounted like a USB drive (`massN:`, fragment-list launch) |
| Add a game | drop a file in the folder | mount the image, copy, unmount |
| Compression | transparent `.zso`/`.cso`/`.chd` | — (raw sectors only) |

Because both backends bind the same UDPRDMA port and the IOP ministack can load only one per boot, you
**can't run both at once** — Files vs Image is a **config-time choice** (defaulting to Files). It's a
single-adapter, single-transport decision, so **switching Files ↔ Image needs an OPL restart to take
effect** (OPL shows the usual restart-to-apply notice).

- **Files** launches with the **stock** `-bsd=udpfs`, which loads Neutrino's shipped `bsd-udpfs.toml`
  (the FHI filesystem driver, `udpfs_ioman` / `udpfs_fhi`). Neutrino opens the game by name
  (`-dvd=udpfs:<name>`) — no `massN:` block device, no fragment list. On the nightly Neutrino the
  `-bsd` is auto-detected.
- **Image** launches with **`-bsd=udpfsbd`**, a **RiptOPL-private** token: Neutrino ships `udpfs_bd.irx`
  but no stock `-bsd` for it, so RiptOPL auto-places `config/bsd-udpfsbd.toml` into the bundled Neutrino
  folder. The private name is deliberate — it avoids colliding with stock's `bsd-udpfs.toml` (a
  *different* driver), so the block config and the stock filesystem config coexist on one install.

### Requirements

- A **PC-side UDPFS server** on the same LAN, matching the UDPFS Access mode you chose. Good options,
  in order: **[pcm720/udpfsd](https://github.com/pcm720/udpfsd)** — a single prebuilt Go binary (no
  Python) that serves **both** `-d` (Files) and `-b` (Image); the bundled **`udpfs_server.py`** (Python
  3, `-d`/`-b`); or the fork's **[NathanNeurotic/PS2-Servers](https://github.com/NathanNeurotic/PS2-Servers)**
  one-stop bundle (SMBv1 + UDPFS servers). The old `udpbd-server` (SUDPBDv2) does **not** work with
  UDPFS. For the **Image** mode the served FAT/exFAT image is laid out with the usual OPL folders
  (`CD`, `DVD`, `ART`, `CFG`, …); for **Files** it's just a flat folder of loose ISOs.
- A **static** PS2 IP. UDPFS has no DHCP client — it reuses the address from **Settings → Network
  Config**, so set a static IP there. OPL warns you if DHCP is on at the moment you select UDPFS. SMB's
  server / port / share / credentials fields hide automatically when UDPFS is selected.
- UDPFS is Neutrino-only (no `<OPL>` core fallback); if `neutrino.elf` is missing, OPL warns and
  returns to the menu.

> **At launch, Neutrino reads its own IP from a toml, not from OPL.** When a game boots, control hands
> to the external Neutrino, which reads the toml for the active mode — **Files** uses the stock
> `config/bsd-udpfs.toml`; **Image** uses the bundled `config/bsd-udpfsbd.toml`. Both hardcode
> `ip=192.168.1.10`. If your PS2's static IP differs, **edit the `ip=` line in whichever toml is
> active** (under the bundled `neutrino/config/`) to match — otherwise games list fine in OPL but fail
> to boot.

> **Hardware note:** the UDPRDMA path (both Files and Image) is validated on emulator only so far —
> real-PS2 confirmation is pending.

## 5. Core-aware per-game settings

The per-game settings adapt to the **Loader Core** chosen for that title, so you only see
options the selected core actually honors (Neutrino ignores most of OPL's embedded-core
features — see the mapping below).

When a game's core is **Neutrino**:
- **Compatibility screen:** the **Neutrino Launch Args** field is editable, and a **Neutrino
  Video** picker (Off / 240p / 480p / 1080i) appears beside it — it maps to Neutrino's `-gsm`
  (`fp1` / `fp2` / `1080ix1`; Off emits nothing) and is the Neutrino-side stand-in for the hidden
  OPL GSM panel. The picker is the *default*: a manual `-gsm` typed into **Launch Args** takes
  precedence (OPL emits only one `-gsm`, since Neutrino aborts on a duplicate/malformed value).
  OPL compat **mode 4 (Skip Videos)** and **mode 6 (Disable IGR)** are greyed —
  they're OPL ee-core features with **no Neutrino equivalent** (Neutrino has no in-game reset, and
  no PSS/BIK video-skip), so OPL never forwards them. **DL Defaults** is greyed too (it pulls
  OPL-bitmask data that doesn't map to `-gc`). Modes 1/2/3/5 *do* map to `-gc`, and a Neutrino-only
  **mode 7** (greyed under the OPL core — the inverse of 4/6) maps to `-gc=7` (fix games that overrun
  an IOP buffer).
- **GSM, Cheats, PADEMU, OSD Language** panels are OPL-core-only; opening one shows
  *"not used with the Neutrino core"* instead of editing dead options (use the Neutrino Video
  picker above for video forcing).
- **VMC** and **Compatibility** stay available — both are honored under Neutrino (VMC via
  `-mc0`/`-mc1` on block devices).
- **UDPFS games** (both Files and Image) have no OPL core backend, so the **Loader Core selector is
  locked to Neutrino** for them (they always launch via Neutrino regardless).

When a game's core is **`<OPL>`** the screen is unchanged from classic OPL, except the Neutrino
Args field and Neutrino Video picker are greyed (never read on the OPL path).

> What Neutrino honors per game: the storage backend + image (`-bsd`/`-dvd`, automatic),
> compat subset (`-gc`), VMC (`-mc0`/`-mc1`), `-logo`, and the free-text **Neutrino Launch
> Args** (the catch-all for everything else, with `$`-disable). Cheats, GSM hacks, IGR/IGS,
> PADEMU and OSD-language are OPL-embedded-core features with no Neutrino equivalent.
