/* Optional CFG Titles in the game lists (#918). See src/cfgtitle.c. */
#ifndef __CFGTITLE_H__
#define __CFGTITLE_H__

#include "include/iosupport.h"

#define CFG_TITLE_MAX 128 /* bytes, including the terminator; longer titles are cut on a character */

/* I/O thread, after a list scan: with gCfgTitlesInLists on, read each game's CFG "Title" once
   (itemGetConfig) and keep the valid ones for display; off, drop any kept titles. */
void cfgTitleRefresh(item_list_t *support, int count);

/* The kept title for a row, or NULL. GUI thread (under the frame lock). */
const char *cfgTitleForRow(item_list_t *support, int id);

/* What a game row shows and sorts by: its CFG title when one is kept, else the existing display
   name (vcdDisplayNameForRow). Never changes the row's identity text. */
const char *cfgTitleDisplayName(item_list_t *support, int id, const char *text);

/* Trims and validates a title (UTF-8, no control characters), cutting it on a character
   boundary to fit. 1 when out holds a usable title. */
int cfgTitleClean(const char *in, char *out, int size);

#endif
