#include "include/opl.h"
#include "include/lang.h"
#include "include/util.h"
#include "include/fntsys.h"
#include "include/ioman.h"
#include "include/themes.h"
#include "include/sound.h"
#include "include/gui.h" // guiLock/guiUnlock -- serialize the language name-list rebuild
#include <dirent.h>
#include <limits.h>

static int guiLangID = 0;
static char **lang_strs = internalEnglish;
static int nValidEntries = LANG_STR_COUNT;

static int nLanguages = 0;
static int languageCapacity = 0;
static language_t *languages;
static char **guiLangNames;
static char scannedBootDir[sizeof(gBootDir)];
static unsigned char scanPriority; // 2: CWD, 1: CWD/LNG, 0: other LNG locations
// Valid matching filenames, including duplicates.
static int scanFoundFiles;

// localised string getter
char *_l(unsigned int id)
{
    return lang_strs[id];
}

static void lngFreeFromFile(char **lang_strs)
{
    if (guiLangID == 0)
        return;

    int strId = 0;
    for (; strId < nValidEntries; strId++) {
        free(lang_strs[strId]);
        lang_strs[strId] = NULL;
    }
    free(lang_strs);
}

static int lngLoadFont(const char *dir, const char *name)
{
    size_t dirLen = strlen(dir);
    size_t nameLen = strlen(name);
    if (dirLen > (size_t)-1 - nameLen - sizeof("font_.ttf"))
        return -1;
    size_t pathSize = dirLen + nameLen + sizeof("font_.ttf");
    char *path = malloc(pathSize);
    if (path == NULL)
        return -1;

    snprintf(path, pathSize, "%sfont_%s.ttf", dir, name);
    LOG("LANG Custom TTF font path: %s\n", path);
    if (fntLoadDefault(path) == 0) {
        free(path);
        return 0;
    }

    snprintf(path, pathSize, "%sfont_%s.otf", dir, name);
    LOG("LANG Custom OTF font path: %s\n", path);
    if (fntLoadDefault(path) == 0) {
        free(path);
        return 0;
    }

    LOG("LANG cannot load font.\n");
    free(path);
    return -1;
}

// The arguments a printf format reads, one letter each: i int (also a '*' width or precision), l long,
// q long long, j/z/t their types, s string, w wide string, p pointer, f double, D long double.
// h and hh read a promoted int. Returns the count, or -1 for %n, an unknown conversion or overflow.
static int lngFormatArgs(const char *fmt, char *args, int size)
{
    int count = 0;

    while ((fmt = strchr(fmt, '%')) != NULL) {
        char length = 0, arg;

        fmt++;
        if (*fmt == '%') {
            fmt++;
            continue;
        }
        while (*fmt != '\0' && strchr("-+ #0'", *fmt) != NULL)
            fmt++;
        for (int part = 0; part < 2; part++) { // width, then precision
            if (part == 1) {
                if (*fmt != '.')
                    break;
                fmt++;
            }
            if (*fmt == '*') {
                if (count >= size)
                    return -1;
                args[count++] = 'i';
                fmt++;
            }
            while (*fmt >= '0' && *fmt <= '9')
                fmt++;
        }
        if (*fmt == 'h') {
            fmt += (fmt[1] == 'h') ? 2 : 1;
        } else if (*fmt == 'l' && fmt[1] == 'l') {
            length = 'q';
            fmt += 2;
        } else if (*fmt != '\0' && strchr("lqLjzt", *fmt) != NULL) {
            length = *fmt++;
        }

        if (*fmt != '\0' && strchr("diouxXc", *fmt) != NULL)
            arg = (length == 0 || length == 'L' || *fmt == 'c') ? 'i' : length;
        else if (*fmt == 's')
            arg = (length == 'l') ? 'w' : 's';
        else if (*fmt == 'p')
            arg = 'p';
        else if (*fmt != '\0' && strchr("eEfFgGaA", *fmt) != NULL)
            arg = (length == 'L') ? 'D' : 'f';
        else
            return -1;
        if (count >= size)
            return -1;
        args[count++] = arg;
        fmt++;
    }
    return count;
}

