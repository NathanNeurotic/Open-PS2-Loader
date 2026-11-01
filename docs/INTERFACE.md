# Interface behaviours

Menu behaviours that are configured from *Settings* but need more than a one-line description:
language and theme selection, menu video modes, folder browsing, the parental lock, and the audio system.

For the button map, see [CONTROLS.md](CONTROLS.md). For UTF-8 Japanese and other Unicode game names with English menus, see [Unicode Game Titles](UNICODE-GAME-TITLES.md): place an optional `font_CJK.ttf` alongside `settings_riptopl.cfg` and restart; there is no UI toggle.

---

## Language

**Settings → Language** contains the single menu-language picker and the
**OSD Defaults** action. The picker changes RiptOPL's interface. OSD Defaults
opens the existing editor for the console language, screen size and video mode
passed to games by the OPL core; it does not change the menu language or write
the console's OSDSYS settings. Per-game overrides remain in each game's settings.

Back and L1/R1 keep edits active for the current session. Choose **Save Changes**
on the Settings index to keep them after restarting. See [Languages](LANGUAGES.md)
for installing translation files and fonts.

---

## Theme selection

**Settings → Interface → Theme** picks the theme: `<OPL>` or a disk theme from `THM/`.
**Theme View** picks how it draws your games: **List**, **Coverflow (3)** or **Coverflow (5)** (the
centered carousel with 3 or 5 covers), **PSBBN Flow** (the PSBBN Definitive Project Game Collection look) or **Grid** (rows and columns of
covers; Up/Down move one row). `<OPL>` offers all of them; a disk
theme offers the views its author declared (both Coverflow entries when it has a Coverflow view), and shows its default view for any other pick. **Default**
uses the theme's own default. Holding **L3** for half a second on the main page switches to the next
view the theme offers, in the order List, Coverflow (3), Coverflow (5), PSBBN Flow, Grid, without
opening the settings. Apply and save to retain the choice. Fresh
configurations start with `<OPL>` in the List view, 4:3 and Auto video mode; theme, view and aspect are
separate settings. A configuration that saved the former `<Coverflow>` or `<PSBBN Flow>` theme loads
`<OPL>` with that view. The two Coverflow entries are saved as `theme_view=coverflow` plus
`coverflow_count=3` or `5`, the keys earlier builds used, so an older configuration keeps its count
and the Coverflow Settings page no longer has a Cover Count row.

