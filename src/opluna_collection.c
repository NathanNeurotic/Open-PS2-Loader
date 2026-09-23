/*
 Copyright 2026, dnunezx
 Licensed under the Academic Free License version 3.0.
 */

#include "include/opl.h"
#include "include/gui.h"
#include "include/opluna.h"
#include "include/renderman.h"
#include "include/themes.h"
#include "include/fntsys.h"
#include "include/pad.h"
#include "include/textures.h"
#include "include/ioman.h"
#include "include/lang.h"

#include <malloc.h>
#include <stdlib.h>
#include <string.h>

#define COLLECTION_THUMB_COUNT 8
#define COLLECTION_THUMB_SIZE 128
#define COLLECTION_GLIDE_FRAMES 25
#define COLLECTION_ART_RETRY_FRAMES 15
#define COLLECTION_ART_FOCAL 1
#define COLLECTION_ART_THUMB 2
#define COLLECTION_ART_NEIGHBOR 3

static const int thumbnailPriority[] = {1, -1, 2, 3, 4, 5, 6, -2};
#define COLLECTION_VISIBLE_THUMB_COUNT 7

typedef struct
{
    int index;
    unsigned int generation;
    unsigned int usedAt;
    GSTEXTURE texture;
    int attempted;
} collection_thumb_t;

static collection_thumb_t thumbnails[COLLECTION_THUMB_COUNT];
/* gsKit tracks textures by address, so move the slot pointers rather than
   copying a texture after it has been bound for drawing. */
static GSTEXTURE coverSlots[4];
static GSTEXTURE *focalCover = &coverSlots[0];
static GSTEXTURE *outgoingCover = &coverSlots[1];
static GSTEXTURE *neighborCover[2] = {&coverSlots[2], &coverSlots[3]};
static int neighborIndex[2] = {-1, -1};
static int neighborAttempted[2];
static int focalIndex = -1;
static int outgoingIndex = -1;
static int selectedIndex;
static opluna_identity_t selectedIdentity;
static int selectedIdentityValid;
static unsigned int seenGeneration;
static int flowStartOffset;
static int flowStartFrame;
static int browseDirection = 1;
static int focalAttempted;
static unsigned int viewEpoch;
static int artRetryIndex = -1;
static int artRetryAfterFrame;

/* One reusable request bounds decoded art memory and work queued ahead of a
   newly selected cover. The worker publishes by setting state to 2 last. */
static struct
{
    volatile int state; /* 0 idle, 1 loading, 2 ready */
    int kind;
    int index;
    int result;
    unsigned int generation;
    unsigned int epoch;
    char path[256];
    GSTEXTURE texture;
} artJob;

static void releaseTexture(GSTEXTURE *texture)
{
    if (texture->Mem != NULL)
        rmUnloadTexture(texture);
    texFree(texture);
    memset(texture, 0, sizeof(*texture));
}

static void shrinkToThumbnail(GSTEXTURE *texture);

static void loadArtwork(void *data)
{
    (void)data;
    artJob.result = texDiscoverLoad(&artJob.texture, artJob.path, -1);
    if (artJob.result >= 0 && artJob.kind == COLLECTION_ART_THUMB)
        shrinkToThumbnail(&artJob.texture);
    artJob.state = 2;
}

void oplunaCollectionInit(void)
{
    ioRegisterHandler(IO_OPLUNA_LOAD_ART, &loadArtwork);
}

static int queueArtwork(int index, int kind)
{
    if (artJob.state != 0)
        return 0;
    if (index == artRetryIndex && guiFrameId < artRetryAfterFrame)
        return 0;
    if (oplunaSquarePathAt(index, artJob.path, sizeof(artJob.path)) < 0)
        return -1;
    artJob.kind = kind;
    artJob.index = index;
    artJob.generation = seenGeneration;
    artJob.epoch = viewEpoch;
    artJob.result = -1;
    memset(&artJob.texture, 0, sizeof(artJob.texture));
    artJob.state = 1;
    if (ioPutRequest(IO_OPLUNA_LOAD_ART, &artJob) != IO_OK) {
        artJob.state = 0;
        return 0;
    }
    return 1;
}

