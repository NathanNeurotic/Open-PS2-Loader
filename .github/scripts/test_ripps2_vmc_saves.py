"""VMC saves (RIPPS2's card-image saves, akilluminati47): src/vmcsaves.c on the host.

Cards are formatted the way modules/vmc/genvmc lays them out (and once with the ECC spare, as PCSX2 writes
a .ps2). The real vmcsaves.c lists, imports, exports and deletes; after every change an independent checker
written here from the card format walks the image: every used cluster belongs to exactly one chain, every
chain ends, every entry's size fits its chain, and the free count adds up.

1. An empty card lists nothing; its free space is the whole allocatable area.
2. Import a folder save: it lists with its icon.sys title; the files read back byte for byte; the root grows
   into a new cluster (two entries fill a 1 KB cluster).
3. Export it to a folder: the same files, the same bytes. Exporting again refuses (-1), and so does importing a
   save whose name is already on the card.
4. Delete it: the slot stays empty, every cluster it held is free again, and the next import reuses the slot.
5. A save bigger than the free space is refused before anything is written: the image is unchanged.
6. An ECC image lists and exports, but refuses import and delete.
7. Titles: full-width Shift-JIS letters become ASCII, kana are dropped, half-width katakana are one byte.
8. PSU (RIPPS2): a save copied out as one .psu reads back with an independent reader (entries, 0xFF padding to
   1 KB, nothing after); it lists beside the folders by the save inside it; it copies back in byte for byte, as
   does a PSU written from the format alone; a cut-short, foreign or badly named PSU is refused untouched.
"""
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
SRC = root / ('src/vmcsaves.c' if (root / 'src/vmcsaves.c').exists() else 'src/core/vmcsaves.cpp')
CS, PAGE, PPC = 1024, 512, 2


