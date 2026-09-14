#!/usr/bin/env python3
"""apa_recover.py -- diagnose, and optionally repair, a PS2 APA hard disk whose partition table
root (the __mbr header, LBA 0-1) or error-record sectors (LBA 6-7) were damaged.

That is the "Connected: YES / Formatted: NO" state. It usually leaves every game intact: each APA
partition carries its own header, and the partitions tile the disk as a linked chain. When that
chain is still readable, the __mbr header can be rebuilt from it.

    python3 apa_recover.py IMAGE_OR_DISK              # read-only diagnosis (the default)
    python3 apa_recover.py IMAGE_OR_DISK --repair     # back up, then rebuild LBA 0-7 only

Disk paths: Windows \\\\.\\PhysicalDriveN (run as Administrator), Linux /dev/sdX (root), macOS
/dev/rdiskN (root). Image files work the same way, and are the safer place to practise.

The repair writes nothing but LBA 0-7, and only after saving the first 4 MB of the disk to a backup
file and proving the partition chain is complete. It refuses a GPT hybrid, a broken chain, or a disk
it cannot read cleanly. See docs/APA-SAFETY.md in the RiptOPL repository.
"""

import argparse
import datetime
import os
import struct
import sys

SECTOR = 512
HEADER_SECTORS = 2
TABLE_SECTORS = 8  # LBA 0-7: one physical sector on 512e drives
BACKUP_SECTORS = 0x2000  # first 4 MB: table, error records, journal and the __mbr reserved area
APA_MAGIC = 0x00415041
APAL_MAGIC = 0x4150414C
MBR_MAGIC = b'Sony Computer Entertainment Inc.'
MBR_VERSION = 2
MBR_DEFAULT_LENGTH = 0x40000  # 128 MB, what every formatter gives __mbr
MIN_PARTITION_ALIGN = 0x4000  # 8 MB, the smallest APA partition any tool creates
# ps2sdk apaEncryptPassword("__mbr", "sce_mbr"): DES-ECB, little-endian halves. Formatters built
# with APA_FORMAT_LOCK_MBR store it in both password fields of the __mbr header.
MBR_PASSWORD = bytes.fromhex('8bbd61617b39ffa5')

TYPE_NAMES = {0x0000: 'free', 0x0001: 'MBR', 0x0082: 'EXT2SWAP', 0x0083: 'EXT2', 0x0088: 'REISER',
              0x0100: 'PFS', 0x0101: 'CFS', 0x1337: 'HDL'}
FLAG_SUB = 0x0001


