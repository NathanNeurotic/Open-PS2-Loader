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

// Full PS1 GameID resolver used by both POPSTARTER VCD and Ember image launches.
//
// The VCD reader is intentionally format-aware. POPStarter .VCD files carry a 1 MiB header and
// then raw 2352-byte CD sectors; treating them like a plain ISO (the old implementation did) means
// SYSTEM.CNF usually cannot be reached and the fallback silently becomes the filename. Ember's
// .BIN images are raw 2352-byte sectors without the VCD header. CUE files are resolved to the data
// track's FILE entry before reading the image.
//
// PVD timestamp mappings cover PS1 discs whose SYSTEM.CNF is absent or boots a generic target such
// as PSX.EXE. The table is derived from OSDMenu's AFL-3.0 game_id_table.h, also used by
// r3LaunchELF_ATTDASH.
#define PS1_SECTOR_DATA_SIZE         2048
#define PS1_RAW_SECTOR_SIZE          2352
#define PS1_VCD_IMAGE_OFFSET         0x100000L
#define PS1_PVD_LBA                  16
#define PS1_PVD_SEARCH_SECTORS       16
#define PS1_ROOT_RECORD_OFFSET       156
#define PS1_MAX_ROOT_DIR_SECTORS     64
#define PS1_PVD_TIMESTAMP_OFFSET     0x32D
#define PS1_PVD_TIMESTAMP_LEN        16
#define PS1_SYSTEM_CNF_MAX           4096

typedef struct
{
    const char timestamp[17];
    const char game_id[12];
} ps1_generic_game_id_t;

static const ps1_generic_game_id_t ps1_generic_game_ids[] = {
    {"1994111009000000", "SLPS_000.01"},
    {"1994110702000000", "SLPS_000.02"},
    {"1994102615231700", "SLPS_000.03"},
    {"1994110218594700", "SLPS_000.04"},
    {"1995030218052000", "SLPS_000.04"},
    {"1994110722360400", "SLPS_000.05"},
    {"1994120610494900", "SLPS_000.05"},
    {"1994110407000000", "SLPS_000.06"},
    {"1994111419300000", "SLPS_000.07"},
    {"1994121808190700", "SLPS_000.08"},
    {"1994121917000000", "SLPS_000.09"},
    {"1995052918000000", "SLPS_000.10"},
    {"1994110220020600", "SLPS_000.11"},
    {"1994121518000000", "SLPS_000.13"},
    {"1994103000000000", "SLPS_000.14"},
    {"1994101813262400", "SLPS_000.15"},
    {"1994112617300000", "SLPS_000.16"},
    {"1994121517300000", "SLPS_000.16"},
    {"1994111013000000", "SLPS_000.17"},
    {"1994111522183200", "SLPS_000.18"},
    {"1994112918000000", "SLPS_000.19"},
    {"1994111721302100", "SLPS_000.20"},
    {"1994100617242100", "SLPS_000.21"},
    {"1995030215000000", "SLPS_000.22"},
    {"1994122718351900", "SLPS_000.23"},
    {"1994092920284600", "SLPS_000.24"},
    {"1994113012000000", "SLPS_000.25"},
    {"1995012512000000", "SLPS_000.25"},
    {"1995041921063500", "SLPS_000.26"},
    {"1994121500000000", "SLPS_000.27"},
    {"1994121017582300", "SLPS_000.28"},
    {"1995022623000000", "SLPS_000.29"},
    {"1995050116000000", "SLPS_000.30"},
    {"1995060613000000", "SLPS_000.30"},
    {"1995021802000000", "SLPS_000.31"},
    {"1995021615022900", "SLPS_000.32"},
    {"1995080809000000", "SLPS_000.33"},
    {"1995100209000000", "SLPS_000.33"},
    {"1995071821394900", "SLPS_000.34"},
    {"1995042506300000", "SLPS_000.35"},
    {"1995011411551700", "SLPS_000.37"},
    {"1995041311392800", "SLPS_000.38"},
    {"1995031205000000", "SLPS_000.40"},
    {"1995061612000000", "SLPS_000.40"},
    {"1995040509000000", "SLPS_000.41"},
    {"1995052612000000", "SLPS_000.43"},
    {"1995042500000000", "SLPS_000.44"},
    {"1995033100003000", "SLPS_000.47"},
    {"1995041400000000", "SLPS_000.48"},
    {"1995050413421800", "SLPS_000.50"},
    {"1995040509595900", "SLPS_000.51"},
    {"1995030103150000", "SLPS_000.52"},
    {"1995100409235300", "SLPS_000.53"},
    {"1995060504013600", "SLPS_000.55"},
    {"1995060319142200", "SLPS_000.55"},
    {"1995060402110800", "SLPS_000.55"},
    {"1995081612000000", "SLPS_000.59"},
    {"1995051201000000", "SLPS_000.60"},
    {"1995051700000000", "SLPS_000.61"},
    {"1995051002471900", "SLPS_000.63"},
    {"1995083112000000", "SLPS_000.65"},
    {"1995111700000000", "SLPS_000.65"},
    {"1996033100000000", "SLPS_000.65"},
    {"1995051816000000", "SLPS_000.66"},
    {"1995061418000000", "SLPS_000.67"},
    {"1995061911303400", "SLPS_000.68"},
    {"1995072800300000", "SLPS_000.68"},
    {"1995061207000000", "SLPS_000.69"},
    {"1995062922000000", "SLPS_000.70"},
    {"1995040719355400", "SLPS_000.71"},
    {"1995061806364400", "SLPS_000.73"},
    {"1995051015300000", "SLPS_000.77"},
    {"1995070302000000", "SLPS_000.78"},
    {"1995070523450000", "SLPS_000.83"},
    {"1995072522004900", "SLPS_000.85"},
    {"1995070613170000", "SLPS_000.88"},
    {"1995082517551900", "SLPS_000.89"},
    {"1995082109402500", "SLPS_000.90"},
    {"1995053117000000", "SLPS_000.91"},
    {"1995081100000000", "SLPS_000.92"},
    {"1995071011035200", "SLPS_000.93"},
    {"1995090510000000", "SLPS_000.94"},
    {"1995083123000000", "SLPS_000.94"},
    {"1995100601300000", "SLPS_000.99"},
    {"1995081001450000", "SLPS_001.01"},
    {"1995080316000000", "SLPS_001.03"},
    {"1995081020000000", "SLPS_001.04"},
    {"1995090722000000", "SLPS_001.08"},
    {"1995090516062841", "SLPS_001.13"},
    {"1995082016003000", "SLPS_001.28"},
    {"1995102101350000", "SLPS_001.33"},
    {"1995102102521200", "SLPS_001.33"},
    {"1995102105003200", "SLPS_001.33"},
    {"1995100910002200", "SLPS_001.37"},
    {"1995101801325900", "SLPS_001.42"},
    {"1995113010450000", "SLPS_001.46"},
    {"1995092205430500", "SLPS_001.52"},
    {"1995121620000000", "SLPS_001.73"},
    {"1995122811000000", "SLPS_001.90"},
    {"1995111622323000", "SLPS_002.01"},
    {"1995121418400300", "SLPS_002.30"},
    {"1996010800000000", "SLPS_002.61"},
    {"1996022700000000", "SLPS_003.21"},
    {"1996020413401600", "SLPS_003.36"},
    {"1996030619500500", "SLPS_003.37"},
    {"1996072211000000", "SLPS_005.49"},
    {"1997011500000000", "SLPS_007.19"},
    {"1997031012200700", "SLPS_008.78"},
    {"1997050817540700", "SLPS_008.95"},
    {"1998061000000000", "SLPS_013.34"},
    {"1998040820350000", "SLPS_015.58"},
    {"1994112112000000", "SCPS_100.01"},
    {"1995011010000000", "SCPS_100.01"},
    {"1995030717020700", "SCPS_100.02"},
    {"1994103110000000", "SCPS_100.03"},
    {"1995022100000000", "SCPS_100.04"},
    {"1995032500000000", "SCPS_100.06"},
    {"1995032400000000", "SCPS_100.07"},
    {"1995052420065100", "SCPS_100.08"},
    {"1995061723590000", "SCPS_100.09"},
    {"1995080914422700", "SCPS_100.10"},
    {"1995071219364500", "SCPS_100.12"},
    {"1995092719000000", "SCPS_100.14"},
    {"1995103122331500", "SCPS_100.16"},
};

