/* RetroAchievements account progress browser; built only in RA flavour. */
#ifndef RIPTOPL_RA_BROWSER_H
#define RIPTOPL_RA_BROWSER_H

#ifdef RETROACHIEVEMENTS

#define RA_BROWSER_PAGE_SIZE 3
#define RA_BROWSER_TEXT 100

typedef struct {
    unsigned int id, total, earned, hardcore, points;
    char icon[33];
    char title[64];
    char description[RA_BROWSER_TEXT + 1];
    char date[20];
} ra_browser_entry_t;

typedef struct {
    int state, count, page, total, earned, maximum;
    unsigned int game_id;
    char user[28], title[64];
    ra_browser_entry_t entries[RA_BROWSER_PAGE_SIZE];
} ra_browser_page_t;

enum {
    RA_BROWSER_LOADING = 0,
    RA_BROWSER_READY,
    RA_BROWSER_OFFLINE,
    RA_BROWSER_UNSUPPORTED,
    RA_BROWSER_BUSY,
    RA_BROWSER_ERROR,
    RA_BROWSER_NET_BUSY
};

void raBrowserOpen(int fromGameMenu);
void raBrowserRender(void);
void raBrowserHandleInput(void);

#endif /* RETROACHIEVEMENTS */
#endif /* RIPTOPL_RA_BROWSER_H */
