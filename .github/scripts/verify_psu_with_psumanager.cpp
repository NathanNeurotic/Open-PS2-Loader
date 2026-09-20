// Cross-check the release packager's PSU against techwritescode's PSUManager core.
#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>

#include "../../third_party/PSUManager/src/core/PsuArchive.h"

namespace fs = std::filesystem;

static void CompareFile(const fs::path& archivePath, const psu::PsuEntry& entry,
                        const fs::path& sourcePath) {
    if (fs::file_size(sourcePath) != entry.size) {
        throw std::runtime_error("size differs: " + entry.name);
    }
    std::ifstream archive(archivePath, std::ios::binary);
    std::ifstream source(sourcePath, std::ios::binary);
    if (!archive || !source) {
        throw std::runtime_error("cannot open PSU member: " + entry.name);
    }
    archive.seekg(static_cast<std::streamoff>(entry.dataOffset));
    std::array<char, 65536> archiveBytes{}, sourceBytes{};
    uint32_t remaining = entry.size;
    while (remaining) {
        const auto count = static_cast<std::streamsize>(
            std::min<size_t>(remaining, archiveBytes.size()));
        archive.read(archiveBytes.data(), count);
        source.read(sourceBytes.data(), count);
        if (archive.gcount() != count || source.gcount() != count ||
            std::memcmp(archiveBytes.data(), sourceBytes.data(), static_cast<size_t>(count))) {
            throw std::runtime_error("bytes differ: " + entry.name);
        }
        remaining -= static_cast<uint32_t>(count);
    }
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::cerr << "usage: verify-psu SAVE.psu APPS/APP_NAME\n";
        return 2;
    }
    try {
        const fs::path archivePath = argv[1];
        const fs::path appDir = argv[2];
        psu::PsuArchive archive;
        archive.Load(archivePath.string());
        if (archive.SaveName() != appDir.filename().string()) {
            throw std::runtime_error("PSU save name differs from app directory");
        }
        std::map<std::string, fs::path> expected;
        for (const auto& member : fs::directory_iterator(appDir)) {
            if (!member.is_regular_file()) {
                throw std::runtime_error("app directory contains a non-file entry");
            }
            expected.emplace(member.path().filename().string(), member.path());
        }
        if (archive.Entries().size() != expected.size()) {
            throw std::runtime_error("PSU member count differs from app directory");
        }
        for (const auto& entry : archive.Entries()) {
            auto member = expected.find(entry.name);
            if (member == expected.end()) {
                throw std::runtime_error("unexpected or repeated PSU member: " + entry.name);
            }
            CompareFile(archivePath, entry, member->second);
            expected.erase(member);
        }
        std::cout << "PSUManager verified " << archivePath.string() << " ("
                  << archive.Entries().size() << " direct files)\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "PSUManager verification failed: " << error.what() << '\n';
        return 1;
    }
}
