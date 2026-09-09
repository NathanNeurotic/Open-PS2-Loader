# GSM — forced video modes

**GSM makes a game output a video mode it was never written to output.** Most PS2 games render
480i (or 576i in PAL). GSM intercepts the game's video setup and substitutes a different raster, so
the same game can come out as 480p, 720p, 1080i, or one of a range of VGA modes — useful on modern
displays and upscalers that handle interlaced signals badly or not at all.

GSM does not re-render anything. The game still draws the same picture at the same internal
resolution; GSM changes how that picture is scanned out. Expect a cleaner, more stable signal, not
extra detail.

---

## Where to set it

GSM lives in two places:

* **Per game** — Triangle on a title → **Configure GSM**.
* **Globally** — *Settings → Display Settings → GSM Defaults*. This is what every game with no GSM
  settings of its own inherits.

The per-game page's first row, **GSM Source**, decides which of those wins:

| GSM Source | Meaning |
|---|---|
| **Global** | Ignore this game's GSM keys entirely and follow the global defaults. Selecting it also *removes* the game's stored GSM keys. |
| **Per Game** | This game's GSM settings apply, as a complete set. |
| **Per Game + Global** | Per-key inheritance: any GSM value this game sets is used, and anything it leaves unset falls through to the global default. |

**Per Game + Global** is the option to reach for when you want one game to differ from your global
setup in a single respect — a different video mode, say — while still tracking your global choices
for everything else.

---

## The options

| Option | What it does |
|---|---|
| **GSM Selector** | The on/off switch. With it off, the four rows below are greyed out and GSM does nothing. |
| **Forced custom display mode** | The video mode to output. See the list below. |
| **H-POS** | Horizontal position offset, −100 to +100. Shifts the picture left/right. |
| **V-POS** | Vertical position offset, −100 to +100. Shifts the picture up/down. |
| **Emulate FIELD Flipping** | Compatibility fix for games that shake, tear, or judder under a progressive mode. Try this first when a game looks wrong *after* GSM is applied. |

On the per-game page the mode list ends with **Default**, which means "follow the global setting".
Picking it removes the key rather than storing a value, so the game genuinely tracks the global from
then on. That entry does not appear on the global page, where it would be meaningless.

### Available modes

Modes 0–5 are the standard console rasters; the rest are forced progressive, HDTV, or VGA modes.

| # | Mode | | # | Mode |
|---|---|---|---|---|
| 0 | NTSC | | 15 | VGA 640x480p @75Hz |
| 1 | NTSC Non Interlaced | | 16 | VGA 640x480p @85Hz |
| 2 | PAL | | 17 | VGA 640x960i @60Hz |
| 3 | PAL Non Interlaced | | 18 | VGA 800x600p @56Hz |
| 4 | PAL @60Hz | | 19 | VGA 800x600p @60Hz |
| 5 | PAL @60Hz Non Interlaced | | 20 | VGA 800x600p @72Hz |
| 6 | PS1 NTSC (HDTV 480p @60Hz) | | 21 | VGA 800x600p @75Hz |
| 7 | PS1 PAL (HDTV 576p @50Hz) | | 22 | VGA 800x600p @85Hz |
| 8 | HDTV 480p @60Hz | | 23 | VGA 1024x768p @60Hz |
| 9 | HDTV 576p @50Hz | | 24 | VGA 1024x768p @70Hz |
| 10 | HDTV 720p @60Hz | | 25 | VGA 1024x768p @75Hz |
| 11 | HDTV 1080i @60Hz | | 26 | VGA 1024x768p @85Hz |
| 12 | HDTV 1080i @60Hz Non Interlaced | | 27 | VGA 1280x1024p @60Hz |
| 13 | VGA 640x480p @60Hz | | 28 | VGA 1280x1024p @75Hz |
| 14 | VGA 640x480p @72Hz | | 29 | HDTV 1080p @60Hz (EXPERIMENTAL) |

