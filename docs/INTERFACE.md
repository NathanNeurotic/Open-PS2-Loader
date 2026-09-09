# Interface behaviours

Menu behaviours that are configured from *Settings* but need more than a one-line description:
folder browsing, the parental lock, and the audio system.

For the button map, see [CONTROLS.md](CONTROLS.md).

---

## Folder browsing

**Settings → Interface → Browse Folders in Game List.** Off by default.

With it on, subfolders of `CD/` and `DVD/` appear in the game list as browsable entries instead of
the loader flattening everything into one long list.

* Folder rows sort to the **top** of the list, ahead of games, and are drawn with a trailing `/`.
  Within each group, entries sort by title.
* **Select** opens a folder; the **cancel** button goes back up a level. Which face button that is
  depends on your Select button setting.
* A folder row has no info page and no per-game settings, so Square and Triangle do nothing on one.

### Supported devices only

Folder browsing works on **BDM devices** (USB, MX4SIO, iLink, exFAT HDD), **MMCE**, and **UDPFS in
Files mode**.

It does **not** apply to:

| Device | Why |
|---|---|
| APA/PFS HDD | Stores games as HDLoader partitions; there is no `CD`/`DVD` directory tree to scan |
| PS1 / VCD list | Same — the VCD view is not a directory scan |
| UDPFS block device | Block transport, not a file tree |
| SMB / ETH | **Deferred, not yet supported.** SMB paths use a different separator (`\`) from the loose-file scanners |

Turning the setting on simply has no effect on those pages.

---

## Parental lock

**Settings → Parental Lock Settings.** Sets a password that must be entered before configuration can
be changed.

### What it actually gates

The parental lock guards **configuration and destructive actions, not game launching**. Anyone can
still start any game on the list. Behind the password:

* **Settings**, and the per-game / per-app settings screens (Triangle on a title)
* **Rename** and **Delete** on a game entry
* **Network compatibility update** and **Start NBD Server**

> It is not a content filter. If your aim is to stop a particular game being played, the parental
> lock will not do it — it stops the library being *changed*, not played.

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
3. `THM/bgm.ogg` under the active settings home — **built-in themes only** (`<OPL>` and
   `<Coverflow>`). A disk theme never falls through to this.

That order is why a disk theme with its own `sound/bgm.ogg` ignores your Default Theme Music setting:
the theme wins. To use your own track everywhere, pick a theme that ships no music of its own.

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

The two built-in themes use effects embedded in the ELF and read nothing from the card. A disk theme
supplying only some of the eight falls back to the built-in sound for the rest.

Sound effects, the boot sound, and background music each have their own on/off switch and their own
volume. See [THEME_ENGINE.md](THEME_ENGINE.md) for packaging audio with a theme.

---

## See also

* [CONTROLS.md](CONTROLS.md) — the button map, including menu rumble
* [THEME_ENGINE.md](THEME_ENGINE.md) — theme-supplied audio
