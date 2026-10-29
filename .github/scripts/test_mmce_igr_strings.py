#!/usr/bin/env python3
"""The MMCE IGR slot and ON/OFF choices are translated (belomaxorka/YAOPL 999bb6d3).

They were fixed English text ("NONE", "BOTH", "OFF", "ON") that no language could change. Checks the
MMCE page takes them from the language table, that BOTH is in the base language with English
"Both" and every fork overlay translates it, and runs the real lang_compiler.py pipeline
(template, overlay, .lng) to see the overlay's word reach the compiled language file while a
language without one keeps the English.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CPP = (ROOT / 'src/ui/guisettings.cpp').exists()
GUI = ROOT / ('src/ui/guisettings.cpp' if CPP else 'src/gui.c')
BASE = ROOT / ('lng/tmpl/_base.yml' if CPP else 'lng_tmpl/_base.yml')
FORK = ROOT / ('lng/fork' if CPP else 'lng_fork')
COMPILER = ROOT / 'tools/lang_compiler.py'


def compile_lng(temp, overlay):
    """The .lng built from an untranslated upstream file, with the overlay when given."""
    upstream = temp / 'upstream.yml'
    run = [sys.executable, str(COMPILER), '--base', str(BASE)]
    subprocess.run(run[:2] + ['--make_template_yml'] + run[2:] + [str(upstream)], check=True, capture_output=True)
    if overlay:
        subprocess.run(run[:2] + ['--overlay_translation_yml'] + run[2:] + ['--translation', str(upstream),
                       '--overlay', str(overlay)], check=True, capture_output=True)
    out = temp / 'lang.lng'
    subprocess.run(run[:2] + ['--make_lng'] + run[2:] + ['--translation', str(upstream), str(out)], check=True,
                   capture_output=True)
    return out.read_bytes().decode('utf-8', 'replace')


def main():
    failures = []
    gui = GUI.read_text(encoding='utf-8')
    start = gui.index('guiShowMmceConfig(void)\n{')
    gui = gui[start:gui.index('\n}\n', start)]  # the MMCE page only
    for word in ('"NONE"', '"BOTH"', '"OFF"', '"ON"'):
        if word in gui:
            failures.append('%s still offers the fixed English choice %s' % (GUI.name, word))
    for line in ('deviceIGRSlots[0] = _l(_STR_OFF);', 'deviceIGRSlots[3] = _l(_STR_BOTH);',
                 'deviceOnOff[0] = _l(_STR_OFF);', 'deviceOnOff[1] = _l(_STR_ON);'):
        if line not in gui:
            failures.append('%s does not set %s' % (GUI.name, line))

    base = BASE.read_text(encoding='utf-8')
    if not re.search(r'^  label: BOTH\n  string: Both$', base, re.M):
        failures.append('%s has no BOTH: Both' % BASE.name)

    words = {}
    for path in sorted(FORK.glob('*.yml')):
        match = re.search(r'^  BOTH: (.+)$', path.read_text(encoding='utf-8'), re.M)
        word = match.group(1).strip() if match else ''
        if len(word) >= 2 and word[0] == word[-1] and word[0] in '\'"':
            word = word[1:-1]  # a quoted YAML scalar: the compiler emits it without the quotes
        if word in ('', 'Both'):
            failures.append('%s does not translate BOTH' % path.name)
        else:
            words[path.stem] = word

    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        english = compile_lng(temp, None)
        if 'Both' not in english.splitlines():
            failures.append('a language without an overlay does not fall back to "Both"')
        for lang in ('Russian', 'German', 'Japanese', 'Spanish'):
            if lang in words:
                lines = compile_lng(temp, FORK / (lang + '.yml')).splitlines()
                if words[lang] not in lines:
                    failures.append('lang_%s.lng does not carry BOTH = %s' % (lang, words[lang]))

    for line in failures:
        print('FAIL: ' + line)
    if failures:
        return 1
    print('MMCE IGR choices: translated; BOTH in the base and %d overlays, compiled through' % len(words))
    return 0


if __name__ == '__main__':
    sys.exit(main())
