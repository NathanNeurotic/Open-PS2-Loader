<!--
  ROLLING RELEASE NOTES, PART 2 of 2 -- read by .github/workflows/rolling-release.yml ("Build release
  notes"), after the generated Download section. Part 1 is rolling-release-notes-intro.md.

  WHO OWNS WHAT, so nothing is said twice and nothing goes stale:
  - The workflow generates what changes per run: the version header, Download (which archives and
    flavours actually built, the bundled Neutrino version) and Recently merged (the last merged PRs).
  - .github/scripts/normalize_release_notes.py adds the banner images and External Tools & Services,
    which it reads from README's section (docs-sync owns that list).
  - These two files hold everything else. Keep each fact in ONE place, keep it short, and link the
    guides site for detail instead of copying it here.

  When a "Needs testing" item is confirmed on hardware, delete it. When a feature lands, add at most
  one clause to Highlights. Keep the voice direct. Plain Markdown, no templating.
-->

## PS1 games

Two cores share one PS1 list; the row you launch decides which one runs, so a game kept for both
appears twice.

| Core | Files | Location |
| --- | --- | --- |
| **POPSTARTER** | `*.VCD` | `<device>:/POPS/` |
| **Ember** | `*.cue` / `*.bin` / `*.exe` | `<device>:/EMBER/games/<Game Name>/` |

- **Setting up Ember:** copy the package's `EMBER/` folder to a device root and add your own PS1 BIOS
  as `EMBER/bios.bin` (512 KB; a BIOS is never included). Give each game its own folder: the folder
  name is the title and the cover-art key (`ART/<Game Name>_COV.png`). Ember writes its memory cards
  into that folder, so the device must be writable. On the internal APA drive, `EMBER/` goes on its
  own `__.EMBER` partition (`__.EMBER0`–`__.EMBER9` for more), while cover art stays on your OPL
  partition.
- **Ember display mode:** *PS Emulation Settings → Ember Display Mode*. 240p or 480p writes
  `EMBER/settings.txt` on that device at launch; Default removes the key again.
- **UDPFS and UDPBD** list Ember titles only: POPSTARTER's IOP reset can't restore either network
  transport.
- **POPSTARTER builds:** `POPS/POPSTARTER VERSIONS/` holds MAIN, DEBUG, USBDELAY, USBDELAY_DEBUG and
  USBDELAY_LONGER_DEBUG. The shipped `POPSTARTER.ELF` is DEBUG on purpose: it carries SMB support, so
  on-screen diagnostics during a VCD launch are expected. Copy another over `POPS/POPSTARTER.ELF` only
  if you need it (USBDELAY for USB devices that settle slowly). Keep the package's `POPS/` together.
- **Guides:** [PS1 / VCD](https://nathanneurotic.github.io/Open-PS2-Loader/ps1-vcd.html) ·
  [internal HDD](https://nathanneurotic.github.io/Open-PS2-Loader/hdd.html)

**Ember is by Gageformer** (<https://github.com/Gageformer/Ember/releases>), bundled unmodified under
the Ember Public Beta Testing Licence, shipped as `EMBER/LICENSE-BETA.txt`: free to use and to bundle
non-commercially; no selling, modifying or repackaging; no BIOS or game content, ever. Report Ember
problems to us first, since the launching is ours.

## Neutrino

The package's `neutrino/` folder is the official build named under Download, re-fetched on every
publish. Copy it to `mc?:/neutrino/`, then pick Neutrino per game; everything else stays on OPL's own
core. RiptOPL adds exactly one file, `config/bsd-udpfsbd.toml`, for UDPFS. *Default Device* includes
iLink. [Guide](https://nathanneurotic.github.io/Open-PS2-Loader/neutrino.html)

**Neutrino is by rickgaiser** (<https://github.com/rickgaiser/neutrino>), under AFL-3.0. Report
launch problems to us; genuine Neutrino bugs belong upstream.

## Highlights

- **Libraries:** *PS2/PS1 Game Display* (Interface and PS Emulation Settings) offers Both (L3), Mixed,
  PS2 or PS1. APPS can move `[PS1]`-titled ELFs to their own L3 view. Favorites (R3 to star) cycles
  All in One, PS2, PS1 and ELF; the file is still `favourites.bin`. Each page remembers its L3 view
  across reboots, mixed lists keep every cover's own shape, and Start or Settings returns you to the
  page you left. A device page whose `CD`/`DVD` folders won't open says so once, with the error,
  instead of rescanning in the background, and an L3 flip no longer rebuilds Apps.
- **Cores:** OPL's own or Neutrino, per game, with global and per-game Neutrino arguments (`$`
  disables a flag; *Test launch* boots without saving). Per-game VMCs are shared with Neutrino on
  writable BDM devices.
- **Network:** SMB, UDPFS, UDPBD and HTTP. Confirming Network Settings reconnects straight away, and
  *Select / Refresh* retries a failed network page. PC servers: PS2-Servers, below.
- **Video:** Coverflow render mode. GameID barcodes for Pixel FX / RetroGEM / PS2Digital (Interface,
  off by default) and for POPSTARTER launches (PS Emulation Settings, on by default). Keeping a new
  video mode takes a hold of Accept, with a countdown to the automatic revert.
- **Cheats:** can be on for every game; a game with no `.cht` just starts, and a cheat file that
  exists but won't load always says so.
- **Storage safety:** on the internal HDD, RiptOPL is a game loader, not a partition manager. It
  writes only inside PFS partitions and never edits the APA table, so HDL games and one-game `PP.*`
  PS1 installs are deleted and renamed on a PC. A table that can't be read shows **code 402: don't
  format it** ([recovery guide](https://github.com/NathanNeurotic/Open-PS2-Loader/blob/rebuild/main/docs/APA-SAFETY.md)).
  USB, exFAT HDD, MX4SIO and iLink no longer return stale data after a failed read. A drive whose
  logical sectors aren't 512 bytes (4Kn) is refused, showing **code 500** on USB and exFAT; 512e
  drives work normally.
- **Cover art:** most "looks wrong" reports are file naming. OrbitPS2 Manager (below) writes `ART/`
  and per-game configs in the layout RiptOPL expects; report its issues to its own repository.

## Needs testing on real hardware

- **Internal APA HDD**, on a disk you have backed up: boot, list, launch, rename a loose VCD or an
  Ember title, exit and power off. Everything should still list, and PS2 games offer no Rename or
  Delete.
- **USB / MX4SIO / exFAT HDD:** normal use. Lists should load at normal speed, and the drive should
  still check clean on a PC afterwards.
- **iLink:** Ember works. Retest Neutrino (now with automatic `-qb`) and POPSTARTER (report the
  `mc?:/POPSTARTER` ilink marker and both installed module sizes/hashes). The native OPL core still
  fails at game handoff.
- **HTTP**, with Docmine17's OPL HTTP server: the catalog lists and an ISO boots.
- **PC network servers:** with PS2-Servers, the list populates and an ISO boots over UDPFS or SMB
  (UDPBD is confirmed).
- **A USB / MX4SIO page with no PS2 games:** the message names the folder and the error number, and
  L3 stays quick on every page.
- **Keeping a video mode:** holding Accept, the bar fills smoothly to the end; left alone, the
  countdown reads 10 to 1 and the old mode comes back.
- **VMC → Neutrino** on USB, exFAT or MX4SIO (internal APA can't yet: upstream neutrino#132).
- **GameID barcode:** your Pixel FX / RetroGEM / PS2Digital loads the per-game profile.
- **Mixed cover sizing:** PS1 and app covers square, PS2 covers portrait, on your own theme too.
- **Remembered L3 view:** toggle a page, launch a game or save settings, reboot; it comes back.
