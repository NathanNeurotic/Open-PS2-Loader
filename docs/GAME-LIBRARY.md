# Game library: All Games, recents, hiding, deleting and art

These library features came from [RIPPS2](https://github.com/akilluminati47/RIPPS2) by
**akilluminati47** (builds 95 to 118) and landed in RiptOPL #99 and Open-PS2-Loader #1084 on
2026-10-28. Both editions behave the same way. They have passed host tests only and are
**NOT TESTED on hardware**.

| Feature | Where | Saved as |
| --- | --- | --- |
| All Games list | Settings → Game Sources → **All Games List** | `all_games` (Off) |
| Show hidden games | Settings → Game Sources → **Show Hidden Games** | `show_hidden` (Off) |
| Sort order | Settings → Interface → **Sort Games**: Off, A to Z, Last played | `autosort` |
| Random game | Start menu → **Random Game**, under Launch PS2 Disc | nothing |
| Recent games | Favourites page, the fifth L3 stop | `recents.bin` |
| Hide a game | Game menu → **Hide Game** / **Show Game Again** | `hidden.txt` on the game's device |
| Delete a game and its files | Game menu → **Delete** | nothing |

## All Games list

With **All Games List** on, the Favourites page becomes **All Games**: one list of the PS2 games,
PS1 games and apps of every device that is started. Device tabs whose games are on it step aside,
and so does the Apps tab once the apps are on it. All Games starts the apps itself when
Applications Page Start Mode is Manual, so that tab goes too; with it Off there are no apps and no
tab. Tabs for devices set to Manual, and the network share picker, stay so those can still be
started. A device that is pulled out, or whose start mode is switched Off, leaves the list with its
tab. When the same title is on two devices, each row shows its device's name. The menu opens on
this page when the setting is on.

Turning the setting off brings every tab back. If Favourites Page Start Mode is Off, the Favourites
page goes away with it and the menu moves to the startup page (Settings → Game Sources → Default
Menu), or to the first tab when that page is not available.

L3 on All Games cycles **All**, **PS2**, **PS1**, **Apps**, **Favourites** and **Recent**. R3 stars
or unstars a row in place, and starred rows draw the favourite star. If the star cannot be saved,
the old state stays and a message says so. Favourites Page Start Mode can stay Off: All Games
does not need it.

## Recent games and Sort Games

`recents.bin` sits beside `favourites.bin` in the shared OPL folder and uses the same record
format. It keeps the last 10 games launched, newest first, one row per game; the BDM slots count
as one device. A launch writes it only when the Favourites page is on (or All Games is on) or
Sort Games is **Last played**, so anyone else sees no new write at launch.

The Favourites L3 ring gains a fifth stop after All: **Recent**. It keeps play order and draws no
stars. R3 on a Recent row adds the game to Favourites.

**Sort Games** replaces the old Sort Games Alphabetically switch:

| Value | Order |
| --- | --- |
| Off | The order the device listed them |
| A to Z | By title |
| Last played | The last 10 games played first, newest first, then the rest A to Z |

The rank is worked out when each row is built, so sorting never reads the memory card. Changing
the setting rebuilds the lists. An out-of-range saved value reads as A to Z.

## Random Game

**Random Game** in the Start menu moves the cursor to a random game on the page you are on. It
never picks a folder or a hidden game. Press Cross to launch it. A page with no games says so.

## Hide Game

**Hide Game** in the game menu of a PS2 or PS1 row (on any page except Apps) takes the game off
its device's page, All Games, Favourites, Recent and Random Game, after one question. A hidden
game is not gathered either, so it never adds a device name to its other copies.

Each device keeps its own `hidden.txt` in its OPL folder, beside `CFG/` and `ART/`. Each line is
`0` (PS2) or `1` (PS1), a tab, and the game's name. A line with no number is a PS2 game, and a
line that starts with `#` is a comment, so the file can be edited on a PC. The HTTP catalogue
keeps no list. A list that cannot be written changes nothing, and a message says so.

To bring a game back, turn on **Settings → Game Sources → Show Hidden Games**, open the game's
menu and choose **Show Game Again**.

## Delete a game and everything that goes with it

On USB and other BDM drives, MMCE and SMB, **Delete** on a PS2 game now removes the game and the
files that belong to it. It asks twice:

1. What goes, by count: game files, settings files, art images and cheat files. What stays: its
   VMC saves. If another copy of the game on the same device uses the same settings, art and
   cheats, the question says so and those stay.
2. A last check, because a delete cannot be undone.

The game's parts go through the device's own delete, which also rebuilds `ul.cfg` for a USBLD
game. Every part must be gone before anything else is removed; if one is left, nothing else
goes and a message says so. Then the game's CFG, its art (any letter case; PNG, JPG and JPEG;
OPL Manager names too) and its cheats go, and so does its line in `hidden.txt`.

Delete is still refused on a starred game and on the Favourites page: unstar it first. The APA
HDD page offers no delete, because that would change the partition table.

## Game art: JPG, any letter case and OPL Manager names

- Art can be `.png`, `.jpg` or `.jpeg`. A JPG saved with a `.png` name loads too, because the
  decoder reads the file's bytes, not its name. JPGs are shrunk while they decode: backgrounds to
  720 x 512, other art to 512 on the longer side.
- In an `ART` folder that the loader lists, file names match in any letter case:
  `Slus_123.45_cov.JPG` is found for `SLUS_123.45_COV`. This matters on the APA HDD, whose PFS
  minds case. SMB, UDPFS and unlisted folders still try `<name>.png`, then `.jpg`, then `.jpeg`.
- OPL Manager's names `_BG_00`, `_SCR_00` and `_SCR_01` are tried when `_BG`, `_SCR` and `_SCR2`
  are missing, and the other way round, in `ART` folders and in the `ART` .tar. The .tar also
  reads JPG members.
- Theme images still load only as `<path>.png`.

JPG support adds about 84 KB to the packed ELF.

## See also

- [Favorites](https://nathanneurotic.github.io/Open-PS2-Loader/favourites.html) for `favourites.bin` and the L3 shelves.
- [Fresh-start defaults](DEFAULTS.md) for every setting's starting value.
- [Fork-gap status](FORK-GAP-STATUS-2026-10-28.md) for the rest of the RIPPS2 port.
