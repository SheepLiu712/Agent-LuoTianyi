#include "windows_input_method.h"

#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <windows.h>

using namespace godot;

namespace {
HKL saved_layout = nullptr;
DWORD saved_thread = 0;

Dictionary result(bool ok, const char *error = "", int64_t native_code = 0) {
    Dictionary value;
    value["ok"] = ok;
    value["error"] = error;
    value["stage"] = "native_code";
    value["native_code"] = native_code;
    return value;
}
}

void WindowsInputMethod::_bind_methods() {
    ClassDB::bind_method(D_METHOD("set_english", "enabled"), &WindowsInputMethod::set_english);
    ClassDB::bind_method(D_METHOD("get_layout"), &WindowsInputMethod::get_layout);
}

Dictionary WindowsInputMethod::set_english(bool enabled) {
    const DWORD thread = GetCurrentThreadId();
    if (!enabled) {
        if (saved_layout != nullptr && saved_thread == thread) {
            const HKL previous = ActivateKeyboardLayout(saved_layout, 0);
            saved_layout = nullptr;
            saved_thread = 0;
            if (previous == nullptr) return result(false, "ACTIVATE_FAILED", GetLastError());
        }
        return result(true);
    }

    if (saved_layout == nullptr) {
        saved_layout = GetKeyboardLayout(thread);
        saved_thread = thread;
    }
    const HKL english = LoadKeyboardLayoutW(L"00000409", 0);
    if (english == nullptr) return result(false, "LOAD_FAILED", GetLastError());
    if (GetKeyboardLayout(thread) == english) return result(true);
    if (ActivateKeyboardLayout(english, 0) == nullptr) {
        return result(false, "ACTIVATE_FAILED", GetLastError());
    }
    return result(true);
}

int64_t WindowsInputMethod::get_layout() const {
    return static_cast<int64_t>(reinterpret_cast<uintptr_t>(GetKeyboardLayout(GetCurrentThreadId())));
}
