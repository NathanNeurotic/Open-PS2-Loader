#!/usr/bin/env python3
"""Check site_sync.py: the search-index rules, the RA page render and the --check contract."""

import json
import tempfile
import unittest
from pathlib import Path

import site_sync

NAV = """<nav class="sidebar">
  <a href="index.html">Home</a>
  <h4>Start</h4><a href="guide.html">Guide</a>
  <h4>Features</h4><a href="retroachievements.html">RA</a><a href="newpage.html">New</a>
  <h4>Reference</h4><a href="faq.html">FAQ</a>
</nav>"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><title>t</title></head><body>{NAV}\n  <main class=\"content\">\n{body}\n</main>\n<footer>f</footer></body></html>"


GUIDE = page("""<h1>Guide</h1>
<p class="lead">Lead <code>text</code> here.</p>
<h2 id="one">One</h2>
<p>Alpha&nbsp;<b>bold</b>, x&minus;y.</p>
<h3 id="one-sub">Sub</h3>
<table><tr><td>cell</td><td>two</td></tr></table>
<h2 id="two">Two</h2>
<ul><li>item</li><li>more</li></ul>
<details class="deep" id="more"><summary>More?</summary><p>Hidden detail.</p></details>
<h2>No id, not indexed</h2><p>tail</p>""")

RA_MD = """# Title

