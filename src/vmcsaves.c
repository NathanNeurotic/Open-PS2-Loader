/*
  Licenced under Academic Free License version 3.0
  Review Open PS2 Loader README & LICENSE files for further details.
*/

// Saves inside a VMC image, as if the card were a folder (RIPPS2 builds 98-115, akilluminati47, ripps2saves.c):
// list them with their titles, copy one out to a folder of its own, copy one back in, delete one.
//
// The image is edited in place with open/lseek/read/write: its size and its place on the drive never
// change, so a native VMC stays mappable. An image with the ECC spare (PCSX2's .ps2) is read only here.
// Writes go in the order a power cut can survive: a new save's data and its folder first, the FAT next,
// the root entry that makes it appear last; a delete hides the entry before it frees the clusters. At
// worst a cut leaves clusters marked used that nothing names, never a save that names freed ones.
//
// Fixed over RIPPS2: ".." of a new save is written the way mcman and genvmc write it (hidden, cluster
// 0); half-width katakana in a title no longer swallow the byte after them; an allocation that comes
// back short is checked, not trusted.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <time.h>
#include <sys/stat.h>

#include "include/vmcsaves.h"

#define MC_FILE   0x0010
#define MC_DIR    0x0020
#define MC_EXISTS 0x8000
#define MODE_DIR  0x8427 // exists, 0400, folder, x, w, r
#define MODE_UP   0xA426 // "..": as above, hidden, not readable (mcman, genvmc)
#define MODE_FILE 0x8497 // exists, 0400, closed, file, x, w, r

#define FAT_USED 0x80000000u
#define FAT_FREE 0x7FFFFFFFu
#define FAT_END  0xFFFFFFFFu

#define ENT_SIZE      512
#define DIR_MAX       4096              // entries a folder may claim; a damaged card claims anything
#define SAVE_FILES    64                // files in one save
#define SAVE_MAX_SIZE (8 * 1024 * 1024) // a whole 8 MB card
#define ICON_SYS_HEAD (0xC0 + 68)       // to the end of the title

typedef unsigned char u8_t;
typedef unsigned int u32_t;

typedef struct
{
    unsigned short mode;
    unsigned short unused;
    u32_t length; // a file's size; a folder's entry count
    u8_t created[8];
    u32_t cluster; // first cluster, relative to the allocatable area
    u32_t dirEntry;
    u8_t modified[8];
    u32_t attr;
    u8_t unused2[28];
    char name[32];
    u8_t unused3[416];
} __attribute__((packed)) vs_ent_t;

typedef char vs_ent_is_512[sizeof(vs_ent_t) == ENT_SIZE ? 1 : -1];

typedef struct
{
    char name[33];
    u32_t size;
    u8_t created[8], modified[8];
    u8_t *data;
} vs_file_t;

typedef struct
{
    char name[33];
    u8_t created[8], modified[8];
    int count;
    vs_file_t files[SAVE_FILES];
} vs_save_t;

typedef struct
{
    int fd, ecc;
    int raw, pageLen, ppc, csize; // bytes per stored page (512, or 528 with ECC), page, pages per cluster, cluster
    u32_t clusters, alloc, allocEnd, root;
    u32_t ifc[32];
    u32_t *fat;    // one entry per allocatable cluster
    u32_t *fatAbs; // where each FAT cluster lives
    u8_t *fatDirty;
    int fatClusters, epc; // FAT clusters, entries per cluster
    u8_t *cl;             // a cluster's worth of scratch
} vs_vmc_t;

static int vsErr;

int vmcSavesError(void)
{
    return vsErr;
}

static int vsFail(int err)
{
    vsErr = err;
    return 0;
}

static u32_t vsU32(const u8_t *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((u32_t)p[3] << 24);
}

// A card's date stamp (sceMcStDateTime): reserved, sec, min, hour, day, month, year (LE u16), in Japan time,
// as the console's clock and every card keep it
static void vsStamp(time_t t, u8_t out[8])
{
    time_t jst = t + 9 * 60 * 60;
    struct tm *tm = gmtime(&jst);

    memset(out, 0, 8);
    if (tm == NULL)
        return;
    out[1] = tm->tm_sec;
    out[2] = tm->tm_min;
    out[3] = tm->tm_hour;
    out[4] = tm->tm_mday;
    out[5] = tm->tm_mon + 1;
    out[6] = (tm->tm_year + 1900) & 0xFF;
    out[7] = (tm->tm_year + 1900) >> 8;
}

