extends Resource
func attach(_window: Window, _login: bool) -> void:
	pass
func set_login_mode(_enabled: bool) -> void:
	pass
func configure(_store: RefCounted, _key: String) -> void:
	pass
func select_layout(_key: String, _size: Vector2i, _minimum: Vector2i) -> void:
	pass
func open_window() -> void:
	pass
func tick(_delta: float) -> void:
	pass
func save() -> void:
	pass
func detach() -> void:
	pass
