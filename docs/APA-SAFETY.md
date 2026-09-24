# APA hard disk safety

This page explains how RiptOPL protects an internal APA (PS2-formatted) hard disk. It also covers what to do if a disk shows up as **"Formatted: NO"**, or RiptOPL reports **code 402**.

**Short version:** RiptOPL is a game loader, not a partition manager. It writes only inside PFS partitions and never edits the APA partition table: its driver refuses formatting, creating, deleting or renaming partitions, and raw sector writes, and it never writes error records. If a disk's table is damaged anyway, your games are almost certainly still on it. **Do not format it.** Use [`pc/apa-recovery`](../pc/apa-recovery/README.md).

## Why LBA 0–7 matter

An APA disk is a chain of partitions. Each partition carries its own 1 KB header, and the chain starts at the `__mbr` header in LBA 0–1. The stock ps2sdk driver also keeps two APA *error records* at LBA 6 and 7, in the same reserved area. They are part of APA's own bookkeeping, not a filesystem.

Almost every modern hard disk is **Advanced Format 512e**: the PS2 addresses ordinary 512-byte logical sectors, and the drive's firmware maps them onto 4 KB physical sectors, so logical LBA 0–7 share one physical sector. Whether an interrupted write there can take its neighbours with it depends on the firmware, and it could not be proven for the disk below. What is certain is that losing LBA 0–1 makes the disk read as unformatted:

- **wLaunchELF:** "Connected: YES / Formatted: NO"
- **RiptOPL:** code 402
- **HDD checkers:** can't help, because they need that sector to start

Every partition header, and every game, is untouched. The data is fine; only the root of the chain is gone.

## What happened

In September 2026 a tester's internal WD disk ended up in exactly that state after trying the RA rolling build. There was no disk image and no way to retest, so the analysis was done from source. The full review is in the description of the pull request that added this page.

- **RiptOPL's own code** only mounts partitions that already exist, and none of it writes LBA 0–7. It did edit APA structures elsewhere: *Delete game* removed a partition (rewriting its neighbours' headers, and LBA 0 for the last one), HDL rename rewrote the game's HDL header, and renaming a one-game `PP.*` PS1 install rewrote its partition header. All three are gone.
- **The drivers RiptOPL embedded from ps2sdk** do write there:
  - `ps2hdd` rewrites the **LBA 6** error record (and flushes) whenever a partition header fails to read or checksum during a table walk.
  - PFS asks `ps2hdd` to set the **LBA 7** error record on *any* PFS disk error, including a bad checksum found by a plain read.
  - Creating or deleting a partition rewrites **LBA 0**.
- **Error records are written when something is already failing:** a drive that isn't ready, a read error, a teardown. Those are the moments a user reaches for the power button.
- **Latent SDK bugs sat on those same error paths:**
  - a NULL dereference that writes garbage to LBA 7 once the driver cache is exhausted
  - a cache leak on failed reads
  - a partition bounds check that wraps in 32-bit arithmetic
- **The message was misleading.** A drive whose table would not validate was reported as *"HardDisk Drive not detected"* (401). That sends people to delete configs and re-run tools, and eventually to format.

The exact trigger on that disk cannot be proven without the disk. The fix is therefore built to close off every path that can write that sector, not one guessed cause.

## What this build guarantees

| Protection | Where |
| --- | --- |
| **Table write fence.** Every APA driver transfer is checked. The only write allowed into LBA 0–7 is a complete, checksummed `__mbr` header at LBA 0: magic, full 1 KB checksum, Sony MBR magic, `__mbr` id, start 0, links inside the disk. Everything else is refused before it reaches the drive. | `modules/hdd/apa/src/table_fence.h`, `table_fence.c` |
| **No error records.** LBA 6/7 are never written; the events are logged instead. | `modules/hdd/apa/src/apa.c` |
| **No APA writes from the loader.** Every APA edit is refused: format, partition creation (including a stray `open(O_CREAT)` on `hdd0:`), partition delete and rename, sub-partition add/remove, OSD MBR changes, partition swaps, and raw sector writes (`HDIOC_WRITESECTOR`). The driver no longer repairs a broken back-link on its own while walking the chain either; it logs it. Nothing left in this build writes a partition header, so the fence above is a backstop. The HDD page offers no Delete, and no Rename for PS2 games; a one-game `PP.*` PS1 install says it can't be renamed. Loose VCDs and Ember folders still rename, because that is a PFS write inside their partition. | `modules/hdd/apa/src/hdd_fio.c`, `src/hddsupport.c` |
| **Bounded reads of corrupt headers.** A partition claiming more than 64 sub-partitions is refused: the header has exactly 64 sub slots, so a larger count is corruption, and the SDK would index past the array. The partition transfer bounds check no longer wraps. | `hdd_fio.c` |
| **4Kn drives are refused.** A drive whose *logical* sectors are not 512 bytes (IDENTIFY word 106) gets no sector I/O at all, since every driver here counts in 512-byte sectors; on the exFAT side it shows code 500. 512e drives are unaffected. | `modules/hdd/atad/src/ps2atad.c` |
| **No wrapped addresses.** The ATA driver refuses any request past the drive's capacity. On drives without LBA48 (up to 137 GB), a sector at or above 2^28 used to wrap silently to the start of the disk. | `modules/hdd/atad/src/ps2atad.c` |
| **GPT/APA hybrids are left alone.** A disk with a GPT header at LBA 1 is treated as a GPT disk: this build's APA driver cannot read that layout, so it is never loaded on it. | `src/hddsupport.c` |
| **BDM (FAT/exFAT) never writes an APA disk's first 128 MB.** "APA disk" means LBA 0 carries the APA magic, or LBA 0 can't be read (then the write is refused too). This also holds on APA + exFAT hybrids. A disk whose header is wiped has no MBR/GPT for BDM to mount, so nothing writes it either way. | `modules/hdd/atad/src/ps2atad.c` |
| **Honest errors.** Code **402**: *"HDD found, but its APA partition table cannot be read. Do not format it -- your games may be recoverable."* It covers both a probe that reads garbage and a table ps2hdd rejects. 401 now means a drive that really did not answer. | `src/hddsupport.c` |
| **Flush on teardown.** An ATA FLUSH CACHE is sent after closing PFS files on exit, power-off and launches from the HDD. Launches from other devices skip it so an idle disk isn't spun up. | `src/hddsupport.c`, `src/hdd.c` |
| **No raw `hdd0:` paths in new code.** CI fails if a file other than `hdd.c`, `hddsupport.c` or `opl.c` spells `hdd0:`/`hdd1:`, or anything calls `fileXioFormat`. | `.github/scripts/test_apa_table_safety.py` |

