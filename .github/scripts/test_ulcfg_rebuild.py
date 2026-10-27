"""Rewriting ul.cfg after a USBLD game is deleted or renamed never leaves it truncated.

sbRebuildULCfg() used to open ul.cfg with "wb" and ignore fwrite() and fclose(), so a write that failed
part-way (a share or drive dropping out) silently dropped every USBLD game after that point. It now writes
ul.cfg.tmp, checks every write and the close, and replaces ul.cfg only once that file is complete.

The real sbWriteULCfg() and sbRebuildULCfg() from src/supportbase.c are compiled against a small in-memory
file system whose fopen, fwrite, fclose, unlink and rename can be made to fail, and checks what ul.cfg and
ul.cfg.tmp hold afterwards. Pass another supportbase.c to check it instead. This is a host check, not a
console test.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "src/supportbase.c"
source = path.read_text(encoding="utf-8")
header = (ROOT / "include/supportbase.h").read_text(encoding="utf-8")


def function(signature):
    match = re.search(r"^" + re.escape(signature) + r"[^;{]*\)\s*\{", source, re.M)
    if match is None:
        sys.exit(f"{path}: {signature}...) not found")
    return source[match.start():source.index("\n}\n", match.start()) + 3]


def typedef(name):
    end = header.index("} %s;" % name)
    return header[header.rfind("typedef struct", 0, end):end] + "} %s;\n" % name


code = (function("static int sbWriteULCfg(") if "static int sbWriteULCfg(" in source else "") + \
    function("void sbRebuildULCfg(")
types = "".join(re.search(r"^#define %s\b.*$" % n, header, re.M).group(0) + "\n" for n in
                ("UL_GAME_NAME_MAX", "ISO_GAME_NAME_MAX", "ISO_GAME_EXTENSION_MAX", "GAME_STARTUP_MAX"))
types += header[header.index("enum GAME_FORMAT {"):header.index("};", header.index("enum GAME_FORMAT {")) + 3]
types += typedef("base_game_info_t") + typedef("USBExtreme_game_entry_t")

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned int u32;
@TYPES@
#define LOG(...) printf("  log: " __VA_ARGS__)

/* A file system of a few named files. Each fopen("wb") truncates; writes go through a stdio-like buffer
   that reaches the file only at fclose, so a failing device can first show at fclose. */
#define NFILES 4
static struct { char name[64]; unsigned char data[4096]; int size, used; } fs[NFILES];
static int fail_open_tmp, fail_write_at, fail_close, fail_rename, fail_direct, writes, direct_opens;
typedef struct { int f; unsigned char buf[4096]; int len; int direct; } FAKEFILE;
static int lookup(const char *name)
{
    for (int i = 0; i < NFILES; i++) if (fs[i].used && !strcmp(fs[i].name, name)) return i;
    return -1;
}
static int create(const char *name)
{
    int i = lookup(name);
    if (i < 0) for (i = 0; fs[i].used; i++);
    fs[i].used = 1; strcpy(fs[i].name, name); fs[i].size = 0;
    return i;
}
static FAKEFILE *fake_fopen(const char *name, const char *mode)
{
    int tmp = strstr(name, ".tmp") != NULL;
    if (strcmp(mode, "wb") || (tmp && fail_open_tmp) || (!tmp && fail_direct == 1)) return NULL;
    FAKEFILE *f = calloc(1, sizeof(*f));
    direct_opens += !tmp;
    f->f = create(name); f->direct = !tmp;
    return f;
}
static size_t fake_fwrite(const void *p, size_t size, size_t n, FAKEFILE *f)
{
    if (++writes == fail_write_at || (f->direct && fail_direct == 2)) return 0;
    memcpy(f->buf + f->len, p, size * n); f->len += size * n;
    return n;
}
static int fake_fclose(FAKEFILE *f)
{
    int fail = fail_close || (f->direct && fail_direct == 3);
    if (!fail) { memcpy(fs[f->f].data, f->buf, f->len); fs[f->f].size = f->len; }
    else fs[f->f].size = f->len / 2; /* what a dropped device leaves */
    free(f);
    return fail ? -1 : 0;
}
static int fake_unlink(const char *name) { int i = lookup(name); if (i < 0) return -1; fs[i].used = 0; return 0; }
static int fake_rename(const char *from, const char *to)
{
    int i = lookup(from);
    if (i < 0 || fail_rename || lookup(to) >= 0) return -1; /* like FatFs: no rename over a file */
    strcpy(fs[i].name, to);
    return 0;
}
#define FILE FAKEFILE
#define fopen fake_fopen
#define fwrite fake_fwrite
#define fclose fake_fclose
#define unlink fake_unlink
#define rename fake_rename

@CODE@

static base_game_info_t games[5];
static base_game_info_t *list = games;
static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL: " __VA_ARGS__); puts(""); } } while (0)

static void reset(void)
{
    memset(fs, 0, sizeof(fs));
    fail_open_tmp = fail_write_at = fail_close = fail_rename = fail_direct = writes = direct_opens = 0;
    memset(games, 0, sizeof(games));
    for (int i = 0; i < 5; i++) {
        snprintf(games[i].name, sizeof(games[i].name), "Game %d", i);
        snprintf(games[i].startup, sizeof(games[i].startup), "SLUS_%03d.%02d", i, i);
        games[i].parts = (u8)(i + 1); games[i].media = 0x14; games[i].format = GAME_FORMAT_USBLD;
    }
    games[2].format = GAME_FORMAT_ISO; /* never written to ul.cfg */
    int f = create("mass0:ul.cfg");
    fs[f].size = 4 * (int)sizeof(USBExtreme_game_entry_t);
    memset(fs[f].data, 0x5A, fs[f].size); /* the previous ul.cfg */
}
static int entries(const char *name) { int i = lookup(name); return i < 0 ? -1 : fs[i].size / (int)sizeof(USBExtreme_game_entry_t); }
static int old_kept(void) { int i = lookup("mass0:ul.cfg"); return i >= 0 && fs[i].size == 4 * (int)sizeof(USBExtreme_game_entry_t) && fs[i].data[0] == 0x5A; }
static void check_list(const char *name, int exclude)
{
    int i = lookup(name), n = 0;
    for (int g = 0; g < 5; g++) {
        if (games[g].format != GAME_FORMAT_USBLD || g == exclude) continue;
        USBExtreme_game_entry_t *e = (USBExtreme_game_entry_t *)fs[i].data + n++;
        CHECK(!memcmp(e->name, games[g].name, UL_GAME_NAME_MAX) && !memcmp(e->startup, games[g].startup, GAME_STARTUP_MAX) &&
                  e->parts == games[g].parts && e->media == 0x14 && !memcmp(e->magic, "ul.", 3) && e->Byte08 == 0x08,
              "%s entry %d is not game %d", name, n - 1, g);
    }
    CHECK(entries(name) == n, "%s holds %d entries, want %d", name, entries(name), n);
}

int main(void)
{
    reset();
    sbRebuildULCfg(&list, "mass0:", 5, 1);
    check_list("mass0:ul.cfg", 1);
    CHECK(lookup("mass0:ul.cfg.tmp") < 0, "a clean rewrite left ul.cfg.tmp behind");
    CHECK(direct_opens == 0, "a clean rewrite opened ul.cfg itself instead of renaming the complete list over it");

    reset();
    sbRebuildULCfg(&list, "mass0:", 5, -1); /* a rename rewrites every game */
    check_list("mass0:ul.cfg", -1);

    reset();
    fail_write_at = 2;
    sbRebuildULCfg(&list, "mass0:", 5, -1);
    CHECK(old_kept(), "a failed write changed ul.cfg");
    CHECK(lookup("mass0:ul.cfg.tmp") < 0, "a failed write left ul.cfg.tmp behind");

    reset();
    fail_close = 1;
    sbRebuildULCfg(&list, "mass0:", 5, 0);
    CHECK(old_kept(), "a failed close changed ul.cfg");
    CHECK(lookup("mass0:ul.cfg.tmp") < 0, "a failed close left ul.cfg.tmp behind");

    reset();
    fail_open_tmp = 1;
    sbRebuildULCfg(&list, "mass0:", 5, 0);
    CHECK(old_kept(), "a failed open changed ul.cfg");

    reset();
    fail_rename = 1; /* a driver without rename: ul.cfg is written directly, as before */
    sbRebuildULCfg(&list, "mass0:", 5, 3);
    check_list("mass0:ul.cfg", 3);
    CHECK(lookup("mass0:ul.cfg.tmp") < 0, "the direct write left ul.cfg.tmp behind");

    for (int mode = 1; mode <= 3; mode++) {
        reset();
        fail_rename = 1; fail_direct = mode; /* and then the direct write fails too: the new list survives */
        sbRebuildULCfg(&list, "mass0:", 5, 3);
        CHECK(lookup("mass0:ul.cfg.tmp") >= 0, "with rename and direct write failing (%d), ul.cfg.tmp was removed", mode);
        if (lookup("mass0:ul.cfg.tmp") >= 0) check_list("mass0:ul.cfg.tmp", 3);
    }

    reset();
    for (int i = 0; i < 5; i++) games[i].format = GAME_FORMAT_ISO;
    sbRebuildULCfg(&list, "mass0:", 5, -1);
    CHECK(entries("mass0:ul.cfg") == 0, "no USBLD games should leave an empty ul.cfg");

    if (fails) { printf("%d failure(s)\n", fails); return 1; }
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "ulcfg.c"
    exe = Path(tmp) / "ulcfg.exe"
    src.write_text(harness.replace("@TYPES@", types).replace("@CODE@", code), encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
    if subprocess.run([str(exe)]).returncode:
        sys.exit(f"FAIL: {path}")
print("PASS: a failed ul.cfg rewrite keeps the previous list; a complete one replaces it")
