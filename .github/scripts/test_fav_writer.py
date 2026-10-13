"""Saving Favorites never leaves the user without a complete list (#936).

favWriteFile() used to open favourites.bin with O_TRUNC and write once: a short write left a
truncated file (the old list gone, the new one incomplete) and a failed close() still reported
success. The real writer and reader (src/favsupport.c) run here against an in-memory filesystem
with fault injection. The rule: the complete new list goes to favourites.bin.new first, then
favourites.bin is rewritten in place, then .new is removed. At every point either favourites.bin
holds the previous complete list, or .new holds the new complete one, and the reader prefers a
complete .new (it only survives an unfinished rewrite). The mc device has no rename, so the scheme
uses none.
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fav = (ROOT / "src/favsupport.c").read_text(encoding="utf-8")


def function(signature):
    start = fav.index(signature)
    return fav[start:fav.index("\n}\n", start) + 3]


names = ["static int rdBytes(", "static int rdU16(", "static int rdU32(", "static fav_raw_t *favReadPath(",
         "static fav_raw_t *favReadFile(", "static void bufU16(", "static void bufU32(",
         "static int favWriteAll(", "static int favWriteWhole(", "static u8 *favBuildImage(",
         "static int favRestoreStaged(", "static int favWriteFile("]
source = "\n".join(function(n) if not n.startswith("static int rdBytes(") else
                   fav[fav.index(n):fav.index("\n", fav.index(n)) + 1] for n in names)

harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 0x100
#define O_TRUNC 0x200
#define SEEK_SET 0
#define LOG(...) ((void)0)
#define FAV_TEXT_MAX 256
#define FAV_MAX_ITEMS 512
#define FAV_MAGIC 0x4641464F
#define FAV_VERSION 3
enum { FAV_KIND_ISO, FAV_KIND_VCD, FAV_KIND_CUE, FAV_KIND_ELF };
enum { APP_MODE = 7 };
typedef struct { int mode, id, icon_id, text_id, kind; char text[FAV_TEXT_MAX]; } fav_raw_t;

/* In-memory filesystem: two files at most, plus fault injection. */
typedef struct { char name[64]; u8 data[8192]; int len, exists; } mfile_t;
static mfile_t files[4];
static struct { mfile_t *f; int pos; } fds[8];
static int writeCap = -1, writesBeforeFail = -1, failCloseOn = -1, closes;
static const char *failOpenName;
static mfile_t *lookup(const char *name, int create)
{
    for (int i = 0; i < 4; i++) if (files[i].exists && !strcmp(files[i].name, name)) return &files[i];
    if (!create) return NULL;
    for (int i = 0; i < 4; i++) if (!files[i].exists) { memset(&files[i], 0, sizeof(files[i])); strcpy(files[i].name, name); files[i].exists = 1; return &files[i]; }
    return NULL;
}
static int open(const char *name, int flags, ...)
{
    mfile_t *f;
    if (failOpenName && !strcmp(name, failOpenName) && (flags & O_WRONLY)) return -1;
    f = lookup(name, (flags & O_CREAT) != 0);
    if (!f) return -1;
    if (flags & O_TRUNC) f->len = 0;
    for (int i = 0; i < 8; i++) if (!fds[i].f) { fds[i].f = f; fds[i].pos = 0; return i; }
    return -1;
}
static int read(int fd, void *buf, int n)
{
    mfile_t *f = fds[fd].f;
    int left = f->len - fds[fd].pos, take = n < left ? n : left;
    if (take < 0) take = 0;
    memcpy(buf, f->data + fds[fd].pos, take);
    fds[fd].pos += take;
    return take;
}
static int write(int fd, const void *buf, int n)
{
    mfile_t *f = fds[fd].f;
    if (writesBeforeFail == 0) return -1;
    if (writesBeforeFail > 0) writesBeforeFail--;
    if (writeCap >= 0 && n > writeCap) n = writeCap;   /* partial writes */
    memcpy(f->data + fds[fd].pos, buf, n);
    fds[fd].pos += n;
    if (fds[fd].pos > f->len) f->len = fds[fd].pos;
    return n;
}
static int close(int fd) { fds[fd].f = NULL; return closes++ == failCloseOn ? -1 : 0; }
static int lseek(int fd, int off, int whence) { (void)whence; fds[fd].pos = off; return off; }
static int fs_remove(const char *name) { mfile_t *f = lookup(name, 0); if (!f) return -1; f->exists = 0; return 0; }
#define remove fs_remove
static void favGetFilePath(char *out, int size) { snprintf(out, size, "mc0:OPL/favourites.bin"); }
static fav_raw_t *favReadWoplFile(int fd, int *count) { (void)fd; *count = 0; return NULL; }
'''

tests = r'''
static fav_raw_t recs[3];
static void make(int n, const char *prefix)
{
    for (int i = 0; i < n; i++) {
        memset(&recs[i], 0, sizeof(recs[i]));
        recs[i].mode = 1; recs[i].id = i;
        snprintf(recs[i].text, sizeof(recs[i].text), "%s %d", prefix, i);
    }
}
static int load(char *first)
{
    int count = 0;
    fav_raw_t *got = favReadFile(&count);
    if (first) first[0] = 0;
    if (got && first) strcpy(first, got[0].text);
    free(got);
    return count;
}
static void reset(void) { memset(files, 0, sizeof(files)); writeCap = -1; writesBeforeFail = -1; failCloseOn = -1; closes = 0; failOpenName = NULL; }
int main(void)
{
    char first[64];

    /* baseline: a save is complete and leaves no staging file */
    reset();
    make(2, "Old");
    assert(favWriteFile(recs, 2) == 1);
    assert(load(first) == 2 && !strcmp(first, "Old 0"));
    assert(lookup("mc0:OPL/favourites.bin.new", 0) == NULL);

    /* partial_writes_accumulate: a device that writes 3 bytes at a time still saves everything */
    writeCap = 3;
    make(3, "New");
    assert(favWriteFile(recs, 3) == 1);
    writeCap = -1;
    assert(load(first) == 3 && !strcmp(first, "New 0"));

    /* staging_fails: no progress while writing .new -> failure, previous list untouched */
    make(2, "Old");
    assert(favWriteFile(recs, 2) == 1);
    make(3, "Lost");
    writesBeforeFail = 0;
    assert(favWriteFile(recs, 3) == 0);
    writesBeforeFail = -1;
    assert(load(first) == 2 && !strcmp(first, "Old 0"));
    assert(lookup("mc0:OPL/favourites.bin.new", 0) == NULL);

    /* close_failure_reported: a failed close is a failed save */
    closes = 0;
    failCloseOn = 0; /* the staging file's close */
    assert(favWriteFile(recs, 3) == 0);
    failCloseOn = -1;
    assert(load(first) == 2 && !strcmp(first, "Old 0"));

    /* in_place_rewrite_fails: favourites.bin is cut short, but the complete new list survives in
       .new and the next read takes it -- the user never ends up with a truncated list */
    make(3, "Wanted");
    writesBeforeFail = 1; /* .new written whole in one call, then the in-place write fails */
    assert(favWriteFile(recs, 3) == 0);
    writesBeforeFail = -1;
    assert(lookup("mc0:OPL/favourites.bin", 0)->len == 0);
    assert(load(first) == 3 && !strcmp(first, "Wanted 0"));

    /* retry_cannot_restore: the complete .new is the only complete list. A save that cannot even
       put it back into favourites.bin must leave it alone, not truncate it while staging. */
    make(2, "Lost");
    writesBeforeFail = 0;
    assert(favWriteFile(recs, 2) == 0);
    writesBeforeFail = -1;
    assert(load(first) == 3 && !strcmp(first, "Wanted 0"));

    /* retry_staging_fails: the complete .new goes back into favourites.bin first, so a staging
       failure afterwards still leaves the last complete list */
    writesBeforeFail = 1; /* the restore is written whole, then staging the new list fails */
    assert(favWriteFile(recs, 2) == 0);
    writesBeforeFail = -1;
    assert(lookup("mc0:OPL/favourites.bin.new", 0) == NULL);
    assert(load(first) == 3 && !strcmp(first, "Wanted 0"));

    /* the next successful save cleans up the staging copy */
    make(1, "After");
    assert(favWriteFile(recs, 1) == 1);
    assert(lookup("mc0:OPL/favourites.bin.new", 0) == NULL && load(first) == 1);

    /* interrupted_staging: a half-written .new (power lost while staging) is ignored */
    {
        mfile_t *n = lookup("mc0:OPL/favourites.bin.new", 1);
        mfile_t *m = lookup("mc0:OPL/favourites.bin", 0);
        memcpy(n->data, m->data, 8); /* header claims records that never arrived */
        n->data[6] = 2;
        n->len = 8;
        assert(load(first) == 1 && !strcmp(first, "After 0"));
    }

    /* empty_list_staged: removing the last favourite stages a header-only list, which wins */
    reset();
    make(2, "Old");
    assert(favWriteFile(recs, 2) == 1);
    writesBeforeFail = 1;
    assert(favWriteFile(recs, 0) == 0);
    writesBeforeFail = -1;
    assert(load(first) == 0);

    puts("ok");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "fav.c"
    exe = Path(tmp) / "fav.exe"
    src.write_text(harness + source + tests, encoding="utf-8")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wno-unused-function", str(src), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: Favorites saves never leave a truncated list")
