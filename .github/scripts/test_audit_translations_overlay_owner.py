"""#1055: a fork-overlay string with bad printf tokens must fail `audit_translations.py --strict`
both on a fresh checkout (no lng_src/) and after `make languages` copied the overlay into lng_src/."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

with tempfile.TemporaryDirectory() as temp:
    tree = Path(temp)
    shutil.copytree(ROOT / 'tools', tree / 'tools')
    shutil.copytree(ROOT / 'lng_tmpl', tree / 'lng_tmpl')
    shutil.copytree(ROOT / 'lng_fork', tree / 'lng_fork')
    for extra in ('Makefile',):
        if (ROOT / extra).exists():
            shutil.copy(ROOT / extra, tree / extra)
    swedish = tree / 'lng_fork' / 'Swedish.yml'
    text = swedish.read_text(encoding='utf-8')
    bad = '  SETTINGS_SAVED: "Inställningar sparade %d"\n'
    lines = [l for l in text.splitlines(keepends=True) if not l.lstrip().startswith('SETTINGS_SAVED:')]
    swedish.write_text(''.join(lines).rstrip('\n') + '\n' + bad, encoding='utf-8')

    def audit():
        return subprocess.run([sys.executable, '-I', str(tree / 'tools/audit_translations.py'), '--strict'],
                              cwd=tree, capture_output=True, text=True)

    shutil.rmtree(tree / 'lng_src', ignore_errors=True)
    fresh = audit()
    assert fresh.returncode != 0 and 'Swedish/SETTINGS_SAVED (overlay)' in fresh.stdout + fresh.stderr, fresh.stdout + fresh.stderr

    (tree / 'lng_src').mkdir()
    shutil.copy(swedish, tree / 'lng_src' / 'Swedish.yml')  # what the overlay merge leaves behind
    merged = audit()
    assert merged.returncode != 0 and 'Swedish/SETTINGS_SAVED (overlay)' in merged.stdout + merged.stderr, merged.stdout + merged.stderr

print('audit_translations --strict rejects a bad overlay string before and after the merge')
