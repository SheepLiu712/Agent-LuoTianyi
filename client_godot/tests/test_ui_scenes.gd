extends SceneTree
const THEME_PATH := "res://theme/app_theme.tres"
# Public scene entrypoints; no internal container paths or script implementation snapshots.
const SCENES := {
	"res://scenes/ui/publish_overlay.tscn": {
		"root":"PublishOverlay","type":"Control","setup":"setup","unique":["PublishDraft","PublishButton","PublishStatus","ClosePublish","CancelPublish","DiscardDialog"]
	},
	"res://scenes/ui/preferences_page.tscn": {
		"root":"PreferencesPage","type":"Control","setup":"setup","unique":["RelationshipField","RelationshipPresets","SpeakingStyleField","SpeakingStylePresets","PersonalityField","CustomContextField","Status","Reload"]
	},
	"res://scenes/ui/model_page.tscn": {
		"root":"ModelPage","type":"Control","setup":"setup","unique":["Scroll","Cards","RefreshTypes","Status","PlainDialog","TestDialog"]
	},
	"res://scenes/ui/model_purpose_card.tscn": {
		"root":"ModelPurposeCard","type":"PanelContainer","setup":"setup","unique":["PurposeTitle","Enabled","Requirements","Description","Fields","provider","base_url","api_key","ModelName","Json","Thinking","Params","CopySlot","CopyButton","TestButton","CardStatus"]
	},
	"res://scenes/ui/account_view.tscn": {
		"root":"AccountForm","type":"PanelContainer","setup":"setup","unique":["Form","Server","Username","Password","Confirm","Invite","Remember","AutoLogin","Submit","Cancel","Status","Logs","MenuButton","CloseLogin","RegisterLink","ResetLink","HistoryButton","ServerDialog","SavedLogin","UsePassword"]
	},
	"res://scenes/main.tscn": {
		"root":"AgentLuo","type":"Control","setup":"setup","unique":["Split","Center","AccountForm","LogProblem","ExitDialog"],
		"inject_layout":true
	},
	"res://scenes/ui/unified_dropdown.tscn": {
		"root":"UnifiedDropdown","type":"Button","setup":"","unique":["Menu","Scroll","Rows"]
	},
	"res://scenes/ui/dropdown_item.tscn": {
		"root":"DropdownItem","type":"Button","setup":"setup","unique":[]
	},
	"res://scenes/ui/log_window.tscn": {
		"root":"LogWindow","type":"Window","setup":"setup","unique":["RunsDropdown","LevelDropdown","ModuleDropdown","Search","Text","Follow","CopyButton","ExportButton","Status","Picker"]
	},
	"res://scenes/ui/message_audio.tscn": {
		"root":"MessageAudio","type":"VBoxContainer","setup":"","unique":["Row","Play","Wave","Time","Stop","Error"]
	},
	"res://scenes/ui/message_bubble.tscn": {
		"root":"MessageBubble","type":"HBoxContainer","setup":"","unique":["System","Avatar","Body","Bubble","Content","Text","HistoryPicture","ImageButton","Picture","Caption"]
	},
	"res://scenes/ui/virtual_message_list.tscn": {
		"root":"VirtualMessageList","type":"ScrollContainer","setup":"","unique":["Canvas"]
	},
	"res://scenes/ui/chat_view.tscn": {
		"root":"ChatView","type":"MarginContainer","setup":"setup","unique":["Margin","Status","HistoryStatus","HistoryRetry","HistorySkip","Scroll","Empty","Latest","Unread","Volume","StopVoice","Input","Send"]
	},
	"res://scenes/ui/image_window.tscn": {
		"root":"ImageWindow","type":"Window","setup":"","unique":["ImageScroll","Picture","ImageError","RetryImage","ZoomIn","ZoomOut","FitImage","OriginalSize","CloseImage","ConfirmImage","Chrome"]
	},
	"res://scenes/ui/dynamics_window.tscn": {
		"root":"DynamicsWindow","type":"Window","setup":"setup","unique":["Unread","Publish","Refresh","ReadAll","Notice","Split","ListScroll","List","More","Right","Empty"]
	},
	"res://scenes/ui/dynamics_post_row.tscn": {
		"root":"DynamicsPostRow","type":"Button","setup":"setup","unique":["Avatar","Author","Meta","Excerpt"]
	},
	"res://scenes/ui/dynamic_comment_row.tscn": {
		"root":"DynamicCommentRow","type":"VBoxContainer","setup":"setup","unique":["Avatar","Author","Body","Time","Reply"]
	},
	"res://scenes/ui/dynamic_detail.tscn": {
		"root":"DynamicDetail","type":"ScrollContainer","setup":"setup","unique":["Column","Avatar","Author","CreatedAt","Body","Notice","CommentDraft","Send","Comments","ReplyBox","ReplyLabel","ReplyDraft","CancelReply","ReplySend","Status","LoadMore"]
	},
	"res://scenes/avatar/avatar_panel.tscn": {
		"root":"AvatarPanel","type":"Control","setup":"","unique":["Driver","Error","Reset"]
	},
	"res://scenes/avatar/avatar_preview.tscn": {
		"root":"AvatarPreview","type":"Control","setup":"","unique":["Driver","Error","Reset"]
	},
}
# Semantic requirements stay attached to public controls, independent of nesting.
const PROPERTIES := {
	"account_view": {"%Username":{"secret":false},"%Password":{"secret":true},"%Confirm":{"secret":true},"%Invite":{"secret":true},"%Submit":{"text":"登录"},"%Cancel":{"text":"取消请求"},"%RegisterLink":{"text":"注册账号"},"%ResetLink":{"text":"忘记密码"},"%Logs":{"text":"日志"}},
	"model_purpose_card": {"%api_key":{"secret":true},"%Enabled":{"text":"使用自己的 API Key"}},
	"preferences_page": {"%PersonalityField":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY},"%CustomContextField":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY},"%Reload":{"text":"重新加载"}},
	"log_window": {"%Text":{"selection_enabled":true},"%Picker":{"file_mode":FileDialog.FILE_MODE_SAVE_FILE,"access":FileDialog.ACCESS_FILESYSTEM,"use_native_dialog":true}},
	"message_bubble": {"%Text":{"fit_content":true,"selection_enabled":true,"scroll_active":false,"autowrap_mode":TextServer.AUTOWRAP_WORD_SMART}},
	"chat_view": {"%HistoryRetry":{"text":"重试历史"},"%HistorySkip":{"text":"跳过本次"},"%StopVoice":{"text":"停止语音"},"%Input":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY},"%Send":{"text":"发送  ↑"}},
	"dynamics_window": {"%Publish":{"text":"发布动态"},"%Refresh":{"text":"刷新"},"%ReadAll":{"text":"全部已读"}},
	"dynamic_comment_row": {"%Body":{"selection_enabled":true,"fit_content":true,"scroll_active":false},"%Reply":{"text":"回复"}},
	"dynamic_detail": {"%Body":{"selection_enabled":true,"fit_content":true,"scroll_active":false},"%Notice":{"text":"此动态不可评论。"},"%CommentDraft":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY},"%ReplyDraft":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY},"%CancelReply":{"text":"取消回复对象"},"%Send":{"text":"发送评论"},"%ReplySend":{"text":"发送回复"}},
	"publish_overlay": {"%PublishDraft":{"wrap_mode":TextEdit.LINE_WRAPPING_BOUNDARY}},
	"unified_dropdown": {"%Menu":{"visible":false,"force_native":false,"transparent_bg":true}},
	"main": {"%ExitDialog":{"ok_button_text":"放弃并继续","cancel_button_text":"返回继续编辑"},"%SecurityError":{"visible":false,"text":"凭据保护组件缺失，请重新解压完整程序。"}},
	"message_audio": {"%Stop":{"text":"停止"},"%Error":{"text":"语音未能保存"}},
}
const DROPDOWNS := {"preferences_page":["RelationshipPresets","SpeakingStylePresets"],"model_purpose_card":["CopySlot"]}
const INPUT_HINTS := {
	"account_view":["Server","Username","Password","Confirm","Invite"],
	"preferences_page":["RelationshipField","SpeakingStyleField","PersonalityField","CustomContextField"],
	"publish_overlay":["PublishDraft"], "log_window":["Search"],
	"chat_view":["Input"], "dynamic_detail":["CommentDraft","ReplyDraft"],
}
const TOOL_HINTS := {"account_view":["Server"], "chat_view":["Volume"], "avatar_panel":["Reset"]}
var failures: Array[String] = []
var _temp := ""

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	_temp = "user://ui-scenes-test-%s" % Time.get_ticks_usec()
	for path: String in SCENES:
		await check_scene(path, SCENES[path])
	var separator: PackedScene = load("res://scenes/ui/dropdown_separator.tscn")
	check(separator != null, "dropdown separator scene loads")
	if separator != null:
		var node := separator.instantiate()
		check(node is HSeparator, "dropdown separator is authored in a reusable scene")
		if node != null: node.free()
	remove_folder(_temp)
	print("UI scenes: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func check_scene(path: String, spec: Dictionary) -> void:
	var scene: PackedScene = load(path)
	check(scene != null, "scene loads: " + path)
	if scene == null: return
	var instance := scene.instantiate()
	check(instance != null, "scene instantiates without constructor arguments: " + path)
	if instance == null: return
	check(instance.name == spec.root and instance.is_class(spec.type), "public root name and type: " + path)
	if not spec.setup.is_empty(): check(instance.has_method(spec.setup), "public injection method: " + path)
	# These checks precede add_child/ready: controls must exist in the authored scene.
	for name in spec.unique:
		var control := instance.get_node_or_null("%" + name)
		check(control != null and control.unique_name_in_owner, "authored public control %" + name + ": " + path)
	var kind := path.get_file().get_basename()
	for name in INPUT_HINTS.get(kind, []): check_hint(instance, name, "placeholder_text")
	for name in TOOL_HINTS.get(kind, []): check_hint(instance, name, "tooltip_text")
	for name in DROPDOWNS.get(kind, []):
		var dropdown := instance.get_node_or_null("%" + name)
		check(dropdown is Button and dropdown.scene_file_path == "res://scenes/ui/unified_dropdown.tscn", "editable dropdown before ready: " + name)
	for key: String in PROPERTIES.get(kind, {}):
		var control := instance.get_node_or_null(key)
		check(control != null, "semantic control exists: " + key)
		if control == null: continue
		for property: String in PROPERTIES[kind][key]:
			check(control.get(property) == PROPERTIES[kind][key][property], "semantic property %s.%s: %s" % [kind,key,property])
	if spec.get("inject_layout", false): instance.callv(spec.setup, [null, _temp.path_join("window.cfg")])
	root.add_child(instance)
	await process_frame
	check(instance.theme == load(THEME_PATH), "view uses the shared theme: " + path)
	instance.queue_free()
	await process_frame

func check_hint(instance: Node, name: String, property: String) -> void:
	var control := instance.get_node_or_null("%" + name)
	check(control != null, "hint control exists: %" + name)
	if control != null:
		var hint: Variant = control.get(property)
		check(hint is String and not hint.strip_edges().is_empty(), "input/action remains explained: %" + name)

func remove_folder(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path): return
	for folder in DirAccess.get_directories_at(path): remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
