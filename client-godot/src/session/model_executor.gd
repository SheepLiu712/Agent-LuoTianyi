extends Node
const ServerAddress = preload("res://src/domain/server_address.gd")
const Attachment = preload("res://src/media/image_attachment.gd")
signal completed(response: Dictionary)
const Http = preload("res://src/network/json_request.gd")
## 只缓存近期已完成的请求，避免长时间会话把全部模型正文留在内存里。
## 在途请求用空字典占位，独立于该上限，不会被淘汰。
const MAX_COMPLETED_RESULTS := 256
var _settings: Node
var _logger: RefCounted
var _timeout: float
var _generation := 0
var _active := false
var _requests: Array[Node] = []
var _results := {}
var _result_order: Array[String] = []

func _init(settings: Node,logger: RefCounted = null,timeout: float = 120.0) -> void:
	_settings = settings
	_logger = logger
	_timeout = timeout

func start() -> void:
	stop()
	_active = true

func stop() -> void:
	_active = false
	_generation += 1
	for request in _requests.duplicate():
		request.cancel()
	_results.clear()
	_result_order.clear()

func enabled_types() -> Array[String]:
	return _settings.enabled_types()

func submit(payload: Dictionary) -> void:
	var id: Variant = payload.get("request_id")
	if not _active or not id is String or id.is_empty():
		return
	if _results.has(id):
		if not _results[id].is_empty():
			completed.emit(_results[id].duplicate(true))
		return
	_results[id] = {}
	var generation := _generation
	var result := await _execute(payload.duplicate(true),_settings.get_config(str(payload.get("type",""))))
	if generation != _generation or not _active:
		return
	var response := {"request_id":id}
	if result.ok:
		response.merge({"content":result.content,"usage":result.usage})
	else:
		response.error = result.code
		response.detail = str(result.get("detail", ""))
	_results[id] = response
	_result_order.append(id)
	_trim_results()
	completed.emit(response.duplicate(true))


## 淘汰最旧的已完成结果；只保留少量近期结果用于同一 request_id 的幂等重放。
func _trim_results() -> void:
	var completed_count := 0
	for id in _results:
		if not _results[id].is_empty():
			completed_count += 1
	while completed_count > MAX_COMPLETED_RESULTS and not _result_order.is_empty():
		var oldest: String = _result_order.pop_front()
		if not _results.has(oldest) or _results[oldest].is_empty():
			continue
		_results.erase(oldest)
		completed_count -= 1

func test_config(type_id: String,config: Dictionary) -> Dictionary:
	var snapshot := config.duplicate(true)
	snapshot.enabled = true
	var generation := _generation
	var result := await _execute({"type":type_id,"model_kind":snapshot.get("model_kind"),"prompt":"Reply with a JSON object containing ok=true.","params":{},"use_json":snapshot.get("model_capabilities",{}).get("can_use_json",false),"enable_thinking":false},snapshot)
	return {"ok":false,"code":"CANCELLED","detail":"model test was cancelled"} if generation != _generation else {"ok":result.ok,"code":result.code,"detail":str(result.get("detail", ""))}

func _execute(request: Dictionary,config: Dictionary) -> Dictionary:
	var valid := _validate_request(request, config)
	if not valid.ok:
		return valid
	var use_json: bool = request.get("use_json",false)
	var thinking: bool = request.get("enable_thinking",false)
	var checked := _validate_media(request, config, use_json, thinking)
	if not checked.ok:
		return checked
	var image: String = request.get("image_base64", "")
	var params: Dictionary = request.get("params",{}).duplicate(true)
	params.merge(config.params,true)
	if (params.has("stream") and (not params.stream is bool or params.stream)) or params.has("stream_options"):
		return _failure("STREAMING_NOT_SUPPORTED")
	if _requests.size() >= 8:
		return _failure("MODEL_BUSY")
	var body := _request_body(request, config, params, image, thinking, use_json)
	var http := Http.new(_timeout)
	add_child(http)
	_requests.append(http)
	var started := Time.get_ticks_msec()
	_log("sending","OK",str(request.type),0)
	var result: Dictionary = await http.send(ServerAddress.normalize(config.base_url)+"/chat/completions",HTTPClient.METHOD_POST,body,["Authorization: Bearer "+config.api_key])
	_requests.erase(http)
	http.queue_free()
	var answer := _parse(result,use_json)
	_log("complete" if answer.ok else "error",answer.code,str(request.type),Time.get_ticks_msec()-started,
		str(answer.get("detail", "")))
	return answer