static void vsSaveFree(vs_save_t *s)
{
    int i;

    for (i = 0; i < s->count; i++)
        free(s->files[i].data);
    s->count = 0;
}

static int vsReadAll(int fd, u8_t *buf, u32_t size)
{
    u32_t done = 0;

    while (done < size) {
        int r = read(fd, buf + done, size - done > 0x10000 ? 0x10000 : size - done);
        if (r <= 0)
            return 0;
        done += r;
    }
    return 1;
}

static int vsWriteAll(int fd, const u8_t *buf, u32_t size)
{
    u32_t done = 0;

    while (done < size) {
        int w = write(fd, buf + done, size - done > 0x10000 ? 0x10000 : size - done);
        if (w <= 0)
            return 0;
        done += w;
    }
    return 1;
}

// ---- the card image ----

static int vsIo(vs_vmc_t *v, u32_t abs, u8_t *buf, int writing)
{
    int p;

    for (p = 0; p < v->ppc; p++) {
        if (lseek(v->fd, (off_t)(((long long)abs * v->ppc + p) * v->raw), SEEK_SET) < 0)
            return 0;
        if (writing ? write(v->fd, buf + p * v->pageLen, v->pageLen) != v->pageLen : read(v->fd, buf + p * v->pageLen, v->pageLen) != v->pageLen)
            return 0;
    }
    return 1;
}

static void vsClose(vs_vmc_t *v)
{
    if (v->fd >= 0)
        close(v->fd);
    free(v->fat);
    free(v->fatAbs);
    free(v->fatDirty);
    free(v->cl);
    memset(v, 0, sizeof(*v));
    v->fd = -1;
}

static int vsOpen(vs_vmc_t *v, const char *image, int forWrite)
{
    u8_t sb[ENT_SIZE];
    u8_t *ind;
    int k, lastInd = -1;
    long long size, pages;

    memset(v, 0, sizeof(*v));
    v->fd = open(image, forWrite ? O_RDWR : O_RDONLY);
    if (v->fd < 0)
        return vsFail(VMCSAVES_ERR_OPEN);
    if (read(v->fd, sb, sizeof(sb)) != (int)sizeof(sb) || memcmp(sb, "Sony PS2 Memory Card Format ", 28) != 0) {
        vsClose(v);
        return vsFail(VMCSAVES_ERR_NOT_CARD);
    }
    v->pageLen = sb[0x28] | (sb[0x29] << 8);
    v->ppc = sb[0x2A] | (sb[0x2B] << 8);
    v->clusters = vsU32(sb + 0x30);
    v->alloc = vsU32(sb + 0x34);
    v->allocEnd = vsU32(sb + 0x38);
    v->root = vsU32(sb + 0x3C);
    for (k = 0; k < 32; k++)
        v->ifc[k] = vsU32(sb + 0x50 + k * 4);
    v->csize = v->pageLen * v->ppc;
    if (v->pageLen != 512 || v->ppc < 1 || v->ppc > 16 || v->csize > 8192 || v->allocEnd == 0 || v->allocEnd > 0x100000 ||
        v->root >= v->allocEnd) {
        vsClose(v);
        return vsFail(VMCSAVES_ERR_NOT_CARD);
    }
    size = lseek(v->fd, 0, SEEK_END);
    pages = (long long)v->clusters * v->ppc;
    if (size >= pages * (v->pageLen + 16)) { // the spare area of every page: ECC (PCSX2's .ps2)
        v->raw = v->pageLen + 16;
        v->ecc = 1;
    } else if (size >= pages * v->pageLen)
        v->raw = v->pageLen;
    else {
        vsClose(v);
        return vsFail(VMCSAVES_ERR_NOT_CARD);
    }
    if (forWrite && v->ecc) {
        vsClose(v);
        return vsFail(VMCSAVES_ERR_READ_ONLY);
    }

    v->epc = v->csize / 4;
    v->fatClusters = (v->allocEnd + v->epc - 1) / v->epc;
    v->fat = (u32_t *)malloc(v->fatClusters * v->epc * 4);
    v->fatAbs = (u32_t *)malloc(v->fatClusters * 4);
    v->fatDirty = (u8_t *)calloc(v->fatClusters, 1);
    v->cl = (u8_t *)malloc(v->csize);
    ind = (u8_t *)malloc(v->csize);
    if (v->fat == NULL || v->fatAbs == NULL || v->fatDirty == NULL || v->cl == NULL || ind == NULL) {
        free(ind);
        vsClose(v);
        return vsFail(VMCSAVES_ERR_MEMORY);
    }
    // the indirect FAT names the FAT's clusters; the FAT chains the allocatable ones
    for (k = 0; k < v->fatClusters; k++) {
        int i = k / v->epc;
        if (i >= 32 || (i != lastInd && !vsIo(v, v->ifc[i], ind, 0))) {
            free(ind);
            vsClose(v);
            return vsFail(VMCSAVES_ERR_READ);
        }
        lastInd = i;
        v->fatAbs[k] = vsU32(ind + (k % v->epc) * 4);
        if (v->fatAbs[k] >= v->clusters || !vsIo(v, v->fatAbs[k], (u8_t *)&v->fat[k * v->epc], 0)) {
            free(ind);
            vsClose(v);
            return vsFail(VMCSAVES_ERR_READ);
        }
    }
    free(ind);
    return 1;
}

