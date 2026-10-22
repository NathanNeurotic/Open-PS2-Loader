# PS1 Games via POPSTARTER and Ember

### Selecting an Ember starting disc

For an Ember game with several CUE files in the same game folder, add `discs.txt`
beside them. For example, put these contents in
`EMBER/games/Final Fantasy VII/discs.txt`, in disc order:

```text
Final Fantasy VII (Disc 1).cue
Final Fantasy VII (Disc 2).cue
Final Fantasy VII (Disc 3).cue
```

When you launch the title, RiptOPL reads this file and offers a starting-disc picker.
Choosing the second entry passes `Final Fantasy VII/Final Fantasy VII (Disc 2).cue`
as Ember's game argument. Back cancels the launch. One listed disc launches directly.
Without `discs.txt`, the existing folder launch is unchanged.

Use up to 16 plain filenames: no quotes, comments, device paths or subdirectories.
Spaces in filenames are preserved. LF/CRLF, a UTF-8 BOM and empty lines are accepted;
entries keep their file order. An unreadable, empty or malformed list, missing selected
CUE, or overlong argument is reported before handoff. The file is read only at launch,
with no additional scan-time metadata or cache. Settings, saves, artwork and Favorites
continue to use the original game folder.

This uses Ember Beta 2's documented `folder/disc-file` argument. RiptOPL only selects
the starting file; Ember's build determines its in-game swapping behavior. The public
README documents explicit file selection but does not currently specify `discs.txt`'s
in-game mapping. Use the matching Ember build when testing that behavior.

RiptOPL lists **PlayStation 1** games beside the PS2 library on the same device. One PS1
view can contain two row types: `*.VCD` images launch through **POPSTARTER**, while game
folders under `EMBER/games/` launch through **Ember**. The row decides the core; there is
no per-page emulator switch.

> This document concentrates on POPSTARTER and its VCD/BDMA handoff. Ember uses the same PS1
> page but does not use POPSTARTER, BDMA, or the memory-card driver preparation described below.

## 1. PS2 and PS1 libraries on each device

Every game device has a PS2 library and a PS1 library:

- **PS2**: ISO / ZSO / UL / HDL rows, as supported by that device.
- **PS1**: POPSTARTER `*.VCD` and Ember game-folder rows, merged and sorted together on ordinary
  local devices, SMB, MMCE, and APA/PFS HDD.

How those libraries appear is controlled by **PS2/PS1 Game Display** (§2). They can be two
L3-switched views, one combined list with filters, or a single locked library. They remain views of
the same device page — with the same covers, favorites, and per-game settings — rather than extra
device tabs.

