#ifndef __RAHUNT_H
#define __RAHUNT_H

// RA/<startup>.ach: a game's achievements as the loader last saw them, for the in-game menu's LEFT TO HUNT
// (src/rahunt.c; RIPPS2's, by akilluminati47). RA editions only.

#define RA_HUNT_TITLE 64
#define RA_HUNT_DESC  160
#define RA_HUNT_MAX   1024       // achievements read from one RA/<startup>.ach (achievements.cpp writes as many)
#define RA_HUNT_BLOB  (8 * 1024) // the most the in-game menu is given (module storage is tight)
#define RA_HUNT_COLS  24         // the in-game menu's line (ee_core igrmenu.c TEXT_CHARS)
#define RA_HUNT_ROWS  8          // and its LEFT TO HUNT rows: up to 2 of title, the points, the rest how to earn it

typedef struct
{
    int unlocked, points;
    char title[RA_HUNT_TITLE];
    char desc[RA_HUNT_DESC];
} ra_hunt_t;

// One achievement as an RA/<startup>.ach line (its first line is "RIPPS2 ACH 1"):
// <unlocked 0|1> TAB <points> TAB <title> TAB <description> NL. Tabs and line breaks in the text become spaces.
// The bytes written to out, 0 when they do not fit in outsz.
int raHuntLine(char *out, int outsz, int unlocked, int points, const char *title, const char *desc);
// RA/<startup>.ach's text into list; how many, or -1 when it is not one
int raHuntRead(const char *text, int len, ra_hunt_t *list, int max);
// The locked ones packed for the in-game menu, in its lines: per achievement its points, its title lines and
// its description lines (one byte each), then those lines, NUL ended, RA_HUNT_COLS characters at most, broken
// at spaces, in the menu's characters (capitals, ASCII 32..95); a description cut short ends "...".
// Bytes used; *count how many fitted in cap.
int raHuntBlob(const ra_hunt_t *list, int n, unsigned char *blob, int cap, int *count);

#endif