class Header:
    def __init__(self, lba, raw):
        self.lba = lba
        self.raw = raw
        (self.checksum, self.magic, self.next, self.prev) = struct.unpack_from('<4I', raw, 0)
        self.id = raw[0x10:0x30].split(b'\0', 1)[0].decode('ascii', 'replace')
        (self.start, self.length, self.type, self.flags, self.nsub) = struct.unpack_from('<IIHHI', raw, 0x40)
        (self.main, self.number) = struct.unpack_from('<II', raw, 0x58)
        self.mbr_magic = raw[0x100:0x120]
        (self.mbr_version, self.mbr_nsector) = struct.unpack_from('<II', raw, 0x120)
        (self.osd_start, self.osd_size) = struct.unpack_from('<II', raw, 0x130)

    @property
    def checksum_ok(self):
        return checksum(self.raw) == self.checksum

    @property
    def valid_partition(self):
        return self.magic == APA_MAGIC and self.checksum_ok and self.start == self.lba and self.length != 0

    @property
    def valid_mbr(self):
        # ps2hdd's apaReadHeader(LBA 0): magic, full 1 KB checksum, Sony MBR magic.
        return self.magic == APA_MAGIC and self.checksum_ok and self.mbr_magic == MBR_MAGIC

    def describe(self):
        kind = TYPE_NAMES.get(self.type, '0x%04x' % self.type)
        sub = ' sub#%d of %#x' % (self.number, self.main) if self.flags & FLAG_SUB else ''
        return '%#010x  %6d MB  %-8s %s%s' % (self.start, self.length // 2048, kind, self.id or '(free)', sub)


def checksum(raw):
    words = struct.unpack_from('<256I', raw, 0)
    return sum(words[1:]) & 0xFFFFFFFF


class Disk:
    def __init__(self, path, writable, sectors=None):
        self.path = path
        flags = os.O_RDWR if writable else os.O_RDONLY
        flags |= getattr(os, 'O_BINARY', 0)
        self.fd = os.open(path, flags)
        self.total = sectors if sectors else self._detect_sectors()
        # APA addresses sectors with 32-bit LBAs.
        self.apa_total = min(self.total, 0x100000000)

    def _detect_sectors(self):
        if os.path.isfile(self.path):
            return os.path.getsize(self.path) // SECTOR
        if sys.platform == 'win32':
            import ctypes
            import msvcrt
            handle = msvcrt.get_osfhandle(self.fd)
            out = ctypes.c_longlong(0)
            returned = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(handle), 0x0007405C, None, 0,
                                                        ctypes.byref(out), 8, ctypes.byref(returned), None)
            if ok:
                return out.value // SECTOR
        elif sys.platform == 'darwin':
            import fcntl
            count = fcntl.ioctl(self.fd, 0x40086419, b'\0' * 8)  # DKIOCGETBLOCKCOUNT
            size = fcntl.ioctl(self.fd, 0x40046418, b'\0' * 4)  # DKIOCGETBLOCKSIZE
            return struct.unpack('<Q', count)[0] * struct.unpack('<I', size)[0] // SECTOR
        else:
            end = os.lseek(self.fd, 0, os.SEEK_END)
            if end > 0:
                return end // SECTOR
        raise SystemExit('Cannot determine the size of %s; pass --sectors N.' % self.path)

    def read(self, lba, count):
        """Returns the bytes, or None if the range is unreadable or past the end of the disk."""
        if lba + count > self.total:
            return None
        try:
            os.lseek(self.fd, lba * SECTOR, os.SEEK_SET)
            data = b''
            while len(data) < count * SECTOR:
                chunk = os.read(self.fd, count * SECTOR - len(data))
                if not chunk:
                    return None
                data += chunk
            return data
        except OSError:
            return None

    def write(self, lba, data):
        assert len(data) % SECTOR == 0
        assert lba + len(data) // SECTOR <= TABLE_SECTORS, 'this tool only ever writes LBA 0-7'
        os.lseek(self.fd, lba * SECTOR, os.SEEK_SET)
        written = os.write(self.fd, data)
        if written != len(data):
            raise OSError('short write: %d of %d bytes' % (written, len(data)))
        os.fsync(self.fd)

    def header(self, lba):
        raw = self.read(lba, HEADER_SECTORS)
        return Header(lba, raw) if raw is not None else None

    def close(self):
        os.close(self.fd)


def format_check(sectors_0_7):
    """ps2hdd's apaGetFormat: a valid MBR header, and no nonzero dword in LBA 6-7 except the first of
    each sector (the error LBAs themselves)."""
    header = Header(0, sectors_0_7[:1024])
    words = struct.unpack_from('<256I', sectors_0_7, 6 * SECTOR)
    dirty = [i for i in range(256) if (i & 0x7F) and words[i]]
    return header.valid_mbr and not dirty, header, dirty


def find_first_partition(disk, header0):
    candidates = []
    if header0 is not None and header0.valid_mbr and header0.next:
        candidates.append(header0.next)
    if header0 is not None and header0.magic == APA_MAGIC and 0 < header0.length < disk.apa_total:
        candidates.append(header0.length)
    candidates.append(MBR_DEFAULT_LENGTH)
    candidates += [MIN_PARTITION_ALIGN * k for k in range(1, 129)]
    seen = set()
    for lba in candidates:
        if lba in seen or lba >= disk.apa_total:
            continue
        seen.add(lba)
        h = disk.header(lba)
        if h is not None and h.valid_partition and h.prev == 0:
            return h
    return None


def walk_chain(disk, first, notes=None):
    if first is None:
        return [], 'no first partition header'
    chain = [first]
    seen = {first.lba}
    current = first
    while current.next != 0:
        nxt = current.next
        if nxt >= disk.apa_total:
            return chain, 'partition %s at %#x links past the end of the disk (%#x)' % (current.id, current.lba, nxt)
        if nxt in seen:
            return chain, 'the chain loops back to %#x' % nxt
        if nxt != current.start + current.length and notes is not None:
            # Formatters tile the disk, so this is unusual -- but ps2hdd only follows next, so it is
            # not a reason to refuse.
            notes.append('partition at %#x links to %#x rather than to its end %#x' % (current.lba, nxt, current.start + current.length))
        h = disk.header(nxt)
        if h is None:
            return chain, 'the header at %#x cannot be read' % nxt
        if not h.valid_partition:
            return chain, 'the header at %#x is damaged (magic/checksum/start)' % nxt
        if h.prev != current.lba:
            return chain, 'the header at %#x does not link back to %#x' % (nxt, current.lba)
        chain.append(h)
        seen.add(nxt)
        current = h
    return chain, None


