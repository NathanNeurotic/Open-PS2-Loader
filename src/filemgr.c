/*
  Licenced under Academic Free License version 3.0
  Review Open PS2 Loader README & LICENSE files for further details.
*/

// File Manager file operations, after RIPPS2's Memory Files browser (akilluminati47/RIPPS2, ripps2files.c,
// builds 91-125). Plain file I/O only, so the host test runs it on a real folder; the dialog is guifilemgr.c.
//
// Kept from RIPPS2's hardware findings:
// - A memory card is opened and made in mcman's own form, "mc0:SAVE/FILE" (no slash after the colon).
// - The first access after a card is detected answers "changed card"; asking again is how every PS2 program
//   deals with it, so card opens and folder makes are tried up to four times.
// - Whether something is there is found by opening it, not stat(): on a card stat() says yes for a path that
//   is not there.
// - A write may take only part of a block; the rest goes again, and a write that takes nothing means full.
// - A copied file is read back for its size before it counts, and removed if it is short.
// - Sizes are 64-bit (a file over 2 GB failed its own size check), and a file over 4 GB is refused before it
//   starts on a FAT drive.
//
// Different from RIPPS2: a name already in the target folder is refused instead of merged or replaced, so a
// paste never changes a file that was there; a move removes its source only once the whole copy is made; a
// folder is never copied or moved into itself.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>

#ifndef FILEMGR_HOST_TEST
#include <ps2sdkapi.h> // lseek64
#include <delaythread.h>
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h>       // fileXioDevctl: a BDM drive's format and free space
#include "include/vmc_alloc.h" // BDM_DEVCTL_VOLINFO
#endif

#include "include/filemgr.h"

#define FM_PATH 320
#define FM_BUF  (64 * 1024)

static int fmErr;
static unsigned long long fmDone, fmTotal; // a copy's progress
static fm_progress_t fmProgress;

int fmError(void)
{
    return fmErr;
}

static int fmFail(int err)
{
    fmErr = err;
    return 0;
}

static void fmPause(void)
{
#ifndef FILEMGR_HOST_TEST
    DelayThread(50 * 1000);
#endif
}

static long long fmSeekEnd(int fd)
{
#ifndef FILEMGR_HOST_TEST
    long long size = lseek64(fd, 0, SEEK_END);
    lseek64(fd, 0, SEEK_SET);
#else
    long long size = lseek(fd, 0, SEEK_END);
    lseek(fd, 0, SEEK_SET);
#endif
    return size;
}

static int fmIsMc(const char *path)
{
    return !strncmp(path, "mc", 2) && (path[2] == '0' || path[2] == '1') && path[3] == ':';
}

// mcman's own form of a card path: "mc0:/A/B" -> "mc0:A/B"; every other path as it is
static const char *fmDevPath(const char *path, char *buf, int size)
{
    if (fmIsMc(path) && path[4] == '/' && path[5] != '\0') {
        snprintf(buf, size, "%.4s%s", path, path + 5);
        return buf;
    }
    return path;
}

char fmSep(const char *path)
{
    return !strncmp(path, "smb", 3) ? '\\' : '/';
}

int fmJoin(char *out, int size, const char *dir, const char *name)
{
    int n = strlen(dir), r;
    char sep = fmSep(dir);

    if (n > 0 && (dir[n - 1] == '/' || dir[n - 1] == '\\' || dir[n - 1] == ':'))
        r = snprintf(out, size, "%s%s", dir, name);
    else
        r = snprintf(out, size, "%s%c%s", dir, sep, name);
    return r >= 0 && r < size;
}

