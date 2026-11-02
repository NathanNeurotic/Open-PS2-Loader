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


def enum_rows(page, row):
    """The choices diaSetEnumIds gives `row` on this page: each one's string id, or its text when it has none."""
    call = re.search(r'diaSetEnumIds\(ui, ' + row + r', (\w+), (\w+)\);', page)
    if not call:
        return None
    names = re.search(r'static const char \*' + call.group(1) + r'\[\] = \{([^}]*)\};', page)
    ids = re.search(r'static const int ' + call.group(2) + r'\[\] = \{([^}]*)\};', page)
    if not names or not ids:
        return None
    names = [name.strip() for name in names.group(1).split(',')]
    ids = [ident.strip() for ident in ids.group(1).split(',')]
    if names[-1] != 'NULL' or len(ids) != len(names) - 1:
        return None
    return [name if ident == '-1' else ident for name, ident in zip(names, ids)]


def main():
    failures = []
    gui = GUI.read_text(encoding='utf-8')
    start = gui.index('guiShowMmceConfig(void)\n{')
    gui = gui[start:gui.index('\n}\n', start)]  # the MMCE page only
    for word in ('"NONE"', '"BOTH"', '"OFF"', '"ON"'):
        if word in gui:
            failures.append('%s still offers the fixed English choice %s' % (GUI.name, word))
    # Each choice in order, as the row shows it: its string id (looked up in every frame, as a language switch
    # frees translated strings) or its own text
    for row, names, want in (('CFG_MMCEIGRSLOT', 'deviceIGRSlots', ['_STR_OFF', '"0"', '"1"', '_STR_BOTH']),
                             ('CFG_MMCE_USE_ALARMS', 'deviceOnOff', ['_STR_OFF', '_STR_ON'])):
        got = enum_rows(gui, row)
        if CPP and got is None:  # until its settings page passes ids too
            if not all('%s[%d] = _l(%s);' % (names, i, word) in gui for i, word in enumerate(want) if word[0] == '_'):
                failures.append('%s does not set %s' % (GUI.name, names))
        elif got != want:
            failures.append('%s: %s shows %s, not %s' % (GUI.name, row, got, want))

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
