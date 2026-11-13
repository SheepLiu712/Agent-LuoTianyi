extends RefCounted
## 四域日志的公共 schema：业务领域分类与严重程度解耦。
## 分类只回答「这条日志属于哪个领域」，级别只回答「有多严重」。
## 该文件不持有运行状态，ClientLog 只通过静态函数读取规则。

const CATEGORIES := ["business", "network", "storage", "system"]
const CATEGORY_LABELS := {
	"business": "业务流", "network": "网络通信", "storage": "存储持久化", "system": "系统诊断",
}
const LEVELS := ["DEBUG", "INFO", "WARN", "ERROR"]
const OUTCOMES := ["success", "failure", "cancelled", "denied", "unknown"]
const ORIGINS := ["client", "network", "server", "upstream", "none", "unknown"]
const ORIGIN_LABELS := {
	"client":"客户端", "network":"网络链路", "server":"服务端",
	"upstream":"上游服务", "none":"无", "unknown":"未知",
}
const CHANNELS := ["http", "ws", "ui", "app"]
const SCOPES := ["sqlite", "file", "unknown"]
const MODULES := ["app", "account", "network", "message", "audio", "cache", "history", "settings", "dynamics", "engine"]

const CODES := "OK UNKNOWN INVALID_INPUT INSECURE_SERVER INVALID_RESPONSE BUSY CANCELLED TIMEOUT NETWORK_ERROR HTTP_ERROR AUTH_REJECTED PUBLIC_KEY_ERROR ENCRYPTION_ERROR CREDENTIAL_UNAVAILABLE NO_SAVED_LOGIN LOGGED_OUT PENDING SEND_REJECTED DELIVERY_UNCERTAIN TRANSPORT_STOPPED ACK_TIMEOUT DISCONNECTED CONNECT_TIMEOUT AUTH_TIMEOUT INVALID_BASE64 AUDIO_ERROR REMOTE_AUDIO_ERROR TTS_EMPTY TTS_STREAM_ERROR TTS_CANCELLED AUDIO_TIMEOUT BUFFER_LIMIT DECODER_UNAVAILABLE PLAYBACK_FAILED REPLAY_FAILED CACHE_WRITE_FAILED CACHE_CLEAR_FAILED INVALID_WAV UNSUPPORTED_FORMAT TRUNCATED_AUDIO EMPTY_AUDIO STREAM_FINISHED STOPPED INTERRUPTED ENGINE_ERROR ENGINE_WARNING ENGINE_SCRIPT ENGINE_SHADER HISTORY_FAILED HISTORY_INVALID HISTORY_DUPLICATE MODEL_ERROR MODEL_DISABLED MODEL_INVALID SAVE_FAILED INVALID_JSON MODEL_BUSY UNKNOWN_MODEL_TYPE INVALID_CONFIG MODEL_KIND_MISMATCH MODEL_CAPABILITY_MISMATCH MODEL_FIELDS_REQUIRED STREAMING_NOT_SUPPORTED PLAINTEXT_CONFIRMATION_REQUIRED KEY_UNAVAILABLE NOT_FOUND COMMENT_NOT_ALLOWED INVALID_REPLY_TARGET STORAGE_ERROR ACCOUNT_START_FAILED SERVER_CHANGED ACCOUNT_SELECTED OPTIONS_CHANGED ACCOUNT_REMOVED CHECKING_SERVER IMAGE_READ_FAILED AVATAR_WRITE_FAILED NO_ACCOUNT IMAGE_TOO_LARGE IMAGE_FORMAT INVALID_IMAGE IMAGE_DIMENSIONS IMAGE_MISSING SERVER_ERROR UNAVAILABLE CACHE_SQL_FAILED CACHE_CONNECTION_INVALID CONNECTION_FAILED SEND_FAILED SYSTEM_RUNTIME_NOT_READY STORAGE_RUNNING STORAGE_UNAVAILABLE SECURITY_UNAVAILABLE PROTECT_FAILED UNPROTECT_FAILED STALE_SCOPE SCHEMA_MISSING SETTINGS_SAVE_FAILED ABNORMAL_SHUTDOWN TARGET_INVALID TARGET_MISSING SOURCE_EMPTY SOURCE_NOT_FOUND SOURCE_UNREADABLE ALREADY_CACHED UNSUPPORTED_IMAGE UI_ERROR CAPABILITY_START_FAILED LOG_PENDING_DROPPED LOG_LIMIT_REACHED"
const PHASES := "saving first_loading first_failed idle connecting authenticating ready reconnecting auth_rejected signed_out signed_in busy queued sending sent received failed uncertain loading complete error warning skipped playing paused stopped receiving decoded begin committed rolled_back begin_failed commit_failed rollback_failed starting running stopping start stop open close close_dialog unknown abnormal"
const METRICS := ["has_audio", "audio_chars", "bytes", "frames", "sample_rate", "channels", "bits", "final", "audio_error", "queued", "volume", "latency_ms", "skips", "count", "status", "index", "duration_ms", "uptime_ms", "pid", "queue_depth", "memory_bytes", "objects", "draw_calls", "fps", "avg_ms", "max_ms", "failures", "affected_rows", "seq", "window_ms", "next_end"]
const STRING_FIELDS := ["detail", "code", "phase", "module", "level", "category", "channel", "action", "method", "route", "outcome", "origin", "reason_code", "subject", "trace_id", "transaction_id", "scope", "operation", "schema_missing", "reply_id", "reason", "previous_run_id", "storage", "initial", "catchup", "older", "model_type"]
const SUBJECT_SECRET_KEYS := ["token", "password", "passwd", "secret", "authorization", "auth", "cookie", "key", "cipher", "private", "credential", "body", "content", "text", "audio", "base64", "message"]

