extends SceneTree
const Probe = preload("res://src/network/connectivity_probe.gd")
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	_check_stages()
	_check_verdicts()
	var probe = Probe.new(null)
	root.add_child(probe)
	await _check_closed_port(probe)
	await _check_invalid_address(probe)
	probe.queue_free()
	await process_frame
	print("Connectivity probe: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)

func _check_stages() -> void:
	check(Probe.stage_for("RESULT_CANT_RESOLVE") == "DNS", "dns failure maps to resolve stage")
	check(Probe.stage_for("RESULT_CANT_CONNECT") == "TCP", "refused connection maps to tcp stage")
	check(Probe.stage_for("RESULT_CONNECTION_ERROR") == "TCP", "connection error maps to tcp stage")
	check(Probe.stage_for("RESULT_TLS_HANDSHAKE_ERROR") == "TLS", "tls failure is isolated from tcp")
	check(Probe.stage_for("RESULT_TIMEOUT") == "TIMEOUT", "timeout keeps its own stage")
	check(Probe.stage_for("RESULT_NO_RESPONSE") == "HTTP", "no response counts as http stage")
	check(Probe.stage_for("", 200) == "HTTP", "any http status counts as http stage")
	check(Probe.stage_for("", 0) == "UNKNOWN", "plain failure without detail is unknown")

func _check_verdicts() -> void:
	var ok := {"ok":true}
	var bad := {"ok":false}
	check(Probe.verdict_for(ok, ok) == "ok", "both endpoints ok")
	check(Probe.verdict_for(ok, bad) == "target_only_fail", "only target fails")
	check(Probe.verdict_for(bad, ok) == "baseline_fail", "only baseline fails")
	check(Probe.verdict_for(bad, bad) == "both_fail", "both endpoints fail")

func _check_closed_port(probe: Node) -> void:
	var result: Dictionary = await probe.probe_one("http://127.0.0.1:1")
	check(not bool(result.get("ok", true)), "closed port is not reachable")
	check(str(result.get("stage", "")) in ["TCP", "TIMEOUT"], "closed port reports tcp or timeout stage: %s" % result)
	check(str(result.get("origin", "")) == "http://127.0.0.1:1", "probe keeps the probed origin")

func _check_invalid_address(probe: Node) -> void:
	var result: Dictionary = await probe.run("")
	check(str(result.get("verdict", "")) == "invalid_address", "empty address is rejected before any request")
	check(str(result.get("baseline", {}).get("stage", "")) == "INVALID", "invalid probe marks first line invalid")
