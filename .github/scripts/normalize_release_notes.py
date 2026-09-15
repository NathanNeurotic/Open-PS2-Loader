import pathlib, re, sys

# Final pass over a published release body (release-normalize.yml): the hero banner on top, the
# External Tools & Services list and the AI-disclosure banner at the foot. Everything between comes
# from rolling-release.yml and the two .github/rolling-release-notes-*.md files. This pass runs more
# than once per release (on `release: published` AND after every Rolling Release), so it must be
# idempotent: it strips what an earlier pass added before adding it back.

p = pathlib.Path(sys.argv[1])
body = p.read_text(encoding='utf-8')
root = pathlib.Path(__file__).resolve().parents[2]

banner = '''<p align="center">\n  <img width="400" height="92" alt="AI-Assisted-Software-Lovers-Only" src="https://github.com/user-attachments/assets/71335775-9fe3-4507-ac2c-caa851abb24c" />\n</p>'''
# The project banner, served from rebuild/main so one file in the repo drives the README, the
# docs site and every release page at once. It has to be an ABSOLUTE url: a release description
# is rendered outside any repository context, so a relative path resolves to nothing.
hero = '''<p align="center"><img alt="RiptOPL" src="https://raw.githubusercontent.com/NathanNeurotic/Open-PS2-Loader/rebuild/main/docs/assets/riptopl.png" /></p>'''
# Anchored to the START of the body and to the asset PATH, not a bare filename, so this only ever
# removes a hero this script itself put there. Deliberately NOT an exact-string match against `hero`:
# if the markup is ever edited, an exact match would stop recognising the previous hero and start
# stacking a second one on every pass.
hero_re = re.compile(r'\A\s*<p align="center">(?:(?!</p>).)*docs/assets/riptopl\.png(?:(?!</p>).)*</p>\s*', re.DOTALL)


def external_tools():
    """A compact copy of README's External Tools & Services, which docs-sync.yml owns: one line per
    tool with its link, author and first sentence, so the release never carries a stale second list."""
    try:
        readme = (root / 'README.md').read_text(encoding='utf-8')
    except OSError:
        return ''
    section = re.search(r'^## External Tools & Services\n(.*?)(?=^## |\Z)', readme, re.M | re.S)
    if section is None:
        return ''
    lines = []
    for item in re.findall(r'^- (.+)$', section.group(1), re.M):
        head, sep, desc = item.partition(' — ')
        if not sep:
            continue
        first = re.match(r'(.+?[.!?])(?:\s|$)', desc)
        lines.append('- %s — %s' % (head, (first.group(1) if first else desc).strip()))
    if not lines:
        return ''
    return '## External Tools & Services\n\n' + '\n'.join(lines)


# Strip anything an earlier pass (or an older notes format) appended, then the hero.
for marker in ('## Other downloads', '## Release downloads', '## External Tools & Services'):
    if marker in body:
        body = body.split(marker, 1)[0].rstrip()
body = re.sub(r'\nSHA256 \(also published as SHA256SUMS\.txt\):\n```.*?```\n', '\n', body, flags=re.DOTALL)
body = hero_re.sub('', body)
body = body.strip()

tools = external_tools()
parts = [hero, body] + ([tools] if tools else []) + [banner]
print('\n\n'.join(parts), end='')
