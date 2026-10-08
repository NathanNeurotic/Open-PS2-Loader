/*
  Copyright 2026, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  3D save icons for the selected game (fork-gaps OR1). See include/saveicon.h for the contract.

  The formats, as checked against the icons this repository ships (misc/, POPS/) and OPL's own VMCs:
  - icon.sys (964 bytes): "PS2D", the background, then three lights at 0x50 (directions), 0x80
    (colours) and 0xB0 (ambient) as float x,y,z,w, the Shift-JIS title at 0xC0 and the list-icon
    file name at 0x104 -- ps2sdk's mcIcon layout.
  - the icon: a 20-byte header (0x00010000, shape count, texture type, a float, vertex count), then
    per vertex one 8-byte position per shape, an 8-byte normal, a 4-byte UV and a 4-byte RGBA, the
    positions, normals and UVs in 4.12 fixed point; then an animation header (tag 1, frame length,
    speed, play offset, frame count) and per frame a shape id, a key count and that many (time,
    value) float keys; then the 128x128 A1B5G5R5 texture when type bit 2 is set -- raw, or with bit 3
    RLE-compressed: a byte count, then 16-bit codes, bit 15 set copying (0x10000 - code) pixels and
    anything else repeating the next pixel code times.
  - a card image: include/mcemu.h's superblock at page 0; a two-level FAT (the indirect clusters the
    superblock lists name the FAT clusters, whose 32-bit entries chain the allocatable clusters: bit
    31 = in use, 0x7FFFFFFF = the end); 512-byte directory entries (mode, length, first cluster, the
    modification time at 0x18, the name at 0x40), the "." entry of a directory counting its entries.
    An image holds either bare pages or pages followed by their 1/32-size ECC spare.
*/

#ifdef SAVEICON_HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define siAllocTexels(bytes) malloc(bytes)
#else
#include "include/opl.h"
#include "include/ioman.h"
#include "include/renderman.h"
#include <dirent.h>
#include <fcntl.h>
#include <malloc.h>
#include <math.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#define siAllocTexels(bytes) memalign(128, bytes) // DMA'd to the GS like every other texture
#endif
#include "include/saveicon.h"

// ---- format (pure, host-tested) -------------------------------------------------------------

static unsigned int siRd32(const unsigned char *p)
{
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8) | ((unsigned int)p[2] << 16) | ((unsigned int)p[3] << 24);
}

static unsigned int siRd16u(const unsigned char *p)
{
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8);
}

static short siRd16(const unsigned char *p)
{
    return (short)siRd16u(p);
}

static float siRdFloat(const unsigned char *p)
{
    union
    {
        unsigned int u;
        float f;
    } v;
    v.u = siRd32(p);
    return v.f;
}

void saveIconFreeModel(saveicon_model_t *model)
{
    int s;

    if (model == NULL)
        return;
    free(model->pos);
    free(model->normal);
    free(model->uv);
    free(model->rgba);
    free(model->texels);
    for (s = 0; s < SAVEICON_MAX_SHAPES; s++)
        free(model->keys[s]);
    memset(model, 0, sizeof(*model));
}

// Expands the RLE texture into dst (count pixels). A stream cut short leaves the rest black rather
// than failing a picture that is merely truncated at the end.
static void siDecodeRle(const unsigned char *src, int len, unsigned short *dst, int count)
{
    int i = 0, n = 0;

    while (i + 2 <= len && n < count) {
        unsigned int code = siRd16u(src + i);
        i += 2;
        if (code & 0x8000) {
            int run = 0x10000 - (int)code;
            while (run-- > 0 && i + 2 <= len && n < count) {
                dst[n++] = (unsigned short)siRd16u(src + i);
                i += 2;
            }
        } else {
            unsigned short value;
            if (i + 2 > len)
                break;
            value = (unsigned short)siRd16u(src + i);
            i += 2;
            while (code-- > 0 && n < count)
                dst[n++] = value;
        }
    }
}

int saveIconParseModel(const unsigned char *data, int size, saveicon_model_t *model)
{
    int off, v, s, k, vsize, textype, frames, f;
    const int pixels = SAVEICON_TEX_SIZE * SAVEICON_TEX_SIZE;

    if (model == NULL)
        return -1;
    memset(model, 0, sizeof(*model));
    if (data == NULL || size < 20 || size > SAVEICON_MAX_FILE || siRd32(data) != 0x00010000)
        return -1;

    model->shapes = (int)siRd32(data + 4);
    textype = (int)siRd32(data + 8);
    model->verts = (int)siRd32(data + 16);
    if (model->shapes < 1 || model->shapes > SAVEICON_MAX_SHAPES || model->verts < 3 ||
        model->verts > SAVEICON_MAX_VERTS || model->verts % 3 != 0 || model->shapes * model->verts > SAVEICON_MAX_POS) {
        memset(model, 0, sizeof(*model));
        return -1;
    }

    vsize = model->shapes * 8 + 8 + 4 + 4;
    off = 20;
    if ((size - off) / vsize < model->verts)
        goto bad;

    model->pos = malloc(sizeof(short) * 3 * model->shapes * model->verts);
    model->normal = malloc(sizeof(short) * 3 * model->verts);
    model->uv = malloc(sizeof(short) * 2 * model->verts);
    model->rgba = malloc(4 * model->verts);
    if (model->pos == NULL || model->normal == NULL || model->uv == NULL || model->rgba == NULL)
        goto bad;

    for (v = 0; v < model->verts; v++) {
        for (s = 0; s < model->shapes; s++) {
            for (k = 0; k < 3; k++)
                model->pos[(s * model->verts + v) * 3 + k] = siRd16(data + off + 8 * s + 2 * k);
        }
        off += 8 * model->shapes;
        for (k = 0; k < 3; k++)
            model->normal[v * 3 + k] = siRd16(data + off + 2 * k);
        off += 8;
        model->uv[v * 2] = siRd16(data + off);
        model->uv[v * 2 + 1] = siRd16(data + off + 2);
        off += 4;
        memcpy(&model->rgba[v * 4], data + off, 4);
        off += 4;
    }

    // Animation. A key list for a shape the model does not have is skipped, never trusted.
    if (size - off < 20 || siRd32(data + off) != 1)
        goto bad;
    model->frameLength = (int)siRd32(data + off + 4);
    model->speed = siRdFloat(data + off + 8);
    if (!(model->speed > 0.0f && model->speed < 100.0f)) // also refuses a NaN
        model->speed = 1.0f;
    frames = (int)siRd32(data + off + 16);
    off += 20;
    if (frames < 0 || frames > SAVEICON_MAX_SHAPES * 4)
        goto bad;
    for (f = 0; f < frames; f++) {
        int shape, count;
        if (size - off < 8)
            goto bad;
        shape = (int)siRd32(data + off);
        count = (int)siRd32(data + off + 4);
        off += 8;
        if (count < 0 || count > SAVEICON_MAX_KEYS || (size - off) / 8 < count)
            goto bad;
        if (shape >= 0 && shape < model->shapes && model->keys[shape] == NULL && count > 0) {
            model->keys[shape] = malloc(sizeof(saveicon_key_t) * count);
            if (model->keys[shape] == NULL)
                goto bad;
            for (k = 0; k < count; k++) {
                model->keys[shape][k].time = siRdFloat(data + off + 8 * k);
                model->keys[shape][k].value = siRdFloat(data + off + 8 * k + 4);
            }
            model->keyCount[shape] = count;
        }
        off += 8 * count;
    }

    if (textype & 4) {
        model->texels = siAllocTexels(sizeof(unsigned short) * pixels);
        if (model->texels == NULL)
            goto bad;
        memset(model->texels, 0, sizeof(unsigned short) * pixels);
        if (textype & 8) {
            int packed;
            if (size - off < 4)
                goto bad;
            packed = (int)siRd32(data + off);
            off += 4;
            if (packed < 0 || packed > size - off)
                goto bad;
            siDecodeRle(data + off, packed, model->texels, pixels);
        } else {
            if (size - off < (int)sizeof(unsigned short) * pixels)
                goto bad;
            for (k = 0; k < pixels; k++)
                model->texels[k] = (unsigned short)siRd16u(data + off + 2 * k);
        }
    }
    return 0;

bad:
    saveIconFreeModel(model);
    return -2;
}

