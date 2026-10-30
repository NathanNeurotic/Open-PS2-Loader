#!/usr/bin/env python3
"""Regenerate the GitHub Pages files that are derived from other files.

  retroachievements.html   its <main class="content"> body, rendered from docs/RETROACHIEVEMENTS.md
  any --md-page PAGE       likewise, from the Markdown file named with it (ps2sdk-notes.html from
                           docs/PS2SDK-NOTES.md)
  data/search-index.json   the site search index, rebuilt from the pages themselves

Both used to be maintained by hand and drifted: the 2026-09-24 documentation audit found the RA page
four sections behind its Markdown source and 12 of 341 search entries describing text that was no
longer on the page. docs-sync.yml runs this after every rebuild/main push (and daily, which is what
picks up a gh-pages merge), so edit the sources, not these two outputs.

Usage, from a rebuild/main checkout with gh-pages checked out somewhere else:

  python3 .github/scripts/site_sync.py --site ../gh-pages --ra-md docs/RETROACHIEVEMENTS.md \
      --md-page docs/PS2SDK-NOTES.md=ps2sdk-notes.html
  python3 .github/scripts/site_sync.py --site ../gh-pages --ra-md docs/RETROACHIEVEMENTS.md \
      --md-page docs/PS2SDK-NOTES.md=ps2sdk-notes.html --check

--check writes nothing and exits 1 when any file is out of date. Needs beautifulsoup4 and
markdown-it-py (docs-sync.yml pins the versions).

An --md-page page keeps its own head, sidebar and footer; only <main class="content"> is replaced, so
the page has to exist on gh-pages first. Until it does, it is skipped with a note rather than failing
the run, so the source change and the gh-pages change can land in either order.

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
REPO_ROOT = Path(__file__).resolve().parents[2]
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


def doc_dir_of(source: Path) -> str:
    """The repository directory a Markdown file's relative links start from: its own directory, when it
    is inside the checkout that holds this script; docs/ otherwise."""
    try:
        parent = source.resolve().relative_to(REPO_ROOT).parent.as_posix()
    except ValueError:
        return "docs/"
    return "" if parent == "." else parent + "/"


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


def ra_release_links(html: str, releases: bool = False) -> str:
    """Keep RA downloads together in their dedicated two-theme channel."""
    base = "https://github.com/NathanNeurotic/Open-PS2-Loader/releases"
    callout = (
        '<section class="callout info" id="ra-release-channel"><div class="h">RetroAchievements downloads</div>'
        f'<p>The <a href="{base}/tag/rolling-ra">single experimental RetroAchievements release</a> '
        'offers both <b>inceBtion</b> and <b>Korium</b> themes. Choose one complete theme kit. '
        'Both use the same RiptOPL source revision and the pinned '
        '<a href="https://github.com/danielnuld/ps2-launcher/releases/tag/v1.0.2">ORBIT Neutrino RA runtime v1.0.2</a>, '
        'which replaces upstream Neutrino in the RA kits. '
        'Standard Rolling and Korium downloads contain standard builds only. '
        'Installing the other RA theme replaces the same <code>APP_RIPTOPL-RA</code> app. '
        'See the <a href="retroachievements.html">RA setup guide and compatibility limits</a>.</p></section>'
    )
    pattern = r'<section\b[^>]*\bid="ra-release-channel"[^>]*>.*?</section>'
    if re.search(pattern, html, re.S):
        html = re.sub(pattern, lambda _: callout, html, count=1, flags=re.S)
    else:
        html, count = re.subn(r'(<main\b[^>]*>)', lambda match: match[1] + "\n" + callout,
                             html, count=1)
        if count != 1:
            raise ValueError("site page is missing main content for RA release links")
    if releases:
        # Replace complete old download rows; retain unrelated curated page text.
        rows = {
            "RIPTOPL-RA.ELF": (
                '<td><code>RIPTOPL-RA-inceBtion.ELF</code>, <code>RIPTOPL-RA-Korium.ELF</code></td>'
                '<td>Theme-specific RetroAchievements updates: '
                f'<a href="{base}/download/rolling-ra/RIPTOPL-RA-inceBtion.ELF">inceBtion ELF</a> or '
                f'<a href="{base}/download/rolling-ra/RIPTOPL-RA-Korium.ELF">Korium ELF</a>. '
                'Rename the selected download to <code>RIPTOPL-RA.ELF</code> when replacing '
                '<code>APPS/APP_RIPTOPL-RA/RIPTOPL-RA.ELF</code>. Full kits install the runtime.</td>'
            ),
            "APP_RIPTOPL.psu": (
                '<td><code>APP_RIPTOPL.psu</code>; RA theme saves</td><td>Standard app-only '
                f'save from Rolling. The <a href="{base}/tag/rolling-ra">RA release</a> has '
                '<code>APP_RIPTOPL-RA-inceBtion.psu</code> and <code>APP_RIPTOPL-RA-Korium.psu</code>. '
                'Both RA saves import into <code>APP_RIPTOPL-RA</code>; copy shared folders from '
                'the matching full kit separately.</td>'
            ),
            "RIPTOPL-RetroAchievements-*.zip": (
                '<td><code>RIPTOPL-RetroAchievements-inceBtion-&lt;version&gt;.zip</code><br>'
                '<code>RIPTOPL-RetroAchievements-Korium-&lt;version&gt;.zip</code></td>'
                f'<td>Both full theme kits in <a href="{base}/tag/rolling-ra">one RA release</a>. '
                'Each includes the ready official-toolchain app, ps2dev comparison apps, artwork, '
                'PSU, POPS, Ember, the pinned <a href="https://github.com/danielnuld/ps2-launcher/releases/tag/v1.0.2">'
                'ORBIT Neutrino RA runtime v1.0.2</a> (in place of upstream Neutrino) and companion links. '
                'Experimental: review the <a href="retroachievements.html">setup and limits</a>.</td>'
            ),
        }
        for key, row in rows.items():
            html = re.sub(r'<tr>\s*<td><code>' + re.escape(key) + r'</code>.*?</tr>',
                          lambda _: "<tr>" + row + "</tr>", html, count=1, flags=re.S)
        html = html.replace('Its name never changes (the same goes for <code>RIPTOPL-RA.ELF</code> below), so',
                            'Its name never changes, so')
        html = re.sub(
            r'<div class="callout info"><div class="h">At most two loose ELFs, everything else in archives</div>.*?</div>',
            '<div class="callout info"><div class="h">Separate standard and RA downloads</div>'
            'Standard releases retain <code>RIPTOPL.ELF</code>, their app-only PSU and install archives. '
            'The dedicated RA release retains one ELF update and PSU per theme, both full kits, '
            'its source snapshot, provenance and checksums. DualSense comparison loaders remain '
            'in the standard VARIANTS archive.</div>', html, count=1, flags=re.S)
        # Remaining references describe the installed filename, not a public asset.
        html = html.replace(f"{base}/download/rolling/RIPTOPL-RA.ELF",
                            f"{base}/tag/rolling-ra")
    return html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", required=True, type=Path, help="gh-pages checkout")
    parser.add_argument("--ra-md", type=Path, help="docs/RETROACHIEVEMENTS.md to render into " + RA_PAGE)
    parser.add_argument("--md-page", action="append", default=[], metavar="MD=PAGE",
                        help="render the Markdown file MD into the site page PAGE (repeatable)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if out of date")
    args = parser.parse_args(argv)
    md_pages = []
    for spec in args.md_page:
        source, sep, name = spec.partition("=")
        if not sep or not source or not name.endswith(".html") or "/" in name or name == RA_PAGE:
            parser.error(f"--md-page wants SOURCE.md=PAGE.html (a top-level page other than {RA_PAGE}), got {spec!r}")
        md_pages.append((Path(source), name))

    stale, pending = [], {}
    for name in ("index.html", "releases.html"):
        page = args.site / name
        if not page.exists():
            continue  # Minimal test/documentation sites need not include download pages.
        before = page.read_text(encoding="utf-8")
        after = ra_release_links(before, releases=name == "releases.html")
        if after != before:
            stale.append(name)
            pending[name] = after
            if not args.check:
                page.write_text(after, encoding="utf-8")
    rendered = [(args.ra_md, RA_PAGE)] if args.ra_md is not None else []
    for source, name in rendered + md_pages:
        page = args.site / name
        if name != RA_PAGE and not page.exists():
            print(f"skipped: {name} is not on the site yet, so {source} has nowhere to go")
            continue
        before = page.read_text(encoding="utf-8")
        after = replace_main(before, render_markdown(source.read_text(encoding="utf-8"), doc_dir_of(source)))
        if after != before:
            stale.append(name)
            pending[name] = after
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