static int vsFlushFat(vs_vmc_t *v)
{
    int k, ok = 1;

    for (k = 0; k < v->fatClusters; k++)
        if (v->fatDirty[k]) {
            if (!vsIo(v, v->fatAbs[k], (u8_t *)&v->fat[k * v->epc], 1))
                ok = 0;
            v->fatDirty[k] = 0;
        }
    return ok;
}

static u32_t vsNext(vs_vmc_t *v, u32_t c)
{
    u32_t e;

    if (c >= v->allocEnd)
        return FAT_END;
    e = v->fat[c];
    if (e == FAT_END || !(e & FAT_USED))
        return FAT_END;
    return e & ~FAT_USED;
}

static void vsSetFat(vs_vmc_t *v, u32_t c, u32_t value)
{
    v->fat[c] = value;
    v->fatDirty[c / v->epc] = 1;
}

// The n-th cluster of a chain, or FAT_END
static u32_t vsWalk(vs_vmc_t *v, u32_t c, int n)
{
    if (n > (int)v->allocEnd) // a chain cannot be longer than the card
        return FAT_END;
    while (n-- > 0 && c != FAT_END)
        c = vsNext(v, c);
    return c;
}

static int vsEnt(vs_vmc_t *v, u32_t dir, int index, vs_ent_t *e, int writing)
{
    int per = v->csize / ENT_SIZE;
    u32_t c = vsWalk(v, dir, index / per);

    if (c == FAT_END || c >= v->allocEnd || !vsIo(v, v->alloc + c, v->cl, 0))
        return 0;
    if (!writing) {
        memcpy(e, v->cl + (index % per) * ENT_SIZE, ENT_SIZE);
        return 1;
    }
    memcpy(v->cl + (index % per) * ENT_SIZE, e, ENT_SIZE);
    return vsIo(v, v->alloc + c, v->cl, 1);
}

static int vsDirLen(u32_t length)
{
    return length > DIR_MAX ? DIR_MAX : (int)length;
}

static int vsNameIs(const vs_ent_t *e, const char *name)
{
    return strlen(name) <= 32 && !strncmp(e->name, name, 32);
}

// A save folder in the card's root: its index there, or -1
static int vsFindSave(vs_vmc_t *v, const char *name, vs_ent_t *found)
{
    vs_ent_t dot, e;
    int i;

    if (!vsEnt(v, v->root, 0, &dot, 0))
        return -1;
    for (i = 2; i < vsDirLen(dot.length); i++)
        if (vsEnt(v, v->root, i, &e, 0) && (e.mode & MC_EXISTS) && (e.mode & MC_DIR) && vsNameIs(&e, name)) {
            if (found)
                *found = e;
            return i;
        }
    return -1;
}

static int vsReadChain(vs_vmc_t *v, u32_t c, u8_t *out, u32_t size)
{
    u32_t done = 0;

    if (size > v->allocEnd * (u32_t)v->csize)
        return 0; // bigger than the card: a damaged entry
    while (done < size) {
        u32_t n;
        if (c == FAT_END || c >= v->allocEnd || !vsIo(v, v->alloc + c, v->cl, 0))
            return 0;
        n = size - done > (u32_t)v->csize ? (u32_t)v->csize : size - done;
        memcpy(out + done, v->cl, n);
        done += n;
        c = vsNext(v, c);
    }
    return 1;
}

static u32_t vsFreeCount(vs_vmc_t *v)
{
    u32_t c, n = 0;

    for (c = 0; c < v->allocEnd; c++)
        if (!(v->fat[c] & FAT_USED))
            n++;
    return n;
}

