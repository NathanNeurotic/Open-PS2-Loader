# File Manager

**Start → File Manager** browses every drive the loader has started and copies, moves, renames and deletes
files on them, without booting a separate file manager. It is a port of the Memory Files browser from
[akilluminati47](https://github.com/akilluminati47)'s [RIPPS2](https://github.com/akilluminati47/RIPPS2)
(builds 91 to 125), redrawn as an ordinary dialog.

*NOT TESTED on hardware yet.*

## Drives

The first page lists what is started now. Nothing is loaded just to fill the list: start a device from its
page (or set it to Auto in Settings) and it appears here.

| Shown as | What it is |
| --- | --- |
| `mass0:/` … with USB, MX4SIO, iLink, UDPBD or internal HDD (exFAT) | each started BDM drive |
| `mmce0:/`, `mmce1:/` | MMCE cards |
| `mc0:/`, `mc1:/` with the free space | formatted PS2 memory cards |
| `pfs0:/` | the loader's own partition on an APA internal HDD (the APA disk itself and its other partitions are never listed or touched) |
| `udpfs:/` | the UDPFS server, when UDPFS is running |
| `smb0:\` | the SMB share, when it is connected |

## Controls

| Button | On a row |
| --- | --- |
| Cross | opens a folder or drive; on a file, shows what can be done with it |
| Square | marks or unmarks the entry (marked rows start with `*`) |
| Triangle | shows what can be done with the entry |
| L1 / R1 | the previous / next page (12 entries a page) |
| Circle | up one folder; from the drive list, closes the File Manager |

A folder lists `..` first, then its folders, then its files with their sizes, each by name. In a memory
card's root each save folder shows the title from its `icon.sys`. The line under the path says the page,
how many entries the folder has, what is on the clipboard and how many are marked.

## What can be done

The actions menu (Triangle, or Cross on a file) offers what fits the entry:

- **Open** (a folder) and **Run** (an `.elf`). Run starts the ELF the way an app on the Apps page starts:
  the Reboot IOP question, then the same handoff. An ELF on the internal HDD (`pfs0:/`) is left to the Apps
  page, which knows its partition.
- **Mark** / **Unmark**.
- **Copy** and **Cut** put the marked entries, or this one if none are marked, on the clipboard.
- **Rename**, typed on the keyboard.
- **Delete** the marked entries, or this one, folders with everything in them. You are asked first.
- **Unpack PSU here** (a `.psu` file) unpacks the save into its folder here. On a memory card it goes in
  the card's root, where games look for saves.

Under the list:

- **Paste here** copies or moves the clipboard into this folder. A save folder pasted onto a memory card
  goes in the card's root, and a `.psu` pasted onto a memory card unpacks into its save.
- **Paste as PSU** turns each save folder on the clipboard (a folder with an `icon.sys`) into one `.psu`
  file here, the save file uLaunchELF, EMS and Apollo use. The saves themselves are not changed. Copy a
  save on a memory card, open a USB folder and Paste as PSU to back it up.
- **New folder**, named on the keyboard.

PSU files are read and written by the same code as [VMC Saves](VMC.md#saves-on-a-card), so the same checks
apply (a cut-short or badly named `.psu` is refused, a PSU is written whole before it gets its name).

## Safety

- Everything that changes a drive needs **Write Operations** on (Settings). With it off the File Manager
  only browses, copies to the clipboard and runs ELFs.
- The File Manager asks for the Parental Lock password when one is set.
- A name already in the target folder is never replaced: that entry is skipped, the rest still go, and the
  first one skipped is named afterwards.
- A copied file is read back for its size before it counts; a copy that stops part way (a full drive, a
  pulled card) removes the cut-short file.
- A move is a rename on the same drive. Across drives it is a copy, and the source is removed only once the
  whole copy is made; a copy that fails is taken back and the source stays.
- A folder is never copied or moved into itself, and a drive's root is never deleted.
- A file over 4 GB is refused before it starts on a FAT32 drive, and so is a file bigger than a BDM
  drive's free space.

## Different from RIPPS2

RIPPS2 draws its own screen with a grid of tiles, a search, a `.tar` browser, card-image (VMC) browsing and
ISO/CUE launching. This port keeps the file manager itself and leaves those out: card images have their own
[VMC Saves](VMC.md#saves-on-a-card) page, and games start from their pages. RIPPS2 asks before replacing a
name that is already there; here nothing is ever replaced.