def relink_mbr(old, first, last):
    """A valid __mbr whose links disagree with the chain: fix only the links, keep everything else."""
    raw = bytearray(old.raw)
    struct.pack_into('<II', raw, 0x08, first.lba, last.lba)
    struct.pack_into('<I', raw, 0, checksum(raw))
    return bytes(raw)


def build_mbr(first, last, old):
    raw = bytearray(1024)
    struct.pack_into('<4I', raw, 0, 0, APA_MAGIC, first.lba, last.lba)
    raw[0x10:0x15] = b'__mbr'
    raw[0x30:0x38] = MBR_PASSWORD  # rpwd
    raw[0x38:0x40] = MBR_PASSWORD  # fpwd
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)  # ps2sdk stores JST
    stamp = struct.pack('<BBBBBBH', 0, now.second, now.minute, now.hour, now.day, now.month, now.year)
    struct.pack_into('<IIHHI', raw, 0x40, 0, first.lba, 0x0001, 0, 0)
    raw[0x50:0x58] = stamp
    raw[0x100:0x120] = MBR_MAGIC
    struct.pack_into('<II', raw, 0x120, MBR_VERSION, 0)
    raw[0x128:0x130] = stamp
    # Keep an installed HDD-OSD boot location when the damaged header still names a sane one.
    if old is not None and old.magic == APA_MAGIC and old.osd_start and old.osd_size:
        if 263 <= old.osd_start and old.osd_start + old.osd_size <= first.lba:
            struct.pack_into('<II', raw, 0x130, old.osd_start, old.osd_size)
    struct.pack_into('<I', raw, 0, checksum(raw))
    return bytes(raw)


