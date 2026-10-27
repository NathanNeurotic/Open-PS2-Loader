/* Adapted from Rian6/caduceus-opl 2a98a9d, AFL-3.0. The Xerabora-mode data
   source below is RiptOPL's own, after ORBIT's use of the xeRAbora PC's HTTP
   interface (map only). */
#ifdef RETROACHIEVEMENTS
#include "include/opl.h"
#include "include/achievements.h"
#include "include/ranet.h"
#include "include/ioman.h"
#include "include/supportbase.h"
#include "include/ethsupport.h"
#include "include/discsupport.h"
#include "include/rahash.h"
#include "include/udpfssupport.h" /* udpfsGetModulesLoaded: the UDPFS share */
#include "include/ratls.h"        /* raHttpsGet: the ORBIT-style game-ID lookup */
static volatile int busy;
static achievement_page_t result;
static char request[180];
static unsigned int serial;
static char requestKind;
static int requestPage, requestFilter;
static char requestTarget[33];
static char imagePath[256], imageStartup[16];
static int imageIsVcd;
/* Empty fields are significant; strtok would merge them. */
static char *field(char **cursor, char separator)
{
    char *start = *cursor, *end;
    if (!start)
        return NULL;
    end = strchr(start, separator);
    if (end) {
        *end = 0;
        *cursor = end + 1;
    } else
        *cursor = NULL;
    return start;
}
static int integer(char *text, int *value)
{
    char *end;
    if (!text || !*text)
        return 0;
    long n = strtol(text, &end, 10);
    if (*end || n < 0 || n > 10000000)
        return 0;
    *value = n;
    return 1;
}
int achievementsParse(char *reply, achievement_page_t *out)
{
    char *lines = reply, *header = field(&lines, '\n'), *part;
    if (!out)
        return 0;
    memset(out, 0, sizeof(*out));
    out->state = ACH_ERROR;
    if (!header)
        return 0;
    if (!strcmp(header, "OFFLINE")) {
        out->state = ACH_OFFLINE;
        return 1;
    }
    if (!strcmp(header, "UNSUPPORTED")) {
        out->state = ACH_UNSUPPORTED;
        return 1;
    }
    part = field(&header, '\t');
    if (!part || strcmp(part, "OK"))
        return 0;
    part = field(&header, '\t');
    if (!part || strlen(part) != 1 || (*part != 'G' && *part != 'A'))
        return 0;
    out->kind = *part;
    if (!integer(field(&header, '\t'), &out->page) ||
        !integer(field(&header, '\t'), &out->total) ||
        !integer(field(&header, '\t'), &out->gameId) ||
        !integer(field(&header, '\t'), &out->earned) ||
        !integer(field(&header, '\t'), &out->maximum))
        return 0;
    part = field(&header, '\t');
    if (!part || strlen(part) > 24)
        return 0;
    snprintf(out->user, sizeof(out->user), "%s", part);
    part = field(&header, '\t');
    if (!part || strlen(part) > 56 || header)
        return 0;
    snprintf(out->title, sizeof(out->title), "%s", part);
    while (lines && *lines) {
        char *row = field(&lines, '\n');
        if (out->count == ACH_PAGE_SIZE)
            return 0;
        achievement_entry_t *entry = &out->entries[out->count++];
        if (!integer(field(&row, '\t'), &entry->id) || !entry->id ||
            !integer(field(&row, '\t'), &entry->total) ||
            !integer(field(&row, '\t'), &entry->earned) ||
            !integer(field(&row, '\t'), &entry->hardcore) ||
            !integer(field(&row, '\t'), &entry->points))
            return 0;
        part = field(&row, '\t');
        if (!part)
            return 0;
        if (strcmp(part, "-")) {
            if (strlen(part) != 32 || strspn(part, "0123456789abcdef") != 32)
                return 0;
            snprintf(entry->icon, sizeof(entry->icon), "%s", part);
        }
        part = field(&row, '\t');
        if (!part || strlen(part) > 56)
            return 0;
        snprintf(entry->title, sizeof(entry->title), "%s", part);
        part = field(&row, '\t');
        if (!part || strlen(part) > 100)
            return 0;
        snprintf(entry->description, sizeof(entry->description), "%s", part);
        part = field(&row, '\t');
        if (!part || strlen(part) > 19 || row)
            return 0;
        snprintf(entry->date, sizeof(entry->date), "%s", part);
    }
    if (out->count > out->total || out->earned > out->maximum)
        return 0;
    out->state = ACH_READY;
    return 1;
}
/* ---- Xerabora mode -------------------------------------------------------
   ORBIT parity: the list and the player's progress come from the xeRAbora
   PC's HTTP interface (port 18280; OPEN TO THE NETWORK in its settings).
   /library gives the account's played games, /game?id=N one game's set. The
   whole document is parsed once into a cached list; pages and filters are
   served from it, so L1/R1/Square never refetch. Select marks it stale. */
