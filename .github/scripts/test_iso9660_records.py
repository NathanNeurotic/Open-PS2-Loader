#!/usr/bin/env python3
"""Regression tests for the ISO 9660 directory walk in isofs (the game list) and the in-game CDVDMAN.

Both copies of cdvdman_locatefile() are compiled on the host, with AddressSanitizer when it is
available, and run on directory sectors built here: a record without a name used to stop the scan
from advancing (an endless loop), a non-zero extended attribute byte was read as the high byte of
the record length (a step of 256+ bytes, or backwards), and damaged records were walked past the
sector. Ported from belomaxorka/YAOPL ff498c19, af5b52b7 and bfe726f5, plus the bounds of our own.
"""
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISOFS = ROOT / 'modules/isofs/isofs.c'
SEARCHFILE = ROOT / 'modules/iopcore/cdvdman/searchfile.c'
INTERNAL = ROOT / 'modules/iopcore/cdvdman/internal.h'
IOOPS = ROOT / 'modules/iopcore/cdvdman/ioops.c'
CC = shutil.which('cc') or shutil.which('gcc')
ROOT_LBA, SUB_LBA, FILE_LBA = 20, 30, 100


def function(text, name):
    match = re.search(r'\n[^\n;{}]*\b' + re.escape(name) + r'\([^;{]*\)[^;{\n]*\n\{', text)
    assert match, name
    depth, i = 0, match.end() - 1
    while True:
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[match.start():i]


def dir_struct(text):
    match = re.search(r'struct dirTocEntry\n\{.*?\} __attribute__\(\(packed\)\);', text, re.S)
    assert match
    return match.group(0)


def record(name, lba=0, size=0, flags=0, length=None, ext=0, pad=True):
    raw = name.encode() if isinstance(name, str) else name
    body = struct.pack('<BBIIIIxxxxxxBB6xB', 0, ext, lba, 0, size, 0, 0, flags, len(raw)) + raw
    if pad and len(body) % 2:
        body += b'\0'
    body = bytes([len(body) if length is None else length]) + body[1:]
    return body


def sector(*records, fill=b'\0'):
    data = b''.join(records)
    assert len(data) <= 2048
    return data + fill * (2048 - len(data))


def standard(*middle):
    return sector(record(b'\0', ROOT_LBA, 2048, 2), record(b'\1', ROOT_LBA, 2048, 2), *middle)


COMMON = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define DPRINTF(...)
static unsigned char disc[64][2048];
static int sceCdReadDvdDualInfo(int *on_dual, u32 *layer1_start) { *on_dual = 0; *layer1_start = 0; return 1; }
'''
MAIN = r'''
int main(int argc, char **argv)
{
    FILE *f = fopen(argv[1], "rb");
    if (!f || fread(disc, 1, sizeof(disc), f) != sizeof(disc))
        return 2;
    fclose(f);
    char path[256];
    strcpy(path, argv[2]);
    struct dirTocEntry *e = cdvdman_locatefile(path, %(root)d, 2048, 0);
    if (e)
        printf("%%u %%u\n", (unsigned)e->fileLBA, (unsigned)e->fileSize);
    else
        puts("none");
    return 0;
}
'''


def isofs_source():
    text = ISOFS.read_text()
    return COMMON + dir_struct(text) + r'''
static unsigned char cdvdman_buf[2048];
static int cdEmuRead(u32 lsn, unsigned int count, void *buffer) { memcpy(buffer, disc[lsn], 2048); return 0; }
''' + function(text, 'cdvdman_locatefile') + MAIN % {'root': ROOT_LBA}


def ingame_source():
    text = SEARCHFILE.read_text()
    return COMMON + dir_struct(INTERNAL.read_text()) + r'''
