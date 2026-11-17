extends SceneTree

const Fallback = preload("res://src/avatar/expression_fallback.gd")

var failures: Array[String] = []
var applied: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _make(delay_seconds: float = 0.1) -> Node:
	var fallback := Fallback.new()
	root.add_child(fallback)
	fallback.setup(func(command: String): applied.append(command), delay_seconds)
	return fallback


func run() -> void:
	check(Fallback.DEFAULT_EXPRESSION == "normal", "fallback returns the normal expression")
	check(is_equal_approx(Fallback.DEFAULT_DELAY_SECONDS, 1.0), "fallback waits one second")
	await _test_voice_end_reset()
	await _test_new_expression_cancels_old_timer()
	await _test_expression_without_voice_still_resets()
	await _test_cancel_releases_pending_reset()
	print("Expression fallback: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _test_voice_end_reset() -> void:
	applied.clear()
	var fallback := _make(0.08)
	fallback.expression_requested()
	fallback.set_speaking(true)
	await create_timer(0.12).timeout
	check(applied.is_empty(), "speaking holds the current expression")
	fallback.set_speaking(false)
	fallback.voice_idle()
	await create_timer(0.04).timeout
	check(applied.is_empty(), "reset waits after playback ends")
	await create_timer(0.08).timeout
	check(applied == ["normal"], "voice end restores the default expression")
	fallback.queue_free()
	await process_frame


func _test_new_expression_cancels_old_timer() -> void:
	applied.clear()
	var fallback := _make(0.1)
	fallback.expression_requested()
	fallback.voice_idle()
	await create_timer(0.06).timeout
	fallback.expression_requested()
	fallback.voice_idle()
	await create_timer(0.06).timeout
	check(applied.is_empty(), "a new expression cancels the pending reset")
	await create_timer(0.08).timeout
	check(applied == ["normal"], "the latest expression still resets once")
	fallback.queue_free()
	await process_frame


func _test_expression_without_voice_still_resets() -> void:
	applied.clear()
	var fallback := _make(0.06)
	fallback.expression_requested()
	fallback.voice_idle()
	await create_timer(0.1).timeout
	check(applied == ["normal"], "an expression without voice also falls back")
	fallback.queue_free()
	await process_frame


func _test_cancel_releases_pending_reset() -> void:
	applied.clear()
	var fallback := _make(0.06)
	fallback.expression_requested()
	fallback.voice_idle()
	fallback.cancel()
	await create_timer(0.1).timeout
	check(applied.is_empty() and not fallback.is_pending(), "cancel drops the pending fallback")
	fallback.queue_free()
	await process_frame