int saveIconParseSys(const unsigned char *data, int size, char *listName, int listSize, saveicon_light_t *light)
{
    int i, k, len;

    if (data == NULL || size < SAVEICON_SYS_SIZE || listName == NULL || listSize <= 0 || memcmp(data, "PS2D", 4) != 0)
        return 0;

    // The name must be a plain file inside the save folder: no separator, no device, not empty.
    for (len = 0; len < 64 && data[SAVEICON_SYS_LIST + len] != '\0'; len++) {
        unsigned char c = data[SAVEICON_SYS_LIST + len];
        if (c == '/' || c == '\\' || c == ':' || c < 0x20)
            return 0;
    }
    if (len == 0 || len == 64 || len >= listSize || (len <= 2 && data[SAVEICON_SYS_LIST] == '.'))
        return 0;
    memcpy(listName, data + SAVEICON_SYS_LIST, len);
    listName[len] = '\0';

    if (light != NULL) {
        for (i = 0; i < 3; i++) {
            for (k = 0; k < 3; k++) {
                light->dir[i][k] = siRdFloat(data + 0x50 + 16 * i + 4 * k);
                light->color[i][k] = siRdFloat(data + 0x80 + 16 * i + 4 * k);
            }
        }
        for (k = 0; k < 3; k++)
            light->ambient[k] = siRdFloat(data + 0xB0 + 4 * k);
        light->valid = 1;
    }
    return 1;
}

int saveIconSerialForStartup(const char *startup, char *serial, int serialSize)
{
    int i;

    if (startup == NULL || serial == NULL || serialSize < 11 || strlen(startup) < 11 || startup[4] != '_' || startup[8] != '.')
        return 0;
    for (i = 0; i < 4; i++) {
        if (!((startup[i] >= 'A' && startup[i] <= 'Z') || (startup[i] >= '0' && startup[i] <= '9')))
            return 0;
    }
    for (i = 5; i <= 10; i++) {
        if (i != 8 && (startup[i] < '0' || startup[i] > '9'))
            return 0;
    }
    // SLUS_200.62 -> SLUS-20062
    snprintf(serial, serialSize, "%.4s-%.3s%.2s", startup, startup + 5, startup + 9);
    return 1;
}

int saveIconFolderMatches(const char *folder, const char *serial)
{
    if (folder == NULL || serial == NULL || folder[0] != 'B' || strlen(folder) < 12 || strlen(serial) != 10)
        return 0;
    return strncmp(folder + 2, serial, 10) == 0;
}

float saveIconShapeWeights(const saveicon_model_t *model, float t, float *weights)
{
    int s, k;
    float sum = 0.0f;

    for (s = 0; s < model->shapes; s++) {
        const saveicon_key_t *keys = model->keys[s];
        int n = model->keyCount[s];
        float w = 0.0f;

        if (model->shapes == 1)
            w = 1.0f;
        else if (n == 1)
            w = keys[0].value;
        else if (n > 1) {
            if (t <= keys[0].time)
                w = keys[0].value;
            else if (t >= keys[n - 1].time)
                w = keys[n - 1].value;
            else {
                for (k = 1; k < n; k++) {
                    if (t <= keys[k].time) {
                        float span = keys[k].time - keys[k - 1].time;
                        float a = span > 0.0f ? (t - keys[k - 1].time) / span : 1.0f;
                        w = keys[k - 1].value + (keys[k].value - keys[k - 1].value) * a;
                        break;
                    }
                }
            }
        }
        if (!(w > 0.0f)) // negative, or a NaN key
            w = 0.0f;
        weights[s] = w;
        sum += w;
    }
    if (!(sum > 0.0f)) {
        // No usable keys: show the first shape still, never an empty (collapsed) model.
        for (s = 0; s < model->shapes; s++)
            weights[s] = s == 0 ? 1.0f : 0.0f;
        sum = 1.0f;
    }
    return sum;
}

// ---- the card filesystem inside a VMC image (pure, host-tested) ------------------------------

#define SI_MC_ENTRY        512 // one directory entry
#define SI_MC_EXISTS       0x8000
#define SI_MC_IS_DIR       0x0020
#define SI_MC_IS_FILE      0x0010
#define SI_MC_CLUSTER_MAX  4096 // bytes; every real card uses 1024
#define SI_MC_CLUSTERS_MAX 262144
#define SI_MC_ENTRIES_MAX  4096 // a directory larger than this is damage, not saves

typedef struct
{
    saveicon_read_t read;
    void *ctx;
    unsigned int pageSize, pageRaw, pagesPerCluster, clusterSize, clusters, allocOffset;
    unsigned int ifc[32];
    unsigned int ifcCached, fatCached; // the absolute cluster each buffer holds, or ~0
    unsigned char ifcBuf[SI_MC_CLUSTER_MAX], fatBuf[SI_MC_CLUSTER_MAX], dirBuf[SI_MC_CLUSTER_MAX];
} si_card_t;

typedef struct
{
    const char *name;   // a file, matched exactly
    const char *serial; // or a save folder of this product code
    unsigned int cluster, length;
    unsigned long long stamp;
    int found;
} si_find_t;

