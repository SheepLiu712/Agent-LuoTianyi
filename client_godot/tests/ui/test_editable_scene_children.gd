extends SceneTree
var failures: Array[String] = []

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	for entry in [
		["preferences_page", ["RelationshipPresets", "SpeakingStylePresets"]],
		["model_page", ["SelectorSlot", "CopySlot"]],
	]:
		var window: Node = load("res://scenes/ui/" + entry[0] + ".tscn").instantiate()
		for name in entry[1]:
			var dropdown := window.get_node_or_null("%" + name)
			check(dropdown is Button and dropdown.scene_file_path == "res://scenes/ui/unified_dropdown.tscn", "editable dropdown before ready: " + name)
		root.add_child(window)
		window.queue_free()
		await process_frame
	var app: Node = load("res://scenes/main.tscn").instantiate()
	var error := app.get_node_or_null("%SecurityError")
	check(error is Label and not error.visible and error.text == "凭据保护组件缺失，请重新解压完整程序。", "component error text is authored in main scene")
	app.free()
	check(ResourceLoader.exists("res://scenes/ui/dropdown_separator.tscn"), "dropdown separator is a reusable scene")
	var theme: Theme = load("res://theme/app_theme.tres")
	check(theme.has_stylebox("normal", "DynamicsPost") and theme.has_stylebox("selected", "DynamicsPost"), "dynamic selection styles are editable resources")
	print("Editable scene children: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