// A chain of n new clusters (n > 0): its first cluster, or FAT_END when the card is full
static u32_t vsAllocChain(vs_vmc_t *v, int n, u32_t *hint)
{
    u32_t first = FAT_END, prev = FAT_END, c;

    for (c = *hint; c < v->allocEnd && n > 0; c++) {
        if (v->fat[c] & FAT_USED)
            continue;
        vsSetFat(v, c, FAT_END);
        if (prev != FAT_END)
            vsSetFat(v, prev, FAT_USED | c);
        else
            first = c;
        prev = c;
        n--;
    }
    *hint = c;
    return n == 0 ? first : FAT_END;
}

static void vsFreeChain(vs_vmc_t *v, u32_t c)
{
    u32_t steps = 0;

    while (c != FAT_END && c < v->allocEnd && steps++ < v->allocEnd) {
        u32_t next = vsNext(v, c);
        vsSetFat(v, c, FAT_FREE);
        c = next;
    }
}

// Up to size bytes of a file in the folder whose entry is dir: the bytes read, or -1
static int vsReadIn(vs_vmc_t *v, const vs_ent_t *dir, const char *name, void *buf, int size)
{
    vs_ent_t e;
    int i;

    for (i = 2; i < vsDirLen(dir->length); i++)
        if (vsEnt(v, dir->cluster, i, &e, 0) && (e.mode & MC_EXISTS) && (e.mode & MC_FILE) && vsNameIs(&e, name)) {
            u32_t n = e.length < (u32_t)size ? e.length : (u32_t)size;
            u32_t c = e.cluster, done = 0;
            while (done < n) { // only the clusters the bytes asked for
                u32_t k = n - done > (u32_t)v->csize ? (u32_t)v->csize : n - done;
                if (c == FAT_END || c >= v->allocEnd || !vsIo(v, v->alloc + c, v->cl, 0))
                    return -1;
                memcpy((u8_t *)buf + done, v->cl, k);
                done += k;
                c = vsNext(v, c);
            }
            return n;
        }
    return -1;
}

static int vsLoadVmc(vs_save_t *s, const char *image, const char *name)
{
    vs_vmc_t v;
    vs_ent_t dir, e;
    int i;
    u32_t total = 0;

    if (!vsOpen(&v, image, 0))
        return 0;
    if (vsFindSave(&v, name, &dir) < 0) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_NO_SAVE);
    }
    snprintf(s->name, sizeof(s->name), "%.32s", dir.name);
    memcpy(s->created, dir.created, 8);
    memcpy(s->modified, dir.modified, 8);
    for (i = 2; i < vsDirLen(dir.length); i++) {
        vs_file_t *f;
        if (!vsEnt(&v, dir.cluster, i, &e, 0)) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_READ);
        }
        if (!(e.mode & MC_EXISTS) || !(e.mode & MC_FILE))
            continue;
        if (s->count >= SAVE_FILES) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_TOO_BIG);
        }
        f = &s->files[s->count];
        snprintf(f->name, sizeof(f->name), "%.32s", e.name);
        f->size = e.length;
        memcpy(f->created, e.created, 8);
        memcpy(f->modified, e.modified, 8);
        total += f->size;
        if (f->size > SAVE_MAX_SIZE || total > SAVE_MAX_SIZE) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_TOO_BIG);
        }
        f->data = (u8_t *)malloc(f->size ? f->size : 1);
        if (f->data == NULL) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_MEMORY);
        }
        s->count++;
        if (f->size && !vsReadChain(&v, e.cluster, f->data, f->size)) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_READ);
        }
    }
    vsClose(&v);
    return 1;
}