// count clusters from absolute cluster first, the first `bytes` of them, into out.
static int siCardRead(si_card_t *card, unsigned int first, unsigned int count, unsigned char *out, unsigned int bytes)
{
    unsigned int page, done;

    if (first >= card->clusters || count > card->clusters - first || bytes > count * card->clusterSize)
        return 0;
    if (card->pageRaw == card->pageSize)
        return card->read(card->ctx, first * card->clusterSize, out, (int)bytes) == (int)bytes;
    // An ECC spare follows every page: one read per page.
    for (page = first * card->pagesPerCluster, done = 0; done < bytes; page++) {
        unsigned int n = bytes - done < card->pageSize ? bytes - done : card->pageSize;
        if (card->read(card->ctx, page * card->pageRaw, out + done, (int)n) != (int)n)
            return 0;
        done += n;
    }
    return 1;
}

static int siCardU32(si_card_t *card, unsigned int cluster, unsigned int index, unsigned char *buf, unsigned int *cached, unsigned int *out)
{
    if (*cached != cluster) {
        if (!siCardRead(card, cluster, 1, buf, card->clusterSize))
            return 0;
        *cached = cluster;
    }
    *out = siRd32(buf + 4 * index);
    return 1;
}

// The cluster after relative cluster n in its chain: 1 = *next set, 0 = the end of the chain or damage.
static int siCardNext(si_card_t *card, unsigned int n, unsigned int *next)
{
    unsigned int per = card->clusterSize / 4, fatIndex = n / per, ifcIndex = fatIndex / per, fatCluster, entry;

    if (ifcIndex >= 32 ||
        !siCardU32(card, card->ifc[ifcIndex], fatIndex % per, card->ifcBuf, &card->ifcCached, &fatCluster) ||
        !siCardU32(card, fatCluster, n % per, card->fatBuf, &card->fatCached, &entry))
        return 0;
    if (!(entry & 0x80000000u) || (entry & 0x7FFFFFFFu) == 0x7FFFFFFFu)
        return 0;
    *next = entry & 0x7FFFFFFFu;
    return 1;
}

// The first `size` bytes of the chain starting at relative cluster first.
static int siCardReadChain(si_card_t *card, unsigned int first, unsigned char *out, unsigned int size)
{
    unsigned int cs = card->clusterSize, done = 0, cluster = first, steps = 0;

    while (done < size) {
        unsigned int start = cluster, count = 1, bytes;

        // Consecutive clusters are one read on an image of bare pages.
        while (done + count * cs < size) {
            unsigned int next;
            if (!siCardNext(card, cluster, &next) || ++steps > card->clusters)
                return 0; // the chain ends before the file does, or loops
            cluster = next;
            if (next != start + count || card->pageRaw != card->pageSize)
                break;
            count++;
        }
        bytes = size - done < count * cs ? size - done : count * cs;
        if (!siCardRead(card, card->allocOffset + start, count, out + done, bytes))
            return 0;
        done += bytes;
    }
    return 1;
}

// Calls visit on each live entry of the directory at relative cluster first (count entries) until it
// returns nonzero. 1 = walked (or stopped by visit), 0 = damage.
static int siCardWalk(si_card_t *card, unsigned int first, unsigned int count, int (*visit)(const unsigned char *entry, si_find_t *find), si_find_t *find)
{
    unsigned int per = card->clusterSize / SI_MC_ENTRY, i = 0, cluster = first, steps = 0, k;

    while (i < count) {
        if (!siCardRead(card, card->allocOffset + cluster, 1, card->dirBuf, card->clusterSize))
            return 0;
        for (k = 0; k < per && i < count; k++, i++) {
            const unsigned char *entry = card->dirBuf + k * SI_MC_ENTRY;
            if ((siRd16u(entry) & SI_MC_EXISTS) && visit(entry, find))
                return 1;
        }
        if (i < count && (!siCardNext(card, cluster, &cluster) || ++steps > card->clusters))
            return 0;
    }
    return 1;
}

// The card's 8-byte time (unused, second, minute, hour, day, month, 16-bit year) as one ordered number.
static unsigned long long siCardStamp(const unsigned char *t)
{
    return (((((unsigned long long)siRd16u(t + 6) * 13 + t[5]) * 32 + t[4]) * 24 + t[3]) * 60 + t[2]) * 60 + t[1];
}

static int siVisitSave(const unsigned char *entry, si_find_t *find)
{
    char name[33];
    unsigned long long stamp;

    if (!(siRd16u(entry) & SI_MC_IS_DIR))
        return 0;
    memcpy(name, entry + 0x40, 32);
    name[32] = '\0';
    if (!saveIconFolderMatches(name, find->serial))
        return 0;
    stamp = siCardStamp(entry + 0x18);
    if (!find->found || stamp > find->stamp) {
        find->found = 1;
        find->stamp = stamp;
        find->cluster = siRd32(entry + 0x10);
        find->length = siRd32(entry + 0x04);
    }
    return 0; // keep walking: the newest save wins
}

static int siVisitFile(const unsigned char *entry, si_find_t *find)
{
    if (!(siRd16u(entry) & SI_MC_IS_FILE) || strncmp((const char *)entry + 0x40, find->name, 32) != 0)
        return 0;
    find->found = 1;
    find->cluster = siRd32(entry + 0x10);
    find->length = siRd32(entry + 0x04);
    return 1;
}

