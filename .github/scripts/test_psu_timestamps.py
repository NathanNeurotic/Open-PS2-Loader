#!/usr/bin/env python3
"""Check release PSU dates against R3Z3N's SAS planner and the raw PSU records."""

import struct
import tempfile
import unittest
from pathlib import Path

import package_release_app as packager


# Values produced by SAS-TIMESTAMPSTOMLV3.py's _planned_timestamp_for_folder.
SAS_GOLDEN = {
    "APP_RIPTOPL": "2098-12-31T14:17:22+00:00",
    "APP_RIPTOPL-RA": "2098-12-31T14:17:22+00:00",
    "BOOT": "2098-12-21T23:47:59+00:00",
    "OPL": "2098-12-19T15:59:10+00:00",
    "NEUTRINO": "2098-12-23T16:44:51+00:00",
    "APPS": "2098-12-31T00:23:04+00:00",
    "FOO-BAR": "2098-12-22T21:24:00+00:00",
    "POPSTARTER": "2098-12-19T15:23:58+00:00",
}


class SasPsuTimestampTests(unittest.TestCase):
    def test_planner_matches_reference(self):
        for name, expected in SAS_GOLDEN.items():
            with self.subTest(name=name):
                self.assertEqual(packager.sas_timestamp(name).isoformat(), expected)
        self.assertEqual(packager.sas_timestamp("BOOT"), packager.sas_timestamp("SYS_BOOT"))
        self.assertEqual(packager.sas_timestamp("OPL"), packager.sas_timestamp("ZZZ_OPL"))

    def test_archive_stores_sas_date_in_every_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for app_name in ("APP_RIPTOPL", "APP_RIPTOPL-RA"):
                with self.subTest(app_name=app_name):
                    app_dir = root / app_name
                    app_dir.mkdir()
                    for filename in (*packager.APP_COMPANIONS, "RIPTOPL.ELF"):
                        (app_dir / filename).write_bytes(b"sample")
                    output = root / f"{app_name}.psu"
                    packager.build_psu(app_dir, output)
                    data = output.read_bytes()
                    expected = struct.pack("<BBBBBBH", 0, 22, 17, 14, 31, 12, 2098)
                    root_record = packager.PSU_ENTRY.unpack_from(data, 0)
                    offsets = [0, packager.PSU_ENTRY.size, 2 * packager.PSU_ENTRY.size]
                    position = 3 * packager.PSU_ENTRY.size
                    for _ in range(root_record[2] - 2):
                        offsets.append(position)
                        record = packager.PSU_ENTRY.unpack_from(data, position)
                        position += packager.PSU_ENTRY.size
                        position += ((record[2] + packager.PSU_CLUSTER - 1) //
                                     packager.PSU_CLUSTER) * packager.PSU_CLUSTER
                    self.assertEqual(position, len(data))
                    for offset in offsets:
                        record = packager.PSU_ENTRY.unpack_from(data, offset)
                        self.assertEqual(record[3], expected)
                        self.assertEqual(record[6], expected)
                    self.assertEqual(packager.inspect_psu(data)[0], app_name)

                    corrupted = bytearray(data)
                    corrupted[3 * packager.PSU_ENTRY.size + 25] ^= 1  # file mTime second
                    with self.assertRaisesRegex(ValueError, "incorrect SAS timestamp"):
                        packager.inspect_psu(corrupted)


if __name__ == "__main__":
    unittest.main()
