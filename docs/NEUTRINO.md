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

> **Network boot is the exception:** the UDPBD / UDPFS feature (§4) ships its **own bundled
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
| UDPBD / UDPFS (network block device) | ✅ **required** — no OPL core, Neutrino only (see §4) |
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
| `-bsd=<usb\|ilink\|mx4sio\|ata\|mmce\|udpbd\|udpfsbd>` | always (the storage backend) |
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

RiptOPL streams games from a PC over the LAN through one of several network transports, chosen with a
single **Device Settings → Network Protocol** selector (Off / SMB / UDPFS / UDPFSBD / UDPBD). Each UDP
transport appears in OPL as its own games list — with covers and per-game settings — just like a local
drive, and (unlike SMB) boots via the external Neutrino core. **UDPBD** is the original one: Rick
Gaiser's SUDPBDv2 *block device* — to OPL it *is* just another block device (it mounts `massN:`), it
has no `<OPL>` core backend, so its games always launch via Neutrino (`-bsd=udpbd`); if `neutrino.elf`
is missing, OPL warns and returns to the menu. UDPFS / UDPFSBD (below) are the newer UDPRDMA transport.

### Requirements

- A PC-side UDPBD server speaking **SUDPBDv2**, on the same LAN, exporting a FAT/exFAT block device
  laid out with the usual OPL folders (`CD`, `DVD`, `ART`, `CFG`, …). Good options, in order:
  **[NathanNeurotic/PS2-Servers](https://github.com/NathanNeurotic/PS2-Servers)** — RiptOPL's own
  one-stop bundle (SMBv1 + UDPBD + UDPFS servers); **[pcm720/udpfsd](https://github.com/pcm720/udpfsd)**
  — a single prebuilt Go binary that serves **both** UDPBD *and* UDPFS (Windows/macOS/Linux/ARM, no
  Python); or **[israpps/udpbd-server](https://github.com/israpps/udpbd-server)** — the canonical Rick
  Gaiser `udpbd-server` (CI-built). The bundled `udpfs_server.py` speaks **UDPFS only**, so for the
  default UDPBD protocol use one of the above (pcm720/udpfsd covers both).
- A **static** PS2 IP. The UDPBD module has no DHCP client and reuses the address from
  **Settings → Network Config**, so set a static IP there. OPL warns you if DHCP is on at the
  moment you enable UDPBD.

### Enable it

**Device Settings → Network Protocol** is a single selector with five choices:

| Choice | Wire protocol | On the PS2 | PC server |
|---|---|---|---|
| **Off** | — | no network device (default) | — |
| **SMB** | SMBv1 | a mounted file share (OPL's *own* core, not Neutrino) | Samba / `smbserver_opl.py` |
| **UDPFS** | UDPRDMA | a **filesystem** (`udpfs:`) — loose ISOs in a folder | `udpfs_server.py -d <dir>` / `udpfsd` |
| **UDPFSBD** | UDPRDMA | a **block device** (`massN:`) — a served disk image | `udpfs_server.py -b <image>` / `udpfsd` |
| **UDPBD** | SUDPBDv2 | a **block device** (`massN:`) — a served disk image | `udpbd-server` *(external)* |

Because the PS2 has a **single** network adapter, only ONE of these is active per session — the
selector is exclusive *by construction* (the old separate ETH start-mode + "Network Boot" toggle +
"Net Boot Protocol" picker, and their live interlock, are all gone). Local devices (USB / internal
HDD / MMCE) are independent and browse alongside whichever network protocol you pick.

The three UDP transports have **no DHCP client**, so set a **static** PS2 IP in **Settings → Network
Config** (they reuse it for the in-OPL game list). SMB keeps its own address / port / share /
credentials fields there — those are hidden automatically when a non-SMB protocol is selected. All
three UDP options are Neutrino-only (no `<OPL>` core fallback); if `neutrino.elf` is missing, OPL
warns and returns to the menu.

> **At launch, Neutrino reads its own IP from a toml, not from OPL.** When a game boots, control hands
> to the external Neutrino, whose `config/bsd-udpbd.toml` / `config/bsd-udpfsbd.toml` hardcode
> `ip=192.168.1.10`. If your PS2's static IP differs, **edit the `ip=` line in that toml** (under the
> bundled `neutrino/config/`) to match — otherwise games list fine in OPL but fail to boot.

### UDPFS vs UDPFSBD — two shapes of one UDPRDMA transport

**UDPFS** is Neutrino's newer network transport (Rick Gaiser's **UDPRDMA**), wire-incompatible with
UDPBD's SUDPBDv2 (so it needs a different PC server). RiptOPL offers it in **both** shapes Neutrino
supports, as two separate selector options:

| | **UDPFS** (filesystem) | **UDPFSBD** (block) |
|---|---|---|
| IOP driver | `udpfs_ioman.irx` → `udpfs:` | `udpfs_bd.irx` → `massN:` |
| PC serves | a **folder of loose ISOs** | a **FAT/exFAT disk image** |
| Server command | `udpfs_server.py -d <dir>` | `udpfs_server.py -b <image>` |
| Neutrino `-bsd` | `-bsd=udpfs` (stock token) | `-bsd=udpfsbd` (RiptOPL token) |
| Add a game | drop a file in the folder | mount the image, copy, unmount |
| Compression | `.zso`/`.cso`/`.chd` via `--enable-compression` | — (raw sectors only) |

Both ride the same UDPRDMA transport and the same servers — [pcm720/udpfsd](https://github.com/pcm720/udpfsd)
(a prebuilt Go binary, serves both) or the bundled `udpfs_server.py` (Python 3); just pass `-d` for the
filesystem or `-b` for the block image. A UDPBD-only `udpbd-server` (SUDPBDv2) will not talk to either.

- **UDPFS** launches with the **stock** `-bsd=udpfs`, which loads Neutrino's shipped `bsd-udpfs.toml`
  (the FHI filesystem driver, `udpfs_ioman` / `udpfs_fhi`). Neutrino opens the game by name
  (`-dvd=udpfs:<path>`) — no `massN:` block device, no fragment list.
- **UDPFSBD** launches with **`-bsd=udpfsbd`**, a **RiptOPL-private** token: Neutrino ships
  `udpfs_bd.irx` but no stock `-bsd` for it, so RiptOPL auto-places `config/bsd-udpfsbd.toml` into the
  bundled Neutrino folder. The private name is deliberate — it avoids colliding with stock's
  `bsd-udpfs.toml` (a *different* driver), so the block config and the stock filesystem config coexist
  on one install.

> **So why keep both?** They're the same protocol but a genuinely different workflow. UDPFS is the
> lower-friction, "modern" model (loose ISOs, drop-in, optional compression) and matches how NHDDL and
> pcm720's server are designed. UDPFSBD reuses OPL's existing `massN:` block pipeline (a disk image the
> PS2 mounts with its own FAT/exFAT drivers) — handy if you already keep a block image or want the exact
> same shape as USB/HDD. Pick whichever fits how you store your games. **Hardware note:** the UDPRDMA
> path (both shapes) is validated on emulator only so far — real-PS2 confirmation is pending.

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
- **UDPBD games** have no OPL core backend, so the **Loader Core selector is locked to Neutrino**
  for them (they always launch via Neutrino regardless).

When a game's core is **`<OPL>`** the screen is unchanged from classic OPL, except the Neutrino
Args field and Neutrino Video picker are greyed (never read on the OPL path).

> What Neutrino honors per game: the storage backend + image (`-bsd`/`-dvd`, automatic),
> compat subset (`-gc`), VMC (`-mc0`/`-mc1`), `-logo`, and the free-text **Neutrino Launch
> Args** (the catch-all for everything else, with `$`-disable). Cheats, GSM hacks, IGR/IGS,
> PADEMU and OSD-language are OPL-embedded-core features with no Neutrino equivalent.
