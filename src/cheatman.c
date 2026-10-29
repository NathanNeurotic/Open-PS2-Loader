/*
 * Manage cheat codes
 *
 * Copyright (C) 2009-2010 Mathias Lafeldt <misfire@debugon.org>
 * Copyright (C) 2014 doctorxyz
 *
 * This file is part of PS2rd, the PS2 remote debugger.
 *
 * PS2rd is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * PS2rd is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with PS2rd.  If not, see <http://www.gnu.org/licenses/>.
 *
 * $Id$
 */

#include <unistd.h>
#include "include/cheatman.h"
#include "include/cheatconfig.h"
#include "include/ioman.h"
#include "../ee_core/include/igrcheats.h"

static int gEnableCheat;     // Enables PS2RD Cheat Engine - 0 for Off, 1 for On
static int gCheatMode;       // Cheat Mode - 0 Enable all cheats, 1 Cheats selected by user
static int gCheatFromGlobal; // 1 = enabled by the all-games default, not by this game's own settings

static u32 gCheatList[MAX_CHEATLIST]; // Store hooks/codes addr+val pairs
cheat_entry_t *gCheats = NULL;        // lazily allocated in load_cheats (~1.03 MB); reclaims the old permanent BSS

static int gEnableImage;           // Prebuilt PS2RD cheat image (.img) - 0 Off, 1 On
static u32 gImage[MAX_IMAGEWORDS]; // The loaded .img patch words (zeroed when none/failed)

// Release the lazily-allocated ~1.03 MB cheat table (see ensureCheatTable). Every reader is
// NULL-guarded (the cheat-selection menu and set_cheats_list), and the launch handoff never
// references gCheats -- set_cheats_list flattens it into the small static gCheatList that
// ee_core reads in-place, so freeing between launches is safe.
static void freeCheatTable(void)
{
    if (gCheats != NULL) {
        free(gCheats);
        gCheats = NULL;
    }
}

void InitCheatsConfig(config_set_t *configSet)
{
    config_set_t *configGame = configGetByType(CONFIG_GAME);

    // Default values.
    gCheatSource = 0;
    gEnableCheat = 0;
    gCheatMode = 0;
    gCheatFromGlobal = 0;
    gEnableImage = 0;

    if (configGetInt(configSet, CONFIG_ITEM_CHEATSSOURCE, &gCheatSource)) {
        // Load the rest of the per-game CHEAT configuration if CHEAT is enabled.
        if (configGetInt(configSet, CONFIG_ITEM_ENABLECHEAT, &gEnableCheat) && gEnableCheat) {
            configGetInt(configSet, CONFIG_ITEM_CHEATMODE, &gCheatMode);
        }
        configGetInt(configSet, CONFIG_ITEM_ENABLEIMAGE, &gEnableImage);
    } else {
        if (configGetInt(configGame, CONFIG_ITEM_ENABLECHEAT, &gEnableCheat) && gEnableCheat) {
            configGetInt(configGame, CONFIG_ITEM_CHEATMODE, &gCheatMode);
            gCheatFromGlobal = 1;
        }
        configGetInt(configGame, CONFIG_ITEM_ENABLEIMAGE, &gEnableImage);
    }

    // Cheats OFF for this launch: reclaim the ~1 MB table a previous cheats-ON launch may have
    // left behind (it only survives OPL at all when that launch FAILED back to the GUI -- a
    // successful launch hands off to ExecPS2). This runs in per-launch settings prep BEFORE any
    // sbLoadCheats of the same launch, so a cheats-ON launch never sees a freed table.
    if (!gEnableCheat)
        freeCheatTable();
}

int GetCheatsEnabled(void)
{
    return gEnableCheat;
}

int GetCheatsFromGlobalDefault(void)
{
    return gCheatFromGlobal;
}

const u32 *GetCheatsList(void)
{
    return gCheatList;
}

int GetImageEnabled(void)
{
    return gEnableImage;
}

const u32 *GetImage(void)
{
    return gImage;
}

