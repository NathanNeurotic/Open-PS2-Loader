# In-Game Reset (IGR)

**In-Game Reset lets you leave a running game — or power the console off — without touching the
console's own Reset button.** It is a controller shortcut that works from inside the game.

RiptOPL installs a small hook into the running game that watches the controller for a reserved
button combination. When it sees one, it tears the game down and either leaves for the PS2 browser
(or the ELF set in **IGR Path**) or shuts the console down.

---

## The button combinations

Every combination starts the same way: **hold all four shoulder buttons — L1 + L2 + R1 + R2 —** and
then, while still holding them, press the second half.

| Hold | Then press | Result |
|---|---|---|
| L1 + L2 + R1 + R2 | **Start + Select** | **Reset** — quit the game; see [Where a reset takes you](#where-a-reset-takes-you) |
| L1 + L2 + R1 + R2 | **L3 + R3** | **Power off** the console |
| L1 + L2 + R1 + R2 | **Up** | **In-Game Screenshot** — see [Screenshots](#in-game-screenshots-igs) |

L3 and R3 are the analog-stick *clicks*, so the power-off combination needs a DualShock with the
analog light on.

### The console power button

The power button on the front of the console is hooked too, and does not need a controller:

| Power button | Result |
|---|---|
| Press **once** | Power off |
| Press **twice** | Reset — the same as Start + Select |

The second press has to land within **about a second** — RiptOPL waits ~50 vertical blanks after the
first press to see whether another arrives, then acts on the count.

This is the fallback worth remembering when a game has stopped responding to the pad entirely.

---

## Where a reset takes you

With the **IGR Path** setting (*Settings → General & System*) left blank, a reset exits to the **PS2
browser**, the same place the menu's own **Exit** goes. It does not come back to RiptOPL by itself.

Point IGR Path at an ELF and that ELF is booted on reset instead: another launcher, a homebrew menu,
or RiptOPL itself. To come straight back to RiptOPL, give it RiptOPL's own ELF —
`mc0:/APP_RIPTOPL/RIPTOPL.ELF` if you imported `APP_RIPTOPL.psu` to the first memory card. RiptOPL
then starts fresh. It does not restore what you had selected: **Remember Last Played Game**
(*Settings → General & System*) is a separate setting, off by default, and it is what re-selects the
last game you ran.

The ELF must live **on a memory card** (`mc0:` or `mc1:`) or on a **FAT32 USB drive** (`mass:/…`).
After a reset the console can only reach USB through `USBD.IRX` and `USBHDFSD.IRX` in the memory
card's `SYS-CONF` folder, the files FMCB installs; without them the reset drops to the PS2 browser
instead. If they are missing, RiptOPL offers to copy its own there the first time you launch a game on
the OPL core with a USB IGR Path (Neutrino has no IGR, so its launches never ask). It never replaces
files that are already there. Games started by **Auto Loading** skip the offer, because nobody is at
the menu to answer it: launch a game on the OPL core from the menu once, or copy the two files
yourself, before relying on a USB IGR Path there.

If you use MMCE cards, **IGR Bootcard Slot(s)** (*Settings → Game Sources → MMCE Settings*) additionally sends a
"switch to bootcard" command to slot 0, slot 1, both, or neither as the reset happens, so the card is
already back on its boot image by the time the next thing loads.

---

## When IGR is not available

IGR is not universal. It is worth knowing the three cases where the combinations will do nothing, so
you do not spend time hunting a fault that is not there.

**Before the game opens a controller.** The hook attaches by patching the game's own
`scePadPortOpen` / `scePad2CreateSocket` call. Until the game asks for a pad, there is nothing
hooked — so IGR does not respond during very early boot logos on some titles. The console power
button still works.

**When the game is incompatible.** A few games handle input in a way the hook disturbs. Per-game
compatibility **Mode 6 — Disable IGR** turns the hook off for that title. If a game misbehaves in a
way that started when you launched it through RiptOPL, this is the mode to try — at the cost of
losing IGR for that game.

**Under the Neutrino core.** Neutrino has no IGR at all. This is not a RiptOPL limitation but a
property of that loader, and it is why Mode 6 is greyed out whenever the Loader Core is set to
Neutrino — there is no hook there to disable. To leave a Neutrino-launched game, use the console's
power or reset button.

PS1 titles are a separate case again: they run under POPSTARTER or Ember, each of which has its own
independent IGR behaviour built into that binary. RiptOPL's hook is not involved. See
[VCD.md](VCD.md).

---

## In-Game Screenshots (IGS)

The **L1+L2+R1+R2 + Up** combination captures the current frame to a bitmap on **memory card slot 1**,
named from the game's ID with a zero-padded sequence number starting at 001 — for example
`mc1:/SLUS_012.34_GS(001).bmp`. The number increments to a maximum of 255 per game.

Two conditions gate it, and both catch people out:

1. **GSM must be enabled** for the running game. The capture is gated on the game's GSM setting, so
   with GSM off the combination does nothing at all.
2. **The build must include IGS.** The `Makefile` defaults `EXTRA_FEATURES` to `0` and `IGS`
   follows it, and the **main release loader is built with that default** — so the loader most
   people run has no IGS and the Up combination is simply inert.

You do not have to build it yourself. The rolling release also publishes an IGS-enabled loader:
inside `RIPTOPL-VARIANTS-*.zip`, the variants named `-extra1` are built with `EXTRA_FEATURES=1`,
which turns IGS on. They come in `pademu0`/`pademu1` and optional `-ds5` flavours. Building from
source with `make IGS=1` (or `EXTRA_FEATURES=1`) works too.

One combination is not available: the **RetroAchievements** loader (`RIPTOPL-RetroAchievements-*.zip`) is
deliberately built without `EXTRA_FEATURES`, because GSM 1080p plus IGS and RA cannot both fit in
the `ram84` region — you can have achievements or in-game screenshots, not both.

---

## Troubleshooting

**Nothing happens when I press the combination.** Check, in order: the game has actually started
(past the early boot logos); the Loader Core is OPL rather than Neutrino; Mode 6 is not set for this
game; and — for the power-off combination specifically — the controller is in analog mode, since L3
and R3 are the stick clicks. The screenshot combination uses **Up**, so it needs no analog mode.

Try the console power button as a cross-check: if that resets and the pad combination does not, the
hook is fine and the problem is in the pad half.

**Reset takes me somewhere unexpected.** Check **IGR Path** in *Settings → General & System*. A stale path
left over from an earlier setup will boot that ELF instead of exiting to the PS2 browser. A USB path that
lands in the PS2 browser anyway is missing its memory-card drivers — see
[Where a reset takes you](#where-a-reset-takes-you).

**The game resets on its own during play.** A game that uses all four shoulders plus Start or Select
in normal play can trigger IGR by accident. Set **Mode 6 — Disable IGR** for that title.

---

## Where this lives in the source

| File | Role |
|---|---|
| `ee_core/src/padhook.c` | The hook itself: pad pattern matching, the VBLANK interrupt handler, combo dispatch, the IGR thread |
| `ee_core/include/padhook.h` | The combo constants (`IGR_COMBO_R1_L1_R2_L2`, `IGR_COMBO_START_SELECT`, `IGR_COMBO_R3_L3`, `IGR_COMBO_UP`) |
| `ee_core/src/cd_igr_rpc.c` | IOP-side reset RPC |
| `ee_core/src/igs_api.c` | Screenshot capture and BMP writing |
| `include/iosupport.h` | `COMPAT_MODE_6` — the Disable IGR flag |

## See also

* [CONTROLS.md](CONTROLS.md) — the full button reference
* [NEUTRINO.md](NEUTRINO.md) — the alternative core, which has no IGR
* [VCD.md](VCD.md) — PS1 titles and their own IGR behaviour
