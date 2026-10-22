extends RefCounted
var _decoder: RefCounted
func _init(decoder: RefCounted) -> void:
	_decoder = decoder
func append(bytes: PackedByteArray) -> Dictionary:
	return _decoder.append(bytes)
func finish() -> Dictionary:
	return _decoder.finish()
func read_frames(count: int) -> PackedVector2Array:
	return _decoder.read_frames(count)
func get_status() -> Dictionary:
	return _decoder.get_status()
func get_amplitude(index: int) -> float:
	return _decoder.get_amplitude(index)
func get_waveform(buckets: int = 24) -> PackedFloat32Array:
	return _decoder.get_waveform(buckets)
