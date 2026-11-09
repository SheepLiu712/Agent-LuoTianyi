extends Node
## 单请求历史抓取：一次只在途一个请求，用 generation 让旧结果失效。
## 只做「发一次、失败最多再试一次」；重试资格由策略决定，
## 是否继续翻页、要不要落库都属于上层，不在这里堆状态。

const Policy = preload("res://src/session/history_sync_policy.gd")

const RETRY_DELAY := 1.0

var _api: Node
var _generation := 0


func _init(api: Node) -> void:
	_api = api
	if api.get_parent() == null:
		add_child(api)


func cancel() -> void:
	_generation += 1
	_api.cancel()


func fetch(session: Dictionary, end_index: int, count: int = Policy.PAGE_SIZE) -> Dictionary:
	_generation += 1
	var generation := _generation
	var response: Dictionary = await _api.fetch_page(session, end_index, count)
	if generation != _generation:
		return _cancelled()
	if response.ok or not Policy.retryable(str(response.code), int(response.status)):
		return response
	return await _retry(session, end_index, count, generation)


func _retry(session: Dictionary, end_index: int, count: int, generation: int) -> Dictionary:
	await get_tree().create_timer(RETRY_DELAY).timeout
	if generation != _generation:
		return _cancelled()
	var response: Dictionary = await _api.fetch_page(session, end_index, count)
	return _cancelled() if generation != _generation else response


static func _cancelled() -> Dictionary:
	return {"ok": false, "code": "CANCELLED", "status": 0, "data": {}}
