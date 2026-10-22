extends RefCounted
signal changed
var _messages: Array[Dictionary] = []
var _scenario := "empty"
var _next_id := 0

func select_scenario(name: String) -> bool:
	if name not in ["conversation", "empty", "disconnected", "error", "thinking"]:
		return false
	_scenario = name
	_messages.clear()
	if name in ["conversation", "thinking"]:
		_messages = [
			{"id":"fixture-1", "role":"system", "text":"今天  14:32 · 以下为界面演示内容", "status":"received"},
			{"id":"fixture-2", "role":"assistant", "text":"你回来啦。今天过得怎么样？", "status":"received"},
			{"id":"fixture-3", "role":"user", "text":"终于忙完了，想在这里休息一会儿。", "status":"sent"},
			{"id":"fixture-4", "role":"assistant", "text":"那就慢慢来吧，不用急着说些什么。\n我在这里，陪你把今天的心情一点点放下来。", "status":"received"},
			{"id":"fixture-5", "role":"user", "text":"给你看看今天的小角落。", "status":"sent", "image":"res://assets/ui/bg2.jpg"},
			{"id":"fixture-6", "role":"user", "text":"这条用来看看发送中的样子。", "status":"sending"},
			{"id":"fixture-7", "role":"user", "text":"这条是发送失败的示例，文字仍然保留。", "status":"failed"},
		]
	changed.emit()
	return true

func get_messages() -> Array[Dictionary]:
	return _messages.duplicate(true)

func submit_text(text: String) -> String:
	if text.strip_edges().is_empty() or _scenario in ["disconnected", "error"]:
		return ""
	_next_id += 1
	var id := "local-%s" % _next_id
	_messages.append({"id":id, "role":"user", "text":text, "status":"sending"})
	changed.emit()
	return id

func settle(id: String, success: bool) -> bool:
	for message in _messages:
		if message.id == id and message.status == "sending":
			message.status = "sent" if success else "failed"
			changed.emit()
			return true
	return false
