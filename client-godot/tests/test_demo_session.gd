extends SceneTree
const Session = preload("res://src/preview/demo_session.gd")
var failures: Array[String] = []

func check(ok: bool, description: String) -> void:
	if not ok:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	var session = Session.new()
	check(session.select_scenario("empty"), "empty scenario accepted")
	check(session.submit_text(" \n\t").is_empty(), "blank rejected")
	check(session.get_messages().is_empty(), "blank has no side effect")
	var first: String = session.submit_text("  你好\n第二行  ")
	var second: String = session.submit_text("继续输入")
	check(not first.is_empty() and first != second, "stable unique local IDs")
	var messages: Array[Dictionary] = session.get_messages()
	check(messages.size() == 2, "send appends two messages")
	if messages.size() == 2:
		check(messages[0].text == "  你好\n第二行  ", "original text preserved")
		check(messages[0].status == "sending", "new send pending")
		messages[0].text = "mutated"
		check(session.get_messages()[0].text != "mutated", "snapshot isolated")
	check(session.settle(first, true), "send can succeed")
	check(not session.settle(first, false), "duplicate completion ignored")
	check(session.settle(second, false), "send can fail")
	if session.get_messages().size() == 2:
		check(session.get_messages()[1].status == "failed", "failure visible")
	var snapshot: Array[Dictionary] = session.get_messages()
	check(not session.select_scenario("invalid"), "unknown scenario rejected")
	check(snapshot == session.get_messages(), "bad scenario preserves content")
	check(session.select_scenario("disconnected"), "offline scenario accepted")
	check(session.submit_text("保留草稿").is_empty(), "offline refuses simulated send")
	check(session.select_scenario("empty"), "scenario reset")
	var third: String = session.submit_text("new")
	check(third != first and third != second, "IDs survive scenario reset")
	check(not session.settle(second, true), "stale completion ignored")
	check(session.select_scenario("conversation"), "conversation accepted")
	check(session.get_messages().size() >= 6, "representative fixtures loaded")
	print("Demo session: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
