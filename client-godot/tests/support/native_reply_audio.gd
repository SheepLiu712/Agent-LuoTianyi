extends "res://src/media/reply_audio.gd"
func _init(logger: RefCounted = null, clock: Callable = Callable(), cache: RefCounted = null) -> void:
	super(logger,clock,cache,preload("res://src/platform/native_decoder_factory.gd").new())
