# PADEMU — DualShock 3 and 4 emulation

**PADEMU lets a DualShock 3 or DualShock 4 stand in for a PS2 controller.** The game sees an ordinary
PS2 pad; PADEMU translates for it. Connect over USB or Bluetooth, on either pad port, with optional
vibration and multitap emulation.

PADEMU is the work of **belek666**.

---

## Before you start

**PADEMU is an OPL-core feature.** It is not available under Neutrino — opening the PADEMU screen for
a title whose Loader Core is Neutrino shows *"This setting is not used with the Neutrino core."* If
you need PADEMU for a game, that game has to launch on the OPL core.

PADEMU is compiled in by default (`PADEMU ?= 1`), so stock builds have it.

---

## Setting it up

PADEMU is configured per game: Triangle on a title → **PADEMU Settings**. The first row, **PADEMU
Source**, chooses between **Global** (follow the defaults set in *Settings*) and **Per Game** (this
title's own settings).

| Option | What it does |
|---|---|
| **Pad Emulator** | The master on/off switch for this game. Everything below is greyed out while it is off. |
| **Pad Emulator Mode** | **DualShock3/4 USB** or **DualShock3/4 BT** (Bluetooth). |
| **Emulation** | Enable emulation on the selected pad port. Set this per port. |
| **Vibration** | Vibration for the selected port. Only available once that port's Emulation is on. |
| **Multitap Emulation** | Present a multitap to the game, for titles that support more than two players. |
| **Multitap Emulator On Port** | Which pad port the emulated multitap occupies. Only available with Multitap Emulation on. |
| **Fake DS3 Workaround** | A compatibility shim for counterfeit DualShock 3 units. **Only shown in Bluetooth mode.** |

The port rows are per-port: select the pad port first, then set Emulation and Vibration for it.

---

## USB or Bluetooth

**USB** (`ds34usb`) is the simpler path — plug the controller into one of the console's USB ports.
Start here if you are not sure.

**Bluetooth** (`ds34bt`) needs a compatible USB Bluetooth adapter plugged into the console. The
controller is then paired to that adapter rather than to the console itself.

### Fake DS3 controllers

Counterfeit DualShock 3 units are common, and many of them deviate from the real protocol enough to
fail. **Fake DS3 Workaround** exists for those. It appears only when the mode is set to Bluetooth,
so if you cannot find the option, check the mode first.

If a controller behaves erratically or will not connect at all, trying this toggle is cheap. It will
not help a genuine DualShock 3, which does not need it.

---

## DualSense (DualShock 5)

DS5 over USB is supported in the code, and has been hardware-validated, but it is **off in the
default build** (`DUALSENSE ?= 0`). The entire DS5 path is behind `#ifdef DS5_ENABLE`, so a default
build behaves identically to the build that is already hardware-proven.

**You do not have to build it yourself.** CI produces a ready-made DualSense loader as a separate
named asset for each SDK flavour — look for the `-ds5.ELF` downloads on the release. They are
built best-effort: if that build fails for a given run, the asset is skipped for that run rather than
holding up the release, so it will not always be present.

---

## Troubleshooting

**The PADEMU screen says it is not used with this core.** The game's Loader Core is Neutrino. Change
it to the OPL core, or accept that PADEMU is unavailable for that title.

**The controller does nothing in game.** Check three things in order: **Pad Emulator** is on;
**Emulation** is on *for the port you plugged into*; and the **Mode** matches how you actually
connected (USB vs BT).

**No vibration.** Vibration is per port and only becomes available once that port's Emulation is on.
Confirm the port is right, then that vibration is enabled on it. Note this is separate from the
menu's own **Rumble** setting, which is about the RiptOPL browser rather than the game — see
[CONTROLS.md](CONTROLS.md#rumble).

**A Bluetooth controller will not pair.** Confirm the adapter is one PADEMU supports and is plugged
into the console, then try **Fake DS3 Workaround** if the controller is not a genuine Sony unit.

**Multitap options are greyed out.** Multitap Emulator On Port only becomes available once Multitap
Emulation itself is on.

---

## See also

* [CONTROLS.md](CONTROLS.md) — the menu's own button map and the Rumble setting
* [NEUTRINO.md](NEUTRINO.md) — the core PADEMU does not work under
