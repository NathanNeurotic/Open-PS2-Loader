# APA hard disk safety

This page explains how RiptOPL protects an internal APA (PS2-formatted) hard disk. It also covers what to do if a disk shows up as **"Formatted: NO"**, or RiptOPL reports **code 402**.

**Short version:** RiptOPL's copy of the APA driver cannot write the one physical sector that holds the partition table, except to store a complete, valid table header. It never formats, never creates partitions and never writes error records. If a disk's table is damaged anyway, your games are almost certainly still on it. **Do not format it.** Use [`pc/apa-recovery`](../pc/apa-recovery/README.md).

## Why one sector matters

An APA disk is a chain of partitions. Each partition carries its own 1 KB header, and the chain starts at the `__mbr` header in LBA 0–1. The stock ps2sdk driver keeps two *error records* at LBA 6 and 7, in the same sector group.

Almost every modern hard disk is **Advanced Format 512e**. It presents 512-byte sectors but stores 4 KB physical sectors. So LBA 0–7 are **one physical sector** on the platter. If a write anywhere in that range is interrupted or misdirected, the drive can lose the whole physical sector. The disk then reads as unformatted:

- **wLaunchELF:** "Connected: YES / Formatted: NO"
- **RiptOPL:** code 402
- **HDD checkers:** can't help, because they need that sector to start

Every partition header, and every game, is untouched. The data is fine; only the root of the chain is gone.

## What happened

In September 2026 a tester's internal WD disk ended up in exactly that state after trying the RA rolling build. There was no disk image and no way to retest, so the analysis was done from source. The full review is in the description of the pull request that added this page.

- **RiptOPL's own code** only mounts partitions that already exist. Its one raw write is an HDL game's own header on rename. None of it writes LBA 0–7.
- **The drivers RiptOPL embedded from ps2sdk** do write there:
  - `ps2hdd` rewrites **LBA 6** (and flushes) whenever a partition header fails to read or checksum during a table walk.
  - `ps2fs` has **LBA 7** rewritten on *any* PFS disk error, including a bad checksum found by a plain read.
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
| **No table edits the loader doesn't need.** Refused: format, partition creation (including a stray `open(O_CREAT)` on `hdd0:`), sub-partition add/remove, OSD MBR changes, partition swaps. **Delete game** and **PS1 rename** still work. | `modules/hdd/apa/src/hdd_fio.c` |
| **Raw sector writes stay out of `__mbr`.** `HDIOC_WRITESECTOR` refuses any LBA inside the first 128 MB or off the disk. The partition transfer bounds check no longer wraps. | `hdd_fio.c` |
| **BDM (FAT/exFAT) never writes an APA disk's first 128 MB.** This also holds on APA + exFAT hybrids. | `modules/hdd/atad/src/ps2atad.c` |
| **Honest errors.** Code **402**: *"HDD found, but its APA partition table cannot be read. Do not format it -- your games may be recoverable."* It covers both a probe that reads garbage and a table ps2hdd rejects. 401 now means a drive that really did not answer. | `src/hddsupport.c` |
| **Flush on teardown.** An ATA FLUSH CACHE is sent after closing PFS files on every exit, power-off and launch. | `src/hddsupport.c`, `src/hdd.c` |
| **No raw `hdd0:` paths in new code.** CI fails if a file other than `hdd.c`, `hddsupport.c` or `opl.c` spells `hdd0:`/`hdd1:`, or anything calls `fileXioFormat`. | `.github/scripts/test_apa_table_safety.py` |

The driver is built from ps2sdk source. The unmodified copy builds **byte-identical** to the ps2sdk prebuilt, so every change is a reviewable diff; see `modules/hdd/apa/ORIGIN.txt`. `test_apa_table_safety.py` compiles the fences on the host, and fails if any of the policy above is lost in a future re-vendor.

## What it cannot guarantee

- **Other software** (wLaunchELF, HDD-OSD, PSBBN, PC tools) uses its own driver and does not get these protections.
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
2. **Delete game:**
   - delete an HDL game in the middle of the disk, and the **last** one (which rewrites LBA 0)
   - reboot, confirm both are gone, and confirm the remaining games still list
3. **PS1 partition rename**, then reboot.
4. **Exit to browser**, and **power off from the menu** while a cover is loading and while a list is still building. Reboot and confirm the disk still lists.
5. **Code 402:** zero LBA 0–7 on the test disk from a PC and boot. Confirm code 402 appears, and that nothing is written. Then recover the disk with `apa_recover.py --repair`, boot again, and confirm everything lists.
6. **APA + exFAT hybrid (APA-Jail):** confirm the exFAT side still mounts and saves settings.
