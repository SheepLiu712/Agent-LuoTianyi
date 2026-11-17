extends SceneTree
const Schema = preload("res://src/storage/log_schema.gd")
const EngineSink = preload("res://src/storage/engine_log_sink.gd")
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
	_check_origins_for_logs()
	_check_tls_annotation()
	_check_tls_cause()
	_check_origins()
	print("Log schema: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_catalog() -> void:
	check(Schema.CATEGORIES == ["business", "network", "storage", "system"], "four domain categories")
	check(Schema.CATEGORY_LABELS.size() == 4, "category labels")
	check(Schema.category_for("message_reply_received") == "business", "business event category")
	check(Schema.category_for("network_http") == "network", "network event category")
	check(Schema.category_for("storage_sqlite_operation") == "storage", "storage event category")
	check(Schema.category_for("engine_error") == "system", "system event category")
	check(Schema.category_for("unknown_event") == "system", "unknown event falls back to system")
	check(Schema.module_for("storage_sqlite_operation") == "history", "registered module")
	check(Schema.EVENT_REGISTRY.size() == 73, "event registry stays explicitly enumerated")
	check(Schema.category_for("network_probe") == "network", "probe event is network")
	check(Schema.category_for("system_tls_trust") == "system", "TLS trust snapshot is system")
	check(Schema.module_for("system_tls_trust") == "network", "TLS trust snapshot belongs to network")
	check(Schema.category_for("log_pending_dropped") == "system", "pending drop diagnostic is system")
	check(Schema.category_for("log_limit_reached") == "system", "limit diagnostic is system")
	check(Schema.safe_code("TLS_BUNDLE_MISSING") == "TLS_BUNDLE_MISSING", "missing bundle code is registered")
	check(Schema.safe_code("TLS_BUNDLE_INVALID") == "TLS_BUNDLE_INVALID", "invalid bundle code is registered")

func _check_levels() -> void:
	check(Schema.default_level("business", {}) == "INFO", "success defaults to info")
	check(Schema.default_level("network", {"outcome":"failure"}) == "ERROR", "failure escalates to error")
	check(Schema.default_level("storage", {"outcome":"cancelled"}) == "WARN", "cancelled escalates to warn")
	check(Schema.default_level("business", {"outcome":"denied"}) == "WARN", "denied escalates to warn")
	check(Schema.default_level("system", {"phase":"error"}) == "ERROR", "error phase escalates")
	check(Schema.default_level("business", {"level":"DEBUG"}) == "INFO", "default level does not read explicit level")

func _check_defaults() -> void:
	var entry := {"event":"network_http"}
	var missing := Schema.apply_defaults(entry, "network")
	check(missing.size() == 4 and entry.has("channel") and entry.has("route"), "network defaults filled")
	check(entry.schema_missing == "channel,route,outcome,duration_ms", "schema missing recorded")
	var business := {"event":"message_queued"}
	check(Schema.apply_defaults(business, "business") == ["phase"] and business.phase == "unknown", "business phase default")

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
	check(Schema.is_trace_id(Schema.new_trace_id("net")), "trace id format")
	check(Schema.is_token(Schema.new_transaction_id(), 64), "transaction id format")

func _check_origins_for_logs() -> void:
	check(Schema.origin_for("https://example.com/auth/login?x=1") == "https://example.com", "origin drops path, query and default port")
	check(Schema.origin_for("https://www-api.u3493359.nyat.app:11664/auth/auto_login") == "https://www-api.u3493359.nyat.app:11664", "origin keeps custom port")
	check(Schema.origin_for("http://127.0.0.1:60030/x") == "http://127.0.0.1:60030", "origin keeps loopback port")
	check(Schema.origin_for("https://user:pass@host.example:443/x") == "https://host.example", "origin strips userinfo and default port")
	check(Schema.origin_for("https://[::1]:443/x") == "https://[::1]", "origin keeps ipv6 literal")
	check(Schema.origin_for("host.example/x").is_empty(), "origin requires scheme")
	check(Schema.origin_for("https://host.example:abc/x").is_empty(), "origin rejects invalid port")

func _check_tls_annotation() -> void:
	var annotated := EngineSink.tls_detail("TLS handshake error: -9984")
	check(int(annotated.get("mbedtls_code", 0)) == -9984, "mbedtls code extracted")
	check(str(annotated.get("detail", "")).contains("MBEDTLS_ERR_X509_CERT_VERIFY_FAILED"), "mbedtls name annotated")
	check(int(EngineSink.tls_detail("something else").get("mbedtls_code", 0)) == 0, "non-tls rationale untouched")
	check(str(EngineSink.tls_detail("TLS handshake error: -1").get("detail", "")) == "TLS handshake error: -1", "unknown tls code keeps raw text")


func _check_tls_cause() -> void:
	check(EngineSink.tls_cause(-9984) == "certificate_verify_failed", "certificate verification cause")
	check(EngineSink.tls_cause(-29312) == "peer_verify_failed", "peer verification cause")
	check(EngineSink.tls_cause(-1) == "", "unknown tls code has no cause")

func _check_origins() -> void:
	check(Schema.is_origin("client") and not Schema.is_origin("local"), "origin enum")
	check(Schema.infer_origin("network_http", {"outcome":"failure", "status":0}, "network") == "network", "status 0 maps to network")
	check(Schema.infer_origin("network_http", {"outcome":"failure", "status":503}, "network") == "server", "5xx maps to server")
	check(Schema.infer_origin("network_http", {"outcome":"success", "status":200}, "network") == "none", "success has no fault origin")
	check(Schema.infer_origin("network_ws_auth", {"outcome":"denied", "reason_code":"AUTH_REJECTED"}, "network") == "server", "ws auth rejection maps to server")
	check(Schema.infer_origin("network_ws_auth", {"outcome":"denied", "reason_code":"INSECURE_SERVER"}, "network") == "client", "ws insecure server maps to client")
	check(Schema.infer_origin("message_error", {"code":"CACHE_WRITE_FAILED"}, "business") == "client", "cache failure maps to client")
	check(Schema.infer_origin("message_error", {"code":"AUTH_REJECTED"}, "business") == "server", "auth rejection maps to server")
	check(Schema.infer_origin("message_error", {"code":"REMOTE_AUDIO_ERROR"}, "business") == "upstream", "remote TTS maps to upstream")
	check(Schema.infer_origin("message_error", {"code":"TIMEOUT"}, "business") == "network", "timeout maps to network")
	check(Schema.infer_origin("ui_error_shown", {"code":"UI_ERROR", "outcome":"failure"}, "system") == "client", "UI error maps to client")
	check(Schema.infer_origin("log_limit_reached", {"code":"LOG_LIMIT_REACHED", "outcome":"failure"}, "system") == "client", "log drop maps to client")
	check(Schema.infer_origin("system_tls_trust", {"outcome":"failure", "code":"TLS_BUNDLE_MISSING"}, "system") == "client", "missing CA bundle maps to client")
	check(Schema.infer_origin("system_tls_trust", {"outcome":"success", "code":"OK"}, "system") == "none", "successful trust snapshot has no fault origin")
