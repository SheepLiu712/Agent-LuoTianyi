extends SceneTree
const THEME_PATH := "res://theme/app_theme.tres"
# 每个视图场景：根节点名、根类型、根脚本、脚本暴露的注入方法、必须带
# unique_name_in_owner 的节点、从代码搬到场景后必须保持不变的属性，以及
# 节点上的样式盒（背景色、圆角、内边距）。
const SCENES := {
	"res://scenes/ui/publish_window.tscn": {
		"root": "PublishWindow",
		"type": "Window",
		"script": "res://src/ui/publish_window.gd",
		"setup": "setup",
		"unique": ["PublishDraft","PublishButton"],
		"properties": {
			"": {
				"title": "发布动态",
				"size": Vector2i(520,350),
				"min_size": Vector2i(400,300),
				"visible": false,
				"transient": true,
				"force_native": true,
			},
			"Panel/Column": {"theme_override_constants/separation": 12},
			"Panel/Column/Title": {
				"text": "分享此刻的想法",
				"theme_override_font_sizes/font_size": 20,
				"theme_override_colors/font_color": Color("344c59"),
			},
			"Panel/Column/PublishDraft": {
				"placeholder_text": "想和天依分享些什么？",
				"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY,
				"size_flags_vertical": Control.SIZE_EXPAND_FILL,
			},
			"Panel/Column/PublishStatus": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"Panel/Column/PublishButton": {
				"text": "发布文字动态",
				"theme_type_variation": &"PrimaryButton",
			},
		},
		"styleboxes": {"Panel": {"panel": [Color("f5f8fb"),0,18]}},
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
		await check_scene(path,SCENES[path])
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
		check(owned != null,"node %%%s is unique in scene owner: %s"%[name,path])
		check(instance.get_node_or_null(NodePath("%"+name)) == owned,"%%%s resolves through unique name: %s"%[name,path])
	root.add_child(instance)
	await process_frame
	if instance is Window:
		check(instance.theme == load(THEME_PATH),"window root carries app theme: "+path)
	check_properties(instance,spec.get("properties",{}),path)
	check_styleboxes(instance,spec.get("styleboxes",{}),path)
	instance.queue_free()
	await process_frame
func check_properties(instance: Node,properties: Dictionary,path: String) -> void:
	for node_path: String in properties:
		var node: Node = instance if node_path.is_empty() else instance.get_node_or_null(NodePath(node_path))
		check(node != null,"node exists: %s in %s"%[node_path,path])
		if node == null:
			continue
		for property: String in properties[node_path]:
			var expected: Variant = properties[node_path][property]
			var actual: Variant = node.get(property)
			check(actual == expected,"%s.%s in %s is %s, got %s"%[node_path,property,path,expected,actual])
func check_styleboxes(instance: Node,styleboxes: Dictionary,path: String) -> void:
	for node_path: String in styleboxes:
		var node: Node = instance.get_node_or_null(NodePath(node_path))
		check(node != null,"node exists: %s in %s"%[node_path,path])
		if node == null:
			continue
		for box_name: String in styleboxes[node_path]:
			var expected: Array = styleboxes[node_path][box_name]
			var label := "%s.%s in %s" % [node_path,box_name,path]
			var box: StyleBox = node.get("theme_override_styles/"+box_name)
			check(box is StyleBoxFlat,label+" is a StyleBoxFlat")
			if not (box is StyleBoxFlat):
				continue
			var flat: StyleBoxFlat = box
			check(flat.bg_color == expected[0],label+" background is "+str(expected[0]))
			check(flat.corner_radius_top_left == expected[1] and flat.corner_radius_top_right == expected[1] and flat.corner_radius_bottom_right == expected[1] and flat.corner_radius_bottom_left == expected[1],label+" corner radius is "+str(expected[1]))
			check(flat.content_margin_left == expected[2] and flat.content_margin_right == expected[2] and flat.content_margin_top == expected[2] and flat.content_margin_bottom == expected[2],label+" content margin is "+str(expected[2]))
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