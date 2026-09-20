extends SceneTree
const THEME_PATH := "res://theme/app_theme.tres"
# 每个视图场景：根节点名、根节点类型、根脚本、脚本必须暴露的注入方法、必须带 unique_name_in_owner 的节点。
const SCENES := {
	"res://scenes/ui/publish_window.tscn": {
		"root": "PublishWindow",
		"type": "Window",
		"script": "res://src/ui/publish_window.gd",
		"setup": "setup",
		"unique": ["PublishDraft","PublishButton"],
	},
}
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	for path: String in SCENES:
		check_scene(path,SCENES[path])
	print("UI scenes: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func check_scene(path: String,spec: Dictionary) -> void:
	check(ResourceLoader.exists(path),"scene exists: "+path)
	if not ResourceLoader.exists(path):
		return
	var scene: PackedScene = load(path)
	check(scene != null,"scene loads: "+path)
	if scene == null:
		return
	var instance := scene.instantiate()
	check(instance != null,"scene instantiates with no _init arguments: "+path)
	if instance == null:
		return
	check(instance.name == spec["root"],"root node name is %s: %s"%[spec["root"],path])
	check(instance.is_class(spec["type"]),"root node type is %s: %s"%[spec["type"],path])
	var script: Script = instance.get_script()
	check(script != null and script.resource_path == spec["script"],"root script is %s: %s"%[spec["script"],path])
	check(script != null and script.get_script_method_list().any(func(method): return method.name == spec["setup"]),"script exposes %s(): %s"%[spec["setup"],path])
	check(init_argument_count(script) == 0,"script needs no _init arguments: "+path)
	for name in spec["unique"]:
		var owned := find_unique(instance,instance,name)
		check(owned != null,"node %%%s is unique in owner: %s"%[name,path])
		check(instance.get_node_or_null(NodePath("%"+name)) == owned,"%%%s resolves through unique name: %s"%[name,path])
	if instance is Window:
		check(instance.theme == load(THEME_PATH),"window root carries app theme: "+path)
	instance.free()
func init_argument_count(script: Script) -> int:
	if script == null:
		return 0
	for method in script.get_script_method_list():
		if method.name == "_init":
			return method.args.size()
	return 0
func find_unique(owner: Node,scope: Node,name: String) -> Node:
	for node in scope.find_children("*","",true,false):
		if node.name == name and node.unique_name_in_owner and node.owner == owner:
			return node
	return null