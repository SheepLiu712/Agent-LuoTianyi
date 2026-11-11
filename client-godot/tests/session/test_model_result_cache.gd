extends SceneTree
## 模型结果缓存必须有界；淘汰旧结果不能丢掉在途占位。

const Executor = preload("res://src/session/model_executor.gd")

var failures: Array[String] = []


func check(ok: bool, label: String) -> void:
	if ok:
		return
	failures.append(label)
	print("FAIL: ", label)


func _initialize() -> void:
	var executor = Executor.new(null)
	for index in 300:
		var id := "request-%d" % index
		executor._results[id] = {"request_id":id, "content":"cached"}
		executor._result_order.append(id)
	executor._results["inflight"] = {}
	executor._trim_results()
	var completed := 0
	for id in executor._results:
		if not executor._results[id].is_empty():
			completed += 1
	check(completed == Executor.MAX_COMPLETED_RESULTS, "completed results stay bounded")
	check(not executor._results.has("request-0"), "oldest completed result is evicted")
	check(executor._results.has("request-299"), "newest completed result is retained")
	check(executor._results.has("inflight"), "in-flight placeholder is never evicted")
	executor.free()
	print("Model result cache: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
