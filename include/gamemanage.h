#ifndef __GAMEMANAGE_H
#define __GAMEMANAGE_H

// Hide Game and Delete everything, ported from RIPPS2 (akilluminati47/RIPPS2, build 114).

#define HIDDEN_FILE     "hidden.txt" // in the source's prefix, beside CFG/ and ART/
#define HIDDEN_MAX      512          // games one drive's list keeps
#define HIDDEN_NAME_MAX 256

extern int gShowHidden; // Settings: list hidden games anyway, so they can be shown again

void hiddenInit(void);
// The source's list was read again (I/O thread): read its hidden list again too.
void hiddenReload(int mode);
// 1 when the source's hidden list names this game. Loads the list once.
int hiddenHas(int mode, int ps1, const char *name);
// 1 when this row of a page (device page or Favourites/All Games) is a hidden game.
int hiddenRow(item_list_t *support, int id);
// The source a row's game is on, whether it is a PS1 game, and its name. 0 when the row has no
// source that keeps a hidden list (apps, the network catalogue, a folder row).
int hiddenRowSource(item_list_t *support, int id, int *mode, int *ps1, const char **name);
// Adds (hide = 1) or removes a game. 1 saved, 0 the list could not be written, -1 the source keeps
// no list. The source's page and Favourites are rebuilt.
int hiddenSet(int mode, int ps1, const char *name, int hide);
// Rebuilds the pages a hidden game could be on.
void hiddenRefresh(int mode);

// Delete everything: the game's parts, and its CFG, art and cheats unless another copy of the game
// on the same drive uses them. VMC saves are kept.
enum { GM_FILE_CFG = 0,
       GM_FILE_ART,
       GM_FILE_CHT };
#define GM_MAX_FILES 64
typedef struct
{
    int parts, cfg, art, cht, shared, count;
    struct
    {
        char path[256];
        int what;
    } files[GM_MAX_FILES];
} gm_delete_plan_t;

// Fills plan for a PS2 game row of a device page. 0 when the row is not a game this can delete.
int gmPlanDelete(item_list_t *support, int id, gm_delete_plan_t *plan);
// Removes the planned extras; returns how many could not be removed.
int gmDeleteExtras(const gm_delete_plan_t *plan);

#endif
