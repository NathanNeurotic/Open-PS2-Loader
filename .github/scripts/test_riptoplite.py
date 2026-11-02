#!/usr/bin/env python3
"""RiptOPLite: the Makefile's per-device module lists, the code gates and the rolling-lite channel."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_lite_release as lite  # noqa: E402
import publish_lite_release as publisher  # noqa: E402

# Kept in every lite build (maintainer decision 2026-11-02: MMCE and network modules are backbone),
# plus the BDM core and USB block driver a lite ELF started from a USB stick reads its settings with.
ALWAYS = {"mmceman", "mmcedrv", "mmceigr", "mmce_cdvdman", "mmce_mcemu", "netman", "smap", "ps2ip", "ps2ips",
          "smsutils", "httpclient", "lwnbdsvr", "ps2atad", "ps2dev9", "bdm", "bdmfs_fatfs", "bdmevent",
          "usbmass_bd", "usbd", "usbhdfsd", "padman", "sio2man", "mcman", "mcserv", "iomanx", "filexio"}
RA_ALWAYS = {"ingame_smstcpip", "smap_ingame", "smbman", "smb2man", "nbns"}
OWN = {"usb": {"bdm_cdvdman"}, "mx4sio": {"mx4sio_bd", "bdm_cdvdman"}, "ilink": {"iLinkman", "IEEE1394_bd"},
       "hdd": {"hdd_cdvdman", "xhdd", "ps2hdd", "ps2fs", "bdm_ata_cdvdman", "dvrdrv"},
       "smb": {"smb_cdvdman", "smb2_cdvdman", "smbman", "smbinit"}, "udpbd": {"smap_udpbd", "bdm_udp_cdvdman"},
       "udpfs": {"udpfs_cdvdman", "udpfs_ioman", "udpfs_bd", "udpfs_fhi", "smb_cdvdman"}, "mmce": set()}


def dropped(device, ra=False):
    out = subprocess.run(["make", "-s", "--no-print-directory", f"RIPTOPLITE={device}",
                          f"RETROACHIEVEMENTS={1 if ra else 0}", "lite-dropped"],
                         cwd=ROOT, capture_output=True, text=True, check=True, env={"PATH": "/usr/bin:/bin"})
    return set(out.stdout.split())


class MakefileTests(unittest.TestCase):
    def test_devices_match_the_channel(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("LITE_DEVICES = " + " ".join(lite.DEVICES), makefile)

    def test_each_device_keeps_its_drivers_and_the_backbone(self):
        everything = dropped("mmce") | {"mmce_cdvdman"}
        for device in lite.DEVICES:
            for ra in (False, True):
                with self.subTest(device=device, ra=ra):
                    gone = dropped(device, ra)
                    self.assertTrue(gone, "a lite build leaves something out")
                    self.assertFalse(gone & ALWAYS)
                    self.assertFalse(gone & OWN[device])
                    if ra:
                        self.assertFalse(gone & RA_ALWAYS)
                    # another device's own driver is gone
                    if device not in ("smb", "udpfs"):
                        self.assertIn("smb_cdvdman", gone)
                    if device != "hdd":
                        self.assertLessEqual({"hdd_cdvdman", "xhdd", "ps2hdd"}, gone)
                    self.assertLessEqual(gone, everything)
                    # PC Card CF and HTTP have no lite build
                    self.assertLessEqual({"pccf_bd", "pccf_cdvdman", "pccf_game", "http_cdvdman"}, gone)

    def test_unknown_device_fails(self):
        result = subprocess.run(["make", "-s", "RIPTOPLITE=floppy", "lite-dropped"], cwd=ROOT,
                                capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not one of", result.stderr)

    def test_full_build_leaves_nothing_out(self):
        out = subprocess.run(["make", "-s", "lite-dropped"], cwd=ROOT, capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(out.stdout.strip(), "")


class CodeTests(unittest.TestCase):
    def test_loader_refuses_a_zero_sized_module(self):
        source = (ROOT / "src/system.c").read_text(encoding="utf-8")
        body = source[source.index("int sysLoadModuleBuffer(void *buffer, int size"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("if (buffer == NULL || size <= 0)", body)
        self.assertLess(body.index("size <= 0"), body.index("WaitSema"))

    def test_header_requires_exactly_one_device(self):
        header = (ROOT / "include/riptlite.h").read_text(encoding="utf-8")
        for title in ("USB", "MX4SIO", "ILINK", "HDD", "SMB", "UDPBD", "UDPFS", "MMCE"):
            self.assertIn(f"#ifdef RIPTOPLITE_{title}", header)
        self.assertIn("#if LITE_DEVICES_A_ + LITE_DEVICES_B_ != 1", header)

    def test_the_shared_config_keeps_the_full_loaders_devices(self):
        opl = (ROOT / "src/opl.c").read_text(encoding="utf-8")
        self.assertIn("liteRememberDeviceKeys(", opl)
        self.assertIn("liteRestoreDeviceKeys(configOPL)", opl)
        self.assertGreaterEqual(opl.count("liteApplyDeviceMask()"), 2)

    def test_normalize_leaves_rolling_lite_alone(self):
        normalize = (ROOT / ".github/workflows/release-normalize.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.release.tag_name != 'rolling-lite' && inputs.tag != 'rolling-lite'", normalize)


def write_ra_release(folder, revision, korium, version="v1.2.0-Beta-80-abcdef0", preview=False):
    folder.mkdir(parents=True)
    kit = folder / f"RIPTOPL-RetroAchievements-Korium-{version}.zip"
    with zipfile.ZipFile(kit, "w") as z:
        z.writestr("neutrino/neutrino.elf", b"ORBIT -ra=<file>")
        z.writestr("neutrino/modules/raagent.irx", b"agent")
        z.writestr("neutrino/LICENSE", b"neutrino licence")
        z.writestr("xeRAbora.url", b"[InternetShortcut]")
        z.writestr("LICENSE-MBEDTLS.txt", b"apache")
        z.writestr("APPS/APP_RIPTOPL-RA/RIPTOPL-RA.ELF", b"full")
    digest = hashlib.sha256(kit.read_bytes()).hexdigest()
    (folder / "RA-RELEASE.json").write_text(json.dumps(dict(revision=revision, korium_revision=korium,
        version=version, preview=preview, assets={kit.name: digest})))
    return version


def write_builds(folder, revision, korium, tamper=None):
    for device in lite.DEVICES:
        for ra in (False, True):
            stage = folder / f"lite-{'ra-' if ra else ''}{device}"
            stage.mkdir(parents=True)
            elf = f"{device}:{ra}".encode()
            (stage / "RIPTOPLITE.ELF").write_bytes(elf)
            record = dict(revision=revision, korium_revision=korium, device=device, ra=ra, theme="Korium",
                          sdk="OFFICIALROLLING", elf_sha256=hashlib.sha256(elf).hexdigest())
            if tamper == (device, ra):
                record["revision"] = "f" * 40
            (stage / "BUILD.json").write_text(json.dumps(record))


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sha, self.korium = "a" * 40, "b" * 40

    def test_channel_holds_korium_elfs_and_ra_zips(self):
        version = write_ra_release(self.root / "ra", self.sha, self.korium)
        write_builds(self.root / "builds", self.sha, self.korium)
        release = lite.package(self.root / "builds", self.root / "ra", self.root / "out", self.sha)
        out = self.root / "out"
        self.assertEqual(set(release["assets"]), lite.expected_assets(version))
        self.assertEqual(publisher.validate(out), self.sha)
        for device, title in lite.DEVICES.items():
            self.assertEqual((out / f"RIPTOPLITE-{title}.ELF").read_bytes(), f"{device}:False".encode())
            with zipfile.ZipFile(out / f"RIPTOPLITE-RA-{title}-{version}.zip") as z:
                names = set(z.namelist())
                self.assertEqual(z.read(f"RIPTOPLITE-RA-{title}.ELF"), f"{device}:True".encode())
                self.assertIn("neutrino/modules/raagent.irx", names)  # ORBIT's runtime, RA's outside need
                self.assertLessEqual({"README.txt", "BUILD.json", "xeRAbora.url", "LICENSE-MBEDTLS.txt",
                                      "LICENSE-LIBSMB2.txt", "LICENSE", "CREDITS"}, names)
                self.assertFalse(any(n.startswith("APPS/") for n in names))
        self.assertFalse(any(n.startswith("RIPTOPLITE-RA-") and n.endswith(".ELF") for n in release["assets"]))
        notes = lite.release_notes(release, "NathanNeurotic/Open-PS2-Loader")
        for title in lite.DEVICES.values():
            self.assertIn(f"/releases/download/rolling-lite/RIPTOPLITE-{title}.ELF)", notes)
            self.assertIn(f"/releases/download/rolling-lite/RIPTOPLITE-RA-{title}-{version}.zip)", notes)

    def test_a_build_from_another_revision_is_refused(self):
        write_ra_release(self.root / "ra", self.sha, self.korium)
        write_builds(self.root / "builds", self.sha, self.korium, tamper=("hdd", True))
        with self.assertRaises(ValueError):
            lite.package(self.root / "builds", self.root / "ra", self.root / "out", self.sha)

    def test_publication_needs_the_ra_release_of_the_same_revision(self):
        pr = "c" * 40
        write_ra_release(self.root / "ra", self.sha, self.korium)
        write_builds(self.root / "builds", pr, self.korium)
        with self.assertRaises(ValueError):
            lite.package(self.root / "builds", self.root / "ra", self.root / "out", pr)
        release = lite.package(self.root / "builds", self.root / "ra", self.root / "preview", pr, preview=True)
        self.assertTrue(release["preview"])
        with self.assertRaises(ValueError):
            publisher.validate(self.root / "preview")

    def test_publish_refuses_a_stale_revision_and_never_marks_latest(self):
        write_ra_release(self.root / "ra", self.sha, self.korium)
        write_builds(self.root / "builds", self.sha, self.korium)
        lite.package(self.root / "builds", self.root / "ra", self.root / "out", self.sha)
        calls = []

        def fake_gh(*args):
            calls.append(args)
            if args[0] == "api" and "git/ref/tags/" in args[1]:
                return json.dumps({"object": {"sha": "d" * 40 if args[1].endswith("rolling-ra") else self.sha}})
            return "[]"

        with patch.object(publisher, "gh", fake_gh):
            with self.assertRaises(ValueError):
                publisher.publish(self.root / "out", Path("notes"), "owner/repo")
        self.assertFalse(any(c[:2] == ("release", "create") for c in calls))
        source = (ROOT / ".github/scripts/publish_lite_release.py").read_text(encoding="utf-8")
        self.assertNotIn("--latest=true", source)
        self.assertNotRegex(source, r'"--latest"(?!=)')


if __name__ == "__main__":
    unittest.main()