// RiptOPL: a translated string gets the arguments its English string is given. A translation whose
// conversions read other types would read an int as a string pointer and crash (an upstream French
// "Auto start" string has %s where English has %i), so it may read the same arguments or fewer of
// them in the same order, never different ones.
static int lngFormatFits(const char *translated, const char *english)
{
    char want[16], got[16];
    int wantCount = lngFormatArgs(english, want, sizeof(want));
    int gotCount = lngFormatArgs(translated, got, sizeof(got));

    if (wantCount < 0)
        return 1; // not a format this check understands: leave the translation alone
    return gotCount >= 0 && gotCount <= wantCount && memcmp(got, want, gotCount) == 0;
}

static int lngLoadFromFile(char *path, char *name)
{
    char *dir;

    file_buffer_t *fileBuffer = openFileBuffer(path, O_RDONLY, 1, 1024);
    if (fileBuffer) {
        // file exists, try to read it and load the custom lang
        char **curL = lang_strs;
        char **newL = (char **)calloc(LANG_STR_COUNT, sizeof(char *));

        int strId = 0;
        while (strId < LANG_STR_COUNT && readFileBuffer(fileBuffer, &newL[strId])) {
            strId++;
        }
        closeFileBuffer(fileBuffer);

        LOG("LANG Loaded %d entries\n", strId);

        for (int i = 0; i < strId; i++) {
            if (newL[i] == NULL || lngFormatFits(newL[i], internalEnglish[i]))
                continue;
            LOG("LANG entry %d does not take the English arguments, using English: %s\n", i, newL[i]);
            char *english = strdup(internalEnglish[i]);
            if (english != NULL) {
                free(newL[i]);
                newL[i] = english;
            } else {
                newL[i][0] = '\0'; // no conversions left to misread
            }
        }

        int newEntries = strId;
        // if necessary complete lang with default internal
        while (strId < LANG_STR_COUNT) {
            LOG("LANG Default entry added: %s\n", internalEnglish[strId]);
            newL[strId] = internalEnglish[strId];
            strId++;
        }
        lang_strs = newL;
        lngFreeFromFile(curL);

        // remember how many entries were read from the file (for the free later)
        nValidEntries = newEntries;

        // "lang_" + language name + ".lng": parent path can exceed 128 bytes.
        size_t dirLen = strlen(path) - strlen(name) - 9;
        dir = malloc(dirLen + 1);
        if (dir != NULL) {
            memcpy(dir, path, dirLen);
            dir[dirLen] = '\0';
            lngLoadFont(dir, name);
            free(dir);
        }

        return 1;
    }
    return 0;
}

char *lngGetValue(void)
{
    return guiLangNames[guiLangID];
}

static int lngEnsureCapacity(int count)
{
    if (count <= languageCapacity)
        return 1;

    int capacity = languageCapacity ? languageCapacity : 32;
    while (capacity < count) {
        if (capacity > INT_MAX / 2) {
            capacity = count;
            break;
        }
        capacity *= 2;
    }
    if ((size_t)capacity > (size_t)-1 / sizeof(*languages))
        return 0;

    language_t *expanded = realloc(languages, (size_t)capacity * sizeof(*languages));
    if (expanded == NULL)
        return 0;
    languages = expanded;
    languageCapacity = capacity;
    return 1;
}

