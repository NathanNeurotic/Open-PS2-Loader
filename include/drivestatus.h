#ifndef __OPL_DRIVESTATUS_H
#define __OPL_DRIVESTATUS_H

// Drive Status (main menu), ported from RIPPS2 build 114 (akilluminati47/RIPPS2). See src/drivestatus.c.

#define DSTAT_LINES 16

// Its own dialog, so its ids only need to differ from each other
enum {
    DSTAT_SAVE_DIAG = 900,
    DSTAT_LINE_FIRST,
    DSTAT_LINE_LAST = DSTAT_LINE_FIRST + DSTAT_LINES - 1,
};

void guiShowDriveStatus(void);

// Helpers, shared with the host test
void dsSizeText(unsigned long long kb, char *out, int size);
const char *dsDriverLabel(const char *driver);
const char *dsFsName(unsigned int fsType);

#endif