def make_card(size_mb, ecc=False):
    """genvmc.c's format: superblock, one indirect FAT cluster per 256 FAT clusters, the FAT, the root."""
    clusters = size_mb * 1024
    blocksize, cpb = 16, 8
    fat_length = ((clusters * 4 - 1) // CS) + 1
    ifc_length = ((fat_length * 4 - 1) // CS) + 1
    img = bytearray(b'\xFF' * (clusters * CS))
    ifc_list = list(range(blocksize // 2, blocksize // 2 + ifc_length))
    i = blocksize // 2 + ifc_length
    ifc = bytearray(ifc_length * CS)
    for j in range(fat_length):
        struct.pack_into('<I', ifc, 4 * j, i + j)
    for z, c in enumerate(ifc_list):
        img[c * CS:(c + 1) * CS] = ifc[z * CS:(z + 1) * CS]
    fat_first = i
    alloc_offset = i + fat_length
    last = (clusters // cpb - 2) * cpb
    alloc_end = last - alloc_offset
    for k in range(fat_length):
        block = bytearray(CS)
        for b in range(256):
            n = k * 256 + b
            if n < alloc_end:
                struct.pack_into('<I', block, 4 * b, 0xFFFFFFFF if n == 0 else 0x7FFFFFFF)
        img[(fat_first + k) * CS:(fat_first + k + 1) * CS] = block
    rootc = bytearray(CS)
    stamp = struct.pack('<BBBBBBH', 0, 1, 2, 3, 4, 5, 2026)
    for idx, (mode, name) in enumerate(((0x8427, b'.'), (0xA426, b'..'))):
        e = bytearray(512)
        struct.pack_into('<HHI', e, 0, mode, 0, 2)
        e[8:16] = stamp
        e[0x18:0x20] = stamp
        e[0x40:0x40 + len(name)] = name
        rootc[idx * 512:(idx + 1) * 512] = e
    img[alloc_offset * CS:(alloc_offset + 1) * CS] = rootc
    sb = bytearray(CS)
    sb[0:28] = b'Sony PS2 Memory Card Format '
    sb[28:35] = b'1.2.0.0'
    struct.pack_into('<HHHH', sb, 0x28, PAGE, PPC, blocksize, 0)
    struct.pack_into('<IIII', sb, 0x30, clusters, alloc_offset, alloc_end, 0)
    for k in range(32):
        struct.pack_into('<I', sb, 0x50 + 4 * k, ifc_list[k] if k < ifc_length else 0xFFFFFFFF)
    img[0:CS] = b'\xFF' * CS
    img[0:0x154] = sb[0:0x154]
    if not ecc:
        return bytes(img)
    out = bytearray()
    for p in range(len(img) // PAGE):
        out += img[p * PAGE:(p + 1) * PAGE] + b'\x00' * 16
    return bytes(out)


class Card:
    """An independent reader of the format, to check what vmcsaves.c wrote."""

    def __init__(self, data):
        self.data = data
        sb = data[:0x154]
        assert sb[:28] == b'Sony PS2 Memory Card Format '
        self.page, self.ppc = struct.unpack_from('<HH', sb, 0x28)
        self.clusters, self.alloc, self.alloc_end, self.root = struct.unpack_from('<IIII', sb, 0x30)
        self.raw = PAGE + 16 if len(data) >= self.clusters * self.ppc * (PAGE + 16) else PAGE
        ifc = [struct.unpack_from('<I', sb, 0x50 + 4 * k)[0] for k in range(32)]
        n = (self.alloc_end + 255) // 256
        self.fat = []
        for k in range(n):
            ind = self.cluster_abs(ifc[k // 256])
            fc = struct.unpack_from('<I', ind, 4 * (k % 256))[0]
            self.fat += list(struct.unpack('<256I', self.cluster_abs(fc)))
        self.fat = self.fat[:self.alloc_end]

    def cluster_abs(self, c):
        out = b''
        for p in range(self.ppc):
            at = (c * self.ppc + p) * self.raw
            out += self.data[at:at + PAGE]
        return out

    def chain(self, c):
        seen = []
        while True:
            assert 0 <= c < self.alloc_end, 'chain leaves the card'
            assert c not in seen, 'chain loops'
            seen.append(c)
            e = self.fat[c]
            assert e & 0x80000000, 'chain runs into a free cluster'
            if e == 0xFFFFFFFF:
                return seen
            c = e & 0x7FFFFFFF

    def entries(self, first, count):
        ch = self.chain(first)
        blob = b''.join(self.cluster_abs(self.alloc + c) for c in ch)
        assert count * 512 <= len(blob), 'a folder claims more entries than its chain holds'
        return [blob[i * 512:(i + 1) * 512] for i in range(count)], ch

    def read(self, first, size):
        ch = self.chain(first)
        assert len(ch) == max(1, (size + CS - 1) // CS), 'chain length does not match the size'
        return b''.join(self.cluster_abs(self.alloc + c) for c in ch)[:size], ch

    def check(self):
        """Every used cluster in exactly one chain; returns {save: {file: bytes}}."""
        owner = {}

        def claim(ch, what):
            for c in ch:
                assert c not in owner, 'cluster %d in %s and %s' % (c, owner[c], what)
                owner[c] = what

        dot = self.entries(self.root, 1)[0][0]
        count = struct.unpack_from('<I', dot, 4)[0]
        ents, ch = self.entries(self.root, count)
        claim(ch, 'root')
        saves = {}
        for e in ents[2:]:
            mode, _, length = struct.unpack_from('<HHI', e, 0)
            if not mode & 0x8000:
                continue
            assert mode & 0x20, 'a file in the root'
            name = e[0x40:0x60].split(b'\0')[0].decode()
            first = struct.unpack_from('<I', e, 0x10)[0]
            sub, sch = self.entries(first, length)
            claim(sch, name)
            assert sub[0][0x40:0x42] == b'.\0' and sub[1][0x40:0x43] == b'..\0'
            assert struct.unpack_from('<H', sub[1], 0)[0] == 0xA426, '".." as mcman writes it'
            files = {}
            for f in sub[2:]:
                fmode, _, flen = struct.unpack_from('<HHI', f, 0)
                if not fmode & 0x8000:
                    continue
                assert fmode == 0x8497
                fname = f[0x40:0x60].split(b'\0')[0].decode()
                if flen:
                    data, fch = self.read(struct.unpack_from('<I', f, 0x10)[0], flen)
                    claim(fch, name + '/' + fname)
                else:
                    data = b''
                files[fname] = data
            saves[name] = files
        used = {c for c, e in enumerate(self.fat) if e & 0x80000000}
        assert used == set(owner), 'clusters marked used that nothing names: %s' % sorted(used - set(owner))[:8]
        return saves

    def free_kb(self):
        return sum(1 for e in self.fat if not e & 0x80000000)


def icon_sys(title_sjis):
    sys_ = bytearray(964)
    sys_[0:4] = b'PS2D'
    sys_[0xC0:0xC0 + len(title_sjis)] = title_sjis
    sys_[0x104:0x104 + 8] = b'list.ico'
    return bytes(sys_)


def fullwidth(text):
    out = b''
    for ch in text:
        if 'A' <= ch <= 'Z':
            out += struct.pack('>H', 0x8260 + ord(ch) - ord('A'))
        elif 'a' <= ch <= 'z':
            out += struct.pack('>H', 0x8281 + ord(ch) - ord('a'))
        elif '0' <= ch <= '9':
            out += struct.pack('>H', 0x824F + ord(ch) - ord('0'))
        else:
            out += b'\x81\x40'
    return out


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "include/vmcsaves.h"
int main(int argc, char **argv)
{
    vmc_save_t list[16];
    unsigned int freeKb = 0;
    int n, i;
    const char *op = argv[1];
    (void)argc;
    if (!strcmp(op, "list") || !strcmp(op, "folder")) {
        n = !strcmp(op, "list") ? vmcSavesList(argv[2], list, 16, &freeKb) : vmcSavesListFolder(argv[2], list, 16);
        printf("%d %u %d", n, freeKb, vmcSavesError());
        for (i = 0; i < n; i++)
            printf("|%s=%s%s%s", list[i].name, list[i].title, list[i].file[0] ? "@" : "", list[i].file);
        printf("\n");
    } else if (!strcmp(op, "probe"))
        printf("%d\n", vmcSavesProbe(argv[2]));
    else if (!strcmp(op, "export"))
        {
        int r = vmcSavesExport(argv[2], argv[3], argv[4]);
        printf("%d %d\n", r, vmcSavesError());
    }
    else if (!strcmp(op, "import"))
        {
        int r = vmcSavesImport(argv[2], argv[3], argv[4]);
        printf("%d %d\n", r, vmcSavesError());
    }
    else if (!strcmp(op, "exportpsu"))
        {
        int r = vmcSavesExportPsu(argv[2], argv[3], argv[4]);
        printf("%d %d\n", r, vmcSavesError());
    }
    else if (!strcmp(op, "importpsu"))
        {
        int r = vmcSavesImportPsu(argv[2], argv[3]);
        printf("%d %d\n", r, vmcSavesError());
    }
    else if (!strcmp(op, "delete"))
        {
        int r = vmcSavesDelete(argv[2], argv[3]);
        printf("%d %d\n", r, vmcSavesError());
    }
    else if (!strcmp(op, "title")) {
        unsigned char sys[0xC0 + 68];
        char out[80];
        FILE *f = fopen(argv[2], "rb");
        if (f == NULL || fread(sys, 1, sizeof(sys), f) != sizeof(sys))
            return 1;
        fclose(f);
        vmcSavesTitle(sys, sizeof(sys), out, sizeof(out));
        printf("[%s]\n", out);
    }
    return 0;
}
'''

ERR = {'READ_ONLY': 3, 'NO_ROOM': 6, 'EXISTS': 8, 'NAME': 10, 'PSU': 12}


def psu_entry(mode, length, name, stamp=struct.pack('<BBBBBBH', 0, 9, 8, 7, 6, 5, 2025)):
    e = bytearray(512)
    struct.pack_into('<HHI', e, 0, mode, 0, length)
    e[8:16] = stamp
    e[0x18:0x20] = stamp
    e[0x40:0x40 + len(name)] = name.encode()
    return bytes(e)


def make_psu(save, files, extra_dir=False):
    """A PSU the way uLaunchELF writes one, from the format alone: folder entry, ".", "..", then each file's
    entry and its data padded with 0xFF to 1 KB."""
    count = len(files) + (1 if extra_dir else 0)
    out = psu_entry(0x8427, count + 2, save) + psu_entry(0x8427, 0, '.') + psu_entry(0x8427, 0, '..')
    if extra_dir:
        out += psu_entry(0x8427, 0, 'SUBDIR')  # a folder entry inside a save: no data follows it
    for name, data in files:
        out += psu_entry(0x8497, len(data), name) + data + b'\xFF' * ((-len(data)) % 1024)
    return out


def read_psu(blob):
    """The independent reader: (save name, entry count, {file: bytes}), checking the padding."""
    head = blob[:512]
    mode, _, count = struct.unpack_from('<HHI', head, 0)
    assert mode & 0x20 and count >= 2
    name = head[0x40:0x60].split(b'\0')[0].decode()
    assert blob[512 + 0x40:512 + 0x42] == b'.\0' and blob[1024 + 0x40:1024 + 0x43] == b'..\0'
    at, files = 1536, {}
    for _ in range(count - 2):
        fmode, _, flen = struct.unpack_from('<HHI', blob, at)
        assert fmode == 0x8497, hex(fmode)
        fname = blob[at + 0x40:at + 0x60].split(b'\0')[0].decode()
        at += 512
        files[fname] = blob[at:at + flen]
        pad = (-flen) % 1024
        assert blob[at + flen:at + flen + pad] == b'\xFF' * pad, 'data padded with 0xFF to 1 KB'
        at += flen + pad
    assert at == len(blob), 'nothing after the last file'
    return name, count, files

with tempfile.TemporaryDirectory(prefix='vmcsaves-') as t:
    t = Path(t)
    (t / 'include').mkdir()
    header = root / 'include/vmcsaves.h'
    (t / 'include/vmcsaves.h').write_text(header.read_text())
    (t / 'main.c').write_text(HARNESS)
    exe = t / 'vmcsaves'
    lang = ['-x', 'c++'] if SRC.suffix == '.cpp' else []
    compiler = 'g++' if SRC.suffix == '.cpp' else 'cc'
    std = '-std=gnu++17' if SRC.suffix == '.cpp' else '-std=gnu99'
    subprocess.run([compiler, std, '-Wall', '-Wextra', '-Werror', '-I', str(t)] + lang + [str(SRC), str(t / 'main.c'), '-o', str(exe)],
                   check=True)

    def run(*args):
        return subprocess.run([str(exe)] + [str(a) for a in args], check=True, capture_output=True, text=True).stdout.strip()

    card = t / 'card.bin'
    card.write_bytes(make_card(8))
    whole = Card(card.read_bytes())
    total_free = whole.free_kb()
    assert run('probe', card) == '1'

    # 1. empty
    assert run('list', card) == '0 %d 0' % total_free, run('list', card)
    assert whole.check() == {}

    # 2. import a folder save
    saves = t / 'SAVES'
    save = saves / 'BASLUS-20062GAME'
    save.mkdir(parents=True)
    files = {'icon.sys': icon_sys(fullwidth('Grand Theft') + b'\x81\x40' + fullwidth('Auto 3')),
             'list.ico': os.urandom(3000), 'BASLUS-20062GAME': os.urandom(1024 * 9 + 7), 'empty.dat': b''}
    for name, data in files.items():
        (save / name).write_bytes(data)
    assert run('import', saves.as_posix() + '/', 'BASLUS-20062GAME', card) == '1 0'
    got = Card(card.read_bytes()).check()
    assert got == {'BASLUS-20062GAME': files}, sorted(got)
    used = sum((len(d) + CS - 1) // CS for d in files.values()) + 3 + 1  # files, 6 entries = 3 clusters, the root's 2nd
    assert run('list', card) == '1 %d 0|BASLUS-20062GAME=Grand Theft Auto 3' % (total_free - used), run('list', card)

    # 3. export, then both refusals
    out = t / 'OUT'
    assert run('export', card, 'BASLUS-20062GAME', out.as_posix() + '/') == '1 0'
    for name, data in files.items():
        assert (out / 'BASLUS-20062GAME' / name).read_bytes() == data, name
    assert run('folder', out.as_posix() + '/') == '1 0 0|BASLUS-20062GAME=Grand Theft Auto 3'
    r = run('export', card, 'BASLUS-20062GAME', out.as_posix() + '/')
    assert r == '-1 %d' % ERR['EXISTS'], r
    before = hashlib.sha256(card.read_bytes()).hexdigest()
    assert run('import', saves.as_posix() + '/', 'BASLUS-20062GAME', card) == '-1 %d' % ERR['EXISTS']
    assert hashlib.sha256(card.read_bytes()).hexdigest() == before

    # 4. delete, then the slot is reused
    assert run('delete', card, 'BASLUS-20062GAME') == '1 0'
    after = Card(card.read_bytes())
    assert after.check() == {}
    assert after.free_kb() == total_free - 1, 'everything but the root\'s grown cluster is free again'
    (saves / 'BESLES-12345ABC').mkdir()
    (saves / 'BESLES-12345ABC' / 'data').write_bytes(b'x' * 100)
    assert run('import', saves.as_posix() + '/', 'BESLES-12345ABC', card) == '1 0'
    assert Card(card.read_bytes()).check() == {'BESLES-12345ABC': {'data': b'x' * 100}}
    raw = Card(card.read_bytes())
    ents, _ = raw.entries(raw.root, 3)
    assert ents[2][0x40:0x50].startswith(b'BESLES-12345ABC'), 'the deleted save\'s slot is reused'

    # 5. too big for the card: refused, nothing written
    (saves / 'BIG').mkdir()
    (saves / 'BIG' / 'a').write_bytes(b'\0' * (4 * 1024 * 1024))
    (saves / 'BIG' / 'b').write_bytes(b'\0' * (4 * 1024 * 1024 - 1))
    before = hashlib.sha256(card.read_bytes()).hexdigest()
    assert run('import', saves.as_posix() + '/', 'BIG', card) == '0 %d' % ERR['NO_ROOM']
    assert hashlib.sha256(card.read_bytes()).hexdigest() == before

    # 6. ECC: read only
    eccCard = t / 'card.ps2'
    eccCard.write_bytes(make_card(8, ecc=True))
    assert run('probe', eccCard) == '2'
    before = hashlib.sha256(eccCard.read_bytes()).hexdigest()
    assert run('import', saves.as_posix() + '/', 'BESLES-12345ABC', eccCard) == '0 %d' % ERR['READ_ONLY']
    assert run('delete', eccCard, 'X') == '0 %d' % ERR['READ_ONLY']
    assert hashlib.sha256(eccCard.read_bytes()).hexdigest() == before
    assert run('list', eccCard).startswith('0 ')

    # a bigger card (more than one FAT cluster per indirect cluster entry) round-trips too
    big = t / 'big.bin'
    big.write_bytes(make_card(32))
    assert run('import', saves.as_posix() + '/', 'BASLUS-20062GAME', big) == '1 0'
    assert Card(big.read_bytes()).check() == {'BASLUS-20062GAME': files}

    # 7. titles
    sysf = t / 'title.sys'
    sysf.write_bytes(icon_sys(fullwidth('Kingdom ') + b'\x82\xa0' + b'\xb1\xb2' + fullwidth('Hearts') + b'!?'))
    assert run('title', sysf) == '[Kingdom Hearts!?]', run('title', sysf)
    hdr = bytearray(icon_sys(fullwidth('Line') + fullwidth('Two')))
    struct.pack_into('<H', hdr, 6, 8)  # the second line starts at byte 8
    sysf.write_bytes(bytes(hdr))
    assert run('title', sysf) == '[Line Two]', run('title', sysf)
    assert run('probe', sysf) == '0'

    # 8. PSU (RIPPS2): copy out as one .psu file and back in, checked against an independent reader and writer
    pcard = t / 'psu.bin'
    pcard.write_bytes(make_card(8))
    assert run('import', saves.as_posix() + '/', 'BASLUS-20062GAME', pcard) == '1 0'
    pdir = t / 'PSUOUT'
    assert run('exportpsu', pcard, 'BASLUS-20062GAME', pdir.as_posix() + '/') == '1 0'
    psu = pdir / 'BASLUS-20062GAME.psu'
    name, count, got = read_psu(psu.read_bytes())
    assert (name, count, got) == ('BASLUS-20062GAME', len(files) + 2, files), (name, count, sorted(got))
    assert sorted(p.name for p in pdir.iterdir()) == ['BASLUS-20062GAME.psu'], 'no .tmp left behind'
    assert run('exportpsu', pcard, 'BASLUS-20062GAME', pdir.as_posix() + '/') == '-1 %d' % ERR['EXISTS']
    # listed beside the folders by the save inside it, with its title, and copied in by its file name
    (pdir / 'AFOLDER').mkdir()
    (pdir / 'AFOLDER' / 'x').write_bytes(b'1')
    (pdir / 'notes.txt').write_bytes(b'not a save')
    (pdir / 'junk.psu').write_bytes(b'\0' * 100)
    listed = run('folder', pdir.as_posix() + '/').split('|')
    assert listed[0] == '2 0 0', listed
    assert sorted(listed[1:]) == ['AFOLDER=', 'BASLUS-20062GAME=Grand Theft Auto 3@BASLUS-20062GAME.psu'], listed
    before = hashlib.sha256(pcard.read_bytes()).hexdigest()
    assert run('importpsu', psu, pcard) == '-1 %d' % ERR['EXISTS']
    assert hashlib.sha256(pcard.read_bytes()).hexdigest() == before
    assert run('delete', pcard, 'BASLUS-20062GAME') == '1 0'
    assert run('importpsu', psu, pcard) == '1 0'
    assert Card(pcard.read_bytes()).check() == {'BASLUS-20062GAME': files}
    # a PSU written from the format alone (as uLaunchELF does, with a folder entry inside) imports too
    ext = t / 'ext.psu'
    ext_files = [('icon.sys', icon_sys(fullwidth('Okami'))), ('SAVE0', os.urandom(2048)), ('tiny', b'\x01')]
    ext.write_bytes(make_psu('BASLUS-21115OKAMI', ext_files, extra_dir=True))
    assert run('importpsu', ext, pcard) == '1 0'
    assert Card(pcard.read_bytes()).check()['BASLUS-21115OKAMI'] == dict(ext_files)
    # refused, card unchanged: cut short, not a PSU, a file named twice, a name no card takes
    before = hashlib.sha256(pcard.read_bytes()).hexdigest()
    whole = make_psu('BASLUS-11111CUT', [('a', os.urandom(5000))])
    (t / 'cut.psu').write_bytes(whole[:-3000])
    assert run('importpsu', t / 'cut.psu', pcard) == '0 %d' % ERR['PSU']
    assert run('importpsu', pdir / 'junk.psu', pcard) == '0 %d' % ERR['PSU']
    (t / 'dup.psu').write_bytes(make_psu('BASLUS-22222DUP', [('a', b'1'), ('a', b'2')]))
    assert run('importpsu', t / 'dup.psu', pcard) == '0 %d' % ERR['NAME']
    (t / 'dots.psu').write_bytes(make_psu('..', [('a', b'1')]))
    assert run('importpsu', t / 'dots.psu', pcard) == '0 %d' % ERR['NAME']
    good = make_psu('BASLUS-33333DOT', [('a', b'1')])
    (t / 'nodot.psu').write_bytes(good[:512] + psu_entry(0x8497, 0, 'x') + good[1024:])  # "." is not a folder named "."
    assert run('importpsu', t / 'nodot.psu', pcard) == '0 %d' % ERR['PSU']
    (t / 'noup.psu').write_bytes(good[:1024] + b'\0' * 512 + good[1536:])  # ".." is blank
    assert run('importpsu', t / 'noup.psu', pcard) == '0 %d' % ERR['PSU']
    assert hashlib.sha256(pcard.read_bytes()).hexdigest() == before

# the dialog: a delete is confirmed first, and an ECC image or a write-protected drive is never written
GG = root / ('src/guigame.c' if (root / 'src/guigame.c').exists() else 'src/ui/guigame.cpp')
gg = GG.read_text()
body = gg[gg.index('static void guiGameShowVMCSaves('):]
body = body[:body.index('\n}\n')]
assert body.index('guiMsgBox(msg, 1, diaVMCSaves)') < body.index('vmcSavesDelete(card'), 'a delete is confirmed first'
assert 'cardWritable = probe == 1 && gEnableWrite;' in body
refresh = gg[gg.index('static void guiGameRefreshVMCSaves('):]
refresh = refresh[:refresh.index('\n}\n')]
for needle in ('VMCSAVES_EXPORT, gEnableWrite &&', 'VMCSAVES_EXPORT_PSU, gEnableWrite &&', 'VMCSAVES_IMPORT, cardWritable &&', 'VMCSAVES_DELETE, cardWritable &&'):
    assert needle in refresh, needle
assert 'VMC_BUTTON_SAVES && vmc_operation == OPERATION_CREATE' in gg, 'never while a card is being made or rebuilt'

print('ok   VMC saves: list, import, export (folder and PSU), delete and ECC read-only, checked against an independent reader')