void oplunaCollectionEnd(void)
{
    int i;
    viewEpoch++;
    if (artJob.state == 2) {
        releaseTexture(&artJob.texture);
        artJob.state = 0;
    }
    releaseTexture(focalCover);
    releaseTexture(outgoingCover);
    for (i = 0; i < 2; i++) {
        releaseTexture(neighborCover[i]);
        neighborIndex[i] = -1;
        neighborAttempted[i] = 0;
    }
    for (i = 0; i < COLLECTION_THUMB_COUNT; i++) {
        releaseTexture(&thumbnails[i].texture);
        thumbnails[i].index = -1;
        thumbnails[i].attempted = 0;
    }
    focalIndex = -1;
    focalAttempted = 0;
    outgoingIndex = -1;
    flowStartOffset = 0;
    browseDirection = 1;
    artRetryIndex = -1;
}

static void syncGeneration(void)
{
    if (seenGeneration != oplunaGeneration()) {
        int previous = selectedIdentityValid ? oplunaFindIdentity(&selectedIdentity) : -1;
        oplunaCollectionEnd();
        seenGeneration = oplunaGeneration();
        if (previous >= 0)
            selectedIndex = previous;
    }
    if (selectedIndex >= oplunaCount())
        selectedIndex = oplunaCount() > 0 ? oplunaCount() - 1 : 0;
    if (oplunaCount() > 0) {
        selectedIdentityValid = oplunaIdentityAt(selectedIndex, &selectedIdentity) == 0;
    }
}

void oplunaCollectionSelectFromNative(item_list_t *support, int itemId)
{
    opluna_identity_t identity;
    const char *title, *startup;
    int index;

    if (support == NULL || itemId < 0 || support->itemGetCount == NULL ||
        support->itemGetName == NULL || support->itemGetStartup == NULL ||
        itemId >= support->itemGetCount(support))
        return;
    title = support->itemGetName(support, itemId);
    startup = support->itemGetStartup(support, itemId);
    if (title == NULL || startup == NULL)
        return;
    identity.mode = support->mode;
    identity.itemId = itemId;
    snprintf(identity.title, sizeof(identity.title), "%s", title);
    snprintf(identity.startup, sizeof(identity.startup), "%s", startup);
    index = oplunaFindIdentity(&identity);
    if (index < 0)
        return;
    if (index != selectedIndex) {
        oplunaCollectionEnd();
        selectedIndex = index;
    }
    selectedIdentity = identity;
    selectedIdentityValid = 1;
}

static int wrapIndex(int index, int count)
{
    if (count <= 0)
        return -1;
    index %= count;
    return index < 0 ? index + count : index;
}

static int currentFlowOffset(void)
{
    int elapsed = guiFrameId - flowStartFrame;
    int remaining;
    if (elapsed < 0 || elapsed >= COLLECTION_GLIDE_FRAMES)
        return 0;
    remaining = COLLECTION_GLIDE_FRAMES - elapsed;
    return flowStartOffset * remaining * remaining * remaining /
           (COLLECTION_GLIDE_FRAMES * COLLECTION_GLIDE_FRAMES * COLLECTION_GLIDE_FRAMES);
}

static void moveSelection(int direction)
{
    int count = oplunaCount();
    int offset;
    if (count < 2)
        return;
    offset = currentFlowOffset() + direction * 1000;
    if (offset > 3000)
        offset = 3000;
    if (offset < -3000)
        offset = -3000;
    selectedIndex = wrapIndex(selectedIndex + direction, count);
    browseDirection = direction;
    selectedIdentityValid = oplunaIdentityAt(selectedIndex, &selectedIdentity) == 0;
    flowStartOffset = offset;
    flowStartFrame = guiFrameId;
}

