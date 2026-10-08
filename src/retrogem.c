/*
  Copyright 2026, Open-PS2-Loader contributors
  Licenced under Academic Free License version 3.0
  Review OpenUsbLd README & LICENSE files for further details.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <fcntl.h>
#include <unistd.h>

#include "include/opl.h"
#include "include/gui.h"
#include "include/renderman.h"
#include "include/vcdsupport.h"
#include "include/retrogem.h"

// PS1 GameID resolver used by both POPSTARTER VCD and Ember image launches.
//
// CosmicScale supplied his PSBBN Definitive Project title-ID extractor directly for this work and
// granted permission to use/adapt its GameID extraction logic. Keep the console implementation on
// that standard path: read ISO9660, find SYSTEM.CNF, parse BOOT/BOOT2, and normalize the executable
// serial. CUE sheets are followed to their data-track image first.
//
// POPStarter VCD needs one format-specific adjustment before applying the same extraction: the disc
// image begins after its 1 MiB VCD header. Ember BIN images begin at sector 0.
#define PS1_SECTOR_DATA_SIZE     2048
#define PS1_RAW_SECTOR_SIZE      2352
#define PS1_VCD_IMAGE_OFFSET     0x100000L
#define PS1_PVD_LBA              16
#define PS1_PVD_SEARCH_SECTORS   16
#define PS1_ROOT_RECORD_OFFSET   156
#define PS1_MAX_ROOT_DIR_SECTORS 64
#define PS1_SYSTEM_CNF_MAX       4096

typedef enum {
    PS1_IMAGE_COOKED_2048 = 0,
    PS1_IMAGE_RAW_2352
} ps1_image_layout_t;

typedef struct
{
    FILE *file;
    long baseOffset;
    ps1_image_layout_t layout;
} ps1_image_reader_t;

static unsigned int retrogemReadLe32(const unsigned char *p)
{
    return (unsigned int)p[0] |
           ((unsigned int)p[1] << 8) |
           ((unsigned int)p[2] << 16) |
           ((unsigned int)p[3] << 24);
}

static int retrogemTitlePrefixChar(char c)
{
    return isalnum((unsigned char)c);
}

// Accept only real PS1 serial shapes. A human game/folder name is NOT a GameID fallback.
static int retrogemCleanTitleID(const char *raw, char *out, size_t maxLen)
{
    const char *p = raw;
    size_t len;
    int i;

    if (raw == NULL || out == NULL || maxLen < RETROGEM_GAMEID_MAX)
        return 0;
    out[0] = '\0';

    if (!strncasecmp(p, "cdrom0:", 7))
        p += 7;
    else if (!strncasecmp(p, "cdrom:", 6))
        p += 6;

    while (*p == '/' || *p == '\\' || *p == ' ' || *p == '\t')
        p++;

    if (!strncasecmp(p, "XX.", 3) || !strncasecmp(p, "SB.", 3) ||
        !strncasecmp(p, "EL.", 3) || !strncasecmp(p, "SM.", 3) ||
        !strncasecmp(p, "PP.", 3) || !strncmp(p, "__.", 3))
        p += 3;

    // All accepted serial spellings need at least ten characters. Guard before indexed reads so
    // a malformed short BOOT token or path component cannot make this metadata parser read beyond
    // its terminating NUL.
    len = strlen(p);
    if (len < 10)
        return 0;

    for (i = 0; i < 4; i++) {
        if (!retrogemTitlePrefixChar(p[i]))
            return 0;
    }

    if (len >= 11 && p[4] == '_' &&
        isdigit((unsigned char)p[5]) && isdigit((unsigned char)p[6]) && isdigit((unsigned char)p[7]) &&
        p[8] == '.' && isdigit((unsigned char)p[9]) && isdigit((unsigned char)p[10])) {
        for (i = 0; i < 11; i++)
            out[i] = (char)toupper((unsigned char)p[i]);
        out[11] = '\0';
        return 1;
    }

    // Alternate archive/partition spelling: SLUS-12345 -> canonical SLUS_123.45.
    if (p[4] == '-' &&
        isdigit((unsigned char)p[5]) && isdigit((unsigned char)p[6]) && isdigit((unsigned char)p[7]) &&
        isdigit((unsigned char)p[8]) && isdigit((unsigned char)p[9])) {
        snprintf(out, maxLen, "%c%c%c%c_%c%c%c.%c%c",
                 toupper((unsigned char)p[0]), toupper((unsigned char)p[1]),
                 toupper((unsigned char)p[2]), toupper((unsigned char)p[3]),
                 p[5], p[6], p[7], p[8], p[9]);
        return 1;
    }

    return 0;
}

static int retrogemReadSector(ps1_image_reader_t *reader, unsigned int lba, unsigned char *data)
{
    unsigned char raw[PS1_RAW_SECTOR_SIZE];
    long sectorSize;
    long offset;
    int dataOffset;

    if (reader == NULL || reader->file == NULL || data == NULL)
        return 0;

    sectorSize = (reader->layout == PS1_IMAGE_RAW_2352) ? PS1_RAW_SECTOR_SIZE : PS1_SECTOR_DATA_SIZE;
    offset = reader->baseOffset + (long)lba * sectorSize;
    if (fseek(reader->file, offset, SEEK_SET) != 0)
        return 0;

    if (reader->layout == PS1_IMAGE_COOKED_2048)
        return fread(data, 1, PS1_SECTOR_DATA_SIZE, reader->file) == PS1_SECTOR_DATA_SIZE;

    if (fread(raw, 1, sizeof(raw), reader->file) != sizeof(raw))
        return 0;

    if (raw[15] == 1) {
        dataOffset = 16;
    } else if (raw[15] == 2) {
        // Mode 2 Form 2 carries 2324 bytes and cannot contain ISO9660 metadata sectors.
        if (raw[18] & 0x20)
            return 0;
        dataOffset = 24;
    } else {
        return 0;
    }

    memcpy(data, raw + dataOffset, PS1_SECTOR_DATA_SIZE);
    return 1;
}

static int retrogemFindPvd(ps1_image_reader_t *reader, unsigned char *pvd)
{
    unsigned char sector[PS1_SECTOR_DATA_SIZE];
    int i;

    for (i = 0; i < PS1_PVD_SEARCH_SECTORS; i++) {
        if (!retrogemReadSector(reader, PS1_PVD_LBA + i, sector))
            return 0;
        if (memcmp(sector + 1, "CD001", 5) != 0)
            continue;
        if (sector[0] == 1) {
            memcpy(pvd, sector, sizeof(sector));
            return 1;
        }
        if (sector[0] == 255)
            return 0;
    }

    return 0;
}

static int retrogemIsoNameMatches(const unsigned char *name, int nameLen, const char *target)
{
    int targetLen;
    int i;

    if (name == NULL || target == NULL || nameLen <= 0)
        return 0;
    targetLen = (int)strlen(target);
    if (nameLen < targetLen)
        return 0;

    for (i = 0; i < targetLen; i++) {
        if (tolower((unsigned char)name[i]) != tolower((unsigned char)target[i]))
            return 0;
    }

    return nameLen == targetLen || name[targetLen] == ';';
}

static int retrogemReadIsoFile(ps1_image_reader_t *reader, unsigned int lba, unsigned int fileSize,
                               char *buffer, size_t bufferSize)
{
    unsigned char sector[PS1_SECTOR_DATA_SIZE];
    size_t copied = 0;
    unsigned int sectorIndex = 0;

    if (buffer == NULL || bufferSize < 2 || fileSize == 0)
        return 0;

    while (copied < fileSize && copied < bufferSize - 1) {
        size_t remainingFile;
        size_t remainingBuffer;
        size_t copyLen;

        if (!retrogemReadSector(reader, lba + sectorIndex, sector))
            break;

        remainingFile = fileSize - copied;
        remainingBuffer = bufferSize - 1 - copied;
        copyLen = remainingFile < PS1_SECTOR_DATA_SIZE ? remainingFile : PS1_SECTOR_DATA_SIZE;
        if (copyLen > remainingBuffer)
            copyLen = remainingBuffer;

        memcpy(buffer + copied, sector, copyLen);
        copied += copyLen;
        sectorIndex++;
    }

    buffer[copied] = '\0';
    return copied > 0;
}

static int retrogemParseSystemCnf(const char *cnf, char *gameID, size_t maxLen)
{
    const char *line = cnf;

    while (line != NULL && *line != '\0') {
        const char *lineEnd = line;
        const char *p;
        const char *eq;
        char bootPath[128];
        size_t n;

        while (*lineEnd != '\0' && *lineEnd != '\r' && *lineEnd != '\n')
            lineEnd++;

        p = line;
        while (p < lineEnd && (*p == ' ' || *p == '\t'))
            p++;

        if ((lineEnd - p >= 4 && !strncasecmp(p, "BOOT", 4))) {
            eq = p;
            while (eq < lineEnd && *eq != '=')
                eq++;
            if (eq < lineEnd) {
                eq++;
                while (eq < lineEnd && (*eq == ' ' || *eq == '\t'))
                    eq++;
                n = 0;
                while (eq + n < lineEnd && eq[n] != ' ' && eq[n] != '\t' && n < sizeof(bootPath) - 1)
                    n++;
                if (n > 0) {
                    memcpy(bootPath, eq, n);
                    bootPath[n] = '\0';
                    if (retrogemCleanTitleID(bootPath, gameID, maxLen))
                        return 1;
                }
            }
        }

        line = lineEnd;
        while (*line == '\r' || *line == '\n')
            line++;
    }

    return 0;
}

static int retrogemParseReader(ps1_image_reader_t *reader, char *gameID, size_t maxLen)
{
    unsigned char pvd[PS1_SECTOR_DATA_SIZE];
    const unsigned char *rootRecord;
    unsigned int rootLba;
    unsigned int rootSize;
    unsigned int rootSectors;
    unsigned int sectorIndex;

    if (!retrogemFindPvd(reader, pvd))
        return 0;

    rootRecord = pvd + PS1_ROOT_RECORD_OFFSET;
    if (rootRecord[0] >= 34) {
        rootLba = retrogemReadLe32(rootRecord + 2);
        rootSize = retrogemReadLe32(rootRecord + 10);
        rootSectors = (rootSize + PS1_SECTOR_DATA_SIZE - 1) / PS1_SECTOR_DATA_SIZE;
        if (rootSectors > PS1_MAX_ROOT_DIR_SECTORS)
            rootSectors = PS1_MAX_ROOT_DIR_SECTORS;

        for (sectorIndex = 0; sectorIndex < rootSectors; sectorIndex++) {
            unsigned char sector[PS1_SECTOR_DATA_SIZE];
            int pos = 0;

            if (!retrogemReadSector(reader, rootLba + sectorIndex, sector))
                break;

            while (pos < PS1_SECTOR_DATA_SIZE) {
                int recordLen = sector[pos];
                int nameLen;
                int flags;

                if (recordLen == 0)
                    break;
                if (recordLen < 34 || pos + recordLen > PS1_SECTOR_DATA_SIZE)
                    break;

                flags = sector[pos + 25];
                nameLen = sector[pos + 32];
                if (!(flags & 0x02) && recordLen >= 33 + nameLen &&
                    retrogemIsoNameMatches(sector + pos + 33, nameLen, "SYSTEM.CNF")) {
                    unsigned int fileLba = retrogemReadLe32(sector + pos + 2);
                    unsigned int fileSize = retrogemReadLe32(sector + pos + 10);
                    char cnf[PS1_SYSTEM_CNF_MAX + 1];

                    if (fileSize > 0 && retrogemReadIsoFile(reader, fileLba, fileSize, cnf, sizeof(cnf)) &&
                        retrogemParseSystemCnf(cnf, gameID, maxLen))
                        return 1;
                }

                pos += recordLen;
            }
        }
    }

    return 0;
}

static int retrogemTryImageLayout(const char *path, long baseOffset, ps1_image_layout_t layout,
                                  char *gameID, size_t maxLen)
{
    ps1_image_reader_t reader;
    FILE *file;
    int result;

    file = fopen(path, "rb");
    if (file == NULL)
        return 0;

    reader.file = file;
    reader.baseOffset = baseOffset;
    reader.layout = layout;
    result = retrogemParseReader(&reader, gameID, maxLen);
    fclose(file);
    return result;
}

static int retrogemHasExt(const char *path, const char *ext)
{
    size_t pathLen;
    size_t extLen;

    if (path == NULL || ext == NULL)
        return 0;
    pathLen = strlen(path);
    extLen = strlen(ext);
    return pathLen >= extLen && !strcasecmp(path + pathLen - extLen, ext);
}

static int retrogemContainsNoCase(const char *haystack, const char *needle)
{
    size_t nlen;

    if (haystack == NULL || needle == NULL)
        return 0;
    nlen = strlen(needle);
    if (nlen == 0)
        return 1;

    while (*haystack != '\0') {
        if (!strncasecmp(haystack, needle, nlen))
            return 1;
        haystack++;
    }
    return 0;
}

static int retrogemCueFileToken(const char *line, char *out, size_t outSize)
{
    const char *p = line;
    const char *end;
    size_t len;

    if (line == NULL || out == NULL || outSize == 0)
        return 0;
    out[0] = '\0';

    while (*p == ' ' || *p == '\t')
        p++;
    if (strncasecmp(p, "FILE", 4) || (p[4] != ' ' && p[4] != '\t'))
        return 0;
    p += 4;
    while (*p == ' ' || *p == '\t')
        p++;

    if (*p == '"') {
        p++;
        end = strchr(p, '"');
        if (end == NULL)
            return 0;
    } else {
        end = p;
        while (*end != '\0' && *end != '\r' && *end != '\n' && *end != ' ' && *end != '\t')
            end++;
    }

    len = (size_t)(end - p);
    if (len == 0 || len >= outSize)
        return 0;
    memcpy(out, p, len);
    out[len] = '\0';
    return 1;
}

static int retrogemCueResolveDataFile(const char *cuePath, char *out, size_t outSize)
{
    FILE *cue;
    char line[512];
    char current[256] = "";
    char first[256] = "";
    char selected[256] = "";
    const char *lastSep;
    size_t dirLen;
    char sep = '/';
    size_t i;

    if (cuePath == NULL || out == NULL || outSize == 0)
        return 0;
    out[0] = '\0';

    cue = fopen(cuePath, "rb");
    if (cue == NULL)
        return 0;

    while (fgets(line, sizeof(line), cue) != NULL) {
        char token[256];
        const char *p = line;

        if (retrogemCueFileToken(line, token, sizeof(token))) {
            snprintf(current, sizeof(current), "%s", token);
            if (first[0] == '\0')
                snprintf(first, sizeof(first), "%s", token);
            continue;
        }

        while (*p == ' ' || *p == '\t')
            p++;
        if (!strncasecmp(p, "TRACK", 5) &&
            (retrogemContainsNoCase(p, "MODE1/") || retrogemContainsNoCase(p, "MODE2/")) &&
            current[0] != '\0') {
            snprintf(selected, sizeof(selected), "%s", current);
            break;
        }
    }
    fclose(cue);

    if (selected[0] == '\0')
        snprintf(selected, sizeof(selected), "%s", first);
    if (selected[0] == '\0')
        return 0;

    // Absolute/device-qualified FILE tokens are already complete.
    if (strchr(selected, ':') != NULL) {
        snprintf(out, outSize, "%s", selected);
        return out[0] != '\0';
    }

    lastSep = strrchr(cuePath, '/');
    {
        const char *back = strrchr(cuePath, '\\');
        if (back != NULL && (lastSep == NULL || back > lastSep))
            lastSep = back;
    }
    if (lastSep == NULL)
        return snprintf(out, outSize, "%s", selected) > 0;

    dirLen = (size_t)(lastSep - cuePath + 1);
    if (dirLen >= outSize)
        return 0;
    memcpy(out, cuePath, dirLen);
    out[dirLen] = '\0';
    sep = *lastSep;

    // CUE sheets commonly contain Windows separators even when the PS2 filesystem uses '/'.
    for (i = 0; selected[i] != '\0' && dirLen + i + 1 < outSize; i++) {
        char c = selected[i];
        if (c == '/' || c == '\\')
            c = sep;
        out[dirLen + i] = c;
    }
    if (selected[i] != '\0')
        return 0;
    out[dirLen + i] = '\0';
    return 1;
}

static int retrogemGetDiscImageGameID(const char *path, int isVcd, char *gameID, size_t maxLen)
{
    if (isVcd && retrogemTryImageLayout(path, PS1_VCD_IMAGE_OFFSET, PS1_IMAGE_RAW_2352, gameID, maxLen))
        return 1;

    // Raw BIN is the normal PS1 image layout. Cooked 2048-byte images are accepted as a useful
    // compatibility fallback for converted/homebrew images.
    if (retrogemTryImageLayout(path, 0, PS1_IMAGE_RAW_2352, gameID, maxLen))
        return 1;
    if (retrogemTryImageLayout(path, 0, PS1_IMAGE_COOKED_2048, gameID, maxLen))
        return 1;

    return 0;
}

int retrogemGetVcdGameID(const char *vcdPath, char *gameID, size_t maxLen)
{
    if (vcdPath == NULL || gameID == NULL || maxLen < RETROGEM_GAMEID_MAX)
        return 0;
    gameID[0] = '\0';
    return retrogemGetDiscImageGameID(vcdPath, 1, gameID, maxLen);
}

int retrogemGetPs1ImageGameID(const char *imagePath, char *gameID, size_t maxLen)
{
    char dataPath[512];

    if (imagePath == NULL || gameID == NULL || maxLen < RETROGEM_GAMEID_MAX)
        return 0;
    gameID[0] = '\0';

    if (retrogemHasExt(imagePath, ".VCD"))
        return retrogemGetVcdGameID(imagePath, gameID, maxLen);

    if (retrogemHasExt(imagePath, ".CUE")) {
        if (retrogemCueResolveDataFile(imagePath, dataPath, sizeof(dataPath)))
            return retrogemGetDiscImageGameID(dataPath, 0, gameID, maxLen);
        return 0;
    }

    if (retrogemHasExt(imagePath, ".BIN") || retrogemHasExt(imagePath, ".ISO"))
        return retrogemGetDiscImageGameID(imagePath, 0, gameID, maxLen);

    // A bare PS-X EXE has no disc filesystem to extract a serial from. Do not invent a GameID from
    // its filename or Ember folder name.
    return 0;
}

static u8 retrogemCalculateCRC(const u8 *data, int len)
{
    int i;
    u8 sum = 0;
    for (i = 0; i < len; i++)
        sum = (u8)(sum + data[i]);
    return (u8)(0x100 - sum);
}

void displayRetroGemGameID(const char *gameID, int frames)
{
    u8 data[64];
    int gidlen, dpos, data_len, xstart, ystart, height;
    int i, j, frame;
    int screenWidth, screenHeight;

    if (gameID == NULL || gameID[0] == '\0')
        return;

    gidlen = (int)strlen(gameID);
    if (gidlen > 11)
        gidlen = 11;
    if (gidlen <= 0)
        return;

    if (frames < 1)
        frames = 1;

    memset(data, 0, sizeof(data));
    dpos = 0;
    data[dpos++] = 0xA5;       // Header
    data[dpos++] = 0x00;       // Address offset
    dpos++;                    // Checksum placeholder (data[2])
    data[dpos++] = (u8)gidlen; // Length byte
    for (i = 0; i < gidlen; i++)
        data[dpos++] = (u8)gameID[i];
    data[dpos++] = 0x00; // Padding
    data[dpos++] = 0xD5; // Footer end word
    data[dpos++] = 0x00; // Padding

    data_len = dpos;
    data[2] = retrogemCalculateCRC(&data[3], data_len - 3);

    rmGetScreenExtents(&screenWidth, &screenHeight);
    xstart = (screenWidth / 2) - (data_len * 8);
    ystart = screenHeight - (((screenHeight / 8) * 2) + 20);
    height = 2;

    for (frame = 0; frame < frames; frame++) {
        rmStartFrame();
        rmDrawRect(0, 0, screenWidth, screenHeight, GS_SETREG_RGBA(0x00, 0x00, 0x00, 0x80));

        for (i = 0; i < data_len; i++) {
            for (j = 7; j >= 0; j--) {
                int x = xstart + (i * 16 + (7 - j) * 2);
                // Clock pixel: Magenta (#FF00FF)
                rmDrawRect(x, ystart, 1, height, GS_SETREG_RGBA(0xFF, 0x00, 0xFF, 0x80));
                // Data bit pixel: Cyan (#00FFFF) for 1, Yellow (#FFFF00) for 0
                u64 bit_color = ((data[i] >> j) & 1) ? GS_SETREG_RGBA(0x00, 0xFF, 0xFF, 0x80) : GS_SETREG_RGBA(0xFF, 0xFF, 0x00, 0x80);
                rmDrawRect(x + 1, ystart, 1, height, bit_color);
            }
        }
        rmEndFrame();
    }

    // 1 clean black frame to ensure graphics buffer is clear before handoff
    rmStartFrame();
    rmDrawRect(0, 0, screenWidth, screenHeight, GS_SETREG_RGBA(0x00, 0x00, 0x00, 0x80));
    rmEndFrame();
}
