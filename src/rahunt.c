/*
  What is left to hunt in a game, and how each one is earned (RIPPS2 build 94, by akilluminati47).
  When a game's Achievements page in the loader reads its set from the xeRAbora PC (achievements.c), the set
  is saved beside the game's watch list as RA/<startup>.ach:
    RIPPS2 ACH 1
    <unlocked 0|1> TAB <points> TAB <title> TAB <description>      one line per achievement
  A launch hands the locked ones to the in-game menu (raHuntBlob, supportbase.c): its ACHIEVEMENTS page shows
  one at a time, title, points and how to earn it. They go in the menu's own lines, wrapped here: the menu has
  only the room the overlay leaves, so it only prints.
  Plain C with no console calls, so the PC tests (.github/scripts) run it.
*/
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

#include "include/rahunt.h"

// The code point of the UTF-8 sequence at *pp, which moves past it; a broken one is '?'
static unsigned huntUtf8(const char **pp, const char *end)
{
    const unsigned char *p = (const unsigned char *)*pp;
    unsigned u = *p++;
    int more = u >= 0xF0 ? 3 : u >= 0xE0 ? 2 :
                           u >= 0xC0     ? 1 :
                                           0;

    if (u >= 0x80 && more == 0)
        u = '?'; // a stray continuation byte
    else if (more)
        u &= 0x3F >> more;
    while (more-- > 0) {
        if ((const char *)p >= end || (*p & 0xC0) != 0x80) {
            u = '?';
            break;
        }
        u = u << 6 | (*p++ & 0x3F);
    }
    *pp = (const char *)p;
    return u;
}

// ---- writing RA/<startup>.ach ----

static int huntField(char *out, int o, int outsz, const char *s)
{
    for (; s != NULL && *s; s++) {
        if (o >= outsz - 1)
            return -1;
        out[o++] = (*s == '\t' || *s == '\n' || *s == '\r') ? ' ' : *s;
    }
    return o;
}

int raHuntLine(char *out, int outsz, int unlocked, int points, const char *title, const char *desc)
{
    int o = snprintf(out, outsz, "%d\t%d\t", unlocked ? 1 : 0, points < 0 ? 0 : points);

    if (o < 0 || o >= outsz || (o = huntField(out, o, outsz, title)) < 0 || o >= outsz - 1)
        return 0;
    out[o++] = '\t';
    if ((o = huntField(out, o, outsz, desc)) < 0 || o >= outsz - 1)
        return 0;
    out[o++] = '\n';
    out[o] = '\0';
    return o;
}

// ---- reading RA/<startup>.ach ----

int raHuntRead(const char *text, int len, ra_hunt_t *list, int max)
{
    const char *p = text, *end = text + len;
    int n = 0;

    if (len < 12 || strncmp(text, "RIPPS2 ACH 1", 12) != 0)
        return -1;
    while (p < end && *p != '\n')
        p++;
    while (p < end && n < max) {
        const char *e;
        char field[4][RA_HUNT_DESC];
        int f = 0, k;

        if (*p == '\n')
            p++;
        if (p >= end)
            break;
        for (e = p; e < end && *e != '\n'; e++)
            ;
        for (k = 0; k < 4; k++)
            field[k][0] = '\0';
        while (p < e && f < 4) {
            int o = 0;
            while (p < e && *p != '\t') {
                if (o < RA_HUNT_DESC - 1 && *p != '\r')
                    field[f][o++] = *p;
                p++;
            }
            field[f][o] = '\0';
            f++;
            if (p < e)
                p++;
        }
        p = e;
        if (f < 3)
            continue;
        list[n].unlocked = atoi(field[0]) != 0;
        list[n].points = atoi(field[1]);
        field[2][RA_HUNT_TITLE - 1] = '\0'; // a longer title is cut to the list's
        memcpy(list[n].title, field[2], RA_HUNT_TITLE);
        memcpy(list[n].desc, field[3], RA_HUNT_DESC);
        n++;
    }
    return n;
}

// ---- for the in-game menu ----

// UTF-8 text in the menu's characters: capitals and ASCII 32..95. Latin-1 letters lose their accents, '"'
// (which its font lacks) becomes '\'', curly quotes and dashes their plain ones, anything else '?'.
static void huntMenuText(const char *s, char *out, int size)
{
    static const char fold[] = "AAAAAAACEEEEIIIIDNOOOOOXOUUUUYTSAAAAAAACEEEEIIIIDNOOOOO/OUUUUYTY"; // U+00C0..U+00FF
    const char *end = s + strlen(s);
    int o = 0;

    while (s < end && o < size - 1) {
        unsigned u = huntUtf8(&s, end);
        int c;

        if (u >= 0xC0 && u <= 0xFF)
            u = (unsigned char)fold[u - 0xC0];
        else if (u == 0x2018 || u == 0x2019 || u == 0x2032 || u == 0x201C || u == 0x201D)
            u = '\'';
        else if (u == 0x2013 || u == 0x2014 || u == 0x2212)
            u = '-';
        else if (u < 0x20 || u == 0xA0)
            u = ' ';
        c = u < 0x80 ? toupper((int)u) : '?';
        if (c == '"')
            c = '\'';
        out[o++] = (char)((c >= 32 && c <= 95) ? c : '?');
    }
    out[o] = '\0';
}

// s in lines of RA_HUNT_COLS broken at spaces (a word too long for one is broken where it must be), at most
// max of them, each NUL ended into blob at *o; a last line with more to say ends "...". The lines, -1 when
// cap ran out.
static int huntLines(const char *text, int max, unsigned char *blob, int *o, int cap)
{
    char menu[RA_HUNT_DESC];
    const char *s = menu;
    int n = 0, len, cut, k, i, dots;

    huntMenuText(text, menu, sizeof(menu));
    for (;;) {
        while (*s == ' ')
            s++;
        if (!*s || n >= max)
            return n;
        len = (int)strlen(s);
        cut = len;
        if (len > RA_HUNT_COLS) {
            for (cut = RA_HUNT_COLS; cut > 0 && s[cut] != ' '; cut--)
                ;
            if (cut == 0)
                cut = RA_HUNT_COLS;
        }
        k = cut;
        while (k > 0 && s[k - 1] == ' ')
            k--;
        dots = n == max - 1 && cut < len;
        if (dots && k > RA_HUNT_COLS - 3)
            k = RA_HUNT_COLS - 3;
        if (*o + k + 3 * dots + 1 > cap)
            return -1;
        for (i = 0; i < k; i++)
            blob[(*o)++] = (unsigned char)s[i];
        for (i = 0; i < 3 * dots; i++)
            blob[(*o)++] = '.';
        blob[(*o)++] = '\0';
        n++;
        s += cut;
    }
}

int raHuntBlob(const ra_hunt_t *list, int n, unsigned char *blob, int cap, int *count)
{
    int i, o = 0;

    *count = 0;
    for (i = 0; i < n; i++) {
        int start = o, nt, nd;

        if (list[i].unlocked)
            continue;
        if (o + 3 > cap)
            break;
        o += 3;
        if ((nt = huntLines(list[i].title, 2, blob, &o, cap)) < 0 ||
            (nd = huntLines(list[i].desc, RA_HUNT_ROWS - 1 - nt, blob, &o, cap)) < 0) {
            o = start; // no room for all of it: none of it
            break;
        }
        blob[start] = (unsigned char)(list[i].points > 255 ? 255 : list[i].points);
        blob[start + 1] = (unsigned char)nt;
        blob[start + 2] = (unsigned char)nd;
        (*count)++;
    }
    return o;
}