#define IOPCORE_COMPAT_EMU_DVDDL 0x10
static struct { struct { int flags; } common; } cdvdman_settings;
static unsigned char cdvdman_buf[2048];
static int sceCdRead(u32 lsn, u32 count, void *buffer, void *mode) { memcpy(buffer, disc[lsn], 2048); return 1; }
static int sceCdSync(int mode) { return 0; }
''' + function(text, 'cdvdman_locatefile') + MAIN % {'root': ROOT_LBA}


@unittest.skipUnless(CC, 'no host C compiler')
class LocateFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exes = {}
        for name, source in (('isofs', isofs_source()), ('ingame', ingame_source())):
            src = Path(cls.tmp.name) / (name + '.c')
            src.write_text(source)
            exe = Path(cls.tmp.name) / name
            for flags in (['-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []):
                built = subprocess.run([CC, '-std=gnu99', '-g', '-O1', '-w', *flags, '-o', str(exe), str(src)],
                                       capture_output=True, text=True)
                if built.returncode == 0:
                    break
            assert built.returncode == 0, built.stderr
            cls.exes[name] = exe

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def locate(self, which, root, path, sub=None):
        image = bytearray(64 * 2048)
        image[ROOT_LBA * 2048:(ROOT_LBA + 1) * 2048] = root
        if sub is not None:
            image[SUB_LBA * 2048:(SUB_LBA + 1) * 2048] = sub
        disc = Path(self.tmp.name) / 'disc.bin'
        disc.write_bytes(bytes(image))
        try:
            run = subprocess.run([str(self.exes[which]), str(disc), path], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            self.fail(f'{which}: {path}: the directory walk did not end')
        self.assertEqual(run.returncode, 0, f'{which}: {path}: {run.stderr[-2000:]}')
        return run.stdout.strip()

    def both(self, root, path, expect, sub=None):
        for which in ('isofs', 'ingame'):
            with self.subTest(which=which, path=path):
                self.assertEqual(self.locate(which, root, path, sub), expect)

    def test_plain_lookup(self):
        self.both(standard(record('SYSTEM.CNF;1', FILE_LBA, 77)), '\\SYSTEM.CNF;1', f'{FILE_LBA} 77')
        self.both(standard(record('SYSTEM.CNF;1', FILE_LBA, 77)), '/SYSTEM.CNF;1', f'{FILE_LBA} 77')
        self.both(standard(record('SYSTEM.CNF;1', FILE_LBA, 77)), '\\MISSING.ELF;1', 'none')

    def test_record_without_a_name_is_stepped_over(self):  # YAOPL ff498c19
        root = standard(record(b'', length=34), record('SYSTEM.CNF;1', FILE_LBA, 77))
        self.both(root, '\\SYSTEM.CNF;1', f'{FILE_LBA} 77')

    def test_extended_attribute_byte_is_not_part_of_the_length(self):  # YAOPL af5b52b7
        for ext in (0x01, 0x80, 0xff):
            root = standard(record('README.TXT;1', 5, 1, ext=ext), record('SYSTEM.CNF;1', FILE_LBA, 77))
            self.both(root, '\\SYSTEM.CNF;1', f'{FILE_LBA} 77')

    def test_damaged_records_end_the_sector_inside_it(self):
        short = standard(record('BROKEN.BIN;1', length=36), record('SYSTEM.CNF;1', FILE_LBA, 77))
        self.both(short, '\\SYSTEM.CNF;1', 'none')  # shorter than its own name: nothing after it is trusted
        # A record that starts in the last bytes of the sector and claims to run past it.
        filler = [record(b'', length=36)[:34] + b'\0\0' for _ in range(55)]
        tail = record('AAAAAAA')
        past_end = (record(b'\0', ROOT_LBA, 2048, 2) + b''.join(filler) + tail)[:2048]
        self.assertEqual(len(past_end), 2048)
        self.both(past_end, '\\AAAAAAA', 'none')
        self.both(sector(record('X' * 200, length=255)), '\\SYSTEM.CNF;1', 'none')

    def test_names_longer_than_level_1(self):  # YAOPL a2ff76fc, already bounded here
        root = standard(record('A_VERY_LONG_LEVEL2_FILENAME_HERE.TXT;1', 5, 1), record('SYSTEM.CNF;1', FILE_LBA, 77))
        self.both(root, '\\SYSTEM.CNF;1', f'{FILE_LBA} 77')

    def test_nested_directory(self):
        root = standard(record('DATA', SUB_LBA, 2048, 2))
        sub = standard(record(b'', length=34), record('MOVIE.PSS;1', FILE_LBA, 4096, ext=0x80))
        self.both(root, '\\DATA\\MOVIE.PSS;1', f'{FILE_LBA} 4096', sub)

    def test_isofs_compares_within_the_record(self):
        # An odd-length name has no pad byte, so the next record's length byte follows it directly.
        root = standard(record('SLUS_200.62;1', FILE_LBA, 9, pad=False), record('SYSTEM.CNF;1', 101, 77))
        self.assertEqual(self.locate('isofs', root, '\\SLUS_200.62;1'), f'{FILE_LBA} 9')
        # A name that only starts like the wanted one is not it.
        root = standard(record('SYSTEM.CNF;12', 5, 1), record('SYSTEM.CNF;1', FILE_LBA, 77))
        self.assertEqual(self.locate('isofs', root, '\\SYSTEM.CNF;1'), f'{FILE_LBA} 77')


class SourceTests(unittest.TestCase):
    def test_record_length_is_one_byte(self):
        for text in (ISOFS.read_text(), INTERNAL.read_text()):
            body = dir_struct(text)
            self.assertRegex(body, r'\{\s*u8 length;[^\n]*\n\s*u8 extAttrLength;')
            self.assertNotIn('short length', body)
        for path in (ISOFS, SEARCHFILE):
            self.assertNotIn('<< 16) >> 16', path.read_text())

    def test_found_name_is_bounded_and_takes_either_separator(self):
        for path in (ISOFS, SEARCHFILE):
            body = function(path.read_text(), 'cdvdman_findfile')
            self.assertNotIn('strcpy(pcdfile->name', body)
            self.assertIn("if (*c == '\\\\' || *c == '/')", body)
            self.assertIn('strncpy(pcdfile->name, base, sizeof(pcdfile->name) - 1);', body)
            self.assertIn("pcdfile->name[sizeof(pcdfile->name) - 1] = '\\0';", body)

    def test_dread_stays_in_the_sector(self):
        body = function(IOOPS.read_text(), 'cdrom_dread')
        self.assertLess(body.index('if (fh->position > 2048 - 34)'), body.index('&cdvdman_fs_buf[fh->position]'))
        self.assertIn('if (tocEntryPointer != NULL) {', body)


if __name__ == '__main__':
    unittest.main()