int saveIconFromCardImage(saveicon_read_t readFn, void *ctx, unsigned int imageSize, const char *serial,
                          saveicon_model_t *model, saveicon_light_t *light)
{
    unsigned char sb[0x150], *data = NULL;
    si_card_t *card;
    si_find_t save, file;
    char listName[64];
    unsigned int spare, root, rootCount, i;
    int ok = 0;

    if (model == NULL)
        return 0;
    memset(model, 0, sizeof(*model));
    if (readFn == NULL || serial == NULL || readFn(ctx, 0, sb, sizeof(sb)) != (int)sizeof(sb) ||
        memcmp(sb, "Sony PS2 Memory Card Format ", 28) != 0)
        return 0;
    card = malloc(sizeof(*card));
    if (card == NULL)
        return 0;
    memset(card, 0, sizeof(*card));
    card->read = readFn;
    card->ctx = ctx;
    card->pageSize = siRd16u(sb + 0x28);
    card->pagesPerCluster = siRd16u(sb + 0x2A);
    card->clusterSize = card->pageSize * card->pagesPerCluster;
    card->clusters = siRd32(sb + 0x30);
    card->allocOffset = siRd32(sb + 0x34);
    root = siRd32(sb + 0x3C);
    for (i = 0; i < 32; i++)
        card->ifc[i] = siRd32(sb + 0x50 + 4 * i);
    card->ifcCached = card->fatCached = 0xFFFFFFFFu;
    spare = card->pageSize / 32;
    if ((card->pageSize != 512 && card->pageSize != 1024) || card->pagesPerCluster < 1 ||
        card->clusterSize > SI_MC_CLUSTER_MAX || card->clusters < 16 || card->clusters > SI_MC_CLUSTERS_MAX ||
        card->allocOffset >= card->clusters)
        goto done;
    // The ECC-spare layout only when the size says exactly that; anything at least the bare size is bare pages.
    if (imageSize == card->clusters * card->pagesPerCluster * (card->pageSize + spare))
        card->pageRaw = card->pageSize + spare;
    else if (imageSize >= card->clusters * card->clusterSize)
        card->pageRaw = card->pageSize;
    else
        goto done;

    // The root's own "." entry counts the root.
    if (!siCardRead(card, card->allocOffset + root, 1, card->dirBuf, card->clusterSize))
        goto done;
    rootCount = siRd32(card->dirBuf + 0x04);
    if (rootCount < 2 || rootCount > SI_MC_ENTRIES_MAX)
        goto done;

    memset(&save, 0, sizeof(save));
    save.serial = serial;
    if (!siCardWalk(card, root, rootCount, &siVisitSave, &save) || !save.found || save.length < 2 || save.length > SI_MC_ENTRIES_MAX)
        goto done;

    memset(&file, 0, sizeof(file));
    file.name = "icon.sys";
    if (!siCardWalk(card, save.cluster, save.length, &siVisitFile, &file) || !file.found ||
        file.length < SAVEICON_SYS_SIZE || file.length > 2 * SAVEICON_SYS_SIZE)
        goto done;
    data = malloc(file.length);
    if (data == NULL || !siCardReadChain(card, file.cluster, data, file.length) ||
        !saveIconParseSys(data, (int)file.length, listName, sizeof(listName), light))
        goto done;
    free(data);
    data = NULL;

    memset(&file, 0, sizeof(file));
    file.name = listName;
    if (!siCardWalk(card, save.cluster, save.length, &siVisitFile, &file) || !file.found || file.length < 20 ||
        file.length > SAVEICON_MAX_FILE)
        goto done;
    data = malloc(file.length);
    if (data != NULL && siCardReadChain(card, file.cluster, data, file.length))
        ok = saveIconParseModel(data, (int)file.length, model) == 0;

done:
    free(data);
    free(card);
    return ok;
}

// PSX-SPX Memory Card Data Format: 128-byte frames, 15 save blocks, 4-bit 16x16 icons.
static int siPs1Checksum(const unsigned char *frame)
{
    unsigned char sum = 0;
    int i;
    for (i = 0; i < 127; i++)
        sum ^= frame[i];
    return sum == frame[127];
}

int saveIconFromPs1CardImage(saveicon_read_t readFn, void *ctx, unsigned int imageSize, const char *serial,
                             saveicon_model_t *model)
{
    unsigned char directory[16][128], data[512];
    int block, pass;

    memset(model, 0, sizeof(*model));
    if (imageSize != 131072 || readFn(ctx, 0, directory, sizeof(directory)) != sizeof(directory) ||
        directory[0][0] != 'M' || directory[0][1] != 'C' || !siPs1Checksum(directory[0]))
        return 0;
    // With no disc id (common for named Ember folders), the dedicated card's first save wins.
    for (pass = 0; pass < ((serial != NULL && serial[0]) ? 2 : 1); pass++) {
        for (block = 1; block < 16; block++) {
            unsigned char *entry = directory[block];
            unsigned int bytes = siRd32(entry + 4), next;
            unsigned int seen = 0;
            char filename[21];
            int current = block, count = 0, valid = 1, frames, pixel;

            if (siRd32(entry) != 0x51 || !siPs1Checksum(entry) || bytes == 0 || bytes > 15 * 8192 || bytes % 8192)
                continue;
            memcpy(filename, entry + 10, 20);
            filename[20] = '\0';
            if (serial != NULL && serial[0] && pass == 0 && !saveIconFolderMatches(filename, serial))
                continue;
            do {
                unsigned char *part = directory[current];
                unsigned int type = siRd32(part);
                if ((seen & (1u << current)) || !siPs1Checksum(part) ||
                    (count == 0 ? type != 0x51 : (type != 0x52 && type != 0x53))) {
                    valid = 0;
                    break;
                }
                seen |= 1u << current;
                count++;
                next = siRd16u(part + 8);
                if (next == 0xFFFF)
                    break;
                if (next >= 15 || type == 0x53) {
                    valid = 0;
                    break;
                }
                current = next + 1;
            } while (count < 15);
            if (!valid || next != 0xFFFF || (unsigned int)count != bytes / 8192 ||
                (count > 1 && siRd32(directory[current]) != 0x53) ||
                readFn(ctx, block * 8192, data, sizeof(data)) != sizeof(data) ||
                data[0] != 'S' || data[1] != 'C' || data[2] < 0x11 || data[2] > 0x13)
                continue;
            frames = data[2] - 0x10;
            model->texels = siAllocTexels(frames * 256 * sizeof(unsigned short));
            if (model->texels == NULL)
                return 0;
            for (pixel = 0; pixel < frames * 256; pixel++) {
                int packed = data[128 + pixel / 2];
                int index = (packed >> ((pixel & 1) * 4)) & 15;
                unsigned short color = siRd16u(data + 96 + index * 2);
                model->texels[pixel] = color == 0 ? 0 : color | 0x8000;
            }
            model->ps1Frames = frames;
            return 1;
        }
    }
    return 0;
}

#ifndef SAVEICON_HOST_TEST
#include "include/cuesupport.h"
#define NEWLIB_PORT_AWARE // Only APA mount/unmount use fileXio; every file read uses POSIX.
#include <fileXio_rpc.h>
#include <io_common.h>

int saveIconPs1Directory(const char *root, const char *name, int ember, char *out, int outSize)
{
    char base[SAVEICON_PATH_SIZE];
    int n, len = strlen(root);
    char sep = len > 0 && root[len - 1] == '\\' ? '\\' : '/';

    if (name == NULL || name[0] == '\0' || strchr(name, '/') != NULL || strchr(name, '\\') != NULL ||
        strchr(name, ':') != NULL || !strcmp(name, ".") || !strcmp(name, "..") ||
        (ember && !cueNameLaunchable(name)))
        return 0;
    if (strlen(root) + strlen(cueEmberFolder()) + strlen("/games") >= sizeof(base))
        return 0;
    if (ember)
        cueBuildGamesDir(root, base, sizeof(base));
    else {
        n = snprintf(base, sizeof(base), "%sPOPS", root);
        if (n <= 0 || n >= (int)sizeof(base))
            return 0;
    }
    n = snprintf(out, outSize, "%s%c%s", base, sep, name);
    return n > 0 && n < outSize;
}