int fmParent(char *out, int size, const char *path)
{
    const char *colon = strchr(path, ':'), *rest, *last = NULL, *p;
    int lead, end, n;

    rest = colon != NULL ? colon + 1 : path; // a path with no device (the host test's) has "/" for its root
    lead = (*rest == '/' || *rest == '\\');  // "mass0:/A" has one, "smb0:A" may not
    end = strlen(path);
    while (end > (int)(rest - path) + lead && (path[end - 1] == '/' || path[end - 1] == '\\'))
        end--; // "mass0:/A/" is "mass0:/A"
    if (end <= (int)(rest - path) + lead)
        return 0; // already the device root
    for (p = rest + lead; p < path + end; p++)
        if (*p == '/' || *p == '\\')
            last = p;
    n = last != NULL ? (int)(last - path) : (int)(rest - path) + lead; // the root keeps its separator
    if (n + 2 > size)
        return 0;
    memcpy(out, path, n);
    out[n] = '\0';
    if (last == NULL && !lead && fmIsMc(path)) // a card root is "mc0:/"
        strcat(out, "/");
    return 1;
}

const char *fmBaseName(const char *path)
{
    const char *p, *base = path;
    for (p = path; *p != '\0'; p++)
        if ((*p == '/' || *p == '\\' || *p == ':') && p[1] != '\0')
            base = p + 1;
    return base;
}

int fmNameOk(const char *name)
{
    int n = strlen(name);
    if (n < 1 || n >= FM_NAME || !strcmp(name, ".") || !strcmp(name, ".."))
        return 0;
    return strpbrk(name, "/\\:") == NULL;
}

int fmExists(const char *path)
{
    char buf[FM_PATH];
    const char *p = fmDevPath(path, buf, sizeof(buf));
    int fd = open(p, O_RDONLY);
    DIR *d;

    if (fd >= 0) {
        close(fd);
        return 1;
    }
    if ((d = opendir(path)) != NULL) {
        closedir(d);
        return 1;
    }
    return 0;
}

static int fmIsDir(const char *dir, const char *name, unsigned long long *size)
{
    char path[FM_PATH];
    struct stat st;

    *size = 0;
    if (!fmJoin(path, sizeof(path), dir, name))
        return 0;
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return 1;
        *size = (unsigned long long)st.st_size;
        return 0;
    }
    return 0;
}

static int fmCompare(const void *a, const void *b)
{
    const fm_entry_t *x = (const fm_entry_t *)a, *y = (const fm_entry_t *)b;
    if (x->isDir != y->isDir)
        return x->isDir ? -1 : 1;
    return strcasecmp(x->name, y->name);
}

int fmList(const char *dir, fm_entry_t *out, int max)
{
    DIR *d = opendir(dir);
    struct dirent *de;
    int n = 0;

    if (d == NULL)
        return -1;
    while (n < max && (de = readdir(d)) != NULL) {
        if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, "..") || strlen(de->d_name) >= FM_NAME)
            continue;
        snprintf(out[n].name, FM_NAME, "%.127s", de->d_name);
        out[n].isDir = fmIsDir(dir, de->d_name, &out[n].size);
#ifdef DT_DIR
        if (!out[n].isDir && out[n].size == 0 && de->d_type == DT_DIR)
            out[n].isDir = 1;
#endif
        n++;
    }
    closedir(d);
    qsort(out, n, sizeof(out[0]), fmCompare);
    return n;
}

// A folder's entries on the heap, for the walks below; NULL (and *count 0) for an empty or unreadable one
static fm_entry_t *fmChildren(const char *dir, int *count)
{
    int cap = 64, n;
    fm_entry_t *list;

    for (;;) {
        if ((list = malloc(cap * sizeof(fm_entry_t))) == NULL) {
            *count = -1;
            return NULL;
        }
        n = fmList(dir, list, cap);
        if (n < cap || cap >= 65536)
            break;
        free(list);
        cap *= 4;
    }
    *count = n;
    return list;
}

static unsigned long long fmTreeWalk(const char *path, int isDir, int depth, int *files)
{
    struct stat st;
    char child[FM_PATH];
    unsigned long long total = 0;
    fm_entry_t *kids;
    int n, i;

    if (!isDir) {
        (*files)++;
        return stat(path, &st) == 0 ? (unsigned long long)st.st_size : 0;
    }
    if (depth > FM_DEPTH || (kids = fmChildren(path, &n)) == NULL)
        return 0;
    for (i = 0; i < n; i++) {
        if (!fmJoin(child, sizeof(child), path, kids[i].name))
            continue;
        if (kids[i].isDir)
            total += fmTreeWalk(child, 1, depth + 1, files);
        else {
            (*files)++;
            total += kids[i].size;
        }
    }
    free(kids);
    return total;
}