static void shrinkToThumbnail(GSTEXTURE *texture)
{
    int bpp, x, y, sourceWidth, sourceHeight;
    unsigned char *source, *pixels;
    if (texture->Mem == NULL || texture->Width <= 0 || texture->Height <= 0)
        return;
    if (texture->PSM == GS_PSM_CT24)
        bpp = 3;
    else if (texture->PSM == GS_PSM_CT32)
        bpp = 4;
    else
        return;
    pixels = memalign(128, COLLECTION_THUMB_SIZE * COLLECTION_THUMB_SIZE * bpp);
    if (pixels == NULL)
        return;
    source = (unsigned char *)texture->Mem;
    sourceWidth = texture->Width;
    sourceHeight = texture->Height;
    for (y = 0; y < COLLECTION_THUMB_SIZE; y++) {
        int sourceY1 = y * sourceHeight / COLLECTION_THUMB_SIZE;
        int sourceY2 = (y + 1) * sourceHeight / COLLECTION_THUMB_SIZE;
        if (sourceY2 <= sourceY1)
            sourceY2 = sourceY1 + 1;
        for (x = 0; x < COLLECTION_THUMB_SIZE; x++) {
            int sourceX1 = x * sourceWidth / COLLECTION_THUMB_SIZE;
            int sourceX2 = (x + 1) * sourceWidth / COLLECTION_THUMB_SIZE;
            unsigned int channels[4] = {0, 0, 0, 0};
            int sourceX, sourceY, channel, samples = 0;
            unsigned char *pixel = pixels + (y * COLLECTION_THUMB_SIZE + x) * bpp;
            if (sourceX2 <= sourceX1)
                sourceX2 = sourceX1 + 1;
            for (sourceY = sourceY1; sourceY < sourceY2; sourceY++) {
                for (sourceX = sourceX1; sourceX < sourceX2; sourceX++) {
                    const unsigned char *sample = source + (sourceY * sourceWidth + sourceX) * bpp;
                    for (channel = 0; channel < bpp; channel++)
                        channels[channel] += sample[channel];
                    samples++;
                }
            }
            for (channel = 0; channel < bpp; channel++)
                pixel[channel] = channels[channel] / samples;
        }
    }
    free(texture->Mem);
    texture->Mem = (u32 *)pixels;
    texture->Width = COLLECTION_THUMB_SIZE;
    texture->Height = COLLECTION_THUMB_SIZE;
    texture->Vram = 0;
    texture->VramClut = 0;
}

static collection_thumb_t *findThumbnail(int index)
{
    int i;
    for (i = 0; i < COLLECTION_THUMB_COUNT; i++) {
        if (thumbnails[i].attempted && thumbnails[i].generation == seenGeneration && thumbnails[i].index == index) {
            thumbnails[i].usedAt = guiFrameId;
            return &thumbnails[i];
        }
    }
    return NULL;
}

static collection_thumb_t *reserveThumbnail(int index)
{
    int i, slot = -1;
    unsigned int oldest = ~0u;
    collection_thumb_t *thumb;
    if (index < 0 || findThumbnail(index) != NULL)
        return NULL;
    for (i = 0; i < COLLECTION_THUMB_COUNT; i++) {
        if (!thumbnails[i].attempted || thumbnails[i].generation != seenGeneration) {
            slot = i;
            break;
        }
        if (thumbnails[i].usedAt < oldest) {
            oldest = thumbnails[i].usedAt;
            slot = i;
        }
    }
    if (slot < 0)
        return NULL;
    thumb = &thumbnails[slot];
    releaseTexture(&thumb->texture);
    thumb->index = index;
    thumb->generation = seenGeneration;
    thumb->usedAt = guiFrameId;
    thumb->attempted = 1;
    return thumb;
}

static void preserveVisibleCover(int index, GSTEXTURE *cover)
{
    collection_thumb_t *thumb;
    int count = oplunaCount();
    int relative, visible = 0;
    if (index < 0 || cover->Mem == NULL || count < 2)
        return;
    for (relative = -1; relative <= 6 && relative < count; relative++) {
        if (wrapIndex(selectedIndex + relative, count) == index) {
            visible = 1;
            break;
        }
    }
    if (!visible)
        return;
    thumb = findThumbnail(index);
    if (thumb != NULL && thumb->texture.Mem != NULL)
        return;
    if (thumb == NULL)
        thumb = reserveThumbnail(index);
    if (thumb == NULL)
        return;
    releaseTexture(&thumb->texture);
    rmUnloadTexture(cover);
    shrinkToThumbnail(cover);
    cover->Vram = 0;
    cover->VramClut = 0;
    thumb->texture = *cover;
    memset(cover, 0, sizeof(*cover));
}

