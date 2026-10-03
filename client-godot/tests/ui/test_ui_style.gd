extends SceneTree
const Style = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
const Bubble = preload("res://scenes/ui/message_bubble.tscn")
var failures: Array[String] = []

class FailingStore extends Resource:
	var values := {"style":"flat", "icons":"svg", "unrelated":"keep"}
	var fail := true
	var saves := 0
	func load_settings() -> Error: return OK
	func get_value(_section: String, key: String, fallback: Variant = null) -> Variant:
		return values.get(key, fallback)
	func set_value(_section: String, key: String, value: Variant) -> void:
		values[key] = value
	func save_settings() -> Error:
		saves += 1
		return ERR_FILE_CANT_WRITE if fail else OK

func _initialize() -> void: run.call_deferred()
func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)

func message(id: String, own: bool = false) -> Dictionary:
	return {"id":id,"role":"user" if own else "assistant","text":"风格切换保留这条消息","status":"sent","code":""}

func make_bubble(style: RefCounted, own: bool = false) -> Control:
	var bubble := Bubble.instantiate()
	bubble.set_ui_style(style)
	root.add_child(bubble)
	bubble.size = Vector2(600, 100)
	bubble.configure(message("sample", own))
	return bubble

func check_bubble(bubble: Control, style_mode: String) -> void:
	var box: StyleBoxFlat = bubble.get_node("%Bubble").get_theme_stylebox("panel")
	if style_mode == "crystal":
		check(box.corner_radius_top_left == 12, "crystal bubble follows visual style")
		check(box.shadow_size == 8, "crystal bubble follows shadow style")
		check(box.border_width_left == 1, "crystal bubble has luminous border")
	else:
		check(box.corner_radius_top_left == 8, "flat bubble follows visual style")
		check(box.shadow_size == 0, "flat bubble follows shadow style")
	check(box.content_margin_left == 16 and box.content_margin_top == 16, "bubble padding remains unchanged")

func audio_state(status: String) -> Dictionary:
	return {"available":true,"code":"","status":status,"blocked":false,"duration":2.4,"position":0.0,"waveform":PackedFloat32Array([.2,.6,.4])}

func run() -> void:
	root.size = Vector2i(900, 800)
	root.content_scale_size = Vector2i.ZERO
	var path := "user://ui-style-%s.cfg" % Time.get_ticks_usec()
	var store := Store.new(path)
	store.set_value("layout", "ratio", .45)
	check(store.save_settings() == OK, "isolated store created")
	var style := Style.new()
	style.configure(store)
	_check_fresh_configuration_defaults_to_flat_svg(style)
	var notifications: Array[bool] = []
	style.style_changed.connect(func(): notifications.append(true))
	var own := make_bubble(style, true)
	var other := make_bubble(style)
	var source: StyleBoxFlat = own.own_style
	var chat = load("res://scenes/ui/chat_view.tscn").instantiate()
	chat.set_ui_style(style)
	root.add_child(chat)
	chat.size = Vector2(620, 600)
	chat.get_node("%Input").text = "未发送草稿"
	var scroll = chat.get_node("%Scroll")
	var messages: Array[Dictionary] = []
	for index in 80: messages.append(message(str(index), index % 2 == 0))
	scroll.set_messages(messages)
	await _check_style_combinations(style, notifications, own, other, chat, scroll, path)
	_check_scene_stylebox_asset_is_not_mutated(source)
	check(store.get_value("layout", "ratio") == .45, "unrelated settings survive")
	check(other.get_node("%Avatar").texture.resource_path.ends_with("tianyi_icon.png"), "original Tianyi avatar retained")
	check(style.save_preferences("invalid", "svg") == ERR_INVALID_PARAMETER, "invalid input rejected")
	var original_count := style._icon_registry.size()
	for index in 10: style.register_icon(chat.get_node("%Send"), "action_send")
	check(style._icon_registry.size() <= original_count, "repeated registration does not accumulate entries")
	own.free()
	other.free()
	chat.free()
	_check_freed_controls_are_pruned_safely(style)
	store.set_value("ui", "style", "unknown")
	store.set_value("ui", "icons", 42)
	store.save_settings()
	style.configure(Store.new(path))
	_check_invalid_persisted_values_fall_back(style)
	await check_failed_save()
	DirAccess.remove_absolute(path)
	print("UI style preferences: ", "PASS" if failures.is_empty() else "FAIL: " + str(failures))
	quit(0 if failures.is_empty() else 1)
