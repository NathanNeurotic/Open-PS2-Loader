"""Interface > PS1 Duplicates (from RIPPS2 build 126): a PS1 game kept both as a POPSTARTER VCD and
as an Ember image shows once, as the one picked; Both (the default) keeps both rows.

Compiles ps1FillGameList with its twin filter from the production source over fake VCD and Ember
halves, then checks the setting's wiring: config key, default, settings row and list rebuild.
"""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
CPP = (root / "src/sources/cuesupport.cpp").exists()


def read(c_path, cpp_path):
    return (root / (cpp_path if CPP else c_path)).read_text(encoding="utf-8")


def function(source, signature):
    start = source.index(signature)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(signature)


cue = read("src/cuesupport.c", "src/sources/cuesupport.cpp")
pieces = "\n".join(function(cue, sig) for sig in (
    "static const char *ps1TwinKey(", "int ps1DropTwins(", "int ps1FillGameList("))
program = r'''
#include <assert.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
typedef struct { char name[64]; int ember; } base_game_info_t;
enum { PS1_DUP_BOTH = 0, PS1_DUP_EMBER, PS1_DUP_POPSTARTER };
static int gPs1Duplicates, gAutosort, ps1ScanIncomplete;
#define LOG(...) ((void)0)
static int ps1RowCmp(const void *a, const void *b) { (void)a; (void)b; return 0; }
static void *memalign(int a, size_t n) { (void)a; return malloc(n); }
static const char *vcdNames[] = {"SLUS_005.94.Crash Bandicoot", "Spyro the Dragon", "Only VCD", "XX.SCUS_944.26.Ape Escape", "SLES_123.45-Medievil", "SLUS_00X.94.Weird", NULL};
static const char *cueNames[] = {"crash bandicoot", "Spyro the Dragon", "Only Ember", "Ape Escape", "MediEvil", "Weird", "SPYRO THE DRAGON", NULL};
static int half(const char **names, int ember, base_game_info_t **out) {
    int n = 0;
    while (names[n]) n++;
    *out = (base_game_info_t *)calloc(n, sizeof(**out));
    for (int i = 0; i < n; i++) { snprintf((*out)[i].name, sizeof((*out)[i].name), "%s", names[i]); (*out)[i].ember = ember; }
    return n;
}
static int vcdFillGameList(const char *p, base_game_info_t **out) { (void)p; return half(vcdNames, 0, out); }
static int cueFillGameListUnsorted(const char *p, base_game_info_t **out) { (void)p; return half(cueNames, 1, out); }
static int has(base_game_info_t *rows, int n, const char *name, int ember) {
    for (int i = 0; i < n; i++)
        if (!strcmp(rows[i].name, name) && rows[i].ember == ember) return 1;
    return 0;
}
''' + pieces + r'''
int main(void) {
    base_game_info_t *rows = NULL;
    gPs1Duplicates = PS1_DUP_BOTH;
    int n;
    assert(ps1FillGameList("mass0:/", &rows) == 13);
    gPs1Duplicates = PS1_DUP_EMBER;
    assert((n = ps1FillGameList("mass0:/", &rows)) == 9);
    assert(has(rows, n, "Ape Escape", 1) && has(rows, n, "MediEvil", 1) && !has(rows, n, "XX.SCUS_944.26.Ape Escape", 0));
    assert(has(rows, n, "crash bandicoot", 1) && has(rows, n, "Spyro the Dragon", 1) && has(rows, n, "SPYRO THE DRAGON", 1));
    assert(has(rows, n, "Only VCD", 0) && has(rows, n, "Only Ember", 1));
    assert(!has(rows, n, "SLUS_005.94.Crash Bandicoot", 0));
    /* Not a disc ID ("00X" is not three digits): the name is kept whole, so no twin. */
    assert(has(rows, n, "SLUS_00X.94.Weird", 0) && has(rows, n, "Weird", 1));
    gPs1Duplicates = PS1_DUP_POPSTARTER;
    assert((n = ps1FillGameList("mass0:/", &rows)) == 8);
    assert(has(rows, n, "XX.SCUS_944.26.Ape Escape", 0) && has(rows, n, "SLES_123.45-Medievil", 0) && !has(rows, n, "MediEvil", 1));
    assert(has(rows, n, "SLUS_005.94.Crash Bandicoot", 0) && has(rows, n, "Spyro the Dragon", 0));
    /* Every Ember copy of a VCD goes, not only the first. */
    assert(!has(rows, n, "Spyro the Dragon", 1) && !has(rows, n, "SPYRO THE DRAGON", 1));
    assert(has(rows, n, "Only VCD", 0) && has(rows, n, "Only Ember", 1));
    assert(!has(rows, n, "crash bandicoot", 1));
    assert(has(rows, n, "SLUS_00X.94.Weird", 0) && has(rows, n, "Weird", 1));
    free(rows);

    /* The HDD list keeps each row's partition in a parallel array: it moves with its row. */
    base_game_info_t hdd[3] = {{"SLUS_005.94.Crash Bandicoot", 0}, {"Only VCD", 0}, {"Crash Bandicoot", 1}};
    char parts[3][33] = {"__.POPS", "__.POPS1", "__.EMBER"};
    assert(ps1DropTwins(hdd, parts, sizeof(parts[0]), 2, 1, PS1_DUP_EMBER) == 2);
    assert(!strcmp(hdd[0].name, "Only VCD") && !strcmp(parts[0], "__.POPS1"));
    assert(!strcmp(hdd[1].name, "Crash Bandicoot") && !strcmp(parts[1], "__.EMBER"));
    puts("PASS: PS1 Duplicates keeps both, the Ember twin or the VCD twin; a POPSTARTER prefix, a real disc ID and case are ignored");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="ps1dup-") as tmp:
    src, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
    src.write_text(program, encoding="utf-8")
    subprocess.run(["c++", "-std=gnu++17", "-Wall", "-Werror", "-x", "c++", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

if CPP:  # one settings table loads and saves every key
    table = (root / "src/core/settings.cpp").read_text(encoding="utf-8")
    assert "intSetting(CONFIG_OPL_PS1_DUPLICATES, &gPs1Duplicates, PS1_DUP_BOTH)" in table, "saved, default Both"
else:
    opl = read("src/opl.c", "src/app/opl.cpp")
    assert "CONFIG_OPL_PS1_DUPLICATES, &gPs1Duplicates" in opl and "CONFIG_OPL_PS1_DUPLICATES, gPs1Duplicates" in opl
    assert re.search(r"gPs1Duplicates = PS1_DUP_BOTH;", opl), "default keeps both rows"
assert '"ps1_duplicates"' in (root / "include/config.h").read_text(encoding="utf-8")
gui = read("src/gui.c", "src/ui/guisettings.cpp")
assert "diaGetInt(ui, UICFG_PS1_DUPLICATES, &gPs1Duplicates)" in gui
assert "previousPs1Dup != gPs1Duplicates" in gui, "a change rebuilds the lists"
assert re.search(r"if \(previousPs1Dup != gPs1Duplicates\)\s*hddVcdInvalidateCache\(\);", gui), "and rescans the cached HDD list"
hdd = read("src/hddsupport.c", "src/sources/hddsupport.cpp")
assert "ps1DropTwins(newGames, newParts, sizeof(*newParts), vcdRows, total - vcdRows, gPs1Duplicates)" in hdd, "HDD honours it"
base = (root / ("lng/tmpl/_base.yml" if CPP else "lng_tmpl/_base.yml")).read_text(encoding="utf-8")
for label in ("PS1_DUPLICATES", "HINT_PS1_DUPLICATES", "PS1_DUPLICATES_BOTH"):
    assert "label: " + label + "\n" in base, label
print("PASS: PS1 Duplicates is saved, defaults to Both, and rebuilds the lists when changed")
