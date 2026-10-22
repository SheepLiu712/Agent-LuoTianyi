extends SceneTree

func _initialize():
	run.call_deferred()

func run():
	root.size = Vector2i(1080, 720)
	
	# Root container
	var root_box = HBoxContainer.new()
	root_box.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root_box.add_theme_constant_override('separation', 0)
	root.add_child(root_box)
	
	# 1. Left Nav Dock (Matching user reference)
	var nav = PanelContainer.new()
	nav.custom_minimum_size = Vector2(58, 0)
	var nav_box = StyleBoxFlat.new()
	nav_box.bg_color = Color(0.945, 0.968, 0.985, 1.0)
	nav_box.border_width_right = 1
	nav_box.border_color = Color(0.88, 0.92, 0.96, 1.0)
	nav.add_theme_stylebox_override('panel', nav_box)
	root_box.add_child(nav)
	
	var nav_col = VBoxContainer.new()
	nav_col.add_theme_constant_override('separation', 18)
	nav.add_child(nav_col)
	
	var top_spacer = Control.new()
	top_spacer.custom_minimum_size = Vector2(0, 12)
	nav_col.add_child(top_spacer)
	
	# Active Item: Chat
	var nav_item1 = HBoxContainer.new()
	nav_item1.custom_minimum_size = Vector2(58, 44)
	nav_item1.add_theme_constant_override('separation', 0)
	
	var active_bar = ColorRect.new()
	active_bar.custom_minimum_size = Vector2(3, 26)
	active_bar.color = Color(0.18, 0.70, 0.98, 1.0)
	active_bar.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	nav_item1.add_child(active_bar)
	
	var chat_card = CenterContainer.new()
	chat_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var chat_pill = PanelContainer.new()
	chat_pill.custom_minimum_size = Vector2(40, 40)
	var chat_pill_box = StyleBoxFlat.new()
	chat_pill_box.bg_color = Color(0.85, 0.92, 0.98, 0.9)
	chat_pill_box.set_corner_radius_all(10)
	chat_pill.add_theme_stylebox_override('panel', chat_pill_box)
	
	var chat_icon = TextureRect.new()
	chat_icon.texture = load('res://assets/ui/icons/nav_chat.svg')
	chat_icon.custom_minimum_size = Vector2(22, 22)
	chat_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	chat_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	chat_pill.add_child(chat_icon)
	chat_card.add_child(chat_pill)
	nav_item1.add_child(chat_card)
	nav_col.add_child(nav_item1)
	
	# Nav item 2: Logs
	var nav_item2 = CenterContainer.new()
	nav_item2.custom_minimum_size = Vector2(58, 40)
	var log_icon = TextureRect.new()
	log_icon.texture = load('res://assets/ui/icons/nav_scroll.svg')
	log_icon.custom_minimum_size = Vector2(22, 22)
	log_icon.modulate = Color(0.65, 0.70, 0.75, 1)
	log_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	log_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	nav_item2.add_child(log_icon)
	nav_col.add_child(nav_item2)
	
	# Nav item 3: Settings
	var nav_item3 = CenterContainer.new()
	nav_item3.custom_minimum_size = Vector2(58, 40)
	var set_icon = TextureRect.new()
	set_icon.texture = load('res://assets/ui/icons/nav_settings.svg')
	set_icon.custom_minimum_size = Vector2(22, 22)
	set_icon.modulate = Color(0.65, 0.70, 0.75, 1)
	set_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	set_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	nav_item3.add_child(set_icon)
	nav_col.add_child(nav_item3)
	
	var nav_sp = Control.new()
	nav_sp.size_flags_vertical = Control.SIZE_EXPAND_FILL
	nav_col.add_child(nav_sp)
	
	# Bottom Edit / Dynamics icon
	var nav_item4 = CenterContainer.new()
	nav_item4.custom_minimum_size = Vector2(58, 50)
	var edit_icon = TextureRect.new()
	edit_icon.texture = load('res://assets/ui/icons/action_edit.svg')
	edit_icon.custom_minimum_size = Vector2(22, 22)
	edit_icon.modulate = Color(0.65, 0.70, 0.75, 1)
	edit_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	edit_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	nav_item4.add_child(edit_icon)
	nav_col.add_child(nav_item4)
	
	# 2. Main Workspace Split (Live2D Area + Chat Stream Area)
	var split = HSplitContainer.new()
	split.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	split.add_theme_constant_override('separation', 0)
	root_box.add_child(split)
	
	# Left Workspace: Live2D Character Area
	var left_side = Control.new()
	left_side.custom_minimum_size = Vector2(400, 0)
	left_side.clip_contents = true
	split.add_child(left_side)
	
	var bg_l2d = TextureRect.new()
	bg_l2d.texture = load('res://assets/ui/bg2.jpg')
	bg_l2d.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg_l2d.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	bg_l2d.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	left_side.add_child(bg_l2d)
	
	# Subtle veil for elegance
	var veil = ColorRect.new()
	veil.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	veil.color = Color(0.96, 0.98, 1.0, 0.12)
	left_side.add_child(veil)
	
	# Live2D Avatar Q-version character (Anchor to bottom center)
	var char_pic = TextureRect.new()
	char_pic.texture = load('res://assets/ui/login_portrait.png')
	char_pic.custom_minimum_size = Vector2(340, 500)
	char_pic.anchor_left = 0.5
	char_pic.anchor_right = 0.5
	char_pic.anchor_top = 1.0
	char_pic.anchor_bottom = 1.0
	char_pic.offset_left = -170
	char_pic.offset_right = 170
	char_pic.offset_top = -520
	char_pic.offset_bottom = 0
	char_pic.grow_horizontal = Control.GROW_DIRECTION_BOTH
	char_pic.grow_vertical = Control.GROW_DIRECTION_BEGIN
	char_pic.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	char_pic.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	left_side.add_child(char_pic)
	
	# Left Header Card / Status Tag
	var l_head = MarginContainer.new()
	l_head.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	l_head.add_theme_constant_override('margin_left', 18)
	l_head.add_theme_constant_override('margin_top', 18)
	
	var l_tag_panel = PanelContainer.new()
	var l_tag_box = StyleBoxFlat.new()
	l_tag_box.bg_color = Color(1, 1, 1, 0.88)
	l_tag_box.border_width_left = 1
	l_tag_box.border_width_top = 1
	l_tag_box.border_width_right = 1
	l_tag_box.border_width_bottom = 1
	l_tag_box.border_color = Color(0.85, 0.91, 0.97, 0.9)
	l_tag_box.set_corner_radius_all(12)
	l_tag_box.content_margin_left = 14
	l_tag_box.content_margin_right = 14
	l_tag_box.content_margin_top = 8
	l_tag_box.content_margin_bottom = 8
	l_tag_panel.add_theme_stylebox_override('panel', l_tag_box)
	
	var l_vbox = VBoxContainer.new()
	var l_name = Label.new()
	l_name.text = '洛天依'
	l_name.add_theme_font_size_override('font_size', 18)
	l_name.add_theme_color_override('font_color', Color(0.18, 0.28, 0.36, 1))
	l_vbox.add_child(l_name)
	
	var l_sub = Label.new()
	l_sub.text = '把平凡的日子，慢慢说给我听。'
	l_sub.add_theme_font_size_override('font_size', 12)
	l_sub.add_theme_color_override('font_color', Color(0.42, 0.52, 0.60, 1))
	l_vbox.add_child(l_sub)
	l_tag_panel.add_child(l_vbox)
	l_head.add_child(l_tag_panel)
	left_side.add_child(l_head)
	
	# Left Reset Position Button
	var reset_btn = Button.new()
	reset_btn.text = '重置位置'
	var r_btn_box = StyleBoxFlat.new()
	r_btn_box.bg_color = Color(1, 1, 1, 0.82)
	r_btn_box.border_width_left = 1
	r_btn_box.border_width_top = 1
	r_btn_box.border_width_right = 1
	r_btn_box.border_width_bottom = 1
	r_btn_box.border_color = Color(0.84, 0.90, 0.96, 0.8)
	r_btn_box.set_corner_radius_all(8)
	r_btn_box.content_margin_left = 10
	r_btn_box.content_margin_right = 10
	r_btn_box.content_margin_top = 5
	r_btn_box.content_margin_bottom = 5
	reset_btn.add_theme_stylebox_override('normal', r_btn_box)
	reset_btn.add_theme_font_size_override('font_size', 12)
	reset_btn.add_theme_color_override('font_color', Color(0.3, 0.4, 0.48, 1))
	reset_btn.anchor_top = 1.0
	reset_btn.anchor_bottom = 1.0
	reset_btn.offset_left = 18
	reset_btn.offset_top = -45
	reset_btn.offset_right = 88
	reset_btn.offset_bottom = -15
	left_side.add_child(reset_btn)
	
	# 3. Right: Chat Workspace (Faithfully matching user image)
	var right_side = PanelContainer.new()
	right_side.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_side.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var r_box = StyleBoxFlat.new()
	r_box.bg_color = Color(0.975, 0.985, 0.995, 1.0)
	r_box.border_width_left = 1
	r_box.border_color = Color(0.89, 0.93, 0.97, 1.0)
	right_side.add_theme_stylebox_override('panel', r_box)
	split.add_child(right_side)
	
	var r_col = VBoxContainer.new()
	r_col.add_theme_constant_override('separation', 0)
	right_side.add_child(r_col)
	
	# Right Header (Title + Connected status)
	var r_header_margin = MarginContainer.new()
	r_header_margin.add_theme_constant_override('margin_left', 28)
	r_header_margin.add_theme_constant_override('margin_right', 28)
	r_header_margin.add_theme_constant_override('margin_top', 18)
	r_header_margin.add_theme_constant_override('margin_bottom', 14)
	
	var r_head_box = VBoxContainer.new()
	r_head_box.add_theme_constant_override('separation', 4)
	
	var h_title = Label.new()
	h_title.text = '和天依聊聊'
	h_title.add_theme_font_size_override('font_size', 20)
	h_title.add_theme_color_override('font_color', Color(0.16, 0.22, 0.28, 1))
	r_head_box.add_child(h_title)
	
	var h_sub = Label.new()
	h_sub.text = '已连接'
	h_sub.add_theme_font_size_override('font_size', 12)
	h_sub.add_theme_color_override('font_color', Color(0.48, 0.58, 0.66, 1))
	r_head_box.add_child(h_sub)
	r_header_margin.add_child(r_head_box)
	r_col.add_child(r_header_margin)
	
	# Header divider
	var sep1 = ColorRect.new()
	sep1.custom_minimum_size = Vector2(0, 1)
	sep1.color = Color(0.89, 0.93, 0.97, 1.0)
	r_col.add_child(sep1)
	
	# Message Scroll Area
	var msg_margin = MarginContainer.new()
	msg_margin.size_flags_vertical = Control.SIZE_EXPAND_FILL
	msg_margin.add_theme_constant_override('margin_left', 28)
	msg_margin.add_theme_constant_override('margin_right', 28)
	msg_margin.add_theme_constant_override('margin_top', 24)
	msg_margin.add_theme_constant_override('margin_bottom', 16)
	
	var msg_list = VBoxContainer.new()
	msg_list.add_theme_constant_override('separation', 20)
	msg_margin.add_child(msg_list)
	r_col.add_child(msg_margin)
	
	# Helper for circle icon avatar (matching reference: microphone for Tianyi, person for user)
	var make_avatar = func(is_assistant: bool):
		var panel = PanelContainer.new()
		panel.custom_minimum_size = Vector2(36, 36)
		panel.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
		var p_box = StyleBoxFlat.new()
		p_box.bg_color = Color(0.92, 0.945, 0.97, 1.0)
		p_box.set_corner_radius_all(18)
		panel.add_theme_stylebox_override('panel', p_box)
		
		var icon_lbl = Label.new()
		icon_lbl.text = '🎤' if is_assistant else '👤'
		icon_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		icon_lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		icon_lbl.add_theme_font_size_override('font_size', 16)
		icon_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		icon_lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		panel.add_child(icon_lbl)
		return panel
	
	# Msg 1: Assistant
	var a1_row = HBoxContainer.new()
	a1_row.add_theme_constant_override('separation', 14)
	a1_row.add_child(make_avatar.call(true))
	
	var a1_content_col = VBoxContainer.new()
	a1_content_col.add_theme_constant_override('separation', 5)
	
	var a1_bubble = PanelContainer.new()
	var a1_box = StyleBoxFlat.new()
	a1_box.bg_color = Color(0.935, 0.96, 0.985, 1.0) # Light subtle off-white/ice
	a1_box.set_corner_radius_all(16)
	a1_box.content_margin_left = 18
	a1_box.content_margin_right = 18
	a1_box.content_margin_top = 12
	a1_box.content_margin_bottom = 12
	a1_bubble.add_theme_stylebox_override('panel', a1_box)
	
	var a1_text = Label.new()
	a1_text.text = '早上好呀！今天天气真不错呢～'
	a1_text.add_theme_font_size_override('font_size', 14)
	a1_text.add_theme_color_override('font_color', Color(0.18, 0.25, 0.32, 1))
	a1_bubble.add_child(a1_text)
	a1_content_col.add_child(a1_bubble)
	
	var a1_time = Label.new()
	a1_time.text = '09:30'
	a1_time.add_theme_font_size_override('font_size', 11)
	a1_time.add_theme_color_override('font_color', Color(0.60, 0.68, 0.74, 1))
	a1_content_col.add_child(a1_time)
	a1_row.add_child(a1_content_col)
	msg_list.add_child(a1_row)
	
	# Msg 2: User
	var u1_row = HBoxContainer.new()
	u1_row.alignment = BoxContainer.ALIGNMENT_END
	u1_row.add_theme_constant_override('separation', 14)
	
	var u1_content_col = VBoxContainer.new()
	u1_content_col.alignment = BoxContainer.ALIGNMENT_END
	u1_content_col.add_theme_constant_override('separation', 5)
	
	var u1_bubble = PanelContainer.new()
	var u1_box = StyleBoxFlat.new()
	u1_box.bg_color = Color(0.33, 0.72, 0.98, 1.0) # Sky blue matching image
	u1_box.set_corner_radius_all(16)
	u1_box.content_margin_left = 18
	u1_box.content_margin_right = 18
	u1_box.content_margin_top = 12
	u1_box.content_margin_bottom = 12
	u1_bubble.add_theme_stylebox_override('panel', u1_box)
	
	var u1_text = Label.new()
	u1_text.text = '早上好！今天确实是个好天气'
	u1_text.add_theme_font_size_override('font_size', 14)
	u1_text.add_theme_color_override('font_color', Color(1, 1, 1, 1))
	u1_bubble.add_child(u1_text)
	u1_content_col.add_child(u1_bubble)
	
	var u1_time = Label.new()
	u1_time.text = '09:31'
	u1_time.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	u1_time.add_theme_font_size_override('font_size', 11)
	u1_time.add_theme_color_override('font_color', Color(0.60, 0.68, 0.74, 1))
	u1_content_col.add_child(u1_time)
	u1_row.add_child(u1_content_col)
	u1_row.add_child(make_avatar.call(false))
	msg_list.add_child(u1_row)
	
	# Msg 3: Assistant
	var a2_row = HBoxContainer.new()
	a2_row.add_theme_constant_override('separation', 14)
	a2_row.add_child(make_avatar.call(true))
	
	var a2_content_col = VBoxContainer.new()
	a2_content_col.add_theme_constant_override('separation', 5)
	
	var a2_bubble = PanelContainer.new()
	a2_bubble.add_theme_stylebox_override('panel', a1_box)
	var a2_text = Label.new()
	a2_text.text = '是呀！要不要一起去散散步？我听说公园里的花都开了呢。'
	a2_text.add_theme_font_size_override('font_size', 14)
	a2_text.add_theme_color_override('font_color', Color(0.18, 0.25, 0.32, 1))
	a2_bubble.add_child(a2_text)
	a2_content_col.add_child(a2_bubble)
	
	var a2_time = Label.new()
	a2_time.text = '09:31'
	a2_time.add_theme_font_size_override('font_size', 11)
	a2_time.add_theme_color_override('font_color', Color(0.60, 0.68, 0.74, 1))
	a2_content_col.add_child(a2_time)
	a2_row.add_child(a2_content_col)
	msg_list.add_child(a2_row)
	
	# Msg 4: User
	var u2_row = HBoxContainer.new()
	u2_row.alignment = BoxContainer.ALIGNMENT_END
	u2_row.add_theme_constant_override('separation', 14)
	
	var u2_content_col = VBoxContainer.new()
	u2_content_col.alignment = BoxContainer.ALIGNMENT_END
	u2_content_col.add_theme_constant_override('separation', 5)
	
	var u2_bubble = PanelContainer.new()
	u2_bubble.add_theme_stylebox_override('panel', u1_box)
	var u2_text = Label.new()
	u2_text.text = '好主意！我正好想出去走走'
	u2_text.add_theme_font_size_override('font_size', 14)
	u2_text.add_theme_color_override('font_color', Color(1, 1, 1, 1))
	u2_bubble.add_child(u2_text)
	u2_content_col.add_child(u2_bubble)
	
	var u2_time = Label.new()
	u2_time.text = '09:32'
	u2_time.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	u2_time.add_theme_font_size_override('font_size', 11)
	u2_time.add_theme_color_override('font_color', Color(0.60, 0.68, 0.74, 1))
	u2_content_col.add_child(u2_time)
	u2_row.add_child(u2_content_col)
	u2_row.add_child(make_avatar.call(false))
	msg_list.add_child(u2_row)
	
	# Bottom Composer (Matching image exactly)
	var sep2 = ColorRect.new()
	sep2.custom_minimum_size = Vector2(0, 1)
	sep2.color = Color(0.89, 0.93, 0.97, 1.0)
	r_col.add_child(sep2)
	
	var comp_margin = MarginContainer.new()
	comp_margin.add_theme_constant_override('margin_left', 28)
	comp_margin.add_theme_constant_override('margin_right', 28)
	comp_margin.add_theme_constant_override('margin_top', 16)
	comp_margin.add_theme_constant_override('margin_bottom', 14)
	
	var comp_box = VBoxContainer.new()
	comp_box.add_theme_constant_override('separation', 10)
	
	# Action toolbar row: Image, Voice, Send icons
	var tool_row = HBoxContainer.new()
	tool_row.add_theme_constant_override('separation', 18)
	
	var icon_pic = TextureRect.new()
	icon_pic.texture = load('res://assets/ui/icons/action_image.svg')
	icon_pic.custom_minimum_size = Vector2(20, 20)
	icon_pic.modulate = Color(0.48, 0.68, 0.82, 1)
	icon_pic.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon_pic.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	tool_row.add_child(icon_pic)
	
	var icon_snd = TextureRect.new()
	icon_snd.texture = load('res://assets/ui/icons/action_voice.svg')
	icon_snd.custom_minimum_size = Vector2(20, 20)
	icon_snd.modulate = Color(0.48, 0.68, 0.82, 1)
	icon_snd.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon_snd.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	tool_row.add_child(icon_snd)
	
	var icon_mail = TextureRect.new()
	icon_mail.texture = load('res://assets/ui/icons/action_send.svg')
	icon_mail.custom_minimum_size = Vector2(20, 20)
	icon_mail.modulate = Color(0.48, 0.68, 0.82, 1)
	icon_mail.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon_mail.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	tool_row.add_child(icon_mail)
	comp_box.add_child(tool_row)
	
	# Input Row: LineEdit + Send Button
	var input_row = HBoxContainer.new()
	input_row.add_theme_constant_override('separation', 12)
	
	var line_input = LineEdit.new()
	line_input.placeholder_text = '输入消息...'
	line_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line_input.custom_minimum_size = Vector2(0, 44)
	var le_box = StyleBoxFlat.new()
	le_box.bg_color = Color(1, 1, 1, 1.0)
	le_box.border_width_left = 1
	le_box.border_width_top = 1
	le_box.border_width_right = 1
	le_box.border_width_bottom = 1
	le_box.border_color = Color(0.85, 0.90, 0.95, 1.0)
	le_box.set_corner_radius_all(10)
	le_box.content_margin_left = 14
	le_box.content_margin_right = 14
	line_input.add_theme_stylebox_override('normal', le_box)
	line_input.add_theme_font_size_override('font_size', 14)
	line_input.add_theme_color_override('font_color', Color(0.2, 0.28, 0.35, 1))
	input_row.add_child(line_input)
	
	var send_btn = Button.new()
	send_btn.text = '➤'
	send_btn.custom_minimum_size = Vector2(52, 44)
	var send_style = StyleBoxFlat.new()
	send_style.bg_color = Color(0.33, 0.72, 0.98, 1.0)
	send_style.set_corner_radius_all(10)
	send_btn.add_theme_stylebox_override('normal', send_style)
	send_btn.add_theme_stylebox_override('hover', send_style)
	send_btn.add_theme_font_size_override('font_size', 18)
	send_btn.add_theme_color_override('font_color', Color(1, 1, 1, 1))
	input_row.add_child(send_btn)
	comp_box.add_child(input_row)
	
	# Hint Row
	var hint = Label.new()
	hint.text = 'Enter 发送 · Shift+Enter 换行'
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	hint.add_theme_font_size_override('font_size', 11)
	hint.add_theme_color_override('font_color', Color(0.58, 0.65, 0.72, 1.0))
	comp_box.add_child(hint)
	
	comp_margin.add_child(comp_box)
	r_col.add_child(comp_margin)
	
	await create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png('res://artifacts/redesign-preview/new_chat_with_live2d.png')
	print('CHAT_WITH_LIVE2D_SAVED')
	quit(0)
