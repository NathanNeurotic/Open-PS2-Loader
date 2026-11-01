"""The bug-report zip takes the official flavour first, refuses packed or padded loaders, and ships a README."""
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_bugreport


def elf(offset=0x80, vaddr=0x00100000, tag=b""):
    """A minimal MIPS ELF32 with one PT_LOAD; the defaults are the layout of a ps2sdk link."""
    header = bytearray(b"\x7fELF\x01\x01\x01" + bytes(9))
    header += struct.pack("<HHIIIIIHHHHHH", 2, 8, 1, vaddr, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    header += struct.pack("<8I", 1, offset, vaddr, vaddr, 16, 16, 7, 0x80)
    return bytes(header) + tag.ljust(16, b"\0")


class PackBugReportTests(unittest.TestCase):
    def stage(self, folder, **flavours):
        (folder / "bugreport").mkdir(exist_ok=True)
        for flavour, payload in flavours.items():
            (folder / "bugreport" / f"RIPTOPL-BUGREPORT-{flavour}.ELF").write_bytes(payload)

    def test_official_first_then_ps2dev(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self.stage(folder, PS2DEVROLLING=elf(tag=b"ps2dev"), OFFICIALROLLING=elf(tag=b"official"))
            archive, flavour = pack_bugreport.pack(folder, "v1.2.0-Beta-4540")
            self.assertEqual((archive.name, flavour), ("RIPTOPL-BUGREPORT-v1.2.0-Beta-4540.zip", "OFFICIALROLLING"))
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(sorted(bundle.namelist()), ["README.txt", "RIPTOPL-BUGREPORT.ELF"])
                self.assertEqual(bundle.read("RIPTOPL-BUGREPORT.ELF"), elf(tag=b"official"))
                text = bundle.read("README.txt").decode()
                self.assertTrue(text.startswith("RiptOPL bug-report build, v1.2.0-Beta-4540\r\n" + "=" * 42 + "\r\n"))
                for needle in ("OFFICIALROLLING", "DIAG.TXT", "RIPTOPL-FREEZE.TXT", pack_bugreport.ISSUES):
                    self.assertIn(needle, text)
                self.assertNotIn("{", text)
            self.stage(folder, PS2DEVROLLING=elf(tag=b"ps2dev"))
            (folder / "bugreport/RIPTOPL-BUGREPORT-OFFICIALROLLING.ELF").unlink()
            archive, flavour = pack_bugreport.pack(folder, "v1")
            self.assertEqual(flavour, "PS2DEVROLLING")
            self.assertEqual("PS2DEVROLLING" in zipfile.ZipFile(archive).read("README.txt").decode(), True)

    def test_nothing_staged_packs_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self.assertIsNone(pack_bugreport.pack(folder, "v1"))
            (folder / "bugreport").mkdir()
            self.assertIsNone(pack_bugreport.pack(folder, "v1"))
            self.assertEqual(list(folder.glob("*.zip")), [])

    def test_packed_padded_and_foreign_loaders_are_refused(self):
        cases = {"packed": elf(offset=0x60, vaddr=0x01D00000), "padded": elf(offset=0x10000), "foreign": b"MZ" + bytes(64)}
        for name, payload in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                self.stage(folder, OFFICIALROLLING=payload)
                with self.assertRaises(ValueError):
                    pack_bugreport.pack(folder, "v1")
                self.assertEqual(list(folder.glob("*.zip")), [])
        pack_bugreport.check_layout(elf())  # the ps2sdk layout passes


if __name__ == "__main__":
    unittest.main()
