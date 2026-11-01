"""Game #Size when a driver's stat() reports no size (RIPPS2 build 126: MMCE showed "0 MiB").

Compiles sbFileSizeMB from the production source with stat() shimmed to answer size 0 (as such a
driver does) and checks that the size then comes from the file's end. Also checks the callers use it
and that the info page shows nothing, not "0 MiB", for an unmeasured size.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
CANDIDATES = {
    "base": ("src/supportbase.c", "src/sources/supportbase.cpp"),
    "theme": ("src/themes.c", "src/gfx/themeelems.cpp"),
}


def read(kind):
    for rel in CANDIDATES[kind]:
        path = root / rel
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError(kind)


def function(source, signature):
    start = source.index(signature)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(signature)


base = read("base")
helper = function(base, "static int sbFileSizeMB(")
program = r'''
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef long long s64;
#define lseek64 lseek
static int zeroStat; /* 1: behave like a driver whose stat gives no size */
static int fakeStat(const char *p, struct stat *st)
{
    int r = stat(p, st);
    if (r == 0 && zeroStat)
        st->st_size = 0;
    return r;
}
#define stat(p, st) fakeStat(p, st)
''' + helper + r'''
int main(int argc, char **argv)
{
    char big[512], gone[512];
    snprintf(big, sizeof(big), "%s/game.iso", argv[1]);
    snprintf(gone, sizeof(gone), "%s/missing.iso", argv[1]);
    zeroStat = 0; assert(sbFileSizeMB(big) == 7);
    zeroStat = 1; assert(sbFileSizeMB(big) == 7);  /* from the file's end */
    assert(sbFileSizeMB(gone) == 0);                /* nothing to open: stays unmeasured */
    assert(argc == 2);
    puts("PASS: sbFileSizeMB falls back to the file's end when stat gives no size");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="size-fallback-") as tmp:
    tmp = Path(tmp)
    with open(tmp / "game.iso", "wb") as f:
        f.truncate(7 << 20)
    src, exe = tmp / "t.c", tmp / "t"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["cc", "-Wall", "-Werror", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe), str(tmp)], check=True)

# sbResolvePs1Size has one size read (VCD); sbPopulateConfigIn two (ISO, then old ISO).
for sig, reads in (("void sbResolvePs1Size(", 1), ("config_set_t *sbPopulateConfigIn(", 2)):
    body = function(base, sig)
    assert body.count("sbFileSizeMB(gamepath)") == reads, sig
    assert "game->sizeMB = st.st_size >> 20" not in body, sig + " still stats only"

theme = read("theme")
draw = function(theme, "static void drawAttributeText(")
assert 'strcmp(mutableText->value, CONFIG_ITEM_SIZE)' in draw and 'strcmp(mutableText->currentValue, "0")' in draw
assert 'strcmp(mutableText->currentValue, "0.00")' in draw, "apps write an unmeasured size as 0.00"
assert draw.index('"0")') < draw.index("%s MiB"), "an unmeasured size returns before the MiB line is built"
print("PASS: ISO, old-ISO and PS1 VCD sizes use the fallback; the info page hides an unmeasured size")
