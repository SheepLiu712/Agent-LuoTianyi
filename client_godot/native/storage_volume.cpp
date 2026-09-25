#include "storage_volume.h"
#include <godot_cpp/core/class_db.hpp>
#include <cstdint>
#include <limits>
#ifdef _WIN32
#include <windows.h>
#elif defined(__unix__) || defined(__APPLE__)
#include <sys/statvfs.h>
#endif

using namespace godot;

void StorageVolume::_bind_methods() {
    ClassDB::bind_method(D_METHOD("query", "path"), &StorageVolume::query);
}

Dictionary StorageVolume::query(const String &path) const {
    Dictionary result;
    result["total_bytes"] = int64_t(-1);
    result["free_bytes"] = int64_t(-1);
    if (path.is_empty()) return result;
    constexpr uint64_t limit = uint64_t(std::numeric_limits<int64_t>::max());
#ifdef _WIN32
    const Char16String wide = path.utf16();
    ULARGE_INTEGER available{}, total{}, free{};
    if (GetDiskFreeSpaceExW(reinterpret_cast<LPCWSTR>(wide.get_data()), &available, &total, &free) &&
            total.QuadPart > 0 && total.QuadPart <= limit && available.QuadPart <= total.QuadPart) {
        result["total_bytes"] = int64_t(total.QuadPart);
        result["free_bytes"] = int64_t(available.QuadPart);
    }
#elif defined(__unix__) || defined(__APPLE__)
    const CharString native = path.utf8();
    struct statvfs info{};
    if (statvfs(native.get_data(), &info) == 0 && info.f_frsize > 0 && info.f_blocks > 0 &&
            uint64_t(info.f_blocks) <= limit / uint64_t(info.f_frsize) && info.f_bavail <= info.f_blocks) {
        result["total_bytes"] = int64_t(uint64_t(info.f_blocks) * uint64_t(info.f_frsize));
        result["free_bytes"] = int64_t(uint64_t(info.f_bavail) * uint64_t(info.f_frsize));
    }
#endif
    return result;
}
