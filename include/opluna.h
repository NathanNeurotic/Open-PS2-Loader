#ifndef __OPLUNA_H
#define __OPLUNA_H

#include "include/iosupport.h"

#define OPLUNA_IDENTITY_TEXT_CAP 192

typedef struct {
    int mode;
    int itemId;
    char title[OPLUNA_IDENTITY_TEXT_CAP];
    char startup[OPLUNA_IDENTITY_TEXT_CAP];
} opluna_identity_t;

/* Published titles are owned by OPLuna. */
void oplunaQueueSource(int mode, item_list_t *support, int count);
void oplunaApplySource(void *source);
void oplunaEnd(void);
unsigned int oplunaGeneration(void);
int oplunaCount(void);
const char *oplunaTitleAt(int index, int *mode);
int oplunaIdentityAt(int index, opluna_identity_t *identity);
int oplunaFindIdentity(const opluna_identity_t *identity);
int oplunaActivateGame(int index, int options);
int oplunaSelectNativeGame(int index);
int oplunaSquarePathAt(int index, char *path, size_t capacity);
void oplunaCollectionInit(void);
void oplunaCollectionPrepare(void);
int oplunaCollectionReady(void);
void oplunaCollectionRender(int width, int height);
void oplunaCollectionLoadingPosition(int width, int height, int iconSize, int *x, int *y);
void oplunaCollectionHandleInput(void);
void oplunaCollectionSelectFromNative(item_list_t *support, int itemId);
void oplunaCollectionEnd(void);

#endif