// The save into the card's root as a new folder; -1 when one of that name is already there
static int vsWriteVmc(const vs_save_t *s, const char *image)
{
    vs_vmc_t v;
    vs_ent_t rootDot, e, *d;
    int i, slot = -1, per, dirEnts = 2 + s->count, dirClusters, need, grow = 0, ok;
    u32_t hint = 0, dirFirst, c;
    u32_t first[SAVE_FILES];
    u8_t *dirBuf;

    if (!vsOpen(&v, image, 1))
        return 0;
    if (vsFindSave(&v, s->name, NULL) >= 0) {
        vsClose(&v);
        vsErr = VMCSAVES_ERR_EXISTS;
        return -1;
    }
    if (!vsEnt(&v, v.root, 0, &rootDot, 0)) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_READ);
    }
    // a root slot: the first one a deleted save left, else one more on the end
    for (i = 2; i < vsDirLen(rootDot.length) && slot < 0; i++)
        if (vsEnt(&v, v.root, i, &e, 0) && !(e.mode & MC_EXISTS))
            slot = i;
    per = v.csize / ENT_SIZE;
    if (slot < 0) {
        if (rootDot.length >= DIR_MAX) {
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_NO_ROOM);
        }
        slot = rootDot.length;
        grow = slot % per == 0; // the root's last cluster is full
    }

    dirClusters = (dirEnts + per - 1) / per;
    need = dirClusters + grow;
    for (i = 0; i < s->count; i++)
        need += (s->files[i].size + v.csize - 1) / v.csize;
    if ((u32_t)need > vsFreeCount(&v)) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_NO_ROOM);
    }

    // the files' data
    for (i = 0; i < s->count; i++) {
        const vs_file_t *f = &s->files[i];
        int n = (f->size + v.csize - 1) / v.csize, k;
        first[i] = FAT_END;
        if (n == 0)
            continue;
        first[i] = vsAllocChain(&v, n, &hint);
        if (first[i] == FAT_END) {
            vsClose(&v); // nothing written names these clusters, and the FAT on the card is untouched
            return vsFail(VMCSAVES_ERR_NO_ROOM);
        }
        for (k = 0, c = first[i]; k < n; k++, c = vsNext(&v, c)) {
            u32_t off = k * v.csize, len = f->size - off > (u32_t)v.csize ? (u32_t)v.csize : f->size - off;
            memset(v.cl, 0xFF, v.csize);
            memcpy(v.cl, f->data + off, len);
            if (!vsIo(&v, v.alloc + c, v.cl, 1)) {
                vsClose(&v);
                return vsFail(VMCSAVES_ERR_WRITE);
            }
        }
    }

    // the save's folder: ".", "..", then its files (mcman's layout for a new folder)
    dirFirst = vsAllocChain(&v, dirClusters, &hint);
    dirBuf = (u8_t *)calloc(dirClusters, v.csize);
    if (dirFirst == FAT_END || dirBuf == NULL) {
        free(dirBuf);
        vsClose(&v);
        return vsFail(dirBuf == NULL ? VMCSAVES_ERR_MEMORY : VMCSAVES_ERR_NO_ROOM);
    }
    d = (vs_ent_t *)dirBuf;
    d[0].mode = MODE_DIR;
    memcpy(d[0].created, s->created, 8);
    memcpy(d[0].modified, s->modified, 8);
    d[0].cluster = v.root; // "." names the parent folder and this folder's place in it
    d[0].dirEntry = slot;
    strcpy(d[0].name, ".");
    d[1].mode = MODE_UP;
    memcpy(d[1].created, s->created, 8);
    memcpy(d[1].modified, s->modified, 8);
    strcpy(d[1].name, "..");
    for (i = 0; i < s->count; i++) {
        vs_ent_t *f = &d[2 + i];
        f->mode = MODE_FILE;
        f->length = s->files[i].size;
        memcpy(f->created, s->files[i].created, 8);
        memcpy(f->modified, s->files[i].modified, 8);
        f->cluster = first[i] == FAT_END ? 0 : first[i];
        strncpy(f->name, s->files[i].name, 32);
    }
    for (i = 0, c = dirFirst; i < dirClusters; i++, c = vsNext(&v, c))
        if (!vsIo(&v, v.alloc + c, dirBuf + i * v.csize, 1)) {
            free(dirBuf);
            vsClose(&v);
            return vsFail(VMCSAVES_ERR_WRITE);
        }
    free(dirBuf);

    // room in the root for one more entry
    if (grow) {
        u32_t last = v.root, add, steps = 0;
        while (vsNext(&v, last) != FAT_END && steps++ < v.allocEnd)
            last = vsNext(&v, last);
        add = vsAllocChain(&v, 1, &hint);
        memset(v.cl, 0, v.csize);
        if (add == FAT_END || !vsIo(&v, v.alloc + add, v.cl, 1)) {
            vsClose(&v);
            return vsFail(add == FAT_END ? VMCSAVES_ERR_NO_ROOM : VMCSAVES_ERR_WRITE);
        }
        vsSetFat(&v, last, FAT_USED | add);
    }
    if (!vsFlushFat(&v)) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_WRITE);
    }

    // and last, the save appears: its entry in the root, then the root's count
    memset(&e, 0, sizeof(e));
    e.mode = MODE_DIR;
    e.length = dirEnts;
    memcpy(e.created, s->created, 8);
    memcpy(e.modified, s->modified, 8);
    e.cluster = dirFirst;
    strncpy(e.name, s->name, 32);
    ok = vsEnt(&v, v.root, slot, &e, 1);
    if (ok && slot >= (int)rootDot.length) {
        rootDot.length = slot + 1;
        ok = vsEnt(&v, v.root, 0, &rootDot, 1);
    }
    vsClose(&v);
    return ok ? 1 : vsFail(VMCSAVES_ERR_WRITE);
}

