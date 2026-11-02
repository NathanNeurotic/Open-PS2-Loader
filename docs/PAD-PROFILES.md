# .pad: HID device profiles for PADEMU, format 1

A `.pad` file describes a USB pad that PADEMU does not know, or one game's button map. The format is
[RIPPS2](https://github.com/akilluminati47/RIPPS2)'s, by [akilluminati47](https://github.com/akilluminati47). This
page carries RIPPS2's specification unchanged, then says what this build does with it
([In this build](#in-this-build)) and where the reader and the rest of this build differ from the text
([How this reader differs from the spec](#how-this-reader-differs-from-the-spec)).

- **Owner:** [RIPPS2](https://github.com/akilluminati47/RIPPS2), by [akilluminati47](https://github.com/akilluminati47).
- **Status:** format 1, frozen with RIPPS2 build 126 (2026-11-01).
- **Text:** RIPPS2's `docs/plans/pad-spec.md` as it stood at build 129 (SHA-256
  `93ee5d05d91f447f17e009303e75ab68dfb1e4a31e45f0fd4c89ad4a17304cd1`). The paragraph under this list, and everything
  from [Files](#files) to the end of [Decoding a report](#decoding-a-report-generic), are that text word for word. Its
  header (owner, reference code, tests) is replaced by this list, and its last section, on RIPPS2's own progress, is
  left out.
- **Reference code:** [`include/padfile.h`](../include/padfile.h) and [`src/padfile.c`](../src/padfile.c), RIPPS2's
  reader, packer and generic decoder (Copyright 2026, RIPPS2 contributors; Academic Free License version 3.0).
  Changed here only so they also build as C++ and pass this repository's
  [clang-format](https://clang.llvm.org/docs/ClangFormat.html) check (two casts, three pairs of parentheses,
  `extern "C"` and whitespace), and so their opening comments point to this page.
- **Ported:** from RIPPS2 builds 126 to 129: the reader, packer and decoder and My Pads (build 126); PADEMU's
  profiles, the menu's USB pad driver, the launcher's hand-over and Set Up A USB Pad (build 129).
- **Tests:** [`test_ripps2_pad.py`](../.github/scripts/test_ripps2_pad.py) runs RIPPS2's build 126 checks (files read
  and refused, the block, the decoder). [`test_ripps2_pad129.py`](../.github/scripts/test_ripps2_pad129.py) runs
  RIPPS2's build 129 checks (PADEMU, ee_core, the launcher and the menu's driver wired; Set Up A USB Pad's finder on a
  made-up pad) and this build's own rules.
- **Hardware:** NOT TESTED on hardware or in an emulator.

Any launcher, PADEMU build, setup app or PC tool may read and write these files. Please keep to this document so one
archive of profiles works everywhere. Changes go through a new format number; readers refuse a number they do not know.

## Files

| Path (beside the launcher's settings) | What |
|---|---|
| `PADS/VVVV_PPPP.pad` | One USB HID pad. `VVVV_PPPP` is its vendor and product ID in hex, upper case (`2563_0575.pad`). The name is the ID: the file does not repeat it. |
| `PADS/generic_gamepad.pad` | Fallback for any gamepad with no profile of its own (reserved; format 1 readers may ignore it). |
| `PADS/generic_keyboard.pad` | Fallback for keyboard-to-pad (reserved, as above). |
| `PADS/GAMES/<ELF name>.pad` | One game's button map (`SLUS_210.08.pad`). Applies to every pad, a real DualShock 2 included. |

Lookup for a connected pad: the exact `VVVV_PPPP.pad`, else a built-in decoder (the Sony pads), else the generic profile,
else "unsupported" with the pad's ID shown so the user can make a profile. A profile the reader refuses falls through to
the next step; it never blocks the pad and never reaches a game half read.

## Text format

ASCII, `key=value`, one per line, CRLF or LF. `#` starts a comment anywhere on a line. Blank lines are ignored. Keys and
values are case-insensitive. Lines are at most 159 characters. Sections in brackets group the keys for people:
`[Device]`, `[Buttons]`, `[Axes]`, `[Triggers]`, `[Mapping]`, `[Rumble]`. A reader does not depend on them: a key means the
same in any section, and a section it does not know is skipped with its keys. Unknown keys are ignored (that is how the
format grows without a new number). The last of a repeated key wins.

### Profile keys

| Key | Value | Default |
|---|---|---|
| `format` | `1` | 1 |
| `name` | Free text, for people and lists | none |
| `decoder` | `generic`, or a built-in decoder: `ds3`, `ds4`, `guitar_gh`, `guitar_rb` (pressure bytes, touchpad, frets) | generic |
| `report_id` | `none`, or a byte (decimal or `0x..`) the pad puts first in each report; it is skipped | none |
| `offset` | Bytes to skip before byte 0 of the map (0-255) | 0 |
| `cross` `circle` `square` `triangle` `l1` `r1` `l2` `r2` `select` `start` `l3` `r3` `up` `down` `left` `right` | `b<byte>.<bit>` (pressed = 1), `!b<byte>.<bit>` (pressed = 0), `a<byte>` (an axis pressed past half, for analog triggers), or `none`. Byte 0-31 after `offset`, bit 0-7 | none |
| `dpad` | `hat<byte>` (0-7 clockwise from up, anything else is the centre), `buttons` (use up/down/left/right) or `none` | none |
| `lx` `ly` `rx` `ry` | `a<byte>` (0-255, 128 centre), `a<byte>-` inverts, `none` (centred). Byte 0-126 | none |
| `deadzone` | Units round 128 that read as 128 (0-127) | 0 |
| `rumble` | `off`, `ds3`, `ds4` (the packet the pad understands) | off |
| `led` | `off`, `ds3`, `ds4` | off |
| `init` | `off`, `ds3` (send the DualShock 3 enable packet) | off |

A generic profile must map at least one button. `dpad=hat..` and up/down/left/right together is refused.

Example (a copy DualShock 3 that reports its buttons from byte 0):

```
# USB Gamepad (made by RIPPS2)
[Device]
format=1
name=USB Gamepad
decoder=generic
[Buttons]
square=b0.0
cross=b0.1
circle=b0.2
triangle=b0.3
l1=b0.4
r1=b0.5
l2=b0.6
r2=b0.7
select=b1.0
start=b1.1
l3=b1.2
r3=b1.3
[Axes]
dpad=hat2
lx=a3
ly=a4
rx=a5
ry=a6
deadzone=12
[Rumble]
rumble=off
led=off
init=off
```

### Game map keys

`<button>=<button>` with the button names above: the left side is what the pad pressed, the right side is what the game
gets. `<button>=none` makes the press reach nothing. Buttons not listed are themselves. `format=1` as above.

## The packed block (what PADEMU gets)

The launcher reads the text and checks it, then hands PADEMU one block of exactly **180 bytes**, the way PADEMU's
settings already reach it. PADEMU never parses text or opens a file while a game runs. All multi-byte fields are little
endian. The second byte after the magic is the format number: a reader refuses a block whose number it does not know.

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | `'P' 'D'` |
| 2 | 1 | Format (1) |
| 3 | 1 | Profiles in the block (0-4) |
| 4 | 4 x 40 | Profiles (below), unused ones zero |
| 164 | 16 | Game map: for DS2 button n, the button the game gets (0xFF itself, 0xFE nothing) |

One profile, 40 bytes:

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | VID |
| 2 | 2 | PID |
| 4 | 1 | Decoder: 0 generic, 1 ds3, 2 ds4, 3 guitar_gh, 4 guitar_rb |
| 5 | 1 | Report ID (used when flag 0x20 is set) |
| 6 | 1 | Offset |
| 7 | 1 | Flags: 0x01 rumble ds3, 0x02 rumble ds4, 0x04 led ds3, 0x08 led ds4, 0x10 init ds3, 0x20 report ID |
| 8 | 1 | Deadzone |
| 9 | 1 | D-pad hat byte, 0xFF none |
| 10 | 4 | LX, LY, RX, RY: the byte, 0x80 set = inverted, 0xFF none |
| 14 | 16 | Buttons in DS2 bit order (below): bits 0-4 the byte, bits 5-7 the bit; for an axis button the axis byte; 0xFF none |
| 30 | 2 | Mapped: bit n set when button n has a reference |
| 32 | 2 | Active low: bit n set when button n is pressed at 0 |
| 34 | 2 | From axis: bit n set when button n is an axis pressed at 0x80 or more |
| 36 | 4 | Zero (room for format 2) |

DS2 bit order (bit n of the button word the game reads, active low): 0 select, 1 l3, 2 r3, 3 start, 4 up, 5 right, 6 down,
7 left, 8 l2, 9 r2, 10 l1, 11 r1, 12 triangle, 13 circle, 14 cross, 15 square.

## Decoding a report (generic)

`padTranslate()` in the reference code is the definition: skip the report ID when the flag is set and the report starts
with it, then `offset`; each mapped button reads its bit (inverted when active low) or its axis (pressed at 0x80 or more);
the hat sets the d-pad (0 up, 1 up+right, 2 right, 3 down+right, 4 down, 5 down+left, 6 left, 7 up+left); axes read their
byte, invert if asked, and snap to 128 inside the deadzone; a byte past the report's end reads as released / centred.
Then the game map, then PADEMU's macros as today. Pressure bytes for a generic pad are 0xFF when pressed, 0 when not.

## In this build

This is what this build does with format 1. It is **NOT TESTED on hardware**: no profiled pad has been played on a
console or in an emulator.

**PADEMU builds, USB PADEMU.** All of it is built only with [PADEMU](PADEMU.md), which stock builds have
(`PADEMU ?= 1`). A game gets the profiles only through the USB PADEMU, Pad Emulator Mode **DualShock3/4 USB**, and
only on the OPL core: PADEMU does not run under [Neutrino](NEUTRINO.md). The Bluetooth PADEMU does not read them and
does not carry the code. The menu's own USB pad driver gets the same profiles, without a game map, when the menu
starts and again after Set Up A USB Pad saves one, so a profiled pad steers the menu too.

**Where PADS is.** `PADS` is a folder beside the settings file (`settings_riptopl.cfg`). With the settings in
`mc0:OPL`, profiles are `mc0:OPL/PADS/VVVV_PPPP.pad` and game maps `mc0:OPL/PADS/GAMES/<ELF name>.pad`, where the ELF
name is the game's ID, as in `SLUS_210.08.pad`. PADS is not used while the settings folder is not known: none yet, a
memory card home with no card found, or a raw APA path (`hdd0:`) rather than a mounted partition.

**Which pads take a profile.** A pad with a Sony vendor ID (054C or 12BA) never takes one, in a game or in the menu,
and neither does the ShanWan PS3 clone (2563:0575): the DualShock 3 and 4, the guitars, other Sony pads and the
ShanWan keep their built-in decoders. A profile for one of them is read and packed but never used. `decoder=` is read,
but nothing in PADEMU uses it, so the launcher leaves out a profile whose `decoder=` is not `generic` (its pad would do
nothing), and My Pads says why. At most four profiles are used, as the block holds four: after the fourth good one,
in the order the folder lists them, the rest are left out, and so is a file over 4095 bytes, rather than read in part.
Each file left out is named, with the reason, in the debug log and in `DIAG.TXT`.

**Game maps** apply only to the pads PADEMU's USB driver reads: DualShock 3, DualShock 4, the ShanWan PS3 clone and
profiled pads. Not the guitars, not pads on Bluetooth, not a real DualShock 2 in a controller port, and not the menu.

**No PADS folder: nothing changes.** No block is made, PADEMU gets its eight bytes of settings exactly as before
(bit 19, which says a block follows, stays clear), and the menu's USB pad driver is sent nothing. The same holds for a
PADS folder with no profile the launcher can use and no map for the game. The cost is one failed folder lookup when
the menu starts and one each time a game starts with the USB PADEMU. The absence is not remembered: a folder made
later is found the next time.

**Where the block goes.** As a game starts, the launcher puts eight bytes for PADEMU's settings and the 180-byte block
in module storage, after the modules and anything the [in-game menu](IGR.md#the-in-game-menu-beta) or
[RetroAchievements](RETROACHIEVEMENTS.md) keep there for the game, 64-byte aligned, below 0xD0000, or below the
in-game menu's overlay when that goes in. When there is no room, and for the two games whose module storage is moved
(SLUS_209.77 and SLPM_656.32), the game starts without profiles, and the debug log and `DIAG.TXT` say so.

**In the menu.** *Settings → Controller Settings → My Pads* lists the profiles, with the line and reason for any the
reader refuses, and says which are not used and why. *Set Up A USB Pad* writes a profile for the pad plugged in: it
asks for each button and stick in turn (SELECT on the PS2 pad skips one), lets you try the result, and puts an older
file for that pad aside first, as `.bak` (then `.b01` to `.b99`), rather than removing it.

**Memory.** The bigger USB PADEMU costs IOP RAM in every game that uses it, with a PADS folder or without:

| Module | Before | After | Change |
|---|---|---|---|
| `usb_pademu.irx` in IOP RAM during a game (text to bss) | 12,928 B | 15,336 B | +2,408 B |
| `usb_pademu.irx` file, kept in module storage for the game | 15,489 B | 18,029 B | +2,540 B |
| `bt_pademu.irx` | 16,564 B in IOP RAM | the same file, byte for byte | none |
| `ds34usb.irx`, the menu's USB pad driver (never in a game), in IOP RAM | 8,128 B | 12,008 B | +3,880 B |

These are the modules as built for this port with the rolling `ps2dev:latest` image from
[ps2dev](https://github.com/ps2dev/ps2dev) (`mipsel-none-elf-gcc` 15.2.0), not the image CI pins. How much IOP RAM a
game has left was not measured.

**Not verified either:** that the IOP's module loader hands PADEMU all 188 bytes of its arguments. It splits a
module's arguments at each zero byte and the block has many; PADEMU reads past them, as it already does for the
second four bytes of its settings.

## How this reader differs from the spec

The text above is RIPPS2's and is not edited here. Where the reader (RIPPS2's reference code, unchanged in behaviour)
or the rest of this build does something else, it is listed below. F1 to F8 were checked by running the reader on a
PC; F9 to F12 by reading PADEMU, the menu's driver and the launchers. Format 1 is frozen, so these are for RIPPS2 to
settle, in the text or in the reader: this build changes neither on its own.

1. **F1, sections.** [Text format](#text-format) says a section the reader does not know "is skipped with its keys".
   The reader ignores section lines altogether, so a key applies under any section: `cross=b0.1`, then `[Keyboard]`
   and `cross=b5.0`, maps cross to b5.0. A game map reads the same way.
2. **F2, line length.** Lines may be 159 characters, with CRLF or LF. The reader counts the CR, so a 159-character
   line that ends in CRLF is refused (`line 1: longer than 159 characters`); with LF it is read.
3. **F3, the hat.** Only 0-7 are directions and "anything else is the centre". The reader looks at the low four bits
   only, so 0x12 reads as 2, right.
4. **F4, the format byte.** [The packed block](#the-packed-block-what-pademu-gets) calls the format number "the second
   byte after the magic". It is the first, at offset 2, as the table under it says.
5. **F5, 0xFF in a button slot.** The profile table gives 0xFF as none, but `b31.7` packs to 0xFF as well. This reader
   goes by the Mapped bits (offset 30), so that button works; a reader that takes 0xFF as none would lose it.
6. **F6, a profile with no button.** "A generic profile must map at least one button", but the reader also takes a
   profile that maps only `dpad=hat..`.
7. **F7, the hat's byte.** No range is given for `dpad=hat<byte>`. The reader takes 0-126, as for an axis, and refuses
   127 or more.
8. **F8, smaller points.** The reader also takes file names in lower-case hex and `.PAD`, and a button's byte in hex
   (`b0x1F.7`). It reports the first error by line, so a bad line above `format=2` hides the format. A UTF-8 byte
   order mark is not skipped: it joins the first line, so a key there is not known and is ignored (with `format=2` on
   that line, the file is read as format 1), and a comment or a section there is refused as `line 1: not key=value`.
   A comment longer than 159 characters refuses the file, like any long line. With `report_id` set, a report that
   starts with another ID is read without skipping a byte, as [Decoding a report](#decoding-a-report-generic) says.
   The original header pointed to the reference code in the tree RIPPS2 patches and named only the build 126 test; the
   list at the top of this page names this repository's copies and both tests.
9. **F9, `decoder=` and built-in pads.** `decoder=` is read and packed, but neither PADEMU nor the menu's driver uses
   it, and a Sony vendor ID never takes a profile, so the lookup order in [Files](#files), the exact `VVVV_PPPP.pad`
   before a built-in decoder, does not hold for Sony pads. Nor does it for the ShanWan PS3 clone, whose built-in decoder
   comes first in RIPPS2 and here, although its ID is the example name in [Files](#files) (`2563_0575.pad`). The reader
   takes `decoder=ds3` with no buttons, a profile that decodes nothing. This build's launcher leaves out every profile
   whose `decoder=` is not `generic` ([In this build](#in-this-build)).
10. **F10, the report's length.** In RIPPS2, PADEMU decodes every report as 64 bytes long, so "a byte past the
    report's end reads as released / centred" never applies there. This build's PADEMU passes each report's real
    length, as the menu's driver does.
11. **F11, where a game map applies.** [Files](#files) says a game map "applies to every pad, a real DualShock 2
    included". Only PADEMU's USB driver applies it, in RIPPS2 and here ([In this build](#in-this-build)).
12. **F12, file size.** The text sets no limit. RIPPS2's launcher reads up to 4095 bytes of a file while its My Pads
    reads 8191, so in RIPPS2 a profile of 4 to 8 KB looks right in My Pads and is cut short when a game starts. This
    build's launcher leaves a file over 4095 bytes out instead. Keep a `.pad` under 4 KB.

## See also

* [PADEMU.md](PADEMU.md) — the Pad Emulator, and the USB and Bluetooth modes
* [CONTROLS.md](CONTROLS.md) — the menu's own button map
