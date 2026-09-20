#pragma once

#include <cstdint>

namespace psu {

// On-disk PS2 memory-card directory-entry record. Every .psu entry (the
// root save folder, ".", "..", and each file) is exactly one of these,
// verified against ps2dev/mymc's `<HHL8sLL8sL28x448s>` struct layout.
#pragma pack(push, 1)
struct RawDate {
    uint8_t reserved;
    uint8_t second;
    uint8_t minute;
    uint8_t hour;
    uint8_t day;
    uint8_t month;
    uint16_t year;
};

struct RawDirEntry {
    uint16_t mode;
    uint16_t unused;
    uint32_t length;   // file count for dirs (root includes "." and ".." => +2), byte size for files
    RawDate created;
    uint32_t cluster;  // memory-card FAT cluster; unused in .psu, always 0
    uint32_t dirEntry;  // parent directory entry index; unused in .psu, always 0
    RawDate modified;
    uint32_t attr;
    uint8_t reserved[28];
    char name[448];    // NUL-terminated
};
#pragma pack(pop)

static_assert(sizeof(RawDirEntry) == 512, "RawDirEntry must match the on-disk 512-byte record");

enum Mode : uint16_t {
    ModeRead = 0x0001,
    ModeWrite = 0x0002,
    ModeExecute = 0x0004,
    ModeProtected = 0x0008,
    ModeFile = 0x0010,
    ModeDir = 0x0020,
    ModePocketstation = 0x0800,
    ModePsx = 0x1000,
    ModeHidden = 0x2000,
    ModeExists = 0x8000,
    ModeRwx = ModeRead | ModeWrite | ModeExecute,
};

// File data following a file's RawDirEntry is padded with 0x00 to this boundary.
inline constexpr uint32_t kClusterSize = 1024;

// Max bytes usable for a name, leaving room for the terminating NUL.
inline constexpr size_t kMaxNameLength = sizeof(RawDirEntry::name) - 1;

}  // namespace psu
