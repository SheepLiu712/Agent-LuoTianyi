extends Node
## 只读连通性探测：先测公网基线，再测目标服务器。
## 只复用客户端自身的 HTTPRequest/TLS 栈，不写档案、不改会话状态。

const Schema = preload("res://src/storage/log_schema.gd")
const Events = preload("res://src/storage/log_events.gd")
const JsonRequest = preload("res://src/network/json_request.gd")
const ServerAddress = preload("res://src/domain/server_address.gd")

const TARGET_ROUTE := "/auth/public_key"
const PROBE_TIMEOUT := 5.0
const PROBE_BODY_LIMIT := 64 * 1024

var _logger: RefCounted
var _baseline_url := ""
var _generation := 0
var _active: Node

func _init(logger: RefCounted = null, baseline_url: String = "") -> void:
	_logger = logger
	_baseline_url = baseline_url.strip_edges()

func run(base: String) -> Dictionary:
	var generation := begin()
	var address := ServerAddress.normalize(base)
	if address.is_empty():
		var invalid := {"ok":false, "stage":"INVALID", "code":"INVALID_INPUT",
			"detail":"", "duration_ms":0, "http_status":0, "origin":""}
		var rejected := {"ok":false, "baseline":invalid, "target":invalid,
			"verdict":"invalid_address", "duration_ms":0}
		Events.probe(_logger, rejected)
		return rejected
	if not ServerAddress.allows_insecure(address):
		var insecure := {"ok":false, "stage":"INSECURE", "code":"INSECURE_SERVER",
			"detail":"服务器地址必须使用 HTTPS（仅回环地址允许 HTTP）", "duration_ms":0,
			"http_status":0, "origin":Schema.origin_for(address)}
		var blocked := {"ok":false, "baseline":insecure, "target":insecure,
			"verdict":"insecure_address", "duration_ms":0}
		Events.probe(_logger, blocked)
		return blocked
	var started := Time.get_ticks_usec()
	var baseline := {"ok":true, "stage":"SKIPPED", "code":"OK", "detail":"", "duration_ms":0, "http_status":0, "origin":""}
	if not _baseline_url.is_empty():
		baseline = await _request(_baseline_url, generation)
	var target := await _request(address + TARGET_ROUTE, generation)
	if generation != _generation:
		return {"ok":false, "cancelled":true, "baseline":baseline, "target":target,
			"verdict":"cancelled", "duration_ms":_elapsed(started)}
	var result := {"ok":bool(baseline.get("ok", false)) and bool(target.get("ok", false)),
		"baseline":baseline, "target":target, "verdict":verdict_for(baseline, target),
		"duration_ms":_elapsed(started)}
	Events.probe(_logger, result)
	return result

## 单端点探测，供测试与后续扩展使用。
func probe_one(url: String) -> Dictionary:
	var generation := begin()
	return await _request(url, generation)

func begin() -> int:
	_generation += 1
	if is_instance_valid(_active) and _active.has_method("cancel"):
		_active.cancel()
	_active = null
	return _generation

func cancel() -> void:
	_generation += 1
	if is_instance_valid(_active) and _active.has_method("cancel"):
		_active.cancel()
	_active = null

func _request(url: String, generation: int) -> Dictionary:
	var origin := Schema.origin_for(url)
	var started := Time.get_ticks_usec()
	var request := JsonRequest.new(PROBE_TIMEOUT, PROBE_BODY_LIMIT, _logger)
	add_child(request)
	_active = request
	# 探测只关心链路是否打通，不要求响应是 JSON。
	var response: Dictionary = await request.send(url, HTTPClient.METHOD_GET, {}, PackedStringArray(), false)
	if is_instance_valid(request):
		request.queue_free()
	if _active == request:
		_active = null
	var duration := _elapsed(started)
	if generation != _generation:
		return {"ok":false, "stage":"CANCELLED", "code":"CANCELLED", "detail":"",
			"duration_ms":duration, "http_status":0, "origin":origin}
	var status := int(response.get("status", 0))
	var detail := str(response.get("detail", ""))
	return {"ok":status > 0, "stage":stage_for(detail, status), "code":str(response.get("code", "NETWORK_ERROR")),
		"detail":detail, "duration_ms":duration, "http_status":status, "origin":origin}

## 把 HTTPRequest 的失败枚举归到链路的具体一段；拿到任何 HTTP 状态都算走到 HTTP。
static func stage_for(detail: String, status: int = 0) -> String:
	if status > 0:
		return "HTTP"
	if detail == "RESULT_CANT_RESOLVE":
		return "DNS"
	if detail == "RESULT_CANT_CONNECT" or detail == "RESULT_CONNECTION_ERROR":
		return "TCP"
	if detail == "RESULT_TLS_HANDSHAKE_ERROR":
		return "TLS"
	if detail == "RESULT_TIMEOUT":
		return "TIMEOUT"
	if detail.begins_with("RESULT_"):
		return "HTTP"
	return "UNKNOWN"

static func verdict_for(baseline: Dictionary, target: Dictionary) -> String:
	var baseline_ok := bool(baseline.get("ok", false))
	var target_ok := bool(target.get("ok", false))
	if str(baseline.get("stage", "")) == "SKIPPED":
		return "ok" if target_ok else "target_only_fail"
	if baseline_ok and target_ok:
		return "ok"
	if baseline_ok:
		return "target_only_fail"
	if target_ok:
		return "baseline_fail"
	return "both_fail"

static func _elapsed(started_usec: int) -> int:
	return int((Time.get_ticks_usec() - started_usec) / 1000)
