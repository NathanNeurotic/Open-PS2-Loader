/*
 * RetroAchievements account browsing for the RA-only RiptOPL flavour.
 *
 * The PC stores the RA login; the console reads a read-only pairing capability
 * from its private SMB share, and retrieves bounded, paged progress over LAN.
 * Based on the public Caduceus wire contract, not on its GUI implementation.
 * No network or filesystem work runs from the renderer.
 */
#include "include/opl.h"
#include "include/ra_browser.h"
#include "include/ranet.h"
#include "include/ethsupport.h"
#include "include/supportbase.h"
#include "include/iosupport.h"
#include "include/gui.h"
#include "include/pad.h"
#include "include/menusys.h"
#include "include/renderman.h"
#include "include/themes.h"
#include "include/fntsys.h"
#include "include/sound.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>

#ifdef RETROACHIEVEMENTS

#define RA_BROWSER_RESPONSE 1024
static ra_browser_page_t shown;
static volatile int pending;
static unsigned int request_id;
static unsigned int query_id;
static int query_page, query_filter;
static char query_kind, query_target[33];
static char view_kind, view_target[33];
static int view_page, view_filter, view_row, library_page;
static int return_screen;

/* Preserve empty tab-separated columns; strtok() loses blank description/date
 * fields and shifts later columns into the wrong spots. */
static int fields(char *line, char **out, int count)
{
    int i;
    if (!line || !out)
        return 0;
    for (i = 0; i < count; i++) {
        char *tab;
        out[i] = line;
        if (i == count - 1)
            break;
        tab = strchr(line, '\t');
        if (!tab)
            return 0;
        *tab = 0;
        line = tab + 1;
    }
    return count;
}

static unsigned int as_uint(const char *s)
{
    unsigned int val = 0;
    if (!s || !*s)
        return 0;
    while (*s >= '0' && *s <= '9') {
        if (val > 100000000)
            return 0;
        val = val * 10 + (*s - '0');
        s++;
    }
    return *s == 0 ? val : 0;
}

static void copy_text(char *dst, size_t n, const char *src)
{
    if (!src) src = "";
    snprintf(dst, n, "%s", src);
}

static int parse_page(char *reply, ra_browser_page_t *out)
{
    char *header, *line, *next, *column[9];
    int i = 0;
    if (!reply || strncmp(reply, "OK\t", 3))
        return 0;
    header = reply + 3;
    line = strchr(header, '\n');
    if (line) *line++ = 0;
    if (fields(header, column, 8) != 8 || (column[0][0] != 'G' && column[0][0] != 'A'))
        return 0;
    out->page = as_uint(column[1]);
    out->total = as_uint(column[2]);
    out->game_id = as_uint(column[3]);
    out->earned = as_uint(column[4]);
    out->maximum = as_uint(column[5]);
    copy_text(out->user, sizeof(out->user), column[6]);
    copy_text(out->title, sizeof(out->title), column[7]);
    if (line) {
        for (; i < RA_BROWSER_PAGE_SIZE && *line; i++) {
            ra_browser_entry_t *entry = &out->entries[i];
            next = strchr(line, '\n');
            if (next) *next++ = 0;
            if (fields(line, column, 9) != 9)
                return 0;
            entry->id = as_uint(column[0]);
            entry->total = as_uint(column[1]);
            entry->earned = as_uint(column[2]);
            entry->hardcore = as_uint(column[3]);
            entry->points = as_uint(column[4]);
            copy_text(entry->icon, sizeof(entry->icon), column[5]);
            copy_text(entry->title, sizeof(entry->title), column[6]);
            copy_text(entry->description, sizeof(entry->description), column[7]);
            copy_text(entry->date, sizeof(entry->date), column[8]);
            if (!next) { i++; break; }
            line = next;
        }
    }
    out->count = i;
    out->state = RA_BROWSER_READY;
    return 1;
}