const CATEGORY_REQUIRED := {
	"business": ["phase"],
	"network": ["channel", "route", "outcome", "duration_ms"],
	"storage": ["scope", "operation", "outcome", "duration_ms"],
	"system": [],
}
const CATEGORY_DEFAULTS := {
	"channel": "app", "route": "/unknown", "duration_ms": 0, "outcome": "unknown",
	"scope": "unknown", "operation": "unknown", "phase": "unknown",
}

const EVENT_REGISTRY := {
	"app_started": {"category":"business", "module":"app", "message":"客户端启动", "phase":"starting"},
	"app_stopped": {"category":"business", "module":"app", "message":"客户端正常退出", "phase":"stopped"},
	"window_state_changed": {"category":"business", "module":"app", "message":"窗口状态变化", "phase":"open"},
	"previous_run_incomplete": {"category":"business", "module":"app", "message":"上次运行未正常结束", "phase":"abnormal"},
	"account_lifecycle": {"category":"business", "module":"account", "message":"账号生命周期", "phase":"running"},
	"account_state": {"category":"business", "module":"account", "message":"账户操作状态", "phase":"unknown"},
	"connection_state": {"category":"business", "module":"network", "message":"聊天连接状态变化", "phase":"unknown"},
	"history_state": {"category":"business", "module":"history", "message":"历史同步状态", "phase":"unknown"},
	"dynamics_state": {"category":"business", "module":"dynamics", "message":"动态读取与写入状态", "phase":"unknown"},
	"message_queued": {"category":"business", "module":"message", "message":"消息已进入发送队列", "phase":"queued"},
	"message_delivery": {"category":"business", "module":"message", "message":"消息投递状态", "phase":"unknown"},
	"message_reply_received": {"category":"business", "module":"message", "message":"收到回复", "phase":"received"},
	"message_error": {"category":"business", "module":"message", "message":"消息处理失败", "phase":"error"},
	"history_reconcile": {"category":"business", "module":"history", "message":"送达不确定后的历史对账", "phase":"complete"},
	"settings_models": {"category":"business", "module":"settings", "message":"模型配置状态", "phase":"unknown"},
	"settings_preference": {"category":"business", "module":"settings", "message":"相处偏好操作", "phase":"unknown"},
	"settings_save_failed": {"category":"business", "module":"settings", "message":"设置保存失败", "phase":"failed"},
	"avatar_applied": {"category":"business", "module":"app", "message":"头像应用", "phase":"complete"},
	"model_execution": {"category":"business", "module":"settings", "message":"模型请求执行", "phase":"complete"},
	"account_auth": {"category":"business", "module":"account", "message":"账号认证事件", "phase":"complete"},
	"dynamics_post_publish": {"category":"business", "module":"dynamics", "message":"发布动态", "phase":"complete"},
	"dynamics_comment_created": {"category":"business", "module":"dynamics", "message":"发表评论", "phase":"complete"},
	"dynamics_comment_rejected": {"category":"business", "module":"dynamics", "message":"评论被拒绝", "phase":"failed"},
	"account_capability_degraded": {"category":"business", "module":"account", "message":"扩展能力降级", "phase":"running"},
	"account_capability_failed": {"category":"business", "module":"account", "message":"扩展能力启动失败", "phase":"failed"},
	"audio_receive_finished": {"category":"business", "module":"audio", "message":"音频接收结束", "phase":"complete"},
	"audio_playback_started": {"category":"business", "module":"audio", "message":"开始播放在线语音", "phase":"playing"},
	"audio_playback_finished": {"category":"business", "module":"audio", "message":"在线语音播放结束", "phase":"complete"},
	"audio_replay_started": {"category":"business", "module":"audio", "message":"开始重放", "phase":"playing"},
	"audio_replay_paused": {"category":"business", "module":"audio", "message":"重放已暂停", "phase":"paused"},
	"audio_replay_resumed": {"category":"business", "module":"audio", "message":"继续重放", "phase":"playing"},
	"audio_replay_stopped": {"category":"business", "module":"audio", "message":"重放已停止", "phase":"stopped"},
	"audio_replay_finished": {"category":"business", "module":"audio", "message":"重放结束", "phase":"complete"},
	"audio_replay_preempted": {"category":"business", "module":"audio", "message":"在线语音打断本地重放", "phase":"warning"},
	"audio_underrun": {"category":"business", "module":"audio", "message":"音频缓冲暂时不足", "phase":"warning"},
	"audio_error": {"category":"business", "module":"audio", "message":"音频处理失败", "phase":"error"},
	"audio_frames_received": {"category":"business", "module":"audio", "message":"收到音频数据", "phase":"receiving"},
	"audio_format_detected": {"category":"business", "module":"audio", "message":"已识别音频格式", "phase":"decoded"},
	"audio_decoded": {"category":"business", "module":"audio", "message":"音频解码完成", "phase":"decoded"},
	"network_http": {"category":"network", "module":"network", "message":"HTTP 请求", "phase":"complete"},
	"network_http_summary": {"category":"network", "module":"network", "message":"HTTP 请求汇总", "phase":"complete"},
	"network_ws": {"category":"network", "module":"network", "message":"WebSocket 访问", "phase":"complete"},
	"network_ws_auth": {"category":"network", "module":"network", "message":"WebSocket 认证", "phase":"complete"},
	"network_ws_audio_summary": {"category":"network", "module":"network", "message":"WebSocket 音频汇总", "phase":"complete"},
	"storage_sqlite_operation": {"category":"storage", "module":"history", "message":"SQLite 操作", "phase":"complete"},
	"storage_scope_guard": {"category":"storage", "module":"history", "message":"数据作用域检查", "phase":"complete"},
	"storage_file_write": {"category":"storage", "module":"app", "message":"文件写入", "phase":"complete"},
	"storage_credential": {"category":"storage", "module":"account", "message":"凭据读写", "phase":"complete"},
	"storage_cache_cleared": {"category":"storage", "module":"cache", "message":"已执行语音缓存清理", "phase":"complete"},
	"storage_cache_write_failed": {"category":"storage", "module":"cache", "message":"缓存写入失败", "phase":"error"},
	"storage_media_scan": {"category":"storage", "module":"cache", "message":"扫描媒体缓存", "phase":"complete"},
	"storage_media_scan_failed": {"category":"storage", "module":"cache", "message":"媒体缓存目录不可用", "phase":"failed"},
	"storage_avatar_clear_failed": {"category":"storage", "module":"app", "message":"头像清理失败", "phase":"error"},
	"storage_avatar_save_failed": {"category":"storage", "module":"app", "message":"头像保存失败", "phase":"error"},
	"storage_history_image_ready": {"category":"storage", "module":"history", "message":"历史图片就绪", "phase":"complete"},
	"storage_history_image_failed": {"category":"storage", "module":"history", "message":"历史图片处理失败", "phase":"error"},
	"storage_image_operation": {"category":"storage", "module":"history", "message":"图片处理", "phase":"complete"},
	"history_storage_unavailable": {"category":"storage", "module":"history", "message":"本地历史库不可用", "phase":"failed"},
	"state_snapshot": {"category":"system", "module":"app", "message":"运行状态快照", "phase":"running"},
	"ui_access": {"category":"system", "module":"app", "message":"界面访问", "phase":"complete"},
	"ui_error_shown": {"category":"system", "module":"app", "message":"已通过弹窗提示用户错误", "phase":"failed"},
	"system_security_component": {"category":"system", "module":"account", "message":"安全组件检查", "phase":"failed"},
	"system_startup": {"category":"system", "module":"app", "message":"启动阶段耗时", "phase":"complete"},
	"system_resource_sample": {"category":"system", "module":"app", "message":"资源占用采样", "phase":"complete"},
	"system_queue_depth": {"category":"system", "module":"app", "message":"队列深度", "phase":"complete"},
	"engine_error": {"category":"system", "module":"engine", "message":"引擎报告错误", "phase":"error"},
	"engine_warning": {"category":"system", "module":"engine", "message":"引擎报告警告", "phase":"warning"},
	"engine_error_repeated": {"category":"system", "module":"engine", "message":"引擎重复错误", "phase":"error"},
	"engine_warning_repeated": {"category":"system", "module":"engine", "message":"引擎重复警告", "phase":"warning"},
	"log_pending_dropped": {"category":"system", "module":"app", "message":"日志后台队列溢出丢弃", "phase":"warning"},
	"log_limit_reached": {"category":"system", "module":"app", "message":"日志容量达到上限", "phase":"error"},
}

