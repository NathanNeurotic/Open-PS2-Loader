# Maintaining documentation

Use `rebuild/main` as the code and release baseline. `master` is an older lineage.
Documentation changes do not establish a console hardware result: retain the source,
host-test and hardware distinctions on experimental feature pages.

## Ownership

| Surface | Edit here |
| --- | --- |
| Repository overview | `README.md`; link to task guides instead of repeating them |
| Detailed source references | `docs/`; start at [the index](README.md) |
| Website task guides and navigation | HTML on `gh-pages` |
| External-tools catalogue in README and website Home | Templates in `.github/workflows/docs-sync.yml`; hand edits to generated catalogues are overwritten |
| Website RetroAchievements body | `docs/RETROACHIEVEMENTS.md`, rendered by `site_sync.py` |
| Website ps2sdk notes and game library bodies | `docs/PS2SDK-NOTES.md` and `docs/GAME-LIBRARY.md`, rendered by `site_sync.py --md-page` |
| Website search | Page content, then regenerate `data/search-index.json`; curated entry titles/categories are preserved |
| Wiki maps, homepage, aliases and conversion | `.github/scripts/wiki_sync.py`; generated pages are published to the separate wiki repository |
| Language install and translation coverage | `docs/LANGUAGES.md`, `tools/audit_translations.py`; copy the user instructions to `gh-pages/languages.html` and regenerate the wiki |

Keep existing URLs and section anchors when consolidating material. A short forwarding section
is preferable to silently breaking a bookmark. Preserve attribution and verbatim third-party
notices; their original archive links are not necessarily paths in this repository.

## Local checks

Use separate source, Pages and wiki checkouts. The examples assume `source/`, `site/` and
`wiki/` are siblings. In the source checkout, create a Python environment and install:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r .github/requirements-docs.txt
python .github/scripts/site_sync.py --site ../site --ra-md docs/RETROACHIEVEMENTS.md \
    --md-page docs/PS2SDK-NOTES.md=ps2sdk-notes.html --md-page docs/GAME-LIBRARY.md=library.html
python .github/scripts/site_sync.py --site ../site --ra-md docs/RETROACHIEVEMENTS.md \
    --md-page docs/PS2SDK-NOTES.md=ps2sdk-notes.html --md-page docs/GAME-LIBRARY.md=library.html --check
python .github/scripts/check_docs.py --site ../site --report /tmp/docs-links.json
python .github/scripts/test_site_sync.py
python .github/scripts/test_wiki_sync.py
python tools/audit_translations.py --strict
git diff --check
git -C ../site diff --check
```

The link audit reads every tracked Markdown file and every site HTML page. It checks local
targets, section anchors and duplicate HTML IDs, and inventories external URLs for a separate
network check. Four archive-relative links in the verbatim POPS upstream README are recorded
as preserved provenance, rather than silently excluded. New broken links still fail.

Inspect changed pages in a browser, including navigation, narrow layouts, tables, search and
download links. An HTTP 403 or timeout is inconclusive; an Actions artifact may return 404
when viewed without sign-in. Check run/artifact metadata before calling it expired.

## Wiki publication

GitHub wikis have a separate Git history and cannot receive normal repository PRs. Review the
builder changes in the source PR and the guide changes in the Pages PR. Commit both source
checkouts before generation so every generated link can identify its exact revision:

```sh
python .github/scripts/wiki_sync.py --source . --site ../site --wiki ../wiki
git -C ../wiki diff --check
git -C ../wiki diff --stat
```

Run generation twice with unchanged inputs and confirm no second diff. The builder validates
internal wiki links/anchors and preserves text, tables and code examples when importing guides.
Overlapping reference pages become small source-section indexes, preserving old wiki URLs and
anchors; unique references remain full pages. Review and commit the wiki, then push normally.
Reconcile concurrent wiki edits before retrying a rejected push. No automatic wiki publication
or new credential is configured by these tools.

## Language-guide publication order

Maintain the technical pipeline and audit commands in `docs/LANGUAGES.md`.
Update the public installation steps in the `gh-pages` branch's `languages.html`
before regenerating the wiki: `wiki_sync.py` imports the website Languages
page into the wiki's `Languages` entry and preserves the separate
`Language-Maintenance` technical page from the repository. A source-only
change does **not** update the published wiki. Review and push the wiki
checkout separately; the source connector and documentation workflow cannot
write GitHub wiki pages through the repository contents API.

The `docs-sync.yml` job regenerates the website search index from the
published HTML, but it does not translate strings or update `languages.html`
from `docs/LANGUAGES.md`. Run the coverage audit after new UI labels are
appended and before claiming any language is fully translated.
