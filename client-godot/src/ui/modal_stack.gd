extends RefCounted
## 同一父窗口只允许一个 exclusive child；后开的模态降级为非 exclusive，
## 避免 Godot 直接拒绝 setter 并让弹窗完全不可用。

static func activate(window: Window) -> void:
	if window == null or not window.visible:
		return
	var parent := window.get_parent()
	if parent == null:
		return
	var host := parent.get_window()
	if host == null:
		return
	window.exclusive = false
	if _has_exclusive_child(host, window):
		return
	window.exclusive = true


static func _has_exclusive_child(node: Node, ignore: Window) -> bool:
	for child in node.get_children():
		if child is Window:
			if child != ignore and child.visible and child.exclusive:
				return true
			continue
		if _has_exclusive_child(child, ignore):
			return true
	return false
