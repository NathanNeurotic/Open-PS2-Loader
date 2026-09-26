#!/usr/bin/env python3
"""Regenerate the GitHub Pages files that are derived from other files.

  retroachievements.html   its <main class="content"> body, rendered from docs/RETROACHIEVEMENTS.md
  data/search-index.json   the site search index, rebuilt from the pages themselves

Both used to be maintained by hand and drifted: the 2026-09-24 documentation audit found the RA page
four sections behind its Markdown source and 12 of 341 search entries describing text that was no
longer on the page. docs-sync.yml runs this after every rebuild/main push (and daily, which is what
picks up a gh-pages merge), so edit the sources, not these two outputs.

Usage, from a rebuild/main checkout with gh-pages checked out somewhere else:

  python3 .github/scripts/site_sync.py --site ../gh-pages --ra-md docs/RETROACHIEVEMENTS.md
  python3 .github/scripts/site_sync.py --site ../gh-pages --ra-md docs/RETROACHIEVEMENTS.md --check

--check writes nothing and exits 1 when either file is out of date. Needs beautifulsoup4 and
markdown-it-py (docs-sync.yml pins the versions).

Search index rules (they match how the hand-built index was laid out, so curated entries survive):
  * one entry per page and one per h2/h3 inside <main> that has an id, plus any other anchor the
    index already carries (a <details> block, say), with that element's own text;
  * an h2 section runs to the next h2, so it includes its h3 subsections; an h3 runs to the next
    indexed heading;
  * text is the rendered text: tags stripped, a space at block boundaries and none around inline
    elements, entities decoded, whitespace collapsed;
  * an existing entry keeps its title and category (they are curated -- edit them in the index);
    a new page takes its category from its sidebar group, a new section a title built from its
    heading;
  * pages keep their order and new pages are appended; duplicate URLs are dropped; a page that is
    indexed by its sections alone (the home page) does not gain a page entry.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown_it import MarkdownIt

REPO_BLOB = "https://github.com/NathanNeurotic/Open-PS2-Loader/blob/rebuild/main/"
INDEX = Path("data") / "search-index.json"
RA_PAGE = "retroachievements.html"
MAIN_OPEN = '<main class="content">'
MAIN_CLOSE = "</main>"

BLOCK = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "details", "div", "dl",
    "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul",
}

# Sidebar group -> category, for a page that has no index entry yet.
GROUP_CATEGORY = {"start": "start", "game sources": "devices", "features": "features",
                  "theme engine": "themes", "reference": "reference"}

# GitHub alerts become the site's own callouts (assets/style.css defines info, amber and red).
ALERTS = {"NOTE": ("info", "Note"), "TIP": ("info", "Tip"),
          "IMPORTANT": ("amber", "Important"), "WARNING": ("amber", "Warning"),
          "CAUTION": ("red", "Caution")}


# ------------------------------------------------------------------------------------------------
# Markdown -> site HTML


def github_slug(text: str, seen: dict[str, int]) -> str:
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def render_markdown(markdown: str, doc_dir: str = "docs/") -> str:
    """The Markdown the way GitHub shows it, in the site's markup (ids, callouts, absolute links)."""
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown)
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, int] = {}
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading["id"] = github_slug(heading.get_text(), seen)
    for tag, attr in (("a", "href"), ("img", "src")):
        for node in soup.find_all(tag):
            target = node.get(attr)
            # A repo-relative link would 404 on the site; point it at the file on rebuild/main.
            if target and not re.match(r"^([a-z][a-z0-9+.-]*:|#|/)", target, re.I):
                node[attr] = REPO_BLOB + posixpath.normpath(posixpath.join(doc_dir, target))
    for quote in soup.find_all("blockquote"):
        first = quote.find("p")
        if first is None or not first.contents or not isinstance(first.contents[0], NavigableString):
            continue
        match = re.match(r"\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", str(first.contents[0]))
        if not match:
            continue
        css, title = ALERTS[match.group(1)]
        first.contents[0].replace_with(str(first.contents[0])[match.end():])
        callout = soup.new_tag("div", attrs={"class": "callout " + css})
        head = soup.new_tag("div", attrs={"class": "h"})
        head.string = title
        callout.append(head)
        for node in list(first.contents):
            callout.append(node.extract())
        for rest in quote.find_all("p")[1:]:
            callout.append(rest.extract())
        quote.replace_with(callout)
    return str(soup).strip()


def replace_main(page_html: str, body: str) -> str:
    start = page_html.index(MAIN_OPEN) + len(MAIN_OPEN)
    end = page_html.index(MAIN_CLOSE, start)
    return page_html[:start] + "\n" + body + "\n" + page_html[end:]


# ------------------------------------------------------------------------------------------------
# Search index


