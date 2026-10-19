"""Characterize released Grimdoomer versus current standard-build IGR sampling.

This is an audit probe, not console acceptance. Compile unchanged production
functions against the existing host kernel fixture and inject alarm allocation
failure. --require-parity fails when current sampling loses cases the archive
handles; it is deliberately not an ordinary green CI acceptance test.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REF = 'b6717a842e02a8010abaf23a9116081ec43d8512'
SHA256 = 'cf486e9248a3aab456aa5d73497dff02eb449e534c179d9bfd7f2d1c0465800c'
URL = f'https://raw.githubusercontent.com/grimdoomer/Open-PS2-Loader/{REF}/ee_core/src/padhook.c'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--archived-source', type=Path, help='Local padhook.c from the pinned released tag')
parser.add_argument('--require-parity', action='store_true')
args = parser.parse_args()
data = args.archived_source.read_bytes() if args.archived_source else urllib.request.urlopen(URL, timeout=30).read()
if hashlib.sha256(data).hexdigest() != SHA256:
    raise SystemExit('Archived source hash mismatch; compare the released exFAT tag, not master')
archived = data.decode()
current = (ROOT / 'ee_core/src/padhook.c').read_text()

# Reuse the same hardware/kernel stubs without importing the regression's test
# runner. Only extract its literal fixture preamble, before any test cases.
tree = ast.parse((ROOT / '.github/scripts/test_igr_polling.py').read_text())
fixture = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'HARNESS' for t in node.targets))
fixture = fixture.split('@CODE@', 1)[0]


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


cases = r'''
static void auditTick(void)
{
#ifdef ARCHIVED
    int previous = intrEnabled;
    intrEnabled = 0;
    IGR_Intc_Handler(kINTC_VBLANK_END);
    intrEnabled = previous;
#else
    tickAlarm();
#endif
}

int main(int argc, char **argv)
{
    int scenario = argc > 1 ? atoi(argv[1]) : 0;
    Pad_Data.libpad = IGR_LIBPAD;
    Pad_Data.libversion = 0x0160;
    padBuf[112] = IGR_PAD_STABLE_V1;
    if (scenario == 1)
        alarmFails = 1;
    Install_IGR();
    Set_libpad_Params(padBuf);
    if (scenario == 2) {
        alarmFails = 1;
        auditTick(); /* idle sample; the next alarm allocation fails */
    }
    padBuf[3] = IGR_COMBO_R1_L1_R2_L2;
    padBuf[2] = IGR_COMBO_START_SELECT;
    for (int i = 0; i < 60 && !Pad_Data.combo_type; i++)
        auditTick();
    printf("%d %d %d\n", Pad_Data.combo_type == IGR_COMBO_START_SELECT, nAlarm, IGR_Poll_Recovery);
    return 0;
}
'''
definitions = {
    'archived': (archived, ('static int IGR_Intc_Handler(', 'static void Set_libpad_Params(', 'void Install_IGR(')),
    'current': (current, ('static void Set_libpad_Params(', 'static void IGR_CheckInputs(',
                          'static void IGR_Poll_Alarm(', 'void Install_IGR(')),
}
results = {}
with tempfile.TemporaryDirectory(prefix='igr-archive-') as directory:
    temp = Path(directory)
    for name, (source, signatures) in definitions.items():
        code = ''.join(function(source, signature) for signature in signatures)
        # The only MIPS-only instruction in these functions has no host meaning.
        code = code.replace('asm volatile("sync.l\\n");', ';')
        program = '#include <stdlib.h>\n' + ('#define ARCHIVED\n' if name == 'archived' else '') + fixture + code + cases
        c, exe = temp / f'{name}.c', temp / name
        c.write_text(program)
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-variable', str(c), '-o', str(exe)], check=True)
        results[name] = []
        for scenario in range(3):
            run = subprocess.run([str(exe), str(scenario)], check=True, capture_output=True, text=True, timeout=5)
            values = list(map(int, run.stdout.split()))
            assert len(values) == 3, run.stdout
            results[name].append(values)

print('Scenario                       Archived detects   Current detects   Current alarm calls')
for index, label in enumerate(('Normal sampling', 'Initial alarm unavailable', 'Alarm rearm fails')):
    old, new = results['archived'][index], results['current'][index]
    print(f'{label:30} {str(bool(old[0])):18} {str(bool(new[0])):17} {new[1]}')
assert all(row[0] for row in results['archived']), 'The pinned archive must detect these cases'
assert results['current'][0][0], 'Current normal sampling must work'
differences = [i for i in range(3) if results['archived'][i][0] != results['current'][i][0]]
if differences:
    print('Observed sampling gap. These injected kernel failures do not attribute a console report.')
if args.require_parity and differences:
    raise SystemExit(1)