**RiptOPL’s UDPFS Files page lists Ember titles and uppercase `POPS/*.VCD` files.**
Ember keeps the mounted network transport alive. POPSTARTER reads UDPFS VCDs through Okeanos’s
separate BDM-UDPFS Assault driver and USB support files; see [POPS UDPFS setup](#pops-udpfs-with-bdm-udpfs-assault).
With **BDMA Apply on Launch**, RiptOPL attempts to equip the `.udpfs` pair before VCD handoff.
An already usable matching manual pair also works. Without a valid pair, the network VCD launch
is stopped. UDPBD remains outside this POPSTARTER driver's scope.

## 2. Choose Both, Mixed, PS2, or PS1

The **PS2/PS1 Game Display** picker is on **Settings → Interface**. It is one global setting
for every device page:

| Value | Behavior |
| --- | --- |
| **Both (L3)** (default) | each device page has separate PS2 and PS1 views; **L3** switches between them and each page retains its own position |
| **Mixed** | each device page initially combines its PS2 and PS1 rows; **L3** cycles **Mixed → PS2 → PS1** on that device |
| **PS2** | each applicable device page shows PS2 rows only; L3 is completely inert, with no hint, sound, notification, or pause |
| **PS1** | each applicable device page shows PS1 rows only; L3 is completely inert, with no hint, sound, notification, or pause |

The setting applies to device game pages, including UDPFS and UDPBD. It does **not** control APPS or
Favorites; those pages have the independent behavior described below. Switching back to an
L3-enabled mode restores each device page's retained position. Returning from the Start/settings
menu also returns to the device page you paused on when that page is still visible; it no longer
arbitrarily selects USB.

### APPS and PS1 ELF titles

The independent **APPS Display** picker has two values:

- **Mixed** (default) shows every configured ELF in one list and leaves L3 completely inert.
- **Apps / PS1ELF (L3)** gives APPS two L3 views. Entries whose displayed title contains **`[PS1]`**
  (case-insensitive) appear on **PS1ELF**; all other entries appear on **Apps**. This is only a list
  accommodation for users who package PS1 launchers as ELFs. Either side still launches the entry
  as an ordinary configured ELF.

### Favorite your PS1 games

Press **R3** on a PS1 title to favorite it, exactly as you would a PS2 game. The **Favorites** page
always keeps its own independent four-stop L3 ring:

1. **All in One** — PS2, PS1, and ELF favorites together.
2. **PS2** — PS2 disc favorites only.
3. **PS1** — POPSTARTER and Ember favorites together.
4. **ELF** — homebrew/app favorites only.

A VCD favorite launches through POPSTARTER straight from the Favorites tab — even when the
source device page is currently showing its disc list — and carries its PS1 cover art and
disc badge with it.

The favorite handoff is wired on **every device with a VCD view** — USB, MX4SIO, iLink, the internal
exFAT HDD, SMB, MMCE, and the **APA-formatted internal HDD**. (On the APA HDD the PS1 games are spread across multiple
APA partitions, so opening one of its VCD favorites re-scans those partitions to find the game —
the first launch may take a moment.)

## 3. How PS1 games launch (POPSTARTER only)

VCD titles always boot through **`POPSTARTER.ELF`**. They never use OPL's built-in core
or Neutrino, so on a VCD game the per-game **Loader Core** selector is locked to an
inert label — choosing a core there has no effect on a PS1 game.

For ordinary VCD files, POPSTARTER needs the VCD's *name*; RiptOPL hands it the selected
title and POPSTARTER finds the matching `*.VCD`. An APA one-game install instead launches
with its literal, case-sensitive `PP.<name>` / `__.<name>` partition label so POPSTARTER can
mount that partition and boot its fixed `IMAGE0.VCD`.

Every local block-device VCD handoff, including iLink, uses POPSTARTER's normal local selector:
`mass:/POPS/XX.<name>.ELF`. OPL's live mount may be `massN:`, but POPSTARTER resets the IOP and
re-registers the selected device driver as bare `mass:` before it resolves that `XX.` argument.

> **Current iLink hardware status:** the selector and external equip are present, but revision 2692
> still returned POPSTARTER to wLaunchELF on an SCPH-39001 in all four SDK flavours. Ember passed on
> the same iLink disk. Treat iLink POPSTARTER as **wired but not hardware-confirmed** until a later
> build passes; the statement above documents the argument contract, not a claimed successful boot.
>
> **i.LINK after POPSTARTER's IOP reset (#1018).** POPSTARTER's i.LINK driver (`usbhdfsd.irx.ilink`)
> never logs out of the drive, so after POPSTARTER resets the IOP the drive still holds the previous
> driver's exclusive login for its reconnect hold (at least 1 s) and refuses the new one. The old
> driver stopped asking after about 0.8 s and never asked again. The driver now shipped in `POPS/`
> keeps asking for up to 5 s, waits for the drive to become ready, and offers it only once it is.
> Copy this release's whole `POPS/` folder to the iLink drive: with **VCD BDMA Apply on Launch** on,
> a card still holding the old driver (21,609 bytes) then gets the new one at the next iLink launch,
> because the size no longer matches. If the drive's `POPS/` still has the old file, RiptOPL does not
> copy it: it warns *The device's POPS folder has old BDMA drivers -- copy this release's POPS folder
> there.*, leaves the card as it is, and the launch goes ahead with the card's current driver.
> Not yet confirmed on hardware.

Where `POPSTARTER.ELF` is loaded from is controlled by **PS Emulation Settings →
POPSTARTER.ELF Path**. The old device picker is gone. The path field displays **`<not set>`** until
you enter a custom full path. When you upgrade, a device the old picker was set to becomes the matching
path, for example `usb:/POPS/POPSTARTER.ELF` or `mmce:/POPS/POPSTARTER.ELF`, and an old Custom path is
kept as it was. HDD (APA) and Game's Device become `<not set>`, because the Game Device tier below
already covers them.

The launch resolver uses one fixed order:

1. **Custom Path** — the user-entered full `POPSTARTER.ELF` path, when present and resolvable.
2. **Game Device** — the VCD's own `POPS/POPSTARTER.ELF`.
3. **Memory Card** — `mc0:/POPS/POPSTARTER.ELF`, then `mc1:/POPS/POPSTARTER.ELF`.

A stale or temporarily unavailable custom path does **not** strand the launch; it falls through to the
same Game Device → MC behavior as an empty field.

The custom ELF may live on a different backend from the VCD. RiptOPL keeps both backends available
until the argv-preserving loader has opened `POPSTARTER.ELF`, so combinations such as an
MMCE-hosted ELF with an APA-HDD game are no longer torn down merely because the game is elsewhere.
Typed BDM aliases are normalized by the mounted driver's real identity (`massN:` may be USB,
MX4SIO, ATA, iLink, or a network block transport). They search the devices mounted now and load
only the one named driver, briefly, when no device of that family is present; `massN:` is that exact
slot. [NEUTRINO.md](NEUTRINO.md#custom-paths-and-cross-device-launches) has the full rules, which
are shared. APA `hdd:/...` / `hdd0:/...` paths resolve only through the already-selected live OPL
data-home partition; RiptOPL does not mount an arbitrary APA partition just because a custom ELF
path names one.

When RiptOPL equips the BDMA drivers, it looks for the variant files first beside the file the
custom path resolved to, so keep them in the same folder as a relocated `POPSTARTER.ELF`.

For an **APA-HDD VCD**, the Game Device tier retains the established canonical
`hdd0:__common/POPS/POPSTARTER.ELF` route. If that is absent, the resolver proceeds to the memory
cards. A custom path still outranks the APA default.

The path editor uses the full 256-byte setting buffer, and its text field scrolls to keep the cursor
in view; it is no longer limited to the 31-character inline preview.

This setting moves **only the executable `POPSTARTER.ELF`**. It does not relocate POPSTARTER's
memory-card dependency/config folder used by SMB/BDMA preparation; those files retain their existing
`mc?:/POPSTARTER/` rules.


### Which *build* of POPSTARTER

The resolver above chooses which **copy** of `POPSTARTER.ELF` is loaded. Which **build** that copy is
comes down to the file itself, and the release package ships five of them in
`POPS/POPSTARTER VERSIONS/`:

| Build | Use it when |
| --- | --- |
| **MAIN** | POPSTARTER without the SMB support the shipped default carries. Only if you know you do not need SMB. |
| **DEBUG** | **The shipped default.** SMB-capable, and prints POPSTARTER's own diagnostics on screen. |
| **USBDELAY** | USB devices that need longer to settle before POPSTARTER reads them. |
| **USBDELAY_DEBUG** | USBDELAY plus the diagnostics. |
| **USBDELAY_LONGER_DEBUG** | A longer delay again, with diagnostics. |

Swapping is manual: copy the `POPSTARTER.ELF` you want over the `POPS/POPSTARTER.ELF` that the
resolver selects. RiptOPL never chooses a build for you and never rewrites that file.

> **The shipped `POPS/POPSTARTER.ELF` is the DEBUG build, deliberately** — it is the build carrying
> SMB support, so it is the correct default for the package. POPSTARTER diagnostic text during an
> otherwise healthy VCD launch is therefore expected on every device, and is not evidence of a
> problem on its own. Do not replace it with **MAIN** unless you are certain you do not need SMB.

## 4. Where to put your VCD files

| Device | Location |
| --- | --- |
| USB / MMCE / MX4SIO / iLink / SMB | a **`POPS`** folder at the device root, holding `POPSTARTER.ELF` + your `*.VCD` files |
| Internal HDD (APA/PFS) | two layouts, both listed: an exact **`__.POPS`, `__.POPS0` … `__.POPS9`** store partition (many `*.VCD` on its root, named per file), and/or **`PP.<name>`** (visible) / **`__.<name>`** (hidden-label) one-game partitions. A one-game candidate is listed only when its root contains the exact file **`IMAGE0.VCD`**, which prevents similarly named HDD apps from appearing as games; it is shown as `<name>`. `POPSTARTER.ELF` is loaded from the canonical **`__common/POPS`** location unless a custom full path is configured. |

> The HDD's `XX.*` (BDMA/exFAT) and `SB.*` (SMBv1) launcher partitions point at VCDs that live on
> an exFAT device or an SMB share — those games appear under the **USB/MX4SIO/MMCE** or **SMB** VCD
> views, not the internal-HDD one.

VCD per-game config and art use the VCD **filename without `.VCD`** as their identity. They
otherwise follow the same layout and suffix rules as PS2 games on that device:

- `POPS/SCUS_123.45.Example.VCD`
- `CFG/SCUS_123.45.Example.cfg`
- `ART/SCUS_123.45.Example_COV.png`

When the filename begins with a valid PS1 disc ID, RiptOPL also accepts that ID as a fallback after
the filename lookup misses. For the example above, the fallback names are
`CFG/SCUS_123.45.cfg` and `ART/SCUS_123.45_COV.png`. This is a same-folder compatibility fallback;
`POPS/ART/` and a suffixless `POPS/<name>.png` remain POPSLoader-only layouts.

APA `PP.<name>` and `__.<name>` one-game installs are the naming exception: every partition contains
the same physical `IMAGE0.VCD` filename, so config and art use the displayed `<name>` from the label.

> **Internal HDD covers and config:** VCD entries use the same OPL data prefix as PS2 HDD
> games. On a `+OPL` data partition that means its root `ART/` and `CFG/` folders; when OPL
> data lives under the legacy `__common/OPL/` layout, use `OPL/ART/` and `OPL/CFG/`.

## 5. Block-device PS1 support — the BDMA equip

POPSTARTER reloads its mass-storage driver after resetting the IOP. USB FAT32 can use its built-in
driver; USB exFAT and the MX4SIO, MMCE, ATA and iLink transports need matching external
block-device modules (the BDMAssault / "BDMA" drivers). RiptOPL
*equips* them for you from the BDMA rows on **Settings → PS Emulation Settings** — RiptOPL copies the selected
loose pair from a device's `POPS/` folder onto your memory card:

RiptOPL prefers an existing `mc0:/POPSTARTER` or `mc1:/POPSTARTER` folder. It **creates** one only
when it has something to put in it: a BDMA driver pair it found, a POPSTARTER launch's install, or a
POPStarter network-settings save. Opening the settings, reading the BDMA mode, or choosing FAT32 (no
external driver) never creates it. A new folder goes on the first present card (slot 1, then
slot 2) and always gets its browser icon first: POPStarter's own `icon.sys`/`list.icn`/`del.icn`
from the `POPS/` folder the files come from, or RiptOPL's icon titled POPSTARTER when that folder has
none. It therefore never shows as Corrupted Data. An icon-less folder left by an older build can
simply be deleted from the PS2 browser if you don't use POPStarter. Both replacement modules are
staged before the live pair is changed, so a failed copy leaves the previous pair available.

- **VCD BDMA Apply on Launch** *(default On)* — POPSTARTER does its own IOP reset and reloads
  its block-device driver from the memory card, so the right exFAT variant must already be on
  the card or the game drops to OSDSYS. When **On**, RiptOPL equips the variant matching the
  PS1 game you're launching (read from that game's own device) automatically, right before
  boot. Turn it **Off** to manage the driver yourself; that reveals the **BDMA Source** / **BDMA
  Mode** pickers below. Automatic equip proves only that the right files were staged; it does not
  turn the still-failing revision 2692 iLink POPSTARTER result into a pass.
