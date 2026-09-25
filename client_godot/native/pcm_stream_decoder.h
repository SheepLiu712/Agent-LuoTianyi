#pragma once
#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/packed_byte_array.hpp>
#include <godot_cpp/variant/packed_vector2_array.hpp>
#include <godot_cpp/variant/packed_float32_array.hpp>
#include <vector>

namespace godot {
class PcmStreamDecoder : public RefCounted {
    GDCLASS(PcmStreamDecoder, RefCounted);
    enum Phase { RIFF, CHUNKS, DATA, TAIL } phase = RIFF;
    std::vector<uint8_t> pending;
    std::vector<Vector2> frames;
    std::vector<float> amplitudes;
    size_t read_offset = 0;
    uint64_t decoded = 0, input = 0, header_bytes = 0, data_left = 0;
    int rate = 0, channels = 0, bits = 0, format = 0, alignment = 0;
    int window_frames = 1, energy_frames = 0;
    double energy = 0;
    bool ended = false, unbounded_data = false;
    String code;
    void fail(const char *reason);
    bool parse_format(const uint8_t *data, size_t size);
    bool decode(const uint8_t *data, size_t count);
protected:
    static void _bind_methods();
public:
    Dictionary append(const PackedByteArray &bytes);
    Dictionary finish();
    Dictionary get_status() const;
    PackedVector2Array read_frames(int max_count);
    double get_amplitude(int64_t frame_index) const;
    PackedFloat32Array get_waveform(int buckets = 24) const;
};
}
