"""Build the RiptOPL wiki from read-only source and GitHub Pages checkouts.

Run: python .github/scripts/wiki_sync.py --source . --site ../site --wiki ../wiki
Only this wiki checkout is written. Publishing is a separate, manual git push.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from markdownify import MarkdownConverter

REPO = "https://github.com/NathanNeurotic/Open-PS2-Loader"
SITE = "https://nathanneurotic.github.io/Open-PS2-Loader/"
WIKI = REPO + "/wiki/"
ROOT = None  # Explicit output checkout, selected by --wiki.
MD = MarkdownIt("commonmark", {"html": True}).enable("table")
COMPAT_BUILDER = '''"""Compatibility entry point; the reviewed builder now lives in the source repository."""
import argparse
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--source", required=True, type=Path)
args, _ = parser.parse_known_args()
builder = args.source.resolve() / ".github/scripts/wiki_sync.py"
if not builder.is_file():
    raise SystemExit("Update the source checkout: .github/scripts/wiki_sync.py is required.")
options = sys.argv[1:]
if "--wiki" not in options:
    options += ["--wiki", str(Path(__file__).resolve().parent.parent)]
raise SystemExit(subprocess.call([sys.executable, str(builder), *options]))
'''

# Website pages remain the task-oriented guides; repository documents supply
# their complete, often more detailed references without a second manual copy.
SITE_GROUPS = {
    "Start here": [
        ("getting-started", "Getting-Started", "Getting started"),
        ("install", "Installation", "Installation and first boot"),
        ("releases", "Releases", "Releases and packages"),
        ("launch-diagnostics", "Launch-Diagnostics-Guide", "Launch diagnostics"),
    ],
    "Storage and networking": [
        ("usb", "USB-MX4SIO-and-iLink", "USB, MX4SIO and iLink"),
        ("mmce", "MMCE", "MMCE"),
        ("hdd", "Internal-HDD", "Internal HDD: APA and exFAT"),
        ("psx-dvr", "PSX-DVR", "PSX DESR DVR (experimental)"),
        ("pc-card-cf", "PC-CARD-CompactFlash", "PC CARD CompactFlash (experimental)"),
        ("smb", "SMB", "SMB shares"),
        ("network-boot", "Network-Boot", "Network boot: UDPFS and UDPBD"),
        ("http", "HTTP", "HTTP"),
        ("nbd", "NBD-Server", "NBD server"),
    ],
    "Games and features": [
        ("game-formats", "Game-Formats", "Game image formats: ISO, ZSO, CHD and CSO"),
        ("neutrino", "Neutrino", "Neutrino core"),
        ("ps1-vcd", "PS1-Games", "PS1: POPStarter and Ember"),
        ("per-game-settings", "Per-Game-Settings", "Per-game settings"),
        ("vmc", "Virtual-Memory-Cards", "Virtual memory cards"),
        ("gsm", "GSM", "GSM video modes"),
        ("igr", "In-Game-Reset", "In-game reset"),
        ("cheats", "Cheats", "Cheats"),
        ("pademu", "PADEMU", "PADEMU"),
        ("retroachievements", "RetroAchievements", "RetroAchievements"),
        ("apps", "Apps", "Apps"),
    ],
    "Interface and customization": [
        ("settings", "Settings", "Settings reference"),
        ("controls", "Controls", "Controls"),
        ("coverflow", "Coverflow", "Coverflow"),
        ("favourites", "Favorites", "Favorites"),
        ("library", "Game-Library", "Game library: All Games, Recent, Hide and Delete"),
        ("themes", "Themes", "Theme engine"),
        ("languages", "Languages", "Languages"),
        ("unicode-titles", "Unicode-Game-Titles", "Japanese / Unicode game titles"),
    ],
    "Help and reference": [
        ("troubleshooting", "Troubleshooting", "Troubleshooting"),
        ("zso", "ZSO", "ZSO format"),
        ("ps3-bc", "PS3-Compatibility", "Backward-compatible PS3"),
        ("credits", "Credits", "Credits and sources"),
        ("fork-gaps", "Fork-Feature-Gaps", "Features in other forks"),
        ("ps2sdk-notes", "PS2SDK-Notes", "Notes for ps2sdk"),
        ("index", "Project-Overview", "Project overview"),
    ],
}
DOCS = {
    "docs/GAME-FORMATS.md": ("Game-Formats-Reference", "Game image formats reference"),
    "docs/README.md": ("Documentation-Index", "Documentation index"),
    "docs/TEST-BUILDS.md": ("Test-Builds", "Test builds and diagnostics"),
    "docs/LAUNCH-DIAGNOSTICS.md": ("Launch-Diagnostics", "Launch diagnostics by package, core and transport"),
    "docs/FORK-COLLABORATION.md": ("Fork-Collaboration", "Learning across PS2 loader projects"),
    "docs/VMC.md": ("VMC-Recovery", "VMC creation and recovery"),
    "docs/EXFAT.md": ("EXFAT-Reference", "exFAT and APA-Jail reference"),
    "docs/PC-CARD-CF.md": ("PC-CARD-CF-Reference", "PC CARD CF implementation reference"),
    "docs/DESR-DVR.md": ("DESR-DVR-Reference", "DESR DVR implementation reference"),
    "docs/GAME-LIBRARY.md": ("Game-Library-Reference", "Game library reference"),
    "docs/PARENTAL-LOCK.md": ("Parental-Lock", "Per-game parental lock"),
    "docs/SIO2MAN-COMPATIBILITY.md": ("SIO2MAN-Compatibility", "SIO2MAN hook compatibility"),
    "docs/DEFAULTS.md": ("Fresh-Start-Defaults", "Fresh-start defaults and saved settings"),
    "README.md": ("Repository-Guide", "Complete repository guide"),
    "ROLLING_RELEASE.md": ("Release-Reference", "Rolling release reference"),
    "docs/APA-SAFETY.md": ("APA-Safety", "APA hard disk safety and code 402"),
    "docs/AUTOLAUNCH-GLOBAL-SETTINGS.md": ("Autolaunch", "Autolaunch and global settings"),
    "docs/CONTROLS.md": ("Controls-Reference", "Controls reference"),
    "docs/GSM.md": ("GSM-Reference", "GSM reference"),
    "docs/HTTP.md": ("HTTP-Reference", "HTTP reference"),
    "docs/IGR.md": ("IGR-Reference", "In-game reset reference"),
    "docs/INTERFACE.md": ("Interface-Behaviors", "Folders, parental lock and audio"),
    "docs/LANGUAGES.md": ("Language-Maintenance", "Language maintenance"),
    "docs/MX4SIO.md": ("MX4SIO-Reference", "MX4SIO launch reference"),
    "docs/NEUTRINO.md": ("Neutrino-Reference", "Neutrino reference"),
    "docs/PADEMU.md": ("PADEMU-Reference", "PADEMU reference"),
    "docs/RETROACHIEVEMENTS.md": ("RetroAchievements-Reference", "RetroAchievements reference"),
    "docs/THEME_ENGINE.md": ("Theme-Engine-Reference", "Theme engine: full authoring reference"),
    "docs/UNICODE-GAME-TITLES.md": ("Unicode-Titles-Reference", "Unicode game titles reference"),
    "docs/VCD.md": ("PS1-Reference", "PS1/VCD reference"),
    "pc/http/README.md": ("HTTP-Conformance", "HTTP server conformance tools"),
    "pc/apa-recovery/README.md": ("APA-Recovery-Tool", "APA recovery tool"),
}
PAIRS = {
    "Game-Formats": "docs/GAME-FORMATS.md",
    "Virtual-Memory-Cards": "docs/VMC.md", "PC-CARD-CompactFlash": "docs/PC-CARD-CF.md",
    "PSX-DVR": "docs/DESR-DVR.md",
    "Controls": "docs/CONTROLS.md", "GSM": "docs/GSM.md", "HTTP": "docs/HTTP.md",
    "In-Game-Reset": "docs/IGR.md", "Languages": "docs/LANGUAGES.md",
    "USB-MX4SIO-and-iLink": "docs/MX4SIO.md", "Neutrino": "docs/NEUTRINO.md",
    "PADEMU": "docs/PADEMU.md", "RetroAchievements": "docs/RETROACHIEVEMENTS.md",
    "Themes": "docs/THEME_ENGINE.md", "PS1-Games": "docs/VCD.md",
    "Settings": "docs/INTERFACE.md", "Releases": "ROLLING_RELEASE.md",
    "Project-Overview": "README.md", "Internal-HDD": "docs/APA-SAFETY.md",
    "Unicode-Game-Titles": "docs/UNICODE-GAME-TITLES.md",
    "Game-Library": "docs/GAME-LIBRARY.md",
}
SITE_MAP = {name + ".html": page for group in SITE_GROUPS.values() for name, page, _ in group}

# Retain existing wiki URLs and source heading anchors without a second full copy
# of the same subject. The current guide is in the wiki; source-only details stay
# available through a pinned source index. Unique engineering guides remain full pages.
REFERENCE_GUIDES = {
    DOCS[origin][0]: guide for guide, origin in PAIRS.items()
    if origin not in {"docs/INTERFACE.md", "docs/APA-SAFETY.md", "docs/LANGUAGES.md",
                      "docs/VMC.md", "docs/PC-CARD-CF.md", "docs/DESR-DVR.md"}
}
REFERENCE_GUIDES["Repository-Guide"] = "Documentation-Index"
REFERENCE_GUIDES["EXFAT-Reference"] = "Internal-HDD"


def reference_index(origin, page, title, source, sha):
    original = (source / origin).read_text(encoding="utf-8")
    text = (f"# {title}\n\nRead {link('the current wiki guide', REFERENCE_GUIDES[page])} "
            f"or [the complete source reference]({source_url('source', origin, sha)}).\n\n"
            "This page keeps older wiki links working. Detailed source sections are indexed below "
            "instead of duplicating a guide that can drift from its website version.\n\n")
    # Every former source anchor remains a destination, including explicit HTML anchors.
    for anchor in sorted(anchors_and_links(original)[0]):
        text += (f'<a name="{anchor}"></a>\n\n'
                 f"- [{anchor.replace('-', ' ')}]({source_url('source', origin, sha)}#{anchor})\n\n")
    return text



def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True, encoding="utf-8").strip()


def source_url(kind, path, sha):
    return f"{REPO}/blob/{sha}/{quote(path, safe='/')}"


def rewrite_url(url, kind, origin, sha, image=False):
    parsed = urlsplit(url)
    # Keep external resources and pinned repository links intact. Only links to
    # this project's website and branch-local documentation are internalized.
    if url.startswith(SITE):
        parsed = urlsplit(url[len(SITE):])
        kind, origin = "site", "index.html"
    elif parsed.scheme or parsed.netloc:
        for branch in ("rebuild/main",):
            prefix = REPO + "/blob/" + branch + "/"
            if url.startswith(prefix):
                return rewrite_url(url[len(prefix):], "source", "README.md", sha, image)
        return url
    if not parsed.path:
        return url
    path = posixpath.normpath(posixpath.join(posixpath.dirname(origin), unquote(parsed.path)))
    fragment = "#" + parsed.fragment if parsed.fragment else ""
    query = "?" + parsed.query if parsed.query else ""
    if kind == "site":
        if path in SITE_MAP and not image:
            return WIKI + SITE_MAP[path] + query + fragment
        return urljoin(SITE + origin, url)
    if path in DOCS and not image:
        return WIKI + DOCS[path][0] + query + fragment
    if image:
        return f"https://raw.githubusercontent.com/NathanNeurotic/Open-PS2-Loader/{sha}/{quote(path, safe='/')}" + query + fragment
    return source_url(kind, path, sha) + query + fragment


class Converter(MarkdownConverter):
    def convert_code(self, el, text, parent_tags):
        result = super().convert_code(el, text, parent_tags)
        if {"td", "th"} & parent_tags:
            result = result.replace("|", "\\|")
        return result

    def convert_a(self, el, text, parent_tags):
        if el.get("name") and not el.get("href"):
            if {"td", "th"} & parent_tags:
                return '<a name="' + el["name"] + '"></a>'
            return '\n\n<a name="' + el["name"] + '"></a>\n\n'
        if "tile" in el.get("class", []):
            label = self.escape(el.get_text(" ", strip=True), parent_tags)
            return "\n\n- [" + label + "](" + el["href"] + ")\n\n"
        return super().convert_a(el, text, parent_tags)

    # A Markdown table cell is one line, so a fenced code block cannot sit in it. Keep a code
    # example inside a cell as inline HTML instead: its line breaks become &#10; and a pipe
    # becomes &#124;, so the cell stays on one line and the table keeps its columns. Text
    # between inline tags is still parsed as Markdown, so the other delimiters are encoded too.
    def convert_pre(self, el, text, parent_tags):
        if {"td", "th"} & parent_tags:
            code = html.escape(el.get_text(), quote=False)
            for char in "\\`*_[]()~|!":
                code = code.replace(char, "&#%d;" % ord(char))
            return "<pre>" + code.replace("\n", "&#10;") + "</pre>"
        return super().convert_pre(el, text, parent_tags)

    def convert_summary(self, el, text, parent_tags):
        return "\n\n**" + text.strip() + "**\n\n"

    def convert_div(self, el, text, parent_tags):
        if "h" in el.get("class", []):
            return "\n\n**" + text.strip() + "**\n\n"
        return "\n\n" + text.strip() + "\n\n"

    # Definition lists (the credits page): GitHub's wiki Markdown has no ": definition" syntax, so
    # markdownify's default leaves a stray colon in the visible text. A bold term line and a plain
    # paragraph read the same and keep the text identical to the page.
    def convert_dt(self, el, text, parent_tags):
        return "\n\n**" + text.strip() + "**\n\n"

    def convert_dd(self, el, text, parent_tags):
        return "\n\n" + text.strip() + "\n\n"


def convert_site(path, sha):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    main = soup.select_one("main.content")
    if main is None:
        raise ValueError(f"No main.content in {path}")
    for tag in main.select("script, style, button, input, .toc, footer, .fork-gap-controls, .fork-gap-count, .directory-alpha"):
        tag.decompose()
    # Retain every explicit website anchor, including anchors on containers.
    for tag in list(main.select("[id]")):
        anchor = soup.new_tag("a", attrs={"name": tag["id"]})
        # An anchor between table rows destroys Markdown table recognition.
        # Keep row/cell bookmarks inside a cell, where inline HTML is supported.
        if tag.name == "tr" and tag.find(["td", "th"]) is not None:
            tag.find(["td", "th"]).insert(0, anchor)
        elif tag.name in ("td", "th"):
            tag.insert(0, anchor)
        else:
            tag.insert_before(anchor)
        del tag["id"]
    for tag in main.select("a[href]"):
        tag["href"] = rewrite_url(tag["href"], "site", path.name, sha)
    for tag in main.select("img[src]"):
        tag["src"] = rewrite_url(tag["src"], "site", path.name, sha, True)
    output = Converter(heading_style="ATX", bullets="-", escape_misc=True, newline_style="backslash",
                       code_language="", wrap=False).convert(str(main)).strip() + "\n"
    rendered = BeautifulSoup(MD.render(output), "html.parser")
    normalize = lambda value: re.sub(r"\s+", "", value)
    if normalize(main.get_text()) != normalize(rendered.get_text()):
        before, after = normalize(main.get_text()), normalize(rendered.get_text())
        changes = [(kind, before[a:b][:100], after[max(0, c-50):d+50][:150])
                   for kind, a, b, c, d in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
                   if kind != "equal"]
        raise ValueError(f"Visible text changed during conversion: {path.name}: {changes[:5]}")
    for tag in ("table", "tr", "td", "th", "pre"):
        if len(main.select(tag)) != len(rendered.select(tag)):
            raise ValueError(f"{tag} count changed during conversion: {path.name}")
    if [el.get_text().strip() for el in main.select("pre")] != [el.get_text().strip() for el in rendered.select("pre")]:
        raise ValueError(f"Code example changed during conversion: {path.name}")
    return output


LINK = re.compile(r"(!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\()([^\s<>]+(?:\([^\n()]*\)[^\s<>]*)?)(\s+\"[^\"\n]*\")?(\))")


def convert_doc(path, origin, sha):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    protected = set()
    for token in MD.parse(text):
        if token.type in ("fence", "code_block") and token.map:
            protected.update(range(*token.map))
    for n, line in enumerate(lines):
        if n in protected:
            continue
        # A code span can be a link label; protect a match only when the link
        # itself starts inside code, not when its label contains code.
        spans = [m.span() for m in re.finditer(r"(`+)(.+?)\1", line)]
        def replace_link(match):
            if any(start <= match.start() < end for start, end in spans):
                return match[0]
            return match[1] + rewrite_url(match[2], "source", origin, sha, match[1].startswith("!")) + (match[3] or "") + match[4]
        line = LINK.sub(replace_link, line)
        line = re.sub(r'(?P<attr>href|src)="(?P<url>[^"\n]+)"',
                      lambda m: m["attr"] + '="' + rewrite_url(m["url"], "source", origin, sha, m["attr"] == "src") + '"', line)
        line = re.sub(r"^(\s*\[[^\]]+\]:\s*)(\S+)",
                      lambda m: m[1] + rewrite_url(m[2], "source", origin, sha), line)
        if not line.strip():
            line = "\n"
        elif line.endswith("  \n"):
            line = line.rstrip() + "\\\n"
        else:
            line = line.rstrip() + "\n"
        lines[n] = line
    output = "".join(lines).strip() + "\n"
    before_html = BeautifulSoup(MD.render(text), "html.parser")
    after_html = BeautifulSoup(MD.render(output), "html.parser")
    if before_html.get_text() != after_html.get_text():
        raise ValueError(f"Visible text changed in repository document: {origin}")
    if [el.get_text() for el in before_html.select("code")] != [el.get_text() for el in after_html.select("code")]:
        raise ValueError(f"Code example changed in repository document: {origin}")
    return output


def link(label, page):
    return f"[{label}]({WIKI}{page})"


def home():
    text = f"""> [!IMPORTANT]