**Library**, right under Theme View, picks **Pages** (every device keeps its own tab) or **All Games
List** (one page with the games of every started device; see [Game library](GAME-LIBRARY.md#all-games-list)).
It works with every view and is the same `all_games` setting as **Game Sources → All Games List**.

**Alternate Background**, under Library, shows the theme's second background when its author gave one
(`alt=` in `conf_theme.cfg`; idea: [KrahJohlito](https://github.com/KrahJohlito)), so one theme can ship two looks. It is Off on fresh
configurations and saved as `theme_alt_bg=1`. A theme without `alt=` looks the same either way, and only
a theme with `alt=` is reloaded when the setting changes. Per-game background art still wins over the
theme's picture while a game is selected. See
[THEME_ENGINE.md, Alternate background](THEME_ENGINE.md#alternate-background-alt--this-fork).

**Boot Theme Wait**, under Alternate Background, is how many seconds (0 to 10) the start-up screen waits
for your saved theme while the drive that holds it is still starting up, so the built-in theme does not show
for a moment first. It is Off (0) on fresh configurations: the menu opens right away and the saved theme
replaces the built-in one as soon as its drive is up. Saved as `boot_theme_wait`; 6 is the old fixed wait.

Both flow views rotate navigation on the main game list: Left/Right browse covers and Up/Down
change sources. R3 remains Favorite, and info/settings screens keep their normal controls.
**Coverflow Settings** tunes the `Coverflow` renderer; PSBBN Flow uses its fixed layout and
25-frame glide. All four views share the editable palette, artwork and audio settings.
See [Controls](CONTROLS.md), [Fresh-start defaults](DEFAULTS.md), and the
[Theme Engine reference](THEME_ENGINE.md#psbbn-flow).

---

## Menu font size

**Settings → Interface → Font Size.** Choose **Small**, **Default** or **Large**.

The size change applies immediately and is saved with your settings. Standard menu text uses
15, 17 or 19 pixels, with list rows and dialog spacing adjusted to match. Theme and language fonts
using the standard 17-pixel size follow this choice. Explicit custom theme point sizes stay unchanged.

For Unicode/Japanese title setups that use `font_CJK.ttf`, the same size setting applies there too.
See [Unicode Game Titles](UNICODE-GAME-TITLES.md) for font file placement.

---

## Button glyphs

**Settings → Interface → Button Glyphs.** Choose **Theme**, **Built-in**, **Standard** or **White**.

These are the button pictures in the hint bar. **Theme** uses the theme's own glyphs, or the set its
`glyph_set` key names. Each of the other choices replaces the glyphs on every theme. **Built-in** is the
built-in set. **Standard** and **White** come from [RIPPS2](https://github.com/akilluminati47/RIPPS2) ([akilluminati47](https://github.com/akilluminati47)), drawn from its Adapt and Grunge
themes. The change shows on the next frame and is saved with your settings. Theme authors can find the
`glyph_set` key and the hint bar keys in the [Theme Engine reference](THEME_ENGINE.md#button-hints-and-glyphs).

*Not yet tested on hardware.*

---

## Menu video modes

**Settings → Interface → Video Mode** sets the signal the **menu** uses. Games are not affected; they
use their own mode, or GSM, described in [GSM.md](GSM.md). After a change, **hold** Accept to keep the new
mode; a tap does nothing, and Back or 10 seconds goes back to the old one (see
[Keeping a new video mode](CONTROLS.md#keeping-a-new-video-mode)). Holding **Triangle + Cross** at
boot forces 480p and **Triangle + Circle** forces Auto, for a screen that shows nothing.

| Entries | What they are |
| --- | --- |
| **Auto** | The console's own region mode (NTSC 640x448i or PAL 640x512i). The default. |
| PAL 640x512i, NTSC 640x448i | The standard interlaced modes. |
| EDTV 640x448p, EDTV 640x512p, VGA 640x480p | Progressive modes; they need component or VGA (composite shows no picture). |
| PAL 704x576i, NTSC 704x480i, EDTV 704x480p, EDTV 704x576p (HIRES) | Sharper 704-wide modes. The interlaced ones draw the menu inside a 4:3 safe area with the same margins as the 640-wide modes, so a 4:3 CRT does not cut it off. |
| HDTV 1280x720p, HDTV 1920x1080i (HIRES) | HD modes for component or HDMI; always drawn as 16:9, whatever the Widescreen setting. |
| PAL 640x256p, NTSC 640x224p | Low-resolution progressive (240p-style) modes, for CRTs and scalers that prefer them. |
| PAL 640x512i, NTSC 640x448i (FLICKER-FREE) | The same interlaced signal, but both fields show the same lines, so thin lines and font edges stop flickering on a CRT, at the cost of half the vertical detail. |
| NTSC 704x480i (HIRES, 448 lines) | NTSC 704x480i with the menu kept in the 640x448 area, for a CRT that still hides the top or bottom of the 480-line mode. |
| PAL 704x576i, NTSC 704x480i, NTSC 704x480i 448 lines (HIRES, FLICKER FILTER) | The three interlaced HIRES modes with each line shown half-and-half with the line below it, which calms interlace flicker while keeping the full vertical resolution. |

The list keeps its order across versions (new modes are added at the end), so a saved mode stays
the same mode after an update. **H-POS**, **V-POS** and **Overscan** are remembered for each video
mode separately. When the settings are on a memory card, the menu starts directly in the saved mode
instead of starting in Auto and switching. The FLICKER FILTER and 448-line modes are new and
**NOT TESTED on hardware**.

---

## Folder browsing

**Settings → General & System → Browse Folders in Game List.** Off by default.

With it on, subfolders of `CD/` and `DVD/` appear in the game list as browsable entries instead of
the loader flattening everything into one long list.

* Folder rows sort to the **top** of the list, ahead of games, and are drawn with a trailing `/`.
  Within each group, entries sort by title.
* **Select** opens a folder; the **cancel** button goes back up a level. Which face button that is
  depends on your Select button setting.
* A folder row has no info page and no per-game settings, so Square and Triangle do nothing on one.

### Supported devices only

Folder browsing works on **BDM devices** (USB, MX4SIO, iLink, exFAT HDD and network-backed BDM slots), **MMCE**, and **UDPFS in
Files mode**.

It does **not** apply to:

| Device | Why |
|---|---|
| APA/PFS HDD | Stores games as HDLoader partitions; there is no `CD`/`DVD` directory tree to scan |
| PS1 / VCD list | Same — the VCD view is not a directory scan |
| SMB / ETH | **Deferred, not yet supported.** SMB paths use a different separator (`\`) from the loose-file scanners |

Turning the setting on simply has no effect on those pages.

---

## Parental lock

**Parental Lock Password**, under **Settings → General & System → Security**. Sets a password that must be entered
before configuration can be changed. Leave it blank to disable the lock.

### What it actually gates

The master password guards **configuration and destructive actions**. Individual PS2 games can
additionally require it at launch. The configuration gate protects:

* **Settings**, and the per-game / per-app settings screens (Triangle on a title)
* **Rename** and **Delete** on a game entry
* **Network compatibility update** and **Start NBD Server**

> To lock an individual PS2 game, enable **Parental Lock** in its Compatibility settings and save.
> Each launch requires fresh authorization, including Favorites and remembered launches. This is
> separate from unlocking settings for the session; unmarked games remain launchable. See
> [Per-game parental lock](PARENTAL-LOCK.md) for Test Changes, saved-lock removal and recovery.

### Setting, using and clearing it

**To set one**, enter a password and save. **To remove one**, clear the field and save — RiptOPL
confirms with *"Parental lock disabled."*

**Entering the correct password** unlocks for the rest of the session: RiptOPL stops asking until the
next restart, so you are not re-prompted between one settings screen and the next.

**A master override password exists** for a forgotten lock. Two things about it are worth knowing:

1. It does not grant one-time access — it **deletes the stored password and saves immediately**,
   showing *"Parental lock disabled."* After that there is no lock until you set a new one.
2. It **cannot be chosen as your own password**. Trying is rejected with *"Error - this password
   cannot be used."*

The value itself is not printed here, matching the documentation site's convention of pointing people
at the community forums for it.

---

## Background music and sound effects

**Settings → Audio Settings.**

### Background music

**BGM is Ogg Vorbis** (`.ogg`). RiptOPL streams it rather than loading it into memory, so a long
track costs no extra RAM. It looks in this order and takes the first that works:

1. `<theme>/sound/bgm.ogg` — a disk theme's own music.
2. The **Default Theme Music** path from Audio Settings.
3. `THM/bgm.ogg` under the active settings home — **the built-in `<OPL>` theme only**, in
   every view. A disk theme never falls through to this.

That order is why a disk theme with its own `sound/bgm.ogg` ignores your Default Theme Music setting:
the theme wins. To use your own track everywhere, pick a theme that ships no music of its own.

The track plays through the console's `audsrv`, which only has converters for some sample rates:
44.1 kHz, 48 kHz, 32 kHz, 22.05 kHz and 11.025 kHz in mono or stereo, and 24 kHz or 12 kHz in stereo
only. A file at any other rate, such as 16 kHz, plays no music at all; the menu carries on silently.
Re-encode it at 44.1 kHz if in doubt.

### Sound effects

**SFX are PS2 ADPCM** (`.adp`, 44.1 kHz), supplied by the theme in its `sound/` folder. There are
eight:

| File | Played when |
|---|---|
| `boot.adp` | RiptOPL starts (the Boot Sound setting) |
| `cursor.adp` | Moving the cursor |
| `confirm.adp` | Confirming |
| `cancel.adp` | Going back |
| `message.adp` | A message or dialog appears |
| `transition.adp` | Changing screen |
| `bd_connect.adp` | A block device is connected |
| `bd_disconnect.adp` | A block device is removed |

The built-in `<OPL>` theme uses, in every view, effects embedded in the ELF and read nothing from the card. A disk theme
supplying only some of the eight falls back to the built-in sound for the rest.

Confirm, cancel, message and transition never wait for each other: a new one stops the one still
playing, so pressing confirm twice quickly plays confirm twice, and confirm then cancel is heard as
the cancel. The cursor sound, the boot sound and the device connect/disconnect sounds play alongside
them instead. A long `transition.adp` or `confirm.adp` in a theme is cut short the same way.

Sound effects, the boot sound, and background music each have their own on/off switch and their own
volume. See [THEME_ENGINE.md](THEME_ENGINE.md) for packaging audio with a theme.

---

## See also

* [CONTROLS.md](CONTROLS.md) — the button map, including menu rumble
* [THEME_ENGINE.md](THEME_ENGINE.md) — theme-supplied audio
