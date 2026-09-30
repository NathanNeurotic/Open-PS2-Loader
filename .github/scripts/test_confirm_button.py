"""Settings and its prompts follow the user's Select Button (volventura, PSX-Place, 09-30).

The Settings redesign (#527) hard-wired Cross = confirm / Circle = back on the Settings pages, the index,
the Save prompt, the Reboot IOP prompt and the POPS settings read, so with Circle chosen as the confirm
button those screens ran the other way round from the rest of RiptOPL. They now ask guiConfirmKey /
guiCancelKey (and the matching icons).

Checked here:
- the four helpers, compiled and run, for both Select Button settings;
- none of those screens names KEY_CROSS / KEY_CIRCLE (in any form) or draws CROSS_ICON / CIRCLE_ICON directly.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def read(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function_text(source, where, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


gui_c = read('src/gui.c')
dia_c = read('src/dia.c')

HARNESS = r'''
#include <stdio.h>
enum { KEY_CROSS = 1, KEY_CIRCLE = 2 };
enum { CROSS_ICON = 10, CIRCLE_ICON = 11 };
static int gSelectButton;
@FUNCTIONS@
static int fails;
static void expect(const char *what, int got, int want)
{
    if (got != want) {
        printf("FAIL %s: got %d, want %d\n", what, got, want);
        fails++;
    }
}
int main(void)
{
    gSelectButton = KEY_CROSS;
    expect("Cross confirm: confirm key", guiConfirmKey(), KEY_CROSS);
    expect("Cross confirm: cancel key", guiCancelKey(), KEY_CIRCLE);
    expect("Cross confirm: confirm icon", guiConfirmIcon(), CROSS_ICON);
    expect("Cross confirm: cancel icon", guiCancelIcon(), CIRCLE_ICON);
    gSelectButton = KEY_CIRCLE;
    expect("Circle confirm: confirm key", guiConfirmKey(), KEY_CIRCLE);
    expect("Circle confirm: cancel key", guiCancelKey(), KEY_CROSS);
    expect("Circle confirm: confirm icon", guiConfirmIcon(), CIRCLE_ICON);
    expect("Circle confirm: cancel icon", guiCancelIcon(), CROSS_ICON);
    if (!fails)
        printf("confirm button: both Select Button settings map confirm/cancel and their icons correctly\n");
    return fails ? 1 : 0;
}
'''

helpers = ''.join(function_text(gui_c, 'src/gui.c', 'int %s(' % name)
                  for name in ('guiConfirmKey', 'guiCancelKey', 'guiConfirmIcon', 'guiCancelIcon'))
if not failures:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'confirm.c'
        exe = Path(tmp) / ('confirm' + ('.exe' if sys.platform == 'win32' else ''))
        src.write_text(HARNESS.replace('@FUNCTIONS@', helpers), encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('confirm harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('confirm harness reported failures')

# ANY Cross/Circle key or icon token -- getKeyOn, getKey, a ternary on gSelectButton -- is a hard-wire
# here; these screens take both from the helpers (CodeRabbit #818).
HARDWIRED = re.compile(r'\bKEY_(?:CROSS|CIRCLE)\b|\b(?:CROSS|CIRCLE)_ICON\b')
for where, source, signature in (
    ('src/gui.c', gui_c, 'static int guiSettingsPromptSave('),
    ('src/gui.c', gui_c, 'static void guiDrawSettingsIndexHints('),
    ('src/gui.c', gui_c, 'static int guiSettingsShowIndex('),
    ('src/gui.c', gui_c, 'int guiPromptRebootIop('),
    ('src/gui.c', gui_c, 'static int guiReadPopsNet('),
    ('src/dia.c', dia_c, 'static int diaHandleInput('),
    ('src/dia.c', dia_c, 'int diaExecuteDialog('),
):
    body = function_text(source, where, signature)
    hit = HARDWIRED.search(body) if body else None
    if hit:
        failures.append('%s %s...): hard-wires "%s" -- use guiConfirmKey/guiCancelKey and their icons'
                        % (where, signature, hit.group(0)))

render = function_text(dia_c, 'src/dia.c', 'void diaRenderUI(')
settings_hints = render.split('if (settingsContext) {', 1)[1].split('} else {', 1)[0] if 'if (settingsContext) {' in render else ''
if not settings_hints:
    failures.append('diaRenderUI: the Settings hint bar block was not found')
elif re.search(r'\b(?:CROSS|CIRCLE)_ICON\b', settings_hints):
    failures.append('diaRenderUI: the Settings hint bar must draw guiConfirmIcon()/guiCancelIcon(), not fixed icons')

if failures:
    print('Confirm button checks FAILED:')
    for failure in failures:
        print(' - ' + failure)
    sys.exit(1)
