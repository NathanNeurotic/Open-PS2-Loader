#include "PsuArchive.h"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

#include "PsuDate.h"
#include "PsuFormat.h"

namespace psu {

namespace {

namespace fs = std::filesystem;

uint32_t RoundUpToCluster(uint32_t size) {
    return (size + kClusterSize - 1) / kClusterSize * kClusterSize;
}

std::string NameFromRaw(const char* raw) {
    return std::string(raw, strnlen(raw, sizeof(RawDirEntry::name)));
}

void ValidateStoredName(const std::string& name) {
    if (name.empty() || name.size() > kMaxNameLength) {
        throw PsuFormatError("invalid entry name: " + name);
    }
    if (name == "." || name == ".." || name.find_first_of("/\\") != std::string::npos) {
        throw PsuFormatError("invalid entry name: " + name);
    }
}

RawDirEntry MakeDirEntry(uint16_t mode, uint32_t length, const RawDate& created,
                          const RawDate& modified, const std::string& name) {
    RawDirEntry entry{};
    entry.mode = mode;
    entry.length = length;
    entry.created = created;
    entry.modified = modified;
    std::copy(name.begin(), name.end(), entry.name);
    return entry;
}

RawDirEntry ReadRawDirEntry(std::ifstream& in) {
    RawDirEntry entry{};
    in.read(reinterpret_cast<char*>(&entry), sizeof(entry));
    if (!in) {
        throw PsuFormatError("truncated .psu file");
    }
    return entry;
}

void WriteRawDirEntry(std::ofstream& out, const RawDirEntry& entry) {
    out.write(reinterpret_cast<const char*>(&entry), sizeof(entry));
}

void CopyFileBytes(std::ifstream& in, std::ofstream& out, uint64_t size) {
    constexpr size_t kBufSize = 64 * 1024;
    std::vector<char> buf(kBufSize);
    uint64_t remaining = size;
    while (remaining > 0) {
        const std::streamsize chunk = static_cast<std::streamsize>(std::min<uint64_t>(remaining, kBufSize));
        in.read(buf.data(), chunk);
        if (!in) {
            throw PsuFormatError("failed reading source file");
        }
        out.write(buf.data(), chunk);
        remaining -= static_cast<uint64_t>(chunk);
    }
}

void WriteZeroPadding(std::ofstream& out, uint32_t count) {
    if (count == 0) return;
    static const std::vector<char> zeros(kClusterSize, 0);
    out.write(zeros.data(), count);
}

}  // namespace

void PsuArchive::Load(const std::string& archivePath) {
    std::ifstream in(archivePath, std::ios::binary);
    if (!in) {
        throw PsuFormatError("cannot open " + archivePath);
    }

    const uint64_t archiveSize = fs::file_size(archivePath);

    const RawDirEntry root = ReadRawDirEntry(in);
    const RawDirEntry dot = ReadRawDirEntry(in);
    const RawDirEntry dotdot = ReadRawDirEntry(in);
    const bool rootIsDir = (root.mode & ModeDir) != 0;
    const bool dotIsDir = (dot.mode & ModeDir) != 0;
    const bool dotdotIsDir = (dotdot.mode & ModeDir) != 0;
    if (!rootIsDir || !dotIsDir || !dotdotIsDir || root.length < 2) {
        throw PsuFormatError(archivePath + " is not a valid .psu save archive");
    }

    // Every file entry needs at least one more 512-byte DIRENTRY record, so this
    // bounds a corrupt/garbage root.length before it drives a runaway reserve().
    const uint32_t fileCount = root.length - 2;
    const uint64_t headerSize = 3 * sizeof(RawDirEntry);
    if (fileCount > (archiveSize - std::min(archiveSize, headerSize)) / sizeof(RawDirEntry)) {
        throw PsuFormatError(archivePath + " is not a valid .psu save archive");
    }

    archivePath_ = archivePath;
    saveName_ = NameFromRaw(root.name);
    entries_.clear();
    entries_.reserve(fileCount);
    for (uint32_t i = 0; i < fileCount; ++i) {
        const RawDirEntry fileEntry = ReadRawDirEntry(in);
        if ((fileEntry.mode & ModeFile) == 0) {
            throw PsuFormatError(archivePath + " contains a subdirectory, which .psu does not support");
        }

        const std::string name = NameFromRaw(fileEntry.name);
        ValidateStoredName(name);

        PsuEntry entry;
        entry.name = name;
        entry.size = fileEntry.length;
        entry.created = FromRawDate(fileEntry.created);
        entry.modified = FromRawDate(fileEntry.modified);
        entry.dataOffset = static_cast<uint64_t>(in.tellg());
        entries_.push_back(entry);

        in.seekg(RoundUpToCluster(fileEntry.length), std::ios::cur);
        if (!in) {
            throw PsuFormatError("truncated .psu file");
        }
    }
}

void PsuArchive::ExtractEntry(size_t index, const std::string& destFilePath) const {
    const PsuEntry& entry = entries_.at(index);

    std::ifstream in(archivePath_, std::ios::binary);
    if (!in) {
        throw PsuFormatError("cannot open " + archivePath_);
    }
    in.seekg(static_cast<std::streamoff>(entry.dataOffset));

    std::ofstream out(destFilePath, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw PsuFormatError("cannot create " + destFilePath);
    }
    CopyFileBytes(in, out, entry.size);
    out.close();

    SetFileModifiedTime(destFilePath, entry.modified);
}

void PsuArchive::ExtractAll(const std::string& destDir) const {
    fs::create_directories(destDir);
    for (size_t i = 0; i < entries_.size(); ++i) {
        ExtractEntry(i, (fs::path(destDir) / entries_[i].name).string());
    }
}

void PsuArchive::Create(const std::string& outPath, const std::string& saveName,
                         const std::vector<SourceFile>& files) {
    ValidateStoredName(saveName);
    for (const SourceFile& file : files) {
        ValidateStoredName(file.storedName);
    }

    std::ofstream out(outPath, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw PsuFormatError("cannot create " + outPath);
    }

    const RawDate now = CurrentRawDate();
    const uint16_t dirMode = ModeDir | ModeRwx | ModeExists;
    const uint16_t fileMode = ModeFile | ModeRwx | ModeExists;

    WriteRawDirEntry(out, MakeDirEntry(dirMode, static_cast<uint32_t>(files.size()) + 2, now, now, saveName));
    WriteRawDirEntry(out, MakeDirEntry(dirMode, 0, now, now, "."));
    WriteRawDirEntry(out, MakeDirEntry(dirMode, 0, now, now, ".."));

    for (const SourceFile& file : files) {
        std::ifstream in(file.sourcePath, std::ios::binary | std::ios::ate);
        if (!in) {
            throw PsuFormatError("cannot open " + file.sourcePath);
        }
        const uint64_t size = static_cast<uint64_t>(in.tellg());
        in.seekg(0);

        // The source file's own timestamp, not "now" - archives should
        // preserve when a save was actually written, not when it was
        // bundled into a .psu.
        const RawDate fileDate = ToRawDate(FileModifiedTime(file.sourcePath));
        WriteRawDirEntry(out, MakeDirEntry(fileMode, static_cast<uint32_t>(size), fileDate, fileDate, file.storedName));
        CopyFileBytes(in, out, size);
        WriteZeroPadding(out, RoundUpToCluster(static_cast<uint32_t>(size)) - static_cast<uint32_t>(size));
    }
}

}  // namespace psu
