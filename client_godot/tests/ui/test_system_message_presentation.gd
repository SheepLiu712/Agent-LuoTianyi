extends SceneTree

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var bubble = load("res://scenes/ui/message_bubble.tscn").instantiate()
	root.add_child(bubble)
	bubble.configure({"id":"notice", "role":"system", "text":"连接已恢复", "status":"received"})
	await process_frame
	var visible: Array[Node] = []
	for child in bubble.get_children():
		if child is Control and child.is_visible_in_tree():
			visible.append(child)
	var passed := visible.size() == 1 and visible[0] is Label
	if passed:
		passed = visible[0].text == "连接已恢复" and visible[0].horizontal_alignment == HORIZONTAL_ALIGNMENT_CENTER
	print("System message only shows centered text: ", "PASS" if passed else "FAIL")
	bubble.queue_free()
	await process_frame
	quit(0 if passed else 1)
