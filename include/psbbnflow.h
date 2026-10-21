/*
 * Copyright 2026, dnunezx
 * Licensed under the Academic Free License version 3.0.
 *
 * Collection glide adapted from PR #733, src/opluna_collection.c at
 * 35653d79484e70b65024e972352e0718c1a48626. Native theme integration by OpenAI.
 * Card layout reworked to match the PSBBN Definitive Project Game Collection, measured from
 * CosmicScale's published videos (no PSBBN code or assets).
 */
#ifndef PSBBNFLOW_H
#define PSBBNFLOW_H

#define PSBBN_FLOW_TAIL   6
#define PSBBN_FLOW_FRAMES 25

/* Virtual 640x480 layout of the PSBBN top-menu frame the Game Collection sits in. */
#define PSBBN_FLOW_HEADER_Y 62  // rule under the header band
#define PSBBN_FLOW_FOOTER_Y 416 // rule above the button-hint band
#define PSBBN_FLOW_RULE_X0  56
#define PSBBN_FLOW_RULE_X1  584

/* One cover as a card turned about its vertical axis: unequal edge heights draw it in
 * perspective. Shade and alpha use the GS scale (0x80 = full). */
typedef struct
{
    int xl, xr, yc, hl, hr, shade, alpha;
} psbbn_flow_card_t;

static inline int psbbnFlowOffset(int start, unsigned int elapsed)
{
    if (elapsed >= PSBBN_FLOW_FRAMES)
        return 0;
    int remaining = PSBBN_FLOW_FRAMES - elapsed;
    return start * remaining * remaining * remaining /
           (PSBBN_FLOW_FRAMES * PSBBN_FLOW_FRAMES * PSBBN_FLOW_FRAMES);
}

/* Focal cover side: 0.425 of the screen height, the PSBBN proportion (204 at 480 lines). */
static inline int psbbnFlowSize(int width, int height)
{
    int size = height * 425 / 1000;
    if (size > width * 40 / 100)
        size = width * 40 / 100;
    return size > 0 ? size : 1;
}

/* Card at position (1000 per slot: 0 focal, >0 tail, <0 outgoing toward the viewer).
 * sizeX/sizeY are the focal side in each axis (they differ in widescreen); centerX/centerY
 * the focal centre. Tail slots, in 1/1000 of the focal side: right edge from the focal left
 * edge, width, right and left edge heights, shade, alpha. The last slot is where a new tail
 * card fades in from. */
static inline psbbn_flow_card_t psbbnFlowCard(int position, int sizeX, int sizeY, int centerX, int centerY)
{
    static const short slots[PSBBN_FLOW_TAIL + 2][6] = {
        {1000, 1000, 1000, 1000, 128, 128},
        {40, 190, 520, 425, 112, 128},
        {-120, 160, 440, 360, 100, 128},
        {-255, 140, 375, 308, 90, 124},
        {-375, 120, 320, 262, 80, 108},
        {-475, 105, 275, 225, 70, 84},
        {-560, 90, 235, 193, 62, 52},
        {-630, 75, 200, 164, 54, 0},
    };
    psbbn_flow_card_t card;
    int left = centerX - sizeX / 2;
    card.yc = centerY;
    if (position < 0) {
        // Outgoing: the cover swells toward the upper right and fades, as PSBBN's does.
        int t = -position > 1000 ? 1000 : -position;
        int size = 1000 + 1500 * t / 1000;
        int x = centerX + sizeX * 85 * t / 100000;
        int remaining = 1000 - t;
        card.xl = x - sizeX * size / 2000;
        card.xr = x + sizeX * size / 2000;
        card.hl = card.hr = sizeY * size / 1000;
        card.yc = centerY - sizeY * 20 * t / 100000;
        card.shade = 128;
        card.alpha = 128 * remaining / 1000 * remaining / 1000;
        return card;
    }
    int slot = position / 1000, fraction = position % 1000;
    if (slot >= PSBBN_FLOW_TAIL + 1) {
        slot = PSBBN_FLOW_TAIL + 1;
        fraction = 0;
    }
    const short *a = slots[slot], *b = slots[slot < PSBBN_FLOW_TAIL + 1 ? slot + 1 : slot];
    int v[6];
    for (int i = 0; i < 6; i++)
        v[i] = a[i] + (b[i] - a[i]) * fraction / 1000;
    card.xr = left + sizeX * v[0] / 1000;
    card.xl = card.xr - sizeX * v[1] / 1000;
    card.hr = sizeY * v[2] / 1000;
    card.hl = sizeY * v[3] / 1000;
    card.shade = v[4];
    card.alpha = v[5];
    return card;
}

/* Texel window that crops cover art to the square PSBBN tile, keeping the centre. */
static inline void psbbnFlowCrop(int width, int height, float uv[4])
{
    uv[0] = 0.0f;
    uv[1] = 0.0f;
    uv[2] = (float)width;
    uv[3] = (float)height;
    if (height > width) {
        uv[1] = (float)(height - width) / 2.0f;
        uv[3] = uv[1] + (float)width;
    } else if (width > height) {
        uv[0] = (float)(width - height) / 2.0f;
        uv[2] = uv[0] + (float)height;
    }
}

/* Outline of a rounded rectangle as PSBBN_FLOW_ROUND_POINTS points (x, y pairs), clockwise
 * from the top-left corner. rx/ry are the corner radii. */
#define PSBBN_FLOW_ROUND_STEPS  4
#define PSBBN_FLOW_ROUND_POINTS (4 * (PSBBN_FLOW_ROUND_STEPS + 1))
static inline void psbbnFlowRoundRect(float x0, float y0, float x1, float y1, float rx, float ry, float *points)
{
    // Quarter-circle unit offsets from the corner centre, 0..90 degrees.
    static const float c[PSBBN_FLOW_ROUND_STEPS + 1] = {1.0f, 0.92388f, 0.70711f, 0.38268f, 0.0f};
    static const float s[PSBBN_FLOW_ROUND_STEPS + 1] = {0.0f, 0.38268f, 0.70711f, 0.92388f, 1.0f};
    const float cx[4] = {x0 + rx, x1 - rx, x1 - rx, x0 + rx};
    const float cy[4] = {y0 + ry, y0 + ry, y1 - ry, y1 - ry};
    const float sx[4] = {-1.0f, 1.0f, 1.0f, -1.0f};
    const float sy[4] = {-1.0f, -1.0f, 1.0f, 1.0f};
    int n = 0;
    for (int corner = 0; corner < 4; corner++) {
        for (int i = 0; i <= PSBBN_FLOW_ROUND_STEPS; i++) {
            // Corners 0 and 2 run from the horizontal edge to the vertical one; 1 and 3 the other way.
            int k = (corner & 1) ? PSBBN_FLOW_ROUND_STEPS - i : i;
            points[n++] = cx[corner] + sx[corner] * rx * c[k];
            points[n++] = cy[corner] + sy[corner] * ry * s[k];
        }
    }
}
#endif