static int thumbnailStillNeeded(int index)
{
    int count = oplunaCount();
    int i;
    if (count < 1)
        return 0;
    if (index == selectedIndex && focalCover->Mem == NULL)
        return 1;
    for (i = 0; i < (focalCover->Mem == NULL ? COLLECTION_VISIBLE_THUMB_COUNT :
                     (int)(sizeof(thumbnailPriority) / sizeof(thumbnailPriority[0]))); i++) {
        if (index == wrapIndex(selectedIndex + thumbnailPriority[i], count) &&
            (index != outgoingIndex || outgoingCover->Mem == NULL))
            return 1;
    }
    return 0;
}

static void acceptArtwork(void)
{
    collection_thumb_t *thumb;
    int i;
    if (artJob.state != 2)
        return;
    if (artJob.generation == seenGeneration && artJob.epoch == viewEpoch) {
        if (artJob.result < 0 && artJob.result != ERR_BAD_FILE) {
            /* A busy device or interrupted read is not evidence that the art
               is absent. Retry after a short pause instead of memoizing it. */
            artRetryIndex = artJob.index;
            artRetryAfterFrame = guiFrameId + COLLECTION_ART_RETRY_FRAMES;
            if (artJob.kind == COLLECTION_ART_FOCAL && artJob.index == focalIndex)
                focalAttempted = 0;
            else if (artJob.kind == COLLECTION_ART_NEIGHBOR) {
                for (i = 0; i < 2; i++) {
                    if (neighborIndex[i] == artJob.index)
                        neighborAttempted[i] = 0;
                }
            }
        }
        if (artJob.result >= 0 && artJob.kind == COLLECTION_ART_FOCAL && artJob.index == focalIndex) {
            releaseTexture(focalCover);
            *focalCover = artJob.texture;
            memset(&artJob.texture, 0, sizeof(artJob.texture));
        } else if (artJob.result >= 0 && artJob.kind == COLLECTION_ART_NEIGHBOR) {
            if (artJob.index == focalIndex && focalCover->Mem == NULL) {
                *focalCover = artJob.texture;
                focalAttempted = 1;
                memset(&artJob.texture, 0, sizeof(artJob.texture));
            } else {
                for (i = 0; i < 2; i++) {
                    if (neighborIndex[i] == artJob.index && neighborCover[i]->Mem == NULL) {
                        *neighborCover[i] = artJob.texture;
                        memset(&artJob.texture, 0, sizeof(artJob.texture));
                        break;
                    }
                }
            }
        } else if ((artJob.result >= 0 || artJob.result == ERR_BAD_FILE) &&
                   artJob.kind == COLLECTION_ART_THUMB &&
                   thumbnailStillNeeded(artJob.index) &&
                   (thumb = reserveThumbnail(artJob.index)) != NULL) {
            if (artJob.result >= 0) {
                thumb->texture = artJob.texture;
                memset(&artJob.texture, 0, sizeof(artJob.texture));
            }
        }
    }
    releaseTexture(&artJob.texture);
    artJob.state = 0;
}

static int syncFocalCover(void)
{
    int previousIndex, i;
    if (focalIndex == selectedIndex)
        return 0;
    previousIndex = focalIndex;
    if (selectedIndex == outgoingIndex && outgoingCover->Mem != NULL) {
        GSTEXTURE *previousFocal = focalCover;
        focalCover = outgoingCover;
        outgoingCover = previousFocal;
        outgoingIndex = previousIndex;
        focalIndex = selectedIndex;
        focalAttempted = 1;
        return 1;
    }
    for (i = 0; i < 2; i++) {
        if (selectedIndex == neighborIndex[i] && neighborCover[i]->Mem != NULL) {
            GSTEXTURE *emptyCover;
            preserveVisibleCover(outgoingIndex, outgoingCover);
            releaseTexture(outgoingCover);
            emptyCover = outgoingCover;
            outgoingCover = focalCover;
            focalCover = neighborCover[i];
            neighborCover[i] = emptyCover;
            neighborIndex[i] = -1;
            neighborAttempted[i] = 0;
            outgoingIndex = previousIndex;
            focalIndex = selectedIndex;
            focalAttempted = 1;
            return 1;
        }
    }
    preserveVisibleCover(outgoingIndex, outgoingCover);
    releaseTexture(outgoingCover);
    {
        GSTEXTURE *previousFocal = focalCover;
        focalCover = outgoingCover;
        outgoingCover = previousFocal;
    }
    outgoingIndex = previousIndex;
    focalIndex = selectedIndex;
    focalAttempted = 0;
    return 1;
}

