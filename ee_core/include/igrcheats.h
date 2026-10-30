/*
  igrcheats.h the cheats the in-game menu can turn on and off (igrmenu.c, cheat_api.c)

  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.

  The launcher packs every cheat of the game's file here, not only the ones ticked, and puts the block after the
  IOP modules (below 0xD0000, kept for the whole game). ee_core reads it in place while the game is paused.
  Shared by the launcher (its cheat manager packs it) and ee_core: plain C, fixed sizes, no pointers inside.

  Layout, all words little endian:
    igr_cheats_t           header
    u32 spare[]            the engine's second code set (IGR_CHEATS_SPARE_WORDS): ee_core writes it, the launcher
                           only zeroes it
    igr_cheat_t cheat[n]   one row of the menu each
    u32 codes[]            every listed cheat's codes (hook codes left out), addr/val pairs, in file order
*/

#ifndef IGRCHEATS_H
#define IGRCHEATS_H

#define IGR_CHEATS_MAGIC       0x31484349                               // "ICH1"
#define IGR_CHEATS_MAX         64                                       // rows in the menu
#define IGR_CHEAT_NAME         24                                       // the menu's width, NUL included
#define IGR_CHEAT_CODES_MAX    512                                      // code pairs over all listed cheats
#define IGR_CHEAT_SET_CODES    250                                      // the engine's MAX_CODES: what one code set holds
#define IGR_CHEATS_SPARE_WORDS ((1 + IGR_CHEAT_SET_CODES * 2 + 3) & ~3) // count, then the pairs

typedef struct
{
    unsigned short first; // its first pair in codes[]
    unsigned short count; // its pairs
    unsigned char on;     // applied now
    unsigned char pad[3];
    char name[IGR_CHEAT_NAME];
} igr_cheat_t;

typedef struct
{
    unsigned int magic;
    unsigned int count; // cheats listed
    unsigned int pairs; // pairs in codes[]
    unsigned int reserved;
} igr_cheats_t;

#define IGR_CHEATS_SPARE(h) ((unsigned int *)((unsigned char *)(h) + sizeof(igr_cheats_t)))
#define IGR_CHEATS_ROWS(h)  ((igr_cheat_t *)(IGR_CHEATS_SPARE(h) + IGR_CHEATS_SPARE_WORDS))
#define IGR_CHEATS_CODES(h) ((unsigned int *)(IGR_CHEATS_ROWS(h) + (h)->count))
#define IGR_CHEATS_BYTES(count, pairs) \
    (sizeof(igr_cheats_t) + IGR_CHEATS_SPARE_WORDS * 4 + (count) * sizeof(igr_cheat_t) + (pairs)*8)

// The ticked rows' codes into set ([count][pairs], the engine's layout), whole cheats in file order while they fit
// IGR_CHEAT_SET_CODES. Returns the pairs written. The launcher's own list (cheatman set_cheats_list) is built the same
// way, so the set the menu makes for the same ticks is the set the game started with.
static inline unsigned int igrCheatsBuild(const igr_cheats_t *b, unsigned int *set)
{
    const igr_cheat_t *row = IGR_CHEATS_ROWS(b);
    const unsigned int *codes = IGR_CHEATS_CODES(b);
    unsigned int n = 0, i, k;

    for (i = 0; i < b->count; i++) {
        if (!row[i].on || n + row[i].count > IGR_CHEAT_SET_CODES || row[i].first + row[i].count > b->pairs)
            continue;
        for (k = 0; k < row[i].count; k++, n++) {
            set[1 + n * 2] = codes[(row[i].first + k) * 2];
            set[2 + n * 2] = codes[(row[i].first + k) * 2 + 1];
        }
    }
    set[0] = n;
    return n;
}

// 1 when the ticked rows plus row `at` fit one set
static inline int igrCheatsFit(const igr_cheats_t *b, unsigned int at)
{
    const igr_cheat_t *row = IGR_CHEATS_ROWS(b);
    unsigned int n = 0, i;

    for (i = 0; i < b->count; i++)
        if (row[i].on || i == at)
            n += row[i].count;
    return n <= IGR_CHEAT_SET_CODES;
}

#endif
