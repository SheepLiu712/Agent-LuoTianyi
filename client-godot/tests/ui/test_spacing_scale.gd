extends SceneTree
## 基础刻度 4/8/12/16/24/40；带描边的控件允许再减 2px（6/10/14/20/28），
## 38 为 30px 头像列 + 8px 间隙的对齐偏移。

const ALLOWED := [0, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 38, 40]
const ROOT := "res://scenes"
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _collect(path: String, files: Array[String]) -> void:
	for folder in DirAccess.get_directories_at(path):
		_collect(path.path_join(folder), files)
	for file in DirAccess.get_files_at(path):
		if file.ends_with(".tscn"):
			files.append(path.path_join(file))


func run() -> void:
	var files: Array[String] = []
	_collect(ROOT, files)
	files.sort()
	var pattern := RegEx.new()
	var compiled := pattern.compile("theme_override_constants/(?:separation|h_separation|v_separation|margin_left|margin_top|margin_right|margin_bottom) = ([0-9]+)")
	check(compiled == OK, "spacing regex compiles")
	for path in files:
		var lines := FileAccess.get_file_as_string(path).split("\n")
		for index in lines.size():
			var found := pattern.search(lines[index])
			if found == null:
				continue
			var value := int(found.get_string(1))
			check(value in ALLOWED, "%s:%s uses off-scale spacing %s" % [path, index + 1, value])
	print("Spacing scale: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