static var _patterns: Array[RegEx] = []
static var _token_pattern: RegEx
static var _trace_pattern: RegEx
static var _route_pattern: RegEx

static func is_category(value: Variant) -> bool:
	return value is String and value in CATEGORIES

static func is_level(value: Variant) -> bool:
	return value is String and value in LEVELS

static func is_outcome(value: Variant) -> bool:
	return value is String and value in OUTCOMES

static func is_origin(value: Variant) -> bool:
	return value is String and value in ORIGINS

static func is_channel(value: Variant) -> bool:
	return value is String and value in CHANNELS

static func is_scope(value: Variant) -> bool:
	return value is String and value in SCOPES

const CLIENT_CODES := [
	"INVALID_INPUT", "INVALID_JSON", "MODEL_DISABLED", "MODEL_INVALID", "MODEL_BUSY",
	"MODEL_FIELDS_REQUIRED", "MODEL_KIND_MISMATCH", "MODEL_CAPABILITY_MISMATCH",
	"STREAMING_NOT_SUPPORTED", "UNKNOWN_MODEL_TYPE", "INVALID_CONFIG",
	"PLAINTEXT_CONFIRMATION_REQUIRED", "KEY_UNAVAILABLE", "SAVE_FAILED", "SETTINGS_SAVE_FAILED",
	"STORAGE_ERROR", "STORAGE_UNAVAILABLE", "CACHE_WRITE_FAILED", "CACHE_CLEAR_FAILED",
	"CACHE_SQL_FAILED", "CACHE_CONNECTION_INVALID", "IMAGE_READ_FAILED", "IMAGE_TOO_LARGE",
	"IMAGE_FORMAT", "INVALID_IMAGE", "IMAGE_DIMENSIONS", "IMAGE_MISSING", "AVATAR_WRITE_FAILED",
	"NO_ACCOUNT", "INVALID_WAV", "UNSUPPORTED_FORMAT", "TRUNCATED_AUDIO", "EMPTY_AUDIO",
	"DECODER_UNAVAILABLE", "PLAYBACK_FAILED", "REPLAY_FAILED", "AUDIO_ERROR", "BUFFER_LIMIT",
	"TARGET_INVALID", "TARGET_MISSING", "SOURCE_EMPTY", "SOURCE_NOT_FOUND", "SOURCE_UNREADABLE",
	"ALREADY_CACHED", "UNSUPPORTED_IMAGE", "SEND_REJECTED", "CREDENTIAL_UNAVAILABLE",
	"PROTECT_FAILED", "UNPROTECT_FAILED", "SECURITY_UNAVAILABLE", "UI_ERROR",
	"CAPABILITY_START_FAILED", "INSECURE_SERVER", "LOG_PENDING_DROPPED", "LOG_LIMIT_REACHED",
]
const NETWORK_CODES := [
	"NETWORK_ERROR", "TIMEOUT", "CONNECTION_FAILED", "CONNECT_TIMEOUT", "DISCONNECTED",
	"TRANSPORT_STOPPED", "ACK_TIMEOUT", "AUTH_TIMEOUT", "PUBLIC_KEY_ERROR",
]
const SERVER_CODES := [
	"AUTH_REJECTED", "HTTP_ERROR", "SERVER_ERROR", "INVALID_RESPONSE", "HISTORY_FAILED",
	"HISTORY_INVALID", "HISTORY_DUPLICATE", "NOT_FOUND", "COMMENT_NOT_ALLOWED",
	"INVALID_REPLY_TARGET",
]
const UPSTREAM_CODES := [
	"REMOTE_AUDIO_ERROR", "TTS_EMPTY", "TTS_STREAM_ERROR", "TTS_CANCELLED",
	"AUDIO_TIMEOUT", "MODEL_ERROR",
]

