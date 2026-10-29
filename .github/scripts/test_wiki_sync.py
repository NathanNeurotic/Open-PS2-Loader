"""Exercise wiki conversion of table bookmarks and legacy source indexes."""

from pathlib import Path
import tempfile
import unittest

from bs4 import BeautifulSoup

import wiki_sync


class WikiConversionTests(unittest.TestCase):
    def test_table_row_and_cell_bookmarks_preserve_table_and_code(self):
        html = '''<main class="content"><h1>Directory</h1>
<table id="directory"><thead><tr><th>Project</th><th>Example</th></tr></thead>
<tbody><tr id="catalog-a"><td>A</td><td id="example"><code>a|b</code></td></tr>
<tr><td>B</td><td>Two</td></tr></tbody></table><pre>sample &lt;code&gt;</pre></main>'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "directory.html"
            path.write_text(html)
            result = wiki_sync.convert_site(path, "abc123")
        rendered = BeautifulSoup(wiki_sync.MD.render(result), "html.parser")
        self.assertEqual(len(rendered.select("table")), 1)
        self.assertEqual(len(rendered.select("td")), 4)
        self.assertEqual(rendered.select_one("code").get_text(), "a|b")
        self.assertEqual(rendered.select_one("pre").get_text().strip(), "sample <code>")
        for anchor in ("directory", "catalog-a", "example"):
            self.assertIn(anchor, wiki_sync.anchors_and_links(result)[0])

    def test_code_example_inside_table_cell_keeps_table_and_lines(self):
        html = '''<main class="content"><h1>Troubleshooting</h1>
<table><thead><tr><th>Problem</th><th>Fix</th></tr></thead>
<tbody><tr><td>Freeze</td><td>In smb.conf set
<pre>keepalive = 0
a|b &lt;x&gt;</pre>
and restart Samba.</td></tr>
<tr><td>Other</td><td>Two</td></tr></tbody></table></main>'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "smb.html"
            path.write_text(html)
            result = wiki_sync.convert_site(path, "abc123")
        rendered = BeautifulSoup(wiki_sync.MD.render(result), "html.parser")
        self.assertEqual(len(rendered.select("table")), 1)
        self.assertEqual(len(rendered.select("td")), 4)
        self.assertEqual(rendered.select_one("td pre").get_text(), "keepalive = 0\na|b <x>")

    def test_source_index_keeps_duplicate_headings_and_explicit_bookmarks(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "README.md").write_text('# Original\n\n## Setup\n\n## Setup\n\n<a name="old-link"></a>\n')
            result = wiki_sync.reference_index("README.md", "Repository-Guide", "Guide", source, "abc123")
        anchors, links = wiki_sync.anchors_and_links(result)
        self.assertTrue({"original", "setup", "setup-1", "old-link"} <= anchors)
        self.assertIn(wiki_sync.WIKI + "Documentation-Index", links)
        self.assertTrue(any("/blob/abc123/README.md#setup-1" in link for link in links))


if __name__ == "__main__":
    unittest.main()