// ---- a folder on the drive ----

static int vsLoadFolder(vs_save_t *s, const char *parent, const char *name)
{
    char dir[320], path[384];
    char(*list)[33];
    DIR *d;
    struct dirent *de;
    struct stat st;
    u32_t total = 0;
    int i, names = 0;

    if (strlen(name) > 32 || name[0] == '\0' || strchr(name, '/') != NULL)
        return vsFail(VMCSAVES_ERR_NAME);
    list = (char(*)[33])malloc(SAVE_FILES * 33);
    if (list == NULL)
        return vsFail(VMCSAVES_ERR_MEMORY);
    snprintf(dir, sizeof(dir), "%s%s/", parent, name);
    d = opendir(dir);
    if (d == NULL) {
        free(list);
        return vsFail(VMCSAVES_ERR_NO_SAVE);
    }
    // the names first, then each file
    while ((de = readdir(d)) != NULL) {
        if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, ".."))
            continue;
        if (snprintf(path, sizeof(path), "%s%s", dir, de->d_name) >= (int)sizeof(path))
            continue;
        if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
            continue; // a save holds files only
        if (names >= SAVE_FILES || strlen(de->d_name) > 32) {
            closedir(d);
            free(list);
            return vsFail(names >= SAVE_FILES ? VMCSAVES_ERR_TOO_BIG : VMCSAVES_ERR_NAME);
        }
        snprintf(list[names++], 33, "%.32s", de->d_name);
    }
    closedir(d);
    if (names == 0) {
        free(list);
        return vsFail(VMCSAVES_ERR_NO_SAVE);
    }
    snprintf(s->name, sizeof(s->name), "%s", name);
    vsStamp(time(NULL), s->created);
    memcpy(s->modified, s->created, 8);
    for (i = 0; i < names; i++) {
        vs_file_t *f = &s->files[s->count];
        int fd, len;
        snprintf(path, sizeof(path), "%s%s", dir, list[i]);
        fd = open(path, O_RDONLY);
        if (fd < 0) {
            free(list);
            return vsFail(VMCSAVES_ERR_READ);
        }
        len = lseek(fd, 0, SEEK_END);
        if (len < 0 || len > SAVE_MAX_SIZE || total + len > SAVE_MAX_SIZE || lseek(fd, 0, SEEK_SET) < 0) {
            close(fd);
            free(list);
            return vsFail(len < 0 ? VMCSAVES_ERR_READ : VMCSAVES_ERR_TOO_BIG);
        }
        snprintf(f->name, sizeof(f->name), "%s", list[i]);
        f->size = len;
        f->data = (u8_t *)malloc(len ? len : 1);
        if (f->data == NULL) {
            close(fd);
            free(list);
            return vsFail(VMCSAVES_ERR_MEMORY);
        }
        s->count++;
        total += len;
        if (stat(path, &st) == 0)
            vsStamp(st.st_mtime, f->modified);
        else
            memcpy(f->modified, s->created, 8);
        memcpy(f->created, f->modified, 8);
        if (!vsReadAll(fd, f->data, len)) {
            close(fd);
            free(list);
            return vsFail(VMCSAVES_ERR_READ);
        }
        close(fd);
    }
    free(list);
    return 1;
}

// A new folder <parent><name>/ holding the save; -1 when one of that name is already there. A folder that
// fails part way is left as far as it got (each file it did write is whole) and the error says so.
static int vsWriteFolder(const vs_save_t *s, const char *parent)
{
    char path[384];
    DIR *d;
    int i, fd;

    mkdir(parent, 0777); // the shared SAVES/ folder: made on the first export, there after
    snprintf(path, sizeof(path), "%s%s", parent, s->name);
    d = opendir(path);
    if (d != NULL) {
        closedir(d);
        vsErr = VMCSAVES_ERR_EXISTS;
        return -1;
    }
    if (mkdir(path, 0777) < 0)
        return vsFail(VMCSAVES_ERR_WRITE);
    for (i = 0; i < s->count; i++) {
        const vs_file_t *f = &s->files[i];
        int ok;
        snprintf(path, sizeof(path), "%s%s/%s", parent, s->name, f->name);
        fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd < 0)
            return vsFail(VMCSAVES_ERR_WRITE);
        ok = vsWriteAll(fd, f->data, f->size);
        close(fd);
        if (!ok) {
            unlink(path);
            return vsFail(VMCSAVES_ERR_WRITE);
        }
    }
    return 1;
}

