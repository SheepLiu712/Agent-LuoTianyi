extends ColorRect

const DEFAULT_RUNTIME := preload("res://resources/platform/runtime.tres")

@export var runtime: Resource
@export var blur_enabled := true


func _ready() -> void:
	if runtime == null:
		runtime = DEFAULT_RUNTIME
	if not blur_enabled or runtime == null or not runtime.supports_blur():
		material = null
