"""Execute the production cheat parser at capacity (YAOPL 44a003bd).

Optional git ref runs the same regression against an older source, to prove failure.
Only the master-name predicate is stubbed; scanner, code parsing and table types are real.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
cpp = (root / 'src/core/cheatman.cpp').exists()
path = 'src/core/cheatman.cpp' if cpp else 'src/cheatman.c'

def read(path):
    if len(sys.argv) > 1:
        return subprocess.check_output(['git', 'show', sys.argv[1] + ':' + path], cwd=root, text=True)
    return (root / path).read_text()

source = read(path)
header = read('include/cheatman.h')
# Keep production limits and structures, without importing PS2-only application headers.
types = header[header.index('#define CHEAT_VERSION'):header.index('extern cheat_entry_t *gCheats')]
parser = source[source.index('static code_t make_code('):source.index('static inline char *read_text_file(')]
program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <assert.h>
typedef unsigned int u32;
#define LOG(...) ((void)0)
@TYPES@
static cheat_entry_t *gCheats;
static int gCheatMode;
static int cheatConfigIsMasterCode(const char *name) { return !strcmp(name, "Master"); }
@PARSER@

static void scenario(int count, int lines, int mode, const char *eol, int final_lf)
{
    size_t cap = (size_t)(count + 1) * (lines + 3) * 100;
    char *text = (char *)calloc(cap, 1);
    size_t used = 0;
    int accepted = count < MAX_CODES ? count : MAX_CODES;
    assert(text);
    memset(gCheats, 0, MAX_CODES * sizeof(*gCheats));
    gCheatMode = mode;
    for (int i = 0; i < count; ++i) {
        used += snprintf(text + used, cap - used, "%s%s", i == 0 ? "Master" : "Cheat name", eol);
        for (int j = 0; j < lines; ++j) {
            used += snprintf(text + used, cap - used, "%08X %08X%s",
                             0x20000000u + (unsigned int)i * 16 + j,
                             0x100u + (unsigned int)i * 16 + j,
                             (i == count - 1 && j == lines - 1 && !final_lf) ? "" : eol);
        }
    }
    assert(used < cap);
    assert(parse_buf(text) == 0);
    for (int i = 0; i < MAX_CODES; ++i) {
        if (i < accepted) {
            assert(!strcmp(gCheats[i].name, i == 0 ? "Master" : "Cheat name"));
            assert(gCheats[i].enabled == (mode == 0 || i == 0));
            for (int j = 0; j < lines; ++j) {
                assert(gCheats[i].codes[j].addr == 0x20000000u + (unsigned int)i * 16 + j);
                assert(gCheats[i].codes[j].val == 0x100u + (unsigned int)i * 16 + j);
            }
            assert(gCheats[i].codes[lines].addr == 0);
            assert(gCheats[i].codes[lines].val == 0);
        } else {
            cheat_entry_t empty;
            memset(&empty, 0, sizeof(empty));
            assert(!memcmp(&empty, &gCheats[i], sizeof(empty)));
        }
    }
    free(text);
}

int main(void)
{
    const int counts[] = {0, 1, MAX_CODES - 1, MAX_CODES, MAX_CODES + 1, MAX_CODES + 20};
    gCheats = (cheat_entry_t *)calloc(MAX_CODES, sizeof(*gCheats));
    assert(gCheats);
    assert(parse_buf(NULL) == -1);
    for (unsigned int n = 0; n < sizeof(counts) / sizeof(counts[0]); ++n)
        for (int mode = 0; mode < 2; ++mode)
            for (int lines = 1; lines <= 3; ++lines)
                for (int ending = 0; ending < 2; ++ending)
                    for (int lf = 0; lf < 2; ++lf)
                        scenario(counts[n], lines, mode, ending ? "\r\n" : "\n", lf);
    memset(gCheats, 0, MAX_CODES * sizeof(*gCheats));
    gCheatMode = 0;
    assert(parse_buf("// comment\nEmpty cheat\n00000000 00000000\nGood cheat\n20000000 00000001\n20000004 00000002 # inline\n") == 0);
    assert(!strcmp(gCheats[0].name, "Good cheat"));
    assert(gCheats[0].codes[0].val == 1 && gCheats[0].codes[1].val == 2);
    assert(gCheats[1].name[0] == 0);
    free(gCheats);
    puts("cheat capacity: accepted names, codes and selection preserved");
    return 0;
}
'''.replace('@TYPES@', types).replace('@PARSER@', parser)
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / ('capacity.cpp' if cpp else 'capacity.c')
    exe = Path(tmp) / 'capacity'
    src.write_text(program)
    subprocess.run(['g++' if cpp else 'gcc', '-std=c++17' if cpp else '-std=c99',
                    '-g', '-O1', '-fno-pie', '-no-pie', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