Intro with [a relative link](IGR.md#igr) and [an absolute one](https://example.com/).

## Status

| Part | State |
| --- | --- |
| telemetry | done |

## Status

```bash
make RETROACHIEVEMENTS=1
```

> [!IMPORTANT]
> **Heads up:** keep the client current.
"""


class SiteSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        (self.site / "data").mkdir()
        (self.site / "index.html").write_text(page('<h1>Home</h1><h2 id="intro">Intro</h2><p>hi</p>'), encoding="utf-8")
        (self.site / "guide.html").write_text(GUIDE, encoding="utf-8")
        (self.site / "newpage.html").write_text(page('<h1>New Page</h1><h3 id="deep">Deep</h3><p>x</p>'), encoding="utf-8")
        (self.site / "retroachievements.html").write_text(page("<h1>Old RA</h1><p>stale</p>"), encoding="utf-8")
        self.md = self.site / "RA.md"
        self.md.write_text(RA_MD, encoding="utf-8")
        old = [
            {"title": "Guide", "cat": "start", "text": "stale", "url": "guide.html"},
            {"title": "Curated — One", "cat": "start", "text": "stale", "url": "guide.html#one"},
            {"title": "Curated — One", "cat": "start", "text": "dup", "url": "guide.html#one"},
            {"title": "More (curated)", "cat": "start", "text": "old", "url": "guide.html#more"},
            {"title": "Gone", "cat": "start", "text": "x", "url": "guide.html#removed"},
            {"title": "Intro", "cat": "reference", "text": "hi", "url": "index.html#intro"},
            {"title": "RetroAchievements", "cat": "Features", "text": "stale", "url": "retroachievements.html"},
        ]
        (self.site / "data" / "search-index.json").write_text(json.dumps(old, separators=(",", ":")), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def index(self):
        return json.loads((self.site / "data" / "search-index.json").read_text(encoding="utf-8"))

    def run_sync(self, *extra):
        return site_sync.main(["--site", str(self.site), "--ra-md", str(self.md), *extra])

    def test_text_extraction(self):
        by_url = {e["url"]: e for e in site_sync.build_index(self.site, json.loads((self.site / "data" / "search-index.json").read_text()))}
        # Blocks are separated, inline elements are not, entities are decoded (a no-break space too).
        self.assertTrue(by_url["guide.html"]["text"].startswith("Guide Lead text here. One Alpha bold, x\u2212y."))
        # An h2 section includes its h3 subsection and stops at the next h2.
        self.assertEqual(by_url["guide.html#one"]["text"], "One Alpha bold, x\u2212y. Sub cell two")
        # An h3 section runs to the next indexed heading.
        self.assertEqual(by_url["guide.html#one-sub"]["text"], "Sub cell two")
        # A heading without an id is not an entry, so the last h2 section runs to the end of <main>.
        self.assertEqual(by_url["guide.html#two"]["text"], "Two item more More? Hidden detail. No id, not indexed tail")

    def test_curation_order_and_duplicates(self):
        old = json.loads((self.site / "data" / "search-index.json").read_text())
        new = site_sync.build_index(self.site, old)
        urls = [e["url"] for e in new]
        self.assertEqual(len(urls), len(set(urls)), "duplicate URLs must be dropped")
        by_url = {e["url"]: e for e in new}
        self.assertEqual(by_url["guide.html#one"]["title"], "Curated — One")  # curated title kept
        self.assertEqual(by_url["guide.html#two"]["title"], "Two")  # new h2: heading text
        self.assertEqual(by_url["guide.html#one-sub"]["title"], "Guide — Sub")  # new h3: page — heading
        self.assertEqual(by_url["guide.html#more"]["title"], "More (curated)")  # non-heading anchor kept
        self.assertEqual(by_url["guide.html#more"]["text"], "More? Hidden detail.")
        self.assertNotIn("guide.html#removed", by_url)  # anchor gone from the page
        self.assertNotIn("index.html", by_url)  # indexed by sections only: no page entry added
        # Existing pages keep their order; the new page is appended with its sidebar category.
        pages = list(dict.fromkeys(u.split("#")[0] for u in urls))
        self.assertEqual(pages, ["guide.html", "index.html", "retroachievements.html", "newpage.html"])
        self.assertEqual(by_url["newpage.html"], {"title": "New Page", "cat": "features", "text": "New Page Deep x", "url": "newpage.html"})
        self.assertEqual(by_url["newpage.html#deep"]["title"], "New Page — Deep")

    def test_ra_render(self):
        body = site_sync.render_markdown(RA_MD)
        self.assertIn('<h1 id="title">Title</h1>', body)
        self.assertIn('<h2 id="status">Status</h2>', body)
        self.assertIn('<h2 id="status-1">Status</h2>', body)  # GitHub's duplicate-heading suffix
        self.assertIn('href="https://github.com/NathanNeurotic/Open-PS2-Loader/blob/rebuild/main/docs/IGR.md#igr"', body)
        self.assertIn('href="https://example.com/"', body)
        self.assertIn("<table>", body)
        self.assertIn('<code class="language-bash">', body)
        self.assertIn('<div class="callout amber"><div class="h">Important</div><strong>Heads up:</strong>', body)
        self.assertNotIn("[!IMPORTANT]", body)
        self.assertNotIn("<blockquote>", body)

    def test_check_write_and_idempotency(self):
        ra = self.site / "retroachievements.html"
        before = ra.read_text(encoding="utf-8")
        index_before = (self.site / "data" / "search-index.json").read_text(encoding="utf-8")
        self.assertEqual(self.run_sync("--check"), 1)
        self.assertEqual(ra.read_text(encoding="utf-8"), before, "--check must not write")
        self.assertEqual((self.site / "data" / "search-index.json").read_text(encoding="utf-8"), index_before)
        # --check indexes the RA page it would write, so its report matches a real run.
        pending = {"retroachievements.html": site_sync.replace_main(before, site_sync.render_markdown(RA_MD))}
        checked = site_sync.build_index(self.site, json.loads(index_before), pending)
        self.assertIn("retroachievements.html#status-1", [e["url"] for e in checked])
        self.assertEqual(self.run_sync(), 0)
        after = ra.read_text(encoding="utf-8")
        self.assertIn('<h2 id="status">', after)
        self.assertNotIn("Old RA", after)
        self.assertTrue(after.startswith(before[: before.index('<main class="content">')]), "page chrome must survive")
        self.assertTrue(after.endswith("</main>\n<footer>f</footer></body></html>"))
        raw = (self.site / "data" / "search-index.json").read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("[\n{") and raw.endswith("}\n]\n"), "one entry per line")
        self.assertEqual(len(raw.splitlines()), len(self.index()) + 2)
        self.assertEqual(self.run_sync("--check"), 0, "a second run must find nothing to change")


if __name__ == "__main__":
    unittest.main()
