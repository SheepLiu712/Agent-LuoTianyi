extends "res://src/media/decoder_factory.gd"


## 引擎解码器只有方法协议，没有 GDScript 类型；这里保留一个薄适配层，
## 让调用方继续依赖稳定的 RefCounted 接口，而不是 ClassDB 实例。
class Decoder extends RefCounted:
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


func create_decoder() -> RefCounted:
	if not ClassDB.class_exists("PcmStreamDecoder"): return null
	return Decoder.new(ClassDB.instantiate("PcmStreamDecoder"))