static func infer_origin(event: String, fields: Dictionary, category: String) -> String:
	var explicit: Variant = fields.get("origin")
	if is_origin(explicit):
		return explicit
	var code := str(fields.get("code", fields.get("reason_code", "")))
	var outcome := str(fields.get("outcome", "unknown"))
	if event.begins_with("network_http"):
		return _http_origin(fields)
	if event.begins_with("network_ws"):
		return _ws_origin(fields, code)
	if event.begins_with("engine_"):
		return _engine_origin(fields)
	if not code.is_empty():
		var by_code := _code_origin(code)
		if by_code != "unknown":
			return by_code
	if outcome == "failure":
		return "network" if category == "network" else "client"
	return "none"

static func _http_origin(fields: Dictionary) -> String:
	if str(fields.get("outcome", "")) != "failure":
		return "none"
	return "network" if int(fields.get("status", 0)) <= 0 else "server"

static func _ws_origin(fields: Dictionary, code: String) -> String:
	if str(fields.get("outcome", "")) not in ["failure", "denied"]:
		return "none"
	if code in SERVER_CODES:
		return "server"
	var by_code := _code_origin(code)
	if by_code != "unknown":
		return by_code
	return "network"

static func _engine_origin(fields: Dictionary) -> String:
	var detail := str(fields.get("detail", "")).to_lower()
	if detail.contains("tls") or detail.contains("ssl") or detail.contains("cert") or detail.contains("handshake"):
		return "network"
	return "client"