static void requestFocalCover(void)
{
    if (oplunaCount() > 0 && !focalAttempted && artJob.state == 0 && currentFlowOffset() == 0) {
        if (queueArtwork(selectedIndex, COLLECTION_ART_FOCAL) != 0)
            focalAttempted = 1;
    }
}

static void requestNeighborCovers(void)
{
    int count = oplunaCount();
    int flow = currentFlowOffset();
    int i;
    if (count < 2 || focalCover->Mem == NULL || artJob.state != 0)
        return;
    for (i = 0; i < 2; i++) {
        int index = wrapIndex(selectedIndex + (i == 0 ? 1 : -1), count);
        int result;
        if (flow != 0 && i != (browseDirection > 0 ? 0 : 1))
            continue;
        if ((i == 1 && index == neighborIndex[0]) ||
            (index == outgoingIndex && outgoingCover->Mem != NULL)) {
            preserveVisibleCover(neighborIndex[i], neighborCover[i]);
            releaseTexture(neighborCover[i]);
            neighborIndex[i] = -1;
            neighborAttempted[i] = 0;
            continue;
        }
        if (neighborIndex[i] != index) {
            preserveVisibleCover(neighborIndex[i], neighborCover[i]);
            releaseTexture(neighborCover[i]);
            neighborIndex[i] = index;
            neighborAttempted[i] = 0;
        }
        if (neighborAttempted[i])
            continue;
        result = queueArtwork(index, COLLECTION_ART_NEIGHBOR);
        if (result != 0)
            neighborAttempted[i] = 1;
        if (result > 0)
            return;
    }
}

static void loadNearbyThumbnail(void)
{
    int count = oplunaCount();
    int i;
    if (count < 2)
        return;
    if (focalCover->Mem == NULL && findThumbnail(selectedIndex) == NULL) {
        int result = queueArtwork(selectedIndex, COLLECTION_ART_THUMB);
        if (result < 0)
            reserveThumbnail(selectedIndex);
        if (result >= 0)
            return;
    }
    for (i = 0; i < (focalCover->Mem == NULL ? COLLECTION_VISIBLE_THUMB_COUNT :
                     (int)(sizeof(thumbnailPriority) / sizeof(thumbnailPriority[0]))); i++) {
        int index = wrapIndex(selectedIndex + thumbnailPriority[i], count);
        int result;
        if (index == selectedIndex ||
            (index == outgoingIndex && outgoingCover->Mem != NULL) ||
            findThumbnail(index) != NULL)
            continue;
        result = queueArtwork(index, COLLECTION_ART_THUMB);
        if (result < 0) {
            reserveThumbnail(index);
            continue;
        }
        break;
    }
}

void oplunaCollectionPrepare(void)
{
    syncGeneration();
    acceptArtwork();
    syncFocalCover();
    requestFocalCover();
    requestNeighborCovers();
    if (artJob.state == 0)
        loadNearbyThumbnail();
}

int oplunaCollectionReady(void)
{
    int count = oplunaCount();
    int i;
    if (count == 0)
        return 1;
    if (!focalAttempted || (artJob.state != 0 && artJob.kind == COLLECTION_ART_FOCAL))
        return 0;
    for (i = 0; i < COLLECTION_VISIBLE_THUMB_COUNT; i++) {
        int index = wrapIndex(selectedIndex + thumbnailPriority[i], count);
        if (index != selectedIndex && index != outgoingIndex && findThumbnail(index) == NULL)
            return 0;
    }
    return 1;
}

static GSTEXTURE *textureFor(int index)
{
    collection_thumb_t *thumb;
    int i;
    if (index == selectedIndex && focalCover->Mem != NULL)
        return focalCover;
    if (index == outgoingIndex && outgoingCover->Mem != NULL)
        return outgoingCover;
    for (i = 0; i < 2; i++) {
        if (index == neighborIndex[i] && neighborCover[i]->Mem != NULL)
            return neighborCover[i];
    }
    thumb = findThumbnail(index);
    return thumb != NULL && thumb->texture.Mem != NULL ? &thumb->texture : NULL;
}

