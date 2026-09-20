#pragma once
#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/variant/dictionary.hpp>

class StorageVolume : public godot::RefCounted {
    GDCLASS(StorageVolume, godot::RefCounted);
protected:
    static void _bind_methods();
public:
    godot::Dictionary query(const godot::String &path) const;
};