static func _code_origin(code: String) -> String:
	if code in CLIENT_CODES:
		return "client"
	if code in NETWORK_CODES:
		return "network"
	if code in SERVER_CODES:
		return "server"
	if code in UPSTREAM_CODES:
		return "upstream"
	return "unknown"

static func category_for(event: String, fields: Dictionary = {}) -> String:
	var explicit: Variant = fields.get("category")
	if is_category(explicit):
		return explicit
	if EVENT_REGISTRY.has(event):
		return EVENT_REGISTRY[event].category
	return "system"

static func explanation(event: String) -> String:
	if EVENT_REGISTRY.has(event):
		return EVENT_REGISTRY[event].message
	return "客户端活动"

static func module_for(event: String, fields: Dictionary = {}) -> String:
	var explicit: Variant = fields.get("module")
	if explicit is String and explicit in MODULES:
		return explicit
	if EVENT_REGISTRY.has(event):
		return EVENT_REGISTRY[event].module
	return "app"

static func default_level(_category: String, fields: Dictionary = {}) -> String:
	var outcome := str(fields.get("outcome", "unknown"))
	if outcome == "failure" or fields.get("phase") == "error":
		return "ERROR"
	if outcome in ["cancelled", "denied"] or fields.get("phase") == "warning":
		return "WARN"
	return "INFO"