unsigned long long fmTreeSize(const char *path, int isDir, int *count)
{
    int files = 0;
    unsigned long long total = fmTreeWalk(path, isDir, 0, &files);
    if (count != NULL)
        *count = files;
    return total;
}

// The drive's room for a file this big: a FAT drive takes nothing over 4 GB, and none takes more than it has
static int fmRoomFor(const char *dstDir, long long size)
{
#ifndef FILEMGR_HOST_TEST
    unsigned int o[4];
    char dev[16];
    int n;

    if (strncmp(dstDir, "mass", 4) != 0 || size <= 0)
        return 1;
    for (n = 0; dstDir[n] != '\0' && dstDir[n] != ':' && n < (int)sizeof(dev) - 2; n++)
        dev[n] = dstDir[n];
    dev[n++] = ':';
    dev[n] = '\0';
    memset(o, 0, sizeof(o));
    if (fileXioDevctl(dev, BDM_DEVCTL_VOLINFO, NULL, 0, o, sizeof(o)) != 0 || o[3] < 1 || o[3] > 4)
        return 1; // the driver does not say: let the write find out
    if (o[3] != 4 && size > 0xFFFFFFFFLL)
        return 0;
    if ((unsigned long long)o[0] * 1024ULL < (unsigned long long)size) // o[0]: free KB, o[3]: FatFs fs_type
        return 0;
#else
    (void)dstDir;
    (void)size;
#endif
    return 1;
}

static int fmCopyFile(const char *src, const char *dst, unsigned char *buf)
{
    char sbuf[FM_PATH], dbuf[FM_PATH];
    const char *s = fmDevPath(src, sbuf, sizeof(sbuf)), *d = fmDevPath(dst, dbuf, sizeof(dbuf));
    int in = -1, out = -1, r, tries, ok = 1;
    unsigned long long copied = 0;
    long long size;

    for (tries = 0; tries < 4 && (in = open(s, O_RDONLY)) < 0 && fmIsMc(src); tries++)
        fmPause();
    if (in < 0)
        return fmFail(FM_ERR_READ);
    size = fmSeekEnd(in);
    if (!fmRoomFor(dst, size)) {
        close(in);
        return fmFail(FM_ERR_WRITE);
    }
    // O_EXCL: never onto something that is there (the caller checked; this closes the gap)
    for (tries = 0; tries < 4 && (out = open(d, O_WRONLY | O_CREAT | O_EXCL, 0666)) < 0 && fmIsMc(dst); tries++)
        fmPause();
    if (out < 0) {
        close(in);
        return fmFail(fmExists(dst) ? FM_ERR_EXISTS : FM_ERR_WRITE);
    }
    while ((r = read(in, buf, FM_BUF)) > 0) {
        int off = 0, w = 0;
        while (off < r && (w = write(out, buf + off, r - off)) > 0)
            off += w;
        if (off < r) {
            fmErr = FM_ERR_WRITE;
            ok = 0;
            break;
        }
        copied += (unsigned long long)r;
        fmDone += (unsigned long long)r;
        if (fmProgress != NULL)
            fmProgress(fmBaseName(src), fmDone, fmTotal);
    }
    if (r < 0) {
        fmErr = FM_ERR_READ;
        ok = 0;
    }
    close(out);
    close(in);
    if (ok) { // read back for its size before it counts
        int chk = open(d, O_RDONLY);
        long long got = chk >= 0 ? fmSeekEnd(chk) : -1;
        if (chk >= 0)
            close(chk);
        if (got < 0 || (unsigned long long)got != copied || (size >= 0 && copied != (unsigned long long)size)) {
            fmErr = FM_ERR_WRITE;
            ok = 0;
        }
    }
    if (!ok)
        remove(dst);
    return ok;
}