func check_failed_save() -> void:
	var store := FailingStore.new()
	var style := Style.new()
	style.configure(store)
	var changes: Array[bool] = []
	style.style_changed.connect(func(): changes.append(true))
	var window = load("res://scenes/ui/settings_window.tscn").instantiate()
	window.set_ui_style(style)
	window.setup(null, null)
	root.add_child(window)
	window.open()
	var page = window.get_node("%StylePage")
	page.get_node("%UiStylePresets").activated.emit("crystal")
	page.get_node("%IconStylePresets").activated.emit("emoji")
	check(window.is_dirty() and style.ui_style == "flat", "selection stays a draft until saved")
	window.close_requested.emit()
	check(window.get_node("%UnsavedDialog").visible, "local appearance drafts guard close")
	window.get_node("%UnsavedDialog").get_cancel_button().pressed.emit()
	var result: Dictionary = await window.save_changes()
	check(not result.ok and window.is_dirty(), "failed save retains appearance draft")
	_check_failure_does_not_change_runtime_appearance(style, changes)
	check(store.values == {"style":"flat","icons":"svg","unrelated":"keep"}, "failure restores store values")
	check(window.get_node("%Result").text.contains("本地保存失败"), "window reports local persistence failure")
	check(store.saves == 1, "two settings use one write")
	window.close_requested.emit()
	window.get_node("%UnsavedDialog").get_node("%SaveAndClose").pressed.emit()
	await process_frame
	check(is_instance_valid(window) and window.is_dirty() and store.saves == 2, "failed save-and-close keeps window and draft")
	store.fail = false
	result = await window.save_changes()
	check(result.ok and not window.is_dirty() and changes.size() == 1, "retry saves both settings and clears draft")
	check(store.saves == 3 and style.ui_style == "crystal" and style.icon_style == "emoji", "retry applies the retained selection")
	page.get_node("%UiStylePresets").activated.emit("flat")
	window.close_requested.emit()
	window.get_node("%UnsavedDialog").get_node("%SaveAndClose").pressed.emit()
	await process_frame
	check(not is_instance_valid(window) and style.ui_style == "flat", "successful save-and-close applies appearance and closes")
	check(style.save_preferences("flat", "svg") == OK, "restore flat shared theme after verification")
func _check_restart_restores_both_preferences(restored: Variant, pair: Variant) -> void:
	check(restored.ui_style == pair[0] and restored.icon_style == pair[1], "restart restores both preferences")

func _check_fresh_configuration_defaults_to_flat_svg(style: Variant) -> void:
	check(style.ui_style == "flat" and style.icon_style == "svg", "fresh configuration defaults to flat/svg")

func _check_scene_stylebox_asset_is_not_mutated(source: Variant) -> void:
	check(source.corner_radius_top_left == 8 and source.shadow_size == 0, "scene stylebox asset is not mutated")

func _check_freed_controls_are_pruned_safely(style: Variant) -> void:
	check(style.save_preferences("crystal", "emoji") == OK and style._icon_registry.is_empty(), "freed controls are pruned safely")

func _check_invalid_persisted_values_fall_back(style: Variant) -> void:
	check(style.ui_style == "flat" and style.icon_style == "svg", "invalid persisted values fall back")

func _check_failure_does_not_change_runtime_appearance(style: Variant, changes: Variant) -> void:
	check(style.ui_style == "flat" and style.icon_style == "svg" and changes.is_empty(), "failure does not change runtime appearance")

func _check_style_combinations(style: Variant, notifications: Array, own: Variant, other: Variant, chat: Variant, scroll: Variant, path: String) -> void:
	for pair in [["flat","svg"],["flat","emoji"],["crystal","svg"],["crystal","emoji"],["flat","svg"]]:
		var changed: bool = style.ui_style != pair[0] or style.icon_style != pair[1]
		var before := notifications.size()
		check(style.save_preferences(pair[0], pair[1]) == OK, "save combination: " + str(pair))
		check(notifications.size() == before + int(changed), "one notification per successful change")
		check_bubble(own, pair[0])
		check_bubble(other, pair[0])
		var fresh := make_bubble(style)
		check_bubble(fresh, pair[0])
		fresh.queue_free()
		check(chat.get_node("%Input").text == "未发送草稿", "switching preserves chat draft")
		var suffix: String = "_emoji.png" if pair[1] == "emoji" else ".svg"
		check(chat.get_node("%Send").icon.resource_path.ends_with("action_send" + suffix), "chat icon switches")
		check(chat.get_node("%Send").get_theme_constant("icon_max_width") == 20, "both icon formats use a fixed display size")
		for status in ["playing", "paused", "idle"]:
			own.set_audio_state(audio_state(status))
			var audio = own.find_child("MessageAudio", true, false)
			var icon_name := "media_pause" if status == "playing" else "media_play"
			check(audio.get_node("%Play").icon.resource_path.ends_with(icon_name + suffix), "audio action icon tracks playback state")
		check(scroll.scroll_to_message("0"), "virtual list scrolls to older messages")
		for frame in 4: await process_frame
		for bubble in scroll.get_node("%Canvas").get_children(): check_bubble(bubble, pair[0])
		scroll.scroll_to_latest()
		for frame in 4: await process_frame
		for bubble in scroll.get_node("%Canvas").get_children(): check_bubble(bubble, pair[0])
		var restored := Style.new()
		restored.configure(Store.new(path))
		_check_restart_restores_both_preferences(restored, pair)
