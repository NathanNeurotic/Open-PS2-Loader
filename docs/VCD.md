# PS1 Games via POPSTARTER (the "VCD" view)

RiptOPL can list and launch your **PlayStation 1** games (`*.VCD` images) right
alongside your PS2 library, on the same device. PS1 titles boot through
**POPSTARTER** — never OPL's built-in core and never Neutrino — so this is a
self-contained path with its own settings.

> The in-app UI deliberately calls this a **VCD** view rather than "PS1" or "POPS",
> so it reads cleanly next to your disc games.

## 1. The VCD view (press L3)

Every device that can hold games — USB, MMCE, MX4SIO, iLink, SMB, and the internal
HDD — has two lists:

- its **disc** games (PS2 ISO / ZSO / UL), and
- its **VCD** games (PS1 `*.VCD`).

Press **L3** on a device page to switch that page between the two. It is a **view**,
not a separate tab — the same page, the same covers, favourites and per-game settings,
just a different list. An on-screen hint shows whether you're looking at discs or VCDs.

## 2. Lock a page with "Default game view"

If you don't want to press L3 every time, open **Settings → Display Settings** and set
**Default game view**:

| Value | Behaviour |
| --- | --- |
| **Both** (default) | every page starts on its disc list; **L3** toggles to the VCD list |
| **ISO** | every page is locked to its disc list (L3 does nothing) |
| **VCD** | every page is locked to its VCD list (L3 does nothing) |

**Favourites follow the active view:** while a page shows VCDs, its favourited VCD
titles appear; while it shows discs, its favourited discs appear. Nothing is lost —
favourites that don't match the current view simply aren't shown until you switch back.

## 3. How PS1 games launch (POPSTARTER only)

VCD titles always boot through **`POPSTARTER.ELF`**. They never use OPL's built-in core
or Neutrino, so on a VCD game the per-game **Loader Core** selector is locked to an
inert label — choosing a core there has no effect on a PS1 game.

POPSTARTER only needs the VCD's *name* to do its job; RiptOPL hands it the selected
title and POPSTARTER finds the matching `*.VCD`.

By default RiptOPL looks for `POPSTARTER.ELF` in each device's `POPS` folder. To use one
specific copy everywhere, set **Settings → General Settings → POPSTARTER.ELF Path**.
(Like the other path fields, the on-screen editor caps at 31 characters; for a longer
path, set `popstarter_path` in `settings_riptopl.cfg` directly.)

## 4. Where to put your VCD files

| Device | Location |
| --- | --- |
| USB / MMCE / MX4SIO / iLink / SMB | a **`POPS`** folder at the device root, holding `POPSTARTER.ELF` + your `*.VCD` files |
| Internal HDD (APA/PFS) | the dedicated **`__.POPS`, `__.POPS0` … `__.POPS9`** APA partitions (each holds its `*.VCD` at the partition root) |

If a VCD's filename matches the PS1 disc-ID pattern `SXXX_NNN.NN.Title.VCD`, RiptOPL keys
cover art and per-game config off that PS1 ID, so PS1 covers load from your `ART` folder
exactly like PS2 covers. Any other `*.VCD` name is still listed and launched — it just
won't auto-match art by ID.

## 5. exFAT PS1 support — the BDMA equip

POPSTARTER's stock driver reads FAT32. To boot PS1 games from an **exFAT** drive,
POPSTARTER needs extra block-device modules (the BDMAssault / "BDMA" drivers). RiptOPL
*equips* them for you from **General Settings** — you supply the module files, RiptOPL
copies the right pair onto your memory card when you change the setting:

- **BDMA MODE** — which driver variant POPSTARTER should use: `USB (FAT32)` (none —
  removes the exFAT modules so POPSTARTER falls back to its built-in FAT32 driver),
  `USB (exFAT)`, `MX4SIO (exFAT)`, `MMCE (exFAT)`, or `HDD (exFAT)` (the internal ATA
  HDD via BDMAssault).
- **BDMA SOURCE** — which device holds the module files in its `POPS` folder: `USB`,
  `MX4SIO`, `MMCE`, or `Internal HDD`. OPL identifies each device by its block-device **driver**
  (`usb` / `mx4sio` / `ata` / `mmce`) and reads from that specific device, so pick the one your
  module files actually sit on. For the internal exFAT HDD choose **`Internal HDD`** — OPL reads it
  from its `ata0:` root (the same volume/path wLaunchELF shows), so its `POPS/usbd.irx.ata` +
  `POPS/usbhdfsd.irx.ata` are found.

> **Module file names matter.** The two driver files in that `POPS/` folder must be named for the
> BDMA **MODE** you pick: **`usbd.irx.<mode>`** and **`usbhdfsd.irx.<mode>`**. For `HDD (exFAT)` that
> is **`usbd.irx.ata`** + **`usbhdfsd.irx.ata`** (other modes use `.usbexfat`, `.mx4sio`, `.mmce`).
> Plain `usbd.irx` / `usbhdfsd.irx` with **no suffix** are ignored — that is what triggers the
> *"BDMA module files not found"* message.

When you change either setting, RiptOPL copies the chosen variant's modules from the
SOURCE device's `POPS` folder onto `mc?:/POPSTARTER/` and records the equipped state in a
marker file there (compatible with POPSLoader). Nothing is embedded in the loader — you
provide the module files, so there is no ELF bloat. SMB is network-only, so the BDMA
equip does not apply to it.

The internal **exFAT HDD** (enable *BDM HDD* in Device Settings) mounts as a normal BDM
block device, so its PS1 games in `massN:/POPS/` list and launch through the same VCD view
(press **L3**) as USB/MX4SIO — there's no separate page. Equip the `HDD (exFAT)` BDMA mode
so POPSTARTER itself can read them off the exFAT volume.

## 6. PS1 over SMB — network config mirror

PS1 games on an SMB share need POPSTARTER's own network config (`IPCONFIG.DAT` +
`SMBCONFIG.DAT`) on the memory card, plus its SMB modules. RiptOPL can write those config
files for you: enable **Settings → Network Settings → Write POPSTARTER Network Config**
(off by default). On save it mirrors the same IP / share values OPL already uses into
`mc?:/POPSTARTER/`. The SMB modules themselves ship in the release's `POPSTARTER/` folder
(copy them to `mc?:/POPSTARTER/`); if they're missing, an SMB VCD launch warns rather than
hanging.

## 7. Notes & limitations

- VCD support reuses the normal device pipeline, so covers, favourites and the theme all
  work exactly as they do for disc games.
- POPSTARTER, the BDMA module variants, and the patch file are supplied by you (or bundled
  in the release `POPS/` folder) — RiptOPL embeds none of them.
- The Loader Core, GSM, Cheats, PADEMU and similar per-game options do not apply to PS1
  games (POPSTARTER ignores them).

See also **[NEUTRINO.md](NEUTRINO.md)** for the separate PS2 external-core loader, and
**[../ROLLING_RELEASE.md](../ROLLING_RELEASE.md)** for what the builds contain.