// Load a prebuilt PS2RD cheat image (.img) into gImage. memset FIRST so a missing/short/failed load
// leaves a clean zeroed image (the ee_core LinkImage then no-ops on the leading zero word). POSIX IO
// only (newlib rule). Over-size files truncate to MAX_IMAGEWORDS; the ee_core bounds-checks on apply.
int LoadImage(const char *filename)
{
    int fd, len;

    memset(gImage, 0, sizeof(gImage));
    fd = open(filename, O_RDONLY);
    if (fd < 0)
        return -1;
    len = read(fd, gImage, sizeof(gImage));
    close(fd);
    return (len < 0) ? -1 : 0;
}

/*
 * make_code - Return a code object from string @s.
 */
static code_t make_code(const char *s)
{
    code_t code;
    u32 address = 0; /* init so a partial sscanf parse is safe */
    u32 value = 0;
    char digits[CODE_DIGITS + 1]; /* +1: NUL terminator after all CODE_DIGITS hex chars */
    int i = 0;

    while (*s) {
        // Collect up to CODE_DIGITS hex chars; digits[] has room for them + NUL.
        if (isxdigit((int)*s) && i < CODE_DIGITS)
            digits[i++] = *s;
        s++;
    }

    digits[i] = '\0';

    /* digits[] holds only hex chars (no spaces); no space in format string.
     * Bail on a partial parse (< 2 items) — leaves address=0/value=0. */
    if (sscanf(digits, "%08X%08X", &address, &value) != 2) {
        code.addr = 0;
        code.val = 0;
        return code;
    }

    // Return Code Address and Value
    code.addr = address;
    code.val = value;
    return code;
}


/*
 * is_cheat_code - Return non-zero if @s indicates a cheat code.
 *
 * Example: 10B8DAFA 00003F00
 */
static int is_cheat_code(const char *s)
{
    int i = 0;

    while (*s) {
        if (isxdigit((int)*s)) {
            if (++i > CODE_DIGITS)
                return 0;
        } else if (!isspace((int)*s)) {
            return 0;
        }
        s++;
    }

    return (i == CODE_DIGITS);
}

/*
 * parse_line - Parse the current line and return a filled (code found) or zeroed (code not found) object.
 */
static code_t parse_line(const char *line, int linenumber)
{
    code_t code;
    code.addr = 0;
    code.val = 0;
    int ret;
    LOG("%4i  %s\n", linenumber, line);
    ret = is_cheat_code(line);
    if (ret) {
        /* Process actual code and add it to the list. */
        code = make_code(line);
    }
    return code;
}

/*
 * is_cmt_str - Return non-zero if @s indicates a comment.
 */
static inline int is_cmt_str(const char *s)
{
    return (strlen(s) >= 2 && !strncmp(s, "//", 2)) || (*s == '#');
}

/*
 * chr_idx - Returns the index within @s of the first occurrence of the
 * specified char @c.  If no such char occurs in @s, then (-1) is returned.
 */
static int chr_idx(const char *s, char c)
{
    int i = 0;

    while (s[i] && (s[i] != c))
        i++;

    return (s[i] == c) ? i : -1;
}

/*
 * term_str - Terminate string @s where the callback functions returns non-zero.
 */
static char *term_str(char *s, int (*callback)(const char *))
{
    if (callback != NULL) {
        while (*s) {
            if (callback(s)) {
                *s = NUL;
                break;
            }
            s++;
        }
    }

    return s;
}

/*
 * is_empty_str - Returns 1 if @s contains no printable chars other than white
 * space.  Otherwise, 0 is returned.
 */
static int is_empty_str(const char *s)
{
    size_t slen = strlen(s);

    while (slen--) {
        if (isgraph((int)*s++))
            return 0;
    }

    return 1;
}

/*
 * trim_str - Removes white space from both ends of the string @s.
 */
static int trim_str(char *s)
{
    size_t first = 0;
    size_t last;
    size_t slen;
    char *t = s;

    /* Return if string is empty */
    if (is_empty_str(s))
        return -1;

    /* Get first non-space char */
    while (isspace((int)*t++))
        first++;

    /* Get last non-space char */
    last = strlen(s) - 1;
    t = &s[last];
    while (isspace((int)*t--))
        last--;

    /* Kill leading/trailing spaces */
    slen = last - first + 1;
    memmove(s, s + first, slen);
    s[slen] = NUL;

    return slen;
}

