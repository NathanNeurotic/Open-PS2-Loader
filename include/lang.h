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

/** 1: the Language page applied the user's pick this session. It is live but reaches language_text only on
 *  save, so until a config load applies the saved language again (0), a language publish (a device bringing
 *  its LNG folder) keeps the pick instead of re-applying the saved language over it. */
void lngSetUserPick(int picked);

// Indices are shifted in GUI, as we add the internal english language at 0
int lngSetGuiValue(int langID);
int lngGetGuiValue(void);
int lngFindGuiID(const char *lang);
char **lngGetGuiList(void);
char *lngGetFilePath(int langID);

#endif
