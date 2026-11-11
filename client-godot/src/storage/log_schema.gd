extends RefCounted
## 九类日志的公共 schema：分类、级别、事件注册、字段白名单、脱敏与归一化。
## 该文件不持有运行状态，ClientLog 只通过静态函数读取规则。

const CATEGORIES := ["error", "warning", "info", "debug", "access", "security", "performance", "transaction", "runtime"]
const CATEGORY_LABELS := {
	"error": "错误", "warning": "警告", "info": "信息", "debug": "调试",
	"access": "访问", "security": "安全", "performance": "性能",
	"transaction": "事务", "runtime": "运行",
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
const MODULE_PREFIXES := [
	["access_ui", "app"], ["access_", "network"], ["security_ws", "network"], ["security_", "account"],
	["performance_image", "history"], ["performance_sqlite", "history"], ["transaction_sqlite", "history"],
	["debug_audio", "audio"], ["info_audio", "audio"],
	["error_audio", "audio"], ["warning_audio", "audio"], ["info_replay", "audio"], ["warning_replay", "audio"],
	["error_cache", "cache"], ["info_cache", "cache"],
	["info_message", "message"], ["info_reply", "message"],
	["info_history", "history"], ["info_settings", "settings"],
	["runtime_connection", "network"], ["runtime_account", "account"], ["runtime_history", "history"],
	["runtime_dynamics", "dynamics"], ["runtime_settings", "settings"],
	["error_engine", "engine"], ["warning_engine", "engine"], ["debug_engine", "engine"],
	["cache_", "cache"], ["history_", "history"], ["audio_", "audio"], ["replay_", "audio"],
	["message_", "message"], ["settings_", "settings"], ["dynamics_", "dynamics"],
	["account_", "account"], ["engine_", "engine"],
]

const CODES := "OK UNKNOWN INVALID_INPUT INSECURE_SERVER INVALID_RESPONSE BUSY CANCELLED TIMEOUT NETWORK_ERROR HTTP_ERROR AUTH_REJECTED PUBLIC_KEY_ERROR ENCRYPTION_ERROR CREDENTIAL_UNAVAILABLE NO_SAVED_LOGIN LOGGED_OUT PENDING SEND_REJECTED DELIVERY_UNCERTAIN TRANSPORT_STOPPED ACK_TIMEOUT DISCONNECTED CONNECT_TIMEOUT AUTH_TIMEOUT INVALID_BASE64 AUDIO_ERROR REMOTE_AUDIO_ERROR TTS_EMPTY TTS_STREAM_ERROR TTS_CANCELLED AUDIO_TIMEOUT BUFFER_LIMIT DECODER_UNAVAILABLE PLAYBACK_FAILED REPLAY_FAILED CACHE_WRITE_FAILED CACHE_CLEAR_FAILED INVALID_WAV UNSUPPORTED_FORMAT TRUNCATED_AUDIO EMPTY_AUDIO STREAM_FINISHED STOPPED INTERRUPTED ENGINE_ERROR ENGINE_WARNING ENGINE_SCRIPT ENGINE_SHADER HISTORY_FAILED HISTORY_INVALID HISTORY_DUPLICATE MODEL_ERROR MODEL_DISABLED MODEL_INVALID SAVE_FAILED INVALID_JSON MODEL_BUSY UNKNOWN_MODEL_TYPE INVALID_CONFIG MODEL_KIND_MISMATCH MODEL_CAPABILITY_MISMATCH MODEL_FIELDS_REQUIRED STREAMING_NOT_SUPPORTED PLAINTEXT_CONFIRMATION_REQUIRED KEY_UNAVAILABLE NOT_FOUND COMMENT_NOT_ALLOWED INVALID_REPLY_TARGET STORAGE_ERROR ACCOUNT_START_FAILED SERVER_CHANGED ACCOUNT_SELECTED OPTIONS_CHANGED ACCOUNT_REMOVED CHECKING_SERVER IMAGE_READ_FAILED AVATAR_WRITE_FAILED NO_ACCOUNT IMAGE_TOO_LARGE IMAGE_FORMAT INVALID_IMAGE IMAGE_DIMENSIONS IMAGE_MISSING SERVER_ERROR UNAVAILABLE CACHE_SQL_FAILED CACHE_CONNECTION_INVALID CONNECTION_FAILED SEND_FAILED SYSTEM_RUNTIME_NOT_READY STORAGE_RUNNING STORAGE_UNAVAILABLE SECURITY_UNAVAILABLE PROTECT_FAILED UNPROTECT_FAILED STALE_SCOPE SCHEMA_MISSING SETTINGS_SAVE_FAILED ABNORMAL_SHUTDOWN TARGET_INVALID TARGET_MISSING SOURCE_EMPTY SOURCE_NOT_FOUND SOURCE_UNREADABLE ALREADY_CACHED UNSUPPORTED_IMAGE UI_ERROR"
const PHASES := "saving first_loading first_failed idle connecting authenticating ready reconnecting auth_rejected signed_out signed_in busy queued sending sent received failed uncertain loading complete error warning skipped playing paused stopped receiving decoded begin committed rolled_back begin_failed commit_failed rollback_failed starting running stopping start stop open close close_dialog unknown abnormal"
const METRICS := ["has_audio", "audio_chars", "bytes", "frames", "sample_rate", "channels", "bits", "final", "audio_error", "queued", "volume", "latency_ms", "skips", "count", "status", "index", "duration_ms", "uptime_ms", "pid", "queue_depth", "memory_bytes", "objects", "draw_calls", "fps", "avg_ms", "max_ms", "failures", "affected_rows", "seq", "window_ms", "next_end"]
const STRING_FIELDS := ["detail", "code", "phase", "module", "level", "category", "channel", "action", "method", "route", "outcome", "origin", "reason_code", "subject", "trace_id", "transaction_id", "scope", "operation", "schema_missing", "reply_id", "reason", "previous_run_id", "storage", "initial", "catchup", "older"]
const SUBJECT_SECRET_KEYS := ["token", "password", "passwd", "secret", "authorization", "auth", "cookie", "key", "cipher", "private", "credential", "body", "content", "text", "audio", "base64", "message"]

const CATEGORY_REQUIRED := {
	"error": ["code", "detail", "stack", "origin"],
	"warning": ["code", "detail", "origin"],
	"info": ["phase"],
	"debug": ["data"],
	"access": ["channel", "action", "route", "outcome", "duration_ms", "trace_id"],
	"security": ["action", "outcome", "reason_code", "subject", "trace_id"],
	"performance": ["operation", "outcome", "duration_ms", "trace_id"],
	"transaction": ["transaction_id", "scope", "operation", "phase", "outcome", "duration_ms", "trace_id"],
	"runtime": ["phase", "reason", "uptime_ms", "pid"],
}
const CATEGORY_DEFAULTS := {
	"code": "UNKNOWN", "detail": "", "stack": [], "data": {},
	"channel": "app", "action": "unknown", "route": "/unknown",
	"duration_ms": 0, "outcome": "unknown", "reason_code": "UNKNOWN",
	"subject": "", "trace_id": "", "transaction_id": "", "scope": "unknown",
	"operation": "unknown", "phase": "unknown", "uptime_ms": 0, "pid": 0,
	"reason": "",
	"origin": "unknown",
}

const EVENT_REGISTRY := {
	"runtime_app_started": {"category":"runtime", "module":"app", "message":"客户端启动", "phase":"starting"},
	"runtime_app_stopped": {"category":"runtime", "module":"app", "message":"客户端正常退出", "phase":"stopped"},
	"runtime_window": {"category":"runtime", "module":"app", "message":"窗口状态变化", "phase":"open"},
	"runtime_previous_incomplete": {"category":"runtime", "module":"app", "message":"上次运行未正常结束", "phase":"abnormal"},
	"runtime_account_lifecycle": {"category":"runtime", "module":"account", "message":"账号生命周期", "phase":"running"},
	"runtime_account_state": {"category":"runtime", "module":"account", "message":"账户操作状态", "phase":"unknown"},
	"runtime_connection_state": {"category":"runtime", "module":"network", "message":"聊天连接状态变化", "phase":"unknown"},
	"runtime_history_state": {"category":"runtime", "module":"history", "message":"历史同步状态", "phase":"unknown"},
	"runtime_dynamics_state": {"category":"runtime", "module":"dynamics", "message":"动态读取与写入状态", "phase":"unknown"},
	"info_message_queued": {"category":"info", "module":"message", "message":"消息已进入发送队列", "phase":"queued"},
	"info_message_delivery": {"category":"info", "module":"message", "message":"消息投递状态", "phase":"unknown"},
	"info_reply_received": {"category":"info", "module":"message", "message":"收到回复分片", "phase":"received"},
	"info_history_reconcile": {"category":"info", "module":"history", "message":"送达不确定后的历史对账", "phase":"complete"},
	"info_settings_models": {"category":"info", "module":"settings", "message":"模型配置状态", "phase":"unknown"},
	"info_settings_preference": {"category":"info", "module":"settings", "message":"相处偏好操作", "phase":"unknown"},
	"info_avatar_apply": {"category":"info", "module":"app", "message":"头像应用", "phase":"complete"},
	"info_cache_cleared": {"category":"info", "module":"cache", "message":"已执行语音缓存清理", "phase":"complete"},
	"info_history_image": {"category":"info", "module":"history", "message":"历史图片就绪", "phase":"complete"},
	"info_python_media_scan": {"category":"info", "module":"cache", "message":"扫描 Python 客户端媒体缓存", "phase":"complete"},
	"warning_python_media_target": {"category":"warning", "module":"cache", "message":"Python 客户端目录不可用", "phase":"failed"},
	"warning_ui_error": {"category":"warning", "module":"app", "message":"已通过弹窗提示用户错误", "phase":"failed"},
	"info_audio_receive_finished": {"category":"info", "module":"audio", "message":"音频接收结束", "phase":"complete"},
	"info_audio_playback_started": {"category":"info", "module":"audio", "message":"开始播放在线语音", "phase":"playing"},
	"info_audio_playback_finished": {"category":"info", "module":"audio", "message":"在线语音播放结束", "phase":"complete"},
	"info_replay_started": {"category":"info", "module":"audio", "message":"开始重放", "phase":"playing"},
	"info_replay_paused": {"category":"info", "module":"audio", "message":"重放已暂停", "phase":"paused"},
	"info_replay_resumed": {"category":"info", "module":"audio", "message":"继续重放", "phase":"playing"},
	"info_replay_stopped": {"category":"info", "module":"audio", "message":"重放已停止", "phase":"stopped"},
	"info_replay_finished": {"category":"info", "module":"audio", "message":"重放结束", "phase":"complete"},
	"error_system": {"category":"error", "module":"app", "message":"操作出现错误", "phase":"error"},
	"error_avatar_clear": {"category":"error", "module":"app", "message":"头像清理失败", "phase":"error"},
	"error_avatar_save": {"category":"error", "module":"app", "message":"头像保存被拒绝", "phase":"error"},
	"error_cache": {"category":"error", "module":"cache", "message":"语音缓存写入失败", "phase":"error"},
	"error_history_image": {"category":"error", "module":"history", "message":"历史图片处理失败", "phase":"error"},
	"error_audio": {"category":"error", "module":"audio", "message":"音频处理失败", "phase":"error"},
	"error_engine": {"category":"error", "module":"engine", "message":"引擎报告错误", "phase":"error"},
	"warning_audio_underrun": {"category":"warning", "module":"audio", "message":"音频缓冲暂时不足", "phase":"warning"},
	"warning_replay_preempted": {"category":"warning", "module":"audio", "message":"在线语音打断本地重放", "phase":"warning"},
	"warning_engine": {"category":"warning", "module":"engine", "message":"引擎报告警告", "phase":"warning"},
	"warning_settings_save": {"category":"warning", "module":"app", "message":"设置保存失败", "phase":"warning"},
	"debug_audio_received": {"category":"debug", "module":"audio", "message":"收到音频数据", "phase":"receiving"},
	"debug_audio_format": {"category":"debug", "module":"audio", "message":"已识别音频格式", "phase":"decoded"},
	"debug_audio_decoded": {"category":"debug", "module":"audio", "message":"音频解码完成", "phase":"decoded"},
	"debug_state": {"category":"debug", "module":"app", "message":"运行状态快照", "phase":"running"},
	"access_http": {"category":"access", "module":"network", "message":"HTTP 请求", "phase":"complete"},
	"access_ws": {"category":"access", "module":"network", "message":"WebSocket 访问", "phase":"complete"},
	"access_ui": {"category":"access", "module":"app", "message":"界面访问", "phase":"complete"},
	"security_auth": {"category":"security", "module":"account", "message":"认证事件", "phase":"complete"},
	"security_token": {"category":"security", "module":"account", "message":"凭证读写", "phase":"complete"},
	"security_component": {"category":"security", "module":"account", "message":"安全组件检查", "phase":"complete"},
	"security_scope": {"category":"security", "module":"account", "message":"数据作用域检查", "phase":"complete"},
	"security_ws_auth": {"category":"security", "module":"network", "message":"WebSocket 认证", "phase":"complete"},
	"performance_startup": {"category":"performance", "module":"app", "message":"启动阶段耗时", "phase":"complete"},
	"performance_sqlite": {"category":"performance", "module":"history", "message":"SQLite 作业性能", "phase":"complete"},
	"performance_image": {"category":"performance", "module":"history", "message":"图片处理性能", "phase":"complete"},
	"performance_model_execution": {"category":"performance", "module":"settings", "message":"模型请求执行", "phase":"complete"},
	"performance_http_summary": {"category":"performance", "module":"network", "message":"HTTP 请求汇总", "phase":"complete"},
	"performance_ws_audio": {"category":"performance", "module":"network", "message":"WebSocket 音频汇总", "phase":"complete"},
	"performance_sample": {"category":"performance", "module":"app", "message":"资源占用采样", "phase":"complete"},
	"performance_queue": {"category":"performance", "module":"app", "message":"队列深度", "phase":"complete"},
	"transaction_sqlite": {"category":"transaction", "module":"history", "message":"SQLite 事务", "phase":"committed"},
	"transaction_file": {"category":"transaction", "module":"app", "message":"文件原子写事务", "phase":"committed"},
}

const LEGACY_ALIASES := {
	"client_started": "runtime_app_started",
	"client_stopped": "runtime_app_stopped",
	"account_state": "runtime_account_state",
	"connection_state": "runtime_connection_state",
	"history_state": "runtime_history_state",
	"dynamics_state": "runtime_dynamics_state",
	"message_queued": "info_message_queued",
	"message_delivery": "info_message_delivery",
	"reply_received": "info_reply_received",
	"system_error": "error_system",
	"history_reconcile": "info_history_reconcile",
	"settings_models": "info_settings_models",
	"settings_preference": "info_settings_preference",
	"settings_model_execution": "performance_model_execution",
	"avatar_apply": "info_avatar_apply",
	"avatar_clear_failed": "error_avatar_clear",
	"avatar_save_rejected": "error_avatar_save",
	"cache_committed": "transaction_file",
	"cache_cleared": "info_cache_cleared",
	"cache_error": "error_cache",
	"history_image": "info_history_image",
	"history_image_error": "error_history_image",
	"engine_error": "error_engine",
	"audio_received": "debug_audio_received",
	"audio_format": "debug_audio_format",
	"audio_decoded": "debug_audio_decoded",
	"audio_receive_finished": "info_audio_receive_finished",
	"audio_error": "error_audio",
	"audio_playback_started": "info_audio_playback_started",
	"audio_playback_finished": "info_audio_playback_finished",
	"audio_underrun": "warning_audio_underrun",
	"replay_started": "info_replay_started",
	"replay_paused": "info_replay_paused",
	"replay_resumed": "info_replay_resumed",
	"replay_stopped": "info_replay_stopped",
	"replay_finished": "info_replay_finished",
	"replay_preempted": "warning_replay_preempted",
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
	"PROTECT_FAILED", "UNPROTECT_FAILED", "SECURITY_UNAVAILABLE",
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
	if event.begins_with("access_http"):
		return _http_origin(fields)
	if event.begins_with("access_ws"):
		return _ws_origin(fields, code)
	if event == "error_engine":
		return _engine_origin(fields)
	if category in ["error", "warning"]:
		return _code_origin(code)
	if category == "security":
		return _security_origin(code)
	if category == "transaction":
		return "client" if str(fields.get("outcome", "")) == "failure" else "none"
	if event.begins_with("runtime_"):
		return _runtime_origin(event, code)
	return "none"

static func _http_origin(fields: Dictionary) -> String:
	if str(fields.get("outcome", "")) != "failure":
		return "none"
	return "network" if int(fields.get("status", 0)) <= 0 else "server"

static func _ws_origin(fields: Dictionary, code: String) -> String:
	if str(fields.get("outcome", "")) != "failure":
		return "none"
	if code in SERVER_CODES:
		return "server"
	var detail := str(fields.get("detail", "")).to_lower()
	if detail.contains("server") or detail.contains("auth"):
		return "server"
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

static func _security_origin(code: String) -> String:
	if code in NETWORK_CODES:
		return "network"
	if code in SERVER_CODES:
		return "server"
	if code in CLIENT_CODES:
		return "client"
	return "unknown"

static func _runtime_origin(event: String, code: String) -> String:
	if code.is_empty():
		return "none"
	if event.contains("connection") and code == "AUTH_REJECTED":
		return "server"
	return _code_origin(code)

static func canonical_event(event: String) -> String:
	return LEGACY_ALIASES.get(event, event)

static func category_for(event: String, fields: Dictionary = {}) -> String:
	var explicit: Variant = fields.get("category")
	if is_category(explicit):
		return explicit
	var canonical := canonical_event(event)
	if EVENT_REGISTRY.has(canonical):
		return EVENT_REGISTRY[canonical].category
	var prefix := event.get_slice("_", 0)
	return prefix if prefix in CATEGORIES else "info"

static func explanation(event: String) -> String:
	var canonical := canonical_event(event)
	if EVENT_REGISTRY.has(canonical):
		return EVENT_REGISTRY[canonical].message
	return "客户端活动"

static func module_for(event: String, fields: Dictionary = {}) -> String:
	var explicit: Variant = fields.get("module")
	if explicit is String and explicit in MODULES:
		return explicit
	var canonical := canonical_event(event)
	if EVENT_REGISTRY.has(canonical):
		return EVENT_REGISTRY[canonical].module
	for pair in MODULE_PREFIXES:
		if event.begins_with(pair[0]):
			return pair[1]
	return "app"

static func default_level(category: String, fields: Dictionary = {}) -> String:
	var base: String = {"error":"ERROR", "warning":"WARN", "debug":"DEBUG"}.get(category, "INFO")
	var elevated := _elevated_level(category, fields)
	return elevated if not elevated.is_empty() else base

static func _elevated_level(category: String, fields: Dictionary) -> String:
	var outcome := str(fields.get("outcome", "unknown"))
	if category == "access":
		return _access_level(outcome)
	if category in ["security", "performance"]:
		return _warn_on_failure(outcome)
	if category == "transaction":
		return _transaction_level(fields, outcome)
	if category == "runtime":
		return _runtime_level(fields)
	return ""

static func _access_level(outcome: String) -> String:
	if outcome == "failure":
		return "ERROR"
	return "WARN" if outcome in ["cancelled", "denied"] else ""

static func _warn_on_failure(outcome: String) -> String:
	return "WARN" if outcome in ["failure", "denied"] else ""

static func _transaction_level(fields: Dictionary, outcome: String) -> String:
	var phase := str(fields.get("phase", ""))
	if phase in ["begin_failed", "commit_failed", "rollback_failed", "rolled_back"]:
		return "ERROR"
	return "ERROR" if outcome == "failure" else ""

static func _runtime_level(fields: Dictionary) -> String:
	return "WARN" if str(fields.get("reason", "")) == "abnormal" else ""

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
