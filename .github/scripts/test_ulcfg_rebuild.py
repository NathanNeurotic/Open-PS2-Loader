"""Deleting or renaming a USBLD game must never lose the other games' ul.cfg entries or split a game (#1068).

sbRebuildULCfg() used to fopen ul.cfg with "wb", truncating every USBLD game's entry, and ignore fwrite()
and fclose(), so a full device or a drive or share dropping out left a short or empty list. sbRename()
ignored each part's rename, so a failure halfway left a game whose parts carried two names, and still wrote
the new name to ul.cfg. RiptOPL fixed both the same way (RiptOPL 0529574); this is the C copy.

The real span of src/supportbase.c from sbWriteULCfg() through sbRename() is compiled on the host over a
temporary folder, with fopen, fwrite, fclose and rename failures injected. It checks:

- a rebuild writes every USBLD entry (not the deleted one, not ISO rows) through ul.cfg.new, leaving none;
- a failed open, write or close leaves ul.cfg byte for byte as it was, and no ul.cfg.new;
- a driver that refuses to rename onto an existing file still gets the new list, and a ul.cfg it can neither
  replace nor remove (read-only) keeps the old list, with any rename put back;
- when both renames fail, ul.cfg is written directly; when that fails too, ul.cfg.new keeps the full list
  and a rename keeps the new name it lists;
- a rename whose second part fails puts the first part back and keeps the old name and ul.cfg;
- a rename whose ul.cfg rewrite fails puts every part back and keeps the old name.

Pass another supportbase.c to check it instead. This is a host check, not a console test.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'src/supportbase.c'
source = path.read_text(encoding='utf-8')
header = (root / 'include/supportbase.h').read_text(encoding='utf-8')
first = 'static int sbWriteULCfg(' if 'static int sbWriteULCfg(' in source else 'void sbRebuildULCfg('
start = source.rindex('\n\n', 0, source.index(first))
end = source.index('\n}\n', source.index('void sbRename(')) + 3
span = source[start:end]
types = ''.join(re.search(r'^#define %s\b.*$' % n, header, re.M).group(0) + '\n' for n in
                ('UL_GAME_NAME_MAX', 'ISO_GAME_NAME_MAX', 'ISO_GAME_EXTENSION_MAX', 'GAME_STARTUP_MAX'))
enum = header.index('enum GAME_FORMAT {')
types += header[enum:header.index('};', enum) + 3]
for name in ('base_game_info_t', 'USBExtreme_game_entry_t'):
    tail = header.index('} %s;' % name)
    types += header[header.rindex('typedef struct', 0, tail):tail] + '} %s;\n' % name

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
typedef unsigned char u8;
typedef unsigned int u32;
#define SCECdPS2CD 0x12
#define FOLDER_SUB_MAX 64
#define LOG(...) printf("  log: " __VA_ARGS__)
static char sbBrowseSub[FOLDER_SUB_MAX + 1];
static u32 USBA_crc32(const char *s) { u32 h = 0; while (*s) h = h * 31 + (u8)*s++; return h; }
@TYPES@
static int failOpenNew, failWrite, failClose, refuseOverwrite, failUnlinkCfg, failRenameAt = -1, failRenameAlso = -1, renames, writes;
static int isCfg(const char *p) { size_t n = strlen(p); return n >= 6 && !strcmp(p + n - 6, "ul.cfg"); }
/* failUnlinkCfg models a read-only ul.cfg: it can be read, but not removed or opened for writing. */
static FILE *fakeFopen(const char *p, const char *m) { return (failOpenNew && strstr(p, ".new")) || (failUnlinkCfg && isCfg(p) && m[0] == 'w') ? NULL : fopen(p, m); }
static size_t fakeFwrite(const void *p, size_t s, size_t n, FILE *f) { writes++; return failWrite && --failWrite == 0 ? 0 : fwrite(p, s, n, f); }
static int fakeFclose(FILE *f) { int r = fclose(f); return failClose ? -1 : r; }
static int fakeRename(const char *a, const char *b)
{
    struct stat st;
    int n = renames++;
    if (n == failRenameAt || n == failRenameAlso || (refuseOverwrite && stat(b, &st) == 0))
        return -1;
    return rename(a, b);
}
static int fakeUnlink(const char *p) { return failUnlinkCfg && isCfg(p) ? -1 : unlink(p); }
#define fopen fakeFopen
#define unlink fakeUnlink
#define fwrite fakeFwrite
#define fclose fakeFclose
#define rename fakeRename
@SPAN@
#undef unlink
#undef rename
#undef fclose
#undef fwrite
#undef fopen
static char dir[256];
static int failures;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL: %s\n", m); failures++; } } while (0)
static long fileSize(const char *name) { char p[512]; struct stat st; snprintf(p, sizeof(p), "%s%s", dir, name); return stat(p, &st) == 0 ? st.st_size : -1; }
static int readFile(const char *name, char *buf, int max) { char p[512]; snprintf(p, sizeof(p), "%s%s", dir, name); FILE *f = fopen(p, "rb"); if (!f) return -1; int n = (int)fread(buf, 1, max, f); fclose(f); return n; }
static void touch(const char *name) { char p[512]; snprintf(p, sizeof(p), "%s%s", dir, name); FILE *f = fopen(p, "wb"); fputs("x", f); fclose(f); }
static void game(base_game_info_t *g, const char *name, int parts, int format) { memset(g, 0, sizeof(*g)); strcpy(g->name, name); strcpy(g->startup, "SLUS_123.45"); g->parts = parts; g->media = 0x14; g->format = format; }
static void partName(char *out, const base_game_info_t *g, const char *name, int part) { sbCreatePath_name(g, out, "", "/", part, name); }
/* The names ul.cfg (or another list file) holds, in order, joined by commas. */
static void names(const char *file, char *out)
{
    USBExtreme_game_entry_t e[8];
    int n = readFile(file, (char *)e, sizeof(e)) / (int)sizeof(e[0]);
    out[0] = '\0';
    for (int i = 0; i < n; i++) {
        CHECK(!memcmp(e[i].magic, "ul.", 3) && e[i].Byte08 == 0x08 && e[i].media == 0x14 && !memcmp(e[i].startup, "SLUS_123.45", 11), "entry layout");
        strncat(out, e[i].name, UL_GAME_NAME_MAX); strcat(out, ",");
    }
}
static void reset(void) { failOpenNew = failWrite = failClose = refuseOverwrite = failUnlinkCfg = renames = writes = 0; failRenameAt = failRenameAlso = -1; }
int main(int argc, char **argv)
{
    (void)argc;
    snprintf(dir, sizeof(dir), "%s/", argv[1]);
    base_game_info_t games[4], *list = games;
    game(&games[0], "Alpha", 2, GAME_FORMAT_USBLD); game(&games[1], "Beta", 1, GAME_FORMAT_USBLD);
    game(&games[2], "Disc", 1, GAME_FORMAT_ISO); game(&games[3], "Gamma", 1, GAME_FORMAT_USBLD);
    char list3[] = "Alpha,Beta,Gamma,", got[512], before[4096], after[4096];
    int n0, n1;

    reset();
    CHECK(sbRebuildULCfg(&list, dir, 4, -1) == 0, "a clean rebuild returns 0");
    names("ul.cfg", got);
    CHECK(!strcmp(got, list3) && fileSize("ul.cfg.new") < 0, "a rebuild writes every USBLD entry, no ISO row, and no ul.cfg.new");
    CHECK(renames == 1, "a clean rebuild renames ul.cfg.new over ul.cfg once");

    n0 = readFile("ul.cfg", before, sizeof(before));
    reset(); failOpenNew = 1;
    CHECK(sbRebuildULCfg(&list, dir, 4, 1) == -1, "a failed open returns -1");
    reset(); failWrite = 2;
    CHECK(sbRebuildULCfg(&list, dir, 4, 1) == -1, "a failed write returns -1");
    reset(); failClose = 1;
    CHECK(sbRebuildULCfg(&list, dir, 4, 1) == -1, "a failed close returns -1");
    n1 = readFile("ul.cfg", after, sizeof(after));
    CHECK(n0 == n1 && !memcmp(before, after, n0) && fileSize("ul.cfg.new") < 0, "a failed open, write or close keeps ul.cfg byte for byte and leaves no ul.cfg.new");

    reset(); refuseOverwrite = 1;
    CHECK(sbRebuildULCfg(&list, dir, 4, 1) == 0, "a driver without rename-over still succeeds");
    names("ul.cfg", got);
    CHECK(!strcmp(got, "Alpha,Gamma,") && fileSize("ul.cfg.new") < 0, "a driver without rename-over gets the new list");
    CHECK(renames == 2 && writes == 2, "a driver without rename-over gets ul.cfg.new renamed, not a second write");
    n0 = readFile("ul.cfg", before, sizeof(before));
    reset(); refuseOverwrite = 1; failUnlinkCfg = 1; /* a read-only ul.cfg */
    CHECK(sbRebuildULCfg(&list, dir, 4, -1) == -1, "a ul.cfg that cannot be replaced or removed returns -1");
    n1 = readFile("ul.cfg", after, sizeof(after));
    CHECK(n0 == n1 && !memcmp(before, after, n0) && fileSize("ul.cfg.new") < 0, "a ul.cfg that cannot be replaced or removed is kept and no ul.cfg.new is left");
    reset();
    CHECK(sbRebuildULCfg(&list, dir, 4, -1) == 0, "the list is restored");

    reset(); failRenameAt = 0; failRenameAlso = 1;
    CHECK(sbRebuildULCfg(&list, dir, 4, -1) == 0, "with both renames failing, the direct write still succeeds");
    names("ul.cfg", got);
    CHECK(!strcmp(got, list3) && fileSize("ul.cfg.new") < 0, "the direct write holds the new list and ul.cfg.new is removed");

    reset(); failRenameAt = 0; failRenameAlso = 1; failWrite = 4; /* two staged entries, then the direct write's second entry fails */
    CHECK(sbRebuildULCfg(&list, dir, 4, 3) == 1, "with renames and the direct write failing, the result is 1");
    names("ul.cfg.new", got);
    CHECK(!strcmp(got, "Alpha,Beta,"), "ul.cfg.new keeps the full new list");
    reset();
    CHECK(sbRebuildULCfg(&list, dir, 4, -1) == 0 && fileSize("ul.cfg.new") < 0, "the next rebuild replaces a leftover ul.cfg.new");

    char path[256], other[256];
    for (int part = 0; part < 2; part++) { partName(path, &games[0], "Alpha", part); touch(path); }
    reset(); failRenameAt = 1;
    sbRename(&list, dir, "/", 4, 0, (char *)"Omega");
    CHECK(strcmp(games[0].name, "Alpha") == 0, "a failed part rename keeps the old name");
    for (int part = 0; part < 2; part++) {
        partName(path, &games[0], "Alpha", part); partName(other, &games[0], "Omega", part);
        CHECK(fileSize(path) == 1 && fileSize(other) < 0, "after a failed part rename every part is back under the old name");
    }
    names("ul.cfg", got);
    CHECK(!strcmp(got, list3), "a failed part rename leaves ul.cfg alone");

    partName(other, &games[0], "Omega", 1); touch(other); /* another file already holds the second part's new name */
    reset(); failRenameAt = 1;
    sbRename(&list, dir, "/", 4, 0, (char *)"Omega");
    CHECK(fileSize(other) == 1, "the rollback touches only the parts it renamed");
    for (int part = 0; part < 2; part++) {
        partName(path, &games[0], "Alpha", part);
        CHECK(fileSize(path) == 1, "after a failed part rename every part is back under the old name");
    }
    unlink(other);

    reset(); refuseOverwrite = 1; failUnlinkCfg = 1; /* parts rename; ul.cfg cannot be replaced or removed */
    sbRename(&list, dir, "/", 4, 0, (char *)"Omega");
    names("ul.cfg", got);
    CHECK(strcmp(games[0].name, "Alpha") == 0 && !strcmp(got, list3), "a ul.cfg that keeps the old list keeps the old name");
    for (int part = 0; part < 2; part++) {
        partName(path, &games[0], "Alpha", part);
        CHECK(fileSize(path) == 1, "a ul.cfg that keeps the old list gets the parts put back");
    }

    reset(); failWrite = 1; /* parts rename, then the ul.cfg write fails */
    sbRename(&list, dir, "/", 4, 0, (char *)"Omega");
    names("ul.cfg", got);
    CHECK(strcmp(games[0].name, "Alpha") == 0 && !strcmp(got, list3), "a failed ul.cfg rewrite keeps the old name and list");
    for (int part = 0; part < 2; part++) {
        partName(path, &games[0], "Alpha", part);
        CHECK(fileSize(path) == 1, "a failed ul.cfg rewrite puts the parts back");
    }

    reset();
    sbRename(&list, dir, "/", 4, 0, (char *)"Omega");
    partName(path, &games[0], "Omega", 1);
    names("ul.cfg", got);
    CHECK(strcmp(games[0].name, "Omega") == 0 && fileSize(path) == 1 && !strcmp(got, "Omega,Beta,Gamma,"), "a clean rename renames every part and rewrites ul.cfg");

    reset(); failRenameAt = 2; failRenameAlso = 3; failWrite = 4; /* parts rename; ul.cfg.new is written but cannot replace ul.cfg */
    sbRename(&list, dir, "/", 4, 0, (char *)"Delta");
    partName(path, &games[0], "Delta", 1);
    names("ul.cfg.new", got);
    CHECK(strcmp(games[0].name, "Delta") == 0 && fileSize(path) == 1 && !strcmp(got, "Delta,Beta,Gamma,"),
          "with ul.cfg gone, the parts keep the name ul.cfg.new lists");

    reset();
    partName(path, &games[1], "Beta", 0); touch(path);
    sbDelete(&list, dir, "/", 4, 1);
    names("ul.cfg", got);
    CHECK(fileSize(path) < 0 && !strcmp(got, "Delta,Gamma,"), "a delete removes the part and the entry");
    return failures != 0;
}
'''

with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    data = work / 'device'
    data.mkdir()
    (work / 'harness.c').write_text(HARNESS.replace('@TYPES@', types).replace('@SPAN@', span), encoding='utf-8')
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wno-unused-function', str(work / 'harness.c'), '-o', str(work / 'harness')], check=True)
    result = subprocess.run([str(work / 'harness'), str(data)], capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.exit(f'FAIL: {path}')
print('PASS: ul.cfg is replaced only by a complete list, and a failed rename leaves the game whole')