- **USB launches always ask** — the PS2 cannot detect whether a USB stick is fat32 or exFAT
  formatted, so every USB .VCD launch first shows a **"fat32 or exFAT USB Mode?"** dialog
  (fat32 is recommended for non-exFAT USB users). Picking **fat32** de-equips to POPSTARTER's
  built-in USB stack (preserving any complete, unmarked manually-managed module pair); picking
  **exFAT** equips the BDMAssault `usbexfat` pair. The pick applies even when Apply-on-Launch is Off,
  and backing out of the dialog cancels the launch.
- **BDMA MODE** *(manual; shown when Apply-on-Launch is Off)* — which driver variant POPSTARTER should use: `USB (FAT32)` (none —
  removes the exFAT modules so POPSTARTER falls back to its built-in FAT32 driver),
  `USB (exFAT)`, `MX4SIO (exFAT)`, `MMCE (exFAT)`, `HDD (exFAT)` (the internal ATA
  HDD via BDMAssault), or `iLink`.
- **BDMA SOURCE** — which device holds the module files in its `POPS` folder: `USB`,
  `MX4SIO`, `MMCE`, `Internal HDD`, or `iLink`. OPL identifies each device by its block-device **driver**
  (`usb` / `mx4sio` / `ata` / `ilink` / `mmce`) and reads from that specific device, so pick the one your
  module files actually sit on. For the internal exFAT HDD choose **`Internal HDD`** — OPL reads the
  files from the same **`massN:/POPS/`** folder it lists that drive's PS1 games from (it never mounts
  an `ata0:` *filesystem*; `ata0:` is only an internal block-device identity, not a readable path).
  It is the same physical volume wLaunchELF shows, so place `POPS/usbd.irx.ata` +
  `POPS/usbhdfsd.irx.ata` there.

