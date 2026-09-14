# apa-recovery

`apa_recover.py` diagnoses, and optionally repairs, a PS2 APA hard disk whose partition table root was damaged. That's the state wLaunchELF shows as **"Connected: YES / Formatted: NO"**, and RiptOPL reports as **code 402**.

In that state the games are almost always still on the disk. Every APA partition has its own header, and the partitions form a linked chain. When the chain is intact, the `__mbr` header at LBA 0 can be rebuilt from it. Background: [docs/APA-SAFETY.md](../../docs/APA-SAFETY.md).

**Do not format the disk.** Image it first if you can.

## Requirements

- Python 3.8 or newer, with no extra packages
- A SATA/IDE-to-USB adapter (or a spare SATA port)
- Administrator (Windows) or root (Linux/macOS) rights to open the raw disk

## Diagnose (read-only, the default)

```bash
python3 apa_recover.py /dev/sdX
```

```bash
python3 apa_recover.py disk.img
```

On Windows, from an Administrator prompt: `python apa_recover.py \\.\PhysicalDrive2`. Find the number in Disk Management; an APA disk shows as unallocated.

The report shows:
- whether LBA 0–7 would be accepted by ps2hdd, and what is wrong if not
- the partition chain: how many partitions, of which type, and a list of them
- whether the disk is **repairable**

Exit code 0 means healthy, 1 means damaged or not repairable, 2 means a usage or I/O error.

## Repair

```bash
python3 apa_recover.py /dev/sdX --repair
```

1. **Refuses** to go on if LBA 1 holds a GPT header (a GPT/APA hybrid), the chain is broken, or the backup file already exists.
2. **Backs up** the first 4 MB (`0x2000` sectors) to `apa_backup_<time>.bin`, or to `--backup FILE`. Unreadable sectors are saved as zeros and listed.
3. **Writes LBA 0–7 only**, as one 4 KB write:
   - A valid `__mbr` header is kept byte for byte. If only its links are wrong, only those are corrected.
   - A missing or damaged header is rebuilt: `next` = the first partition, `prev` = the last, the standard `__mbr` password, and a still-sane HDD-OSD boot area from the old header, if any.
   - LBA 2–5 are kept if readable; LBA 6–7 are zeroed.
4. **Verifies:** re-reads LBA 0–7, applies ps2hdd's own format check, and walks the whole chain again from the new header.

The disk is opened read-only for the whole diagnosis. Before anything is written, the tool shows the target (path, size and partition count) and asks you to type `REPAIR`; only then does it reopen the disk for writing. `--yes` skips that confirmation, so only use it when you are certain of the path.

A checksummed header whose `next` is 0 is taken as the real end of the chain, because deleting the last partition on a disk leaves that partition's old header in place. If an intact `__mbr` names a later last partition than the chain reaches, the tool refuses: the chain was cut short.

## Tests

`.github/scripts/test_apa_recover.py` runs the tool against synthetic APA images:
- healthy
- table sector wiped
- error sectors dirty
- bad checksum
- stale links
- broken chain
- GPT hybrid
- existing backup file

It checks that a rebuilt header passes the IOP driver's write fence and ps2hdd's format rules, and uses the password ps2sdk computes. It also checks that nothing outside LBA 0–7 ever changes.

Image-file operation has been tested on Linux and Windows. Raw-device access (`\\.\PhysicalDriveN`, `/dev/sdX`, `/dev/rdiskN` and the disk-size ioctls) has not been tested. Reports from real disks are welcome.
