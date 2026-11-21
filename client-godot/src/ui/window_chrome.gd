extends Control

const DEFAULT_HOST := preload("res://resources/platform/window_host.tres")

@export var login_mode := false
@export var host: Resource


func _init() -> void:
	name = "WindowChrome"
	visible = false
	mouse_filter = MOUSE_FILTER_IGNORE
	if host == null:
		host = DEFAULT_HOST.duplicate()


func _enter_tree() -> void:
	host.attach(get_window(),login_mode)
func set_login_mode(enabled: bool) -> void:
	login_mode = enabled
	host.set_login_mode(enabled)
func configure(store: RefCounted, key: String) -> void:
	host.configure(store,key)
func select_layout(key: String, size: Vector2i, minimum: Vector2i) -> void:
	host.select_layout(key,size,minimum)
func open_window() -> void:
	host.open_window()
func _process(delta: float) -> void:
	host.tick(delta)
func _exit_tree() -> void:
	host.detach()
