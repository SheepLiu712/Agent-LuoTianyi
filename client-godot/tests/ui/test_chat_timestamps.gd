extends SceneTree

const ChatTime = preload("res://src/ui/chat_time.gd")
const List = preload("res://scenes/ui/virtual_message_list.tscn")
const Style = preload("res://src/application/ui_style.gd")
const Store = preload("res://src/storage/godot_settings_store.gd")
const ARTIFACTS := "res://artifacts/ui-redraw-client"
var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func check(ok: bool, description: String) -> void:
	if not ok:
		failures.append(description)
		print("FAIL: ", description)

func settle() -> void:
	for frame in 12: await process_frame

func message(id: String, timestamp: Variant, role: String = "assistant") -> Dictionary:
	return {"id":id, "role":role, "text":"消息 " + id, "timestamp":timestamp, "status":"received", "code":""}

func run() -> void:
	root.size = Vector2i(1280, 800)
	root.content_scale_size = Vector2i.ZERO
	test_parsing()
	test_gaps()
	await test_virtual_history()
	await test_chat_presentation()
	print("Chat timestamp groups: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func test_parsing() -> void:
	var epoch := float(Time.get_unix_time_from_datetime_string("2026-10-01T01:00:00"))
	var local: float = epoch + Time.get_time_zone_from_system().bias * 60
	check(is_equal_approx(ChatTime.seconds(epoch), local), "Unix seconds use the local display timezone")
	check(is_equal_approx(ChatTime.seconds(epoch * 1000), local), "Unix milliseconds match Unix seconds")
	check(is_equal_approx(ChatTime.seconds(str(epoch)), local), "numeric history strings are accepted")
	check(is_equal_approx(ChatTime.seconds("2026-10-01T01:00:00Z"), local), "UTC ISO time matches the event timestamp")
	check(is_equal_approx(ChatTime.seconds("2026-10-01T09:00:00+08:00"), local), "explicit ISO offset is respected")
	var calendar := float(Time.get_unix_time_from_datetime_string("2026-10-01T09:00:00"))
	check(is_equal_approx(ChatTime.seconds("2026-10-01 09:00:00"), calendar), "server calendar strings preserve wall time")
	check(absf(ChatTime.seconds("2026-10-01 09:00:00.500") - calendar - .5) < .001, "fractional history seconds are preserved")
	check(ChatTime.seconds("2024-02-29 12:00:00") >= 0, "valid leap day is accepted")
	for invalid in [null, true, {}, "", "not a time", "2026-02-29 12:00:00", "2026-13-01 09:00:00", "2026-10-01 24:00:00", "2026-10-01T09:00:00+24:00", -1, INF, NAN]:
		check(ChatTime.seconds(invalid) < 0, "invalid timestamps do not fabricate display time: " + str(invalid))
	check(ChatTime.label(calendar).ends_with("09:00"), "timestamp label has minute precision")

func test_gaps() -> void:
	var messages: Array[Dictionary] = [
		message("first", "2026-10-01 09:00:00"),
		message("short", "2026-10-01 09:04:59", "user"),
		message("notice", "2026-10-01 09:09:58", "system"),
		message("gap", "2026-10-01 09:09:59"),
		message("continuation", "2026-10-01 09:14:58", "user")
	]
	var markers := ChatTime.markers(messages)
	check(markers.keys() == ["first", "gap"], "299 seconds hides a marker; exactly 300 seconds starts a new group; system notices do not reset it")
	var continuous: Array[Dictionary] = []
	for index in 30: continuous.append(message(str(index), 1800000000 + index * 240))
	check(ChatTime.markers(continuous).keys() == ["0"], "two hours of continuous dialogue do not create periodic markers")
	var unknown: Array[Dictionary] = [message("missing", null), message("valid", 1800000000), message("reverse", 1799999999)]
	check(ChatTime.markers(unknown).keys() == ["valid"], "missing and out-of-order times do not create false gaps")
	var interrupted: Array[Dictionary] = [message("first", 1800000000), message("invalid", null), message("next", 1800000060)]
	check(ChatTime.markers(interrupted).keys() == ["first"], "invalid timestamps do not restart a continuous group")
	var reversed: Array[Dictionary] = [message("first", 1800000600), message("reverse", 1800000000), message("next", 1800000660)]
	check(ChatTime.markers(reversed).keys() == ["first"], "out-of-order arrivals do not move the time baseline backwards")
	var fractional: Array[Dictionary] = [message("first", "2026-10-01 09:00:00.900"), message("next", "2026-10-01 09:05:00.100")]
	check(ChatTime.markers(fractional).keys() == ["first"], "a sub-five-minute fractional gap stays continuous")
	var midnight: Array[Dictionary] = [message("before", "2026-09-30 23:58:00"), message("after", "2026-10-01 00:03:00")]
	check(ChatTime.markers(midnight).size() == 2, "five-minute grouping also works across midnight")
	check(messages.size() == 5 and not messages[0].has("time_marker"), "presentation grouping never mutates business messages")

func test_virtual_history() -> void:
	var list = List.instantiate()
	root.add_child(list)
	list.size = Vector2(620, 420)
	var messages: Array[Dictionary] = []
	for index in 1000:
		var timestamp := 1800000000 + index * 240 + (300 if index >= 500 else 0)
		messages.append(message(str(index), timestamp))
	list.set_messages(messages)
	await settle()
	check(list._nodes.size() < 30, "1000 timestamped messages retain bounded virtual nodes")
	check(list.get_visible_ids().has("999"), "initial timestamped history follows latest")
	check(list.scroll_to_message("500"), "timestamp headers do not replace real UUID navigation")
	await settle()
	var anchor: Dictionary = list.get_reading_anchor()
	check(anchor.id == "500", "reading anchor remains a real message UUID")
	var bubble: Control = list._nodes["500"]
	check(bubble.get_node("%TimeMarker").visible, "the first message after a gap owns its visible timestamp")
	check(absf(bubble.get_node("%TimePanel").get_global_rect().get_center().x - bubble.get_global_rect().get_center().x) < 1, "time bubble is centered across the chat viewport")
	var selected: RichTextLabel = bubble.get_node("%Text")
	selected.select_all()
	list.set_messages(messages)
	await settle()
	check(selected.get_selected_text() == selected.text, "a timestamp refresh preserves text selection")
	var older: Array[Dictionary] = [message("older", 1799999940)]
	list.set_messages(older + messages)
	await settle()
	check(not list._time_markers.has("0") and list._time_markers.has("older"), "prepending history re-evaluates the page boundary without duplicate time bubbles")
	check(list.get_reading_anchor().id == anchor.id and absf(list.get_reading_anchor().offset - anchor.offset) < 2, "prepending timestamped history preserves the reading anchor")
	list.size.x = 460
	await settle()
	check(list.get_reading_anchor().id == "500", "resize keeps timestamped history anchored")
	check(list.get_visible_ids().all(func(id): return id.is_valid_int()), "visible IDs contain only actual messages, never timestamp IDs")
	list.queue_free()
	await process_frame

func presentation_messages() -> Array[Dictionary]:
	var day := Time.get_date_string_from_system()
	var samples: Array[Dictionary] = [
		message("first", day + " 09:00:00"),
		message("user", day + " 09:02:00", "user"),
		message("continuous", day + " 09:04:59"),
		message("gap", day + " 09:09:59", "user"),
		message("reply", day + " 09:10:10")
	]
	samples[0].text = "回来啦。今天过得怎么样？"
	samples[1].text = "刚忙完，想和你一起放松一下。"
	samples[2].text = "好呀，我在这里陪着你。连续聊天时，不会重复出现时间提醒。"
	samples[3].text = "休息了一会儿，又想起一件开心的事。"
	samples[4].text = "慢慢说，我在听。相邻消息满五分钟才开始新的时间分组。"
	return samples

func test_chat_presentation() -> void:
	var path := "user://chat-time-%s.cfg" % Time.get_ticks_usec()
	var style := Style.new()
	style.configure(Store.new(path))
	var chat = load("res://scenes/ui/chat_view.tscn").instantiate()
	chat.set_ui_style(style)
	root.add_child(chat)
	chat.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	chat.get_node("%Status").text = "布局验收 · 本地固定消息"
	chat.get_node("%Empty").hide()
	chat.get_node("%Latest").hide()
	chat.get_node("%Unread").hide()
	chat.get_node("%Input").text = "未发送的草稿保留在这里"
	var list = chat.get_node("%Scroll")
	list.set_messages(presentation_messages())
	await settle()
	for dimensions in [Vector2i(1280, 800), Vector2i(960, 640)]:
		root.size = dimensions
		for variant in ["flat", "crystal"]:
			check(style.save_preferences(variant, "svg") == OK, "timestamp theme switches: " + variant)
			await settle()
			check(list.scroll_to_message("first"), "time group can be reviewed from its first message")
			await settle()
			check(chat.get_node("%Input").text == "未发送的草稿保留在这里", "time style switches keep the composer draft")
			check(list._time_markers.keys() == ["first", "gap"], "both themes use exactly the same timestamp groups")
			check(chat.get_node("%Send").is_visible_in_tree(), "time bubbles do not cover the send action")
			await capture("chat-time-%s-%sx%s" % [variant, dimensions.x, dimensions.y])
	chat.queue_free()
	await process_frame
	DirAccess.remove_absolute(path)

func capture(name: String) -> void:
	if DisplayServer.get_name() == "headless": return
	DirAccess.make_dir_recursive_absolute(ARTIFACTS)
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png(ARTIFACTS.path_join(name + ".png")) == OK, "native timestamp capture " + name)
