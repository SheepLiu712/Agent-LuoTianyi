extends VBoxContainer
signal action(value: String)
const ErrorDialog = preload("res://src/ui/error_dialog.gd")

@onready var _row: HBoxContainer = %Row
@onready var _play: Button = %Play
@onready var _wave: HBoxContainer = %Wave
@onready var _time: Label = %Time
@onready var _stop: Button = %Stop
@onready var _error: Label = %Error
var _status := "idle"
var _ui_style: RefCounted
var _last_code := ""


func set_ui_style(style: RefCounted) -> void:
	_ui_style = style
	style.apply_view(self, {"Stop":"media_stop"})
	_update_icon()

func _update_icon() -> void:
	var play := _play if _play != null else get_node_or_null("%Play") as Button
	if _ui_style != null and play != null:
		_ui_style.register_icon(play, "media_pause" if _status == "playing" else "media_play")

func _ready() -> void:
	_play.pressed.connect(func(): action.emit({"idle":"play","playing":"pause","paused":"resume"}[_status]))
	_stop.pressed.connect(func(): action.emit("stop"))
	_update_icon()

func update_state(state: Dictionary) -> void:
	visible = state.available
	_row.visible = state.available
	_error.visible = false
	if not state.available and not state.code.is_empty() and state.code != _last_code:
		_last_code = state.code
		ErrorDialog.present(self, "这条语音无法播放。")
	_status = state.status
	_update_icon()
	_play.text = {"idle":"重放","playing":"暂停","paused":"继续"}[_status]
	_play.disabled = state.blocked
	_stop.visible = _status != "idle"
	_time.text = "%.1f 秒" % state.duration if _status == "idle" else "%.1f/%.1f 秒" % [state.position,state.duration]
	_wave.values = state.waveform
	_wave.progress = state.position / state.duration if state.duration > 0 else 0.0