// ---- loading (IO worker) --------------------------------------------------------------------

#define SI_SETTLE_US      250000  // a row is read once the cursor has rested on it this long
#define SI_CONFIG_WAIT_US 2000000 // how long a row waits for its per-game config before reading the cards alone
#define SI_SPIN_SECONDS   6.0f    // one turn

// A whole small file, malloc'd; NULL when missing, empty or larger than maxSize.
static unsigned char *siReadFile(const char *path, int maxSize, int *outSize)
{
    unsigned char *buf;
    int fd, size;

    fd = open(path, O_RDONLY);
    if (fd < 0)
        return NULL;
    size = lseek(fd, 0, SEEK_END);
    if (size <= 0 || size > maxSize || lseek(fd, 0, SEEK_SET) != 0) {
        close(fd);
        return NULL;
    }
    buf = malloc(size);
    if (buf != NULL && read(fd, buf, size) != size) {
        free(buf);
        buf = NULL;
    }
    close(fd);
    if (buf != NULL)
        *outSize = size;
    return buf;
}

static int siFdRead(void *ctx, unsigned int offset, void *buf, int size)
{
    int fd = *(int *)ctx;

    if (lseek(fd, (int)offset, SEEK_SET) != (int)offset)
        return -1;
    return read(fd, buf, size);
}

// The game's own per-game VMC.
static int siLoadFromVmc(const char *path, const char *serial, saveicon_model_t *model, saveicon_light_t *light)
{
    int fd, size, ok;

    fd = open(path, O_RDONLY);
    if (fd < 0)
        return 0;
    size = lseek(fd, 0, SEEK_END);
    ok = size > 0 && saveIconFromCardImage(&siFdRead, &fd, (unsigned int)size, serial, model, light);
    close(fd);
    LOG("SAVEICON %s in %s: %s\n", serial, path, ok ? "loaded" : "none");
    return ok;
}

// The memory cards: the newest save folder of that product code on either, by modification time.
static int siLoadFromCards(const char *serial, saveicon_model_t *model, saveicon_light_t *light)
{
    char best[96], path[96], listName[64];
    saveicon_light_t candidate;
    time_t bestTime = 0;
    unsigned char *data;
    int port, size = 0, ok, found = 0;

    for (port = 0; port < 2; port++) {
        char root[8];
        DIR *dir;
        struct dirent *de;

        // Slot 2 is where an MX4SIO sits: never put card traffic on the bus it is serving games from.
        if (port == 1 && gEnableMX4SIO)
            continue;
        snprintf(root, sizeof(root), "mc%d:/", port);
        dir = opendir(root);
        if (dir == NULL)
            continue;
        while ((de = readdir(dir)) != NULL) {
            struct stat st;
            time_t mtime;

            if (!saveIconFolderMatches(de->d_name, serial))
                continue;
            snprintf(path, sizeof(path), "mc%d:/%s", port, de->d_name);
            mtime = stat(path, &st) == 0 ? st.st_mtime : 0;
            if (found && mtime <= bestTime)
                continue; // an equally new or newer save already won
            snprintf(path, sizeof(path), "mc%d:/%s/icon.sys", port, de->d_name);
            data = siReadFile(path, 2 * SAVEICON_SYS_SIZE, &size);
            if (data == NULL)
                continue;
            ok = saveIconParseSys(data, size, listName, sizeof(listName), &candidate);
            free(data);
            if (!ok)
                continue;
            snprintf(best, sizeof(best), "mc%d:/%s/%s", port, de->d_name, listName);
            bestTime = mtime;
            *light = candidate;
            found = 1;
        }
        closedir(dir);
    }
    if (!found)
        return 0;
    data = siReadFile(best, SAVEICON_MAX_FILE, &size);
    if (data == NULL)
        return 0;
    ok = saveIconParseModel(data, size, model) == 0;
    free(data);
    LOG("SAVEICON %s: %s %s\n", serial, best, ok ? "loaded" : "unreadable");
    return ok;
}

// ---- hand-off between the two threads ---------------------------------------------------------

#define SI_NONE    0
#define SI_MODEL   1 // a model for that key
#define SI_MISSING 2 // looked, and that game has no readable save icon

#define SI_KEY_SIZE (16 + 2 * SAVEICON_PATH_SIZE + 4)

static int siSema = -1;

// Under siSema. Written by the GUI thread, read by the IO worker: what to load. The key is
// startup|vmc0|vmc1, "" for nothing.
static char siWantKey[SI_KEY_SIZE];
static char siWantStartup[16];
static char siWantVmc[2][SAVEICON_PATH_SIZE];
static int siWantPs1; // 1 POPSTARTER, 2 Ember
// Under siSema. A finished load, published by the IO worker and adopted by the GUI thread.
static char siPendingKey[SI_KEY_SIZE];
static int siPendingState;
static saveicon_model_t siPending;
static saveicon_light_t siPendingLight;

// GUI thread only.
static char siSelStartup[16]; // the row the element last asked about
static clock_t siSelSince;
static char siQueuedKey[SI_KEY_SIZE];
static char siShownKey[SI_KEY_SIZE];
static int siShownState;
static saveicon_model_t siShown;
static saveicon_light_t siShownLight;
static int siShownLit;
static GSTEXTURE siTex;
static GSTEXTURE siPs1Tex[3];
static clock_t siShownSince;
static float siPivot[3], siRadius, siHalfHeight;
// The model last replaced, kept two more frames: a hires frame can still be drawing from it.
static saveicon_model_t siRetired;
static int siRetiredFrames;
// Per-vertex work buffers, and the painter's order kept from frame to frame.
static float *siX, *siY, *siZ, *siDepth, *siDrawXY, *siDrawUV;
static u64 *siCol, *siDrawCol;
static int *siOrder, siBufVerts, siOrderValid;

static void siLock(void)
{
    if (siSema < 0) {
        ee_sema_t sema;
        sema.init_count = 1;
        sema.max_count = 1;
        sema.option = 0;
        siSema = CreateSema(&sema);
    }
    WaitSema(siSema);
}

static void siUnlock(void)
{
    SignalSema(siSema);
}

