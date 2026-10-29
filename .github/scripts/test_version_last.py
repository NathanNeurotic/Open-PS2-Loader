"""Every release ZIP name ends with the build version."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import version_last


class VersionLastTests(unittest.TestCase):
    def test_rolling_names_already_end_with_the_version_except_the_source(self):
        version = "v1.2.0-Beta-4420"
        self.assertEqual(version_last.target("RIPTOPL-v1.2.0-Beta-4420.zip", version), "RIPTOPL-v1.2.0-Beta-4420.zip")
        self.assertEqual(version_last.target("RIPTOPL-DEBUG-v1.2.0-Beta-4420.zip", version), "RIPTOPL-DEBUG-v1.2.0-Beta-4420.zip")
        self.assertEqual(version_last.target("RIPTOPL-v1.2.0-Beta-4420-src.zip", version), "RIPTOPL-src-v1.2.0-Beta-4420.zip")

    def test_the_korium_label_moves_in_front_of_the_version(self):
        version = "v1.2.0-Beta-4420-Korium"
        cases = {
            "RIPTOPL-v1.2.0-Beta-4420-Korium.zip": "RIPTOPL-Korium-v1.2.0-Beta-4420.zip",
            "RIPTOPL-VARIANTS-v1.2.0-Beta-4420-Korium.zip": "RIPTOPL-VARIANTS-Korium-v1.2.0-Beta-4420.zip",
            "RIPTOPL-DEBUG-v1.2.0-Beta-4420-Korium.zip": "RIPTOPL-DEBUG-Korium-v1.2.0-Beta-4420.zip",
            "RIPTOPL-LANGS-v1.2.0-Beta-4420-Korium.zip": "RIPTOPL-LANGS-Korium-v1.2.0-Beta-4420.zip",
            "RIPTOPL-v1.2.0-Beta-4420-Korium-src.zip": "RIPTOPL-src-Korium-v1.2.0-Beta-4420.zip",
        }
        for old, new in cases.items():
            self.assertEqual(version_last.target(old, version, "Korium"), new)

    def test_other_files_and_unlabelled_versions_keep_their_names(self):
        for name in ("RIPTOPL.ELF", "APP_RIPTOPL.psu", "SHA256SUMS.txt", "RIPTOPL-v1.2.0-Beta-4420-Korium-PS2DEVROLLING.ELF",
                     "RIPTOPL-v1.2.0-Beta-4419-Korium.zip"):
            self.assertEqual(version_last.target(name, "v1.2.0-Beta-4420-Korium", "Korium"), name)
        # A v* tag carries no channel label: nothing moves.
        self.assertEqual(version_last.target("RIPTOPL-v1.3.0.zip", "v1.3.0", "Korium"), "RIPTOPL-v1.3.0.zip")

    def test_folder_and_checksums_follow_the_new_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            names = ["RIPTOPL.ELF", "RIPTOPL-v1.2.0-Beta-4420-Korium.zip", "RIPTOPL-v1.2.0-Beta-4420-Korium-src.zip"]
            for name in names:
                (folder / name).write_bytes(name.encode())
            (folder / "SHA256SUMS.txt").write_text("".join(
                f"{hashlib.sha256(n.encode()).hexdigest()}  {n}\n" for n in names if not n.endswith("Korium.zip")))
            version_last.rename(folder, "v1.2.0-Beta-4420-Korium", "Korium")
            self.assertEqual({p.name for p in folder.iterdir()}, {"RIPTOPL.ELF", "SHA256SUMS.txt",
                             "RIPTOPL-Korium-v1.2.0-Beta-4420.zip", "RIPTOPL-src-Korium-v1.2.0-Beta-4420.zip"})
            for line in (folder / "SHA256SUMS.txt").read_text().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