#define XERA_HTTP_PORT 18280
#define XERA_DOC_MAX   (512 * 1024)
#define XERA_LIST_MAX  1024
static achievement_entry_t *xeraList;
static int xeraCount, xeraId = -1, xeraEarned, xeraMaximum;
static char xeraKind, xeraTitle[57];
static volatile int xeraStale;

static const char *jsonWs(const char *p, const char *e)
{
    while (p < e && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
        p++;
    return p;
}

/* Appends code point c as UTF-8 if it fits whole. */
static int jsonPutUtf8(char *out, int at, int size, unsigned int c)
{
    char b[4];
    int n = c < 0x80 ? 1 : c < 0x800 ? 2 :
                                       3;
    if (n == 1)
        b[0] = c;
    else if (n == 2) {
        b[0] = 0xC0 | (c >> 6);
        b[1] = 0x80 | (c & 0x3F);
    } else {
        b[0] = 0xE0 | (c >> 12);
        b[1] = 0x80 | ((c >> 6) & 0x3F);
        b[2] = 0x80 | (c & 0x3F);
    }
    if (at + n >= size)
        return at;
    memcpy(out + at, b, n);
    return at + n;
}

/* p at the opening quote. Decodes into out (NUL-terminated, never splitting a
   UTF-8 sequence) and returns the position after the closing quote, or NULL. */
static const char *jsonString(const char *p, const char *e, char *out, int size)
{
    int at = 0;
    if (p >= e || *p != '"')
        return NULL;
    for (p++; p < e && *p != '"'; p++) {
        unsigned int c = (unsigned char)*p;
        if (c == '\\') {
            if (++p >= e)
                return NULL;
            switch (*p) {
                case 'n':
                case 't':
                case 'r':
                case 'b':
                case 'f':
                    c = ' ';
                    break;
                case 'u': {
                    unsigned int u = 0;
                    int i;
                    if (p + 4 >= e)
                        return NULL;
                    for (i = 1; i <= 4; i++) {
                        char h = p[i];
                        u = u * 16 + (h >= '0' && h <= '9' ? h - '0' : h >= 'a' && h <= 'f' ? h - 'a' + 10 :
                                                                   h >= 'A' && h <= 'F'     ? h - 'A' + 10 :
                                                                                              0);
                    }
                    p += 4;
                    c = (u >= 0xD800 && u <= 0xDFFF) ? '?' : u; /* astral planes: not in the menu font */
                    break;
                }
                default:
                    c = (unsigned char)*p; /* \" \\ \/ */
            }
            if (out)
                at = jsonPutUtf8(out, at, size, c);
            continue;
        }
        if (out && at + 1 < size) {
            /* Raw UTF-8: copy a lead byte only if its whole sequence fits. */
            int n = c < 0x80 ? 1 : (c & 0xE0) == 0xC0 ? 2 :
                               (c & 0xF0) == 0xE0     ? 3 :
                               (c & 0xF8) == 0xF0     ? 4 :
                                                        1;
            if (n > 1 && (c & 0xC0) != 0x80) {
                if (at + n < size && p + n <= e) {
                    memcpy(out + at, p, n);
                    at += n;
                }
                p += n - 1;
                continue;
            }
            out[at++] = c;
        }
    }
    if (out && size > 0)
        out[at < size ? at : size - 1] = '\0';
    return p < e ? p + 1 : NULL;
}

/* Skips any value (string, number, literal, object, array); NULL on malformed input. */
static const char *jsonSkip(const char *p, const char *e)
{
    int depth = 0;
    p = jsonWs(p, e);
    do {
        if (p >= e)
            return NULL;
        if (*p == '"') {
            p = jsonString(p, e, NULL, 0);
            if (!p)
                return NULL;
        } else if (*p == '{' || *p == '[') {
            depth++;
            p++;
        } else if (*p == '}' || *p == ']') {
            if (--depth < 0)
                return NULL;
            p++;
        } else if (depth == 0) {
            while (p < e && *p != ',' && *p != '}' && *p != ']')
                p++;
            return p;
        } else
            p++;
    } while (depth > 0);
    return p;
}

/* Calls back for each member of the object at p; returns the position after it. */
typedef void (*json_member_fn)(const char *key, const char *value, const char *e, void *ctx);
static const char *jsonObject(const char *p, const char *e, json_member_fn fn, void *ctx)
{
    char key[32];
    p = jsonWs(p, e);
    if (p >= e || *p != '{')
        return NULL;
    p = jsonWs(p + 1, e);
    if (p < e && *p == '}')
        return p + 1;
    while (p < e) {
        p = jsonString(jsonWs(p, e), e, key, sizeof(key));
        if (!p || (p = jsonWs(p, e)) >= e || *p != ':')
            return NULL;
        p = jsonWs(p + 1, e);
        fn(key, p, e, ctx);
        if (!(p = jsonSkip(p, e)) || (p = jsonWs(p, e)) >= e)
            return NULL;
        if (*p == '}')
            return p + 1;
        if (*p++ != ',')
            return NULL;
    }
    return NULL;
}

static int jsonInt(const char *v)
{
    long n = strtol(v, NULL, 10);
    return n < 0 ? 0 : n > 10000000 ? 10000000 :
                                      (int)n;
}

typedef struct
{
    char kind;
    achievement_entry_t *entry;
    const char *array;
} xera_parse_t;

static void xeraEntryMember(const char *key, const char *v, const char *e, void *ctx)
{
    xera_parse_t *x = ctx;
    achievement_entry_t *a = x->entry;
    if (!strcmp(key, "id"))
        a->id = jsonInt(v);
    else if (!strcmp(key, "title") && *v == '"')
        jsonString(v, e, a->title, sizeof(a->title));
    else if (!strcmp(key, "description") && *v == '"')
        jsonString(v, e, a->description, sizeof(a->description));
    else if (!strcmp(key, "points"))
        a->points = jsonInt(v);
    else if (x->kind == 'G' && !strcmp(key, "total"))
        a->total = jsonInt(v);
    else if (x->kind == 'G' && !strcmp(key, "awarded"))
        a->earned = jsonInt(v);
    else if (x->kind == 'G' && !strcmp(key, "hardcore"))
        a->hardcore = jsonInt(v);
    else if (x->kind == 'A' && !strcmp(key, "earned") && *v == '"') {
        jsonString(v, e, a->date, sizeof(a->date)); /* "YYYY-MM-DD hh:mm:ss", empty while locked */
        a->earned = a->date[0] != '\0';
    }
}

static void xeraRootMember(const char *key, const char *v, const char *e, void *ctx)
{
    xera_parse_t *x = ctx;
    if (!strcmp(key, x->kind == 'G' ? "games" : "achievements") && *v == '[')
        x->array = v;
    else if (x->kind == 'A' && !strcmp(key, "title") && *v == '"')
        jsonString(v, e, xeraTitle, sizeof(xeraTitle));
    else if (x->kind == 'A' && !strcmp(key, "total"))
        xeraMaximum = jsonInt(v);
    else if (x->kind == 'A' && !strcmp(key, "awarded"))
        xeraEarned = jsonInt(v);
}

/* Parses a /library ('G') or /game ('A') document into the cache. 1 = parsed. */
int achievementsParseXerabora(char kind, const char *json, int length)
{
    const char *e = json + length, *p;
    xera_parse_t x = {kind, NULL, NULL};
    achievement_entry_t *list = malloc(XERA_LIST_MAX * sizeof(*list));
    int count = 0;

    if (!list)
        return 0;
    xeraTitle[0] = '\0';
    xeraEarned = xeraMaximum = 0;
    if (!jsonObject(json, e, xeraRootMember, &x) || !x.array) {
        free(list);
        return 0;
    }
    p = jsonWs(x.array + 1, e);
    while (p < e && *p != ']') {
        if (count == XERA_LIST_MAX)
            break; /* keep the first XERA_LIST_MAX: larger than any RA set */
        memset(&list[count], 0, sizeof(*list));
        x.entry = &list[count];
        if (!(p = jsonObject(p, e, xeraEntryMember, &x))) {
            free(list);
            return 0;
        }
        if (list[count].id > 0)
            count++;
        p = jsonWs(p, e);
        if (p < e && *p == ',')
            p = jsonWs(p + 1, e);
    }
    free(xeraList);
    xeraList = list;
    xeraCount = count;
    xeraKind = kind;
    if (kind == 'G') {
        int i;
        for (i = 0; i < count; i++)
            xeraMaximum += list[i].total, xeraEarned += list[i].earned;
    }
    return 1;
}

/* Serves one page of the cached list through the browser's filters
   (0 All, 1 Earned, 2 Locked, 3 Hardcore). */
void achievementsXeraboraPage(achievement_page_t *out, char kind, int page, int filter)
{
    int i, match = 0;
    memset(out, 0, sizeof(*out));
    out->state = ACH_READY;
    out->kind = kind;
    out->page = page;
    out->gameId = kind == 'A' ? xeraId : 0;
    out->earned = xeraEarned;
    out->maximum = xeraMaximum;
    snprintf(out->title, sizeof(out->title), "%s", kind == 'A' ? xeraTitle : "");
    for (i = 0; i < xeraCount; i++) {
        const achievement_entry_t *a = &xeraList[i];
        if (kind == 'A' && ((filter == 1 && !a->earned) || (filter == 2 && a->earned) || (filter == 3 && !a->hardcore)))
            continue;
        if (match >= page * ACH_PAGE_SIZE && out->count < ACH_PAGE_SIZE)
            out->entries[out->count++] = *a;
        match++;
    }
    out->total = match;
}

/* 1 = cached list ready, 0 = the document did not parse, -1 = xeRAbora did not answer. */
static int xeraFetch(unsigned int host, char kind, int id)
{
    char path[32], *doc;
    int body, length, ok;

    if (!xeraStale && xeraList && xeraKind == kind && (kind == 'G' || xeraId == id))
        return 1;
    doc = malloc(XERA_DOC_MAX);
    if (!doc)
        return 0;
    if (kind == 'G')
        snprintf(path, sizeof(path), "/library");
    else
        snprintf(path, sizeof(path), "/game?id=%d", id);
    body = raNetHttpGet(host, XERA_HTTP_PORT, path, doc, XERA_DOC_MAX, &length);
    ok = body < 0 ? -1 : achievementsParseXerabora(kind, doc + body, length);
    free(doc);
    if (ok == 1) {
        xeraId = kind == 'A' ? id : -1;
        xeraStale = 0;
    }
    return ok;
}

static int xeraState(int fetched)
{
    return fetched < 0 ? ACH_OFFLINE : ACH_ERROR;
}

/* A failed raNetXeraboraIdentify: -7 is the PC still identifying the image (retry),
   -8 not Xerabora mode or a reserved NIC (a UDP transport holds it); only the rest mean
   the PC is not reachable (#1062). */
static int xeraIdentifyState(int rc)
{
    return rc == -7 ? ACH_ERROR : rc == -8 ? ACH_NET_BUSY :
                                             ACH_OFFLINE;
}

/* The account library entry for an image: exact title, case-insensitive. */
static int xeraFindGame(const char *title)
{
    int i;
    for (i = 0; i < xeraCount; i++)
        if (!strcasecmp(xeraList[i].title, title))
            return xeraList[i].id;
    return 0;
}

typedef struct
{
    int success, id;
} gameid_parse_t;

static void gameIdMember(const char *key, const char *v, const char *e, void *ctx)
{
    gameid_parse_t *g = ctx;
    char *end;
    long n;

    if (!strcmp(key, "Success"))
        g->success = e - v >= 4 && !strncmp(v, "true", 4);
    else if (!strcmp(key, "GameID") && v < e && *v >= '0' && *v <= '9') {
        n = strtol(v, &end, 10);
        if (end > v && end <= e && n >= 0 && n <= 100000000)
            g->id = (int)n;
    }
}

int achievementsParseGameId(const char *json, int length)
{
    gameid_parse_t g = {0, -1};

    if (json == NULL || length <= 0 || !jsonObject(json, json + length, gameIdMember, &g))
        return -1;
    return g.success ? g.id : -1;
}

/* Set when the last HTTPS lookup could not run because the console clock is
   unset; the browser then says so (read by the GUI, written here). */
static volatile int xeraClockNote;
/* No internet (DNS, connect or the deadline failed): one attempt per session, so a console
   without a route to retroachievements.org does not wait at every game card. Select
   (achievementsForget) tries again. */
static int xeraHttpsUnreachable;

int achievementsClockUnset(void)
{
    return xeraClockNote;
}

/* ORBIT's lookup: retroachievements.org's public connect API maps an image
   hash to its game ID. >= 0 = the ID (0 = unknown to RetroAchievements),
   < 0 = no answer (no internet, TLS or certificate failure, unset clock). */
static int raHttpsGameId(const char *hash)
{
    static char doc[2048];
    char path[64];
    int body, length;

    xeraClockNote = 0;
    if (hash == NULL || strlen(hash) != 32 || strspn(hash, "0123456789abcdef") != 32)
        return -1; /* never put anything but a hash into the request line */
    if (xeraHttpsUnreachable)
        return -1;
    snprintf(path, sizeof(path), "/dorequest.php?r=gameid&m=%s", hash);
    body = raHttpsGet("retroachievements.org", path, doc, sizeof(doc), &length);
    if (body < 0) {
        if (body == RATLS_ERR_CLOCK)
            xeraClockNote = 1;
        if (body == RATLS_ERR_NET || body == RATLS_ERR_TIMEOUT)
            xeraHttpsUnreachable = 1;
        return -1;
    }
    return achievementsParseGameId(doc + body, length - body);
}

static void loadXerabora(void)
{
    char hash[33], boot[16], title[57];
    unsigned int host;
    int count, id, rc;

    if (imagePath[0]) {
        if (imageIsVcd ? raHashVcd(imagePath, boot, sizeof(boot), hash) != 0 :
                         raHashIsoDirect(imagePath, imageStartup, hash) != 0)
            return; /* ACH_ERROR */
        /* The xeRAbora PC serves the list either way: find it first (this
           also brings the network up). */
        if ((rc = raNetXeraboraIdentify(NULL, NULL, &host, title, sizeof(title), &count)) != 0) {
            result.state = xeraIdentifyState(rc);
            return;
        }
        /* ORBIT's path: the game ID from retroachievements.org by hash, so a
           game never played still shows its whole list. */
        if ((id = raHttpsGameId(hash)) == 0) {
            result.state = ACH_UNSUPPORTED;
            return;
        }
        if (id > 0) {
            requestKind = 'A';
            requestPage = 0;
            requestFilter = 0;
            goto fetch;
        }
        /* No internet (or no clock): #926's match by title in the library. */
        rc = raNetXeraboraIdentify(hash, imageIsVcd ? boot : imageStartup, &host, title, sizeof(title), &count);
        if (rc == 1) {
            result.state = ACH_UNSUPPORTED;
            return;
        }
        if (rc != 0) {
            result.state = xeraIdentifyState(rc);
            return;
        }
        if ((rc = xeraFetch(host, 'G', 0)) != 1) {
            result.state = xeraState(rc);
            return;
        }
        if ((id = xeraFindGame(title)) == 0) {
            /* Known to RetroAchievements, not yet in this account's library. */
            memset(&result, 0, sizeof(result));
            result.state = ACH_NOT_PLAYED;
            result.kind = 'A';
            result.maximum = count;
            snprintf(result.title, sizeof(result.title), "%s", title);
            return;
        }
        requestKind = 'A';
        requestPage = 0;
        requestFilter = 0;
    } else {
        if ((rc = raNetXeraboraIdentify(NULL, NULL, &host, title, sizeof(title), &count)) != 0) {
            result.state = xeraIdentifyState(rc);
            return;
        }
        id = requestKind == 'A' ? (int)strtol(requestTarget, NULL, 10) : 0;
        if (requestKind == 'A' && id <= 0)
            return; /* ACH_ERROR */
    }
fetch:
    if ((rc = xeraFetch(host, requestKind, id)) != 1) {
        result.state = xeraState(rc);
        return;
    }
    achievementsXeraboraPage(&result, requestKind, requestPage, requestFilter);
}

void achievementsForget(void)
{
    xeraStale = 1;            /* read by the I/O thread on the next request */
    xeraHttpsUnreachable = 0; /* and Select retries the online lookup */
}

/* The share that holds ART/CADUCEUS.KEY and the badge images: the folder
   PS2-Servers serves while UDPFS Files owns the NIC (its pages travel over
   the mstack: link), else the SMB share. NULL = none reachable: UDPFS IMG
   serves a disk image, and UDPBD has no share at all. */
static const char *cadSharePrefix(void)
{
    if (gNetworkProtocol == NET_PROTO_UDPFS)
        return udpfsGetModulesLoaded() ? "udpfs:/" : NULL;
    if (raNetNicReserved())
        return NULL;
    return ethEnsureSMBShareConnected() ? ethGetSMBPrefix() : NULL;
}

static void loadPage(void)
{
    static char response[1024];
    memset(&result, 0, sizeof(result));
    result.state = ACH_ERROR;
    char key[68], keyPath[256], hash[33];
    const char *share;
    int fd, length;
    if (gRAMode == RA_MODE_XERABORA) {
        loadXerabora();
        goto done;
    }
    if ((share = cadSharePrefix()) == NULL) {
        result.state = ACH_OFFLINE;
        goto done;
    }
    if (imagePath[0]) {
        if (imageIsVcd) {
            char boot[16];
            if (raHashVcd(imagePath, boot, sizeof(boot), hash) != 0)
                goto done;
        } else if (raHashIsoDirect(imagePath, imageStartup, hash) != 0)
            goto done;
        snprintf(request, sizeof(request), "CADA1 %u A 0 0 %s", serial, hash);
    }
    snprintf(keyPath, sizeof(keyPath), "%sART/CADUCEUS.KEY", share);
    fd = open(keyPath, O_RDONLY);
    if (fd < 0 && !strcmp(share, "udpfs:/")) {
        /* A case-sensitive UDPFS server may hold the folder as art/ (udpfssupport probes both
           for cover art the same way). */
        snprintf(keyPath, sizeof(keyPath), "%sart/CADUCEUS.KEY", share);
        fd = open(keyPath, O_RDONLY);
    }
    length = fd >= 0 ? read(fd, key, sizeof(key) - 1) : -1;
    if (fd >= 0)
        close(fd);
    if (length < 0 || length >= (int)sizeof(key) - 1) {
        result.state = ACH_OFFLINE;
        goto done;
    }
    key[length] = 0;
    while (length > 0 && (key[length - 1] == '\r' || key[length - 1] == '\n' ||
                          key[length - 1] == ' ' || key[length - 1] == '\t'))
        key[--length] = 0;
    if (length != 64 || strspn(key, "0123456789abcdef") != 64) {
        result.state = ACH_OFFLINE;
        goto done;
    }
    strncat(request, " ", sizeof(request) - strlen(request) - 1);
    strncat(request, key, sizeof(request) - strlen(request) - 1);
    memset(key, 0, sizeof(key));
    if (raCaduceusPage(request, serial, response, sizeof(response)) != 0 ||
        !achievementsParse(response, &result) ||
        (result.state == ACH_READY && (result.kind != requestKind || result.page != requestPage)))
        result.state = ACH_ERROR;
done:
    imagePath[0] = imageStartup[0] = 0;
    imageIsVcd = 0;
    memset(key, 0, sizeof(key));
    memset(request, 0, sizeof(request));
    __asm__ volatile("" ::
                         : "memory");
    busy = 0;
}
int achievementsBusy(void) { return busy; }
int achievementsRequest(char kind, int page, int filter, const char *target)
{
    if (busy || sbHashGameBusy() || discCheckBusy() || page < 0 || page > 999999 || filter < 0 || filter > 3 ||
        (kind != 'G' && kind != 'A') || !target || !*target || strlen(target) > 32 ||
        strspn(target, "0123456789abcdef") != strlen(target))
        return 0;
    imagePath[0] = 0;
    requestKind = kind;
    requestPage = page;
    requestFilter = filter;
    snprintf(requestTarget, sizeof(requestTarget), "%s", target);
    busy = 1;
    serial++;
    snprintf(request, sizeof(request), "CADA1 %u %c %d %d %s", serial, kind, page, filter, target);
    if (ioPutRequest(IO_CUSTOM_SIMPLEACTION, &loadPage) != IO_OK) {
        busy = 0;
        return 0;
    }
    return 1;
}
static int requestImage(const char *path, const char *startup, int isVcd)
{
    if (busy || sbHashGameBusy() || discCheckBusy() || !path || !*path ||
        (!isVcd && !startup) || strlen(path) >= sizeof(imagePath) ||
        (startup && strlen(startup) >= sizeof(imageStartup)))
        return 0;
    requestKind = 'A';
    requestPage = 0;
    snprintf(imagePath, sizeof(imagePath), "%s", path);
    snprintf(imageStartup, sizeof(imageStartup), "%s", startup ? startup : "");
    imageIsVcd = isVcd;
    busy = 1;
    serial++;
    if (ioPutRequest(IO_CUSTOM_SIMPLEACTION, &loadPage) != IO_OK) {
        busy = 0;
        imagePath[0] = imageStartup[0] = 0;
        imageIsVcd = 0;
        return 0;
    }
    return 1;
}
int achievementsRequestImage(const char *path, const char *startup)
{
    return requestImage(path, startup, 0);
}
int achievementsRequestVcd(const char *path)
{
    return requestImage(path, NULL, 1);
}
void achievementsSnapshot(achievement_page_t *out)
{
    if (!out)
        return;
    memset(out, 0, sizeof(*out));
    if (busy) {
        out->state = ACH_LOADING;
        return;
    }
    __asm__ volatile("" ::
                         : "memory");
    *out = result;
}
#endif
