extends RefCounted

static func tone(seconds: float = 0.3, rate: int = 24000) -> PackedByteArray:
	var frames := int(seconds * rate)
	var bytes := PackedByteArray()
	bytes.resize(44 + frames * 2)
	for pair in [[0,"RIFF"], [8,"WAVE"], [12,"fmt "], [36,"data"]]:
		for i in 4:
			bytes[pair[0] + i] = pair[1].unicode_at(i)
	bytes.encode_u32(4, 36 + frames * 2)
	bytes.encode_u32(16, 16)
	bytes.encode_u16(20, 1)
	bytes.encode_u16(22, 1)
	bytes.encode_u32(24, rate)
	bytes.encode_u32(28, rate * 2)
	bytes.encode_u16(32, 2)
	bytes.encode_u16(34, 16)
	bytes.encode_u32(40, frames * 2)
	for i in frames:
		bytes.encode_s16(44 + i * 2, int(sin(i * TAU * 440.0 / rate) * 8000))
	return bytes