/*
 * is_empty_substr - Returns 1 if the first @count chars of @s are not printable
 * (apart from white space).  Otherwise, 0 is returned.
 */
static int is_empty_substr(const char *s, size_t count)
{
    while (count--) {
        if (isgraph((int)*s++))
            return 0;
    }

    return 1;
}

/* Max line length to parse */
#define CHEAT_LINE_MAX 255

/**
 * parse_buf - Parse a text buffer for cheats.
 * @buf: buffer holding text (must be NUL-terminated!)
 * @return: 0: success, -1: error
 */
static int parse_buf(const char *buf)
{
    code_t code;
    char line[CHEAT_LINE_MAX + 1];
    int linenumber = 1;
    int cheat_index = -1; // Starts at -1.. indicating no cheat being processed yet
    int code_index = 0;
    char temp_name[CHEAT_NAME_MAX + 1] = {0};

    if (buf == NULL)
        return -1;

    while (*buf) {
        /* Scanner */
        int lfIdx = chr_idx(buf, LF);
        int len = lfIdx;
        if (len < 0)
            len = strlen(buf);
        // Cap BOTH branches: a final line with no trailing LF longer than CHEAT_LINE_MAX used to
        // strncpy past line[256] -- a stack smash on the launch thread. Loose .cht files always
        // carried this; community-distributed cht.tar packs make malformed input a first-class
        // vector, so it lands with the tar support (adversarial review of #154).
        if (len > CHEAT_LINE_MAX)
            len = CHEAT_LINE_MAX;

        if (!is_empty_substr(buf, len)) {
            strncpy(line, buf, len);
            line[len] = NUL;

            /* Screener */
            term_str(line, is_cmt_str);
            trim_str(line);

            // Check if the line is a cheat name
            if (!is_cheat_code(line) && strlen(line) > 0) {
                // Store the cheat name temporarily
                strncpy(temp_name, line, CHEAT_NAME_MAX);
                temp_name[CHEAT_NAME_MAX] = NUL;
                // Reset code index in case this is a new cheat
                code_index = 0;
            } else {
                /* Parser */
                code = parse_line(line, linenumber);
                if (!(code.addr == 0 && code.val == 0)) {
                    // Only add the cheat entry if we have a valid cheat name in temp_name.
                    if (temp_name[0] != NUL) {
                        // belomaxorka / YAOPL 44a003bd: once full, stop before another
                        // cheat's codes can overwrite or append to the last accepted cheat.
                        if (cheat_index + 1 >= MAX_CODES) {
                            LOG("%s: more than %d cheats, ignoring the rest\n", __FUNCTION__, MAX_CODES);
                            break;
                        }
                        cheat_index++; // Move to the next cheat entry
                        strncpy(gCheats[cheat_index].name, temp_name, CHEAT_NAME_MAX);
                        gCheats[cheat_index].name[CHEAT_NAME_MAX] = NUL;
                        // Auto mode runs every cheat; Select mode starts from the master codes
                        // alone, and the game's remembered picks are applied on top (cheatconfig.c).
                        gCheats[cheat_index].enabled = (gCheatMode == 0) || cheatConfigIsMasterCode(gCheats[cheat_index].name);
                        temp_name[0] = NUL; // Clear temp_name after use
                    }
                    // Add the cheat code to the current cheat entry
                    if (cheat_index >= 0 && code_index < MAX_CHEATLIST)
                        gCheats[cheat_index].codes[code_index++] = code;
                }
            }
        }
        linenumber++;
        // Advance past the LF only when one was found. On the final line without a
        // trailing newline, stop at the NUL rather than reading one byte past it.
        buf += (lfIdx < 0) ? len : len + 1;
    }

    return 0;
}

/**
 * read_text_file - Reads text from a file into a buffer.
 * @filename: name of text file
 * @maxsize: max file size (0: arbitrary size)
 * @return: ptr to NULL-terminated text buffer, or NULL if an error occured
 */
