#include "pcm_stream_decoder.h"
#include <godot_cpp/core/class_db.hpp>
#include <algorithm>
#include <cmath>
#include <cstring>
using namespace godot;
namespace {
constexpr size_t QUEUE_FRAMES = 128 * 1024 * 1024 / sizeof(Vector2);
constexpr size_t HEADER_LIMIT = 1024 * 1024;
uint16_t u16(const uint8_t *p) { return p[0] | (uint16_t(p[1]) << 8); }
uint32_t u32(const uint8_t *p) { return u16(p) | (uint32_t(u16(p + 2)) << 16); }
bool tag(const uint8_t *p, const char *name) { return std::memcmp(p, name, 4) == 0; }
}
void PcmStreamDecoder::_bind_methods() {
    ClassDB::bind_method(D_METHOD("append", "bytes"), &PcmStreamDecoder::append);
    ClassDB::bind_method(D_METHOD("finish"), &PcmStreamDecoder::finish);
    ClassDB::bind_method(D_METHOD("get_status"), &PcmStreamDecoder::get_status);
    ClassDB::bind_method(D_METHOD("read_frames", "max_count"), &PcmStreamDecoder::read_frames);
    ClassDB::bind_method(D_METHOD("get_amplitude", "frame_index"), &PcmStreamDecoder::get_amplitude);
    ClassDB::bind_method(D_METHOD("get_waveform", "buckets"), &PcmStreamDecoder::get_waveform, DEFVAL(24));
}
Dictionary PcmStreamDecoder::get_status() const {
    Dictionary status;
    status["ok"] = code.is_empty();
    status["code"] = code;
    status["sample_rate"] = rate;
    status["channels"] = channels;
    status["bits"] = bits;
    status["queued_frames"] = int64_t(frames.size() - read_offset);
    status["decoded_frames"] = int64_t(decoded);
    status["input_bytes"] = int64_t(input);
    status["finished"] = ended;
    return status;
}

void PcmStreamDecoder::fail(const char *reason) {
    code = reason;
    ended = true;
    std::vector<uint8_t>().swap(pending);
    std::vector<Vector2>().swap(frames);
    std::vector<float>().swap(amplitudes);
    read_offset = 0;
    energy_frames = 0;
}

bool PcmStreamDecoder::parse_format(const uint8_t *p, size_t size) {
    if (size < 16 || rate != 0) { fail("INVALID_WAV"); return false; }
    format = u16(p); channels = u16(p + 2); rate = u32(p + 4);
    alignment = u16(p + 12); bits = u16(p + 14);
    if (format == 0xfffe) {
        // Validate the entire subtype GUID; accepting only its first word is unsafe.
        const uint8_t suffix[] = {0,0,0,0,0x10,0,0x80,0,0,0xaa,0,0x38,0x9b,0x71};
        if (size < 40 || u16(p + 16) < 22 || u16(p + 18) != bits ||
                std::memcmp(p + 26, suffix, sizeof(suffix)) != 0) {
            fail("UNSUPPORTED_FORMAT"); return false;
        }
        format = u16(p + 24);
    }
    if (channels < 1 || channels > 2 || rate < 8000 || rate > 192000 ||
            !((format == 1 && (bits == 8 || bits == 16 || bits == 24 || bits == 32)) ||
              (format == 3 && bits == 32))) {
        fail("UNSUPPORTED_FORMAT"); return false;
    }
    if (alignment != channels * bits / 8 || u32(p + 8) != uint32_t(rate * alignment)) {
        fail("INVALID_WAV"); return false;
    }
    window_frames = std::max(1, rate / 100);
    return true;
}

bool PcmStreamDecoder::decode(const uint8_t *p, size_t count) {
    const size_t amount = count / alignment;
    if (frames.size() - read_offset + amount > QUEUE_FRAMES || decoded + amount > uint64_t(rate) * 1800) {
        fail("BUFFER_LIMIT"); return false;
    }
    if (read_offset && read_offset * 2 >= frames.size()) {
        frames.erase(frames.begin(), frames.begin() + read_offset);
        read_offset = 0;
    }
    for (size_t frame = 0; frame < amount; ++frame) {
        float values[2];
        for (int channel = 0; channel < channels; ++channel, p += bits / 8) {
            float value;
            if (format == 3) {
                std::memcpy(&value, p, sizeof(value));
                if (!std::isfinite(value)) { fail("INVALID_WAV"); return false; }
            } else if (bits == 8) value = (int(p[0]) - 128) / 128.f;
            else if (bits == 16) value = int16_t(u16(p)) / 32768.f;
            else if (bits == 24) {
                int32_t integer = p[0] | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16);
                if (integer & 0x800000) integer -= 0x1000000;
                value = integer / 8388608.f;
            } else value = int32_t(u32(p)) / 2147483648.f;
            values[channel] = std::clamp(value, -1.f, 1.f);
        }
        if (channels == 1) values[1] = values[0];
        frames.emplace_back(values[0], values[1]);
        energy += (double(values[0]) * values[0] + double(values[1]) * values[1]) * 0.5;
        if (++energy_frames == window_frames) {
            amplitudes.push_back(float(std::sqrt(energy / energy_frames)));
            energy = 0; energy_frames = 0;
        }
        ++decoded;
    }
    return true;
}

