extends SceneTree
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	var app: Node = load("res://scenes/main.tscn").instantiate()
	for name in ["NavChat","NavDynamics","NavSettings","NavLogs"]:
		check(app.get_node_or_null("%"+name) is Button,"navigation is scene-authored: "+name)
	check(app.get_node_or_null("%AccountMenu") == null,"account menu is removed from main navigation")
	for name in ["NavChat","NavDynamics","NavSettings","NavLogs"]:
		check(app.get_node("%"+name).alignment == HORIZONTAL_ALIGNMENT_CENTER,"navigation text is centered: " + name)
		check(app.get_node("%"+name).vertical_icon_alignment == VERTICAL_ALIGNMENT_TOP,"navigation icon is above its label: " + name)
	check(app.get_node("%NavChat").button_pressed,"chat is selected initially")
	check(app.get_node("%Navigation").custom_minimum_size.x == 80,"navigation uses review width")
	check(app.get_node("%DynamicsUnread") != null,"dynamic unread indication remains available")
	for name in ["NavChat", "NavDynamics", "NavSettings"]:
		check(app.get_node("%" + name).custom_minimum_size == Vector2(64, 64), name + " uses a square footprint")
	check(app.get_node("%Navigation").find_children("*", "TextureRect", true, false).is_empty(), "navigation decorative avatars are removed")
	app.free()
	var chat = load("res://scenes/ui/chat_view.tscn").instantiate()
	root.add_child(chat)
	check(chat.has_method("is_dirty"),"chat exposes unsent draft status")
	if chat.has_method("is_dirty"):
		check(not chat.is_dirty(),"empty composer is clean")
		chat.get_node("%Input").text = "未发送草稿"
		check(chat.is_dirty(),"unsent text participates in exit guard")
	check(chat.get_node_or_null("%CacheButton") == null,"cache management has moved to settings")
	check(chat.get_node("%Input").custom_minimum_size.y == 48,"composer starts with a compact input row")
	check(chat.get_node("%Input").get_parent() == chat.get_node("%Send").get_parent(), "send is beside the input")
	check(chat.get_node("%ImageButton").get_parent() == chat.get_node("%VolumeButton").get_parent(), "image and volume share the upper toolbar")
	check(chat.get_node_or_null("%StopVoice") == null, "composer stop voice control is removed")
	for name in ["ImageButton", "VolumeButton", "Send"]:
		check(chat.get_node("%" + name).text.is_empty() and chat.get_node("%" + name).icon != null, name + " is icon-only with original artwork")
	chat.queue_free()
	await process_frame
	print("Main navigation: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
