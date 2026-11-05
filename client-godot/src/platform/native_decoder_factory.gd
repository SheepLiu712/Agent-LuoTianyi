extends "res://src/media/decoder_factory.gd"
func create_decoder() -> RefCounted:
	if not ClassDB.class_exists("PcmStreamDecoder"): return null
	return preload("res://src/platform/native_pcm_decoder.gd").new(ClassDB.instantiate("PcmStreamDecoder"))
