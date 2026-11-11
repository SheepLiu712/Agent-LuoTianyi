extends SceneTree
const Schema = preload("res://src/storage/log_schema.gd")
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	_check_catalog()
	_check_levels()
	_check_defaults()
	_check_sanitizers()
	_check_routes_and_ids()
	_check_origins()
	print("Log schema: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_catalog() -> void:
	check(Schema.CATEGORIES.size() == 9, "nine categories")
	check(Schema.CATEGORY_LABELS.size() == 9, "category labels")
	check(Schema.category_for("runtime_app_started") == "runtime", "new runtime event category")
	check(Schema.category_for("client_started") == "runtime", "legacy alias category")
	check(Schema.category_for("error_system") == "error", "error prefix category")
	check(Schema.category_for("unknown_event") == "info", "unknown event falls back to info")

func _check_levels() -> void:
	check(Schema.default_level("error") == "ERROR", "error level")
	check(Schema.default_level("warning") == "WARN", "warning level")
	check(Schema.default_level("debug") == "DEBUG", "debug level")
	check(Schema.default_level("access", {"outcome":"failure"}) == "ERROR", "failed access escalates")
	check(Schema.default_level("transaction", {"phase":"rolled_back"}) == "ERROR", "rolled back transaction escalates")

func _check_defaults() -> void:
	var entry := {"event":"access_http"}
	var missing := Schema.apply_defaults(entry, "access")
	check(missing.size() == 6 and entry.has("trace_id") and entry.has("route"), "access defaults filled")
	check(entry.schema_missing == "channel,action,route,outcome,duration_ms,trace_id", "schema missing recorded")

func _check_sanitizers() -> void:
	var text := Schema.sanitize_text("Authorization: Bearer abc.def token=secret " + "A".repeat(90))
	check(not text.contains("abc.def") and not text.contains("secret") and text.contains("[redacted-base64]"), "text redaction")
	var json_text := Schema.sanitize_text('{"password":"secret-value","access_token":"abc123","x-api-key":"key-9"}')
	check(not json_text.contains("secret-value") and not json_text.contains("abc123") and not json_text.contains("key-9"), "quoted and suffixed secret keys redacted")
	check(Schema.sanitize_text("x".repeat(40), 10).length() == 10, "text truncation")
	var data := Schema.sanitize_data({"safe":1, "token":"secret", "nested":{"a":1}, "text":"hello", "long":"y ".repeat(300)})
	check(data.has("safe") and not data.has("token") and not data.has("nested") and not data.has("text") and data.long.length() == 256, "debug data sanitized")
	var stack := Schema.sanitize_stack([{"function":"f", "source":"D:\\private\\a.gd", "line":3}, "plain"])
	check(stack.size() == 2 and stack[0].contains("<abs>/a.gd:3"), "stack path normalized")

func _check_routes_and_ids() -> void:
	check(Schema.route_for("https://example.com:1234/auth/login?username=alice&token=x") == "/auth/login", "route strips host and query")
	check(Schema.safe_route("history?username=alice") == "/history", "safe route strips query")
	check(Schema.hash_subject("https://a", "bob") == Schema.hash_subject("https://a", "bob"), "subject hash stable")
	check(Schema.is_trace_id(Schema.new_trace_id("req")), "trace id format")
	check(Schema.is_token(Schema.new_transaction_id(), 64), "transaction id format")

func _check_origins() -> void:
	check(Schema.is_origin("client") and not Schema.is_origin("local"), "origin enum")
	check(Schema.infer_origin("access_http", {"outcome":"failure", "status":0}, "access") == "network", "status 0 maps to network")
	check(Schema.infer_origin("access_http", {"outcome":"failure", "status":503}, "access") == "server", "5xx maps to server")
	check(Schema.infer_origin("access_http", {"outcome":"success", "status":200}, "access") == "none", "success has no fault origin")
	check(Schema.infer_origin("error_system", {"code":"CACHE_WRITE_FAILED"}, "error") == "client", "cache failure maps to client")
	check(Schema.infer_origin("error_system", {"code":"AUTH_REJECTED"}, "error") == "server", "auth rejection maps to server")
	check(Schema.infer_origin("error_system", {"code":"REMOTE_AUDIO_ERROR"}, "error") == "upstream", "remote TTS maps to upstream")
	check(Schema.infer_origin("error_system", {"code":"TIMEOUT"}, "error") == "network", "timeout maps to network")