static func required_fields(category: String) -> Array:
	return CATEGORY_REQUIRED.get(category, [])

static func missing_fields(category: String, entry: Dictionary) -> Array:
	var missing: Array = []
	for key in required_fields(category):
		if not entry.has(key):
			missing.append(key)
	return missing

static func apply_defaults(entry: Dictionary, category: String) -> Array:
	var missing := missing_fields(category, entry)
	for key in required_fields(category):
		if not entry.has(key):
			entry[key] = _copy_default(CATEGORY_DEFAULTS.get(key, null))
	if not missing.is_empty():
		entry.schema_missing = ",".join(missing)
	return missing

static func _copy_default(value: Variant) -> Variant:
	if value is Array:
		return value.duplicate()
	if value is Dictionary:
		return value.duplicate(true)
	return value

static func is_token(value: Variant, max_len: int = 64) -> bool:
	if not value is String or value.is_empty() or value.length() > max_len:
		return false
	if _token_pattern == null:
		_token_pattern = RegEx.new()
		_token_pattern.compile("^[A-Za-z0-9_:-]+$")
	return _token_pattern.search(value) != null

static func is_trace_id(value: Variant) -> bool:
	if not value is String or value.length() > 64:
		return false
	if _trace_pattern == null:
		_trace_pattern = RegEx.new()
		_trace_pattern.compile("^[a-z]{2,12}_[a-f0-9]{8,40}$")
	return _trace_pattern.search(value) != null

static func new_trace_id(prefix: String = "tr") -> String:
	return "%s_%s" % [prefix, Crypto.new().generate_random_bytes(8).hex_encode()]

static func new_transaction_id() -> String:
	return "tx_%s" % Crypto.new().generate_random_bytes(8).hex_encode()

static func safe_code(value: Variant) -> String:
	return value if value is String and value in CODES.split(" ") else "UNKNOWN"

static func safe_phase(value: Variant) -> String:
	return value if value is String and value in PHASES.split(" ") else "UNKNOWN"

static func route_for(url: String) -> String:
	var path := url
	var scheme := path.find("://")
	if scheme >= 0:
		var slash := path.find("/", scheme + 3)
		path = "/" if slash < 0 else path.substr(slash)
	var query := path.find("?")
	if query >= 0:
		path = path.left(query)
	for known in ["/auth/public_key", "/auth/login", "/auth/register", "/auth/reset_account", "/auth/auto_login",
			"/history", "/get_image", "/chat/completions", "/llm/client-model-types",
			"/preference/get", "/preference/overwrite"]:
		if path == known:
			return known
	if path.begins_with("/auth/"):
		return "/auth/" + path.get_file()
	if path.begins_with("/dynamics"):
		return "/dynamics/*"
	if path.is_empty():
		return "/unknown"
	return "/" + path.get_slice("/", 1)

static func safe_route(value: Variant) -> String:
	if not value is String:
		return "/unknown"
	var text: String = str(value).strip_edges()
	if text.contains("://"):
		return route_for(text)
	var query: int = text.find("?")
	if query >= 0:
		text = text.left(query)
	if text.is_empty():
		return "/unknown"
	if not text.begins_with("/"):
		text = "/" + text
	if _route_pattern == null:
		_route_pattern = RegEx.new()
		_route_pattern.compile("^/[A-Za-z0-9_./*-]{0,63}$")
	return text if _route_pattern.search(text) != null else "/unknown"

