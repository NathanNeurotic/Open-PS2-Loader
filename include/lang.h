#ifndef __LANG_H
#define __LANG_H

#include "lang_autogen.h"

extern char *internalEnglish[LANG_STR_COUNT];
// getter for a localised string version
extern char *_l(unsigned int id);

typedef struct
{
    char *filePath;
    char *name;
    unsigned char sourcePriority; // CWD > CWD/LNG > other LNG directories
} language_t;

int lngAddLanguages(char *path, const char *separator, int mode);
void lngInit(void);
/** Retry discovery when the boot path becomes readable after driver initialization. */
void lngRefreshBootLanguages(int mode);
/** Load the optional Unicode fallback after settings home relocation is resolved. */
void lngInitFallbackFont(void);
char *lngGetValue(void);
void lngEnd(void);

// Indices are shifted in GUI, as we add the internal english language at 0
int lngSetGuiValue(int langID);
int lngGetGuiValue(void);
int lngFindGuiID(const char *lang);
char **lngGetGuiList(void);
char *lngGetFilePath(int langID);

#endif
