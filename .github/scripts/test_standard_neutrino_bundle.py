#!/usr/bin/env python3
"""A changed or incomplete external runtime must never reach a standard kit."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "standard_neutrino", Path(__file__).with_name("package_standard_neutrino.py")
)
pkg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pkg)


class StandardNeutrinoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "runtime.7z"
        self.archive.write_bytes(b"fixture archive")
        self.destination = self.root / "kit/neutrino"
        self.pin = json.loads(pkg.PIN.read_text(encoding="utf-8"))
        self.pin["sha256"] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.payload = {name: b"runtime" for name in pkg.REQUIRED}
        self.payload["version.txt"] = self.pin["version"].encode()

    def extract(self, command, **kwargs):
        root = Path(command[3][2:])
        for name, data in self.payload.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def stage(self):
        with patch.object(pkg.subprocess, "run", side_effect=self.extract):
            pkg.stage(self.archive, self.destination, self.pin, "7z")

    def test_complete_runtime_records_archive_source_and_module_hashes(self):
        self.stage()
        proof = json.loads((self.destination / "RIPTOPL-STANDARD.json").read_text())
        self.assertEqual(proof["source_commit"], self.pin["source_commit"])
        self.assertEqual(proof["sha256"], self.pin["sha256"])
        for name, data in self.payload.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
            self.assertEqual(
                proof["runtime_sha256"][name], hashlib.sha256(data).hexdigest()
            )
        self.assertEqual(
            (self.destination / "LICENSE").read_bytes(),
            (pkg.ROOT / "third_party/neutrino/LICENSE").read_bytes(),
        )
        self.assertEqual(
            (self.destination / "config/bsd-udpfsbd.toml").read_bytes(),
            (pkg.ROOT / "neutrino/bsd-udpfsbd.toml").read_bytes(),
        )

    def test_old_companion_server_is_not_shipped(self):
        self.payload["udpfs_server/udpfs_server.py"] = b"old PC server"
        self.stage()
        self.assertFalse((self.destination / "udpfs_server").exists())
        proof = json.loads((self.destination / "RIPTOPL-STANDARD.json").read_text())
        self.assertNotIn("udpfs_server/udpfs_server.py", proof["runtime_sha256"])

    def test_digest_mismatch_stops_before_extraction(self):
        self.pin["sha256"] = "0" * 64
        with patch.object(pkg.subprocess, "run") as extract:
            with self.assertRaisesRegex(ValueError, "archive digest mismatch"):
                pkg.stage(self.archive, self.destination, self.pin, "7z")
            extract.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_wrong_version_does_not_publish(self):
        self.payload["version.txt"] = b"another build"
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            self.stage()
        self.assertFalse(self.destination.exists())

    def test_missing_required_module_does_not_publish(self):
        del self.payload["modules/udpfs_fhi.irx"]
        with self.assertRaisesRegex(ValueError, "missing standard"):
            self.stage()
        self.assertFalse(self.destination.exists())

    def test_existing_runtime_is_preserved(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "existing"
        marker.write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.stage()
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_license_mismatch_does_not_publish(self):
        self.pin["license_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "license digest mismatch"):
            self.stage()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