static func safe_action(value: Variant) -> String:
	if not value is String:
		return "unknown"
	var text: String = str(value).strip_edges().to_lower()
	return text if is_token(text, 32) else "unknown"

static func safe_method(value: Variant) -> String:
	if not value is String:
		return ""
	var text: String = str(value).strip_edges().to_upper()
	return text if is_token(text, 16) else ""

static func sanitize_text(value: Variant, max_len: int = 1024) -> String:
	if value == null:
		return ""
	var text := str(value).replace("\r", " ").replace("\n", " ")
	_ensure_patterns()
	for pattern in _patterns:
		text = _redact_pattern(pattern, text)
	text = text.strip_edges()
	if text.length() > max_len:
		text = text.left(maxi(0, max_len - 3)) + "..."
	return text

static func _ensure_patterns() -> void:
	if not _patterns.is_empty():
		return
	var specs := [
		["(?i)\\b(bearer)\\s+[A-Za-z0-9._~+/=-]+", "$1 ***"],
		# 同时覆盖裸键、JSON 引号键和 access_token/x-api-key 等常见命名。
		["(?i)\\b((?:access|refresh|message|login|auth|session|api|id)?[_-]?token|password|passwd|secret|authorization|x-api-key|api[_-]?key|apikey|cookie|cipher|credential|key)[\"']?\\s*[:=]\\s*[\"']?[^\"'\\s,;}\\]]+", "$1=***"],
		["[A-Za-z0-9+/]{80,}={0,2}", "[redacted-base64]"],
		["[A-Za-z]:\\\\[^\\s\"']+", "<abs>"],
	]
	for spec in specs:
		var pattern := RegEx.new()
		pattern.compile(spec[0])
		pattern.set_meta("replacement", spec[1])
		_patterns.append(pattern)

static func _redact_pattern(pattern: RegEx, text: String) -> String:
	return pattern.sub(text, pattern.get_meta("replacement", ""), true)

static func sanitize_stack(frames: Variant, max_frames: int = 12) -> Array:
	var result: Array = []
	if not frames is Array:
		return result
	for frame in frames:
		if result.size() >= max_frames:
			break
		if frame is Dictionary:
			var function := str(frame.get("function", frame.get("func", "")))
			var source := str(frame.get("source", frame.get("file", "")))
			var line := int(frame.get("line", 0))
			var path := _safe_path(source)
			var text := "%s@%s:%d" % [function, path, line] if not function.is_empty() else "%s:%d" % [path, line]
			result.append(sanitize_text(text, 240))
		elif frame is String:
			result.append(sanitize_text(frame, 240))
	return result

static func _safe_path(value: String) -> String:
	if value.begins_with("res://") or value.begins_with("user://"):
		return value
	if value.is_empty():
		return ""
	return "<abs>/" + value.get_file()

static func sanitize_data(value: Variant, max_keys: int = 16, max_str: int = 256) -> Dictionary:
	var result: Dictionary = {}
	if not value is Dictionary:
		return result
	for key in value:
		if result.size() >= max_keys:
			break
		var name := str(key)
		if not _valid_data_key(name):
			continue
		var item: Variant = value[key]
		if _is_scalar(item):
			result[name] = _scalar(item, max_str)
	return result

static func _valid_data_key(name: String) -> bool:
	return not name.is_empty() and name.length() <= 64 and is_token(name) and not _is_secret_key(name)

static func _is_scalar(value: Variant) -> bool:
	return value is bool or value is int or (value is float and is_finite(value)) or value is String

static func _scalar(value: Variant, max_str: int) -> Variant:
	return sanitize_text(value, max_str) if value is String else value

static func _is_secret_key(key: String) -> bool:
	var lower := key.to_lower()
	for secret in SUBJECT_SECRET_KEYS:
		if lower.contains(secret):
			return true
	return false

static func hash_subject(server: String, username: String) -> String:
	if server.is_empty() and username.is_empty():
		return ""
	return JSON.stringify([server, username]).sha256_text().left(12)