typedef enum
{
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

    for (i = 0; i < 4; i++) {
        if (!retrogemTitlePrefixChar(p[i]))
            return 0;
    }

    if (p[4] == '_' &&
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

static int retrogemLookupTimestamp(const unsigned char *pvd, char *gameID, size_t maxLen)
{
    char timestamp[PS1_PVD_TIMESTAMP_LEN + 1];
    size_t i;

    memcpy(timestamp, pvd + PS1_PVD_TIMESTAMP_OFFSET, PS1_PVD_TIMESTAMP_LEN);
    timestamp[PS1_PVD_TIMESTAMP_LEN] = '\0';

    for (i = 0; i < sizeof(ps1_generic_game_ids) / sizeof(ps1_generic_game_ids[0]); i++) {
        if (!strncmp(timestamp, ps1_generic_game_ids[i].timestamp, PS1_PVD_TIMESTAMP_LEN)) {
            snprintf(gameID, maxLen, "%s", ps1_generic_game_ids[i].game_id);
            return 1;
        }
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

    return retrogemLookupTimestamp(pvd, gameID, maxLen);
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

static const char *retrogemFinalName(const char *path)
{
    const char *name = path;
    const char *p;

    if (path == NULL)
        return NULL;
    p = strrchr(path, '/');
    if (p != NULL)
        name = p + 1;
    p = strrchr(path, '\\');
    if (p != NULL && p + 1 > name)
        name = p + 1;
    p = strrchr(path, ':');
    if (p != NULL && p + 1 > name)
        name = p + 1;
    return name;
}

static int retrogemPathFallback(const char *path, char *gameID, size_t maxLen)
{
    const char *p;
    const char *name;

    if (path == NULL)
        return 0;

    // POPStarter HDD partition labels can carry the serial even when IMAGE0.VCD cannot be read.
    for (p = path; *p != '\0'; p++) {
        if ((!strncasecmp(p, "PP.", 3) || !strncmp(p, "__.", 3)) &&
            retrogemCleanTitleID(p, gameID, maxLen))
            return 1;
    }

    name = retrogemFinalName(path);
    if (name != NULL && retrogemCleanTitleID(name, gameID, maxLen))
        return 1;

    return 0;
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

    return retrogemPathFallback(path, gameID, maxLen);
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
        if (retrogemCueResolveDataFile(imagePath, dataPath, sizeof(dataPath)) &&
            retrogemGetDiscImageGameID(dataPath, 0, gameID, maxLen))
            return 1;
        return retrogemPathFallback(imagePath, gameID, maxLen);
    }

    if (retrogemHasExt(imagePath, ".BIN") || retrogemHasExt(imagePath, ".ISO"))
        return retrogemGetDiscImageGameID(imagePath, 0, gameID, maxLen);

    // A bare PS-X EXE has no ISO9660 filesystem or trustworthy disc serial. Only emit a GameID when
    // its filename itself is a strict serial, rather than inventing one from the Ember folder name.
    return retrogemPathFallback(imagePath, gameID, maxLen);
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
