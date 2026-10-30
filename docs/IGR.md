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

The second press has to land within **about a second** — RiptOPL waits ~50 frames after the
first press to see whether another arrives, then acts on the count. A single
hardware power-off status held across several frames counts as **one** press,
not a spurious double press.

**A physical tap is not guaranteed on every console and transport.** On
hardware with an active DEV9/network adapter or HDD, the front-panel event
passes through the console's Mechacon/CDVD handling. If the event is missed,
controller IGR can still work: the two have different input paths, and
reset and power-off take different shutdown paths. This is a compatibility
limit, not a reason to reset DEV9 or power-cycle the drive during a game.
If a short tap is ignored, the console's normal press-and-hold standby
action is the hardware fallback; avoid cutting AC power during disk activity.

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

This limits the **return ELF's location**, not the game's source. OPL-core PS2
games on an internal exFAT HDD use the same IGR hook as other OPL transports.
The reset loader does not restore an internal exFAT filesystem for an `ata:`
return path. Use the PS2 browser or a memory-card ELF to isolate a failing
return target from a combination that is not detected.

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
button is independent of the pad buffer, subject to the hardware limits above.

**When the game is incompatible.** A few games handle input in a way the hook disturbs. Per-game
compatibility **Mode 6 — Disable IGR** turns the hook off for that title. If a game misbehaves in a
way that started when you launched it through RiptOPL, this is the mode to try — at the cost of
losing IGR for that game.

**Fatal Fury: Battle Archives Volume 2** is the known example. IGR watches the pad from a **VBLANK
interrupt handler**, and registering one black-screens that game whatever the handler does. The USA
release (SLUS_217.23) gets Mode 6 by default; set it yourself for other regions. On the **RetroAchievements** loader with achievements active, Mode 6 still registers
a VBLANK handler for the achievement snapshots, so play that game on the standard loader instead.

**Under the Neutrino core.** Neutrino has no IGR at all. This is not a RiptOPL limitation but a
property of that loader, and it is why Mode 6 is greyed out whenever the Loader Core is set to
Neutrino — there is no hook there to disable. To leave a Neutrino-launched game, use the console's
power or reset button.

PS1 titles do not use RiptOPL's PS2 IGR hook. POPSTARTER supplies its own reset
behavior; **Ember does not provide IGR**. See [VCD.md](VCD.md).

---

## How IGR watches the pad

Once a frame, a VBLANK interrupt handler reads the controller and the power button. When it sees a
request it stops the game's DMA and the GS, suspends every game thread, and wakes the IGR thread,
which does the rest of the shutdown. Because this runs in interrupt context, a game that keeps the
EE busy cannot hold it off. This is how OPL has always done it. The **RetroAchievements** loader
uses the same handler and also takes its per-frame achievement snapshots there. Under Mode 6, RA
installs a snapshot-only handler when telemetry is active, with no IGR thread or pad hooks:
achievements continue, but client-triggered reset is unavailable.