static int fmMkdirDev(const char *path)
{
    char buf[FM_PATH];
    const char *p = fmDevPath(path, buf, sizeof(buf));
    int tries;

    for (tries = 0; tries < 4; tries++) {
        if (mkdir(p, 0777) == 0)
            return 1;
        if (!fmIsMc(path))
            break;
        fmPause(); // "changed card": ask again
    }
    return 0;
}

static int fmCopyTree(const char *src, const char *dst, int isDir, int depth, unsigned char *buf)
{
    char s[FM_PATH], d[FM_PATH];
    fm_entry_t *kids;
    int n, i, ok = 1;

    if (!isDir)
        return fmCopyFile(src, dst, buf);
    if (depth > FM_DEPTH)
        return fmFail(FM_ERR_DEEP);
    if (!fmMkdirDev(dst))
        return fmFail(fmExists(dst) ? FM_ERR_EXISTS : FM_ERR_WRITE);
    kids = fmChildren(src, &n);
    if (n < 0)
        return fmFail(FM_ERR_MEMORY);
    for (i = 0; i < n && ok; i++) {
        if (!fmJoin(s, sizeof(s), src, kids[i].name) || !fmJoin(d, sizeof(d), dst, kids[i].name))
            ok = fmFail(FM_ERR_NAME);
        else
            ok = fmCopyTree(s, d, kids[i].isDir, depth + 1, buf);
    }
    free(kids);
    return ok;
}

// 1 if dst is src or under it ("mass0:/A" and "mass0:/A/B", not "mass0:/AB")
static int fmUnder(const char *dst, const char *src)
{
    int n = strlen(src);
    if (strncasecmp(dst, src, n) != 0)
        return 0;
    return dst[n] == '\0' || dst[n] == '/' || dst[n] == '\\';
}

static int fmTarget(const char *src, int isDir, const char *dstDir, char *dst, int size)
{
    if (!fmJoin(dst, size, dstDir, fmBaseName(src)))
        return fmFail(FM_ERR_NAME);
    if (isDir && fmUnder(dst, src))
        return fmFail(FM_ERR_INSIDE);
    if (fmExists(dst))
        return fmFail(FM_ERR_EXISTS);
    return 1;
}

static int fmCopyTo(const char *src, int isDir, const char *dst, fm_progress_t progress)
{
    unsigned char *buf;
    int ok;

    if ((buf = malloc(FM_BUF)) == NULL)
        return fmFail(FM_ERR_MEMORY);
    fmDone = 0;
    fmTotal = fmTreeSize(src, isDir, NULL);
    fmProgress = progress;
    ok = fmCopyTree(src, dst, isDir, 0, buf);
    fmProgress = NULL;
    free(buf);
    return ok;
}

int fmCopy(const char *src, int isDir, const char *dstDir, fm_progress_t progress)
{
    char dst[FM_PATH];

    fmErr = FM_OK;
    if (!fmTarget(src, isDir, dstDir, dst, sizeof(dst)))
        return 0;
    return fmCopyTo(src, isDir, dst, progress);
}

static int fmRemove(const char *path, int isDir)
{
    int tries;
    for (tries = 0; tries < 4; tries++) {
        if ((isDir ? rmdir(path) : remove(path)) == 0 && !fmExists(path))
            return 1;
        fmPause(); // a card can refuse a removal straight after the same files were read
    }
    return fmFail(FM_ERR_DELETE);
}

static int fmDeleteTree(const char *path, int isDir, int depth)
{
    char child[FM_PATH];
    fm_entry_t *kids;
    int n, i, ok = 1;

    if (!isDir)
        return fmRemove(path, 0);
    if (depth > FM_DEPTH)
        return fmFail(FM_ERR_DEEP);
    kids = fmChildren(path, &n);
    if (n < 0)
        return fmFail(FM_ERR_MEMORY);
    for (i = 0; i < n; i++) {
        if (!fmJoin(child, sizeof(child), path, kids[i].name) || !fmDeleteTree(child, kids[i].isDir, depth + 1))
            ok = 0;
    }
    free(kids);
    return ok && fmRemove(path, 1);
}