Dictionary PcmStreamDecoder::append(const PackedByteArray &bytes) {
    if (!code.is_empty()) return get_status();
    if (ended) {
        Dictionary status = get_status();
        status["ok"] = false; status["code"] = "STREAM_FINISHED";
        return status;
    }
    if (bytes.size() > 8 * 1024 * 1024) { fail("BUFFER_LIMIT"); return get_status(); }
    input += bytes.size();
    if (!bytes.is_empty()) pending.insert(pending.end(), bytes.ptr(), bytes.ptr() + bytes.size());
    size_t offset = 0;
    while (offset < pending.size()) {
        const uint8_t *p = pending.data() + offset;
        const size_t available = pending.size() - offset;
        if (phase == RIFF) {
            if (available < 12) break;
            if (!tag(p, "RIFF") || !tag(p + 8, "WAVE")) { fail("INVALID_WAV"); return get_status(); }
            offset += 12; header_bytes += 12; phase = CHUNKS;
        } else if (phase == CHUNKS) {
            if (available < 8) break;
            const uint32_t size = u32(p + 4);
            if (tag(p, "data")) {
                if (!rate) { fail("INVALID_WAV"); return get_status(); }
                if (header_bytes + 8 > HEADER_LIMIT) { fail("BUFFER_LIMIT"); return get_status(); }
                data_left = size; unbounded_data = size == 0xffffffff;
                offset += 8; phase = DATA;
            } else {
                const uint64_t padded = uint64_t(size) + (size & 1) + 8;
                if (header_bytes + padded > HEADER_LIMIT) { fail("BUFFER_LIMIT"); return get_status(); }
                if (available < padded) break;
                if (tag(p, "fmt ") && !parse_format(p + 8, size)) return get_status();
                offset += size_t(padded); header_bytes += padded;
            }
        } else if (phase == DATA) {
            size_t count = unbounded_data ? available : size_t(std::min<uint64_t>(available, data_left));
            count -= count % alignment;
            if (count && !decode(p, count)) return get_status();
            offset += count;
            if (!unbounded_data) {
                data_left -= count;
                if (!data_left) { phase = TAIL; continue; }
            }
            if (!count) break;
        } else { offset = pending.size(); }
    }
    if (offset) pending.erase(pending.begin(), pending.begin() + offset);
    return get_status();
}

Dictionary PcmStreamDecoder::finish() {
    if (ended) return get_status();
    if (phase == RIFF || phase == CHUNKS || !pending.empty() || (!unbounded_data && data_left)) fail("TRUNCATED_AUDIO");
    else if (!decoded) fail("EMPTY_AUDIO");
    ended = true;
    return get_status();
}

PackedVector2Array PcmStreamDecoder::read_frames(int max_count) {
    PackedVector2Array output;
    if (max_count <= 0) return output;
    const size_t count = std::min<size_t>(max_count, frames.size() - read_offset);
    output.resize(count);
    if (count) std::copy_n(frames.data() + read_offset, count, output.ptrw());
    read_offset += count;
    if (read_offset == frames.size()) { frames.clear(); read_offset = 0; }
    return output;
}

double PcmStreamDecoder::get_amplitude(int64_t index) const {
    if (!code.is_empty() || index < 0 || uint64_t(index) >= decoded) return 0;
    const size_t window = size_t(index / window_frames);
    if (window < amplitudes.size()) return amplitudes[window];
    return energy_frames ? std::sqrt(energy / energy_frames) : 0;
}

PackedFloat32Array PcmStreamDecoder::get_waveform(int buckets) const {
    PackedFloat32Array output;
    if (!ended || !code.is_empty() || !decoded || buckets < 1 || buckets > 128) return output;
    output.resize(buckets);
    const uint64_t windows = amplitudes.size() + (energy_frames ? 1 : 0);
    for (int bucket = 0; bucket < buckets; ++bucket) {
        const uint64_t start = uint64_t(bucket) * windows / buckets;
        const uint64_t end = std::max(start + 1, uint64_t(bucket + 1) * windows / buckets);
        float peak = 0;
        for (uint64_t window = start; window < end; ++window) {
            const float value = window < amplitudes.size() ? amplitudes[window] : float(std::sqrt(energy / energy_frames));
            peak = std::max(peak, value);
        }
        output.set(bucket, peak);
    }
    return output;
}
