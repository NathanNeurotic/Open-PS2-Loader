# Controls reference

Every button RiptOPL responds to, in one place.

Two settings change what you read below, so check them first if the tables do not match your console:

* **Select button** (*Settings → Interface*) swaps which face button confirms. The tables use the
  default, **Cross = confirm, Circle = back**. If you set Circle as the select button, swap those two
  everywhere *except* the Settings screens (see the note under [Settings screens](#settings-screens)).
* **Coverflow** (*Settings → Interface*) rotates the navigation axis on the game list. Both layouts
  are given below.

---

## Game list

| Button | Action |
|---|---|
| **D-pad Up / Down** | Move through the game list |
| **D-pad Left / Right** | Switch device page (USB, HDD, SMB, Apps, Favorites…) |
| **Cross** | Launch the selected game *(or go up one folder level, if Circle is your select button)* |
| **Circle** | Go up one folder level *(or launch, if Circle is your select button)* |
| **Triangle** | Per-game settings for the selected title |
| **Square** | Game info page — cover, screenshots, size, disc type |
| **L1 / R1** | Previous / next page of the list |
| **L2** | Jump to the first page |
| **R2** | Jump to the last page |
| **L3** | Cycle this page's library view (PS2 / PS1 / Both / …) |
| **R3** | Star or un-star the selected title as a Favorite |
| **Start** | Open the main menu |
| **Select** | Refresh the current device list |

### With Coverflow enabled

Coverflow rotates the two navigation axes on the game list — **and only there**. The info screen and
every menu keep the standard layout.

| Button | Coverflow off | Coverflow on |
|---|---|---|
| **Up / Down** | Move through the list | Switch device page |
| **Left / Right** | Switch device page | Move through the carousel |

Every other button is unchanged.

### Notes on individual buttons

**Triangle** adapts to what is selected. On a PS2 title it opens per-game settings; on a PS1 title it
opens the VCD menu; on an entry in Apps it opens the app menu. Folder rows have no settings screen,
so Triangle does nothing on them.

**Square** opens the info page. Folder rows have no info page. On PS1 titles and direct HDD entries
the size field is intentionally left blank rather than computed.

**R3** does nothing when Favorites is disabled — it never writes silently. On the Favorites page
itself, R3 removes the selected entry. See [the Favorites docs](https://nathanneurotic.github.io/Open-PS2-Loader/favourites.html).

**Select / Refresh** is also the retry for a device page that failed to populate — a network share
that was not up when RiptOPL started, for example.

---

## Main menu and dialogs

| Button | Action |
|---|---|
| **Up / Down** | Move between entries |
| **Left / Right** | Change the value of the highlighted setting |
| **Cross** | Confirm / activate |
| **Circle** | Back / cancel |
| **Start** | Confirm and close |
| **Triangle** | Open the on-screen keyboard on a text field |

### Settings screens

The settings screens pin the confirm and cancel buttons: **Cross is always OK and Circle is always
Cancel there**, whichever way the global Select button setting is configured. This is deliberate — it
keeps the settings UI stable no matter how the browser is set up.

| Button | Action |
|---|---|
| **L1 / R1** | Move to the previous / next settings screen |
| **Cross** | OK |
| **Circle** | Cancel |

### On-screen keyboard

Opened with Triangle from any text field.

| Button | Action |
|---|---|
| **D-pad** | Move around the key grid |
| **Cross** | Type the highlighted character |
| **Square** | Backspace |
| **Triangle** | Clear the field |
| **L1 / R1** | Move the caret left / right |
| **Start** | Accept and close |

---

## In-game

These work inside a running game. Hold all four shoulder buttons, then press the second half.

| Hold | Then press | Result |
|---|---|---|
| L1 + L2 + R1 + R2 | **Start + Select** | Reset — return to RiptOPL |
| L1 + L2 + R1 + R2 | **L3 + R3** | Power off the console |
| L1 + L2 + R1 + R2 | **Up** | In-game screenshot *(needs GSM on and an IGS-enabled build)* |

The console's own power button also works: **one press** powers off, **two presses** reset.

This is In-Game Reset. It does not apply under the Neutrino core, and it can be turned off per game
with compatibility Mode 6. Full detail, including the limitations, is in [IGR.md](IGR.md).

---

## At boot

| Hold at boot | Result |
|---|---|
| **Triangle + Cross** | Force the menu to 480p progressive (recovery) |

Hold both while RiptOPL starts and it ignores the saved video mode, forcing **480p progressive**
(640×448p60) and writing that back to the config. This is the recovery path for a blank screen after
setting a video mode the display cannot sync.

Two things to know: it forces 480p specifically, not Auto — Auto resolves to the region-default
interlaced mode, which is exactly what some upscalers fail to sync, so it would leave you no better
off. And it affects **the RiptOPL menu only**, not games; a game that loses the picture needs its GSM
override changed instead. Your display and cable must be able to do 480p progressive (component,
VGA, or a capable HDMI adapter) for this to help.

---

## Rumble

RiptOPL can give a short vibration when you move the cursor, confirm, or go back. It is controlled by
**Rumble** in *Settings → Controller*.

It needs a **DualShock in analog mode** — with the analog light off, the controller has no motors
available and the setting does nothing. Third-party pads and most adapters vary in whether they
report vibration support correctly.

This is menu rumble only, and is independent of in-game vibration, which is the game's business (or
PADEMU's, when emulating a pad).

---

## See also

* [IGR.md](IGR.md) — In-Game Reset in full
* [THEME_ENGINE.md](THEME_ENGINE.md) — themes can relabel on-screen button prompts