static void siLoadAction(void)
{
    char key[SI_KEY_SIZE], startup[16], vmc[2][SAVEICON_PATH_SIZE], serial[16];
    saveicon_model_t model;
    saveicon_light_t light;
    int found = 0, slot, ps1;

    siLock();
    memcpy(key, siWantKey, sizeof(key));
    memcpy(startup, siWantStartup, sizeof(startup));
    memcpy(vmc, siWantVmc, sizeof(vmc));
    ps1 = siWantPs1;
    siUnlock();
    if (key[0] == '\0')
        return;

    memset(&model, 0, sizeof(model));
    memset(&light, 0, sizeof(light));
    if (ps1) {
        char directory[SAVEICON_PATH_SIZE], path[SAVEICON_PATH_SIZE];
        int mounted = 0;
        char sep = strchr(vmc[0], '\\') != NULL ? '\\' : '/';
        snprintf(directory, sizeof(directory), "%s", vmc[0]);
        if (vmc[1][0]) {
            fileXioUmount("pfs1:");
            mounted = fileXioMount("pfs1:", vmc[1], FIO_MT_RDONLY) == 0;
        }
        if (!vmc[1][0] || mounted) {
            // Ember's optional shared card redirects to one sibling game folder, never a path.
            if (ps1 == 2) {
                unsigned char *shared;
                int size = 0, n = snprintf(path, sizeof(path), "%s%cSharedMC.txt", directory, sep);
                shared = n > 0 && n < sizeof(path) ? siReadFile(path, CUE_NAME_LAUNCH_MAX + 2, &size) : NULL;
                if (shared != NULL) {
                    char name[CUE_NAME_LAUNCH_MAX + 3], target[SAVEICON_PATH_SIZE];
                    char *slash = strrchr(directory, '/'), *backslash = strrchr(directory, '\\');
                    struct stat st;
                    if (backslash != NULL && (slash == NULL || backslash > slash))
                        slash = backslash;
                    memcpy(name, shared, size);
                    name[size] = '\0';
                    while (size > 0 && (name[size - 1] == '\n' || name[size - 1] == '\r'))
                        name[--size] = '\0';
                    if (slash != NULL && cueNameLaunchable(name) && memchr(name, '\0', size) == NULL) {
                        int parentLen = slash - directory;
                        n = snprintf(target, sizeof(target), "%.*s%c%s", parentLen, directory, *slash, name);
                        if (n > 0 && n < sizeof(target) && strcmp(target, directory) != 0 &&
                            stat(target, &st) == 0 && S_ISDIR(st.st_mode)) {
                            n = snprintf(path, sizeof(path), "%s%cSharedMC.txt", target, sep);
                            // Ember refuses chained redirects; use the original folder then.
                            if (n > 0 && n < sizeof(path) && stat(path, &st) < 0)
                                snprintf(directory, sizeof(directory), "%s", target);
                        }
                    }
                    free(shared);
                }
            }
            for (slot = 0; slot < 2 && !found; slot++) {
                int fd, size, n = snprintf(path, sizeof(path), ps1 == 2 ? "%s%cMC%d.vmc" : "%s%cSLOT%d.VMC", directory, sep, ps1 == 2 ? slot + 1 : slot);
                if (n <= 0 || n >= sizeof(path))
                    continue;
                fd = open(path, O_RDONLY);
                if (fd < 0)
                    continue;
                size = lseek(fd, 0, SEEK_END);
                found = size > 0 && saveIconFromPs1CardImage(&siFdRead, &fd, size, NULL, &model);
                close(fd);
            }
        }
        if (mounted)
            fileXioUmount("pfs1:");
    } else if (saveIconSerialForStartup(startup, serial, sizeof(serial))) {
        // The game's own VMC first: when it has one, that is where its saves are.
        for (slot = 0; slot < 2 && !found; slot++) {
            if (vmc[slot][0] != '\0')
                found = siLoadFromVmc(vmc[slot], serial, &model, &light);
        }
        if (!found)
            found = siLoadFromCards(serial, &model, &light);
    }

    siLock();
    if (strcmp(siWantKey, key) == 0) {
        if (siPendingState == SI_MODEL)
            saveIconFreeModel(&siPending);
        siPendingState = found ? SI_MODEL : SI_MISSING;
        if (found) {
            siPending = model;
            siPendingLight = light;
            found = 0; // handed over
        }
        memcpy(siPendingKey, key, sizeof(siPendingKey));
    }
    siUnlock();
    if (found)
        saveIconFreeModel(&model); // the selection moved on while the cards were read
}

static void siFreeRetired(void)
{
    saveIconFreeModel(&siRetired);
    siRetiredFrames = 0;
}

static void siRetireShown(void)
{
    int frame;
    if (siShownState == SI_MODEL) {
        if (siShown.ps1Frames) {
            for (frame = 0; frame < siShown.ps1Frames; frame++)
                rmUnloadTexture(&siPs1Tex[frame]);
        } else if (siShown.texels != NULL)
            rmUnloadTexture(&siTex);
        siFreeRetired();
        siRetired = siShown;
        memset(&siShown, 0, sizeof(siShown));
    }
    memset(&siTex, 0, sizeof(siTex));
    memset(siPs1Tex, 0, sizeof(siPs1Tex));
    siShownState = SI_NONE;
    siShownKey[0] = '\0';
}

// The pivot and the extent over every shape, so no frame of the animation leaves the box.
static void siMeasure(void)
{
    int i, k, n = siShown.shapes * siShown.verts;
    float lo[3] = {1e9f, 1e9f, 1e9f}, hi[3] = {-1e9f, -1e9f, -1e9f};

    for (i = 0; i < n; i++) {
        for (k = 0; k < 3; k++) {
            float c = siShown.pos[i * 3 + k];
            if (c < lo[k])
                lo[k] = c;
            if (c > hi[k])
                hi[k] = c;
        }
    }
    for (k = 0; k < 3; k++)
        siPivot[k] = (lo[k] + hi[k]) * 0.5f;
    siRadius = 1.0f;
    for (i = 0; i < n; i++) {
        float dx = siShown.pos[i * 3] - siPivot[0], dz = siShown.pos[i * 3 + 2] - siPivot[2];
        float r = sqrtf(dx * dx + dz * dz);
        if (r > siRadius)
            siRadius = r;
    }
    siHalfHeight = (hi[1] - lo[1]) * 0.5f;
    if (siHalfHeight < 1.0f)
        siHalfHeight = 1.0f;
}

// icon.sys lights, used only when they hold something: an all-zero (or unreadable) set leaves the
// vertex colours as they are rather than drawing the icon black.
static void siPrepareLight(void)
{
    float total = 0.0f;
    int i, k;

    siShownLit = 0;
    if (!siShownLight.valid)
        return;
    for (i = 0; i < 3; i++) {
        float *d = siShownLight.dir[i], len = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
        if (!(len < 1e6f))
            return; // NaN or absurd
        if (len > 0.0f) {
            for (k = 0; k < 3; k++)
                d[k] /= len;
        }
        for (k = 0; k < 3; k++) {
            if (!(siShownLight.color[i][k] >= 0.0f && siShownLight.color[i][k] <= 4.0f))
                return;
            total += siShownLight.color[i][k];
        }
    }
    for (k = 0; k < 3; k++) {
        if (!(siShownLight.ambient[k] >= 0.0f && siShownLight.ambient[k] <= 4.0f))
            return;
        total += siShownLight.ambient[k];
    }
    siShownLit = total > 0.05f;
}