static void fetch_page(void)
{
    static char response[RA_BROWSER_RESPONSE] __attribute__((aligned(64)));
    ra_browser_page_t next;
    char key[65] = {0};
    char packet[192];
    int fd, count, rc, i;
    memset(&next, 0, sizeof(next));
    next.state = RA_BROWSER_ERROR;

    if (raNetNicBusy()) {
        next.state = RA_BROWSER_NET_BUSY;
        goto done;
    }
    /* This is a paired SMB capability, NOT the user's RA password or API key.
     * Deliberately do not start a second NIC stack for UDPBD/UDPFS users. */
    if (!ethIsSMBShareConnected()) {
        next.state = RA_BROWSER_OFFLINE;
        goto done;
    }
    fd = open("smb0:ART/CADUCEUS.KEY", O_RDONLY);
    if (fd < 0) {
        next.state = RA_BROWSER_OFFLINE;
        goto done;
    }
    count = read(fd, key, sizeof(key) - 1);
    close(fd);
    if (count < 64) {
        next.state = RA_BROWSER_OFFLINE;
        goto done;
    }
    for (i = 0; i < 64; i++) {
        if (!((key[i] >= '0' && key[i] <= '9') || (key[i] >= 'a' && key[i] <= 'f'))) {
            next.state = RA_BROWSER_OFFLINE;
            goto done;
        }
    }
    key[64] = 0;
    snprintf(packet, sizeof(packet), "CADA1 %u %c %d %d %s %s",
             query_id, query_kind, query_page, query_filter, query_target, key);
    memset(key, 0, sizeof(key));
    rc = raNetAccountPage(packet, query_id, response, sizeof(response));
    if (rc == -8) {
        next.state = RA_BROWSER_NET_BUSY;
    } else if (rc < 0) {
        next.state = RA_BROWSER_OFFLINE;
    } else if (!strncmp(response, "OFFLINE", 7)) {
        next.state = RA_BROWSER_OFFLINE;
    } else if (!strncmp(response, "UNSUPPORTED", 11)) {
        next.state = RA_BROWSER_UNSUPPORTED;
    } else if (!strncmp(response, "BUSY", 4) || !strncmp(response, "WAIT", 4)) {
        next.state = RA_BROWSER_BUSY;
    } else if (!parse_page(response, &next)) {
        next.state = RA_BROWSER_ERROR;
    }

done:
    memset(key, 0, sizeof(key));
    /* The I/O thread is the only writer, the renderer reads only when pending=0. */
    shown = next;
    __asm__ volatile("" ::: "memory");
    pending = 0;
}

static int queue_page(void)
{
    if (pending || sbHashGameBusy())
        return 0;
    pending = 1;
    request_id++;
    query_id = request_id;
    query_kind = view_kind;
    query_page = view_page;
    query_filter = view_filter;
    copy_text(query_target, sizeof(query_target), view_target);
    memset(&shown, 0, sizeof(shown));
    shown.state = RA_BROWSER_LOADING;
    if (ioPutRequest(IO_CUSTOM_SIMPLEACTION, &fetch_page) != IO_OK) {
        shown.state = RA_BROWSER_BUSY;
        pending = 0;
        return 0;
    }
    return 1;
}

void raBrowserOpen(int fromGameMenu)
{
    if (pending) {
        guiShowRANotice("Previous achievement request still running.", NULL);
        return;
    }
    return_screen = fromGameMenu ? GUI_SCREEN_GAME_MENU : GUI_SCREEN_MENU;
    view_kind = 'G';
    copy_text(view_target, sizeof(view_target), "0");
    view_page = view_filter = view_row = library_page = 0;
    queue_page();
    guiSwitchScreen(GUI_SCREEN_RA_BROWSER);
}

static void browser_line(int x, int y, const char *label, int selected)
{
    fntRenderString(gTheme->fonts[0], x, y, ALIGN_NONE, 552, 28, label,
                    selected ? gTheme->selTextColor : gTheme->textColor);
}