// ---- titles ----

// Shift-JIS from an icon.sys title to plain ASCII: full-width letters, digits and common punctuation map
// across, everything else (kana, kanji) is dropped. lineBreak is the byte offset where the second line starts.
static void vsSjisToAscii(const u8_t *s, int len, int lineBreak, char *out, int size)
{
    int i = 0, o = 0, broke = 0;

    while (i < len && s[i] && o < size - 1) {
        unsigned int c = s[i], w;
        char a = 0;
        if (!broke && i >= lineBreak && lineBreak > 0) {
            broke = 1;
            if (o > 0 && out[o - 1] != ' ')
                out[o++] = ' ';
            if (o >= size - 1)
                break;
        }
        if (c < 0x80) {
            out[o++] = (char)c;
            i++;
            continue;
        }
        if (c >= 0xA1 && c <= 0xDF) { // half-width katakana: one byte
            i++;
            continue;
        }
        if (i + 1 >= len)
            break;
        w = (c << 8) | s[i + 1];
        i += 2;
        if (w >= 0x824F && w <= 0x8258)
            a = (char)('0' + (w - 0x824F));
        else if (w >= 0x8260 && w <= 0x8279)
            a = (char)('A' + (w - 0x8260));
        else if (w >= 0x8281 && w <= 0x829A)
            a = (char)('a' + (w - 0x8281));
        else
            switch (w) {
                case 0x8140:
                    a = ' ';
                    break;
                case 0x8143:
                    a = ',';
                    break;
                case 0x8144:
                    a = '.';
                    break;
                case 0x8146:
                    a = ':';
                    break;
                case 0x8147:
                    a = ';';
                    break;
                case 0x8148:
                    a = '?';
                    break;
                case 0x8149:
                    a = '!';
                    break;
                case 0x8151:
                    a = '_';
                    break;
                case 0x815B:
                case 0x815C:
                case 0x817C:
                    a = '-';
                    break;
                case 0x815E:
                    a = '/';
                    break;
                case 0x8160:
                    a = '~';
                    break;
                case 0x8166:
                    a = '\'';
                    break;
                case 0x8168:
                    a = '"';
                    break;
                case 0x8169:
                    a = '(';
                    break;
                case 0x816A:
                    a = ')';
                    break;
                case 0x817B:
                    a = '+';
                    break;
                case 0x8181:
                    a = '=';
                    break;
                case 0x8190:
                    a = '$';
                    break;
                case 0x8193:
                    a = '%';
                    break;
                case 0x8194:
                    a = '#';
                    break;
                case 0x8195:
                    a = '&';
                    break;
                default:
                    break;
            }
        if (a)
            out[o++] = a;
    }
    while (o > 0 && out[o - 1] == ' ')
        o--;
    out[o] = '\0';
}

void vmcSavesTitle(const unsigned char *iconSys, int size, char *out, int outSize)
{
    if (outSize <= 0)
        return;
    out[0] = '\0';
    if (iconSys != NULL && size >= ICON_SYS_HEAD && !memcmp(iconSys, "PS2D", 4))
        vsSjisToAscii(iconSys + 0xC0, 68, iconSys[6] | (iconSys[7] << 8), out, outSize);
}

// ---- the entry points ----

int vmcSavesProbe(const char *image)
{
    vs_vmc_t v;
    int ro;

    vsErr = VMCSAVES_OK;
    if (!vsOpen(&v, image, 0))
        return 0;
    ro = v.ecc;
    vsClose(&v);
    return ro ? 2 : 1;
}