def backup(disk, path):
    sectors = min(BACKUP_SECTORS, disk.total)
    data = bytearray()
    bad = []
    for lba in range(0, sectors, 256):
        count = min(256, sectors - lba)
        chunk = disk.read(lba, count)
        if chunk is None:
            chunk = bytearray()
            for s in range(lba, lba + count):
                one = disk.read(s, 1)
                if one is None:
                    bad.append(s)
                    one = b'\0' * SECTOR
                chunk += one
        data += chunk
    with open(path, 'xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('device', help='disk or image to inspect')
    parser.add_argument('--repair', action='store_true', help='rebuild LBA 0-7 after a backup (writes!)')
    parser.add_argument('--backup', help='backup file for --repair (default: apa_backup_<time>.bin)')
    parser.add_argument('--yes', action='store_true', help='do not ask for confirmation before repairing')
    parser.add_argument('--sectors', type=int, help='disk size in sectors, if it cannot be detected')
    args = parser.parse_args(argv)

    disk = Disk(args.device, writable=args.repair, sectors=args.sectors)
    try:
        return run(disk, args)
    finally:
        disk.close()


def run(disk, args):
    print('Disk: %s, %d sectors (%.1f GB)' % (disk.path, disk.total, disk.total * SECTOR / 1e9))

    table = disk.read(0, TABLE_SECTORS)
    header0 = Header(0, table[:1024]) if table is not None else None
    problems = []
    if table is None:
        problems.append('LBA 0-7 cannot be read (a damaged physical sector)')
        formatted = False
        dirty = []
    else:
        formatted, header0, dirty = format_check(table)
        if not header0.valid_mbr:
            if header0.magic != APA_MAGIC:
                problems.append('LBA 0 holds no APA header (%s)' % ('all zero' if not any(table[:1024]) else 'unrecognized data'))
            elif not header0.checksum_ok:
                problems.append('the __mbr header checksum is wrong')
            else:
                problems.append('the __mbr header lacks the Sony MBR magic')
        if dirty:
            problems.append('LBA 6-7 hold data in %d position(s) where ps2hdd expects zero' % len(dirty))
        if table[SECTOR:SECTOR + 8] == b'EFI PART':
            print('\nLBA 1 holds a GPT header: this is a GPT/APA hybrid. This tool does not handle those.')
            return 1

    first = find_first_partition(disk, header0)
    if first is None:
        print('\nPartition table root (LBA 0-7):', 'readable' if formatted else 'DAMAGED')
        for problem in problems:
            print('  - ' + problem)
        print('\nNo valid first partition header was found after __mbr. Nothing here can be rebuilt safely.')
        return 1
    notes = []
    chain, broken = walk_chain(disk, first, notes)
    for note in notes[:8]:
        print('  note: ' + note)
    last = chain[-1]
    mains = [h for h in chain if not h.flags & FLAG_SUB]
    print('\nPartition chain from %#x: %d header(s), %d partition(s), %s' %
          (first.lba, len(chain), len(mains), 'BROKEN: ' + broken if broken else 'complete'))
    counts = {}
    for h in mains:
        counts[TYPE_NAMES.get(h.type, 'other')] = counts.get(TYPE_NAMES.get(h.type, 'other'), 0) + 1
    print('  ' + ', '.join('%d %s' % (n, k) for k, n in sorted(counts.items())))
    for h in mains[:40]:
        print('  ' + h.describe())
    if len(mains) > 40:
        print('  ... and %d more' % (len(mains) - 40))

    if header0 is not None and header0.valid_mbr and not broken:
        if header0.next != first.lba or header0.prev != last.lba:
            problems.append('__mbr links (next %#x, prev %#x) disagree with the chain (%#x .. %#x)' %
                            (header0.next, header0.prev, first.lba, last.lba))
            formatted = False

    print('\nPartition table root (LBA 0-7):', 'OK -- ps2hdd will accept this disk' if formatted and not problems else 'DAMAGED')
    for problem in problems:
        print('  - ' + problem)

    if formatted and not problems:
        print('\nNothing to repair.')
        return 0
    if broken:
        print('\nThe chain is broken, so the table cannot be rebuilt safely. Keep the disk as it is and image it.')
        return 1
    if not args.repair:
        print('\nRepairable: every partition above is intact. Run again with --repair to rebuild LBA 0-7.')
        print('Do NOT format this disk.')
        return 1

    mbr_valid = header0 is not None and header0.valid_mbr
    if mbr_valid and header0.next == first.lba and header0.prev == last.lba:
        new_header, action = header0.raw, 'existing __mbr header kept'
    elif mbr_valid:
        new_header, action = relink_mbr(header0, first, last), '__mbr links corrected (next %#x, prev %#x)' % (first.lba, last.lba)
    else:
        new_header, action = build_mbr(first, last, header0), 'new __mbr header (next %#x, prev %#x)' % (first.lba, last.lba)
    middle = table[1024:6 * SECTOR] if table is not None else b'\0' * (4 * SECTOR)
    new_table = new_header + middle + b'\0' * (2 * SECTOR)

    backup_path = args.backup or datetime.datetime.now().strftime('apa_backup_%Y%m%d_%H%M%S.bin')
    if os.path.exists(backup_path):
        print('\nThe backup file %s already exists; choose another with --backup. Nothing was written.' % backup_path)
        return 1
    print('\nPlan:')
    print('  1. save the first %d sectors to %s' % (min(BACKUP_SECTORS, disk.total), backup_path))
    print('  2. write LBA 0-7: %s, LBA 6-7 zeroed' % action)
    print('  3. re-read and verify with the same checks ps2hdd applies')
    if not args.yes:
        if input('Type REPAIR to continue: ').strip() != 'REPAIR':
            print('Aborted; nothing was written.')
            return 1

    bad = backup(disk, backup_path)
    print('Backup written%s.' % (' (%d unreadable sector(s) saved as zeros: %s)' % (len(bad), bad[:16]) if bad else ''))
    disk.write(0, new_table)

    verify = disk.read(0, TABLE_SECTORS)
    ok, verified, dirty = format_check(verify) if verify is not None else (False, None, [])
    chain2, broken2 = walk_chain(disk, disk.header(verified.next)) if ok and verified.next else ([], 'no chain')
    if not broken2 and chain2 and chain2[0].prev != 0:
        broken2 = 'the __mbr no longer points at the first partition'
    if ok and not broken2 and len(chain2) == len(chain):
        print('Repaired and verified: ps2hdd will accept this disk, and all %d partition(s) are linked.' % len(mains))
        return 0
    print('Verification FAILED (%s). The original sectors are in %s.' % (broken2 or 'format check', backup_path))
    return 1


if __name__ == '__main__':
    sys.exit(main())
