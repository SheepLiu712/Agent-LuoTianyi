extends RefCounted
## 同一父窗口只允许一个 exclusive child；后开的模态降级为非 exclusive，
## 避免 Godot 直接拒绝 setter 并让弹窗完全不可用。

static func activate(window: Window) -> void:
	if window == null or not window.visible:
		return
	var parent := window.get_parent()
	if parent == null:
		return
	window.exclusive = false
	for child in parent.get_children():
		if child is Window and child != window and child.visible and child.exclusive:
			return
	window.exclusive = true