int vmcSavesList(const char *image, vmc_save_t *out, int max, unsigned int *freeKb)
{
    vs_vmc_t v;
    vs_ent_t dot, e;
    u8_t sys[ICON_SYS_HEAD];
    int i, n = 0;

    vsErr = VMCSAVES_OK;
    if (!vsOpen(&v, image, 0))
        return -1;
    if (freeKb)
        *freeKb = vsFreeCount(&v) * (v.csize / 1024);
    if (!vsEnt(&v, v.root, 0, &dot, 0)) {
        vsClose(&v);
        vsFail(VMCSAVES_ERR_READ);
        return -1;
    }
    for (i = 2; i < vsDirLen(dot.length) && n < max; i++) {
        if (!vsEnt(&v, v.root, i, &e, 0))
            break;
        if (!(e.mode & MC_EXISTS) || !(e.mode & MC_DIR))
            continue;
        snprintf(out[n].name, sizeof(out[n].name), "%.32s", e.name);
        memset(sys, 0, sizeof(sys));
        if (vsReadIn(&v, &e, "icon.sys", sys, sizeof(sys)) == (int)sizeof(sys))
            vmcSavesTitle(sys, sizeof(sys), out[n].title, sizeof(out[n].title));
        else
            out[n].title[0] = '\0';
        n++;
    }
    vsClose(&v);
    return n;
}

static int vsCopy(int fromVmc, const char *from, const char *save, const char *to)
{
    static vs_save_t s; // ~2.5 KB of names and pointers; one copy at a time (the GUI thread)
    int r;

    vsErr = VMCSAVES_OK;
    memset(&s, 0, sizeof(s));
    r = fromVmc ? vsLoadVmc(&s, from, save) : vsLoadFolder(&s, from, save);
    if (r)
        r = fromVmc ? vsWriteFolder(&s, to) : vsWriteVmc(&s, to);
    vsSaveFree(&s);
    return r;
}

int vmcSavesExport(const char *image, const char *save, const char *parent)
{
    return vsCopy(1, image, save, parent);
}

int vmcSavesImport(const char *parent, const char *save, const char *image)
{
    return vsCopy(0, parent, save, image);
}

int vmcSavesDelete(const char *image, const char *save)
{
    vs_vmc_t v;
    vs_ent_t dir, e;
    int i, at, ok;
    u32_t files[SAVE_FILES];
    int nfiles = 0;

    vsErr = VMCSAVES_OK;
    if (!vsOpen(&v, image, 1))
        return 0;
    at = vsFindSave(&v, save, &dir);
    if (at < 0) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_NO_SAVE);
    }
    // the chains first, read while the save is still whole
    for (i = 2; i < vsDirLen(dir.length) && nfiles < SAVE_FILES; i++)
        if (vsEnt(&v, dir.cluster, i, &e, 0) && (e.mode & MC_EXISTS) && (e.mode & MC_FILE) && e.length > 0)
            files[nfiles++] = e.cluster;
    // then the save goes: its root entry hidden (the slot stays, empty, as mcman leaves it), and only then its clusters freed
    dir.mode &= ~MC_EXISTS;
    if (!vsEnt(&v, v.root, at, &dir, 1)) {
        vsClose(&v);
        return vsFail(VMCSAVES_ERR_WRITE);
    }
    for (i = 0; i < nfiles; i++)
        vsFreeChain(&v, files[i]);
    vsFreeChain(&v, dir.cluster);
    ok = vsFlushFat(&v);
    vsClose(&v);
    return ok ? 1 : vsFail(VMCSAVES_ERR_WRITE);
}

int vmcSavesListFolder(const char *parent, vmc_save_t *out, int max)
{
    char path[384];
    u8_t sys[ICON_SYS_HEAD];
    DIR *d = opendir(parent);
    struct dirent *de;
    struct stat st;
    int n = 0, fd;

    if (d == NULL)
        return 0;
    while ((de = readdir(d)) != NULL && n < max) {
        if (de->d_name[0] == '.' || strlen(de->d_name) > 32)
            continue;
        if (snprintf(path, sizeof(path), "%s%s", parent, de->d_name) >= (int)sizeof(path) || stat(path, &st) != 0 || !S_ISDIR(st.st_mode))
            continue;
        snprintf(out[n].name, sizeof(out[n].name), "%.32s", de->d_name);
        out[n].title[0] = '\0';
        snprintf(path, sizeof(path), "%s%s/icon.sys", parent, de->d_name);
        if ((fd = open(path, O_RDONLY)) >= 0) {
            if (read(fd, sys, sizeof(sys)) == (int)sizeof(sys))
                vmcSavesTitle(sys, sizeof(sys), out[n].title, sizeof(out[n].title));
            close(fd);
        }
        n++;
    }
    closedir(d);
    return n;
}