void raBrowserRender(void)
{
    char text[180];
    int i;
    ra_browser_page_t page;
    if (guiDrawBGSettings() == 0)
        guiDrawBGPlasma();
    if (pending) {
        browser_line(40, 70, "RetroAchievements | Loading account progress...", 0);
        browser_line(40, 115, "Back: return to menu after request completes.", 0);
        return;
    }
    page = shown;
    browser_line(40, 30, "RETROACHIEVEMENTS", 1);
    if (page.state != RA_BROWSER_READY) {
        const char *msg = page.state == RA_BROWSER_NET_BUSY
            ? "UDPFS/UDPBD owns the network; account browsing is unavailable."
            : page.state == RA_BROWSER_OFFLINE
            ? "Connect SMB and sign in to RA on PS2-Servers (Caduceus mode)."
            : page.state == RA_BROWSER_UNSUPPORTED
            ? "No achievements found for this game."
            : page.state == RA_BROWSER_BUSY
            ? "Account server is busy. Press Select to retry."
            : "Unable to load progress. Press Select to retry.";
        browser_line(40, 120, msg, 0);
        browser_line(40, 380, "Select: retry    Cancel: return", 0);
        return;
    }
    snprintf(text, sizeof(text), "%s  [%s]", view_kind == 'G' ? "Account library" : page.title,
             page.user);
    browser_line(40, 70, text, 0);
    snprintf(text, sizeof(text), "Page %d / %d  |  %d entries",
             view_page + 1, (page.total + RA_BROWSER_PAGE_SIZE - 1) / RA_BROWSER_PAGE_SIZE,
             page.total);
    browser_line(40, 98, text, 0);
    if (view_kind == 'A') {
        static const char *filters[] = {"All", "Earned", "Locked", "Hardcore"};
        snprintf(text, sizeof(text), "Unlocked: %d / %d  |  Filter: %s",
                 page.earned, page.maximum, filters[view_filter]);
        browser_line(40, 126, text, 0);
    }
    for (i = 0; i < page.count; i++) {
        ra_browser_entry_t *entry = &page.entries[i];
        int y = 165 + i * 62;
        snprintf(text, sizeof(text), "%s", entry->title);
        browser_line(48, y, text, i == view_row);
        if (view_kind == 'G')
            snprintf(text, sizeof(text), "%u/%u unlocked  (%u hardcore)",
                     entry->earned, entry->total, entry->hardcore);
        else
            snprintf(text, sizeof(text), "%u points - %s", entry->points,
                     entry->earned ? "earned" : "locked");
        browser_line(58, y + 23, text, 0);
    }
    if (page.count > 0) {
        ra_browser_entry_t *entry = &page.entries[view_row < page.count ? view_row : 0];
        browser_line(40, 370, entry->description, 0);
    }
    browser_line(40, 425,
                 view_kind == 'G' ? "L1/R1: page  Confirm: game's achievements  Select: reload  Back: exit"
                                  : "L1/R1: page  Square: filter  Select: reload  Back: library", 0);
}

void raBrowserHandleInput(void)
{
    int cancel = guiCancelKey();
    if (getKeyOn(cancel)) {
        if (view_kind == 'A' && !pending) {
            view_kind = 'G';
            copy_text(view_target, sizeof(view_target), "0");
            view_page = library_page;
            view_filter = view_row = 0;
            queue_page();
        } else {
            guiSwitchScreen(return_screen);
        }
        return;
    }
    if (pending)
        return;
    if (getKeyOn(KEY_SELECT)) {
        queue_page();
        return;
    }
    if (shown.state != RA_BROWSER_READY)
        return;
    if (getKeyOn(KEY_UP)) {
        if (view_row > 0) view_row--;
        sfxPlay(SFX_CURSOR);
    } else if (getKeyOn(KEY_DOWN)) {
        if (view_row + 1 < shown.count) view_row++;
        sfxPlay(SFX_CURSOR);
    } else if (getKeyOn(KEY_L1)) {
        if (view_page > 0) { view_page--; view_row = 0; queue_page(); }
    } else if (getKeyOn(KEY_R1)) {
        if ((view_page + 1) * RA_BROWSER_PAGE_SIZE < shown.total) {
            view_page++;
            view_row = 0;
            queue_page();
        }
    } else if (getKeyOn(KEY_SQUARE) && view_kind == 'A') {
        view_filter = (view_filter + 1) % 4;
        view_page = view_row = 0;
        queue_page();
    } else if (getKeyOn(gSelectButton) && view_kind == 'G' && shown.count > 0) {
        library_page = view_page;
        snprintf(view_target, sizeof(view_target), "%u", shown.entries[view_row].id);
        view_kind = 'A';
        view_page = view_filter = view_row = 0;
        queue_page();
    }
}