func _parse(result: Dictionary,use_json: bool) -> Dictionary:
	if not result.ok:
		return _failure(result.code, str(result.get("detail", "")))
	var data: Dictionary = result.data
	if not data.get("choices") is Array or data.choices.is_empty() or not data.choices[0] is Dictionary or not data.choices[0].get("message") is Dictionary or not data.choices[0].message.get("content") is String:
		return _failure("INVALID_RESPONSE", "choices[0].message.content is missing")
	var content: String = data.choices[0].message.content
	if use_json and JSON.new().parse(content) != OK:
		return _failure("INVALID_JSON", "model content is not valid JSON")
	var usage := _response_usage(data)
	return {"ok":true,"code":"OK","content":content,"usage":usage}
func _failure(code: String, detail: String = "") -> Dictionary:
	return {"ok":false,"code":code,"detail":detail}

func _log(phase: String,code: String,type_id: String,elapsed: int,detail: String = "") -> void:
	if _logger != null:
		_logger.record_as("business", "model_execution", {"operation":"model_execution",
			"outcome":"success" if code == "OK" else "failure", "phase":phase, "code":code,
			"model_type":type_id, "duration_ms":elapsed, "detail":detail,
			"level":"INFO" if code == "OK" else "ERROR"})

func _exit_tree() -> void:
	stop()

func _validate_request(request: Dictionary, config: Dictionary) -> Dictionary:
	if not _active:
		return _failure("CANCELLED", "model executor is stopped")
	if config.is_empty() or config.get("enabled") != true:
		return _failure("MODEL_DISABLED", "model is disabled or has no config")
	var valid: Dictionary = _settings.validate(str(request.get("type","")),config)
	if not valid.ok:
		return _failure(valid.code, str(valid.get("detail", "")))
	if request.get("model_kind") != config.model_kind:
		return _failure("MODEL_KIND_MISMATCH", "request model_kind does not match config")
	if not request.get("prompt") is String or not request.get("params",{}) is Dictionary or not request.get("use_json",false) is bool or not request.get("enable_thinking",false) is bool:
		return _failure("INVALID_INPUT", "prompt, params, use_json or enable_thinking has an invalid type")
	return {"ok":true}

func _validate_media(request: Dictionary, config: Dictionary, use_json: bool, thinking: bool) -> Dictionary:
	if (use_json and not config.model_capabilities.can_use_json) or (thinking and not config.model_capabilities.can_enable_thinking):
		return _failure("MODEL_CAPABILITY_MISMATCH", "model does not support requested JSON or thinking mode")
	var image: Variant = request.get("image_base64","")
	if not image is String or (not image.is_empty() and config.model_kind != "vlm"):
		return _failure("MODEL_KIND_MISMATCH", "image input requires a VLM model")
	if not image.is_empty():
		var image_check: Dictionary = Attachment.from_data_uri(image)
		if not image_check.ok:
			return _failure(image_check.code, str(image_check.get("detail", "image attachment is invalid")))
	return {"ok":true}

func _request_body(request: Dictionary, config: Dictionary, params: Dictionary, image: String, thinking: bool, use_json: bool) -> Dictionary:
	var body := {"max_tokens":4096,"temperature":0.7,"top_p":0.9}
	body.merge(params,true)
	body.model = config.model
	body.stream = false
	body.messages = [{"role":"system","content":request.prompt}] if image.is_empty() else [{"role":"user","content":[{"type":"text","text":request.prompt},{"type":"image_url","image_url":{"url":image,"detail":"auto"}}]}]
	if thinking:
		body.enable_thinking = true
	if use_json:
		body.response_format = {"type":"json_object"}
	return body

func _response_usage(data: Dictionary) -> Dictionary:
	var usage := {}
	if data.get("usage") is Dictionary:
		for key in ["prompt_tokens","completion_tokens","total_tokens"]:
			var value: Variant = data.usage.get(key)
			if (value is float or value is int) and is_finite(float(value)) and value >= 0:
				usage[key] = int(value)
	return usage
