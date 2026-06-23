#ifndef __TAR_H
#define __TAR_H

// Lazy .tar archive loader (ART/CFG/CHT), ported from wOPL (author: mystyq).
// RiptOPL wires ONLY the ART kind, behind the user toggle gEnableArtTar (default OFF);
// the CFG/CHT kinds are kept intact so they can be wired later with no engine change.
// On-disk format is plain uncompressed ustar (512-byte blocks) so existing wOPL/sOPL
// art packs (ART/art.tar of <GAMEID>_<suffix>.png files) are compatible as-is.

#include <tamtypes.h>

#define TAR_BLOCK_SIZE 512
#define MAX_FILE_SIZE  (4 * 1024 * 1024) // 4 MiB
#define ARC_MAGIC      "ARC\0"
#define ARC_VERSION    3

typedef struct
{
    char magic[4];
    u32 version;
    u64 tarSize;
    u32 entryCount;
} TarCacheHeader;

typedef struct
{
    u64 offset;     // offset of file data in archive
    u32 rawSize;    // actual file size from header (octal), capped by MAX_FILE_SIZE
    u32 paddedSize; // file size rounded up to 512-byte TAR blocks
} TarEntryBase;

typedef struct
{
    TarEntryBase base;
    char filename[41]; // ART: filename up to 40 chars + null
} TarEntryArt;

typedef struct
{
    TarEntryBase base;
    char filename[20]; // CFG: "SLUS_203.70.cfg"
} TarEntryCfg;

typedef struct
{
    TarEntryBase base;
    char filename[20]; // CHT: "SLUS_203.70.cht"
} TarEntryCht;

typedef enum {
    TAR_KIND_ART = 0,
    TAR_KIND_CFG = 1,
    TAR_KIND_CHT = 2,
    TAR_KIND_MAX
} TarKind;

int tarLoadFromAnyDevice(TarKind kind);
int tarLoadFile(TarKind kind, const char *path);
int tarClose(TarKind kind);

TarEntryBase *tarFind(TarKind kind, const char *filename);
void *tarGet(TarKind kind, const char *filename);
u32 tarRead(TarKind kind, const TarEntryBase *entry, void *dst, u32 dstSize);

int tarEnsureLoaded(TarKind kind);
void tarInvalidate(TarKind kind);

const char *tarGetDevicePrefix(TarKind kind);

#endif
