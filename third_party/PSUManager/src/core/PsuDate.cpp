#include "PsuDate.h"

#include <sys/stat.h>

#if defined(_WIN32)
#include <sys/utime.h>
#else
#include <utime.h>
#endif

#include "PsuArchive.h"

namespace psu {

RawDate ToRawDate(std::time_t time) {
    std::tm tm{};
#if defined(_WIN32)
    localtime_s(&tm, &time);
#else
    localtime_r(&time, &tm);
#endif
    RawDate date{};
    date.reserved = 0;
    date.second = static_cast<uint8_t>(tm.tm_sec);
    date.minute = static_cast<uint8_t>(tm.tm_min);
    date.hour = static_cast<uint8_t>(tm.tm_hour);
    date.day = static_cast<uint8_t>(tm.tm_mday);
    date.month = static_cast<uint8_t>(tm.tm_mon + 1);
    date.year = static_cast<uint16_t>(tm.tm_year + 1900);
    return date;
}

std::time_t FromRawDate(const RawDate& date) {
    std::tm tm{};
    tm.tm_sec = date.second;
    tm.tm_min = date.minute;
    tm.tm_hour = date.hour;
    tm.tm_mday = date.day;
    tm.tm_mon = date.month - 1;
    tm.tm_year = date.year - 1900;
    tm.tm_isdst = -1;
    return std::mktime(&tm);
}

RawDate CurrentRawDate() {
    return ToRawDate(std::time(nullptr));
}

// Deliberately not std::filesystem::last_write_time: its file_time_type runs
// on an unspecified clock pre-C++20 (no standard file_clock <-> system_clock
// conversion until clock_cast), and the usual "now in both clocks" shim to
// bridge that loses up to a second in practice. stat/utime work in time_t
// directly, so there's nothing to convert.
std::time_t FileModifiedTime(const std::string& path) {
#if defined(_WIN32)
    struct _stat64 info {};
    if (_stat64(path.c_str(), &info) != 0) {
        throw PsuFormatError("cannot read modified time for " + path);
    }
#else
    struct stat info {};
    if (stat(path.c_str(), &info) != 0) {
        throw PsuFormatError("cannot read modified time for " + path);
    }
#endif
    return info.st_mtime;
}

void SetFileModifiedTime(const std::string& path, std::time_t time) {
#if defined(_WIN32)
    struct __utimbuf64 times {
        time, time
    };
    if (_utime64(path.c_str(), &times) != 0) {
        throw PsuFormatError("cannot set modified time for " + path);
    }
#else
    struct utimbuf times {
        time, time
    };
    if (utime(path.c_str(), &times) != 0) {
        throw PsuFormatError("cannot set modified time for " + path);
    }
#endif
}

}  // namespace psu
