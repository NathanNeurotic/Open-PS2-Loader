# In-Game Reset (IGR)

**In-Game Reset lets you leave a running game and come straight back to RiptOPL — or power the
console off — without touching the console's own Reset button.** It is a controller shortcut that
works from inside the game.

RiptOPL installs a small hook into the running game that watches the controller for a reserved
button combination. When it sees one, it tears the game down and either returns you to the browser
or shuts the console down.

---

## The button combinations

Every combination starts the same way: **hold all four shoulder buttons — L1 + L2 + R1 + R2 —** and
then, while still holding them, press the second half.

| Hold | Then press | Result |
|---|---|---|
| L1 + L2 + R1 + R2 | **Start + Select** | **Reset** — quit the game and return to RiptOPL |
| L1 + L2 + R1 + R2 | **L3 + R3** | **Power off** the console |
| L1 + L2 + R1 + R2 | **Up** | **In-Game Screenshot** — see [Screenshots](#in-game-screenshots-igs) |

L3 and R3 are the analog-stick *clicks*, so the power-off combination needs a DualShock with the
analog light on.

### The console power button

The power button on the front of the console is hooked too, and does not need a controller:

| Power button | Result |
|---|---|
| Press **once** | Power off |
| Press **twice** | Reset — return to RiptOPL |

This is the fallback worth remembering when a game has stopped responding to the pad entirely.

---

## Where a reset takes you

By default a reset returns you to the RiptOPL browser, on the same device page you launched from.

You can send it somewhere else instead with the **IGR Path** setting (*Settings → General*). Point it
at an ELF and that ELF is booted on reset rather than the browser — a common use is to drop straight
back into a different launcher or a homebrew menu. The file must live **on a memory card**
(`mc0:` or `mc1:`); leave the setting blank to return to RiptOPL normally.

If you use MMCE cards, **IGR Bootcard Slot(s)** (*Settings → MMCE*) additionally sends a
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

The **L1+L2+R1+R2 + Up** combination captures the current frame to a bitmap on the memory card, named
like `mc1:/SLUS_012.34_IGS(001).bmp`.

Two conditions gate it, and both catch people out:

1. **GSM must be enabled** for the running game. IGS reads the frame through GSM's view of the video
   hardware, so with GSM off the combination does nothing.
2. **The build must include IGS.** It is compiled out of stock builds — the `Makefile` defaults
   `EXTRA_FEATURES` to `0`, and `IGS` follows it. Official release builds therefore **do not have
   IGS**. Building with `make IGS=1` (or `EXTRA_FEATURES=1`) enables it.

If you are on a release build, the Up combination is inert and that is expected.

---

## Troubleshooting

**Nothing happens when I press the combination.** Check, in order: the game has actually started
(past the early boot logos); the Loader Core is OPL rather than Neutrino; Mode 6 is not set for this
game; and — for the power-off and screenshot combinations specifically — the controller is in analog
mode. Try the console power button as a cross-check: if that resets and the pad combination does not,
the hook is fine and the problem is in the pad half.

**Reset takes me somewhere unexpected.** Check **IGR Path** in *Settings → General*. A stale path
left over from an earlier setup will boot that ELF instead of returning to the browser.

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
