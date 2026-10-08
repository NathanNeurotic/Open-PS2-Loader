"""Regression test for #868: custom theme fonts must not pass a garbage expected size to readFile().

The September font-locking refactor split file IO into fntReadData(). Before that change, custom font
loads initialized bufferSize to -1 before readFile(); after the split the local became uninitialized.
readFile() interprets any positive incoming size as an exact expected file size, so a random positive
stack value makes a valid TTF fail to load and the theme silently falls back to FNT_DEFAULT.

Compile the real fntReadData() against a tiny stub and pin both contracts:
- file-backed font reads enter readFile() with size == -1 and accept the size readFile returns;
- the built-in font path still uses size_poeveticanew_raw and does not claim ownership.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/fntsys.c").read_text(encoding="utf-8").replace("\r\n", "\n")

match = re.search(r"^static void \*fntReadData\(.*?^}\n", source, re.M | re.S)
if match is None:
    print("FAIL: src/fntsys.c: fntReadData() not found")
    sys.exit(1)

function = match.group(0)

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char poeveticanew_raw[17];
static int size_poeveticanew_raw = sizeof(poeveticanew_raw);
static int seen_size = 999;
static unsigned char fake_font[123];

#define LOG(...) ((void)0)

static void *readFile(char *path, int align, int *size)
{
    (void)path;
    (void)align;
    seen_size = *size;
    *size = sizeof(fake_font);
    return fake_font;
}

@FUNCTION@

int main(void)
{
    int size = 777;
    int owned = -1;
    void *p = fntReadData("mass0:/THM/thm_test/custom.ttf", &size, &owned);

    if (p != fake_font) {
        puts("FAIL: file-backed font did not return readFile()'s buffer");
        return 1;
    }
    if (seen_size != -1) {
        printf("FAIL: readFile() saw expected size %d; custom font reads must start at -1\n", seen_size);
        return 1;
    }
    if (size != (int)sizeof(fake_font) || owned != 1) {
        printf("FAIL: file-backed result size/ownership = %d/%d\n", size, owned);
        return 1;
    }

    size = 777;
    owned = -1;
    p = fntReadData(NULL, &size, &owned);
    if (p != poeveticanew_raw || size != size_poeveticanew_raw || owned != 0) {
        printf("FAIL: built-in result size/ownership = %d/%d\n", size, owned);
        return 1;
    }

    puts("PASS: custom font reads use unknown-size sentinel and built-in font sizing is unchanged");
    return 0;
}
'''.replace("@FUNCTION@", function)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / "font_size_test.c"
    exe = td / "font_size_test"
    src.write_text(harness, encoding="utf-8")
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", str(src), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
