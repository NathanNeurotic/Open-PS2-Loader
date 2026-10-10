"""Compile generated language tables in both flavours and verify stable IDs."""
from pathlib import Path
import subprocess
import tempfile
import yaml

root = Path(__file__).resolve().parents[2]
base = yaml.safe_load((root / 'lng_tmpl/_base.yml').read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory() as temp:
    work = Path(temp)
    for option, name in [('--make_header', 'lang_autogen.h'), ('--make_source', 'language.c')]:
        subprocess.run(['python', str(root / 'tools/lang_compiler.py'), option,
                        '--base', str(root / 'lng_tmpl/_base.yml'), str(work / name)], check=True)
    checks = ['#include <assert.h>', '#include <string.h>', '#include "language.c"', 'int main(void) {']
    array = base['string_array_name']
    prefix = base['enum_label_prefix']
    for index, item in enumerate(base['gui_strings']):
        label = item['label']
        checks.append(f'assert({prefix}{label} == {index});')
        if label.startswith(('RA_', 'HINT_RA_', 'CAD_')):
            checks.extend(['#ifdef RETROACHIEVEMENTS',
                           f'assert({array}[{index}][0] != 0);', '#else',
                           f'assert({array}[{index}][0] == 0);', '#endif'])
    checks.append('return 0; }')
    (work / 'check.c').write_text('\n'.join(checks), encoding='utf-8')
    for ra in (False, True):
        exe = work / ('ra.exe' if ra else 'standard.exe')
        subprocess.run(['cc', *(['-DRETROACHIEVEMENTS'] if ra else []),
                        str(work / 'check.c'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        if not ra:
            binary = exe.read_bytes()
            assert b'Caduceus' not in binary and b'Xerabora' not in binary
print('PASS: RA-only language text excluded from standard binary; all string IDs preserved')
