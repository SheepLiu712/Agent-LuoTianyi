extends Node
signal changed(id: String, state: Dictionary)
func start(_session: Dictionary) -> void:
	pass
func stop() -> void:
	pass
func get_state(_id: String) -> Dictionary:
	return {"status":"error","texture":null,"original_size":Vector2i.ZERO,"code":"IMAGE_SOURCE_UNAVAILABLE"}
func ensure(id: String) -> void:
	changed.emit(id,get_state(id))
func retry(id: String) -> void:
	ensure(id)
func preview(_id: String) -> Texture2D:
	return null
func store_local(_id: String, _bytes: PackedByteArray) -> Error:
	return ERR_UNAVAILABLE
