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
| UDPBD (network block device) | ✅ **required** — no OPL core, Neutrino only (see §4) |
| SMB / ETH | ❌ (falls back to `<OPL>`) |
| USB Extreme split images (`.ul`) | ❌ (falls back to `<OPL>`) |
| Compressed ISO (`.zso`) | ❌ (falls back to `<OPL>`) |

Unsupported cases fall back to the `<OPL>` core automatically with an on-screen warning.

## 3. Launch arguments

OPL always builds the **mandatory** Neutrino arguments for you from the game and its
settings:

| Auto argument | When |
|---|---|
| `-bsd=<usb\|ilink\|mx4sio\|ata\|mmce\|udpbd>` | always (the storage backend) |
| `-bsdfs=hdl` | internal HDD (APA) only |
| `-dvd=<path>` / `-dvd=hdl:<partition>` | always (the game image/partition) |
| `-gc=<modes>` | only if the game has OPL compatibility modes set |
| `-dbc` | only if **Debug Colors** is enabled |
| `-logo` | only if **PS2 Logo** is enabled |

On top of those, you can pass **extra Neutrino flags** (e.g. media-type or video tweaks)
in two places. Both are **appended after** the auto-built arguments; **global first, then
per-game**, so a game can extend the global set.

### Global default args — applies to every Neutrino launch

**Settings → General Settings → Neutrino Launch Args** (config key `neutrino_args` in
`conf_riptopl.cfg`).

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

## 4. UDPBD network boot (Neutrino-only)

**UDPBD** streams games from a PC over the LAN as a network *block device* (Rick Gaiser's
[udpbd](https://github.com/rickgaiser/udpbd) protocol). It appears in OPL as its own
**UDPBD Games** list — with covers and per-game settings — exactly like a USB drive, because
to OPL it *is* just another block device (it mounts `massN:`). It has **no built-in OPL core
backend**, so UDPBD games **always launch via Neutrino** (`-bsd=udpbd`); OPL forces the
Neutrino core for them automatically and, if `neutrino.elf` is missing, warns and returns to
the menu (there is no `<OPL>` fallback for UDPBD).

### Requirements

- A PC-side UDPBD server (e.g. `udpbd-server`) on the same LAN, exporting a FAT/exFAT block
  device laid out with the usual OPL folders (`CD`, `DVD`, `ART`, `CFG`, …).
- A **static** PS2 IP. The UDPBD module has no DHCP client and reuses the address from
  **Settings → Network Config**, so set a static IP there. OPL warns you if DHCP is on at the
  moment you enable UDPBD.

### Enable it

1. **Device Settings → UDPBD (Network)** → On. The default is **Off**.
2. UDPBD and the SMB/ETH stack share the single PS2 network adapter, so they are **mutually
   exclusive** — enabling UDPBD requires the Ethernet (SMB) device mode set to **Disabled**.
   The two are interlocked live in the Device Settings page (turning one on greys the other).

UDPBD reuses the IP set in Network Config; there are **no UDPBD-specific network fields**.
