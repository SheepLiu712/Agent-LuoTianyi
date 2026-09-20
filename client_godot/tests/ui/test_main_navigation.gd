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
	for name in ["NavChat","NavDynamics","NavSettings","NavLogs","AccountMenu"]:
		check(app.get_node_or_null("%"+name) is Button,"navigation is scene-authored: "+name)
	app.free()
	var chat = load("res://scenes/ui/chat_view.tscn").instantiate()
	root.add_child(chat)
	check(chat.has_method("is_dirty"),"chat exposes unsent draft status")
	if chat.has_method("is_dirty"):
		check(not chat.is_dirty(),"empty composer is clean")
		chat.get_node("%Input").text = "未发送草稿"
		check(chat.is_dirty(),"unsent text participates in exit guard")
	check(chat.get_node_or_null("%CacheButton") is Button,"chat cache action remains accessible")
	chat.queue_free()
	await process_frame
	print("Main navigation: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