> **Module file names matter.** The two driver files in that `POPS/` folder must be named for the
> BDMA **MODE** you pick: **`usbd.irx.<mode>`** and **`usbhdfsd.irx.<mode>`**. For `HDD (exFAT)` that
> is **`usbd.irx.ata`** + **`usbhdfsd.irx.ata`**; iLink uses **`usbd.irx.ilink`** +
> **`usbhdfsd.irx.ilink`** (other modes use `.usbexfat`, `.mx4sio`, `.mmce`). Plain `usbd.irx` /
> `usbhdfsd.irx` with **no suffix** are ignored. If the selected pair is absent from every searched
> device `POPS/` folder, RiptOPL warns and leaves the current memory-card pair unchanged.
>
> **An older release's pair is passed over at launch.** Each release ships one pair per mode, and the
> launch equip checks a pair's file sizes before copying it. A pair from another release is skipped
> and the search goes on to the next folder, so a current pair on the game's device still wins over
> an old one in the boot device's `POPS/`. If only old pairs turn up, nothing is copied, the card
> keeps its current pair, and the launch goes ahead with the warning *The device's POPS folder has
> old BDMA drivers -- copy this release's POPS folder there.* Copying the release's whole `POPS/`
> folder to that device fixes it at the next launch. The manual **BDMA Mode** / **BDMA Source** equip
> (Apply-on-Launch Off) still installs whichever pair you put there.

