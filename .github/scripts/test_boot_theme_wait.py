"""Boot Theme Wait: the intro holds for the saved theme only as long as the setting says, and not at all by default.

The intro (guiIntroLoop in src/gui.c) used to keep the greeting on screen for a fixed 6 s whenever the saved disk theme
was not loaded yet, which includes a theme whose drive or folder is simply gone, so every boot paid the full 6 s.
The wait is now the Boot Theme Wait setting (boot_theme_wait, seconds, Settings > Interface), default 0 = off.

This compiles the real themeHoldMs() on the host and checks:
- 0 (the default) and negative values give no hold;
- 1..10 seconds give that many milliseconds;
- a hand-edited value above 10 is clamped to 10 s;
and statically that the hold condition requires themeHoldMs() > 0, that the setting defaults to 0, and that the
Interface page reads and writes it.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
splash = (root / 'src/gui.c').read_text(encoding='utf-8').replace('\r\n', '\n')
opl = (root / 'src/opl.c').read_text(encoding='utf-8')
guisettings = splash
dialogs = (root / 'src/dialogs.c').read_text(encoding='utf-8')

failures = []

start = splash.index('#define THEME_HOLD_MAX_S')
end = splash.index('\n}\n', splash.index('static int themeHoldMs(void)')) + 3
fn = splash[start:end]

if 'THEME_HOLD_MS' in splash:
    failures.append('the fixed THEME_HOLD_MS hold is still used')
if not re.search(r'themeHold\s*=\s*[^;]*themeHoldMs\(\)\s*>\s*0\s*&&\s*thmSavedThemePending\(\)', splash):
    failures.append('the hold condition does not require themeHoldMs() > 0 before waiting for the saved theme')
if not re.search(r'gBootThemeWait = 0;', opl):
    failures.append('boot_theme_wait does not default to 0 (off)')
if opl.count('configGetInt(configOPL, CONFIG_OPL_BOOT_THEME_WAIT, &gBootThemeWait);') != 2:
    failures.append('boot_theme_wait is not read on both settings load paths')
if opl.count('if (gBootThemeWait < 0 || gBootThemeWait > 10)') != 2:
    failures.append('a hand-edited boot_theme_wait is not clamped to 0..10 on both settings load paths')
if 'configSetInt(configOPL, CONFIG_OPL_BOOT_THEME_WAIT, gBootThemeWait);' not in opl:
    failures.append('boot_theme_wait is not saved')
if 'diaSetInt(ui, UICFG_BOOT_THEME_WAIT, gBootThemeWait)' not in guisettings:
    failures.append('the Interface page does not show the current Boot Theme Wait')
if 'diaGetInt(ui, UICFG_BOOT_THEME_WAIT, &gBootThemeWait)' not in guisettings:
    failures.append('the Interface page does not save Boot Theme Wait')
if '{UI_INT, UICFG_BOOT_THEME_WAIT, 1, 1, _STR_HINT_BOOT_THEME_WAIT, 0, 0, {.intvalue = {0, 0, 0, 10}}}' not in dialogs:
    failures.append('the Boot Theme Wait row is not a 0..10 integer defaulting to 0')

program = r'''
#include <stdio.h>
static int gBootThemeWait;
@FN@
int main(void)
{
    static const int in[] = {0, -3, 1, 6, 10, 11, 600};
    static const int want[] = {0, 0, 1000, 6000, 10000, 10000, 10000};
    int bad = 0;
    for (unsigned i = 0; i < sizeof(in) / sizeof(in[0]); i++) {
        gBootThemeWait = in[i];
        int got = themeHoldMs();
        if (got != want[i]) {
            printf("FAIL: boot_theme_wait=%d gave %d ms, want %d\n", in[i], got, want[i]);
            bad = 1;
        }
    }
    if (!bad)
        printf("boot theme wait: ok\n");
    return bad;
}
'''.replace('@FN@', fn)

with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / 'boot_theme_wait.c'
    exe = Path(tmp) / 'boot_theme_wait'
    c.write_text(program, encoding='utf-8')
    built = subprocess.run(['gcc', '-std=gnu11', '-Wall', str(c), '-o', str(exe)], capture_output=True, text=True)
    if built.returncode != 0:
        print(built.stderr)
        sys.exit('FAIL: could not build the boot theme wait harness')
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    print(ran.stdout, end='')
    if ran.returncode != 0:
        failures.append('themeHoldMs() harness failed')

for f in failures:
    print('FAIL:', f)
if failures:
    sys.exit(1)
