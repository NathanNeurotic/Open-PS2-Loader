#pragma once

#include <cstdint>
#include <ctime>
#include <stdexcept>
#include <string>
#include <vector>

namespace psu {

class PsuFormatError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct PsuEntry {
    std::string name;
    uint32_t size = 0;
    std::time_t created = 0;
    std::time_t modified = 0;
    uint64_t dataOffset = 0;  // byte offset into the archive file where this entry's raw data begins
};

// A file to bundle into a new archive: read from `sourcePath` on the local
// filesystem, stored inside the archive under `storedName`.
struct SourceFile {
    std::string sourcePath;
    std::string storedName;
};

// Reads and writes the PS2 .psu save-archive format (a sequence of 512-byte
// memory-card directory-entry records; see PsuFormat.h for the on-disk
// layout this was verified against).
class PsuArchive {
public:
    void Load(const std::string& archivePath);

    const std::string& SaveName() const { return saveName_; }
    const std::vector<PsuEntry>& Entries() const { return entries_; }

    // Writes every entry into destDir, using each entry's stored name.
    void ExtractAll(const std::string& destDir) const;
    void ExtractEntry(size_t index, const std::string& destFilePath) const;

    static void Create(const std::string& outPath, const std::string& saveName,
                        const std::vector<SourceFile>& files);

private:
    std::string archivePath_;
    std::string saveName_;
    std::vector<PsuEntry> entries_;
};

}  // namespace psu
