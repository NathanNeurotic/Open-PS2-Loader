# Neutrino Core (External Loader)

This fork can hand a game off to an **external [Neutrino](https://github.com/ps2max32/neutrino) ELF**
instead of OPL's built-in EE core, on a **per-game** basis. This is useful for titles that
boot better under Neutrino, or for users who prefer Neutrino's loader and its launch flags.

> The core selector and the launch-args fields described here are specific to this fork.

## Credit and licence

**[Neutrino](https://github.com/ps2max32/neutrino) is created by [rickgaiser](https://github.com/rickgaiser)** — a *"Small, Fast and Modular
PS2 Device Emulator"*. Home: <https://github.com/ps2max32/neutrino>.

The [RiptOPL](https://github.com/NathanNeurotic/RiptOPL) release package
bundles the upstream development pre-release selected at publish time (falling back to the upstream latest release when no pre-release is listed); a failed download or incomplete extraction fails packaging, under [Neutrino](https://github.com/ps2max32/neutrino)'s
**AFL-3.0** licence. We add one file to that folder — `config/bsd-udpfsbd.toml`, because
Neutrino ships `udpfs_bd.irx` without a matching `-bsd` token and RiptOPL launches UDPFS as
`-bsd=udpfsbd` — and replace the i.LINK pair: `modules/IEEE1394_bd_mini.irx` and its manager
`modules/iLinkman.irx` are RiptOPL's builds of the same ps2sdk modules (`modules/ilink/IEEE1394_bd` and
`modules/ilink/iLinkman`, see their `ORIGIN.txt`). The stock driver gives up logging in to an i.LINK
drive before the drive lets go of the login held across an IOP reset, so i.LINK games never started
(#1018); the manager carries the transmit-cancel, alarm and receive-FIFO fixes. The RetroAchievements
kit's ORBIT runtime gets the same pair (#1065). Nothing else of [rickgaiser](https://github.com/rickgaiser)'s is altered or removed.

[Neutrino](https://github.com/ps2max32/neutrino) is deliberately **UI-agnostic**: it has no interface of its own, and that is exactly what
makes a front-end like this one possible. [RiptOPL](https://github.com/NathanNeurotic/RiptOPL) is one of several — **[LUNA](https://github.com/dnunezx/LUNA)**
by **[darkladark](https://github.com/dnunezx)** (our #1 recommended alternative, for lightweight,
customized Neutrino gameplay), **[NHDDL](https://github.com/pcm720/nhddl)**, **XEB+ Plugin**, **RETROLauncher**, **OSD-XMB** and
**PSBBN/BBNL** all drive the same core.

Report *launching* problems here — building the arguments and handing off are ours. Genuine [Neutrino](https://github.com/ps2max32/neutrino)
bugs belong on [rickgaiser](https://github.com/rickgaiser)'s tracker.

### PSX DESR DVR filesystem (experimental)

[RiptOPL](https://github.com/NathanNeurotic/RiptOPL) can detect the DESR DVRP hardware capability and enumerate ISO files
from the DVR-side `dvr_pfs0:` / `dvr_pfs1:` filesystems using read-only
mounts. For launching, **[pcm720](https://github.com/pcm720)'s separate [bsd-dvr Neutrino branch](https://github.com/pcm720/neutrino/tree/bsd-dvr)**
is required: normal bundled [Neutrino](https://github.com/ps2max32/neutrino) does not contain its DVR modules. Select
the full DVR Neutrino installation under **Neutrino Path**. RiptOPL emits
`-bsd=dvr` and `-dvd=dvr_pfsN:/path.iso`, without `-qb` (which would
skip the required PSX-mode transition). This is unverified on DESR hardware
and is not yet included in the official supported-device matrix. See
[DESR-DVR.md](DESR-DVR.md) for precise implementation scope, safety and tests.

## 1. Install Neutrino

RiptOPL's own installation folder and Neutrino's folder are independent. **You do not need to move RiptOPL out of `APPS/` or into the memory-card root.** Automatic memory-card lookup expects the complete Neutrino installation under `mc0:/neutrino/` or `mc1:/neutrino/`; a Neutrino folder nested inside an app folder needs an explicit full **Neutrino Path**. Setting the path selects an installation, not a game source, and does not repair a missing configuration or module.

Copy Neutrino's **whole `neutrino/` folder**, not only `neutrino.elf`. RiptOPL validates the
install before launch: `config/system.toml` (or the flat SAS-layout `system.toml`) must exist
beside the ELF. An ELF-only/incomplete folder is skipped and the next fallback is tried.

Open **Settings → Game Launching → Neutrino Defaults**. **Neutrino Path** is a full-path text field.
Until you explicitly set one, it displays **`<not set>`**. An empty value is intentional and keeps
the compatibility-first automatic behavior.

The lookup order is fixed and deliberately short:

1. **Custom Path** — if Neutrino Path is non-empty, RiptOPL resolves that exact full path first.
2. **Game Device** — if the custom path is absent or unavailable, RiptOPL checks the active game's
   device for `neutrino/neutrino.elf` (including the established case variants).
3. **Memory Card** — finally `mc0:`, then `mc1:`.

There is no Neutrino device picker anymore. When you upgrade, an old **Memory Card** or **HDD (APA)**
choice becomes the matching Neutrino Path: `mc:/NEUTRINO/neutrino.elf` or `hdd:/neutrino/neutrino.elf`.
Until you edit that path, RiptOPL also tries the other folder/file spellings the old picker accepted,
because memory cards and APA partitions are case-sensitive. The other old choices (USB, MX4SIO, MMCE,
exFAT HDD, iLink, Game's Device) load as `<not set>`.

> **Upgrading with Neutrino on the APA HDD:** older builds also searched the APA data home
> automatically for games on other devices. That search is gone. If Neutrino lives in
> `+OPL/neutrino/` or `__common/OPL/neutrino/` and you use it for USB, MMCE or network games, set
> Neutrino Path to `hdd:/neutrino/neutrino.elf`. HDD games still find it through the Game Device tier.

### Custom paths and cross-device launches

A custom path is allowed to be on a **different backend from the game**. RiptOPL resolves the typed
alias to the live filesystem, activates the required storage stack when it is safe to do so, and keeps
both the game backend and the Neutrino backend alive through the keep-IOP ELF handoff. For example,
RiptOPL may be started from USB, load `neutrino.elf` from `mmce0:`, and launch an APA-HDD game;
the MMCE filesystem is not discarded just because the game itself is on HDD.

Common accepted path families include:

| Meaning | Accepted examples |
|---|---|
| USB | `usb:/...`, `usb0:/...` |
| Internal exFAT HDD | `ata:/...`, `ata0:/...` |
| MX4SIO | `mx4:/...`, `mx4sio:/...`, `massX:/...` |
| iLink | `ilink:/...` |
| A mounted BDM slot | `mass:/...` (every mounted slot), `mass0:/...` (that one slot) |
| MMCE | `mmce:/...`, `mmce0:/...`, `mmce1:/...` |
| Memory card | `mc:/...`, `mc?:/...`, `mc0:/...`, `mc1:/...` |
| SMB filesystem | `smb:/...` |
| UDPFS filesystem | `udpfs:/...` |
| UDPFS disk / UDPBD disk | `udpfsd:/...`, `udpfsbd:/...`, `udpbd:/...` |
| APA HDD / selected OPL data home | `hdd:/...`, `hdd0:/...` |
| Mounted APA/PFS filesystem | `pfs:/...`, `pfs0:/...` |
| Internal ROM | `rom:/...`, `rom0:/...` |

BDM paths are resolved against the devices that are mounted **now**:

- `massN:` means that exact slot and nothing else, and nothing is loaded for it. Slot numbers
  follow the order devices mounted in, so a typed alias is the steadier spelling.
- `mass:` searches every mounted slot.
- A typed alias (`usb:`, `ata:`, `mx4sio:`, `ilink:` and the other spellings above) searches every
  mounted device of that family. The family comes from each device's **driver**, not from the
  spelling, so an ATA-backed slot counts as ATA. Only when no device of that family is mounted does
  RiptOPL load that one driver and wait briefly for a device: 2 s, or 5 s for the internal HDD. A
  device that is present but lacks the file costs no wait, and no other family is ever loaded.

A network path (`smb:`, `udpfs:`, `udpbd:`...) starts its network stack when no other network
protocol is running yet. The PS2 has one network adapter, so the other protocols stay unavailable
until you reboot.

For an **APA HDL game**, the automatic Game Device tier means the selected OPL data home already
mounted on `pfs0:` (`+OPL` root or `__common/OPL/`). The semantic `hdd:/...` / `hdd0:/...`
alias also resolves only through that already-selected live APA data home; it never mounts an
arbitrary partition. Explicit nonzero `hddN:` units fail closed rather than being silently
redirected to `hdd0:`. A custom `pfs0:` path addresses the currently mounted PFS filesystem
directly.

> **HTTP URLs are not direct ELF filesystem paths in the current HTTP backend.** HTTP games are
> streamed by the in-game HTTP driver; RiptOPL does not have an `http:` ioman filesystem from which
> `sysLoadELFKeepIOP` can open `neutrino.elf`. An `http://...` Neutrino Path therefore cannot be
> used as the custom ELF tier and falls through to Game Device → memory card rather than pretending
> the URL is locally openable.

### MMCE GameID

A custom Neutrino path on the MMCE **mass-storage surface** (`mmceN:`) remains available when MMCE
switches its emulated memory-card GameID, so a cross-device HDD/USB game can still use MMCE-hosted
Neutrino while receiving its per-game card switch.

Putting Neutrino on the emulated `mcN:` surface of the same MMCE slot is fundamentally different:
the GameID operation replaces that memory-card view. The existing safety guard remains for that
specific collision; use `mmceN:` for Neutrino when MMCE GameID switching is required.

The on-screen row is only a preview. Selecting it opens the full-size path editor, so valid long
paths are no longer limited to 31 characters.


## 2. Pick the core per game

1. Highlight a game, press **Triangle** and choose **Game Settings**.
2. Set **Loader Core** to one of:
   - **`<OPL>`** — OPL's built-in core (default).
   - **`Neutrino`** — chain to the external `neutrino.elf`.
3. Save. The choice is stored per title (`$CoreLoader` in the game's `.cfg`).

### Where Neutrino works

| Source | Neutrino? | VMC under Neutrino? |
|---|---|---|
| USB / MX4SIO / internal ATA (BDM) | ✅ | ✅ `-mcN=massN:…VMC/<name>.bin` |
| iLink / IEEE 1394 (**FAT PS2 models only**) | ⚠️ supported and wired; the post-2692 build adds quick boot for RiptOPL's inherited-stack handoff, pending hardware retest | ⚠️ `-mcN=massN:…VMC/<name>.bin` is emitted; the overall iLink launch is pending retest |
| Internal HDD (APA → HDL) | ✅ | ❌ **games boot, VMC is dropped with a warning** — Neutrino has no APA/pfs backing store to open the `.bin` from (NHDDL's HDL backend has the same no-VMC rule). The OPL core honors the same VMC normally. |
| MMCE | ✅ | ✅ `-mcN=mmceN:/…VMC/<name>.bin` |
| UDPFS (network boot — Files or Image) | ✅ **default** for Files and Image — Neutrino unless the game's Loader Core is `<OPL>` (see §4). On `<OPL>`, Files reads the ISO through the in-game `udpfs_fhi` module and keeps VMCs on the server (`udpfs_mcemu`); **not tested on hardware** | ✅ `-mcN=udpfs:/VMC/<name>.bin` — the PC server must **not** run read-only, or saves fail. Same rule on `<OPL>`: a VMC the server will not open read-write offers the usual skip prompt |
| UDPBD (network boot — served disk image) | ✅ **default** — Neutrino unless the game's Loader Core is `<OPL>` (see §4). Hardware-confirmed 2026-09-26: Kingdom Hearts on PS2-Servers, with every Neutrino setting at its default (neutrino.elf found inside the served image, no per-game filesystem or args) | ⚠️ `-mcN=massN:…VMC/<name>.bin` is emitted; not yet tested on hardware |
| SMB / ETH | ⚠️ **experimental, needs a Neutrino build with SMB support** — **Default** follows the global **Loader Core**, with per-game **Neutrino** / **<OPL>** overrides. See [SMB through Neutrino](#smb-through-neutrino-experimental). **Not tested on hardware** | ❌ the SMB driver is read-only: a game with a VMC launches with `<OPL>` and a warning |
| USB Extreme split images (`.ul`) | ❌ (falls back to `<OPL>`) | n/a |
| Compressed ISO (`.zso`) | ❌ (falls back to `<OPL>`) | n/a |

> **Upstream rates iLink lowest of every backend.** Neutrino's own backend table lists iLink /
> IEEE1394 at a device-compatibility score of **10**, against 80 for USB, 60 for MX4SIO and 100 for
> MMCE, ATA, UDPBD and UDPFS -- and restricts it to **FAT PS2 models**. So a passing `-qb` retest is
> necessary but may not be sufficient: some iLink enclosures are expected to fail upstream too. Use
> the isolation checks below rather than assuming any single fix makes iLink universally work.

> **i.LINK after an IOP reset (#1018).** The i.LINK driver never logs out of the drive, so after
> every IOP reset the drive still holds the old exclusive login for its reconnect hold (at least
> 1 s) and refuses the new driver. The stock driver stopped asking after about 0.8 s and never asked
> again, so every core that resets the IOP lost the drive: native OPL got as far as the PS2 logo,
> Neutrino and POPSTARTER did not start, and only Ember (which keeps the IOP) booted. RiptOPL's own
> build keeps asking for up to 5 s, waits for the drive to become ready, and only offers it once it
> is. It is used by the native core and shipped in the bundled Neutrino, and POPSTARTER's i.LINK
> driver pair has the same change (see [PS1/VCD](VCD.md)). Not yet confirmed on hardware.

Unsupported cases fall back to the `<OPL>` core automatically with an on-screen warning.

> **PS1 games are a separate path.** PlayStation 1 titles (`*.VCD`, shown according to the shared
> **PS2/PS1 Game Display** setting) always boot through **POPSTARTER.ELF** — never OPL's core and never Neutrino
> — so the per-game Loader Core selector is locked/inert for them. See **[VCD.md](VCD.md)**.

### SMB through Neutrino (experimental)

Neutrino nightly includes the SMB backend merged on 2026-10-31 in
[ps2max32/neutrino PR #236](https://github.com/ps2max32/neutrino/pull/236) by
[Ronnie Sahlberg (sahlberg)](https://github.com/sahlberg). It uses his
[usmb2](https://github.com/sahlberg/usmb2), a minimal SMB client (dialect 3.0 only) with its own small TCP/IP stack:
`smb_ioman.irx` reads the game in Neutrino's loader and `smb_fhi.irx` reads it in the game. Install the
**whole latest nightly folder**, including `config/bsd-smb.toml` and both SMB modules. Release kits
fetch upstream's `latest` nightly at packaging time. An older installed folder without those files
falls back to `<OPL>` with a warning. The RA kit uses the pinned ORBIT runtime; it needs its own SMB
backend update before this path is available there. **Not tested on hardware.**

How a game gets there:

1. Set the global **Loader Core** to **Neutrino** and leave the game on **Default**, or select
   **Neutrino** for this game (Game Settings → Compatibility). An explicit **<OPL>** choice stays
   on the native core. Favourites use the same rule as the original SMB row.
2. At launch, the PS2's address, mask and gateway (the static ones, or the DHCP lease the menu got),
   the server's address (a NetBIOS name is looked up first), the user, the password and the share are
   written into every module argument in `<neutrino folder>/config/bsd-smb.toml`, because that file
   is the only place Neutrino reads them from. The file is rewritten only when a value changed.
3. Neutrino starts with `-bsd=smb -dvd=smb:<SMB prefix>/DVD/<name>.iso`, after its own IOP reset, so
   the menu's SMB session is closed first and Neutrino logs in with its own client.

Each of these keeps the game on `<OPL>`, with a warning saying why:

| Limit | Why |
|---|---|
| SMB port is not **445** | usmb2 always dials 445. Use PS2-Servers' **SMBv3** card on 445 (its normal default is 1445); SMBv1 and the SMBv2 card cannot negotiate this backend |
| A VMC is set for the game | the driver is read-only, so it cannot write the card |
| `.zso` or USB Extreme (`ul.*`) images | Neutrino reads one plain ISO |
| neutrino.elf only on the SMB share | Neutrino loads its modules after the share is closed; keep it on a memory card or USB |
| User or password over 31 characters, share over 63, or path on the share over 127 | the driver's own limits |
| `bsd-smb.toml` missing, read-only or not in the stock shape | the settings could not be handed over |

The server must offer the **SMB 3.0** dialect (usmb2 asks for no other) with NTLM login, and no signing or encryption. Use ASCII usernames and passwords of at most 31 characters, because usmb2 hashes password bytes rather than decoding UTF-8. OPL's **SMB Version** setting does not apply to this path. RetroAchievements are not
carried on this path yet. `bsd-smb.toml` holds the SMB password in plain text, like
`conf_network.cfg` already does.

## 3. Launch arguments

OPL always builds the **mandatory** Neutrino arguments for you from the game and its
settings:

| Auto argument | When |
|---|---|
| `-bsd=<usb\|ilink\|mx4sio\|ata\|mmce\|udpfs\|udpfsbd\|udpbd\|smb>` | always (the storage backend). APA HDD maps to `ata` (+ `-bsdfs=hdl`), so no separate `apa` token is ever emitted. OPL emits this unconditionally for every backend, including `udpfs` — nightly Neutrino builds that auto-detect the backend simply ignore the explicit token, so there is no version split on OPL's side |
| `-bsdfs=hdl` | internal HDD (APA) only |
| `-bsdfs=<exfat\|hdl\|bd>` | only if the per-game **Neutrino Filesystem** picker (Compatibility screen) is set off Auto; block-backed devices only (never mmce/udpfs — no filesystem layer there). `hdl`/`bd` also reshape `-dvd` to `hdl:`/`bdfs:`. A hand-typed `-bsdfs=` in the args wins over the picker (per-game args over global ones, last one wins) and reshapes `-dvd` the same way; a hand-typed `-dvd=` wins when forwarded; an over-budget interactive launch is refused. `bd` names the drive as `<driver><N>p0` (a second USB stick is `usb1p0`), using the device number the drive reported; if it never reported one, the launch is refused while the menu is still up, not guessed as device 0 -- whether `bd` came from the picker or was typed, and even beside a typed `-dvd=`. ATA is exempt (one device, always 0) |
| `-dvd=<path>` / `-dvd=hdl:<partition>` | always (the game image/partition) |
| `-qb` | USB, iLink, UDPBD and both UDPFS legs (`udpfs`/`udpfsbd`), the same set NHDDL uses (every mode except HDL). RiptOPL's no-reset ELF bridge deliberately preserves the already-mounted BDM/UDPFS environment; quick boot makes Neutrino enter its load environment without resetting that inherited stack away. For UDPFS an IOP reset also triggers a secondary DISCOVERY that collides with active server streams. Without it, UDPBD reconnected on its own after the reset, read the image's partition table and never reached the game. A user-supplied active `-qb` is never duplicated |
| `-gc=<modes>` | only if the game has OPL compatibility modes set |
| `-dbc` | only if **Debug Colors** is enabled |
| `-logo` | only if **PS2 Logo** is enabled — and never on mmce or the UDPFS legs: rom0:PS2LOGO's extra IOP reboot drops the resident backend stack (issue #56 class), so the global toggle is suppressed there. A hand-typed `-logo` in the global/per-game args still passes through |
| `-gsm=<mode>[:<comp>]` | only if a **Neutrino Video** mode resolves for the game (per-game picker, or the global **Settings → Game Launching → Neutrino Video** default when the per-game picker is "Default"). The `:<comp>` half is appended only when a **Neutrino GSM Compatibility** type is set — it is never emitted on its own |

> **Revision 2692 iLink result:** Neutrino failed on an SCPH-39001 from iLink in all four SDK
> flavours. That build emitted the documented `-bsd=ilink` token but, unlike its USB handoff, did not
> emit `-qb`. Because RiptOPL's bridge intentionally preserves the mounted iLink environment and
> Neutrino documents `-qb` as direct entry into its load environment, that omission is a
> source-confirmed handoff mismatch consistent with the observed reset-boundary symptom. The
> post-2692 change corrects the mismatch; only a new hardware pass can establish whether it was the
> complete cause, so this remains **pending retest** rather than being documented as proven.

On top of those, you can pass **extra Neutrino flags**
in two places. Both are **appended after** the auto-built arguments; **global first, then
per-game**, so a game can extend the global set.

### Global default args — applies to every Neutrino launch

**Game Launching → Neutrino Defaults → Advanced Arguments** (config key `neutrino_args` in
`settings_riptopl.cfg`).

### Per-game args — applies to one title

**Triangle → Game Settings → Neutrino Launch Args** (config key
`$NeutrinoArgs` in the game's `.cfg`).

Both rows are **buttons** that open the same structured sub-screen rather than one raw text
field: **Quick Boot** (`-qb`), **Debug Colors** (`-dbc`), **PS2 Logo** (`-logo`), **Working Dir**
(`-cwd`), **Config** (`-cfg`), **Boot ELF** (`-elf`), `-ata0`, `-ata0id`, `-ata1`, plus a
free-text **Extra** field for everything else. OPL reassembles the fields in the order Neutrino
accepts, with the Extra / `--b` tail last. Select any text field to edit its full value with the
on-screen keyboard; the row displays a short preview. The complete assembled argument string must
fit its 255-character saved limit, and the editor refuses to save an overlong result instead of
silently truncating it. At launch, OPL composes the full global, per-game, and automatic arguments
and checks the 14-entry / 256-byte ExecPS2 budget before leaving the menu. If either limit is
exceeded, a manual launch shows a warning and stays in the menu so no requested argument is
silently lost. HDD autolaunch falls back to the native core, as it does for other Neutrino
preflight failures.

A flag that has its own row is **moved into that row** when you save: type `-logo` into Extra and,
after saving, Extra no longer shows it but the **PS2 Logo** row is on. It is still sent, exactly
once. To check what a launch really passes, use **Show Launch Arguments** (below).

Quick Boot means **enter Neutrino's load environment directly**; it is not merely a boot-screen
toggle. RiptOPL supplies it automatically for USB, iLink, and UDPFS handoffs, so enabling the field
yourself on those devices changes nothing and does not add a duplicate.

The stored format is unchanged — a space-separated string, e.g.:

```
-cfg=custom -qb
```

The **Extra Args** field accepts Neutrino flags not given their own row, including `-bsdfs`,
`-mc0`/`-mc1`, `-gc`, and `--b` for an ELF's own arguments. RiptOPL normally derives the game
device (`-bsd`) and ISO (`-dvd`) and provides VMC, compatibility, and video controls elsewhere in
the GUI. Overrides of those boot-critical values are expert settings: the chosen backend and image
path still have to agree, and a missing VMC file can prevent boot.

| Upstream option | On-console control (global and per-game where applicable) |
|---|---|
| `-bsd`, `-dvd` | Derived from the selected game source and image; an override can be entered in either Extra Args field. |
| `-bsdfs` | Per-game **Neutrino Filesystem** picker, or either Extra Args field for a global/default or a custom value. |
| `-gsm` | Global **Neutrino Video** and **Neutrino GSM Compatibility** defaults; per-game pickers override them. |
| `-gc` | Per-game compatibility switches; either Extra Args field can also carry a manual value. |
| `-mc0`, `-mc1` | Per-game VMC controls; either Extra Args field can carry a manual path. |
| `-elf`, `-cwd`, `-cfg`, `-ata0`, `-ata0id`, `-ata1`, `-qb`, `-dbc`, `-logo` | Named controls in both Advanced Arguments screens. Automatic `-elf` also has a global toggle. |
| `--b` and ELF arguments | Enter in Extra Args. If both scopes use `--b`, RiptOPL collects the Neutrino options first and passes one combined ELF-argument tail, global then per-game. |

All of these controls are reachable from RiptOPL's GUI. The Extra Args field retains a way to
enter new Neutrino options if upstream adds them before RiptOPL has a named control.

### Automatic `-elf=` (enabled by default)

**Game Launching → Auto Boot ELF (-elf)** controls `neutrino_elf_arg`. It defaults on, making
Neutrino launches also pass
`-elf=cdrom0:\<STARTUP>;1` -- the game's boot-file path -- so Neutrino's per-GameID
`config/<GameID>.toml` compatibility lookup can resolve before its IOP reset. It is only
emitted for retail-shaped startups (`AAAA_NNN.NN`) and never when your own args already carry
an `-elf=`. Turn it off in the GUI if a launch misbehaves. For a single game, the per-game **Boot
ELF** field can supply `auto` (Neutrino's own disc lookup) or a specific ELF path, which suppresses
the generated boot path for that game.

### See the exact launch arguments

**Game Launching → Neutrino Defaults → Show Launch Arguments** (`neutrino_show_args`, off by
default) shows, before every Neutrino launch, the complete argument list Neutrino will receive:
the automatic arguments, the global and per-game ones, and the VMC paths, in order. An argument
that contains a space (a spaced ISO or VMC path) is shown in quotes; it is still one argument.
**Accept** launches; **Back** returns to the menu without launching. The list is the one the
launch itself uses, not a reconstruction, so it settles questions such as whether a per-game
`-logo` made it through. It appears only after the argument budget check passes, and never on an
autolaunch (there is no menu to answer it).

### Video-mode limits

Neutrino's current `-gsm` modes are 240p/288p, 480p/576p, and 1080i x1–x3; the low-resolution
modes follow the game's PAL/NTSC choice. **Off** keeps its native 480i/576i output. Neither
Neutrino's documented CLI nor NHDDL's game-video GUI supplies a force-NTSC-480i option for a PAL
game. NHDDL's `video: ntsc` setting changes **NHDDL's own menu**, not Neutrino's game output.
The upstream loader parses `-gsm=:1` through `:3`, but its EE core does not enable GSM when no
video mode is selected, so field compatibility alone is not an effective substitute.

For the full list of flags Neutrino accepts, see the
[Neutrino documentation](https://github.com/ps2max32/neutrino/blob/master/README.md).

## 4. Network boot — the Network Protocol selector

[RiptOPL](https://github.com/NathanNeurotic/RiptOPL) streams games from a PC over the LAN, chosen with the **Game Sources → Network
Connectivity** row (**Off** / Manual / Auto) plus the **Protocol** selector — **SMB / UDPFS /
UDPBD / HTTP** — shown indented under it and on **Network** (one setting, both places). HTTP uses OPL’s core and has its own [guide](HTTP.md). **UDPFS** is the modern
network-boot protocol ([Rick Gaiser](https://github.com/rickgaiser)'s **UDPRDMA** transport); **UDPBD** is the older SUDPBDv2 protocol,
kept for users still running the `udpbd-server`. Both appear in OPL as their own games list — with
covers and per-game settings — and boot via the external [Neutrino](https://github.com/ps2max32/neutrino) core. **SMB** uses
a mounted SMB file share served by OPL's **own** core (Neutrino only per game, experimental: see below), and it keeps its own address /
port / share / credentials fields plus an **SMB Version** row (**SMBv1** default, or **SMB2**).
SMB2 changes **both** browsing and in-game reading, so the server must speak SMB 2.0.2 or 2.1 for
the whole session; PS2-Servers' SMBv1 card lists no games with it (use its SMBv2 card, Samba or
Windows). Changing the version while an SMB driver is already loaded offers the usual restart. If
the SMB2 driver cannot load, browsing falls back to SMBv1.

| Choice | Wire protocol | On the PS2 | Core | PC server |
|---|---|---|---|---|
| **Network Connectivity: Off** | — | no network device (default) | — | — |
| **SMB** | SMBv1 (default) or SMB2 on OPL's core (**Network → SMB Version**); SMB 3.0 on port 445 (Neutrino core) | a mounted file share | OPL's *own* core; Neutrino per game (experimental) | [PS2 Servers](https://github.com/NathanNeurotic/PS2-Servers) (recommended: SMBv1 or SMBv2 card for OPL, SMBv3 card for Neutrino) / Samba |
| **UDPFS** | UDPRDMA | a games source served over UDP (see **UDPFS Access** below) | Files and Image: Neutrino by default, `<OPL>` per game | [PS2 Servers](https://github.com/NathanNeurotic/PS2-Servers) (recommended, PC) / [udpfs-server](https://github.com/YouKnow-sys/udpfs-server) (Android) / [`udpfsd`](https://github.com/pcm720/udpfsd) |
| **UDPBD** | SUDPBDv2 | a served disk image mounted as `massN:` | Neutrino by default, `<OPL>` per game | [PS2 Servers](https://github.com/NathanNeurotic/PS2-Servers) (recommended) / [`udpbd-server`](https://github.com/israpps/udpbd-server) |
| **HTTP** | HTTP byte ranges | a `games.csv` catalog and ISO streams | OPL's own core | [Docmine17's server](https://github.com/Docmine17/Open-PS2-Loader-HTTP) or a server meeting the [HTTP profile](HTTP.md) |

> **SMB2 means SMB 2.0.2 and 2.1.** OPL's own core logs on with NTLMv2 and signs its requests when
> the server requires signing (Windows 11 24H2 does by default). It does not offer SMB 3.x, so a
> server set to SMB 3 only is not reached (browsing it fails). Use PS2-Servers' **SMBv1**
> card (or Samba with `min protocol = NT1`) with **SMBv1**, or its **SMBv2** card with **SMB2**;
> Neutrino's experimental SMB path needs the **SMBv3** card on port 445 instead.

Because the PS2 has a **single** network adapter, only ONE of these is active per session — the
selector is exclusive *by construction* (the old separate ETH start-mode + "Network Boot" toggle +
"Net Boot Protocol" picker, and their live interlock, are all gone). Local devices (USB / internal
HDD / MMCE) are independent and browse alongside whichever network protocol you pick.

> **UDPBD vs UDPFS — pick by your PC server.** They are **wire-incompatible**: UDPBD speaks SUDPBDv2
> (port `0xBDBD`, `udpbd-server`), UDPFS speaks UDPRDMA (port `0xF5F6`, `udpfsd`). If you already run
> the old `udpbd-server`, select **UDPBD** and nothing else changes. If you're setting up fresh, prefer
> **UDPFS** (it serves loose ISOs as well as disk images). A config saved as
> UDPBD stays UDPBD: RiptOPL never silently migrates you off it.

### UDPFS Access — Files vs Image

When **UDPFS** is selected, a second sub-setting **"UDPFS Access"** appears with two values — **Files**
(default) and **IMG** (image mode). They are the **same UDPFS protocol** in two shapes: Files is the `udpfs_ioman`
FILESYSTEM (`udpfs:`), Image is the `udpfs_bd` BLOCK device (`massN:`).

| | **Files** (default) | **IMG** |
|---|---|---|
| IOP driver | `udpfs_ioman.irx` → `udpfs:` (filesystem) | `udpfs_bd.irx` → `massN:` (block device) |
| PC serves | a folder containing **`CD/` and `DVD/` subfolders** of ISOs (the standard OPL layout — OPL lists from `<served>/CD` + `<served>/DVD`, NOT from the folder root) | a **FAT/exFAT disk image** |
| Server command | `udpfsd -fsroot <dir>` | `udpfsd -bdpath <image>` |
| Launch | by name (`-dvd=udpfs:<name>`, stock `-bsd=udpfs`) — no `massN:`, no fragment list | mounted like a USB drive (`massN:`, fragment-list launch) |
| Add a game | drop it into the served `CD/` or `DVD/` folder | mount the image, copy, unmount |
| Compression | Server-dependent; RiptOPL must see an `.iso` entry and ISO bytes | — (raw sectors only) |

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

- A **PC-side UDPFS server** on the same LAN, matching the UDPFS Access mode you chose. [RiptOPL](https://github.com/NathanNeurotic/RiptOPL) does
  **not** embed one. Serving from a **phone or tablet** instead of a PC?
  **[udpfs-server](https://github.com/YouKnow-sys/udpfs-server)** by
  **[YouKnow-sys](https://github.com/YouKnow-sys)** is an Android app that shares folders and disk
  images over UDPFS and is found by broadcast, so there is no address to type on the console; it is
  built on **[udpfsd](https://github.com/pcm720/udpfsd)** by **[pcm720](https://github.com/pcm720)**
  and is MIT licensed. On a PC, use **[NathanNeurotic/PS2-Servers](https://github.com/NathanNeurotic/PS2-Servers)**,
  the maintained all-in-one launcher for UDPFS, SMB (v1, v2 and v3), UDPBD and HTTP; release packages include a
  `PS2-Servers.url` shortcut to it. Advanced users can instead run
  **[pcm720/udpfsd](https://github.com/pcm720/udpfsd)** directly. The old standalone `udpbd-server`
  (SUDPBDv2) does **not** work with UDPFS. Layout: **Image** mode's served FAT/exFAT image uses the
  usual OPL folders (`CD`, `DVD`,
  `ART`, `CFG`, …); **Files** mode's served *directory* needs the same `CD/` + `DVD/` subfolders —
  OPL never lists ISOs sitting loose at the served root.
- A **static** PS2 IP. UDPFS/UDPBD have no DHCP client — they use the static address fields from
  **Settings → Network**. When either UDP protocol is selected, RiptOPL locks **IP Address Type** to
  **Static** and enables those address fields. The user's DHCP choice is preserved as the SMB/HTTP
  preference and is restored when switching back, so testing UDP does not silently rewrite normal
  network behavior. If DHCP is that preserved preference, the boot notice reminds you that UDP is
  using the saved static address. SMB's server / port / share / credentials fields hide automatically
  when either UDP protocol is selected.
- You can start the server **after** the console: the UDPFS drivers keep re-discovering in the
  background (both Files and Image), so the games page appears when the server comes up — no reboot.
- When the Neutrino launch cannot start (no `neutrino.elf`, a `.zso` image), UDPFS **Files**, UDPFS
  **Image** and UDPBD all fall back to the OPL core (below). A missing or unwritable bsd toml is the
  exception: that still returns to the menu, as its message says.

### UDPBD and UDPFS Image on the `<OPL>` core

The OPL core can also run games from the UDP block device, that is UDPBD and UDPFS in Image mode
(ported from [YAOPL](https://github.com/belomaxorka/yaopl)). Neutrino stays the default there: a game
launches with Neutrino unless its own **Loader Core** is set to `<OPL>`; the global Game Launching
default does not change that. When the Neutrino launch cannot start (no `neutrino.elf`, a `.zso`
image, too many fragments), the game falls back to the OPL core instead of returning to the menu.
A missing or unwritable bsd toml is the exception: that launch returns to the menu with its message.

On the OPL core:

- The game keeps the network. After the IOP reset OPL reloads the same block driver the menu used
  (`smap_udpbd` for UDPBD; `udpfs_smap`, `udpfs_ministack` and `udpfs_bd` for UDPFS Image) and fakes
  the game's own DEV9 and SMAP modules, as it does for SMB.
- It uses the static PS2 IP from **Settings → Network**, like the menu.
- There is no RetroAchievements telemetry and no in-game UDPTTY or DECI2 output: both need the SMB
  network stack, which cannot share the adapter with the block driver.
- PADEMU, OPL-core cheats and patches, and VMCs work as on USB. A VMC needs a server that is not
  read-only.
- UDPBD reads at most 32 sectors (16 KiB) per request, in the menu and in game (YAOPL `12cc6fb`).
- If the block driver does not start after the reset (for example a bad static IP), the screen
  blinks red and the console stops, instead of hanging on a black screen.

> **Not tested on hardware yet.** Report results with the game, the server and the protocol.

### UDPFS Files on the `<OPL>` core

UDPFS **Files** games can run on the OPL core too. As with Image, Neutrino stays the default: a game
uses the OPL core when its own **Loader Core** is `<OPL>`, or when Neutrino cannot run it (no
`neutrino.elf`, a `.zso` image).

How it works, following Neutrino's own `udpfs_fhi` design:

- The menu opens the game's ISO on the server and keeps it open across the IOP reset. The server keeps
  that open file for the console when the console finds it again, so the game reads the same file.
- In game, OPL loads `udpfs_smap`, `udpfs_ministack` and `udpfs_fhi`. `udpfs_fhi` finds the server
  again and reads 512-byte sectors of the open ISO for OPL's disc driver.
- The game waits up to 30 seconds for the server at start, and after a dropped connection it waits for
  the reconnect and retries a read up to 3 times.
- **VMCs work and saves go to the server.** Each card is opened read-write and kept open the same way.
  If the server will not open a card for writing (a read-only share, or the file is already open
  elsewhere), you get the usual prompt to continue without that VMC. Automatic VMC works here too.
- The same limits as Image apply: no RetroAchievements telemetry and no in-game UDPTTY or DECI2.
- If the PC server is **restarted** while a game runs, the game loses its open files and cannot reopen
  them; restart the game. Neutrino has the same limit.

> **Not tested on hardware yet.** Report results with the game, the server and whether VMCs were on.

> **At launch, Neutrino reads its own IP from a toml, not from OPL.** When a game boots, control hands
> to the external Neutrino, which reads the toml for the active mode — **Files** uses the stock
> `config/bsd-udpfs.toml`; **Image** uses the bundled `config/bsd-udpfsbd.toml`. Both ship hardcoding
> `ip=192.168.1.10`, which historically meant games *listed* fine in OPL but failed to *boot* on any
> other subnet. **RiptOPL now rewrites the active toml's `ip=` to your configured PS2 IP at every UDPFS
> launch**, so no hand-edit is needed; if the toml has been restructured so the `"ip=` token isn't
> found, OPL logs it and leaves the file alone (the old hand-edit contract applies).
>
> **Neutrino on a Memory Card:** before #1010 this rewrite could not shorten a file on `mc0:`/`mc1:` —
> the card's driver keeps a file's old length unless it is recreated — so a shorter IP left the end of
> the old file behind it (a stray `]` or `"]` line). Neutrino could not read the damaged toml and every
> UDPFS game went straight back to the browser. RiptOPL now recreates the file on every rewrite, and
> repairs a toml already damaged this way the next time you launch a game; nothing to delete or copy.
>
> **Files read from a UDPFS share lost their last byte when their size was odd (#1010).** The UDPFS
> network driver never stored the final byte of an odd-length reply, so the file arrived at the right
> size with a stray last byte. RiptOPL now delivers every byte. The same driver is inside Neutrino's
> release modules, so a `neutrino` folder copied from a UDPFS share to a memory card with a file
> manager that uses them can be damaged: Neutrino then stops on a config such as
> `config/i_dev9_hidden.toml` ("bad control char in comment") and every UDPFS game goes back to the
> browser. Copy the `neutrino` folder from the release zip to the card again from a USB drive. In
> RiptOPL itself the lost byte could stop PNG covers on UDPFS from loading.

> **Hardware note:** the UDPRDMA path (both Files and Image) is validated on emulator only so far —
> real-PS2 confirmation is pending.

### When the network game list stays empty

- **Server restarted or connection dropped:** UDPFS reconnects on its own and starts a fresh
  session, so the list returns without rebooting the PS2.
- **Another device using the PS2's IP:** before each discovery the PS2 announces its IP. If another
  device answers for that same address, the server's replies go to it and the list stays empty;
  RiptOPL then shows a notice with the IP and the other device's MAC address. Pick a free PS2 IP in
  **Network Settings** (an address outside your router's DHCP range is safest).
- **RetroAchievements build:** while UDPFS or UDPBD is the selected protocol, RA menu actions (support
  check, achievements browser, link test) report the network as busy instead of starting SMB, which
  would otherwise take the network adapter until the next boot.
- **Network adapter not detected:** if DEV9 fails to start, RiptOPL loads no network driver and
  tries again the next time the page refreshes.

## 5. Core-aware per-game settings

The per-game settings adapt to the **Loader Core** chosen for that title, so you only see
options the selected core actually honors (Neutrino ignores most of OPL's embedded-core
features — see the mapping below).

When a game's core is **Neutrino**:
- **Compatibility screen:** the **Neutrino Launch Args** field is editable, and a **Neutrino
  Video** picker (Off / 240p / 480p / 1080i x1–x3 / Default) appears beside it — it maps to
  Neutrino's `-gsm` (`fp1` / `fp2` / `1080ix1..3`; Off emits nothing) and is the Neutrino-side
  stand-in for the hidden OPL GSM panel. **Default** follows the *global* Neutrino Video setting
  in **Settings** (so you can force e.g. `-gsm=1080ix3` for every Neutrino game at once); an
  explicit per-game value — including **Off** — overrides the global. The picker is the *default*
  source of `-gsm`: a manual `-gsm` typed into **Launch Args** takes precedence (OPL emits only
  one `-gsm`, since Neutrino aborts on a duplicate/malformed value).

  > **1080i x1–x3 remain interlaced output.** These presets change the output mapping, not
  > the game's rendering resolution or frame rate. x3 is not a 1080p mode or a universal
  > recommendation. Start with video forcing Off when diagnosing a launch; see
  > [the scaling explanation](SETUP-QUESTIONS.md#what-do-neutrinos-1080i-x1-x2-and-x3-mean).
  OPL compat **mode 4 (Skip Videos)**, **mode 6 (Disable IGR)** and **mode 8 (Slow Reads)** are greyed —
  they're OPL-core features with **no Neutrino equivalent** (Neutrino has no in-game reset, no
  PSS/BIK video-skip, and no read-rate cap), so OPL never forwards them. Mode 8 is Accurate Reads
  (mode 1) with DVD games read at the CD rate, ~900 KB/s instead of ~2200 KB/s, for titles whose
  streamed audio breaks at the faster rate (#924, Tales of the Abyss). Modes 1/2/3/5 *do* map to `-gc`, and a Neutrino-only
  **mode 7** (greyed under the OPL core — the inverse of 4/6) maps to `-gc=7` (fix games that overrun
  an IOP buffer).
- **Neutrino GSM Compatibility** (Compatibility screen, beside Neutrino Video) — **Off / Type 1
  (GSM/OPL) / Type 2 / Type 3 / Default** — supplies the `:<comp>` half of `-gsm=<mode>:<comp>`,
  a field-flipping fix for shake/tear. The comp half is **never** emitted without a video mode (a
  bare `:<comp>` aborts Neutrino's boot), so the row greys out while the effective video mode is
  Off; **Default** follows the global **Settings** value.
- **GSM, PADEMU, OSD Language** panels are OPL-core-only; opening one shows
  *"not used with the Neutrino core"* instead of editing dead options (use the Neutrino Video
  picker above for video forcing).
- **Cheats** work on both cores (see [Cheats under Neutrino](#cheats-under-neutrino)). Only the
  panel's **PS2RD image** row is greyed: Neutrino takes `.cht` codes but has no cheat-image support.
- **VMC** and **Compatibility** stay available — both are honored under Neutrino. VMC becomes
  discrete `-mc0`/`-mc1` args on **BDM devices (USB/iLink/MX4SIO/exFAT HDD/UDPBD), MMCE and
  UDPFS**; the one exception is **APA HDD**, where no `-mc` args can be emitted (Neutrino has no
  APA/pfs backing store — the game boots and OPL warns that the VMC was dropped). See the VMC
  notes below.
- **UDPFS games** (both Files and Image) have no OPL core backend, so the **Loader Core selector is
  locked to Neutrino** for them (they always launch via Neutrino regardless).

When a game's core is **`<OPL>`** the screen is unchanged from classic OPL, except the Neutrino
Args field and Neutrino Video picker are greyed (never read on the OPL path).

> What Neutrino honors per game: the storage backend + image (`-bsd`/`-dvd`, automatic),
> compat subset (`-gc`), VMC (`-mc0`/`-mc1`), `-logo`, cheats (`-cfg=`, below), and the free-text
> **Neutrino Launch Args** (the catch-all for everything else, with `$`-disable). GSM hacks,
> IGR/IGS, PADEMU, OSD-language and PS2RD cheat images are OPL-embedded-core features with no
> Neutrino equivalent.

### Cheats under Neutrino

Neutrino runs PS2RD cheat codes (upstream commit `0469cc31`). You use the same **Cheat Settings**, the same `CHT/<startup>.cht` (or `CHT/cht.tar`) file, and the same **Select Game Cheats** picker as the OPL core. Selections persist per game across both cores.

At launch, RiptOPL writes the enabled codes to **`riptopl-cheats.toml`** in Neutrino's config directory (`neutrino/config/`, or flat `neutrino/`, or your forwarded `-cwd=`) and appends `-cfg=riptopl-cheats` to the launch arguments. The file is rewritten on each launch with cheats enabled and is safe to delete.

Requirements for cheats to apply under Neutrino:

- **Neutrino runtime version:** Cheats require the post-v1.8.0 development build (`v1.8.0-61-g7be8de2` or newer) bundled in standard RiptOPL rolling-release downloads. Official standalone Neutrino `v1.8.0` predates cheat support in its `ee_core.elf`. If you use an external `v1.8.0` install or the RetroAchievements (RA) edition (which pins ORBIT `v1.0.2` based on `v1.8.0`), codes do not apply.
- **Mastercode (`90xxxxxx`) hook:** Neutrino's PS2RD engine hooks into `SetupThread` through a `90xxxxxx` code. The `.cht` file must contain a valid `90` mastercode. Files with only an `F0xxxxxx` code or raw memory writes (`20xxxxxx`) lack a hook target. In that case, `ee_core` skips hook installation and cheats do not execute.
- **Cheat toggle:** Cheats must be toggled On in Game Settings or Global Settings.
- **User `-cfg` forwarding:** A custom `-cfg=` passed in your Neutrino arguments continues to load. Neutrino keeps the final `-cfg` (RiptOPL's), and RiptOPL chains yours via `depends`.
- **Read-only storage:** If RiptOPL cannot write `riptopl-cheats.toml` (such as a read-only share or full card), it prompts before launching without cheats. Autolaunches proceed without cheats.
- **Launch argument inspection:** Enable **Show Launch Arguments** in Neutrino Defaults to verify that `-cfg=riptopl-cheats` is passed to the runtime.

### VMC under Neutrino — how it actually works

OPL turns the per-game **VMC** settings (`$VMC_0`/`$VMC_1`) into discrete
`-mcN=<device>:…VMC/<name>.bin` arguments — the same `.bin`, in the same `VMC/` folder, that the
OPL core's mcemu uses, so one card serves both cores.

Each slot also has a **Disable VMC N (keep card)** toggle on the Compatibility screen (stored as
`$VMCDisable_0` / `$VMCDisable_1`). It suppresses that slot's `-mc` argument for **Neutrino
launches only** — the card name stays configured and the game sees the real physical card; OPL's
own mcemu ignores the toggle entirely. Dropping the argument also clears that slot from the VMC
slot mask, so the MMCE GameID card-switch re-arms for it, and on APA HDD it silences the
"VMC unsupported under Neutrino" warning.

Rules that follow from Neutrino's design (verified against Neutrino's source, now `ps2max32/neutrino`):

- **The `.bin` must already exist.** Neutrino opens it `O_RDWR` with no create, and **aborts the
  whole boot** (black screen) if it can't. OPL therefore creates/format cards at *config* time
  (the per-game VMC menu, via genvmc — including over UDPFS), and at *launch* verifies each card
  and skips a missing one with a warning rather than handing Neutrino an unopenable path.
- **The VMC must live on the same device as the game.** Neutrino loads exactly one backing-store
  driver per launch and every virtual file (ISO + VMCs) shares it — a VMC on a different device
  than the ISO is structurally unsupported. This is also why APA HDD can't have one: the game
  comes from raw APA (`-bsd=ata -bsdfs=hdl`), and there is no pfs backend for the `.bin`.
- **UDPFS VMCs are writable network files**: the card lives at `VMC/<name>.bin` under the PC
  server's shared folder, and the server must not run in read-only mode or saves fail.
- **Block devices share Neutrino's 64-fragment budget** across ISO + VMCs; OPL pre-counts and
  falls back/aborts with a message when it can't fit (defragment the drive if you see it).
- **Upstream caveats** (Neutrino's `mc_emu`, as of mid-2026): only **port 1 (`-mc0`) is actually
  emulated** — `-mc1` is accepted and opened but the second port's emulation is left inactive —
  and the advertised card geometry is hardcoded (8192 pages ≈ first 4 MB of the image addressed)
  rather than read from the card file. Both are Neutrino-side behaviors, not OPL's; prefer slot 1
  and 8 MB cards for predictable results.

## RetroAchievements edition runtime

Both theme kits in the [dedicated RetroAchievements release](https://github.com/NathanNeurotic/Open-PS2-Loader/releases/tag/rolling-ra) bundle the pinned ORBIT v1.0.2 [Neutrino](https://github.com/ps2max32/neutrino) runtime by Daniel / [danielnuld](https://github.com/danielnuld) (AFL-3.0), based on Neutrino by [Maximus32](https://github.com/rickgaiser) and [xeRAbora](https://github.com/hacan359/xerabora) protocol work by [hacan359](https://github.com/hacan359). Standard kits keep ordinary upstream Neutrino. Copy the complete runtime folder, including its license and ORBIT-RA provenance files, to your chosen supported device. An RA ELF update alone does not install it.

The adapter supports both RA modes (Xerabora, and Caduceus through its engine), watch lists whose direct values fit 1,216 bytes (pointer-chain achievements excluded, as in ORBIT), and writable configuration storage. UDP storage reuses its existing network stack and currently needs static addressing, a saved watch list and a companion profile that already knows the image. Console unlock notices are not supplied by this runtime. See the [RA setup and validation limits](RETROACHIEVEMENTS.md#neutrino-in-the-ra-edition).