int fmDelete(const char *path, int isDir)
{
    char parent[FM_PATH];

    fmErr = FM_OK;
    if (fmParent(parent, sizeof(parent), path) == 0)
        return fmFail(FM_ERR_NAME); // never a device root
    return fmDeleteTree(path, isDir, 0);
}

// Two paths on the same device ("mass0:" and "mass0:"), where a rename can move between folders
static int fmSameDevice(const char *a, const char *b)
{
    const char *ca = strchr(a, ':'), *cb = strchr(b, ':');
    return ca != NULL && cb != NULL && ca - a == cb - b && !strncasecmp(a, b, ca - a);
}

static int fmRenameDev(const char *from, const char *to)
{
    char fbuf[FM_PATH], tbuf[FM_PATH];
    return rename(fmDevPath(from, fbuf, sizeof(fbuf)), fmDevPath(to, tbuf, sizeof(tbuf))) == 0 && fmExists(to) &&
           !fmExists(from);
}

// A move as a copy, then the source removed only once the whole copy is made; a failed copy is taken back
static int fmCopyThenDelete(const char *src, int isDir, const char *dst, fm_progress_t progress)
{
    if (!fmCopyTo(src, isDir, dst, progress)) {
        int err = fmErr;
        fmDeleteTree(dst, isDir, 0);
        return fmFail(err);
    }
    return fmDeleteTree(src, isDir, 0);
}

int fmMove(const char *src, int isDir, const char *dstDir, fm_progress_t progress)
{
    char dst[FM_PATH];

    fmErr = FM_OK;
    if (!fmTarget(src, isDir, dstDir, dst, sizeof(dst)))
        return 0;
    if (fmSameDevice(src, dst) && fmRenameDev(src, dst))
        return 1;
    return fmCopyThenDelete(src, isDir, dst, progress);
}

int fmRename(const char *path, const char *newName)
{
    char dir[FM_PATH], dst[FM_PATH];
    struct stat st;
    int isDir;

    fmErr = FM_OK;
    if (!fmNameOk(newName))
        return fmFail(FM_ERR_NAME);
    if (!fmParent(dir, sizeof(dir), path) || !fmJoin(dst, sizeof(dst), dir, newName))
        return fmFail(FM_ERR_NAME);
    if (!strcmp(fmBaseName(path), newName))
        return 1;
    if (fmExists(dst) && strcasecmp(fmBaseName(path), newName) != 0)
        return fmFail(FM_ERR_EXISTS);
    if (fmRenameDev(path, dst))
        return 1;
    // a device that cannot rename (or only a file): copy under the new name, then remove the old one
    isDir = stat(path, &st) == 0 && S_ISDIR(st.st_mode);
    if (fmExists(dst))
        return fmFail(FM_ERR_EXISTS); // only the case of the name changed and the device kept it
    return fmCopyThenDelete(path, isDir, dst, NULL);
}

int fmMakeDir(const char *dir, const char *name)
{
    char path[FM_PATH];

    fmErr = FM_OK;
    if (!fmNameOk(name) || !fmJoin(path, sizeof(path), dir, name))
        return fmFail(FM_ERR_NAME);
    if (fmExists(path))
        return fmFail(FM_ERR_EXISTS);
    if (!fmMkdirDev(path))
        return fmFail(FM_ERR_WRITE);
    return 1;
}

void fmSizeText(unsigned long long bytes, char *out, int size)
{
    unsigned long long kb = (bytes + 1023) / 1024;
    if (kb >= 1024ULL * 1024)
        snprintf(out, size, "%u.%u GB", (unsigned)(kb >> 20), (unsigned)((kb & ((1 << 20) - 1)) * 10 >> 20));
    else if (kb >= 1024)
        snprintf(out, size, "%u.%u MB", (unsigned)(kb >> 10), (unsigned)((kb & 1023) * 10 >> 10));
    else
        snprintf(out, size, "%u KB", (unsigned)kb);
}
