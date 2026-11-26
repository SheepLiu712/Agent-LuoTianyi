extends SceneTree
var failures: Array[String] = []
func check(ok: bool,label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ",label)
func _initialize() -> void:
	run.call_deferred()
func run() -> void:
	var theme: Theme = load("res://theme/app_theme.tres")
	check(theme.has_stylebox("panel","AppSurface"),"application surfaces use theme resources")
	check(theme.has_stylebox("normal","TerminalSurface"),"log terminal has a dark content surface")
	var frost := preload("res://src/ui/frost_surface.gd").new()
	frost.material = load("res://theme/frost_popup.tres").duplicate()
	check(frost is ColorRect and frost.material is ShaderMaterial, "frost uses a Godot control and material")
	frost.blur_enabled = false
	root.add_child(frost)
	check(frost.material == null and frost.color.a == 1.0, "disabled blur falls back to readable solid color")
	frost.queue_free()
	var audio = load("res://scenes/ui/chat/message_audio.tscn").instantiate()
	root.add_child(audio)
	var wave = audio.get_node("%Wave")
	check(wave is Control and wave.get_child_count() == 0, "waveform uses single custom-drawn control without redundant bar children")
	wave.values = PackedFloat32Array([.2, .8])
	wave.progress = .5
	check(wave.bar_count() == 2 and wave.bar_color(0, 2) == wave.played_color and wave.bar_color(1, 2) == wave.remaining_color, "waveform data updates control appearance")
	audio.queue_free()
	await process_frame
	print("Visual surfaces: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
