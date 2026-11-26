extends RefCounted
## 历史分页策略：只放「什么算合法一页 / 什么错值得重试 / 还要不要继续补」。
## 这些判断被同步控制器与抓取器共用，放在纯函数里，
## 既避免状态机里散落魔法数字，也让每个判断都能单独测。

## 每批 30 条：首屏与上翻统一口径。
const PAGE_SIZE := 30

const RETRYABLE_CODES := ["NETWORK_ERROR", "TIMEOUT"]
const RETRYABLE_STATUS := [408, 429]


## 服务端返回的 start_index 必须与本轮请求预期一致，避免分页漂移被静默接受。
static func valid_bounds(end_index: int, start: Variant, size: int, count: int) -> bool:
	if not _valid_start(start) or size < 0 or size > count:
		return false
	if end_index < 0:
		return _valid_first(int(start), size, count)
	return _valid_older(end_index, int(start), size)


## 首批：起点为 0，或整页取满；空页且 start=0 合法。
static func _valid_first(start: int, size: int, count: int) -> bool:
	return start == 0 or size == count


## 更早页：必须紧接在请求边界之前，且不能声明越过 0 的负区间。
static func _valid_older(end_index: int, start: int, size: int) -> bool:
	if end_index <= 0 or size <= 0:
		return false
	return start == maxi(0, end_index - PAGE_SIZE) and start + size == end_index


## 只有传输层与限流/服务端瞬时错误值得自动重试；鉴权与格式错误不重试。
static func retryable(code: String, status: int) -> bool:
	if code in RETRYABLE_CODES or status in RETRYABLE_STATUS:
		return true
	return status >= 500 and status <= 599


## 还有更早的历史没接上，且没有被暂停，才继续自动补齐。
static func continue_catchup(state: Dictionary) -> bool:
	if bool(state.get("paused", false)) or bool(state.get("joined", false)):
		return false
	if not bool(state.get("has_baseline", false)):
		return false
	return int(state.get("next_end", -1)) > 0


static func _valid_start(value: Variant) -> bool:
	if not (value is int or value is float):
		return false
	return is_finite(float(value)) and value >= 0 and value == floor(float(value))
