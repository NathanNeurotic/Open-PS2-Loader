/*
 Copyright 2026, dnunezx
 Licensed under the Academic Free License version 3.0.
 */

#include "include/opl.h"
#include "include/gui.h"
#include "include/opluna.h"

#define OPLUNA_MAX_SOURCE_ITEMS 4096
#define OPLUNA_MAX_TITLE_LENGTH 191
#define OPLUNA_MAX_SOURCE_TEXT (512 * 1024)

typedef struct
{
    int mode;
    int count;
    item_list_t *support;
    int *itemIds;
    char **titles;
    char **startups;
    char *text;
} opluna_source_t;

static opluna_source_t *sources[MODE_COUNT];
static unsigned int generation;

static size_t titleLength(const char *title)
{
    size_t length = 0;
    if (title != NULL) {
        while (title[length] != '\0' && length < OPLUNA_MAX_TITLE_LENGTH)
            length++;
    }
    return length;
}

static void freeSource(opluna_source_t *source)
{
    if (source != NULL) {
        free(source->itemIds);
        free(source->titles);
        free(source->startups);
        free(source->text);
        free(source);
    }
}

/* Called on OPL's I/O worker, after itemUpdate has finished. The GUI only
   receives owned strings, never pointers into a backend's mutable game list. */
void oplunaQueueSource(int mode, item_list_t *support, int count)
{
    opluna_source_t *source;
    struct gui_update_t *update;
    size_t textSize = 0;
    int i, eligible = 0;

    if (mode < 0 || mode >= MODE_COUNT)
        return;

    source = calloc(1, sizeof(*source));
    if (source == NULL)
        return;
    source->mode = mode;
    // Favourites is a view of games already present in their source lists.
    // Publishing it again would duplicate every favourited game in Collection.
    source->support = mode == FAV_MODE ? NULL : support;

    if (source->support != NULL && count > 0 && count <= OPLUNA_MAX_SOURCE_ITEMS &&
        support->itemGetName != NULL && support->itemGetStartup != NULL) {
        for (i = 0; i < count; i++) {
            const char *title = support->itemGetName(support, i);
            const char *startup = support->itemGetStartup(support, i);
            // Folder rows have no startup. Collection presents launchable rows only.
            if (title == NULL || startup == NULL || startup[0] == '\0')
                continue;
            eligible++;
            textSize += titleLength(title) + 1;
            textSize += titleLength(startup) + 1;
            if (textSize > OPLUNA_MAX_SOURCE_TEXT)
                break;
        }

        if (i == count && eligible > 0) {
            source->itemIds = malloc((size_t)eligible * sizeof(*source->itemIds));
            source->titles = malloc((size_t)eligible * sizeof(*source->titles));
            source->startups = malloc((size_t)eligible * sizeof(*source->startups));
            source->text = malloc(textSize);
            if (source->itemIds != NULL && source->titles != NULL &&
                source->startups != NULL && source->text != NULL) {
                char *next = source->text;
                for (i = 0; i < count; i++) {
                    const char *title = support->itemGetName(support, i);
                    const char *startup = support->itemGetStartup(support, i);
                    if (title == NULL || startup == NULL || startup[0] == '\0')
                        continue;
                    int slot = source->count++;
                    size_t length = titleLength(title);
                    source->itemIds[slot] = i;
                    source->titles[slot] = next;
                    if (length != 0)
                        memcpy(next, title, length);
                    next[length] = '\0';
                    next += length + 1;
                    length = titleLength(startup);
                    source->startups[slot] = next;
                    if (length != 0)
                        memcpy(next, startup, length);
                    next[length] = '\0';
                    next += length + 1;
                }
            } else {
                freeSource(source);
                source = calloc(1, sizeof(*source));
                if (source == NULL)
                    return;
                source->mode = mode;
            }
        }
    }

    update = guiOpCreate(GUI_OP_OPLUNA_PUBLISH);
    if (update == NULL) {
        freeSource(source);
        return;
    }
    update->oplunaSource = source;
    if (guiDeferUpdate(update) < 0)
        freeSource(source);
}

/* Called only by the GUI's deferred-operation drain. */
void oplunaApplySource(void *next)
{
    opluna_source_t *source = next;
    if (source == NULL || source->mode < 0 || source->mode >= MODE_COUNT) {
        freeSource(source);
        return;
    }

    freeSource(sources[source->mode]);
    sources[source->mode] = source;
    generation++;
}

void oplunaEnd(void)
{
    int mode;
    for (mode = 0; mode < MODE_COUNT; mode++) {
        freeSource(sources[mode]);
        sources[mode] = NULL;
    }
    generation++;
}

unsigned int oplunaGeneration(void)
{
    return generation;
}

int oplunaCount(void)
{
    int mode, count = 0;
    for (mode = 0; mode < MODE_COUNT; mode++) {
        if (sources[mode] != NULL)
            count += sources[mode]->count;
    }
    return count;
}

const char *oplunaTitleAt(int index, int *mode)
{
    int currentMode;
    if (index < 0)
        return NULL;
    for (currentMode = 0; currentMode < MODE_COUNT; currentMode++) {
        opluna_source_t *source = sources[currentMode];
        if (source != NULL) {
            if (index < source->count) {
                if (mode != NULL)
                    *mode = currentMode;
                return source->titles[index];
            }
            index -= source->count;
        }
    }
    return NULL;
}

int oplunaIdentityAt(int index, opluna_identity_t *identity)
{
    int mode;
    if (index < 0 || identity == NULL)
        return -1;
    for (mode = 0; mode < MODE_COUNT; mode++) {
        opluna_source_t *source = sources[mode];
        if (source != NULL) {
            if (index < source->count) {
                identity->mode = mode;
                identity->itemId = source->itemIds[index];
                snprintf(identity->title, sizeof(identity->title), "%s", source->titles[index]);
                snprintf(identity->startup, sizeof(identity->startup), "%s", source->startups[index]);
                return 0;
            }
            index -= source->count;
        }
    }
    return -1;
}

int oplunaFindIdentity(const opluna_identity_t *identity)
{
    int mode, offset = 0;
    if (identity == NULL)
        return -1;
    for (mode = 0; mode < MODE_COUNT; mode++) {
        opluna_source_t *source = sources[mode];
        int i;
        if (source == NULL)
            continue;
        if (mode == identity->mode) {
            for (i = 0; i < source->count; i++) {
                if (source->itemIds[i] == identity->itemId &&
                    strcmp(source->startups[i], identity->startup) == 0 &&
                    strcmp(source->titles[i], identity->title) == 0)
                    return offset + i;
            }
            for (i = 0; i < source->count; i++) {
                if (strcmp(source->startups[i], identity->startup) == 0 &&
                    strcmp(source->titles[i], identity->title) == 0)
                    return offset + i;
            }
            return -1;
        }
        offset += source->count;
    }
    return -1;
}

int oplunaSquarePathAt(int index, char *path, size_t capacity)
{
    int mode;

    if (index < 0 || path == NULL || capacity < 5)
        return -1;
    for (mode = 0; mode < MODE_COUNT; mode++) {
        opluna_source_t *source = sources[mode];
        if (source != NULL) {
            if (index < source->count) {
                if (source->support == NULL || source->support->itemGetPrefix == NULL || source->startups[index][0] == '\0')
                    return -1;
                const char *prefix = source->support->itemGetPrefix(source->support);
                if (prefix == NULL)
                    return -1;
                if (snprintf(path, capacity, "%sART/PSBBN/%s", prefix, source->startups[index]) >= (int)capacity - 4)
                    return -1;
                return 0;
            }
            index -= source->count;
        }
    }
    return -1;
}