When you change either setting, RiptOPL copies the chosen variant's modules from the
SOURCE device's `POPS` folder onto `mc?:/POPSTARTER/` and records the equipped state in a
marker file there (compatible with POPSLoader). Every pair ships as separate files in the release
`POPS/` folder; **no BDMA module is embedded in `RIPTOPL.ELF`**. On apply, RiptOPL strips only the
mode suffix and writes `mc?:/POPSTARTER/usbd.irx` + `mc?:/POPSTARTER/usbhdfsd.irx`. Keep the whole
release `POPS/` folder on the relevant device so automatic launch preparation can find its pair.
SMB is network-only, so the BDMA equip does not apply to it.

The internal **exFAT HDD** (enable *BDM HDD* in **Game Sources**) mounts as a normal BDM
block device, so its PS1 games in `massN:/POPS/` list and launch through the same device page
according to **PS2/PS1 Game Display** — there's no separate page. Equip the `HDD (exFAT)` BDMA mode
so POPSTARTER itself can read them off the exFAT volume.

### POPS UDPFS with BDM-UDPFS Assault

[Okeanos's BDM-UDPFS Assault](https://github.com/Okeanos86/BDMAssault/releases/tag/Alpha)
adds **read-only UDPFS fallback** to POPSTARTER's USB driver. USB is tried first; when a VCD
is absent there, the driver requests the same path from the UDPFS server after POPSTARTER's
IOP reset. This is a POPSTARTER driver, separate from Neutrino's PS2 UDPFS loader.

The included `POPS/` folder supplies these four files:

| Included file | Installation / purpose |
| --- | --- |
| `usbd.irx.udpfs` | Copy to `mc?:/POPSTARTER/usbd.irx`, removing `.udpfs` |
| `usbhdfsd.irx.udpfs` | Copy to `mc?:/POPSTARTER/usbhdfsd.irx`, removing `.udpfs` |
| `IPCONFIG.DAT` | USB `mass:/POPS/IPCONFIG.DAT`: PS2 IP, netmask, optional gateway |
| `UDPFSCONFIG.DAT` | USB `mass:/POPS/UDPFSCONFIG.DAT`: UDPFS server IP; empty file enables discovery |

Keep your own `POPS_IOX.PAK` and other runtime POPS files on USB. The driver pair can be
sourced from `POPS/` on any supported device, including APA HDD `__common/POPS/`.
On the server, place the VCD at the matching path relative to the shared root, for example
`POPS/SLUS_011.56.VCD`; the driver also accepts `POPS0/` through `POPS9/`. Use uppercase
`.VCD`. Only VCD reads fall back to the network; other files and writes stay on USB.
The upstream release reports testing with `udpfsd` and `udpfs_server.py`.

Edit the supplied examples for your LAN before use: `IPCONFIG.DAT` contains
`192.168.1.10 255.255.255.0 192.168.1.1`, and `UDPFSCONFIG.DAT` contains `192.168.1.11`.
Without a valid IP config, the driver uses PS2 `192.168.1.10/24`; without a valid same-subnet
server address it uses broadcast discovery. The server must be on the PS2's subnet: the
driver does not route through the gateway. These files are read from USB, not from the
memory card and not from RiptOPL's saved network settings.

**RiptOPL setup:** open **POPS Network Settings → POPS UDPFS Network Settings** and enter
your PS2 IP, netmask and server IP. Server `0.0.0.0` selects broadcast discovery. Saving writes
both files to **every connected USB volume's `POPS/` folder**, with replacement confirmation
for existing files. This editor is separate from the SMB memory-card configuration.

The **UDPFS Files** PS1/Mixed view now lists uppercase `POPS/*.VCD` alongside Ember titles.
Launching a VCD there, or from Favorites, checks the USB config pair on every connected USB
volume and requires matching valid values before proceeding. This explicit check is an interim
requirement because the Alpha IRX reads runtime configs from USB `mass:/POPS/`; upstream
itself permits missing files and falls back to defaults. Installing support files on another
device does not change that runtime USB requirement.

With **VCD BDMA Apply on Launch** enabled, RiptOPL equips the `.udpfs` pair on the memory
card and hands POPSTARTER its usual `mass:/POPS/XX.<name>.ELF` selector. With automatic
equip disabled, select **BDMA Mode → UDPFS** and equip the pair manually. Existing BDMA
equip failures remain best-effort warnings, so inspect the installed pair if a launch fails.
USB VCDs take precedence over the server when both contain the same path. UDPBD and UDPFS
IMG remain Ember-only. The new RiptOPL VCD handoff is implemented and host-tested; physical
console validation is still pending, and POPS UDPFS RetroAchievements integration is unavailable.

Credit goes to **Okeanos** for BDM-UDPFS Assault, **israpps** for the original BDM Assault,
**krHACKen** for POPSTARTER, **rickgaiser** for Neutrino/UDPFS/UDPRDMA, **pcm720** for `udpfsd`,
and the **PS2SDK contributors**. The upstream release is **Alpha**. Its license and third-party
notices accompany the drivers in `POPS/UDPFS-NOTICES/`.

## 6. PS1 over SMB — POPSTARTER network settings

PS1 games on an SMB share need POPSTARTER's own network config (`IPCONFIG.DAT` +
`SMBCONFIG.DAT`) on the memory card, plus its SMB modules. Edit those files from
**POPSTARTER Network Settings**, on **Settings → PS Emulation Settings** or **Settings → Network**.
The screen shows what the card's files already contain, can import both from the connected share's
`POPS` folder, and on OK writes back only the values you changed. The exception is a first setup:
with neither file on the card, saving the SMB values writes `IPCONFIG.DAT` too, as DHCP unless a
complete static IP is entered. The SMB modules themselves ship in the release's `POPS/` folder
(copy them to `mc?:/POPSTARTER/`); if they're missing, an SMB VCD launch warns rather than
hanging.

