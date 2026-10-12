"""Validate pinned extraction, preservation and refusal before package mutation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("packer", Path(__file__).with_name("package_orbit_neutrino.py"))
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "neutrino"
        self.destination.mkdir()
        (self.destination / "stock").write_bytes(b"preserve on failure")
        self.pin = json.loads(packer.PIN.read_text())

    def archive(self, missing=None, extra=None, loader=b"ELF -ra=<file>"):
        archive = self.root / "runtime.zip"
        files = {name: b"payload" for name in (
            "neutrino.elf", "modules/ee_core.elf", "modules/raagent.irx",
            "config/system.toml", "config/bsd-udpfs.toml", "LICENSE")}
        files["neutrino.elf"] = loader
        files.pop(missing, None)
        with zipfile.ZipFile(archive, "w") as z:
            for name, data in files.items():
                z.writestr("ORBIT-test/neutrino/" + name, data)
            z.writestr("ORBIT-test/orbit.elf", b"launcher must not ship")
            if extra:
                info = zipfile.ZipInfo("entry")
                info.filename = extra
                z.writestr(info, b"unsafe")
        self.pin["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        return archive

    def test_stages_runtime_only_and_preserves_private_config(self):
        config = self.destination / "config/bsd-udpfsbd.toml"
        config.parent.mkdir()
        config.write_bytes(b"private block transport")
        packer.stage(self.archive(), self.destination, self.pin)
        self.assertEqual(config.read_bytes(), b"private block transport")
        self.assertFalse((self.destination / "stock").exists())
        self.assertFalse((self.destination / "orbit.elf").exists())
        self.assertTrue((self.destination / "modules/raagent.irx").is_file())
        self.assertEqual(json.loads((self.destination / "ORBIT-RA.json").read_text()), self.pin)

    def test_digest_mismatch_preserves_existing_install(self):
        archive = self.archive()
        self.pin["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            packer.stage(archive, self.destination, self.pin)
        self.assertTrue((self.destination / "stock").exists())

    def test_invalid_runtime_or_path_preserves_existing_install(self):
        for kwargs in ({"missing": "modules/raagent.irx"}, {"loader": b"stock"},
                       {"extra": "ORBIT-test/neutrino/../escape"},
                       {"extra": "/absolute"}, {"extra": "bad\\windows"},
                       {"extra": "ORBIT-test/neutrino/LICENSE"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                packer.stage(self.archive(**kwargs), self.destination, self.pin)
            self.assertTrue((self.destination / "stock").exists())

    def test_refuses_non_neutrino_destination(self):
        with self.assertRaisesRegex(ValueError, "destination"):
            packer.stage(self.archive(), self.root, self.pin)

    def test_watcher_matches_standard_schedule(self):
        root = packer.ROOT
        import re
        scheduled = lambda name: re.findall(r"cron:\s*[\"']([^\"']+)", (root / ".github/workflows" / name).read_text())
        self.assertEqual(scheduled("neutrino-watch.yml"), scheduled("orbit-neutrino-watch.yml"))


if __name__ == "__main__":
    unittest.main()
