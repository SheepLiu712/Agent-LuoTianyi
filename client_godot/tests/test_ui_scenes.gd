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
	"res://scenes/ui/preferences_window.tscn": {
		"root": "PreferencesWindow",
		"type": "Window",
		"script": "res://src/ui/preferences_window.gd",
		"setup": "setup",
		"unique": ["RelationshipField","RelationshipPresets","SpeakingStyleField","SpeakingStylePresets","PersonalityField","CustomContextField","Status","Reload","Save"],
		"properties": {
			"": {"title": "相处模式","size": Vector2i(600,620),"min_size": Vector2i(480,520),"visible": false},
			"Margin": {
				"theme_override_constants/margin_left": 22,
				"theme_override_constants/margin_right": 22,
				"theme_override_constants/margin_top": 22,
				"theme_override_constants/margin_bottom": 22,
			},
			"Margin/Column": {"theme_override_constants/separation": 12},
			"Margin/Column/Title": {"text": "和天依相处的方式","theme_override_font_sizes/font_size": 22,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/RelationshipLabel": {"text": "关系","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/RelationshipRow/RelationshipField": {"placeholder_text": "关系（可自定义）","size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Margin/Column/SpeakingStyleLabel": {"text": "表达风格","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/SpeakingStyleRow/SpeakingStyleField": {"placeholder_text": "表达风格（可自定义）","size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Margin/Column/PersonalityLabel": {"text": "性格关键词","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/PersonalityField": {"placeholder_text": "用逗号、顿号或换行分隔","custom_minimum_size": Vector2(0,80),"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Column/CustomContextLabel": {"text": "补充上下文","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/CustomContextField": {"placeholder_text": "想让天依了解的相处背景","custom_minimum_size": Vector2(0,120),"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"Margin/Column/Actions/Reload": {"text": "重新加载"},
			"Margin/Column/Actions/Save": {"text": "保存相处模式","theme_type_variation": &"PrimaryButton"},
		},
	},
	"res://scenes/ui/model_window.tscn": {
		"root": "ModelWindow",
		"type": "Window",
		"script": "res://src/ui/model_window.gd",
		"setup": "setup",
		"unique": ["SelectorSlot","Requirements","Enabled","provider","base_url","api_key","ModelName","Json","Thinking","Params","CopySlot","CopyButton","SaveButton","TestButton","Status","PlainDialog","TestDialog"],
		"properties": {
			"": {"title": "LLM / VLM 模型设置","size": Vector2i(660,780),"min_size": Vector2i(520,600),"visible": false},
			"Margin/Scroll": {"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED},
			"Margin/Scroll/Column": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/separation": 10},
			"Margin/Scroll/Column/Title": {"text": "每个用途独立配置，保存不会调用供应商","theme_override_font_sizes/font_size": 18,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/Enabled": {"text": "启用此用途的本地模型"},
			"Margin/Scroll/Column/ProviderLabel": {"text": "服务商名称","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/BaseUrlLabel": {"text": "Base URL（例如 https://example.com/v1）","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/ApiKeyLabel": {"text": "API Key","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/api_key": {"secret": true},
			"Margin/Scroll/Column/ModelLabel": {"text": "模型名称","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/Json": {"text": "声明支持 JSON 输出"},
			"Margin/Scroll/Column/Thinking": {"text": "声明支持 thinking"},
			"Margin/Scroll/Column/ParamsLabel": {"text": "高级 JSON 参数（非流式）","theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Scroll/Column/Params": {"custom_minimum_size": Vector2(0,120),"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Scroll/Column/CopyRow/CopyButton": {"text": "复制该用途配置"},
			"Margin/Scroll/Column/SaveButton": {"text": "保存当前用途","theme_type_variation": &"PrimaryButton"},
			"Margin/Scroll/Column/TestButton": {"text": "手动测试当前配置","visible": false},
			"Margin/Scroll/Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"PlainDialog": {"title": "密钥保护失败","dialog_text": "Windows 未能保护 API Key。是否明确选择在本机以明文保存？默认取消保存。","ok_button_text": "明文保存","cancel_button_text": "取消保存"},
			"TestDialog": {"title": "测试可能消耗供应商额度","dialog_text": "将使用当前草稿发送一次固定短输入，不发送聊天历史。成功仅表示本次请求可用。","cancel_button_text": "取消"},
		},
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