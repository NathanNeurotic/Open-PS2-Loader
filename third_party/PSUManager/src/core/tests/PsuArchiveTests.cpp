#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "../PsuArchive.h"
#include "../PsuDate.h"

namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void Check(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << "\n";
        ++g_failures;
    }
}

void WriteFile(const fs::path& path, const std::string& content) {
    std::ofstream out(path, std::ios::binary);
    out << content;
}

std::string ReadFile(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

void TestCreateLoadExtractRoundTrip(const fs::path& workDir) {
    const fs::path srcDir = workDir / "src";
    fs::create_directories(srcDir);
    WriteFile(srcDir / "icon.sys", std::string(100, '\x01'));
    WriteFile(srcDir / "save.bin", std::string(2500, '\x02'));  // spans multiple 1024-byte clusters

    const fs::path archivePath = workDir / "BESLES-12345TESTGAME.psu";
    psu::PsuArchive::Create(archivePath.string(), "BESLES-12345TESTGAME",
                             {{(srcDir / "icon.sys").string(), "icon.sys"},
                              {(srcDir / "save.bin").string(), "save.bin"}});

    psu::PsuArchive archive;
    archive.Load(archivePath.string());
    Check(archive.SaveName() == "BESLES-12345TESTGAME", "save name round-trips");
    Check(archive.Entries().size() == 2, "entry count round-trips");
    Check(archive.Entries()[0].name == "icon.sys", "first entry name round-trips");
    Check(archive.Entries()[0].size == 100, "first entry size round-trips");
    Check(archive.Entries()[1].name == "save.bin", "second entry name round-trips");
    Check(archive.Entries()[1].size == 2500, "second entry size round-trips");

    const fs::path extractDir = workDir / "extracted";
    archive.ExtractAll(extractDir.string());
    Check(ReadFile(extractDir / "icon.sys") == ReadFile(srcDir / "icon.sys"), "icon.sys extracts byte-identical");
    Check(ReadFile(extractDir / "save.bin") == ReadFile(srcDir / "save.bin"), "save.bin extracts byte-identical");

    // 3 header dirents (512 each) + per-file (512-byte dirent + data padded to 1024).
    const uint64_t expectedSize = 3 * 512 + (512 + 1024) + (512 + 3072);
    Check(fs::file_size(archivePath) == expectedSize, "archive file size matches dirent+padded-data layout");
}

void TestPreservesFileTimestamps(const fs::path& workDir) {
    const fs::path srcFile = workDir / "timestamped.bin";
    WriteFile(srcFile, "stamped content");

    // Mid-January, mid-morning: far from any DST transition, so mktime's
    // local-time round-trip through RawDate's calendar fields is unambiguous.
    std::tm tm{};
    tm.tm_year = 2020 - 1900;
    tm.tm_mon = 0;
    tm.tm_mday = 15;
    tm.tm_hour = 10;
    tm.tm_min = 30;
    tm.tm_sec = 0;
    tm.tm_isdst = -1;
    const std::time_t pastTime = std::mktime(&tm);
    psu::SetFileModifiedTime(srcFile.string(), pastTime);

    const fs::path archivePath = workDir / "TIMESTAMPTEST.psu";
    psu::PsuArchive::Create(archivePath.string(), "TIMESTAMPTEST", {{srcFile.string(), "timestamped.bin"}});

    psu::PsuArchive archive;
    archive.Load(archivePath.string());
    Check(archive.Entries()[0].modified == pastTime, "archive stores the source file's real modified timestamp");

    const fs::path extractDir = workDir / "extracted_timestamp";
    archive.ExtractAll(extractDir.string());
    Check(psu::FileModifiedTime((extractDir / "timestamped.bin").string()) == pastTime,
          "extraction restores the original modified timestamp");
}

void TestRejectsGarbageFile(const fs::path& workDir) {
    const fs::path garbagePath = workDir / "garbage.psu";
    WriteFile(garbagePath, std::string(2048, '\xff'));

    psu::PsuArchive archive;
    bool threw = false;
    try {
        archive.Load(garbagePath.string());
    } catch (const psu::PsuFormatError&) {
        threw = true;
    }
    Check(threw, "loading a non-.psu file throws PsuFormatError");
}

void TestRejectsPathTraversalName(const fs::path& workDir) {
    const fs::path srcFile = workDir / "payload.bin";
    WriteFile(srcFile, "x");

    bool threw = false;
    try {
        psu::PsuArchive::Create((workDir / "traversal.psu").string(), "SAVE",
                                 {{srcFile.string(), "../../evil.bin"}});
    } catch (const psu::PsuFormatError&) {
        threw = true;
    }
    Check(threw, "creating an archive with a path-separator entry name throws PsuFormatError");
}

}  // namespace

int main() {
    const fs::path workDir = fs::temp_directory_path() / "psu-core-tests";
    fs::remove_all(workDir);
    fs::create_directories(workDir);

    TestCreateLoadExtractRoundTrip(workDir);
    TestPreservesFileTimestamps(workDir);
    TestRejectsGarbageFile(workDir);
    TestRejectsPathTraversalName(workDir);

    fs::remove_all(workDir);

    if (g_failures == 0) {
        std::cout << "all tests passed\n";
        return 0;
    }
    std::cerr << g_failures << " test(s) failed\n";
    return 1;
}