Between October 5 and October 19, 2026, standard builds tried two replacements that avoided VBLANK,
and both failed on real consoles
([issue #984](https://github.com/NathanNeurotic/Open-PS2-Loader/issues/984)):

* **A low-priority polling thread** woken by an EE timer (official OPL #1762). A game that always
  has a thread ready to run never lets that thread run, so IGR did nothing in GTA San Andreas, Need
  for Speed Most Wanted, PES and others.
* **Sampling inside the EE timer callback.** In games the controller combination and the power
  button both stopped answering, Resident Evil 4 included.

Builds from that window can therefore fail where current builds work. If IGR stops responding in a
game that used to answer it, report the title and the exact build.

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

## The in-game menu (beta)

**Settings → Game Launching → In-Game Menu (Beta)**, off by default. With it on, **L1 + L2 + R1 + R2 +
Start + Select** no longer leaves the game at once: it **pauses** the game under a small panel.

| Item | What it does |
|---|---|
| **Resume** | Back to the game, exactly where it stopped. Start or the back button also resume. |
| **Cheats** | Only when the game was started with cheats on. Every cheat of the game's `.cht` file, **ON** or **OFF**; the confirm button switches one, the back button returns. Changes apply when you resume. |
| **Achievements** | RetroAchievements builds only. How many of the game's achievements you have unlocked and how many are left. The confirm button opens **Left To Hunt**: the locked ones one at a time, with points and how to earn each; Up and Down page through them. |
| **Exit Game** | What the combo always did: leave for the **IGR Path** (or the PS2 browser). Press confirm twice. |
| **Power Off** | Turns the console off. Press confirm twice. |

Up and Down move; the confirm and back buttons are the ones OPL's own menus use.
The console's power button still works while the menu is open: once powers off, twice exits.

**Cheats, live.** The game's `.cht` file is read when the game starts (*Cheats* on in the game's
settings, as before); every cheat comes along, ticked or not, and the menu turns them on and off while
you play, without a restart. Things to know:

* **OFF stops a cheat writing; it does not undo it.** A value it wrote (health, money) stays until the
  game changes it, and a cheat that patches the game's code (widescreen, "always run") stays patched
  until the game reloads that code.
* The **master code** (the `9…` hook line) is always in, ticked or not: the cheat engine can only plant
  its hook when the game starts, so a cheat that is nothing but a hook cannot be switched.
* The ticked cheats must fit the engine's 250 codes. A cheat that would not fit stays OFF and the page
  says *FULL: TURN ONE OFF FIRST*. The page lists up to 64 cheats (512 codes in all).
* *The cheat engine has not run in this game yet* means the master code's hook never matched: no cheat
  is being applied, ticked or not. Check the master code for your version of the game.
* *Not applied yet* means the engine was in the middle of applying codes when you paused; resume and
  open the menu again.

**Achievements, Left To Hunt.** RetroAchievements builds, *xeRAbora* mode. The menu cannot ask the PC while
the game is paused, so it shows the list as the loader last saw it: open the game's achievements in the
loader (*View achievements* in the game's menu) and the set it reads from the xeRAbora PC is also saved as
`RA/<game ID>.ach` beside the game's watch list. The next launch of that game takes it into the menu.

* Open the page again after a session to bring the list up to date. Unlocks earned since are not in it.
* No list yet: the page says *No list for this game* and how to get one. Caduceus mode, HDLoader (APA)
  games and PS1 games have no image the page can read, so they have no list either.
* Up to 8 KB of descriptions travel with the game (several hundred achievements); a set bigger than that
  shows the counts without *Left To Hunt*. Titles and descriptions are shown in capitals, wrapped to the panel.

**Where it works.** Games on the **OPL core** only (USB, MX4SIO, iLink, exFAT and APA HDD, SMB, MMCE,
UDPBD/UDPFS). Neutrino has no IGR at all, and PS1 games use POPStarter's or Ember's own. The menu draws
into the picture the game is showing, which it finds through the same GS write breakpoint GSM uses:

* **PCSX2 cannot show it** (it has no data breakpoints), so there the combo leaves the game as before.
* A game that shows its picture in a way the menu cannot see, or in a format it cannot draw, also
  leaves at once, as before. Nothing is lost compared with the menu off.
* **The game goes quiet while the menu is open** and its sound goes on where it stopped when you resume:
  a small IOP module (`igrmbox.irx`) turns the SPU2's volume down and holds every voice. It cannot hold a
  game that streams PCM straight to the sound cores; that stream keeps running, silently, while you are paused.
* **Resume gives back the exact picture.** The pixels under the panel are kept in IOP memory while the menu
  is open and drawn back before the game runs again, so a still screen does not keep the panel. A game
  that leaves the IOP too little free memory (up to 315 KB for a 640-wide picture) gets the old behaviour:
  the panel stays until the game draws over it. If the IOP has no room for `igrmbox.irx` itself, the
  menu still opens, but with neither the silent pause nor the exact picture.
* With *In-Game Menu* off, `igrmbox.irx` is not packed or loaded at all, so a game sees exactly the modules
  and memory it always did.
* In the **RetroAchievements** builds (`RETROACHIEVEMENTS=1`) `ee_core` has no room for the menu beside RA,
  so there the menu is a small program of its own, `igrovl.elf`, that the loader copies into the top 16 KB
  of the module area (0xCC000 to 0xD0000) only for a launch with *In-Game Menu* on. With the menu off
  nothing is copied and the module area is what it always was. A game whose modules are moved elsewhere
  (`mod_storage_location_list`), or run past 0xCC000, gets the plain combo in those builds.
* Not in the IGS (`EXTRA_FEATURES=1`) and freeze-report (`INGAMEDIAG=1`) builds: `ee_core` has no room
  for both. Those keep the plain combo and have no *In-Game Menu* row. `make IGR_MENU=0` leaves it out of
  a standard build too.
* The CHEATS page needs a game whose modules sit at the usual address; a few games moved elsewhere
  (`mod_storage_location_list`) get the menu without it, and their cheats run as ticked before launch.

The menu is **RIPPS2's** (by **akilluminati47**), itself built on ORBIT's Neutrino in-game menu
(danielnuld/ps2-launcher, AFL-3.0); the silent pause and the exact picture are RIPPS2's too (build 108,
here as a module of their own instead of inside CDVDMAN), and so is Achievements with Left To Hunt (build 94).
RIPPS2's Screenshot page is not ported yet; the Cheats page is new here. **NOT TESTED on hardware** yet: please report games where pausing misbehaves.

---

## Troubleshooting

**Nothing happens when I press the combination.** Check, in order: the game has actually started
(past the early boot logos); the Loader Core is OPL rather than Neutrino; Mode 6 is not set for this
game; and — for the power-off combination specifically — the controller is in analog mode, since L3
and R3 are the stick clicks. The screenshot combination uses **Up**, so it needs no analog mode.

Try the console power button as a cross-check: if that resets and the pad combination does not, the
VBLANK handler is running; check the pad hook and controller behavior.

**IGR did nothing on a build from mid-October 2026.** Builds made between October 5 and October 19,
2026 (for example Beta-3979, Beta-4032 and Beta-4080) used the timer-based samplers described
above, which fail in many games, on every storage type. Update to a current build.

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
| `ee_core/src/padhook.c` | The hook itself: pad pattern matching, the VBLANK interrupt handler that samples input and stops the game, the IGR shutdown thread, combo dispatch |
| `ee_core/include/padhook.h` | The combo constants (`IGR_COMBO_R1_L1_R2_L2`, `IGR_COMBO_START_SELECT`, `IGR_COMBO_R3_L3`, `IGR_COMBO_UP`) |
| `ee_core/src/cd_igr_rpc.c` | IOP-side reset RPC |
| `ee_core/src/igs_api.c` | Screenshot capture and BMP writing |
| `ee_core/src/igrmenu.c` | The in-game menu: finding the shown frame, drawing the panel, the pages, the pad loop |
| `ee_core/include/igrcheats.h` | The cheat list the launcher hands the menu, and how a code set is built from it |
| `ee_core/src/igrmbox.c`, `modules/iopcore/igrmbox/` | The menu's IOP mailbox: the silent pause and the pixels held under the panel |
| `ee_core/src/cheat_engine.S`, `cheat_api.c` | The cheat engine; `CheatLiveApply` swaps in the menu's code set |
| `src/cheatman.c` | `igrCheatsPack` / `set_cheats_list_live`: the launcher's side of live cheats |
| `ee_core/tests/test_igrmenu.cpp` | Host test: the pages as pictures, and the code set the Cheats page builds |
| `include/iosupport.h` | `COMPAT_MODE_6` — the Disable IGR flag |

## See also

* [CONTROLS.md](CONTROLS.md) — the full button reference
* [NEUTRINO.md](NEUTRINO.md) — the alternative core, which has no IGR
* [VCD.md](VCD.md) — PS1 cores and their separate limitations
