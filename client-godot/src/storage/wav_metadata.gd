extends RefCounted
## 纯数据：解析 WAV 头，并给出缓存 manifest 需要的字段与波形。
## 只做计算，不读写文件、不依赖原生扩展；导入器与测试共用同一套口径。
## 校验边界与 `native/pcm_stream_decoder.cpp`、`audio_cache.gd` 保持一致：
## 能被导入的音频，必须也是能播放的音频。

const HEADER_BYTES := 44
const MAX_BYTES := 8 * 1024 * 1024
const MAX_SECONDS := 1800
const MIN_RATE := 8000
const MAX_RATE := 192000
const WAVE_FORMAT_PCM := 1
const WAVE_FORMAT_FLOAT := 3
const WAVE_FORMAT_EXTENSIBLE := 0xFFFE
const BUCKETS := 24

## 扩展格式的固定 GUID 尾段：只认真正的 PCM / IEEE float 子格式。
const EXTENSIBLE_SUFFIX := [0, 0, 0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71]


static func describe(bytes: PackedByteArray) -> Dictionary:
	var header_code := _header_error(bytes)
	if not header_code.is_empty():
		return _failure(header_code)
	var parsed := _scan_chunks(bytes)
	if not parsed.ok:
		return parsed
	return _describe_stream(bytes.size(), parsed)


## 只看容器层：长度与 RIFF/WAVE 标识。字段级校验交给 _describe_stream。
static func _header_error(bytes: PackedByteArray) -> String:
	if bytes.size() < HEADER_BYTES:
		return "TRUNCATED_AUDIO"
	if bytes.size() > MAX_BYTES:
		return "AUDIO_TOO_LARGE"
	if _tag(bytes, 0) != "RIFF" or _tag(bytes, 8) != "WAVE":
		return "INVALID_WAV"
	return ""


## 字段级的可播放性判断；能被导入的音频必须也是能播放的音频。
static func _describe_stream(total_bytes: int, parsed: Dictionary) -> Dictionary:
	var format := int(parsed.format)
	var channels := int(parsed.channels)
	var bits := int(parsed.bits)
	var rate := int(parsed.sample_rate)
	if not supported_encoding(format, bits):
		return _failure("UNSUPPORTED_FORMAT")
	if not _stream_shape_ok(channels, rate, bits):
		return _failure("UNSUPPORTED_FORMAT")
	var frames := _frame_count(int(parsed.data_size), channels, bits)
	if frames <= 0:
		return _failure("TRUNCATED_AUDIO")
	if frames > rate * MAX_SECONDS:
		return _failure("AUDIO_TOO_LONG")
	return {
		"ok": true, "code": "OK",
		"sample_rate": rate, "channels": channels, "bits": bits, "format": format,
		"frames": frames, "bytes": total_bytes,
		"data_offset": int(parsed.data_offset), "data_size": int(parsed.data_size),
	}

static func _stream_shape_ok(channels: int, rate: int, bits: int) -> bool:
	return channels >= 1 and channels <= 2 and rate >= MIN_RATE and rate <= MAX_RATE and bits % 8 == 0

## 帧数由「数据长度 / 每帧字节」得出；不整除的尾巴不算一帧。
static func _frame_count(data_size: int, channels: int, bits: int) -> int:
	@warning_ignore("integer_division")
	var align := channels * bits / 8
	@warning_ignore("integer_division")
	return data_size / align


static func supported_encoding(format: int, bits: int) -> bool:
	if format == WAVE_FORMAT_PCM:
		return bits in [8, 16, 24, 32]
	return format == WAVE_FORMAT_FLOAT and bits == 32


## 与原生解码器同口径：10ms 窗口 RMS，再按桶取窗口峰值。
## 原生扩展缺席时才走这里，结果用于绘制气泡波形。
static func waveform(bytes: PackedByteArray, metadata: Dictionary, buckets: int = BUCKETS) -> PackedFloat32Array:
	if buckets < 1 or buckets > 128:
		return PackedFloat32Array()
	var shape := _waveform_shape(metadata)
	if shape.is_empty():
		return PackedFloat32Array()
	var amplitudes := _window_peaks(bytes, shape)
	if amplitudes.is_empty():
		return PackedFloat32Array()
	return _bucket_peaks(amplitudes, buckets)


## 一次把后面要反复用的字段算好；任何一项缺失都说明头不可信，直接返回空。
static func _waveform_shape(metadata: Dictionary) -> Dictionary:
	var frames := int(metadata.get("frames", 0))
	var channels := int(metadata.get("channels", 0))
	var bits := int(metadata.get("bits", 0))
	var rate := int(metadata.get("sample_rate", 0))
	var offset := int(metadata.get("data_offset", -1))
	if frames <= 0 or channels <= 0 or bits <= 0 or rate <= 0 or offset < 0:
		return {}
	@warning_ignore("integer_division")
	var width := bits / 8
	return {
		"frames": frames, "channels": channels, "bits": bits, "format": int(metadata.get("format", WAVE_FORMAT_PCM)),
		"offset": offset, "width": width, "step": channels * width, "window": maxi(1, rate / 100),
	}

## 逐帧算 10ms 窗口的 RMS，窗口不满也收尾输出。
static func _window_peaks(bytes: PackedByteArray, shape: Dictionary) -> Array[float]:
	var amplitudes: Array[float] = []
	var energy := 0.0
	var counted := 0
	for frame in int(shape.frames):
		var base: int = int(shape.offset) + frame * int(shape.step)
		var left := _sample(bytes, base, int(shape.bits), int(shape.format))
		var right := left if int(shape.channels) == 1 else _sample(bytes, base + int(shape.width), int(shape.bits), int(shape.format))
		energy += (left * left + right * right) * 0.5
		counted += 1
		if counted == int(shape.window):
			amplitudes.append(sqrt(energy / float(counted)))
			energy = 0.0
			counted = 0
	if counted > 0:
		amplitudes.append(sqrt(energy / float(counted)))
	return amplitudes