**HDTV 480p @60Hz** (8) is the safe starting point on almost any modern display. **720p** (10) and
**1080i** (11) are the next most widely accepted. The VGA modes need a display fed over VGA or a
component/VGA-capable path; a plain HDMI adapter will usually not sync them.

---

## 1080p is experimental, and asks three times

Mode 29, **HDTV 1080p @60Hz (EXPERIMENTAL)**, is compiled into every shipped build. It is a
GSM-synthetic progressive raster — not a mode the PS2 hardware natively produces — and while it has
passed real-hardware testing, it is non-standard enough that some displays will not sync it at all.

Because a display that cannot sync leaves you with a black screen and no way to undo the choice from
the console, selecting 1080p **with GSM enabled** triggers a three-step confirmation before it is
written to disk. Decline at any of the three steps and the mode falls back to **NTSC (mode 0)**, not
to your previous selection — so if you cancel, set the mode you actually wanted before leaving the
page.

The same gate applies on the global page, which carries the wider blast radius of the two: it is what
every game without its own GSM settings inherits.

---

## When a game loses the picture

GSM is applied per game, so a bad setting affects that game only — the RiptOPL menu itself is
unaffected and you can always get back to it.

1. Launch a game that still works, or use the console's reset to return to the browser.
2. Triangle on the affected title → **Configure GSM**.
3. Either turn **GSM Selector** off, or pick a more conservative mode (480p, or the game's native
   NTSC/PAL).

If the **menu itself** has no picture, that is not GSM — that is the global video mode setting. Hold
**Triangle + Cross while RiptOPL boots** to force the menu to 480p progressive. See
[CONTROLS.md](CONTROLS.md).

### The game runs but looks wrong

**Shaking, tearing, or juddering under a progressive mode** — turn on **Emulate FIELD Flipping**.
This is what it exists for.

**Picture off-centre** — adjust **H-POS** and **V-POS**.

**Some scenes fine, others broken** — a few games switch video mode mid-run (typically for FMVs).
Those tend to be poor GSM candidates; try a less aggressive mode or leave GSM off for that title.

---

## GSM and the other cores

**Neutrino** does not use OPL's GSM. It has its own forced video mode handling, and the per-game
**Neutrino GSM Compatibility** option is the equivalent field-flipping fix — "for games that shake or
tear under a forced Neutrino video mode". Set it there rather than on the GSM page when the Loader
Core is Neutrino. See [NEUTRINO.md](NEUTRINO.md).

**PS1 titles** run under POPSTARTER or Ember and do not use OPL's GSM either. Modes 6 and 7 in the
list above are named "PS1 NTSC/PAL" because of the raster they produce, not because they apply to PS1
games. See [VCD.md](VCD.md).

---

## Related settings that are not GSM

Two settings are easy to mistake for GSM options:

* **Overscan** (*Settings → Display*) trims the edges of the **RiptOPL menu**, not of games. It is a
  UI setting and is unrelated to the GSM H-POS/V-POS offsets.
* **Video Mode** (*Settings → Display*) sets the mode the **menu** runs in. GSM never affects it.

---

## Notes for builders

GSM's 1080p mode is behind `GSM_1080P`, which the `Makefile` defaults to `1` — so every shipped
build has it and the mode list is a consistent 30 entries across published flavours. Building with
`GSM1080P=0` drops mode 29 and shortens the list.

`In-game screenshots (IGS) require GSM to be enabled` — see [IGR.md](IGR.md#in-game-screenshots-igs).

| File | Role |
|---|---|
| `ee_core/src/gsm_api.c`, `gsm_engine.S`, `gsm_engine_adv.S` | The GSM engine |
| `src/guigame.c` | The GSM settings page, the mode list, and the 1080p confirmation gate |
| `src/dialogs.c` | The six GSM dialog rows |

## See also

* [CONTROLS.md](CONTROLS.md) — the boot recovery combo for a menu with no picture
* [IGR.md](IGR.md) — in-game screenshots depend on GSM
* [NEUTRINO.md](NEUTRINO.md) — the alternative core's own video handling
