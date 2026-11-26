extends Node
## 语音播完后把角色表情恢复默认；服务端漏发 normal 或后续回复没有表情时也兜底。

const DEFAULT_EXPRESSION := "normal"
const DEFAULT_DELAY_SECONDS := 1.0

var _apply_default: Callable
var _delay_seconds := DEFAULT_DELAY_SECONDS
var _generation := 0
var _speaking := false
var _pending := false


func setup(apply_default: Callable, delay_seconds: float = DEFAULT_DELAY_SECONDS) -> void:
	_apply_default = apply_default
	_delay_seconds = maxf(0.0, delay_seconds)


## 新表情只登记待复位，真正计时等语音队列空闲后再开始。
func expression_requested() -> void:
	_pending = true
	_generation += 1


func set_speaking(speaking: bool) -> void:
	if speaking:
		_generation += 1
		_speaking = true
		return
	_speaking = false


## 播放器和待播队列都空了，才开始计算语音结束后的延迟。
func voice_idle() -> void:
	if not _speaking and _pending:
		_schedule()


func cancel() -> void:
	_generation += 1
	_speaking = false
	_pending = false


func is_pending() -> bool:
	return _pending


func _schedule() -> void:
	if not is_inside_tree():
		return
	_generation += 1
	var generation := _generation
	var timer := get_tree().create_timer(_delay_seconds, true)
	timer.timeout.connect(func(): _reset(generation), CONNECT_ONE_SHOT)


func _reset(generation: int) -> void:
	if generation != _generation or not _pending or _speaking:
		return
	_pending = false
	if _apply_default.is_valid():
		_apply_default.call(DEFAULT_EXPRESSION)
