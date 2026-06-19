#ifndef __FAVSUPPORT_H
#define __FAVSUPPORT_H

#include "include/iosupport.h"

#define FAV_MODE_UPDATE_DELAY 240
#define FAV_TEXT_MAX          256        // cap on a stored favourite's text length (incl. NUL)
#define FAV_MAX_ITEMS         512        // cap on records read from favourites.bin
#define FAV_MAGIC             0x4641464F // 'OFAV' (little-endian on the EE)
#define FAV_VERSION           1

// Defined in favsupport.c; consumed by opl.c/gui.c (config load/save/default).
extern int gFAVStartMode;

item_list_t *favGetObject(int initOnly);

// Dynamic mode flags for the currently-selected FAV item (its source's flags). Used by
// itemExecTriangle so a FAV item exposes the same Options menu as its source would.
unsigned char favGetFlags(item_list_t *itemList);

// R3-toggle helpers (called from opl.c). add/remove rewrite favourites.bin.
void addFavouriteItem(int mode, int id, int icon_id, int text_id, const char *text);
void removeFavouriteByIdAndText(int id, const char *text);

// Remove the favourite at FAV-list index favIndex (R3 pressed on the Favourites tab).
void favRemoveByIndex(int favIndex);

// Cheap/idempotent: clears the FAV list + schedules its single deferred rebuild.
void loadFavourites(void);

#endif
