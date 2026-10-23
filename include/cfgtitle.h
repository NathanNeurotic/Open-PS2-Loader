/* Optional CFG Titles in the game lists (#918). See src/cfgtitle.c. */
#ifndef __CFGTITLE_H__
#define __CFGTITLE_H__

#include "include/iosupport.h"

#define CFG_TITLE_MAX 128 /* bytes, including the terminator; longer titles are cut on a character */

/* I/O thread, after a list scan: with gCfgTitlesInLists on, read each game's CFG "Title" once
   (itemGetConfig) and keep the valid ones for display; off, drop any kept titles. */
void cfgTitleRefresh(item_list_t *support, int count);

/* I/O thread, before a rebuild queues its rows: drop the old table so a new row never shows a title
   that belonged to the old list's row of the same index. */
void cfgTitleForget(item_list_t *support);

/* The kept title for a row, or NULL (always NULL while the setting is off). GUI thread. */
const char *cfgTitleForRow(item_list_t *support, int id);

/* What a game row shows: its CFG title when one is kept, else the existing display
   name (vcdDisplayNameForRow). Never changes the row's identity text. */
const char *cfgTitleDisplayName(item_list_t *support, int id, const char *text);

/* Alphabetical title without the cosmetic RA mark. text is the unchanged source name. */
const char *cfgTitleSortName(item_list_t *support, int id, const char *text);

/* Trims and validates a title (UTF-8, no control characters), cutting it on a character
   boundary to fit. 1 when out holds a usable title. */
int cfgTitleClean(const char *in, char *out, int size);

#endif
