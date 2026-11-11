extends RefCounted
## 唯一的服务装配根：不做全局查找，也不承担业务状态迁移。
var account: Node
var chat: Node
var models: Node
var dynamics: Node
var executor: Node
var storage_worker: Node
var persistence: RefCounted
var media_migration: Node
var avatar: Node
var cache: RefCounted
var storage: RefCounted
var log: RefCounted
var settings: Resource
var dynamics_settings: Resource
var ui_style: RefCounted

static func create_geometry(layout_path: String) -> Resource:
	return preload("res://src/storage/window_geometry.gd").new(layout_path.get_base_dir().path_join("window-geometry.cfg"))

func _init(layout_path: String, runtime: Resource) -> void:
	settings = preload("res://src/storage/godot_settings_store.gd").new(layout_path)
	dynamics_settings = preload("res://src/storage/godot_settings_store.gd").new(layout_path.get_base_dir().path_join("dynamics-window.cfg"))
	ui_style = preload("res://src/application/ui_style.gd").new()
	ui_style.configure(settings)
	log = preload("res://src/storage/client_log.gd").new("user://logs" if layout_path == "user://window_layout.cfg" else layout_path.get_base_dir().path_join("logs"),8*1024*1024,runtime)

func mount(host: Node, injected_account: Node, layout_path: String, encryption: Resource, secrets: Resource, decoder_factory: Resource) -> void:
	var data_root := layout_path.get_base_dir()
	var credentials = preload("res://src/storage/credential_store.gd").new(secrets,data_root.path_join("accounts"),log)
	storage = preload("res://src/storage/godot_storage_service.gd").new(data_root.path_join("account.cfg"),credentials)
	account = injected_account
	if account == null:
		account = preload("res://src/session/account_session.gd").new(preload("res://src/network/account_api.gd").new(encryption,15.0,log),storage,log)
	host.add_child(account)
	models = preload("res://src/session/model_settings.gd").new(preload("res://src/network/json_request.gd").new(15.0,8*1024*1024,log),preload("res://src/storage/model_store.gd").new(secrets,data_root.path_join("models"),log),log)
	host.add_child(models)
	dynamics = preload("res://src/session/dynamics_controller.gd").new(log)
	host.add_child(dynamics)
	cache = preload("res://src/storage/audio_cache.gd").new(data_root.path_join("audio"),log)
	var images = preload("res://src/storage/history_images.gd").new(data_root.path_join("images"),log)
	# 目录随登录切换而变，所以用取数回调；Python 来源只由用户显式选择。
	media_migration = preload("res://src/storage/python_media_migration.gd").new()
	media_migration.bind(
		func() -> String: return cache.get_directory(),
		func() -> String: return images.get_directory())
	media_migration.set_settings(settings)
	media_migration.set_scope_provider(func(): return account.get_session())
	media_migration.set_logger(log)
	host.add_child(media_migration)
	images.set_local_source(func() -> String: return media_migration.get_images_directory())
	# 连接只属于工作线程：装配层造线程与门面，会话层只拿门面。
	storage_worker = preload("res://src/storage/sqlite_worker.gd").new(func() -> RefCounted: return preload("res://src/storage/sqlite_history_database.gd").new(),log)
	host.add_child(storage_worker)
	storage_worker.start()
	persistence = preload("res://src/session/message_persistence.gd").new(storage_worker)
	# 对账使用独立的历史客户端：共用实例会让上翻与对账互相取消。
	var history = preload("res://src/session/history_sync.gd").new(
		preload("res://src/network/history_api.gd").new(15.0,log),persistence,log,
		preload("res://src/network/history_api.gd").new(15.0,log))
	var reading = preload("res://src/storage/reading_position.gd").new(data_root.path_join("reading"))
	executor = preload("res://src/session/model_executor.gd").new(models,log)
	var audio = preload("res://src/media/reply_audio.gd").new(log,Callable(),cache,decoder_factory)
	chat = preload("res://src/session/chat_session.gd").new(preload("res://src/network/websocket_transport.gd").new(Callable(),log),log,audio,history,reading,images,executor,persistence)
	chat.set_history_root(data_root.path_join("history"))
	chat.set_media_migration(media_migration)
	media_migration.imported.connect(func(kind: String, ids: Array):
		if kind == "audio":
			chat.refresh_message_audio(ids)
		else:
			chat.refresh_message_images(ids))
	host.add_child(chat)
	avatar = preload("res://src/session/avatar_profile.gd").new(preload("res://src/storage/avatar_store.gd").new(data_root.path_join("avatar"),log),log)
	host.add_child(avatar)
	chat.set_avatar(avatar)

func create_settings() -> Dictionary:
	var controller = preload("res://src/session/preferences_controller.gd").new(preload("res://src/network/json_request.gd").new(15.0,8*1024*1024,log),log)
	var window = preload("res://scenes/ui/settings_window.tscn").instantiate()
	window.set_ui_style(ui_style)
	window.setup(controller,models,executor,chat.clear_cache,storage,cache.get_directory())
	window.set_media_migration(media_migration)
	window.set_avatar_source(avatar)
	return {"window":window,"start":func(): controller.start(account.get_session())}

func create_dynamics() -> Dictionary:
	var window = preload("res://scenes/ui/dynamics_window.tscn").instantiate()
	window.set_ui_style(ui_style)
	window.setup(dynamics,dynamics_settings)
	window.set_avatar_source(avatar)
	return {"window":window,"start":Callable()}

static func external_links() -> RefCounted:
	return preload("res://src/platform/godot_external_link_opener.gd").new()
