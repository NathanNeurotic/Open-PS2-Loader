"""A translated string must not read arguments its English string is not given.

RiptOPL hands each translation to printf with the English string's arguments. Several upstream
translations do not match them: French AUTO_START_IN_N_SECS has %s where English has %i (the
Auto Start countdown then reads its int as a string pointer and crashes), Persian strings swap or
add conversions. lngLoadFromFile now checks every loaded string with lngFormatFits and shows the
English string instead of one that would misread its arguments.

This compiles the real lngFormatArgs/lngFormatFits from src/lang.c and checks them against the
upstream cases and the printf forms RiptOPL's strings use, and that lngLoadFromFile applies them.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/lang.c").read_text(encoding="utf-8").replace("\r\n", "\n")
failures = []

start = source.find("static int lngFormatArgs(")
end = source.find("static int lngLoadFromFile(", start)
if start < 0 or end < 0:
    print("src/lang.c: lngFormatArgs/lngFormatFits not found before lngLoadFromFile")
    sys.exit(1)
guard = source[start:end]

load = source[end:source.find("\n}\n", end) + 3]
if not re.search(r"lngFormatFits\(newL\[i\], internalEnglish\[i\]\)", load):
    failures.append("lngLoadFromFile does not check each loaded string with lngFormatFits")

# (translation, English, fits)
CASES = [
    ("Lancement automatique dans %s...", "Auto start in %i s...", 0),  # upstream French: crash
    ("Auto %i s", "Auto start in %i s...", 1),
    ("% s ... % d", "%s ... %d", 1),  # upstream Cebuano: a space flag reads the same argument
    ("no conversions", "%s %d", 1),  # upstream Japanese: fewer arguments are never misread
    ("%s %d %d", "%s %d", 0),  # upstream TChinese: an argument that is not passed
    ("%d %s", "%s %d", 0),  # upstream Persian: swapped
    ("%s %s", "%s", 0),  # upstream Persian GAME_SETTINGS_REMOVED
    ("100%% done %s", "%s", 1),
    ("%1$s", "%s", 0),  # positional arguments are not understood: English is safer
    ("%-10s|%5.2f", "%s|%f", 1),
    ("%lu", "%u", 0),
    ("%lu", "%lu", 1),
    ("%lld", "%d", 0),
    ("%hhd %hu %c %x", "%d %d %d %d", 1),
    ("%d", "%*d", 1),
    ("%*d", "%d", 0),
    ("%p", "%s", 0),
    ("%n", "%d", 0),
    ("trailing %", "%d", 0),
    ("%s", "not a format %", 1),  # English this check does not understand: left alone
    ("", "", 1),
]

harness = r"""
#include <stdio.h>
#include <string.h>
""" + guard + r"""
struct test_case { const char *translated, *english; int fits; };
static const struct test_case cases[] = {
@CASES@
};
int main(void)
{
    int failures = 0;
    for (unsigned int i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        int fits = lngFormatFits(cases[i].translated, cases[i].english);
        if (fits != cases[i].fits) {
            printf("\"%s\" for English \"%s\": %s, want %s\n", cases[i].translated, cases[i].english,
                   fits ? "kept" : "replaced", cases[i].fits ? "kept" : "replaced");
            failures++;
        }
    }
    return failures != 0;
}
"""


def c_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


rows = ",\n".join("    {%s, %s, %d}" % (c_string(t), c_string(e), f) for t, e, f in CASES)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    program = tmp / "guard.c"
    exe = tmp / ("guard.exe" if sys.platform == "win32" else "guard")
    program.write_text(harness.replace("@CASES@", rows), encoding="utf-8")
    build = subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-format-security",
                            str(program), "-o", str(exe)], capture_output=True, text=True, check=False)
    if build.returncode != 0:
        failures.append("did not compile:\n" + build.stderr)
    else:
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=20)
        if run.returncode != 0:
            failures += run.stdout.strip().splitlines() or ["exited %d" % run.returncode]

if failures:
    print("\n".join(failures))
    sys.exit(1)
print("Language format guard: translations that misread their arguments fall back to English")