> **This is the legacy version of RiptOPL.** We have moved over to ps2build's **C++ Edition** at
> **[NathanNeurotic/RiptOPL](https://github.com/NathanNeurotic/RiptOPL)**, where new development now happens.

![RiptOPL]({SITE}assets/riptopl.png)

# RiptOPL Wiki

Setup guides and complete references for RiptOPL, the Open PS2 Loader fork.
Start with your storage device, choose the right game core, and keep the detailed
settings and troubleshooting guides close by.

**New installation:** {link('Getting started', 'Getting-Started')} → {link('Installation and first boot', 'Installation')} → {link('Controls', 'Controls')}.

**Already running:** {link('Settings', 'Settings')} · {link('Per-game settings', 'Per-Game-Settings')} · {link('Troubleshooting', 'Troubleshooting')} · {link('Releases', 'Releases')}.

The [documentation website]({SITE}), [repository documentation]({REPO}/tree/rebuild/main/docs),
and this wiki offer complementary ways to read the project guides. The wiki includes
the website's task guides and unique repository references. Overlapping source references are linked
as section indexes, so each subject has one main wiki reading page. Language support
and translation maintenance are covered under {link('Languages', 'Languages')}.

## Choose a starting point

| I want to… | Start here |
| --- | --- |
| Run my first PS2 game | {link('Getting started', 'Getting-Started')} |
| Use ISO, ZSO, CHD or CSO game images | {link('Game image formats', 'Game-Formats')} · {link('ZSO', 'ZSO')} |
| Use USB, MX4SIO or iLink storage | {link('USB, MX4SIO and iLink', 'USB-MX4SIO-and-iLink')} |
| Use an SD2PSX or compatible MMCE device | {link('MMCE', 'MMCE')} |
| Test a supplied preview or diagnose a failed save card | {link('Test builds', 'Test-Builds')} · {link('VMC recovery', 'VMC-Recovery')} |
| Diagnose by package, core and transport | {link('Launch diagnostics', 'Launch-Diagnostics')} |
| Compare and share improvements across projects | {link('Fork collaboration', 'Fork-Collaboration')} |
| Use experimental special hardware | {link('DESR DVR', 'PSX-DVR')} · {link('PC CARD CF', 'PC-CARD-CompactFlash')} |
| Use an internal HDD | {link('APA and exFAT HDD', 'Internal-HDD')} · {link('Disk safety and code 402', 'APA-Safety')} |
| Share games from a PC or NAS | {link('SMB', 'SMB')} · {link('UDPFS / UDPBD', 'Network-Boot')} · {link('HTTP', 'HTTP')} |
| Choose between OPL and Neutrino | {link('Neutrino', 'Neutrino')} · {link('Per-game settings', 'Per-Game-Settings')} |
| Play PS1 games | {link('POPStarter and Ember', 'PS1-Games')} · {link('Full PS1 reference', 'PS1-Reference')} |
| Adjust startup and menu behavior | {link('Autolaunch', 'Autolaunch')} · {link('Settings', 'Settings')} · {link('Interface behaviors', 'Interface-Behaviors')} |
| Customize the interface | {link('Coverflow', 'Coverflow')} · {link('Themes', 'Themes')} · {link('Theme authoring reference', 'Theme-Engine-Reference')} |
| Build or contribute | {link('Repository guide', 'Repository-Guide')} · {link('Language maintenance', 'Language-Maintenance')} · {link('Credits', 'Credits')} |

## Compatibility and validation

Support depends on the **device, game core, and build**. Read the status and limitations
on each feature page before treating a setting as available for every launch path.
The HTTP and RetroAchievements guides explicitly distinguish implementation and host
tests from PS2 hardware validation. This wiki preserves those qualifications; publishing
a guide does not establish hardware compatibility.

## Browse all guides

"""
    for group, pages in SITE_GROUPS.items():
        text += f"### {group}\n\n"
        text += "\n".join("- " + link(title, page) for _, page, title in pages) + "\n\n"
    text += "### Detailed repository references\n\n"
    text += "\n".join("- " + link(title, page) for page, title in DOCS.values() if page not in REFERENCE_GUIDES) + "\n\n"
    text += f"For documentation corrections and rebuilding this wiki, see {link('Wiki maintenance', 'Wiki-Maintenance')}.\n"
    return text


def sidebar():
    text = "**" + link("RiptOPL Wiki", "Home") + "**\n\n"
    for group, pages in SITE_GROUPS.items():
        text += f"**{group}**\n\n"
        text += "\n".join("- " + link(title, page) for _, page, title in pages) + "\n\n"
    text += "**Detailed references**\n\n"
    text += "\n".join("- " + link(title, page) for page, title in DOCS.values() if page not in REFERENCE_GUIDES) + "\n\n"
    text += link("Wiki maintenance", "Wiki-Maintenance") + "\n"
    return text


def maintenance(source_sha, site_sha):
    return f"""# Wiki maintenance

The wiki is a separate Git repository. Its builder reads existing documentation from
`rebuild/main` and `gh-pages` and writes only this wiki checkout. It does not push,
edit the source checkouts, run `docs-sync.yml`, change translations, or deploy the website.

## Where to make a correction

- **Task guides:** edit the corresponding `gh-pages` HTML page through the project's normal review process.
- **Detailed references:** edit the corresponding Markdown document on `rebuild/main`.
- **Generated external-tools sections:** edit the templates in `.github/workflows/docs-sync.yml`; direct edits to their generated source output will be overwritten by the existing workflow.
- **Wiki homepage, navigation, source mappings and conversion:** edit `.github/scripts/wiki_sync.py` on `rebuild/main` through a normal PR.

Every imported page or source index has an exact source-commit link at the bottom. Correct its source,
then regenerate the wiki. Direct edits to imported wiki pages are overwritten on the
next rebuild. Integration plans and the internal documentation gap checklist are not
published as user guides; links to those files remain links to the source repository.

## Rebuild

Use Python 3.10 or newer, Git, and three separate sibling directories. The source and
site checkouts must be clean. Existing working copies are also accepted by the builder.

```sh
git clone --depth 1 --single-branch --branch rebuild/main https://github.com/NathanNeurotic/Open-PS2-Loader.git source
git clone --depth 1 --single-branch --branch gh-pages https://github.com/NathanNeurotic/Open-PS2-Loader.git site
git clone https://github.com/NathanNeurotic/Open-PS2-Loader.wiki.git wiki
git -C source fetch origin {source_sha}
git -C source checkout --detach FETCH_HEAD
git -C site fetch origin {site_sha}
git -C site checkout --detach FETCH_HEAD
cd wiki
python -m venv .venv
```

Activate the environment with `.venv\\Scripts\\activate` on Windows or
`source .venv/bin/activate` on Linux/macOS, then run:

```sh
python -m pip install -r ../source/.github/requirements-docs.txt
python ../source/.github/scripts/wiki_sync.py --source ../source --site ../site --wiki .
git diff --check
git diff --stat
git diff
```

The builder fails on missing source pages, dirty source checkouts, duplicate page
names, unresolved wiki links or section anchors, and unexpected output files. It checks
that conversion preserves text, tables and code examples. Run it again with the same
inputs: generated file hashes must be identical. Source checkouts are checked again
at the end to ensure their tracked and untracked state did not change.

Review the content before committing and pushing the **wiki** repository. Use a normal
push that preserves history; concurrent edits must be reconciled. There is no automatic
publication job or additional credential configured by this setup.

## Coverage and source revisions

- Source: [{source_sha[:12]}]({REPO}/commit/{source_sha})
- Website: [{site_sha[:12]}]({REPO}/commit/{site_sha})
- All website HTML pages are included, with explicit source-to-wiki mappings.
- Current user/developer references are included. Overlapping references keep their old URLs and anchors as short indexes pointing to the current guide and pinned source sections.
- `_tools/manifest.json` records source revisions, per-page origins, output hashes and validation counts.

Website search, styling and JavaScript controls belong to the website. In the wiki,
tables are static and expandable explanations are shown in full. Content, code examples,
and section destinations are preserved. Overlapping guides use one wiki reading page plus a short source-section index.
Unique source references remain complete. Legacy page names and heading anchors are preserved.
"""


def anchors_and_links(text):
    anchors, links, seen = set(), [], {}
    tokens = MD.parse(text)
    for i, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[i + 1]
            title = "".join(child.content for child in (inline.children or []) if child.type in ("text", "code_inline"))
            slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchors.add(slug + (f"-{count}" if count else ""))
        for child in token.children or []:
            if child.type == "link_open":
                links.append(child.attrGet("href"))
            elif child.type == "image":
                links.append(child.attrGet("src"))
            elif child.type == "html_inline":
                fragment = BeautifulSoup(child.content, "html.parser")
                anchors.update(tag.get("name") or tag.get("id") for tag in fragment.select("[name], [id]"))
                links.extend(tag["href"] for tag in fragment.select("a[href]"))
        if token.type == "html_block":
            fragment = BeautifulSoup(token.content, "html.parser")
            anchors.update(tag.get("name") or tag.get("id") for tag in fragment.select("[name], [id]"))
            links.extend(tag["href"] for tag in fragment.select("a[href]"))
            links.extend(tag["src"] for tag in fragment.select("img[src]"))
    return anchors, links


def validate(pages):
    parsed = {page: anchors_and_links(text) for page, text in pages.items()}
    errors, checked = [], 0
    for page, (_, links) in parsed.items():
        for url in links:
            parts = urlsplit(url)
            if url.startswith(WIKI):
                target = unquote(parts.path[len(urlsplit(WIKI).path):]) or "Home"
            elif not parts.scheme and not parts.netloc:
                target = unquote(parts.path) or page
            else:
                continue
            checked += 1
            if target not in parsed:
                errors.append(f"{page}: missing wiki page {url}")
            elif parts.fragment and unquote(parts.fragment) not in parsed[target][0]:
                errors.append(f"{page}: missing anchor {url}")
    if errors:
        raise ValueError("\n".join(errors))
    return checked


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--wiki", required=True, type=Path)
    args = parser.parse_args()
    source, site = args.source.resolve(), args.site.resolve()
    ROOT = args.wiki.resolve()
    if not (ROOT / ".git").exists():
        raise ValueError("--wiki must be an existing wiki Git checkout")
    for path in (source, site):
        if path == ROOT or path in ROOT.parents or ROOT in path.parents:
            raise ValueError("Source/site must be outside the wiki checkout")
        if git(path, "status", "--porcelain"):
            raise ValueError(f"Source checkout is dirty: {path}")
    source_sha, site_sha = git(source, "rev-parse", "HEAD"), git(site, "rev-parse", "HEAD")
    discovered = {p.name for p in site.glob("*.html")}
    if discovered != set(SITE_MAP):
        raise ValueError(f"Website mapping differs: {discovered.symmetric_difference(SITE_MAP)}")
    pages, origins = {}, {}

    def add(page, text, kind, origin, sha):
        if page in pages:
            raise ValueError(f"Duplicate page: {page}")
        if origin:
            text += f"\n---\n\nSource: [{origin} @ {sha[:12]}]({source_url(kind, origin, sha)}).\n"
            if kind == "site":
                text += f"[Read on the documentation website]({SITE}{origin}).\n"
        pages[page] = text
        origins[page] = {"kind": kind, "path": origin, "commit": sha}

    for origin, page in SITE_MAP.items():
        text = convert_site(site / origin, source_sha)
        if page in PAIRS:
            detail, title = DOCS[PAIRS[page]]
            text += "\n**Detailed reference:** " + link(title, detail) + ".\n"
        if page == "Settings":
            text += "\n**Startup behavior:** " + link("Autolaunch and global settings", "Autolaunch") + ".\n"
        add(page, text, "site", origin, site_sha)
    for origin, (page, _) in DOCS.items():
        text = (reference_index(origin, page, DOCS[origin][1], source, source_sha)
                if page in REFERENCE_GUIDES else convert_doc(source / origin, origin, source_sha))
        partners = [site_page for site_page, doc in PAIRS.items() if doc == origin]
        if partners:
            text += "\n**Related guide:** " + " · ".join(link(p.replace("-", " "), p) for p in partners) + ".\n"
        add(page, text, "source", origin, source_sha)
    add("Home", home(), "wiki", None, None)
    add("_Sidebar", sidebar(), "wiki", None, None)
    add("_Footer", f"{link('Wiki home', 'Home')} · [Documentation website]({SITE}) · [Repository]({REPO}) · {link('Wiki maintenance', 'Wiki-Maintenance')}\n", "wiki", None, None)
    add("Wiki-Maintenance", maintenance(source_sha, site_sha), "wiki", None, None)
    checked = validate(pages)
    for path, expected in ((source, source_sha), (site, site_sha)):
        if git(path, "rev-parse", "HEAD") != expected or git(path, "status", "--porcelain"):
            raise ValueError(f"Source checkout changed during generation: {path}")
    unexpected = {p.stem for p in ROOT.glob("*.md")} - set(pages)
    if unexpected:
        raise ValueError(f"Unmanaged pages require review before generation: {unexpected}")
    for page, text in pages.items():
        (ROOT / (page + ".md")).write_text(text, encoding="utf-8", newline="\n")
    (ROOT / "_tools" / "build.py").write_text(COMPAT_BUILDER, encoding="utf-8", newline="\n")
    manifest = {
        "source_commit": source_sha, "site_commit": site_sha,
        "website_pages": len(SITE_MAP), "repository_documents": len(DOCS),
        "wiki_pages": len(pages) - 2, "internal_links_checked": checked,
        "pages": {page: {**origins[page], "sha256": hashlib.sha256(text.encode()).hexdigest()} for page, text in sorted(pages.items())},
    }
    (ROOT / "_tools" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Built {len(pages) - 2} pages plus sidebar/footer; checked {checked} internal links and anchors.")


if __name__ == "__main__":
    main()