static inline char *read_text_file(const char *filename, int maxsize)
{
    char *buf = NULL;
    int fd, filesize;

    fd = open(filename, O_RDONLY);
    if (fd < 0) {
        LOG("%s: Can't open text file %s\n", __FUNCTION__, filename);
        return NULL;
    }

    filesize = lseek(fd, 0, SEEK_END);
    if (filesize < 0) {
        LOG("%s: Can't seek in text file %s\n", __FUNCTION__, filename);
        close(fd);
        return NULL;
    }

    if (maxsize > 0 && filesize > maxsize) {
        LOG("%s: Text file too large: %i bytes, max: %i bytes\n", __FUNCTION__, filesize, maxsize);
        close(fd);
        return NULL;
    }

    buf = malloc(filesize + 1);
    if (buf == NULL) {
        LOG("%s: Unable to allocate %i bytes\n", __FUNCTION__, filesize + 1);
        close(fd);
        return NULL;
    }

    if (filesize > 0) {
        if (lseek(fd, 0, SEEK_SET) != 0) {
            LOG("%s: Can't seek to start of text file %s\n", __FUNCTION__, filename);
            free(buf);
            close(fd);
            return NULL;
        }
        if (read(fd, buf, filesize) != filesize) {
            LOG("%s: Can't read from text file %s\n", __FUNCTION__, filename);
            free(buf);
            close(fd);
            return NULL;
        }
    }

    buf[filesize] = '\0';
    close(fd);

    return buf;
}

/*
 * Load cheats from text file.
 */
// Lazy cheat table: MAX_CODES x sizeof(cheat_entry_t) (~1.03 MB) that used to sit in BSS
// permanently, held even with cheats off (the default). Allocated on the first cheat load and
// kept for the session (a successful launch hands off to ExecPS2 anyway; a failed one reuses
// the buffer on retry). An allocation failure degrades exactly like an unreadable cheat file --
// the launch legs already toast _STR_ERR_CHEATS_LOAD_FAILED for ret < 0. Shared by the loose-
// file loader below and the CHT/cht.tar member loader (load_cheats_buf).
static int ensureCheatTable(void)
{
    if (gCheats == NULL) {
        gCheats = (cheat_entry_t *)malloc(MAX_CODES * sizeof(cheat_entry_t));
        if (gCheats == NULL) {
            LOG("%s: cheat table allocation failed (%d bytes)\n", __FUNCTION__, (int)(MAX_CODES * sizeof(cheat_entry_t)));
            return -1;
        }
    }
    memset(gCheats, 0, MAX_CODES * sizeof(cheat_entry_t));
    return 0;
}

int load_cheats(const char *cheatfile)
{
    char *buf = NULL;
    int ret;

    if (ensureCheatTable() < 0)
        return -1;

    LOG("%s: Reading cheat file '%s'...\n", __FUNCTION__, cheatfile);
    buf = read_text_file(cheatfile, 0);
    if (buf == NULL) {
        LOG("%s: Could not read cheats file '%s'\n", __FUNCTION__, cheatfile);
        return -1;
    }

    ret = parse_buf(buf);
    free(buf);

    if (ret < 0)
        return ret;

    return (gCheatMode == 0) ? 0 : 1;
}

// Parse cheats from an in-memory buffer (a CHT/cht.tar member). buf MUST be NUL-terminated --
// tar members carry no terminator, so the caller allocates rawSize+1 and terminates. wOPL's
// variant takes an unused size parameter and feeds the raw tar buffer to the parser (a latent
// overread); the explicit contract here avoids porting that.
int load_cheats_buf(const char *buf)
{
    int ret;

    if (buf == NULL || ensureCheatTable() < 0)
        return -1;

    ret = parse_buf(buf);
    if (ret < 0)
        return ret;

    return (gCheatMode == 0) ? 0 : 1;
}

