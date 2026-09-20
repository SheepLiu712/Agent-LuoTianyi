extends SceneTree

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	# Normal main-scene startup has no caller injecting setup().
	var before := DirAccess.get_files_at("user://logs")
	var app = load("res://scenes/main.tscn").instantiate()
	root.add_child(app)
	await process_frame
	app.queue_free()
	await process_frame
	var archived := false
	for filename in DirAccess.get_files_at("user://logs"):
		if filename not in before:
			if filename.ends_with(".jsonl"):
				var content := FileAccess.get_file_as_string("user://logs/" + filename)
				archived = content.contains("client_started") and content.contains("client_stopped")
			DirAccess.remove_absolute("user://logs/" + filename)
	print("Default startup archives logs in user directory: ", "PASS" if archived else "FAIL")
	quit(0 if archived else 1)