static int lngReadEntry(int index, const char *path, const char *separator, const char *name, unsigned char d_type)
{
    size_t nameLen = strlen(name);
    if (d_type == DT_DIR || nameLen <= 9 || strncasecmp(name, "lang_", 5) != 0 ||
        strcasecmp(name + nameLen - 4, ".lng") != 0 || index >= INT_MAX - nLanguages - 1)
        return index;

    // Device callers use a positive return to stop polling this LNG folder;
    // count valid files even if CWD registered an identically named language.
    scanFoundFiles++;
    size_t langLen = nameLen - 9;
    int existing = -1;
    int count = nLanguages + index;
    for (int i = 0; i < count; i++) {
        if (strlen(languages[i].name) == langLen && strncasecmp(languages[i].name, name + 5, langLen) == 0) {
            existing = i;
            break;
        }
    }
    // First discovered wins unless a higher-priority CWD copy becomes readable
    // later (e.g. once network or BDM modules finish initializing).
    if (existing >= 0 && scanPriority <= languages[existing].sourcePriority)
        return index;

    size_t pathLen = strlen(path);
    size_t sepLen = strlen(separator);
    if (pathLen && (path[pathLen - 1] == '/' || path[pathLen - 1] == '\\' || path[pathLen - 1] == ':'))
        sepLen = 0;
    if (pathLen > (size_t)-1 - sepLen - nameLen - 1)
        return index;

    char *filePath = malloc(pathLen + sepLen + nameLen + 1);
    if (filePath == NULL)
        return index;
    memcpy(filePath, path, pathLen);
    if (sepLen)
        memcpy(filePath + pathLen, separator, sepLen);
    memcpy(filePath + pathLen + sepLen, name, nameLen + 1);

    // The GUI thread reads this registry (lngSetGuiValue, the language notification) while the IO
    // worker adds to it, so the array is grown, filled and a path replaced only under the GUI lock.
    if (existing >= 0) {
        guiLock();
        char *oldPath = languages[existing].filePath;
        languages[existing].filePath = filePath;
        languages[existing].sourcePriority = scanPriority;
        guiUnlock();
        free(oldPath);
        return index;
    }

    char *langName = malloc(langLen + 1);
    if (langName == NULL) {
        free(filePath);
        return index;
    }
    memcpy(langName, name + 5, langLen);
    langName[langLen] = '\0';

    guiLock();
    int added = lngEnsureCapacity(count + 1);
    if (added) {
        languages[count].filePath = filePath;
        languages[count].name = langName;
        languages[count].sourcePriority = scanPriority;
    }
    guiUnlock();
    if (!added) {
        free(filePath);
        free(langName);
        return index;
    }
    return index + 1;
}

static void lngRebuildLangNames(void)
{
    char **newNames = malloc((size_t)(nLanguages + 2) * sizeof(*newNames));
    if (newNames == NULL)
        return;

    newNames[0] = internalEnglish[0];
    for (int i = 0; i < nLanguages; i++)
        newNames[i + 1] = languages[i].name;
    newNames[nLanguages + 1] = NULL;
    free(guiLangNames);
    guiLangNames = newNames;
}

static int lngScanDirectory(char *path, const char *separator, unsigned char priority)
{
    if (path == NULL || path[0] == '\0' || nLanguages >= INT_MAX - 1)
        return 0;

    scanPriority = priority;
    scanFoundFiles = 0;
    int added = listDir(path, separator, INT_MAX - nLanguages - 1, &lngReadEntry);
    int found = scanFoundFiles;
    guiLock();
    nLanguages += added;
    guiUnlock();
    scanPriority = 0;
    return found;
}

static int lngScanBootDirectory(void)
{
    if (gBootDir[0] == '\0' || strcmp(gBootDir, scannedBootDir) == 0)
        return 0;

    // Defer latching a boot path until it is readable. Storage may mount late.
    DIR *dir = opendir(gBootDir);
    if (dir == NULL)
        return 0;
    closedir(dir);

    const char *separator = strchr(gBootDir, '\\') ? "\\" : "/";
    int added = lngScanDirectory(gBootDir, separator, 2);

    char path[sizeof(gBootDir) + sizeof("/LNG")];
    size_t len = strlen(gBootDir);
    const char *join = separator;
    if (gBootDir[len - 1] == '/' || gBootDir[len - 1] == '\\' || gBootDir[len - 1] == ':')
        join = "";
    int written = snprintf(path, sizeof(path), "%s%sLNG", gBootDir, join);
    int lngReadable = 0;
    if (written >= 0 && (size_t)written < sizeof(path)) {
        // A boot device may expose its root before the LNG subfolder is ready.
        DIR *lngDir = opendir(path);
        if (lngDir != NULL) {
            closedir(lngDir);
            added += lngScanDirectory(path, separator, 1);
            lngReadable = 1;
        }
    }

    if (lngReadable)
        snprintf(scannedBootDir, sizeof(scannedBootDir), "%s", gBootDir);
    return added;
}

