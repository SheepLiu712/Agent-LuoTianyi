extends SceneTree

const Lifecycle = preload("res://src/application/account_lifecycle.gd")
var failures: Array[String] = []

class Controller extends Node:
	var starts := 0
	var stops := 0
	var result: Error = OK
	func start(_value: Dictionary) -> Error:
		starts += 1
		return result
	func stop() -> void:
		stops += 1

class Capability extends Resource:
	var starts := 0
	var stops := 0
	var result: Error = ERR_UNAVAILABLE
	func start(_context: Dictionary) -> Error:
		starts += 1
		return result
	func stop() -> void:
		stops += 1

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		print("FAIL: ", label)

func _initialize() -> void:
	var chat := Controller.new()
	var models := Controller.new()
	var dynamics := Controller.new()
	root.add_child(chat)
	root.add_child(models)
	root.add_child(dynamics)
	var optional := Capability.new()
	var lifecycle := Lifecycle.new(chat, models, dynamics, optional)
	var session := {"server":"https://example.invalid", "username":"alice", "message_token":"token"}
	chat.result = ERR_INVALID_PARAMETER
	check(lifecycle.start(session) == ERR_INVALID_PARAMETER, "transport failure is returned")
	check(lifecycle.get_context().is_empty(), "failed activation clears account context")
	check(chat.stops > 0 and models.stops > 0 and dynamics.stops > 0, "failed activation rolls controllers back")
	chat.result = OK
	check(lifecycle.start(session) == OK, "valid activation succeeds")
	check(not lifecycle.get_context().is_empty() and optional.starts == 1, "optional unavailable capability does not block chat")
	var generation: int = lifecycle.get_context().generation
	check(lifecycle.start(session) == OK and lifecycle.get_context().generation == generation, "duplicate activation is idempotent")
	lifecycle.stop()
	check(lifecycle.get_context().is_empty() and optional.stops == 2, "stop clears context and stops capabilities")
	lifecycle.stop()
	check(optional.stops == 2, "stop is safe when repeated")
	chat.queue_free()
	models.queue_free()
	dynamics.queue_free()
	print("Account lifecycle: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
