#!/usr/bin/env python3
"""Exercise two-theme provenance gates and release rollback without GitHub writes."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_ra_release as pack
import publish_ra_release as publisher


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.sha = "a" * 40
        self.korium = "b" * 40

    def builds(self):
        for theme in pack.THEMES:
            for sdk in pack.SDKS:
                folder = self.folder / f"{theme}-{sdk}"
                folder.mkdir()
                hashes = {}
                for pad in ([1] if sdk == "OFFICIALROLLING" else [0, 1]):
                    elf = folder / f"pademu{pad}.ELF"
                    elf.write_bytes(b"\x7fELF" + f"{theme}:{sdk}:{pad}".encode())
                    hashes[str(pad)] = pack.digest(elf)
                (folder / "BUILD.json").write_text(json.dumps(dict(revision=self.sha,
                    korium_revision=self.korium, theme=theme, sdk=sdk, elf_sha256=hashes)))
                if theme == "Korium":
                    (folder / "Korium.patch").write_bytes(b"same theme patch")

    def assets(self):
        names = {"RIPTOPL-RetroAchievements-test-src.zip"}
        for theme in publisher.THEMES:
            names.update((f"RIPTOPL-RA-{theme}.ELF", f"APP_RIPTOPL-RA-{theme}.psu",
                          f"RIPTOPL-RetroAchievements-{theme}-test.zip"))
        for name in names:
            (self.folder / name).write_bytes(name.encode())
        data = dict(revision=self.sha, version="test", themes=list(publisher.THEMES),
                    preview=False, assets={name: pack.digest(self.folder / name) for name in names})
        (self.folder / "RA-RELEASE.json").write_text(json.dumps(data))
        (self.folder / "SHA256SUMS.txt").write_text("".join(
            f"{pack.digest(file)}  {file.name}\n" for file in sorted(self.folder.iterdir())))

    def test_builds_require_same_code_and_identical_theme_patch(self):
        self.builds()
        self.assertEqual(len(pack.validate_builds(self.folder, self.sha, self.korium)), 6)
        file = self.folder / "Korium-PS2DEVPINNED/BUILD.json"
        data = json.loads(file.read_text())
        data["revision"] = "c" * 40
        file.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "mixed source"):
            pack.validate_builds(self.folder, self.sha, self.korium)
        data["revision"] = self.sha
        file.write_text(json.dumps(data))
        (file.parent / "Korium.patch").write_bytes(b"different patch")
        with self.assertRaisesRegex(ValueError, "different theme"):
            pack.validate_builds(self.folder, self.sha, self.korium)

    def test_bootstrap_selects_install_kit_instead_of_source_or_ra_archive(self):
        names = ["RIPTOPL-v1.2.0-Beta-3841-src.zip", "RIPTOPL-v1.2.0-Beta-3841.zip",
                 "RIPTOPL-RetroAchievements-v1.2.0-Beta-3841.zip", "RIPTOPL-DEBUG-v1.zip"]
        self.assertEqual(pack.standard_asset([{"name": name} for name in names]), names[1])
        with self.assertRaises(ValueError):
            pack.standard_asset([{"name": names[0]}])

    def test_standard_release_never_builds_or_stages_ra(self):
        root = pack.ROOT
        rolling = (root / ".github/workflows/rolling-release.yml").read_text()
        extras = (root / ".github/scripts/build_rolling_extras.sh").read_text()
        for text in (rolling, extras):
            self.assertNotIn("RETROACHIEVEMENTS=1", text)
            self.assertNotIn("package_orbit_neutrino.py", text)
            self.assertNotIn("rolling/ra", text)
        workflow = (root / ".github/workflows/ra-release.yml").read_text()
        self.assertIn("theme: [inceBtion, Korium]", workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn("cancel-in-progress: false", workflow)

    def test_missing_theme_or_changed_binary_refuses(self):
        self.builds()
        elf = self.folder / "inceBtion-OFFICIALROLLING/pademu1.ELF"
        elf.write_bytes(b"\x7fELFchanged")
        with self.assertRaisesRegex(ValueError, "changed RA"):
            pack.validate_builds(self.folder, self.sha, self.korium)
        elf.unlink()
        with self.assertRaises(OSError):
            pack.validate_builds(self.folder, self.sha, self.korium)

    def test_unsafe_shared_zip_refuses_before_extraction(self):
        import zipfile
        for name in ("../escape", "/absolute", "C:/absolute", "bad\\windows"):
            with self.subTest(name=name):
                archive = self.folder / "bad.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    entry = zipfile.ZipInfo("entry")
                    entry.filename = name
                    output.writestr(entry, b"bad")
                with self.assertRaises(ValueError):
                    pack.extract(archive, self.folder / "output")
                self.assertFalse((self.folder / "output").exists())

    def test_preview_and_changed_asset_fail_before_any_api_call(self):
        self.assets()
        self.assertEqual(publisher.validate(self.folder), self.sha)
        file = self.folder / "RIPTOPL-RA-Korium.ELF"
        file.write_bytes(b"changed")
        with patch.object(publisher, "gh") as gh, self.assertRaisesRegex(ValueError, "digest"):
            publisher.publish(self.folder, Path("notes"), "owner/repo")
        gh.assert_not_called()
        manifest = self.folder / "RA-RELEASE.json"
        data = json.loads(manifest.read_text())
        data["preview"] = True
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "preview"):
            publisher.validate(self.folder)

    def test_gh_retries_transient_failures_then_gives_up(self):
        calls = []

        def flaky(command, text):
            calls.append(command)
            if len(calls) < 3:
                raise subprocess.CalledProcessError(1, command)
            return "ok\n"

        with patch.object(publisher.subprocess, "check_output", side_effect=flaky), \
                patch.object(publisher.time, "sleep") as sleep:
            self.assertEqual(publisher.gh("release", "view", "rolling-ra"), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], list(publisher.RETRY_DELAYS))
        failing = subprocess.CalledProcessError(1, "gh")
        with patch.object(publisher.subprocess, "check_output", side_effect=failing), \
                patch.object(publisher.time, "sleep"), self.assertRaises(subprocess.CalledProcessError):
            publisher.gh("release", "upload", "rolling-ra", "x")

    def test_mid_upload_failure_restores_all_fixed_names_and_keeps_old_kits(self):
        self.assets()
        fixed = ["RIPTOPL-RA-inceBtion.ELF", "RIPTOPL-RA-Korium.ELF", "RA-RELEASE.json"]
        old = dict(tag_name="rolling-ra", assets=[{"name": name} for name in fixed + ["old-kit.zip"]])
        calls = []
        failed = False

        def fake(*args):
            nonlocal failed
            calls.append(args)
            if args[:2] == ("api", "repos/owner/repo/git/ref/tags/rolling"):
                return json.dumps(dict(object=dict(sha=self.sha)))
            if args[:2] == ("api", "--paginate"):
                return json.dumps([[old]])
            if args[:2] == ("release", "download"):
                (Path(args[args.index("--dir") + 1]) / args[args.index("--pattern") + 1]).write_bytes(b"old")
            if args[:2] == ("release", "upload") and not failed and Path(args[3]).name == "RIPTOPL-RA-inceBtion.ELF":
                failed = True
                raise subprocess.CalledProcessError(1, "gh")
            return ""

        with patch.object(publisher, "gh", side_effect=fake), self.assertRaises(subprocess.CalledProcessError):
            publisher.publish(self.folder, Path("notes"), "owner/repo")
        restored = [Path(call[3]).name for call in calls if call[:2] == ("release", "upload") and Path(call[3]).parent != self.folder]
        self.assertEqual(sorted(restored), sorted(fixed))
        self.assertFalse(any(call[:2] in (("release", "delete-asset"), ("release", "edit")) for call in calls))
        self.assertFalse(any("PATCH" in call for call in calls))

    def test_new_release_is_draft_until_all_assets_uploaded_and_never_latest(self):
        self.assets()
        calls = []
        def fake(*args):
            calls.append(args)
            return json.dumps(dict(object=dict(sha=self.sha))) if "git/ref/tags/rolling" in args[-1] else "[]" if args[:2] == ("api", "--paginate") else ""
        with patch.object(publisher, "gh", side_effect=fake):
            publisher.publish(self.folder, Path("notes"), "owner/repo")
        create = next(call for call in calls if call[:2] == ("release", "create"))
        self.assertIn("--draft", create)
        self.assertIn("--latest=false", create)
        self.assertTrue(all("--latest=false" in call for call in calls if call[:2] == ("release", "edit")))


if __name__ == "__main__":
    unittest.main()
