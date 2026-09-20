#pragma once

#include <ctime>
#include <string>

#include "PsuFormat.h"

namespace psu {

RawDate ToRawDate(std::time_t time);
std::time_t FromRawDate(const RawDate& date);
RawDate CurrentRawDate();

// Reads/writes a file's last-write time on disk, so Create()/ExtractEntry()
// can preserve real timestamps instead of stamping "now" on everything.
std::time_t FileModifiedTime(const std::string& path);
void SetFileModifiedTime(const std::string& path, std::time_t time);

}  // namespace psu
