extends SceneTree
## 装配契约：会话层拿到的都是门面，数据库线程与连接只存在于装配层。

const Services = preload("res://src/composition/application_services.gd")

var failures: Array[String] = []
var _root := ""


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	_root = "user://test-services-%d" % Time.get_ticks_usec()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_root))
	var host := Node.new()
	root.add_child(host)
	var account := Node.new()
	account.name = "AccountStandIn"
	var services = Services.new(_root.path_join("window_layout.cfg"), preload("res://src/platform/runtime_environment.gd").new())
	services.mount(host, account, _root.path_join("window_layout.cfg"), null, null, null)
	check(services.storage_worker != null and services.persistence != null, "graph builds the storage facade")
	check(services.chat.get_history_state().has("storage"), "chat exposes storage state")
	check(services.chat.get_messages().is_empty(), "chat starts empty")
	check(services.persistence.scope().is_empty(), "storage is closed until an account starts")
	check(services.chat.has_method("load_older_history"), "chat exposes the older page entry")
	check(services.avatar != null, "graph builds the avatar service")
	check(services.avatar.get_texture() == null, "avatar starts empty before login")
	services.chat.free()
	services.storage_worker.begin_shutdown()
	services.storage_worker.wait_to_finish()
	host.free()
	print("Service graph: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)
