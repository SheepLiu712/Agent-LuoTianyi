#pragma once

#include <godot_cpp/classes/ref_counted.hpp>

namespace godot {

class WindowsInputMethod : public RefCounted {
    GDCLASS(WindowsInputMethod, RefCounted);

protected:
    static void _bind_methods();

public:
    Dictionary set_english(bool enabled);
    int64_t get_layout() const;
};

} // namespace godot
