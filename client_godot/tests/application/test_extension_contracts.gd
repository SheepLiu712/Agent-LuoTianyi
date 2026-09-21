extends SceneTree
var failures: Array[String] = []

class AppearanceProbe extends Resource:
	var contexts: Array[Dictionary] = []
	var stops := 0
	func start(context: Dictionary) -> Error:
		contexts.append(context.duplicate(true))
		context.character_id = "mutated by adapter"
		return OK
	func stop() -> void:
		stops += 1

func check(value: bool, label: String) -> void:
	if not value: failures.append(label); print("FAIL: ",label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var appearance = load("res://src/extensions/appearance_service.gd").new()
	var world = load("res://src/extensions/world_service.gd").new()
	var devices = load("res://src/extensions/device_service.gd").new()
	var completed: Array = []
	for capability in [appearance,world,devices]:
		capability.completed.connect(func(id,result): completed.append([id,result]))
		check(not capability.get_capabilities().available, "reserved capability is explicitly unavailable")
		check(capability.start({"scope_id":"test","generation":1,"character_id":"luotianyi"}) == ERR_UNAVAILABLE, "default start rejects instead of pretending to connect")
		var mutable: Dictionary = capability.get_capabilities()
		mutable.available = true
		check(not capability.get_capabilities().available, "capability snapshots do not leak state")
	for result in [appearance.request_change("a","luotianyi","outfit","ai"),appearance.request_change("u","luotianyi","outfit","user"),world.apply_state({"sample":[1]}),world.request_action("w",{}),devices.request_control("d","device",{})]:
		check(not result.ok and result.code == "NOT_IMPLEMENTED", "reserved operations explicitly reject")
	for capability in [appearance,world,devices]:
		capability.cancel("unknown")
		capability.stop()
		capability.stop()
	await process_frame
	check(completed.is_empty() and appearance.get_state().is_empty(), "default services leave no requests or fake completion")

	# Real application/account/controller lifecycle; only the future external module is a probe.
	var directory := "user://extension-contract-%s" % Time.get_ticks_usec()
	var protection = load("res://src/platform/windows_secret_protection.gd").new()
	var api = load("res://src/network/account_api.gd").new(load("res://src/platform/windows_password_encryption.gd").new())
	var storage = load("res://src/storage/godot_storage_service.gd").new(directory+"/account.cfg",load("res://src/storage/credential_store.gd").new(protection,directory+"/tokens"))
	var session = load("res://src/session/account_session.gd").new(api,storage)
	var first := AppearanceProbe.new()
	var second := AppearanceProbe.new()
	var app = load("res://scenes/main.tscn").instantiate()
	app.appearance = first
	app.world = second
	app.setup(session,directory+"/layout.cfg")
	root.add_child(app)
	await process_frame
	for username in ["ui","other"]:
		var login: Dictionary = await session.perform("login",OS.get_environment("GODOT_TEST_SERVER"),{"username":username,"password":"synthetic-password","request_token":false},false)
		check(login.ok, "real account enters extension lifecycle")
		check(first.contexts[-1] == second.contexts[-1], "one adapter cannot mutate another adapter's context")
		check(first.contexts[-1].keys().size() == 3 and first.contexts[-1].character_id == "luotianyi", "extensions receive only scope generation and character identity")
		var starts := first.contexts.size()
		check(session.set_login_options(username,false,false).ok, "login options can update without leaving the account")
		check(first.contexts.size() == starts, "repeated signed-in state does not restart capabilities")
		session.logout()
	check(first.stops == 2 and second.stops == 2, "logout stops account capabilities")
	check(first.contexts[0].scope_id != first.contexts[1].scope_id and first.contexts[0].generation < first.contexts[1].generation, "account changes produce distinct scopes and newer generations")
	app.queue_free()
	await process_frame
	check(first.stops == 2, "repeated teardown after logout is idempotent")
	_remove_tree(directory)
	print("Extension contracts: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _remove_tree(path: String) -> void:
	assert(path.begins_with("user://extension-contract-"))
	for child in DirAccess.get_directories_at(path): _remove_tree(path.path_join(child))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
