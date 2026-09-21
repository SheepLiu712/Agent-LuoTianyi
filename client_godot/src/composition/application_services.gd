extends RefCounted
## The one concrete service graph. No global lookup or business state transitions.
var account: Node
var chat: Node
var models: Node
var dynamics: Node
var executor: Node
var cache: RefCounted
var storage: RefCounted
var log: RefCounted
var settings: Resource
var dynamics_settings: Resource

static func create_geometry(layout_path: String) -> Resource:
	return preload("res://src/storage/window_geometry.gd").new(layout_path.get_base_dir().path_join("window-geometry.cfg"))

func _init(layout_path: String, runtime: Resource) -> void:
	settings = preload("res://src/storage/godot_settings_store.gd").new(layout_path)
	dynamics_settings = preload("res://src/storage/godot_settings_store.gd").new(layout_path.get_base_dir().path_join("dynamics-window.cfg"))
	log = preload("res://src/storage/client_log.gd").new("user://logs" if layout_path == "user://window_layout.cfg" else layout_path.get_base_dir().path_join("logs"),2097152,runtime)

func mount(host: Node, injected_account: Node, layout_path: String, encryption: Resource, secrets: Resource) -> void:
	var data_root := layout_path.get_base_dir()
	var credentials = preload("res://src/storage/credential_store.gd").new(secrets,data_root.path_join("accounts"))
	storage = preload("res://src/storage/godot_storage_service.gd").new(data_root.path_join("account.cfg"),credentials)
	account = injected_account
	if account == null:
		account = preload("res://src/session/account_session.gd").new(preload("res://src/network/account_api.gd").new(encryption),storage)
	host.add_child(account)
	models = preload("res://src/session/model_settings.gd").new(preload("res://src/network/json_request.gd").new(),preload("res://src/storage/model_store.gd").new(secrets,data_root.path_join("models")),log)
	host.add_child(models)
	dynamics = preload("res://src/session/dynamics_controller.gd").new(log)
	host.add_child(dynamics)
	cache = preload("res://src/storage/audio_cache.gd").new(data_root.path_join("audio"),log)
	var history = preload("res://src/session/history_sync.gd").new(preload("res://src/network/history_api.gd").new(),log)
	var reading = preload("res://src/storage/reading_position.gd").new(data_root.path_join("reading"))
	var images = preload("res://src/storage/history_images.gd").new(data_root.path_join("images"),log)
	executor = preload("res://src/session/model_executor.gd").new(models,log)
	var audio = preload("res://src/media/reply_audio.gd").new(log,Callable(),cache,preload("res://src/platform/native_decoder_factory.gd").new())
	chat = preload("res://src/session/chat_session.gd").new(preload("res://src/network/websocket_transport.gd").new(),log,audio,history,reading,images,executor)
	host.add_child(chat)

func create_settings() -> Dictionary:
	var controller = preload("res://src/session/preferences_controller.gd").new(preload("res://src/network/json_request.gd").new(),log)
	var window = preload("res://scenes/ui/settings_window.tscn").instantiate()
	window.setup(controller,models,executor,chat.clear_cache,storage,cache.get_directory())
	return {"window":window,"start":func(): controller.start(account.get_session())}

func create_dynamics() -> Dictionary:
	var window = preload("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.setup(dynamics,dynamics_settings)
	return {"window":window,"start":Callable()}

static func external_links() -> RefCounted:
	return preload("res://src/platform/godot_external_link_opener.gd").new()