## 把窗口序列压到固定桶数，每桶取窗口峰值。
static func _bucket_peaks(amplitudes: Array[float], buckets: int) -> PackedFloat32Array:
	var output := PackedFloat32Array()
	output.resize(buckets)
	var windows := amplitudes.size()
	for bucket in buckets:
		@warning_ignore("integer_division")
		var start := bucket * windows / buckets
		@warning_ignore("integer_division")
		var end := mini(windows, maxi(start + 1, (bucket + 1) * windows / buckets))
		output[bucket] = clampf(_peak_between(amplitudes, start, end), 0.0, 1.0)
	return output

static func _peak_between(amplitudes: Array[float], start: int, end: int) -> float:
	var peak := 0.0
	for index in range(start, end):
		peak = maxf(peak, amplitudes[index])
	return peak


## 逐 chunk 走，跳过未知块并处理奇数字节填充。
## `data` 长度为 0 或越界时按「剩余文件长度」处理，兼容流式写出的头。
static func _scan_chunks(bytes: PackedByteArray) -> Dictionary:
	var offset := 12
	var rate := 0
	var channels := 0
	var bits := 0
	var format := 0
	var data_offset := -1
	var data_size := 0
	while offset + 8 <= bytes.size():
		var identifier := _tag(bytes, offset)
		var declared := int(bytes.decode_u32(offset + 4))
		var body := offset + 8
		if identifier == "fmt ":
			var fmt := _read_fmt(bytes, body, declared)
			if not fmt.ok:
				return fmt
			format = int(fmt.format)
			channels = int(fmt.channels)
			rate = int(fmt.rate)
			bits = int(fmt.bits)
		elif identifier == "data":
			var data := _read_data(bytes, body, declared, channels, bits, rate)
			if not data.ok:
				return data
			data_offset = int(data.offset)
			data_size = int(data.size)
			break
		if declared == 0xFFFFFFFF:
			break
		offset = body + declared + declared % 2
	if data_offset < 0:
		return _failure("TRUNCATED_AUDIO")
	return {
		"ok": true, "code": "OK", "sample_rate": rate, "channels": channels,
		"bits": bits, "format": format, "data_offset": data_offset, "data_size": data_size,
	}

## fmt 块必须先于 data 出现，且 16 字节的公共头要完整。
static func _read_fmt(bytes: PackedByteArray, body: int, declared: int) -> Dictionary:
	if declared < 16 or body + 16 > bytes.size():
		return _failure("INVALID_WAV")
	var bits := int(bytes.decode_u16(body + 14))
	var format := int(bytes.decode_u16(body))
	if format == WAVE_FORMAT_EXTENSIBLE:
		if not _extensible_format(bytes, body, declared, bits):
			return _failure("UNSUPPORTED_FORMAT")
		format = int(bytes.decode_u16(body + 24))
	return {
		"ok": true, "format": format, "channels": int(bytes.decode_u16(body + 2)),
		"rate": int(bytes.decode_u32(body + 4)), "bits": bits,
	}

## 没有先读到合法 fmt 就出现 data，说明头不全。
static func _read_data(bytes: PackedByteArray, body: int, declared: int, channels: int, bits: int, rate: int) -> Dictionary:
	if channels <= 0 or bits <= 0 or rate <= 0:
		return _failure("INVALID_WAV")
	var size := _declared_data_size(bytes, body, declared)
	if size <= 0:
		return _failure("TRUNCATED_AUDIO")
	return {"ok": true, "offset": body, "size": size}

## 只有「长度未知」才用文件尾兜底；声明长度超出文件就是写了一半，返回 -1。
static func _declared_data_size(bytes: PackedByteArray, body: int, declared: int) -> int:
	if declared == 0 or declared == 0xFFFFFFFF:
		return bytes.size() - body
	if body + declared > bytes.size():
		return -1
	return declared


static func _extensible_format(bytes: PackedByteArray, body: int, declared: int, bits: int) -> bool:
	if declared < 40 or body + 40 > bytes.size():
		return false
	if int(bytes.decode_u16(body + 16)) < 22 or int(bytes.decode_u16(body + 18)) != bits:
		return false
	for index in EXTENSIBLE_SUFFIX.size():
		if bytes[body + 26 + index] != EXTENSIBLE_SUFFIX[index]:
			return false
	return true


static func _sample(bytes: PackedByteArray, offset: int, bits: int, format: int) -> float:
	match bits:
		8:
			return (float(bytes[offset]) - 128.0) / 128.0
		16:
			return float(bytes.decode_s16(offset)) / 32768.0
		24:
			var value := int(bytes[offset]) | (int(bytes[offset + 1]) << 8) | (int(bytes[offset + 2]) << 16)
			if value >= 0x800000:
				value -= 0x1000000
			return float(value) / 8388608.0
		_:
			if format == WAVE_FORMAT_FLOAT:
				return bytes.decode_float(offset)
			return float(bytes.decode_s32(offset)) / 2147483648.0


static func _tag(bytes: PackedByteArray, offset: int) -> String:
	if offset + 4 > bytes.size():
		return ""
	var text := ""
	for index in 4:
		var value := int(bytes[offset + index])
		# 非可打印字节不可能是 chunk 标识；直接判空，避免把 NUL 拼进字符串。
		if value < 0x20 or value > 0x7E:
			return ""
		text += String.chr(value)
	return text


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code}