void set_cheats_list(void)
{
    int cheatCount = 0;

    memset((void *)gCheatList, 0, sizeof(gCheatList));

    // No cheat file was ever loaded this session: the zeroed list above ALREADY carries its
    // addr=0 terminator, so return instead of re-testing the pointer every loop iteration
    // (PR #101 review -- LOG in the body forces a reload of the global each pass).
    if (gCheats == NULL)
        return;

    // Populate the cheat list
    for (int i = 0; i < MAX_CODES; ++i) {
        if (gCheats[i].enabled) {
            for (int j = 0; j < MAX_CHEATLIST && gCheats[i].codes[j].addr != 0; ++j) {
                if (cheatCount + 2 <= MAX_CHEATLIST) {
                    // Store the address and value in gCheatList
                    gCheatList[cheatCount++] = gCheats[i].codes[j].addr;
                    gCheatList[cheatCount++] = gCheats[i].codes[j].val;
                    LOG("%s: Setting cheat for eecore:\n%s\n%08X %08X\n", __FUNCTION__, gCheats[i].name, gCheats[i].codes[j].addr, gCheats[i].codes[j].val);
                } else
                    break;
            }
        }
    }

    // Append a blank cheat entry if theres space
    if (cheatCount < MAX_CHEATLIST) {
        gCheatList[cheatCount++] = 0; // addr
        gCheatList[cheatCount++] = 0; // val
    } else {
        // Overwrite the last cheat with a blank cheat if we are at max
        gCheatList[cheatCount - 2] = 0; // addr
        gCheatList[cheatCount - 1] = 0; // val
    }
}

/*
 * The in-game menu's CHEATS page (ee_core/include/igrcheats.h, RIPPS2's menu by akilluminati47).
 *
 * igrCheatsPack lays out every cheat of the loaded file at dst: its name and its codes, hook codes left out (the
 * engine plants the hook once, when the game calls SetupThread, so a hook cannot be switched later), and whether it
 * is ticked now. set_cheats_list_live then rebuilds gCheatList for that launch: every cheat's hook codes, so the
 * hook is planted even when the master code row is not ticked, and the ticked cheats' other codes, whole cheats
 * while they fit the engine's MAX_CODES. That is the set igrCheatsBuild makes from the same ticks, so the menu's
 * first change starts from the set the game began with.
 */

// A hook code, by the engine's own rule (ee_core cheat_api.c SetupCheats): 0x90/0x91 addresses, unless the line
// before was the first of a two-line 3- or 4-type code. prevCanHook carries that across one cheat's lines.
static int cheatIsHook(const code_t *c, int *prevCanHook)
{
    int hook = ((c->addr & 0xfe000000) == 0x90000000) && *prevCanHook;
    *prevCanHook = !((c->addr & 0xf0000000) == 0x40000000 || (c->addr & 0xf0000000) == 0x30000000);
    return hook;
}

static int cheatRealCodes(const cheat_entry_t *e)
{
    int n = 0, canHook = 1;
    for (int j = 0; j < MAX_CHEATLIST && e->codes[j].addr != 0; ++j)
        if (!cheatIsHook(&e->codes[j], &canHook))
            n++;
    return n;
}

// One more row of n codes fits the page after count rows of pairs codes. Both of igrCheatsPack's walks ask this.
static int igrRowFits(unsigned int count, unsigned int pairs, int n, unsigned int room)
{
    return count < IGR_CHEATS_MAX && n <= IGR_CHEAT_SET_CODES && pairs + n <= IGR_CHEAT_CODES_MAX &&
           IGR_CHEATS_BYTES(count + 1, pairs + n) <= room;
}

