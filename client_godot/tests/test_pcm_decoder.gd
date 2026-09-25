extends SceneTree
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func wav(pcm: PackedByteArray, bits: int = 16, channels: int = 1, rate: int = 24000, format: int = 1) -> PackedByteArray:
	var bytes := PackedByteArray()
	bytes.resize(44)
	for pair in [[0,"RIFF"], [8,"WAVE"], [12,"fmt "], [36,"data"]]:
		for i in 4:
			bytes[pair[0] + i] = pair[1].unicode_at(i)
	bytes.encode_u32(4, 36 + pcm.size())
	bytes.encode_u32(16, 16)
	bytes.encode_u16(20, format)
	bytes.encode_u16(22, channels)
	bytes.encode_u32(24, rate)
	bytes.encode_u32(28, rate * channels * bits / 8)
	bytes.encode_u16(32, channels * bits / 8)
	bytes.encode_u16(34, bits)
	bytes.encode_u32(40, pcm.size())
	bytes.append_array(pcm)
	return bytes

func decoder():
	return ClassDB.instantiate("PcmStreamDecoder")

func _initialize() -> void:
	if not ClassDB.class_exists("PcmStreamDecoder"):
		print("ENVIRONMENT: decoder extension unavailable")
		quit(2)
		return
	var data := wav(PackedByteArray([0,64,0,192,0,0]))
	data.encode_u32(4, 0xffffffff)
	data.encode_u32(40, 0xffffffff)
	var stream = decoder()
	check(stream.has_method("get_waveform"), "native waveform API available")
	if stream.has_method("get_waveform"):
		var samples := PackedByteArray()
		samples.resize(960)
		for i in range(240,480):
			samples.encode_s16(i*2,16384)
		stream.append(wav(samples))
		check(stream.get_waveform().is_empty(), "unfinished waveform unavailable")
		stream.finish()
		stream.read_frames(480)
		check(stream.get_waveform(2) == PackedFloat32Array([0,.5]), "waveform represents real quiet and loud halves after consumption")
		check(stream.get_waveform(0).is_empty() and stream.get_waveform(129).is_empty(), "waveform bucket bounds")
		stream = decoder()
		stream.append(wav(PackedByteArray([0,64])))
		stream.finish()
		var tiny: PackedFloat32Array = stream.get_waveform(128)
		check(tiny.size() == 128 and tiny[0] == .5 and tiny[127] == .5, "single RMS window safely covers many buckets")
	stream = decoder()
	for part in [data.slice(0,3), data.slice(3,23), data.slice(23,45), data.slice(45)]:
		check(stream.append(part).ok, "split header and partial sample accepted")
	var status: Dictionary = stream.finish()
	check(status.ok and status.finished and status.sample_rate == 24000 and status.decoded_frames == 3, "streamable mono completed")
	check(stream.read_frames(2) == PackedVector2Array([Vector2(.5,.5), Vector2(-.5,-.5)]), "PCM16 normalized stereo frames")
	check(stream.read_frames(8) == PackedVector2Array([Vector2.ZERO]), "reads consume only available frames")
	check(is_equal_approx(stream.get_amplitude(0), sqrt(0.5/3.0)), "native RMS follows absolute frame")
	check(stream.get_amplitude(3) == 0.0, "out of range amplitude zero")
	check(stream.finish().ok and stream.append(data).code == "STREAM_FINISHED", "finish idempotent and rejects late append")
	for sample in [[8, PackedByteArray([192,64]), 1], [24, PackedByteArray([0,0,64,0,0,192]), 1], [32, PackedByteArray([0,0,0,64,0,0,0,192]), 1], [32, PackedByteArray([0,0,0,63,0,0,0,191]), 3]]:
		stream = decoder()
		check(stream.append(wav(sample[1], sample[0], 2, 48000, sample[2])).ok and stream.finish().ok, "supported stereo format")
		check(stream.read_frames(1) == PackedVector2Array([Vector2(.5,-.5)]), "stereo sign and scale")
	for malformed in [PackedByteArray([1,2,3,4]), data.slice(0,43), data.slice(0,45), wav(PackedByteArray())]:
		stream = decoder()
		stream.append(malformed)
		check(not stream.finish().ok and stream.read_frames(100).is_empty(), "truncated or empty rejected without partial data")
	stream = decoder()
	check(not stream.append(wav(PackedByteArray([0,0]),16,1,24000,6)).ok, "compressed format rejected")
	check(not stream.append(data).ok, "decode failure sticky")
	stream = decoder()
	var known := wav(PackedByteArray([0,64,0,192]))
	stream.append(known.slice(0,46))
	check(stream.finish().code == "TRUNCATED_AUDIO", "known data length enforced")
	stream = decoder()
	var with_junk := known.slice(0,12)
	with_junk.append_array(PackedByteArray([74,85,78,75,1,0,0,0,42,0]))
	with_junk.append_array(known.slice(12))
	with_junk.append_array("LISTignored".to_utf8_buffer())
	check(stream.append(with_junk).ok and stream.finish().ok and stream.read_frames(9).size() == 2, "odd auxiliary chunk and trailing metadata ignored")
	var extended := known.slice(0,36)
	extended.encode_u32(16,40)
	extended.encode_u16(20,0xfffe)
	extended.append_array(PackedByteArray([22,0,16,0,4,0,0,0,1,0,0,0,0,0,16,0,128,0,0,170,0,56,155,113]))
	extended.append_array(known.slice(36))
	stream = decoder()
	check(stream.append(extended).ok and stream.finish().ok, "extensible PCM GUID accepted")
	extended[59] = 0
	stream = decoder()
	check(stream.append(extended).code == "UNSUPPORTED_FORMAT", "unknown GUID rejected")
	stream = decoder()
	check(not stream.append(wav(PackedByteArray([0,0,128,127]),32,1,24000,3)).ok, "nonfinite float rejected")
	for invalid_format in [[16,0,24000], [16,3,24000], [16,1,7999], [16,1,192001], [12,1,24000]]:
		stream = decoder()
		check(stream.append(wav(PackedByteArray([0,0]),invalid_format[0],invalid_format[1],invalid_format[2])).code == "UNSUPPORTED_FORMAT", "invalid format bounds rejected")
	for offset in [28,32]:
		stream = decoder()
		var broken := known.duplicate()
		broken[offset] ^= 1
		check(stream.append(broken).code == "INVALID_WAV", "invalid byte rate or alignment rejected")
	stream = decoder()
	var half_frame := known.slice(0,47)
	half_frame.encode_u32(40,3)
	stream.append(half_frame)
	check(stream.finish().code == "TRUNCATED_AUDIO", "known length half frame rejected")
	stream = decoder()
	var large_header := known.slice(0,36)
	large_header.append_array(PackedByteArray([74,85,78,75,0,0,0,0]))
	large_header.encode_u32(40,1024*1024-44)
	large_header.resize(1024*1024)
	large_header.append_array(known.slice(36))
	check(stream.append(large_header).code == "BUFFER_LIMIT", "data header included in prefix bound")
	var silence := PackedByteArray()
	silence.resize(2*1024*1024)
	for rate in [8000,24000]:
		stream = decoder()
		var header := wav(PackedByteArray(),16,1,rate)
		header.encode_u32(40,0xffffffff)
		stream.append(header)
		for i in 17:
			stream.append(silence)
		check(stream.get_status().code == "BUFFER_LIMIT" and stream.read_frames(1).is_empty(), "duration and unread queue limits discard failed buffer")
	stream = decoder()
	var enormous := PackedByteArray()
	enormous.resize(8*1024*1024+1)
	check(stream.append(enormous).code == "BUFFER_LIMIT", "input bound enforced")
	print("PCM decoder: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
