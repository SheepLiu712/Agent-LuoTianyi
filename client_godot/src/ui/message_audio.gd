extends VBoxContainer
signal action(value: String)
@onready var _row: HBoxContainer = %Row
@onready var _play: Button = %Play
@onready var _wave = %Wave
@onready var _time: Label = %Time
@onready var _stop: Button = %Stop
@onready var _error: Label = %Error
var _status := "idle"

func _ready() -> void:
	_play.pressed.connect(func(): action.emit({"idle":"play","playing":"pause","paused":"resume"}[_status]))
	_stop.pressed.connect(func(): action.emit("stop"))

func update_state(state: Dictionary) -> void:
	visible = state.available or not state.code.is_empty()
	_row.visible = state.available
	_error.visible = not state.code.is_empty()
	_error.text = "语音未能保存" if state.code == "CACHE_WRITE_FAILED" else "语音暂时无法重放"
	_status = state.status
	_play.text = {"idle":"重放","playing":"暂停","paused":"继续"}[_status]
	_play.disabled = state.blocked
	_stop.visible = _status != "idle"
	_time.text = "%.1f 秒" % state.duration if _status == "idle" else "%.1f/%.1f 秒" % [state.position,state.duration]
	_wave.values = state.waveform
	_wave.progress = state.position / state.duration if state.duration > 0 else 0.0