The driver is built from ps2sdk source. The unmodified copy builds **byte-identical** to the ps2sdk prebuilt, so every change is a reviewable diff; see `modules/hdd/apa/ORIGIN.txt`. `test_apa_table_safety.py` compiles the fences on the host, and fails if any of the policy above is lost in a future re-vendor.

## What it cannot guarantee

- **Other software** (wLaunchELF, HDD-OSD, PSBBN, PC tools) uses its own driver and does not get these protections.
- **GPT/APA hybrid disks** are not supported by this build's APA driver, and their APA side does not list.
- **A power cut inside a partition** can still damage what was being written there, such as a PFS journal or a config file. PFS replays its journal on the next mount; the partition table itself is not at risk.
- **A failing drive** fails regardless. Recovery starts with imaging the disk.
- **None of this has been through a hardware power-cut test yet.** See the checklist below.

## If your disk shows "Formatted: NO" or code 402

1. **Stop.** Do not format, "initialize", or run repair tools that write. Every write is a risk until you have a copy.
2. **Connect the disk to a PC** with a SATA/IDE adapter. If you have the space, image the whole disk first (for example with `dd`, or Win32 Disk Imager's *Read*). At minimum the tool saves the first 4 MB for you.
3. **Diagnose** (read-only):

   ```bash
   python3 pc/apa-recovery/apa_recover.py /dev/sdX
   ```

   On Windows, run as Administrator: `python apa_recover.py \\.\PhysicalDrive2`. Pick the right disk number in Disk Management; the APA disk shows as unallocated.

   It reports what is wrong with LBA 0–7, and walks the partition chain to list your partitions.
4. **Repair**, if it says *Repairable*:

   ```bash
   python3 pc/apa-recovery/apa_recover.py /dev/sdX --repair
   ```

   It backs up the first 4 MB, then rewrites **only** LBA 0–7:
   - an unreadable or garbage table gets a rebuilt `__mbr` header
   - a valid header with wrong links has only its links corrected
   - LBA 6–7 are zeroed

   It re-reads the result and checks it with the same rules ps2hdd applies. It refuses GPT hybrids, broken chains, and anything it cannot verify.

If the chain itself is broken (a damaged header in the middle), the tool stops and says so. Keep the disk and the image; that needs a different kind of recovery.

## Hardware verification checklist (maintainers)

Use a disposable APA disk with PS2 games, POPS containers, an Ember partition and a `+OPL` data home.

1. **Boot, list, launch:** HDL, POPS and Ember titles, plus Neutrino with its install on `+OPL`. The IOP log must show no `refused` lines.
2. **No partition edits:** the Triangle menu on an HDD PS2 game has no Rename or Delete. Renaming a one-game `PP.*` PS1 title shows the "own APA partition" message and changes nothing. Renaming a loose VCD in `__.POPS` and an Ember title still works after a reboot.
3. **4Kn drive** (if available): an internal 4Kn disk formatted exFAT shows code 500, and one formatted APA is not detected. Neither is written to.
4. **Exit to browser**, and **power off from the menu** while a cover is loading and while a list is still building. Reboot and confirm the disk still lists.
5. **Code 402:** zero LBA 0–7 on the test disk from a PC and boot. Confirm code 402 appears, and that nothing is written. Then recover the disk with `apa_recover.py --repair`, boot again, and confirm everything lists.
6. **APA + exFAT hybrid (APA-Jail):** confirm the exFAT side still mounts and saves settings. Launched from APA (for example PSBBN's `hdd0:__system:pfs:/launcher/OPNPS2LD.ELF`), RiptOPL should home its settings on the exFAT root; with RiptOPL settings already on exFAT it must not mount PFS at all. See [Auto Loading global settings](AUTOLAUNCH-GLOBAL-SETTINGS.md).
