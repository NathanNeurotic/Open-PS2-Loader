"""ORBIT Neutrino Watch: when the RA runtime pin needs a review, and that the watch never moves it."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import orbit_neutrino_watch as watch  # noqa: E402

WORKFLOWS = ROOT / ".github/workflows"


class OrbitWatchTests(unittest.TestCase):
    def setUp(self):
        self.pin = json.loads((ROOT / "third_party/orbit-neutrino/release.json").read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def release(self, tag=None, name=None, digest="pin", **extra):
        digest = "sha256:" + self.pin["sha256"] if digest == "pin" else digest
        asset = {"name": name or self.pin["asset"], "digest": digest}
        release = {"tag_name": tag or self.pin["tag"], "html_url": "https://example.invalid/r",
                   "draft": False, "prerelease": False, "assets": [{"name": "launcher.elf"}, asset]}
        release.update(extra)
        return release

    def run_watch(self, release, *args):
        path = self.out / "release.json"
        path.write_text(json.dumps(release))
        watch.main(["--release", str(path), "--out", str(self.out / "o"), *args])
        issue = self.out / "o/issue.md"
        return (self.out / "o/status").read_text(), issue.read_text() if issue.exists() else None

    def test_pinned_release_is_current(self):
        self.assertEqual(self.run_watch(self.release()), ("current", None))

    def test_digest_compare_ignores_case(self):
        release = self.release(digest="sha256:" + self.pin["sha256"].upper())
        self.assertEqual(self.run_watch(release)[0], "current")

    def test_newer_release_asks_for_review(self):
        status, issue = self.run_watch(self.release("v9.9", "ORBIT-v9.9.zip", "sha256:" + "ab" * 32),
                                       "--tag-commit", "c0ffee")
        self.assertEqual(status, "changed")
        self.assertIn("`" + self.pin["tag"] + "` | `v9.9`", issue)
        suggested = json.loads(re.search(r"```json\n(.*?)\n```", issue, re.S).group(1))
        self.assertEqual((suggested["tag"], suggested["asset"], suggested["sha256"], suggested["source_commit"]),
                         ("v9.9", "ORBIT-v9.9.zip", "ab" * 32, "c0ffee"))
        # Review-only fields are carried over, never guessed.
        self.assertEqual(suggested["snapshot_bytes_max"], self.pin["snapshot_bytes_max"])
        self.assertIn("ordinary kits keep the upstream Neutrino", issue)

    def test_replaced_archive_under_the_same_tag_is_a_change(self):
        status, issue = self.run_watch(self.release(digest="sha256:" + "00" * 32))
        self.assertEqual(status, "changed")
        self.assertIn("archive was replaced", issue)

    def test_missing_pinned_asset_is_a_change(self):
        self.assertEqual(self.run_watch(self.release(name="ORBIT-renamed.zip"))[0], "changed")

    def test_missing_digest_needs_a_download_then_decides(self):
        self.assertEqual(self.run_watch(self.release(digest=None))[0], "unverified")
        self.assertEqual(self.run_watch(self.release(digest=None), "--asset-sha256", self.pin["sha256"])[0], "current")
        self.assertEqual(self.run_watch(self.release(digest=None), "--asset-sha256", "11" * 32)[0], "changed")

    def test_non_stable_answer_is_ignored(self):
        self.assertEqual(self.run_watch(self.release("v9.9", prerelease=True)), ("unknown", None))
        self.assertEqual(self.run_watch(self.release(tag_name="")), ("unknown", None))

    def test_issue_names_this_repository_snapshot_limit(self):
        _, issue = self.run_watch(self.release("v9.9"))
        self.assertTrue(any(path in issue for path, _ in watch.LIMIT_SITES))

    def test_pin_file_is_untouched(self):
        pin_path = ROOT / "third_party/orbit-neutrino/release.json"
        before = pin_path.read_bytes()
        self.run_watch(self.release("v9.9"))
        self.assertEqual(pin_path.read_bytes(), before)


class OrbitWatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "orbit-neutrino-watch.yml").read_text()

    def test_runs_on_the_neutrino_watch_schedule(self):
        cron = lambda text: re.findall(r"cron:\s*[\"']([^\"']+)", text)
        self.assertEqual(cron((WORKFLOWS / "neutrino-watch.yml").read_text()), cron(self.text))

    def test_reports_but_never_writes_the_repository(self):
        self.assertIn("contents: read", self.text)
        self.assertIn("issues: write", self.text)
        for forbidden in ("contents: write", "git push", "git commit", "actions: write"):
            self.assertNotIn(forbidden, self.text)

    def test_uses_the_script_and_stable_releases(self):
        self.assertIn(".github/scripts/orbit_neutrino_watch.py", self.text)
        self.assertIn("releases/latest", self.text)


if __name__ == "__main__":
    unittest.main()
