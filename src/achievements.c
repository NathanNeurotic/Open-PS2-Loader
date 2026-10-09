/* Adapted from Rian6/caduceus-opl 2a98a9d, AFL-3.0. */
#ifdef RETROACHIEVEMENTS
#include "include/opl.h"
#include "include/achievements.h"
#include "include/ranet.h"
#include "include/ioman.h"
#include "include/supportbase.h"
#include "include/ethsupport.h"
#include "include/discsupport.h"
#include "include/rahash.h"
static volatile int busy;
static achievement_page_t result;
static char request[180];
static unsigned int serial;
static char requestKind;
static int requestPage;
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
static void loadPage(void)
{
    static char response[1024];
    memset(&result, 0, sizeof(result));
    result.state = ACH_ERROR;
    char key[68], keyPath[256], hash[33];
    int fd, length;
    if (raNetNicBusy() || !ethEnsureSMBShareConnected()) {
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
    snprintf(keyPath, sizeof(keyPath), "%sART/CADUCEUS.KEY", ethGetSMBPrefix());
    fd = open(keyPath, O_RDONLY);
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