def text_of(nodes) -> str:
    out: list[str] = []

    def walk(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            out.append(str(node))
            return
        if not isinstance(node, Tag) or node.name in ("script", "style"):
            return
        block = node.name in BLOCK
        if block:
            out.append(" ")
        for child in node.children:
            walk(child)
        if block:
            out.append(" ")

    for node in nodes:
        walk(node)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def section_nodes(heading: Tag, stop: Tag | None) -> list:
    """The heading and everything after it in document order, up to (not including) stop."""
    nodes = [heading]

    def take_until_stop(container):
        for child in container.children:
            if child is stop:
                return True
            if isinstance(child, Tag) and stop is not None and stop in child.descendants:
                return take_until_stop(child)
            nodes.append(child)
        return False

    node = heading
    while True:
        sibling = node.next_sibling
        while sibling is None:
            node = node.parent
            if node is None or node.name == "main":
                return nodes
            sibling = node.next_sibling
        node = sibling
        if node is stop:
            return nodes
        if isinstance(node, Tag) and stop is not None and stop in node.descendants:
            take_until_stop(node)
            return nodes
        nodes.append(node)


def page_entries(path: Path, extra_ids: set[str] = frozenset(), html: str | None = None) -> tuple[str, list[dict]]:
    """(h1 text, [page entry, section entries...]) with titles/categories still to be filled in.

    extra_ids: anchors on other elements (a <details>, say) that the index already carries; each
    keeps its entry, with that element's own text."""
    soup = BeautifulSoup(html if html is not None else path.read_text(encoding="utf-8"), "html.parser")
    main = soup.find("main")
    if main is None:
        raise SystemExit(f"{path}: no <main> element")
    h1 = main.find("h1")
    page_title = text_of([h1]) if h1 else path.stem
    entries = [{"title": page_title, "text": text_of([main]), "url": path.name}]
    heads = [h for h in main.find_all(["h2", "h3"]) if h.get("id")]
    for node in main.find_all(id=True):
        if node in heads:
            i = heads.index(node)
            later = heads[i + 1:] if node.name == "h3" else [h for h in heads[i + 1:] if h.name == "h2"]
            text = text_of(section_nodes(node, later[0] if later else None))
        elif node["id"] in extra_ids:
            text = text_of([node])
        else:
            continue
        entries.append({"title": text_of([node.find("summary") or node]), "tag": node.name, "text": text,
                        "url": f"{path.name}#{node['id']}"})
    return page_title, entries


def sidebar_categories(site: Path) -> dict[str, str]:
    """page.html -> category, from the sidebar groups in index.html."""
    index = site / "index.html"
    if not index.exists():
        return {}
    nav = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser").find("nav")
    group, result = "", {}
    for node in nav.find_all(["h4", "a"]) if nav else []:
        if node.name == "h4":
            group = GROUP_CATEGORY.get(node.get_text(strip=True).lower(), "reference")
        elif node.get("href", "").endswith(".html") and "://" not in node["href"]:
            result.setdefault(node["href"], group or "reference")
    return result


def build_index(site: Path, old: list[dict], pending: dict[str, str] | None = None) -> list[dict]:
    """pending: page name -> HTML about to be written, so --check indexes what a real run would."""
    pending = pending or {}
    old_by_url: dict[str, dict] = {}
    order: list[str] = []
    for entry in old:
        old_by_url.setdefault(entry["url"], entry)
        page = entry["url"].split("#")[0]
        if page not in order:
            order.append(page)
    pages = sorted(p.name for p in site.glob("*.html"))
    sidebar = sidebar_categories(site)
    order = [p for p in order if p in pages]
    order += [p for p in sorted(pages, key=lambda p: (list(sidebar).index(p) if p in sidebar else len(sidebar), p))
              if p not in order]
    indexed_pages = {e["url"].split("#")[0] for e in old}
    result = []
    for page in order:
        extra = {u.split("#", 1)[1] for u in old_by_url if u.startswith(page + "#")}
        page_title, entries = page_entries(site / page, extra, pending.get(page))
        known = old_by_url.get(page)
        if known is None and page in indexed_pages:
            entries = entries[1:]  # indexed by its sections only (the home page): keep it that way
        category = known["cat"] if known else sidebar.get(page, "reference")
        title = known["title"] if known else page_title
        for entry in entries:
            previous = old_by_url.get(entry["url"])
            if previous is not None:
                entry_title, entry_cat = previous["title"], previous["cat"]
            elif "#" not in entry["url"]:
                entry_title, entry_cat = title, category
            else:
                heading = re.sub(r"^\d+\s*·\s*", "", entry["title"])
                entry_title = heading if entry["tag"] == "h2" else f"{title} — {heading}"
                entry_cat = category
            result.append({"title": entry_title, "cat": entry_cat, "text": entry["text"], "url": entry["url"]})
    return result


def dump_index(entries: list[dict]) -> str:
    # One entry per line: diffs and merges stay reviewable, and app.js only needs valid JSON.
    lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in entries]
    return "[\n" + ",\n".join(lines) + "\n]\n"


# ------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", required=True, type=Path, help="gh-pages checkout")
    parser.add_argument("--ra-md", type=Path, help="docs/RETROACHIEVEMENTS.md to render into " + RA_PAGE)
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if out of date")
    args = parser.parse_args(argv)

    stale, pending = [], {}
    if args.ra_md is not None:
        page = args.site / RA_PAGE
        before = page.read_text(encoding="utf-8")
        after = replace_main(before, render_markdown(args.ra_md.read_text(encoding="utf-8")))
        if after != before:
            stale.append(RA_PAGE)
            pending[RA_PAGE] = after
            if not args.check:
                page.write_text(after, encoding="utf-8")

    index_path = args.site / INDEX
    before = index_path.read_text(encoding="utf-8")
    old = json.loads(before)
    new = build_index(args.site, old, pending)
    after = dump_index(new)
    if after != before:
        stale.append(str(INDEX))
        changed = sum(1 for e in new if e not in old)
        dropped = len({e["url"] for e in old} - {e["url"] for e in new})
        print(f"{INDEX}: {len(old)} -> {len(new)} entries, {changed} new or changed, "
              f"{dropped} URL(s) gone, {len(old) - len({e['url'] for e in old})} duplicate(s) removed")
        if not args.check:
            index_path.write_text(after, encoding="utf-8")

    if args.check and stale:
        print("out of date: " + ", ".join(stale))
        return 1
    print("up to date" if not stale else "regenerated: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