static int curvePercent(int distance, const unsigned char *points, int length)
{
    int segment, fraction;
    if (distance <= 0)
        return points[0] * 1000;
    segment = distance / 1000;
    if (segment >= length - 1)
        return points[length - 1] * 1000;
    fraction = distance - segment * 1000;
    return points[segment] * 1000 + (points[segment + 1] - points[segment]) * fraction;
}

static void drawCover(int index, int position, int focalSize, int focalCenterX, int centerY, int width)
{
    static const unsigned char sizes[] = {100, 44, 41, 38, 30, 22, 14};
    static const unsigned char offsets[] = {0, 50, 72, 93, 112, 127, 138};
    GSTEXTURE *texture = textureFor(index);
    int distance = abs(position);
    int size, centerX, x, y, emphasis, visibility, colorValue;
    if (position >= 0) {
        size = focalSize * curvePercent(distance, sizes, sizeof(sizes)) / 100000;
        centerX = focalCenterX - focalSize * curvePercent(distance, offsets, sizeof(offsets)) / 100000;
    } else {
        int progress = distance > 1000 ? 1000 : distance;
        int squared = progress * progress / 1000;
        size = focalSize * (1000 + 750 * squared / 1000) / 1000;
        centerX = focalCenterX + focalSize * 160 * squared / 100000;
    }
    x = centerX - size / 2;
    y = centerY - size / 2 + (position > 0 ? distance * 3 / 2000 : 0);
    if (x + size < 24 || x > width - 12)
        return;
    emphasis = 1000 - (distance < 1000 ? distance : 1000);
    visibility = distance <= 1000 ? 1000 : 1000 - (distance - 1000) * 850 / 5000;
    if (visibility < 150)
        visibility = 150;
    colorValue = (0x58 + emphasis * 0x28 / 1000) * visibility / 1000;
    if (texture != NULL) {
        rmDrawPixmap(texture, x, y, ALIGN_NONE, size, size, SCALING_NONE,
                     GS_SETREG_RGBA(colorValue, colorValue, colorValue, 0x80), 0);
    } else {
        rmDrawRect(x, y, size, size, GS_SETREG_RGBA(0x05, 0x16, 0x35, 0x60));
        if (position == 0 && size > 120)
            fntRenderString(gTheme->fonts[0], centerX, centerY, ALIGN_HCENTER, size - 20, 0, "ART UNAVAILABLE",
                            GS_SETREG_RGBA(0x9A, 0xC1, 0xD8, 0x80));
    }
}

static void drawRightAlignedText(int rightX, int y, const char *label, u64 color)
{
    int font = gTheme->fonts[0];
    int labelWidth = rmUnScaleX(fntCalcDimensions(font, label));
    fntRenderString(font, rightX - labelWidth, y, ALIGN_LEFT, 0, 0, label, color);
}

void oplunaCollectionLoadingPosition(int width, int height, int iconSize, int *x, int *y)
{
    char counter[32];
    int count = oplunaCount();
    int textWidth;
    snprintf(counter, sizeof(counter), "%d/%d", count ? selectedIndex + 1 : 0, count);
    textWidth = rmUnScaleX(fntCalcDimensions(gTheme->fonts[0], counter));
    *x = width - 38 - textWidth - 9 - iconSize;
    *y = height - 83;
}

