#!/usr/bin/env python3
"""Exercise two-theme provenance gates and release rollback without GitHub writes."""
import argparse
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
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
        names = {"RIPTOPL-RetroAchievements-src-test.zip", "LICENSE-LIBSMB2.txt"}
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
                 "RIPTOPL-RetroAchievements-v1.2.0-Beta-3841.zip", "RIPTOPL-DEBUG-v1.zip",
                 "RIPTOPL-src-v1.2.0-Beta-3841.zip"]
        self.assertEqual(pack.standard_asset([{"name": name} for name in names]), names[1])
        for source in (names[0], names[4]):
            with self.assertRaises(ValueError):
                pack.standard_asset([{"name": source}])

    def old_shared_kit(self):
        archive = self.folder / "standard.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("APPS/APP_RIPTOPL/RIPTOPL.ELF", b"\x7fELFborrowed-standard-loader")
            output.writestr("POPS/usbd.irx.udpfs", b"old Alpha driver")
            output.writestr("POPS/CHEATS.TXT", b"install-kit-only runtime file")
        return archive

    def verify_shared_udpfs(self, args):
        # Exercise the real payload validator against the exact archive handed
        # to full-kit validation; unrelated app/PSU layout has separate tests.
        with zipfile.ZipFile(args.zip) as package:
            pack.app.verify_udpfs_payload(package)
            self.assertEqual(package.read("POPS/CHEATS.TXT"), b"install-kit-only runtime file")
            self.assertEqual(package.read("APPS/APP_RIPTOPL/RIPTOPL.ELF"), args.source_elf.read_bytes())

    def test_preview_refreshes_old_pops_before_validation_without_changing_input(self):
        archive = self.old_shared_kit()
        original = pack.digest(archive)
        shared = self.folder / "shared"
        with patch.object(pack.app, "verify", side_effect=self.verify_shared_udpfs) as verify:
            pack.stage_shared_kit(archive, shared, preview=True)
        verify.assert_called_once()
        self.assertEqual(pack.digest(archive), original)
        for suffix in ("udpfs",):
            for module in ("usbd.irx", "usbhdfsd.irx"):
                name = f"{module}.{suffix}"
                self.assertEqual((shared / "POPS" / name).read_bytes(), (pack.ROOT / "POPS" / name).read_bytes())
        self.assertEqual((shared / "POPS/CHEATS.TXT").read_bytes(), b"install-kit-only runtime file")

    def test_publication_does_not_refresh_or_accept_stale_shared_pops(self):
        archive = self.old_shared_kit()
        shared = self.folder / "shared"
        with patch.object(pack.app, "verify", side_effect=self.verify_shared_udpfs), \
                self.assertRaisesRegex(ValueError, "missing UDPFS"):
            pack.stage_shared_kit(archive, shared, preview=False)
        self.assertEqual((shared / "POPS/usbd.irx.udpfs").read_bytes(), b"old Alpha driver")
        self.assertFalse((self.folder / "preview-standard.zip").exists())

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


    def republish(self, draft_fails=False, stays_draft=False, republish_fails=False):
        self.assets()
        old = dict(tag_name="rolling-ra", assets=[{"name": "old-kit.zip"}])
        calls = self.calls = []
        state = dict(isDraft=False, publishedAt="2026-10-12T18:56:18Z")

        def fake(*args):
            calls.append(args)
            if args[:2] == ("api", "repos/owner/repo/git/ref/tags/rolling"):
                return json.dumps(dict(object=dict(sha=self.sha)))
            if args[:2] == ("api", "--paginate"):
                return json.dumps([[old]])
            if args[:2] == ("release", "view"):
                return json.dumps(state)
            if args[:2] == ("release", "edit") and "--draft=true" in args:
                if draft_fails:
                    raise subprocess.CalledProcessError(1, "gh")
                state["isDraft"] = True
            elif args[:2] == ("release", "edit") and republish_fails and "--notes-file" not in args:
                raise subprocess.CalledProcessError(1, "gh")
            elif args[:2] == ("release", "edit") and state["isDraft"] and not stays_draft:
                state.update(isDraft=False, publishedAt="2026-10-30T06:00:00Z")
            return ""

        with patch.object(publisher, "gh", side_effect=fake), patch.object(publisher.time, "sleep"):
            publisher.publish(self.folder, Path("notes"), "owner/repo")
        return calls, state

    def test_republished_release_gets_a_new_date_and_stays_a_prerelease(self):
        calls, state = self.republish()
        edits = [call for call in calls if call[:2] == ("release", "edit")]
        self.assertEqual(edits[1:], [("release", "edit", "rolling-ra", "--repo", "owner/repo", "--draft=true"),
                                     ("release", "edit", "rolling-ra", "--repo", "owner/repo", "--draft=false",
                                      "--prerelease", "--latest=false")])
        self.assertEqual(state, dict(isDraft=False, publishedAt="2026-10-30T06:00:00Z"))
        # The tag moves only after the release is visible again.
        self.assertGreater(next(i for i, c in enumerate(calls) if "PATCH" in c), calls.index(edits[-1]))

    def test_failed_draft_call_costs_only_the_date(self):
        calls, state = self.republish(draft_fails=True)
        self.assertFalse(state["isDraft"])
        self.assertTrue(any("PATCH" in call for call in calls))

    def test_republish_gets_one_more_try_then_fails_before_the_tag_moves(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.republish(republish_fails=True)
        republishes = [c for c in self.calls if c[:2] == ("release", "edit") and "--notes-file" not in c and "--draft=false" in c]
        self.assertEqual(len(republishes), 2)
        self.assertFalse(any("PATCH" in call for call in self.calls))

    def test_release_left_a_draft_fails_the_run(self):
        with self.assertRaisesRegex(RuntimeError, "still a draft"):
            self.republish(stays_draft=True)

class MbedtlsLicenceShippingTest(unittest.TestCase):
    def test_ra_kit_ships_the_apache_licence_and_ordinary_kits_refuse_it(self):
        root = Path(__file__).resolve().parents[2]
        ra = (root / ".github/scripts/package_ra_release.py").read_text(encoding="utf-8")
        app = (root / ".github/scripts/package_release_app.py").read_text(encoding="utf-8")
        self.assertIn('shutil.copyfile(ROOT / "third_party/mbedtls/LICENSE", kit / "LICENSE-MBEDTLS.txt")', ra)
        self.assertIn('required.add("LICENSE-MBEDTLS.txt")', app)
        self.assertIn('"LICENSE-MBEDTLS.txt" in names', app)


class Libsmb2LicenceShippingTest(unittest.TestCase):
    def test_every_kit_bundle_and_standalone_download_ships_the_lgpl_licence(self):
        # Every RiptOPL ELF embeds smb2man over libsmb2 (LGPL-2.1), so the licence text must travel
        # with the install kits (the RA kits copy the standard one), the VARIANTS/DEBUG zips and the
        # standalone ELF download.
        root = Path(__file__).resolve().parents[2]
        licence = root / "modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt"
        self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", licence.read_text(encoding="utf-8"))
        app = (root / ".github/scripts/package_release_app.py").read_text(encoding="utf-8")
        self.assertIn('LIBSMB2_LICENCE = ROOT / "modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt"', app)
        self.assertIn('shutil.copyfile(LIBSMB2_LICENCE, package / "LICENSE-LIBSMB2.txt")', app)
        self.assertIn('"LICENSE-LIBSMB2.txt",  # every loader embeds libsmb2 (LGPL-2.1)', app)
        # CREDITS, the notice that the loaders use libsmb2 under that licence, goes everywhere the licence goes.
        self.assertIn('CREDITS = ROOT / "CREDITS"', app)
        self.assertIn('shutil.copyfile(CREDITS, package / "CREDITS")', app)
        self.assertIn('"CREDITS",  # the notice that names libsmb2 and its licence', app)
        workflow = (root / ".github/workflows/rolling-release.yml").read_text(encoding="utf-8")
        self.assertIn("cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt rolling/LICENSE-LIBSMB2.txt", workflow)
        self.assertIn("PS2RD-CHT-Manager.url LICENSE-LIBSMB2.txt CREDITS >/dev/null", workflow)
        self.assertIn('cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt "rolling/$kind/LICENSE-LIBSMB2.txt"', workflow)
        self.assertIn('cp -f CREDITS "rolling/$kind/CREDITS"', workflow)
        # The MEGA mirror uploads the standalone flavour ELFs on their own, so the licence goes up beside them.
        self.assertIn("cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt mega-out/LICENSE-LIBSMB2.txt", workflow)
        self.assertIn("cp -f CREDITS mega-out/CREDITS", workflow)
        self.assertIn('MEGA_UPLOAD_FILES="mega-out/${ARCHIVE} mega-out/LICENSE-LIBSMB2.txt mega-out/CREDITS"', workflow)
        notes = (root / ".github/scripts/normalize_release_notes.py").read_text(encoding="utf-8")
        self.assertIn('"LICENSE-LIBSMB2.txt": "LGPL-2.1 licence of libsmb2', notes)
        # The RA channel publishes standalone RA ELFs too, so the licence is an RA asset as well, and a
        # PR preview bootstrapped from an older standard kit still passes the verifier.
        ra = (root / ".github/scripts/package_ra_release.py").read_text(encoding="utf-8")
        self.assertIn('shutil.copyfile(app.LIBSMB2_LICENCE, destination / "LICENSE-LIBSMB2.txt")', ra)
        self.assertIn('shutil.copyfile(app.CREDITS, destination / "CREDITS")', ra)
        self.assertIn('shutil.copyfile(app.LIBSMB2_LICENCE, args.output / "LICENSE-LIBSMB2.txt")', ra)
        publish = (root / ".github/scripts/publish_ra_release.py").read_text(encoding="utf-8")
        self.assertIn('"LICENSE-LIBSMB2.txt"}', publish)
        # Normalize Release Assets verifies the kit with rebuild/main's packager, which requires the licence
        # and CREDITS. A kit, VARIANTS zip or release built before they shipped (rolling-korium until
        # korium-sync brings the change over) gets them there instead of failing, and the final asset check
        # insists on the loose licence beside the standalone loaders.
        normalize = (root / ".github/workflows/release-normalize.yml").read_text(encoding="utf-8")
        self.assertIn("cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt package-work/LICENSE-LIBSMB2.txt", normalize)
        self.assertIn("cp -f CREDITS package-work/CREDITS", normalize)
        self.assertIn("cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt variants-work/LICENSE-LIBSMB2.txt", normalize)
        self.assertIn("cp -f CREDITS variants-work/CREDITS", normalize)
        self.assertIn('retry gh release upload "$TAG" release-work/LICENSE-LIBSMB2.txt', normalize)
        self.assertIn("grep -qFx 'LICENSE-LIBSMB2.txt'", normalize)
        verify = normalize.index("package_release_app.py verify")
        self.assertLess(normalize.index("package-work/LICENSE-LIBSMB2.txt"), verify)
        self.assertLess(normalize.index("package-work/CREDITS"), verify)

    def test_credits_say_every_loader_uses_libsmb2_under_the_lgpl(self):
        # CREDITS is the LGPL-2.1 section 6 notice that travels with the licence: it names libsmb2, says every
        # loader embeds it, that it is used under the LGPL-2.1 and where that licence text is.
        credits = (pack.ROOT / "CREDITS").read_text(encoding="utf-8")
        entry = credits[credits.index("  - libsmb2, by Ronnie Sahlberg"):]
        entry = " ".join(entry[:entry.index("\n\n")].split())
        for phrase in ("https://github.com/sahlberg/libsmb2", "every loader embeds", "used under the LGPL-2.1 licence",
                       "LICENSE-LIBSMB2.txt"):
            self.assertIn(phrase, entry)

    def test_a_staged_kit_carries_the_licence_and_the_credits_at_its_root(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            elf = folder / "built.ELF"
            elf.write_bytes(b"\x7fELFstaged-loader")
            package = folder / "package"
            with contextlib.redirect_stdout(io.StringIO()):
                pack.app.stage(argparse.Namespace(package=str(package), source_elf=str(elf), app_name="APP_RIPTOPL",
                    elf_name="RIPTOPL.ELF", title="[APP] Open PS2 Loader: RiptOPL", pbt_title="[APP] RiptOPL",
                    version="test", flavour="OFFICIALROLLING", channel="Rolling",
                    description="Open PS2 Loader for PS2 and PS3"))
            self.assertEqual((package / "LICENSE-LIBSMB2.txt").read_bytes(), pack.app.LIBSMB2_LICENCE.read_bytes())
            self.assertEqual((package / "CREDITS").read_bytes(), (pack.ROOT / "CREDITS").read_bytes())
            # Both sit beside the app, never inside it, so the PSU is the app folder alone.
            self.assertFalse(any(p.name in ("CREDITS", "LICENSE-LIBSMB2.txt") for p in (package / "APPS").rglob("*")))

    def assert_copied_before_upload(self, workflow, artifact, copies, listed):
        # The copies run in the job that uploads the artifact, before the upload and whenever it runs: no
        # condition but success() and no continue-on-error, so a later edit cannot quietly drop the licence.
        import yaml  # the host-test runners carry PyYAML; imported here so the other tests do not need it

        allowed = ("${{ success() }}", "success()")
        jobs = yaml.safe_load((pack.ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))["jobs"]
        uploads = [(job["steps"], index) for job in jobs.values() for index, step in enumerate(job.get("steps", []))
                   if "actions/upload-artifact@" in step.get("uses", "") and step.get("with", {}).get("name") == artifact]
        self.assertEqual(len(uploads), 1, artifact)
        steps, upload = uploads[0]
        self.assertEqual(steps[upload]["with"]["path"].split(), listed, artifact)
        self.assertIn(steps[upload].get("if", allowed[0]), allowed, artifact)
        for copy in copies:
            found = [step for step in steps[:upload]
                     if copy in [line.strip() for line in str(step.get("run", "")).splitlines()]]
            self.assertEqual(len(found), 1, (artifact, copy))
            self.assertIn(found[0].get("if", allowed[0]), allowed, (artifact, copy))
            self.assertNotIn("continue-on-error", found[0], (artifact, copy))

    def test_every_actions_build_of_a_loader_carries_the_licence_and_the_credits(self):
        # Testers download loaders straight from Actions runs: the build-flavours artifacts, and the RA
        # builds the RetroAchievements release is packed from. CREDITS is a tracked file at the root.
        self.assertTrue((pack.ROOT / "CREDITS").is_file())
        self.assert_copied_before_upload(
            "flavours.yml", "OPL-${{ matrix.flavour }}",
            ["cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt LICENSE-LIBSMB2.txt"],
            ["RIPTOPL-*.ELF", "OPNPS2LD-*.ELF", "BUILD-MANIFEST.txt", "LICENSE-LIBSMB2.txt", "CREDITS", "POPS/",
             "docs/VCD.md"])
        self.assert_copied_before_upload(
            "ra-release.yml", "ra-${{ matrix.theme }}-${{ matrix.sdk.name }}",
            ["cp -f modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt ra-build/LICENSE-LIBSMB2.txt",
             "cp -f CREDITS ra-build/CREDITS"],
            ["ra-build/"])

    def test_make_release_zip_carries_the_licence_and_never_leaves_a_partial_one(self):
        # Run the real $(EE_VPKD).ZIP rule, cut out of the Makefile, in a scratch tree.
        if not (shutil.which("make") and shutil.which("zip")):
            self.skipTest("needs make and zip, which the ubuntu-24.04 runners have")
        makefile = (pack.ROOT / "Makefile").read_text(encoding="utf-8")
        rule = makefile[makefile.index("$(EE_VPKD).ZIP:"):]
        rule = rule[:rule.index("\n\n") + 1]
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            licence = tree / "modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt"
            licence.parent.mkdir(parents=True)
            licence.write_bytes(b"LGPL-2.1 text")
            inputs = ("RIPTOPL-test.ELF", "DETAILED_CHANGELOG", "CREDITS", "LICENSE", "README.md")
            for name in inputs:
                (tree / name).write_bytes(name.encode())
            (tree / "Makefile").write_text("EE_VPKD = RIPTOPL-test\n" + rule, encoding="utf-8")
            archive = tree / "RIPTOPL-test.ZIP"

            def make():
                return subprocess.run(["make", "-B", "-s", archive.name], cwd=tree, capture_output=True, text=True)

            for run in ("first", "second"):  # a second run replaces the entries instead of adding duplicates
                result = make()
                self.assertEqual(result.returncode, 0, result.stderr)
                with zipfile.ZipFile(archive) as zipped:
                    self.assertEqual(sorted(zipped.namelist()), sorted(inputs + ("LICENSE-LIBSMB2.txt",)), run)
                    self.assertEqual(zipped.read("LICENSE-LIBSMB2.txt"), b"LGPL-2.1 text", run)
            licence.unlink()
            self.assertNotEqual(make().returncode, 0)
            self.assertFalse(archive.exists(), "a failed rule must not leave the archive behind")


if __name__ == "__main__":
    unittest.main()
