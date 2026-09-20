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
	"res://scenes/ui/preferences_page.tscn": {
		"root": "PreferencesPage",
		"type": "Control",
		"script": "res://src/ui/preferences_page.gd",
		"setup": "setup",
		"unique": ["RelationshipField","RelationshipPresets","SpeakingStyleField","SpeakingStylePresets","PersonalityField","CustomContextField","Status","Reload"],
		"properties": {
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
		},
	},
	"res://scenes/ui/model_page.tscn": {
		"root": "ModelPage",
		"type": "Control",
		"script": "res://src/ui/model_page.gd",
		"setup": "setup",
		"unique": ["SelectorSlot","Requirements","Enabled","provider","base_url","api_key","ModelName","Json","Thinking","Params","CopySlot","CopyButton","TestButton","Status","PlainDialog","TestDialog"],
		"properties": {
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
			"Margin/Scroll/Column/TestButton": {"text": "手动测试当前配置","visible": false},
			"Margin/Scroll/Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"PlainDialog": {"title": "密钥保护失败","dialog_text": "Windows 未能保护 API Key。是否明确选择在本机以明文保存？默认取消保存。","ok_button_text": "明文保存","cancel_button_text": "取消保存"},
			"TestDialog": {"title": "测试可能消耗供应商额度","dialog_text": "将使用当前草稿发送一次固定短输入，不发送聊天历史。成功仅表示本次请求可用。","cancel_button_text": "取消"},
		},
	},
	"res://scenes/ui/account_view.tscn": {
		"root": "AccountForm",
		"type": "PanelContainer",
		"script": "res://src/ui/account_view.gd",
		"setup": "setup",
		"unique": ["Form","AccountMode","Server","Username","Password","Confirm","Invite","Remember","Submit","Cancel","Identity","Logout","Status","Logs"],
		"properties": {
			"Column": {"theme_override_constants/separation": 14},
			"Column/Title": {"text": "和天依再见面","theme_override_font_sizes/font_size": 25,"theme_override_colors/font_color": Color("344c59")},
			"Column/Subtitle": {"text": "登录你的账户，继续这段陪伴。","theme_override_font_sizes/font_size": 13,"theme_override_colors/font_color": Color("809ba7")},
			"Column/Form": {"theme_override_constants/separation": 10},
			"Column/Form/AccountMode": {"custom_minimum_size": Vector2(140,40),"alignment": HORIZONTAL_ALIGNMENT_LEFT,"clip_text": true},
			"Column/Form/Server": {"placeholder_text": "服务器地址","tooltip_text": "例如 https://你的服务器地址；本地联调可使用 http://127.0.0.1:端口","custom_minimum_size": Vector2(0,40)},
			"Column/Form/Username": {"placeholder_text": "用户名","tooltip_text": "用户名","secret": false},
			"Column/Form/Password": {"placeholder_text": "密码","secret": true},
			"Column/Form/Confirm": {"placeholder_text": "确认密码","secret": true,"visible": false},
			"Column/Form/Invite": {"placeholder_text": "邀请码","secret": true,"visible": false},
			"Column/Form/Remember": {"text": "下次自动登录"},
			"Column/Form/Submit": {"text": "登录","theme_type_variation": &"PrimaryButton","custom_minimum_size": Vector2(0,42)},
			"Column/Cancel": {"text": "取消请求","visible": false},
			"Column/Identity": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"visible": false},
			"Column/Logout": {"text": "退出登录","visible": false},
			"Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_font_sizes/font_size": 13,"theme_override_colors/font_color": Color("607f8d")},
			"Column/Logs": {"text": "打开日志"},
		},
		"styleboxes": {
			"": {"panel": [Color("ffffff"),18,28]},
			"Column/Form/Password": {"normal": [Color("f0f5f7"),8,10]},
		},
	},
	"res://scenes/main.tscn": {
		"root": "AgentLuo",
		"type": "Control",
		"script": "res://src/application.gd",
		"setup": "setup",
		"inject_layout": true,
		"unique": ["Split","Center","AccountForm","LogProblem","ExitDialog"],
		"properties": {
			"Split": {"dragger_visibility": SplitContainer.DRAGGER_HIDDEN_COLLAPSED},
			"Split/Center": {"custom_minimum_size": Vector2(440,0),"size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Split/Center/AccountForm": {"custom_minimum_size": Vector2(390,0)},
			"LogProblem": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_colors/font_color": Color("b72a2a")},
			"ExitDialog": {"title": "放弃未保存的内容？","dialog_text": "设置或动态窗口中有未保存的内容，确认放弃并继续？","ok_button_text": "放弃并继续","cancel_button_text": "取消"},
		},
	},
	"res://scenes/ui/unified_dropdown.tscn": {
		"root": "UnifiedDropdown",
		"type": "Button",
		"script": "res://src/ui/unified_dropdown.gd",
		"setup": "",
		"unique": ["Menu","Scroll","Rows"],
		"properties": {
			"": {"custom_minimum_size": Vector2(140,40),"alignment": HORIZONTAL_ALIGNMENT_LEFT,"clip_text": true},
			"Menu": {"visible": false,"force_native": true},
			"Menu/Scroll": {"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED},
			"Menu/Scroll/Rows": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/separation": 0},
		},
		"styleboxes": {"Menu": {"panel": [Color("ffffff"),10,6]}},
	},
	"res://scenes/ui/dropdown_item.tscn": {
		"root": "DropdownItem",
		"type": "Button",
		"script": "res://src/ui/dropdown_item.gd",
		"setup": "setup",
		"unique": [],
		"properties": {
			"": {"custom_minimum_size": Vector2(0,42),"alignment": HORIZONTAL_ALIGNMENT_LEFT,"theme_override_colors/font_color": Color("353c43")},
		},
		"styleboxes": {"": {"normal": [Color("ffffff"),6,12],"hover": [Color("f0f2f4"),6,12]}},
	},
	"res://scenes/ui/log_window.tscn": {
		"root": "LogWindow",
		"type": "Window",
		"script": "res://src/ui/log_window.gd",
		"setup": "setup",
		"unique": ["RunsDropdown","LevelDropdown","ModuleDropdown","Search","Text","Follow","CopyButton","ExportButton","Status","Picker"],
		"properties": {
			"": {"size": Vector2i(960,620),"min_size": Vector2i(660,400),"visible": false,"transient": false},
			"Panel/Column/Filters/RunsDropdown": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Panel/Column/Search": {"placeholder_text": "搜索时间、活动或错误码"},
			"Panel/Column/Text": {"selection_enabled": true,"size_flags_vertical": Control.SIZE_EXPAND_FILL,"theme_override_colors/default_color": Color("d6e5ee"),"theme_override_font_sizes/normal_font_size": 14},
			"Panel/Column/Actions/Follow": {"text": "跟随最新","button_pressed": true,"theme_override_colors/font_color": Color("d6e5ee")},
			"Panel/Column/Actions/CopyButton": {"text": "复制显示记录"},
			"Panel/Column/Actions/ExportButton": {"text": "导出完整诊断 ZIP"},
			"Panel/Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_colors/font_color": Color("ffd58a")},
			"Picker": {"file_mode": FileDialog.FILE_MODE_SAVE_FILE,"access": FileDialog.ACCESS_FILESYSTEM,"use_native_dialog": true},
		},
		"styleboxes": {"Panel": {"panel": [Color("111923"),0,14]}},
	},
	"res://scenes/ui/message_audio.tscn": {
		"root": "MessageAudio",
		"type": "VBoxContainer",
		"script": "res://src/ui/message_audio.gd",
		"setup": "",
		"unique": ["Row","Play","Wave","Time","Stop","Error"],
		"properties": {
			"Row": {"theme_override_constants/separation": 6},
			"Row/Play": {"theme_override_font_sizes/font_size": 12},
			"Row/Wave": {"custom_minimum_size": Vector2(96,26),"mouse_filter": Control.MOUSE_FILTER_IGNORE,"played_color": Color("66ccff"),"remaining_color": Color("9eb6c4")},
			"Row/Time": {"theme_override_font_sizes/font_size": 11,"theme_override_colors/font_color": Color("304553")},
			"Row/Stop": {"text": "停止","theme_override_font_sizes/font_size": 12},
			"Error": {"text": "语音未能保存","theme_override_font_sizes/font_size": 12},
		},
	},
	"res://scenes/ui/message_bubble.tscn": {
		"root": "MessageBubble",
		"type": "HBoxContainer",
		"script": "res://src/preview/message_bubble.gd",
		"setup": "",
		"unique": ["System","Avatar","Body","Bubble","Content","Text","HistoryPicture","ImageButton","Picture","Caption"],
		"properties": {
			"": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/separation": 10},
			"System": {"visible": false,"horizontal_alignment": HORIZONTAL_ALIGNMENT_CENTER,"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_font_sizes/font_size": 12,"theme_override_colors/font_color": Color("8a9ba4")},
			"Avatar": {"custom_minimum_size": Vector2(38,38),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_vertical": Control.SIZE_SHRINK_BEGIN},
			"Body": {"theme_override_constants/separation": 5},
			"Body/Bubble/Content/Text": {"fit_content": true,"selection_enabled": true,"scroll_active": false,"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"Body/Bubble/Content/HistoryPicture": {"visible": false,"custom_minimum_size": Vector2(0,135),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED},
			"Body/Bubble/Content/ImageButton": {"visible": false,"text": "加载图片…"},
			"Body/Bubble/Content/Picture": {"visible": false,"custom_minimum_size": Vector2(0,135),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"mouse_default_cursor_shape": Control.CURSOR_POINTING_HAND},
			"Body/Caption": {"visible": false,"horizontal_alignment": HORIZONTAL_ALIGNMENT_RIGHT,"theme_override_font_sizes/font_size": 11},
		},
		"styleboxes": {"Body/Bubble": {"panel": [Color("ffffff"),12,13]}},
	},
	"res://scenes/ui/virtual_message_list.tscn": {
		"root": "VirtualMessageList",
		"type": "ScrollContainer",
		"script": "res://src/ui/virtual_message_list.gd",
		"setup": "",
		"unique": ["Canvas"],
		"properties": {
			"": {"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED},
			"Canvas": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL},
		},
	},
	"res://scenes/ui/chat_view.tscn": {
		"root": "ChatView",
		"type": "MarginContainer",
		"script": "res://src/ui/chat_view.gd",
		"setup": "setup",
		"unique": ["Margin","Dynamics","ChatMore","Status","HistoryStatus","HistoryRetry","HistorySkip","Scroll","Empty","Latest","Unread","Volume","StopVoice","Input","Send","ClearDialog"],
		"properties": {
			"Background": {"color": Color("f5f8fb"),"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Margin": {"theme_override_constants/margin_left": 22,"theme_override_constants/margin_right": 22,"theme_override_constants/margin_top": 22,"theme_override_constants/margin_bottom": 22},
			"Margin/Column": {"theme_override_constants/separation": 12},
			"Margin/Column/Heading": {"theme_override_constants/separation": 12},
			"Margin/Column/Heading/Avatar": {"custom_minimum_size": Vector2(42,42),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_vertical": Control.SIZE_SHRINK_BEGIN},
			"Margin/Column/Heading/Identity": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Margin/Column/Heading/Identity/Title": {"text": "和天依聊聊","theme_override_font_sizes/font_size": 22,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/Heading/Identity/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_font_sizes/font_size": 13,"theme_override_colors/font_color": Color("607f8d")},
			"Margin/Column/Heading/Dynamics": {"text": "动态"},
			"Margin/Column/HistoryRow/HistoryStatus": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_font_sizes/font_size": 12},
			"Margin/Column/HistoryRow/HistoryRetry": {"text": "重试历史"},
			"Margin/Column/HistoryRow/HistorySkip": {"text": "跳过本次"},
			"Margin/Column/Scroll": {"size_flags_vertical": Control.SIZE_EXPAND_FILL,"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED},
			"Margin/Column/Empty": {"text": "从一句问候开始","horizontal_alignment": HORIZONTAL_ALIGNMENT_CENTER},
			"Margin/Column/Latest": {"text": "回到最新 ↓","visible": false},
			"Margin/Column/Unread": {"text": "定位未读","visible": false},
			"Margin/Column/AudioControls/VolumeLabel": {"text": "语音音量","theme_override_font_sizes/font_size": 12,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/AudioControls/Volume": {"min_value": 0.0,"max_value": 1.0,"step": 0.01,"custom_minimum_size": Vector2(110,0),"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"tooltip_text": "回复语音自动播放；拖到最左侧静音"},
			"Margin/Column/AudioControls/StopVoice": {"text": "停止语音"},
			"Margin/Column/Input": {"custom_minimum_size": Vector2(0,92),"placeholder_text": "想说些什么？","wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Column/Footer/Hint": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"text": "Enter 发送 · Shift + Enter 换行","theme_override_font_sizes/font_size": 11,"theme_override_colors/font_color": Color("94a5af")},
			"Margin/Column/Footer/Send": {"custom_minimum_size": Vector2(96,0),"theme_type_variation": &"PrimaryButton","text": "发送  ↑"},
			"ClearDialog": {"title": "清理语音缓存","dialog_text": "清理当前服务器、本账号保存的全部语音？\n聊天文字保留；已清理的语音将无法重放。","ok_button_text": "清理","cancel_button_text": "取消","visible": false},
		},
	},
	"res://scenes/preview/image_overlay.tscn": {
		"root": "ImageOverlay",
		"type": "PanelContainer",
		"script": "res://src/preview/image_overlay.gd",
		"setup": "setup",
		"unique": ["Title","ZoomOut","ZoomIn","Close","Scroll","Picture","Feedback","Confirm"],
		"properties": {
			"Column": {"theme_override_constants/separation": 12},
			"Column/Bar/Title": {"theme_override_font_sizes/font_size": 19,"theme_override_colors/font_color": Color("344c59")},
			"Column/Bar/ZoomOut": {"text": "－"},
			"Column/Bar/ZoomIn": {"text": "＋"},
			"Column/Bar/Close": {"text": "关闭"},
			"Column/Scroll": {"size_flags_vertical": Control.SIZE_EXPAND_FILL},
			"Column/Scroll/Picture": {"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"size_flags_vertical": Control.SIZE_EXPAND_FILL},
			"Column/Feedback": {"visible": false,"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
			"Column/Confirm": {"visible": false,"text": "发送图片 · 离线演示"},
		},
		"styleboxes": {"": {"panel": [Color("f7fafc"),16,20]}},
	},
	"res://scenes/ui/dynamics_window.tscn": {
		"root": "DynamicsWindow",
		"type": "Window",
		"script": "res://src/ui/dynamics_window.gd",
		"setup": "setup",
		"unique": ["Unread","Publish","Refresh","ReadAll","Notice","Split","ListScroll","List","More","Right","Empty"],
		"properties": {
			"": {"title": "天依的动态","size": Vector2i(1000,780),"min_size": Vector2i(900,640),"visible": false,"transient": false,"force_native": true},
			"Panel/Column": {"theme_override_constants/separation": 12},
			"Panel/Column/Toolbar/Unread": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_font_sizes/font_size": 20},
			"Panel/Column/Toolbar/Publish": {"text": "发布动态"},
			"Panel/Column/Toolbar/Refresh": {"text": "刷新"},
			"Panel/Column/Toolbar/ReadAll": {"text": "全部已读"},
			"Panel/Column/Notice": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"theme_override_font_sizes/font_size": 12},
			"Panel/Column/Split": {"size_flags_vertical": Control.SIZE_EXPAND_FILL},
			"Panel/Column/Split/Left": {"custom_minimum_size": Vector2(270,0)},
			"Panel/Column/Split/Left/ListScroll": {"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED,"size_flags_vertical": Control.SIZE_EXPAND_FILL},
			"Panel/Column/Split/Left/ListScroll/List": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/separation": 5},
			"Panel/Column/Split/Right": {"custom_minimum_size": Vector2(330,0)},
			"Panel/Column/Split/Right/Empty": {"text": "选择一条动态","horizontal_alignment": HORIZONTAL_ALIGNMENT_CENTER,"vertical_alignment": VERTICAL_ALIGNMENT_CENTER},
		},
		"styleboxes": {"Panel": {"panel": [Color("f5f8fb"),0,16]},"Panel/Column/Split/Right": {"panel": [Color("ffffff"),12,0]}},
	},
	"res://scenes/ui/dynamics_post_row.tscn": {
		"root": "DynamicsPostRow",
		"type": "Button",
		"script": "res://src/ui/dynamics_post_row.gd",
		"setup": "setup",
		"unique": ["Avatar","Author","Meta","Excerpt"],
		"properties": {
			"": {"custom_minimum_size": Vector2(0,102),"clip_contents": true},
			"Content": {"mouse_filter": Control.MOUSE_FILTER_IGNORE,"offset_left": 14.0,"offset_top": 14.0,"offset_right": -14.0,"offset_bottom": -10.0},
			"Content/Avatar": {"custom_minimum_size": Vector2(38,38),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_vertical": Control.SIZE_SHRINK_BEGIN,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Content/Labels": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Content/Labels/Author": {"theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59"),"text_overrun_behavior": TextServer.OVERRUN_TRIM_ELLIPSIS,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Content/Labels/Meta": {"theme_override_font_sizes/font_size": 11,"theme_override_colors/font_color": Color("344c59"),"text_overrun_behavior": TextServer.OVERRUN_TRIM_ELLIPSIS,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Content/Labels/Excerpt": {"theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("344c59"),"text_overrun_behavior": TextServer.OVERRUN_TRIM_ELLIPSIS,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
		},
	},
	"res://scenes/ui/dynamic_comment_row.tscn": {
		"root": "DynamicCommentRow",
		"type": "VBoxContainer",
		"script": "res://src/ui/dynamic_comment_row.gd",
		"setup": "setup",
		"unique": ["Avatar","Author","Body","Time","Reply"],
		"properties": {
			"Line/Avatar": {"custom_minimum_size": Vector2(34,34),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_vertical": Control.SIZE_SHRINK_BEGIN},
			"Line/Content": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL},
			"Line/Content/Author": {"theme_override_font_sizes/font_size": 14,"theme_override_colors/font_color": Color("65717d")},
			"Line/Content/Body": {"fit_content": true,"selection_enabled": true,"scroll_active": false},
			"Line/Content/Footer/Time": {"theme_override_font_sizes/font_size": 12,"theme_override_colors/font_color": Color("94999f")},
			"Line/Content/Footer/Reply": {"flat": true,"text": "回复"},
		},
	},
	"res://scenes/ui/dynamic_detail.tscn": {
		"root": "DynamicDetail",
		"type": "ScrollContainer",
		"script": "res://src/ui/dynamic_detail.gd",
		"setup": "setup",
		"unique": ["Column","Avatar","Author","CreatedAt","Body","Notice","CommentDraft","Send","Comments","ReplyBox","ReplyLabel","ReplyDraft","CancelReply","ReplySend","Status","LoadMore"],
		"properties": {
			"": {"horizontal_scroll_mode": ScrollContainer.SCROLL_MODE_DISABLED,"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"size_flags_vertical": Control.SIZE_EXPAND_FILL},
			"Margin": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/margin_left": 18,"theme_override_constants/margin_right": 18,"theme_override_constants/margin_top": 18,"theme_override_constants/margin_bottom": 18},
			"Margin/Column": {"size_flags_horizontal": Control.SIZE_EXPAND_FILL,"theme_override_constants/separation": 14},
			"Margin/Column/Header/Avatar": {"custom_minimum_size": Vector2(42,42),"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_CENTERED,"size_flags_vertical": Control.SIZE_SHRINK_BEGIN},
			"Margin/Column/Header/Identity/Author": {"theme_override_font_sizes/font_size": 18,"theme_override_colors/font_color": Color("344c59")},
			"Margin/Column/Header/Identity/CreatedAt": {"theme_override_font_sizes/font_size": 12,"theme_override_colors/font_color": Color("94999f")},
			"Margin/Column/Body": {"fit_content": true,"selection_enabled": true,"scroll_active": false},
			"Margin/Column/Notice": {"text": "此动态不可评论。"},
			"Margin/Column/CommentDraft": {"placeholder_text": "写下你的留言…","custom_minimum_size": Vector2(0,90),"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Column/Send": {"text": "发送评论","size_flags_horizontal": Control.SIZE_SHRINK_END,"theme_type_variation": &"PrimaryButton"},
			"Margin/Column/CommentTitle": {"text": "评论 · 仅你与天依可见","theme_override_font_sizes/font_size": 15,"theme_override_colors/font_color": Color("818991")},
			"Margin/Column/Comments": {"theme_override_constants/separation": 16},
			"Margin/Column/ReplyBox": {"visible": false},
			"Margin/Column/ReplyBox/ReplyDraft": {"placeholder_text": "写下回复…","custom_minimum_size": Vector2(0,90),"wrap_mode": TextEdit.LINE_WRAPPING_BOUNDARY},
			"Margin/Column/ReplyBox/Actions/CancelReply": {"text": "取消回复对象"},
			"Margin/Column/ReplyBox/Actions/ReplySend": {"text": "发送回复","theme_type_variation": &"PrimaryButton"},
			"Margin/Column/Status": {"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART},
		},
		"styleboxes": {"Margin/Column/CommentDraft": {"normal": [Color("f5f7fa"),8,12]},"Margin/Column/ReplyBox/ReplyDraft": {"normal": [Color("f5f7fa"),8,12]}},
	},
	"res://scenes/avatar/avatar_panel.tscn": {
		"root": "AvatarPanel",
		"type": "Control",
		"script": "res://src/avatar/avatar_panel.gd",
		"setup": "",
		"unique": ["Driver","Error","Reset"],
		"scripts": {"Driver": "res://src/avatar/avatar_driver.gd"},
		"properties": {
			"": {"clip_contents": true},
			"Background": {
				"expand_mode": TextureRect.EXPAND_IGNORE_SIZE,
				"stretch_mode": TextureRect.STRETCH_KEEP_ASPECT_COVERED,
				"mouse_filter": Control.MOUSE_FILTER_IGNORE,
			},
			"Veil": {"color": Color(0.96,0.98,1.0,0.18),"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Error": {"position": Vector2(20,80),"autowrap_mode": TextServer.AUTOWRAP_WORD_SMART,"mouse_filter": Control.MOUSE_FILTER_IGNORE},
			"Reset": {"text": "重置位置","tooltip_text": "滚轮缩放 · 右键拖动"},
		},
	},
	"res://scenes/avatar/avatar_preview.tscn": {
		"root": "AvatarPreview",
		"type": "Control",
		"script": "res://src/avatar/avatar_preview.gd",
		"setup": "",
		"unique": ["Driver","Error","Reset"],
		"properties": {"": {"clip_contents": true}},
	},
}
var failures: Array[String] = []
var _temp := ""
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	_temp = "user://ui-scenes-test-%s" % Time.get_ticks_usec()
	for path: String in SCENES:
		await check_scene(path,SCENES[path])
	remove_folder(_temp)
	print("UI scenes: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
func remove_folder(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path):
		return
	for folder in DirAccess.get_directories_at(path):
		remove_folder(path.path_join(folder))
	for file in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
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
	if not spec["setup"].is_empty():
		check(script != null and script.get_script_method_list().any(func(method): return method.name == spec["setup"]),"script exposes %s(): %s"%[spec["setup"],path])
	check(init_argument_count(script) == 0,"script needs no _init arguments: "+path)
	for name in spec["unique"]:
		var owned := find_unique(instance,instance,name)
		check(owned != null,"node %%%s is unique in scene owner: %s"%[name,path])
		check(instance.get_node_or_null(NodePath("%"+name)) == owned,"%%%s resolves through unique name: %s"%[name,path])
	for node_path: String in spec.get("scripts",{}):
		var node: Node = instance if node_path.is_empty() else instance.get_node_or_null(NodePath(node_path))
		var child: Script = node.get_script() if node != null else null
		check(child != null and child.resource_path == spec["scripts"][node_path],"node %s script is %s: %s"%[node_path,spec["scripts"][node_path],path])
	if spec.get("inject_layout",false):
		instance.callv(spec["setup"],[null,_temp.path_join("window.cfg")])
	root.add_child(instance)
	await process_frame
	check(instance.theme == load(THEME_PATH),"view root carries app theme: "+path)
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
		var node: Node = instance if node_path.is_empty() else instance.get_node_or_null(NodePath(node_path))
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