static void siAdoptPending(void)
{
    siLock();
    if (siPendingState != SI_NONE) {
        if (strcmp(siPendingKey, siWantKey) == 0) {
            siRetireShown();
            siShownState = siPendingState;
            memcpy(siShownKey, siPendingKey, sizeof(siShownKey));
            if (siPendingState == SI_MODEL) {
                siShown = siPending;
                siShownLight = siPendingLight;
                if (siShown.ps1Frames) {
                    int frame;
                    for (frame = 0; frame < siShown.ps1Frames; frame++) {
                        GSTEXTURE *tex = &siPs1Tex[frame];
                        tex->Width = tex->Height = 16;
                        tex->PSM = GS_PSM_CT16;
                        tex->Mem = (u32 *)(siShown.texels + frame * 256);
                        tex->Filter = GS_FILTER_NEAREST;
                        tex->ClutStorageMode = GS_CLUT_STORAGE_CSM1;
                        tex->Delayed = 1;
                    }
                } else if (siShown.texels != NULL) {
                    siTex.Width = SAVEICON_TEX_SIZE;
                    siTex.Height = SAVEICON_TEX_SIZE;
                    siTex.PSM = GS_PSM_CT16;
                    siTex.Mem = (u32 *)siShown.texels;
                    siTex.Filter = GS_FILTER_LINEAR;
                    siTex.ClutStorageMode = GS_CLUT_STORAGE_CSM1;
                    siTex.Delayed = 1;
                }
                if (!siShown.ps1Frames) {
                    siMeasure();
                    siPrepareLight();
                }
                siShownSince = clock();
                siOrderValid = 0;
            }
        } else if (siPendingState == SI_MODEL) {
            saveIconFreeModel(&siPending);
        }
        memset(&siPending, 0, sizeof(siPending));
        siPendingState = SI_NONE;
    }
    siUnlock();
}

static void siSetWant(const char *key, const char *startup, const char *vmc0, const char *vmc1)
{
    siLock();
    snprintf(siWantKey, sizeof(siWantKey), "%s", key);
    snprintf(siWantStartup, sizeof(siWantStartup), "%s", startup);
    snprintf(siWantVmc[0], sizeof(siWantVmc[0]), "%s", vmc0);
    snprintf(siWantVmc[1], sizeof(siWantVmc[1]), "%s", vmc1);
    siWantPs1 = 0;
    siUnlock();
}

void saveIconSelect(const char *startup, const char *vmc0, const char *vmc1, int vmcKnown)
{
    char key[SI_KEY_SIZE];

    if (startup == NULL)
        startup = "";
    if (strcmp(startup, siSelStartup) != 0 || siWantPs1) {
        snprintf(siSelStartup, sizeof(siSelStartup), "%s", startup);
        siSelSince = clock();
        siQueuedKey[0] = '\0';
        siSetWant("", "", "", ""); // nothing on screen until this row's own icon is known
    }
    if (startup[0] == '\0')
        return;
    // Its per-game config names its VMCs. Wait for it, but not forever: a config that never arrives
    // must not cost the memory cards.
    if (!vmcKnown || vmc0 == NULL || vmc1 == NULL) {
        if ((clock() - siSelSince) < (clock_t)SI_CONFIG_WAIT_US)
            return;
        vmc0 = vmc1 = "";
    }
    snprintf(key, sizeof(key), "%s|%s|%s", startup, vmc0, vmc1);
    if (strcmp(key, siWantKey) != 0)
        siSetWant(key, startup, vmc0, vmc1);
    // Read once the cursor has settled, so scrolling past games never touches the cards.
    if ((clock() - siSelSince) >= (clock_t)SI_SETTLE_US && strcmp(siWantKey, siShownKey) != 0 &&
        strcmp(siWantKey, siQueuedKey) != 0) {
        memcpy(siQueuedKey, siWantKey, sizeof(siQueuedKey));
        if (ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&siLoadAction) != IO_OK)
            siQueuedKey[0] = '\0'; // try again next frame
    }
}

void saveIconSelectPs1(const char *directory, const char *partition, int ember)
{
    char key[SI_KEY_SIZE];
    int kind = ember ? 2 : 1;

    if (directory == NULL || directory[0] == '\0' || partition == NULL ||
        strlen(directory) >= SAVEICON_PATH_SIZE || strlen(partition) >= SAVEICON_PATH_SIZE) {
        saveIconSelect(NULL, "", "", 1);
        return;
    }
    snprintf(key, sizeof(key), "PS1%d|%s|%s", kind, directory, partition);
    if (strcmp(key, siWantKey) != 0) {
        siSelStartup[0] = '\0';
        siSelSince = clock();
        siQueuedKey[0] = '\0';
        siLock();
        snprintf(siWantKey, sizeof(siWantKey), "%s", key);
        snprintf(siWantVmc[0], sizeof(siWantVmc[0]), "%s", directory);
        snprintf(siWantVmc[1], sizeof(siWantVmc[1]), "%s", partition);
        siWantPs1 = kind;
        siUnlock();
    }
    if (clock() - siSelSince >= (clock_t)SI_SETTLE_US && strcmp(key, siShownKey) != 0 && strcmp(key, siQueuedKey) != 0) {
        snprintf(siQueuedKey, sizeof(siQueuedKey), "%s", key);
        if (ioPutRequestUnlessWaiting(IO_CUSTOM_SIMPLEACTION, (void *)&siLoadAction) != IO_OK)
            siQueuedKey[0] = '\0';
    }
}

static void siFreeBuffers(void)
{
    free(siX);
    free(siY);
    free(siZ);
    free(siDepth);
    free(siDrawXY);
    free(siDrawUV);
    free(siCol);
    free(siDrawCol);
    free(siOrder);
    siX = siY = siZ = siDepth = siDrawXY = siDrawUV = NULL;
    siCol = siDrawCol = NULL;
    siOrder = NULL;
    siBufVerts = 0;
    siOrderValid = 0;
}

static int siEnsureBuffers(int verts)
{
    if (verts <= siBufVerts)
        return 1;
    siFreeBuffers();
    siX = malloc(sizeof(float) * verts);
    siY = malloc(sizeof(float) * verts);
    siZ = malloc(sizeof(float) * verts);
    siDepth = malloc(sizeof(float) * (verts / 3));
    siDrawXY = malloc(sizeof(float) * 2 * verts);
    siDrawUV = malloc(sizeof(float) * 2 * verts);
    siCol = malloc(sizeof(u64) * verts);
    siDrawCol = malloc(sizeof(u64) * verts);
    siOrder = malloc(sizeof(int) * (verts / 3));
    if (siX == NULL || siY == NULL || siZ == NULL || siDepth == NULL || siDrawXY == NULL || siDrawUV == NULL ||
        siCol == NULL || siDrawCol == NULL || siOrder == NULL) {
        siFreeBuffers();
        return 0;
    }
    siBufVerts = verts;
    return 1;
}