void oplunaCollectionRender(int width, int height)
{
    int count, size, focalX, focalCenterX, centerY, flow, relative, seen[8], seenCount = 0;
    char counter[32];
    const u64 white = GS_SETREG_RGBA(0xE9, 0xF7, 0xFF, 0x80);
    const u64 muted = GS_SETREG_RGBA(0x9B, 0xBD, 0xDB, 0x80);

    oplunaCollectionPrepare();
    count = oplunaCount();
    flow = currentFlowOffset();

    guiDrawBGPlasma();
    rmDrawRect(0, 0, width, height, GS_SETREG_RGBA(0x03, 0x09, 0x20, 0x58));
    rmDrawRect(0, height - 39, width, 39, GS_SETREG_RGBA(0x02, 0x07, 0x19, 0x62));

    size = (height - 118) * 76 / 100;
    if (size > width * 38 / 100)
        size = width * 38 / 100;
    size = size * 115 / 100;
    focalX = width - size - 37;
    focalCenterX = focalX + size / 2;
    centerY = 75 + size / 2;

    rmDrawRect(24, 79, focalX - 51, 2, GS_SETREG_RGBA(0x45, 0xB2, 0xF0, 0x24));
    rmDrawRect(24, 79, 2, height - 159, GS_SETREG_RGBA(0x45, 0xB2, 0xF0, 0x1B));
    fntRenderString(gTheme->fonts[0], 54, height - 102, ALIGN_LEFT, 0, 0, "COLLECTION", white);
    fntRenderString(gTheme->fonts[0], 54, height - 77, ALIGN_LEFT, 0, 0, "PS2 LIBRARY", muted);

    if (count == 0) {
        fntRenderString(gTheme->fonts[0], 56, centerY, ALIGN_LEFT, focalX - 70, 0, "NO GAMES FOUND", muted);
    } else {
        // Draw the far tail first, then the focal jacket and outgoing foreground.
        for (relative = 6; relative >= 0; relative--) {
            int index = wrapIndex(selectedIndex + relative, count);
            int i, duplicate = 0;
            // A short library wraps before the end of the visible tail.
            // Keep only the nearest occurrence so focus is always drawn.
            if (relative >= count)
                continue;
            // During forward motion the previous focal jacket exits to the
            // right. In a short library it can also wrap into this tail.
            if (flow > 0 && relative > 0 && index == outgoingIndex)
                continue;
            for (i = 0; i < seenCount; i++)
                duplicate |= seen[i] == index;
            if (duplicate)
                continue;
            seen[seenCount++] = index;
            drawCover(index, relative * 1000 + flow, size, focalCenterX, centerY, width);
        }
        if (count > 1) {
            int index = wrapIndex(selectedIndex - 1, count);
            int i, duplicate = 0;
            for (i = 0; i < seenCount; i++)
                duplicate |= seen[i] == index;
            if (!duplicate)
                drawCover(index, -1000 + flow, size, focalCenterX, centerY, width);
        }
    }

    snprintf(counter, sizeof(counter), "%d/%d", count ? selectedIndex + 1 : 0, count);
    drawRightAlignedText(width - 38, height - 83, counter, white);
    {
        int hintTexts[3] = {_STR_RUN, _STR_OPTIONS, _STR_GAMES_LIST};
        int hintIcons[3] = {gSelectButton == KEY_CIRCLE ? CIRCLE_ICON : CROSS_ICON,
                            TRIANGLE_ICON, R3_ICON};
        int hintX = guiAlignSubMenuHints(3, hintTexts, hintIcons, gTheme->fonts[0], 12, 1);
        int hintY = gTheme->usedHeight - 32;
        int i;
        for (i = 0; i < 3; i++) {
            hintX = guiDrawIconAndText(hintIcons[i], hintTexts[i], gTheme->fonts[0],
                                       hintX, hintY, gTheme->textColor);
            hintX += 12;
        }
    }
}

void oplunaCollectionHandleInput(void)
{
    int count;
    syncGeneration();
    count = oplunaCount();
    if (getKeyOn(KEY_R3) || getKeyOn(KEY_L3) ||
        getKeyOn(gSelectButton == KEY_CIRCLE ? KEY_CROSS : KEY_CIRCLE)) {
        if (count > 0)
            oplunaSelectNativeGame(selectedIndex);
        guiSwitchScreen(GUI_SCREEN_MAIN);
    } else if (count > 0 && getKeyOn(gSelectButton)) {
        oplunaActivateGame(selectedIndex, 0);
    } else if (count > 0 && getKeyOn(KEY_TRIANGLE)) {
        oplunaActivateGame(selectedIndex, 1);
    } else if (count > 1 && (getKey(KEY_LEFT) || getKey(KEY_UP))) {
        moveSelection(-1);
    } else if (count > 1 && (getKey(KEY_RIGHT) || getKey(KEY_DOWN))) {
        moveSelection(1);
    }
}
