extends SceneTree
class BrokenSecurity extends RefCounted:
	func protect_secret(_plain: PackedByteArray,_scope: PackedByteArray) -> Dictionary:
		return {"ok":false,"data":PackedByteArray(),"error":"PROTECT_FAILED"}
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	check(ResourceLoader.exists("res://src/session/model_settings.gd"),"dynamic model settings exist")
	if not failures.is_empty():
		quit(1)
		return
	var directory := "user://model-settings-test-%s"%Time.get_ticks_usec()
	var store_script = load("res://src/storage/model_store.gd")
	var security = ClassDB.instantiate("WindowsSecurity")
	var store = store_script.new(security,directory)
	var settings = load("res://src/session/model_settings.gd").new(load("res://src/network/json_request.gd").new(),store)
	root.add_child(settings)
	var scope := {"server":OS.get_environment("GODOT_TEST_SERVER"),"username":"models","message_token":"message-test"}
	await settings.start(scope)
	check(settings.get_types().size()==2,"types discovered without fixed purpose IDs")
	var config: Dictionary = settings.get_config("text-purpose")
	config.merge({"enabled":true,"base_url":scope.server+"/v1","api_key":"SYNTHETIC_KEY","model":"fake-model","provider":"Fixture"},true)
	check(not settings.validate("text-purpose",config).ok,"required JSON capability enforced")
	config.model_capabilities.can_use_json = true
	check(settings.save("text-purpose",config).ok,"valid config saved locally")
	check(settings.enabled_types()==["text-purpose"],"only enabled valid types advertised")
	var copy: Dictionary = settings.copy_config(config,"vision-purpose")
	check(copy.model_kind == "vlm" and settings.validate("vision-purpose",copy).ok,"copy preserves target kind")
	copy.params = {"stream":true}
	check(not settings.validate("vision-purpose",copy).ok,"streaming conflict rejected")
	var recovered = store_script.new(security,directory)
	recovered.set_scope(scope.server,scope.username)
	check(recovered.read("text-purpose").config.api_key == "SYNTHETIC_KEY","DPAPI key restores across instances")
	for folder in DirAccess.get_directories_at(directory):
		for file in DirAccess.get_files_at(directory.path_join(folder)):
			check(not FileAccess.get_file_as_string(directory.path_join(folder).path_join(file)).contains("SYNTHETIC_KEY"),"key not stored in plaintext")
	recovered.set_scope(scope.server,"other")
	check(not recovered.read("text-purpose").ok,"other account cannot read key")
	var broken = store_script.new(BrokenSecurity.new(),directory)
	broken.set_scope(scope.server,"broken")
	check(broken.save("text-purpose",config).code == "PLAINTEXT_CONFIRMATION_REQUIRED","protection failure requires explicit plaintext choice")
	check(not broken.read("text-purpose").ok,"default cancellation does not save key")
	check(broken.save("text-purpose",config,true).ok,"explicit plaintext choice allowed")
	var malformed := config.duplicate(true)
	malformed.model_capabilities = "broken-local-file"
	check(store.save("vision-purpose",malformed).ok,"fixture writes malformed stored configuration")
	await settings.start(scope)
	check(settings.get_config("vision-purpose").model_capabilities is Dictionary and not settings.get_config("vision-purpose").enabled,"bad persisted configuration safely disabled")
	check(ResourceLoader.exists("res://scenes/ui/model_window.tscn"),"model settings window available")
	if ResourceLoader.exists("res://scenes/ui/model_window.tscn"):
		var window = load("res://scenes/ui/model_window.tscn").instantiate()
		window.setup(settings)
		root.add_child(window)
		window.open()
		await process_frame
		var model = window.find_child("ModelName",true,false)
		check(model != null,"model form exposed")
		if model != null:
			model.text = "draft-model"
			model.text_changed.emit(model.text)
			check(window.is_dirty(),"model draft participates in close guard")
			window.close_requested.emit()
			await process_frame
			check(is_instance_valid(window),"closing draft awaits confirmation")
		window.queue_free()
		await process_frame
		check(settings.get_types().size()==2,"closing window preserves application settings")
	settings.queue_free()
	await process_frame
	for folder in DirAccess.get_directories_at(directory):
		for file in DirAccess.get_files_at(directory.path_join(folder)):
			DirAccess.remove_absolute(directory.path_join(folder).path_join(file))
		DirAccess.remove_absolute(directory.path_join(folder))
	DirAccess.remove_absolute(directory)
	print("Model settings: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
