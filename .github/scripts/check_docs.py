#!/usr/bin/env python3
"""Check tracked Markdown and a gh-pages checkout for broken local links/anchors.

Run from any directory: python3 .github/scripts/check_docs.py --site ../pages
Requires beautifulsoup4 and markdown-it-py, like site_sync.py. External URLs are
inventoried for a separate network audit; an HTTP error is not a local-link error.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

REPO = "https://github.com/NathanNeurotic/Open-PS2-Loader/"
SITE = "https://nathanneurotic.github.io/Open-PS2-Loader/"
MD = MarkdownIt("commonmark", {"html": True}).enable("table")
# This verbatim upstream README documents the upstream archive layout, as its
# adjacent provenance README explains. Inventory these four known references;
# newly introduced missing links still fail the audit.
UPSTREAM_LAYOUT_LINKS = {
    "POPS/UDPFS-NOTICES/UPSTREAM-README.md": {
        "../LICENSE", "docs/README_CONFIG.txt", "docs/THIRD_PARTY_NOTICES.md", "licenses/",
    },
}
# Every website page carries this banner between the top bar and the layout, outside
# <main class="content">, so site_sync.py's page renders keep it.
LEGACY_NOTICE = "legacy-notice"


def document(path):
    text = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(MD.render(text) if path.suffix == ".md" else text, "html.parser")
    anchors = [node.get("id") or node.get("name") for node in soup.select("[id], a[name]")]
    if path.suffix == ".md":
        seen = Counter()
        for heading in soup.select("h1,h2,h3,h4,h5,h6"):
            slug = re.sub(r"[^\w\- ]", "", heading.get_text().lower()).replace(" ", "-")
            anchors.append(slug + (f"-{seen[slug]}" if seen[slug] else ""))
            seen[slug] += 1
    links = [node[attr] for tag, attr in (("a", "href"), ("img", "src"), ("script", "src"), ("link", "href"))
             for node in soup.find_all(tag) if node.get(attr)]
    return anchors, links


def audit(source, site):
    tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "*.md"], text=True).splitlines()
    files = [source / name for name in tracked]
    files += sorted(site.glob("*.html")) if site else []
    parsed = {path.resolve(): document(path) for path in files}
    errors, external, checked, upstream = [], {}, 0, []
    for path, (anchors, links) in parsed.items():
        label = ("site/" + path.name) if site and path.parent == site else path.relative_to(source).as_posix()
        if path.suffix == ".html":
            errors += [f"{label}: duplicate id {key}" for key, count in Counter(anchors).items() if count > 1]
            if LEGACY_NOTICE not in anchors:
                errors.append(f"{label}: missing the #{LEGACY_NOTICE} banner after the top bar")
        for url in links:
            if url in UPSTREAM_LAYOUT_LINKS.get(label, set()):
                upstream.append({"document": label, "upstream_relative_link": url})
                continue
            target, parts = None, urlsplit(url)
            if url.startswith(SITE):
                if site:
                    target = site / (unquote(parts.path[len(urlsplit(SITE).path):]) or "index.html")
            elif url.startswith(REPO + "blob/rebuild/main/") or url.startswith(REPO + "tree/rebuild/main/"):
                offset = "blob/rebuild/main/" if "/blob/" in url else "tree/rebuild/main/"
                target = source / unquote(parts.path.split(offset, 1)[1])
            elif not parts.scheme and not parts.netloc:
                target = (path.parent / unquote(parts.path)) if parts.path else path
            elif parts.scheme in ("http", "https"):
                external.setdefault(url.split("#", 1)[0], set()).add(label)
            if target is None:
                continue
            checked += 1
            target = target.resolve()
            if not target.exists():
                errors.append(f"{label}: missing file {url}")
            elif parts.fragment and target in parsed and unquote(parts.fragment) not in parsed[target][0]:
                errors.append(f"{label}: missing anchor {url}")
    return {"markdown_files": len(tracked), "website_pages": len(files) - len(tracked),
            "local_links_checked": checked, "errors": sorted(set(errors)),
            "preserved_upstream_layout_links": upstream,
            "external_urls": {url: sorted(origins) for url, origins in sorted(external.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--site", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(args.source.resolve(), args.site.resolve() if args.site else None)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Checked {report['markdown_files']} Markdown files, {report['website_pages']} website pages, "
          f"{report['local_links_checked']} local links; {len(report['external_urls'])} external URLs inventoried.")
    for error in report["errors"]:
        print(error)
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