int igrCheatsPack(void *dst, unsigned int room)
{
    igr_cheats_t *h = (igr_cheats_t *)dst;
    unsigned int count = 0, pairs = 0;

    if (gCheats == NULL || dst == NULL || room < IGR_CHEATS_BYTES(1, 1))
        return 0;
    // what fits: rows first, then their codes. A ticked cheat the page cannot hold means no page: the game then
    // starts with the list it gets without the menu's page (set_cheats_list), and the ticked cheat runs.
    for (int i = 0; i < MAX_CODES; ++i) {
        int n = gCheats[i].codes[0].addr != 0 ? cheatRealCodes(&gCheats[i]) : 0;
        if (n == 0)
            continue;
        if (!igrRowFits(count, pairs, n, room)) {
            if (gCheats[i].enabled)
                return 0;
            continue;
        }
        count++;
        pairs += n;
    }
    if (count == 0)
        return 0;

    memset(dst, 0, IGR_CHEATS_BYTES(count, pairs));
    h->magic = IGR_CHEATS_MAGIC;
    h->count = count;
    h->pairs = pairs;
    igr_cheat_t *row = IGR_CHEATS_ROWS(h);
    unsigned int *codes = IGR_CHEATS_CODES(h), r = 0, p = 0;
    for (int i = 0; i < MAX_CODES && r < count; ++i) {
        int n = gCheats[i].codes[0].addr != 0 ? cheatRealCodes(&gCheats[i]) : 0;
        if (n == 0 || !igrRowFits(r, p, n, room))
            continue;
        int canHook = 1;
        row[r].first = p;
        row[r].count = n;
        row[r].on = gCheats[i].enabled ? 1 : 0;
        // the menu's font is upper case ASCII: anything else shows as '?'
        snprintf(row[r].name, sizeof(row[r].name), "%s", gCheats[i].name[0] ? gCheats[i].name : "CHEAT");
        for (int j = 0; j < MAX_CHEATLIST && gCheats[i].codes[j].addr != 0; ++j)
            if (!cheatIsHook(&gCheats[i].codes[j], &canHook)) {
                codes[p * 2] = gCheats[i].codes[j].addr;
                codes[p * 2 + 1] = gCheats[i].codes[j].val;
                p++;
            }
        r++;
    }
    // ticks that do not fit one set come off, last first, so the rows say what runs
    for (int i = (int)count - 1; i >= 0; --i) {
        unsigned int on = 0;
        for (unsigned int k = 0; k < count; ++k)
            if (row[k].on)
                on += row[k].count;
        if (on <= IGR_CHEAT_SET_CODES)
            break;
        row[i].on = 0;
    }
    return (int)IGR_CHEATS_BYTES(count, pairs);
}

void set_cheats_list_live(const void *packed)
{
    const igr_cheats_t *h = (const igr_cheats_t *)packed;
    int cheatCount = 0;
    unsigned int set[IGR_CHEATS_SPARE_WORDS];

    memset((void *)gCheatList, 0, sizeof(gCheatList));
    if (gCheats == NULL)
        return;
    // every hook, from every cheat: the engine takes MAX_HOOKS, so the ticked cheats' hooks go first, and a hook two
    // cheats share is listed once
    for (int pass = 0; pass < 2; ++pass)
        for (int i = 0; i < MAX_CODES; ++i) {
            if ((gCheats[i].enabled != 0) != (pass == 0))
                continue;
            int canHook = 1;
            for (int j = 0; j < MAX_CHEATLIST && gCheats[i].codes[j].addr != 0; ++j) {
                if (!cheatIsHook(&gCheats[i].codes[j], &canHook) || cheatCount + 2 > MAX_HOOKS * 2)
                    continue;
                int seen = 0;
                for (int d = 0; d < cheatCount && !seen; d += 2)
                    seen = gCheatList[d] == gCheats[i].codes[j].addr && gCheatList[d + 1] == gCheats[i].codes[j].val;
                if (!seen) {
                    gCheatList[cheatCount++] = gCheats[i].codes[j].addr;
                    gCheatList[cheatCount++] = gCheats[i].codes[j].val;
                }
            }
        }
    // then the ticked rows' codes, as the menu builds them: at most MAX_CODES, so with MAX_HOOKS hooks the list is
    // exactly full, which SetupCheats reads without a terminator (it stops at MAX_CHEATLIST); a shorter list ends
    // in the zeros of the memset above
    unsigned int n = igrCheatsBuild(h, set);
    for (unsigned int k = 0; k < n && cheatCount + 2 <= MAX_CHEATLIST; ++k) {
        gCheatList[cheatCount++] = set[1 + k * 2];
        gCheatList[cheatCount++] = set[2 + k * 2];
    }
}
