"""Release-note regressions: real Git history, assets, credits and repeat normalization."""
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name("normalize_release_notes.py")
spec = importlib.util.spec_from_file_location("notes", SCRIPT)
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)
README = (notes.ROOT / "README.md").read_text(encoding="utf-8")


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.patch = patch.object(notes, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "release-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        (self.root / "README.md").write_text(README, encoding="utf-8")
        for i in range(12):
            self.git("commit", "-q", "--allow-empty", "-m", f"Change {i}")
        branch = self.git("branch", "--show-current")
        self.git("checkout", "-q", "-b", "fix", "HEAD~2")
        self.git("commit", "-q", "--allow-empty", "-m", "Fix loader [edge case]")
        self.fix_sha = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", branch)
        self.git("merge", "-q", "--no-ff", "fix", "-m", "Merge rebuild/main into Korium")
        self.sha = self.git("rev-parse", "HEAD")
        self.git("tag", "v-test")
        self.git("commit", "-q", "--allow-empty", "-m", "Not in this release")
        self.assets = [
            "RIPTOPL-v1.zip", "RIPTOPL.ELF", "RIPTOPL-RA.ELF",
            "RIPTOPL-RetroAchievements-v1.zip", "APP_RIPTOPL.psu",
            "APP_RIPTOPL-RA.psu", "RIPTOPL-DEBUG-v1.zip",
            "RIPTOPL-LANGS-v1.zip", "RIPTOPL-VARIANTS-v1.zip", "RIPTOPL-v1-src.zip",
        ]

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root,
                                       text=True, encoding="utf-8").strip()

    def render(self, tag="rolling", assets=None):
        return notes.render(self.assets if assets is None else assets, tag, "refs/tags/v-test",
                            "owner/repo", "https://github.com", "v-test", "1.7.0", README)

    def test_release_history_is_bounded_and_pinned(self):
        body = self.render()
        changes = body.split("## Changelog\n", 1)[1]
        self.assertEqual(10, len([x for x in changes.splitlines() if x.startswith("- ")]))
        self.assertIn(f"Fix loader \\[edge case\\] ([{self.fix_sha[:8]}](https://github.com/owner/repo/commit/{self.fix_sha}))", changes)
        self.assertNotIn("Merge rebuild/main", changes)
        self.assertNotIn("Not in this release", changes)
        self.assertNotIn("- Change 0 ", changes)
        self.assertTrue(body.endswith(f"[Full changelog](https://github.com/owner/repo/commits/{self.sha})\n"))
        self.assertEqual(["## Downloads", "## Credits", "## Changelog"],
                         [x for x in body.splitlines() if x.startswith("## ")])

    def test_actual_downloads_and_short_credits(self):
        body = self.render(assets=["RIPTOPL.ELF"])
        downloads = body.split("## Downloads\n", 1)[1].split("## Credits", 1)[0]
        self.assertEqual(1, downloads.count("\n- "))
        self.assertNotIn("RIPTOPL-RA.ELF", downloads)
        credit_block = body.split("## Credits\n", 1)[1].split("## Changelog", 1)[0]
        self.assertIn("Gageformer", credit_block)
        self.assertIn("https://github.com/Gageformer/Ember/releases", credit_block)
        self.assertIn("https://github.com/rickgaiser/neutrino", credit_block)
        self.assertIn("https://github.com/hacan359/xerabora", credit_block)
        self.assertNotIn("—", credit_block)
        self.assertNotIn("<img", body)
        self.assertLess(len(body), 8000)

    def test_channels_and_tagged_releases(self):
        for tag in ("rolling", "rolling-korium", "v1.2.3"):
            body = self.render(tag=tag)
            self.assertIn(f"/releases/download/{tag}/RIPTOPL.ELF", body)
            self.assertIn("## Changelog", body)
            self.assertEqual("Korium Komblete" in body, tag == "rolling-korium")

    def test_transient_uploads_not_advertised(self):
        for name in ("RIPTOPL-v1-OFFICIALROLLING.ELF", "SHA256SUMS.txt",
                     "DETAILED_CHANGELOG", "IRX_MANIFEST.txt"):
            self.assertFalse(notes.staged_asset(name))
        self.assertTrue(all(notes.staged_asset(name) for name in self.assets))

    def test_repeat_normalization_preserves_watcher_and_changelog(self):
        original = self.render()
        source = self.root / "release.json"
        for _ in range(2):
            source.write_text(json.dumps({"assets": [{"name": n} for n in self.assets],
                                          "body": original}), encoding="utf-8")
            output = io.StringIO()
            with patch.object(sys, "argv", [str(SCRIPT), "--release-json", str(source),
                                          "--tag", "rolling", "--revision", "refs/tags/v-test",
                                          "--repository", "owner/repo"]), contextlib.redirect_stdout(output):
                notes.main()
            self.assertEqual(original, output.getvalue())
            self.assertIn("Included build: 1.7.0 ", output.getvalue())
            original = output.getvalue()

    def test_initial_publish_matches_normalized_notes(self):
        staged = self.root / "assets"
        staged.mkdir()
        for name in self.assets + ["RIPTOPL-stamped.ELF", "SHA256SUMS.txt", "DETAILED_CHANGELOG"]:
            (staged / name).touch()
        (staged / "subdirectory").mkdir()
        output = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), "--assets-dir", str(staged),
                                      "--tag", "rolling", "--revision", "refs/tags/v-test",
                                      "--repository", "owner/repo", "--version", "v-test",
                                      "--neutrino-version", "1.7.0"]), contextlib.redirect_stdout(output):
            notes.main()
        self.assertEqual(self.render(), output.getvalue())

    def test_missing_assets_or_history_fails_instead_of_silent_changelog_loss(self):
        with self.assertRaises(ValueError):
            self.render(assets=[])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(subprocess.CalledProcessError):
            notes.changelog("refs/tags/does-not-exist", "https://github.com/owner/repo")


if __name__ == "__main__":
    unittest.main()
