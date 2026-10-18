/*
 * Copyright 2026, dnunezx
 * Licensed under the Academic Free License version 3.0.
 *
 * Collection geometry adapted from PR #733, src/opluna_collection.c at
 * 35653d79484e70b65024e972352e0718c1a48626. Native theme integration by OpenAI.
 */
#ifndef PSBBNFLOW_H
#define PSBBNFLOW_H

#define PSBBN_FLOW_TAIL   6
#define PSBBN_FLOW_FRAMES 25

typedef struct
{
    int x, y, size, shade;
} psbbn_flow_rect_t;

static inline int psbbnFlowCurve(int distance, const unsigned char *points, int length)
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

static inline int psbbnFlowOffset(int start, unsigned int elapsed)
{
    if (elapsed >= PSBBN_FLOW_FRAMES)
        return 0;
    int remaining = PSBBN_FLOW_FRAMES - elapsed;
    return start * remaining * remaining * remaining /
           (PSBBN_FLOW_FRAMES * PSBBN_FLOW_FRAMES * PSBBN_FLOW_FRAMES);
}

static inline int psbbnFlowSize(int width, int height)
{
    int size = (height - 118) * 76 / 100;
    if (size > width * 38 / 100)
        size = width * 38 / 100;
    return size > 0 ? size * 115 / 100 : 1;
}

static inline psbbn_flow_rect_t psbbnFlowRect(int position, int focalSize, int focalCenterX, int centerY)
{
    static const unsigned char sizes[] = {100, 44, 41, 38, 30, 22, 14};
    static const unsigned char offsets[] = {0, 50, 72, 93, 112, 127, 138};
    int distance = position < 0 ? -position : position;
    int centerX, emphasis, visibility;
    psbbn_flow_rect_t rect;
    if (position >= 0) {
        rect.size = focalSize * psbbnFlowCurve(distance, sizes, sizeof(sizes)) / 100000;
        centerX = focalCenterX - focalSize * psbbnFlowCurve(distance, offsets, sizeof(offsets)) / 100000;
    } else {
        int progress = distance > 1000 ? 1000 : distance;
        int squared = progress * progress / 1000;
        rect.size = focalSize * (1000 + 750 * squared / 1000) / 1000;
        centerX = focalCenterX + focalSize * 160 * squared / 100000;
    }
    rect.x = centerX - rect.size / 2;
    rect.y = centerY - rect.size / 2 + (position > 0 ? distance * 3 / 2000 : 0);
    emphasis = 1000 - (distance < 1000 ? distance : 1000);
    visibility = distance <= 1000 ? 1000 : 1000 - (distance - 1000) * 850 / 5000;
    if (visibility < 150)
        visibility = 150;
    rect.shade = (0x58 + emphasis * 0x28 / 1000) * visibility / 1000;
    return rect;
}
#endif