static void lngPublishLanguages(int mode)
{
    guiLock();
    lngRebuildLangNames();
    guiUnlock();

    const char *saved;
    if (configGetStr(configGetByType(CONFIG_OPL), "language_text", &saved)) {
        if (lngSetGuiValue(lngFindGuiID(saved)))
            moduleUpdateMenu(mode, 0, 1);
    }
}

void lngRefreshBootLanguages(int mode)
{
    if (lngScanBootDirectory() > 0)
        lngPublishLanguages(mode);
}

int lngAddLanguages(char *path, const char *separator, int mode)
{
    // Retry CWD before scanning each newly mounted device's conventional LNG.
    (void)lngScanBootDirectory();
    int found = lngScanDirectory(path, separator, 0);
    lngPublishLanguages(mode);
    return found;
}

// An optional CJK font belongs to the settings home, NOT the selected UI
// language. The English UI must still be able to show Japanese game filenames.
// Do not bundle a large unlicensed font in the ELF or open it during rendering.
void lngInitFallbackFont(void)
{
    static const char *const fontNames[] = {"font_CJK.ttf", "font_CJK.otf", "font_Japanese.ttf", "font_Japanese.otf"};
    const char *home = configGetHomePath();
    if (home == NULL || home[0] == '\0')
        return;

    const size_t len = strlen(home);
    const char *sep = (home[len - 1] == '/' || home[len - 1] == ':') ? "" : "/";
    for (unsigned int i = 0; i < sizeof(fontNames) / sizeof(fontNames[0]); i++) {
        char path[256];
        int length = snprintf(path, sizeof(path), "%s%s%s", home, sep, fontNames[i]);
        if (length <= 0 || length >= (int)sizeof(path))
            continue;
        if (fntLoadFallback(path) == 0)
            return;
    }
}

void lngInit(void)
{
    fntInit();

    lngAddLanguages(gBaseMCDir, "/", -1);
}

void lngEnd(void)
{
    lngFreeFromFile(lang_strs);

    int i = 0;
    for (; i < nLanguages; i++) {
        free(languages[i].name);
        free(languages[i].filePath);
    }

    free(guiLangNames);
    free(languages);
    languages = NULL;
    languageCapacity = nLanguages = 0;

    fntEnd();
}

int lngSetGuiValue(int langID)
{
    if (langID >= 0 && langID <= nLanguages) {
        if (guiLangID != langID) {
            bgmMute();
            if (langID != 0) {
                // The IO worker may grow the registry or replace this path meanwhile (lngReadEntry):
                // copy the path under the GUI lock. A language's name is never moved or freed.
                char *path = NULL, *name = NULL;
                guiLock();
                path = strdup(languages[langID - 1].filePath);
                name = languages[langID - 1].name;
                guiUnlock();
                int loaded = path != NULL && lngLoadFromFile(path, name);
                free(path);
                if (loaded) {
                    guiLangID = langID;
                    thmSetGuiValue(thmGetGuiValue(), 1);
                    bgmUnMute();
                    return 1;
                }
            }
            /* Free the previously-loaded foreign lang_strs before switching to
               internalEnglish. guiLangID is still non-zero here so lngFreeFromFile's
               guard correctly allows the free; nValidEntries still holds the old
               file-entry count so the per-entry loop is correctly bounded. */
            lngFreeFromFile(lang_strs);
            lang_strs = internalEnglish;
            guiLangID = 0;
            nValidEntries = LANG_STR_COUNT;
            // lang switched back to internalEnglish, reload default font
            fntLoadDefault(NULL);
            thmSetGuiValue(thmGetGuiValue(), 1);
            bgmUnMute();
            return 1;
        }
    }
    return 0;
}

int lngGetGuiValue(void)
{
    return guiLangID;
}

int lngFindGuiID(const char *lang)
{
    if (lang) {
        int i = 0;
        for (; i < nLanguages; i++) {
            if (strcasecmp(languages[i].name, lang) == 0)
                return i + 1; // shift for Gui id
        }
    }
    return 0;
}

char **lngGetGuiList(void)
{
    return guiLangNames;
}

char *lngGetFilePath(int langID)
{
    language_t *currLang = &languages[langID - 1];
    char *path = currLang->filePath;

    return path;
}