void saveIconReset(void)
{
    siLock();
    if (siPendingState == SI_MODEL)
        saveIconFreeModel(&siPending);
    memset(&siPending, 0, sizeof(siPending));
    siPendingState = SI_NONE;
    siWantKey[0] = '\0';
    siWantPs1 = 0;
    siUnlock();
    siRetireShown();
    siFreeRetired();
    siFreeBuffers();
    siSelStartup[0] = '\0';
    siQueuedKey[0] = '\0';
}

// ---- drawing (GUI thread) ---------------------------------------------------------------------

static u64 siShade(const unsigned char *rgba, float nx, float ny, float nz)
{
    float f[3] = {1.0f, 1.0f, 1.0f};
    int i, k, c[3];

    if (siShownLit) {
        for (k = 0; k < 3; k++)
            f[k] = siShownLight.ambient[k];
        for (i = 0; i < 3; i++) {
            float d = nx * siShownLight.dir[i][0] + ny * siShownLight.dir[i][1] + nz * siShownLight.dir[i][2];
            // Two-sided: which way the format's light vectors point must not be decided by a guess,
            // since the wrong sign would leave the front of every icon unlit.
            if (d < 0.0f)
                d = -d;
            for (k = 0; k < 3; k++)
                f[k] += siShownLight.color[i][k] * d;
        }
    }
    for (k = 0; k < 3; k++) {
        c[k] = (int)(rgba[k] * (f[k] < 1.0f ? f[k] : 1.0f));
        if (c[k] > 0xFF)
            c[k] = 0xFF;
    }
    return GS_SETREG_RGBAQ(c[0], c[1], c[2], 0x80, 0x00);
}

void saveIconDraw(int cx, int cy, int w, int h, float xScale)
{
    float weights[SAVEICON_MAX_SHAPES], sum, seconds, angle, cosA, sinA, scale, t;
    int v, s, i, k, tris;

    siAdoptPending();
    if ((siRetired.verts != 0 || siRetired.texels != NULL) && ++siRetiredFrames > 2)
        siFreeRetired();
    if (siShownState != SI_MODEL || siWantKey[0] == '\0' || strcmp(siShownKey, siWantKey) != 0 || w <= 0 || h <= 0)
        return;
    if (siShown.ps1Frames) {
        int side = w < h ? w : h;
        int drawW = (int)(side * xScale);
        int frame = (int)(((float)(clock() - siShownSince) / CLOCKS_PER_SEC) /
                          (siShown.ps1Frames == 2 ? 0.32f : 0.22f)) %
                    siShown.ps1Frames;
        rmDrawPixmap(&siPs1Tex[frame], cx - drawW / 2, cy - side / 2, ALIGN_NONE,
                     drawW, side, SCALING_NONE, gDefaultCol, 0);
        return;
    }
    if (!siEnsureBuffers(siShown.verts))
        return;
    tris = siShown.verts / 3;
    if (!siOrderValid) {
        for (i = 0; i < tris; i++)
            siOrder[i] = i;
        siOrderValid = 1;
    }

    seconds = (float)(clock() - siShownSince) / (float)CLOCKS_PER_SEC;
    angle = fmodf(seconds, SI_SPIN_SECONDS) * (2.0f * 3.14159265f / SI_SPIN_SECONDS);
    cosA = cosf(angle);
    sinA = sinf(angle);
    t = 0.0f;
    if (siShown.frameLength > 1)
        t = fmodf(seconds * 60.0f * siShown.speed, (float)siShown.frameLength);
    sum = saveIconShapeWeights(&siShown, t, weights);

    // The whole animation's extent around the spin axis fits the box at every angle.
    scale = (w * 0.5f) / siRadius;
    if ((h * 0.5f) / siHalfHeight < scale)
        scale = (h * 0.5f) / siHalfHeight;

    for (v = 0; v < siShown.verts; v++) {
        const short *n = &siShown.normal[v * 3];
        float p[3] = {0.0f, 0.0f, 0.0f};

        for (s = 0; s < siShown.shapes; s++) {
            const short *q = &siShown.pos[(s * siShown.verts + v) * 3];
            if (weights[s] <= 0.0f)
                continue;
            for (k = 0; k < 3; k++)
                p[k] += weights[s] * q[k];
        }
        for (k = 0; k < 3; k++)
            p[k] = p[k] / sum - siPivot[k];
        // A turn about the vertical axis; icon space already has +y down the screen.
        siX[v] = cx + (p[0] * cosA + p[2] * sinA) * scale * xScale;
        siY[v] = cy + p[1] * scale;
        siZ[v] = p[2] * cosA - p[0] * sinA;
        siCol[v] = siShade(&siShown.rgba[v * 4], (n[0] * cosA + n[2] * sinA) / 4096.0f, n[1] / 4096.0f,
                           (n[2] * cosA - n[0] * sinA) / 4096.0f);
    }

    // Painter's order, far first: +z points into the screen. Insertion sort, because last frame's
    // order is nearly right after a small turn, which makes this close to one pass.
    for (i = 0; i < tris; i++)
        siDepth[i] = siZ[i * 3] + siZ[i * 3 + 1] + siZ[i * 3 + 2];
    for (i = 1; i < tris; i++) {
        int cur = siOrder[i], j = i - 1;
        float d = siDepth[cur];
        while (j >= 0 && siDepth[siOrder[j]] < d) {
            siOrder[j + 1] = siOrder[j];
            j--;
        }
        siOrder[j + 1] = cur;
    }

    for (i = 0; i < tris; i++) {
        int a = siOrder[i] * 3;
        for (k = 0; k < 3; k++) {
            int dst = i * 3 + k, src = a + k;
            siDrawXY[dst * 2] = siX[src];
            siDrawXY[dst * 2 + 1] = siY[src];
            // 4.12 UVs of a 128-texel texture: 4096 is the full width, so texels = uv / 32.
            siDrawUV[dst * 2] = siShown.uv[src * 2] / 32.0f;
            siDrawUV[dst * 2 + 1] = siShown.uv[src * 2 + 1] / 32.0f;
            siDrawCol[dst] = siCol[src];
        }
    }
    rmDrawTriangles(siShown.texels != NULL ? &siTex : NULL, tris, siDrawXY, siDrawUV, siDrawCol);
}

#endif // SAVEICON_HOST_TEST
