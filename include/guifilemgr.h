#ifndef __OPL_GUIFILEMGR_H
#define __OPL_GUIFILEMGR_H

// File Manager (main menu), after RIPPS2's Memory Files browser (akilluminati47/RIPPS2). See src/guifilemgr.c.

#define FM_ROWS 12 // entries on one page

// Its own dialogs, so their ids only need to differ from each other
enum {
    FM_PATH = 950,
    FM_STATUS,
    FM_PASTE_BTN,
    FM_PASTE_PSU_BTN,
    FM_NEW_FOLDER_BTN,
    FM_ROW_FIRST,
    FM_ROW_LAST = FM_ROW_FIRST + FM_ROWS - 1,

    FMA_TITLE,
    FMA_OPEN,
    FMA_RUN,
    FMA_MARK,
    FMA_COPY,
    FMA_CUT,
    FMA_RENAME,
    FMA_DELETE,
    FMA_UNPACK,
};

void guiShowFileManager(void);

#endif