## 7. Troubleshooting — "my VCDs don't show up"

Work down this ladder; each step isolates a different stage (from the #154 forensics):

1. **Does the device page appear at all?** If not, it's the device enables, not VCD: USB/MX4SIO/
   iLink need their toggles on; the **internal exFAT** page needs *BDM devices* + *BDM HDD* ON.
   APA/PFS and exFAT/BDM-ATA can both be enabled because they share the ATA stack; leaving the APA
   page enabled does not suppress the exFAT page.
2. **Do PS2 ISOs list from the device?** If yes, the filesystem/mount layer is proven working and
   the problem is downstream of listing — skip to the VCD-specific steps below.
3. **Check PS2/PS1 Game Display.** **Both (L3)** switches between separate libraries and **Mixed**
   cycles Mixed/PS2/PS1. L3 is intentionally absent and inert in the locked **PS2** and **PS1**
   modes; choose **PS1** when you want the PS1 library without an L3 action.
4. **VCDs are scanned from `<device-root>:/POPS/*.VCD`** — the game-folder prefix
   (`usb_prefix` etc.) is deliberately **not** applied, because POPSTARTER itself only reads
   `/POPS` at the root. A `POPS` folder inside your games subfolder will never be found.
5. **Name rules:** basenames longer than **160 characters** and the reserved name
   **`POPSTARTER.VCD`** are skipped at scan (the debug log says so) — previously they listed but
   could never launch (a dead ✕ button). Rename the file.
6. **Fails only after selecting a game?** Then listing/scan is fine and the handoff is the
   suspect: `POPSTARTER.ELF` present in `/POPS` (or `__common/POPS` on APA)? On a BDMA-backed device, the BDMA
   equip (§5) is best-effort — a failed equip toasts but the launch still proceeds and may land
   on OSDSYS.
7. **iLink returns to wLaunchELF?** Inspect the card after the attempt. A successful RiptOPL equip
   leaves `mc?:/POPSTARTER/bdma_config.txt` containing exactly `ilink`, plus `usbd.irx` (48,500 bytes;
   SHA-256 `5EA4818BA1CF5207F6D7CADB4C13B5AFA88C37C260750C21155B079A8C18F369`) and `usbhdfsd.irx`
   (21,977 bytes; SHA-256 `8F9A9E4E6984A58435FE7E24E1E5832F027DC537B3274BC4220245BBE1844714`). Missing or different files
   put the defect on RiptOPL's external-equip side; exact files narrow it to POPSTARTER/BDMA runtime
   reinitialization after the handoff.
8. **UDPFS shows Ember but no VCDs?** Select **UDPFS Files**, check server `POPS/*.VCD`
   with uppercase `.VCD`, and refresh the PS1/Mixed view. For launch failures, check the
   [BDM-UDPFS Assault setup](#pops-udpfs-with-bdm-udpfs-assault): installed memory-card
   pair, matching USB configs, runtime support files and same-subnet server. UDPBD and UDPFS
   IMG remain Ember-only.
9. **"Missing ember.elf", "Missing bios.bin beside ember.elf" or "Missing POPSTARTER.ELF" on
   launch?** The message's second line is the exact file RiptOPL looked for, for example
   `mass0:/EMBER/ember.elf` or `mass0:/POPS/POPSTARTER.ELF` (on the internal HDD,
   `hdd0:__.EMBER/EMBER/ember.elf` or `hdd0:__common/POPS/POPSTARTER.ELF`; with a custom
   **POPSTARTER.ELF Path** set, that path). Put the file there and launch again. Ember game folders
   stay listed while `ember.elf` is missing, so a missing or misnamed core shows up as this message
   instead of an empty Ember library. On the internal HDD, "Error, could not run the item." with a
   partition name (`hdd0:__.EMBER`) means that partition itself would not mount, so nothing inside
   it was checked yet.

## 8. Notes & limitations

- Ember does not provide IGR. POPSTARTER has its own reset behavior; neither
  uses [RiptOPL's PS2 IGR hook](IGR.md).
- **Ember list empty on a BDM drive:** a reproduced scanner defect lets a
  loose file such as `EMBER/games/readme.txt` or `.DS_Store` abort the Ember
  scan on FAT32 and exFAT. Move loose files out of `EMBER/games/`, leaving
  the individual game directories there. [PR #999](https://github.com/NathanNeurotic/Open-PS2-Loader/pull/999)
  proposes the fix; this does not require reformatting the disk or changing
  the PS2 BDM Prefix.
- VCD support reuses the normal device pipeline, so covers, favorites and the theme all
  work exactly as they do for disc games.
- POPSTARTER, the patch file and every BDMA module variant are supplied as separate files in the
  release `POPS/` folder. RiptOPL embeds none of them.
- The Loader Core, GSM, Cheats, PADEMU and similar per-game options do not apply to PS1
  games (POPSTARTER ignores them).

See also **[NEUTRINO.md](NEUTRINO.md)** for the separate PS2 external-core loader, and
**[../ROLLING_RELEASE.md](../ROLLING_RELEASE.md)** for what the builds contain.
