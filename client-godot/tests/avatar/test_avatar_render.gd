extends SceneTree
## 真实 GPU 渲染门槛：登录态的角色区不能变成整块黑色剪影。

const AvatarPanel := preload("res://scenes/avatar/avatar_panel.tscn")
const ATLAS := "res://assets/live2d/luo/Textures_.png"
var failures: Array[String] = []


func _initialize() -> void:
	run.call_deferred()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func _black_ratio(image: Image, area: Rect2i) -> float:
	var total := 0
	var dark := 0
	for y in range(maxi(0, area.position.y), mini(image.get_height(), area.end.y)):
		for x in range(maxi(0, area.position.x), mini(image.get_width(), area.end.x)):
			var color := image.get_pixel(x, y)
			if color.a < 0.5:
				continue
			total += 1
			if color.r + color.g + color.b < 0.15:
				dark += 1
	return 0.0 if total == 0 else float(dark) / float(total)


func run() -> void:
	if DisplayServer.get_name() == "headless":
		print("Avatar render: SKIP (requires GPU)")
		quit(2)
		return
	root.size = Vector2i(1280, 800)
	var panel = AvatarPanel.instantiate()
	root.add_child(panel)
	panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	panel.position = Vector2.ZERO
	panel.size = Vector2(430, 760)
	for _frame in 30:
		await process_frame
	check(panel.avatar.get_status().loaded, "real Live2D model loads")
	var atlas := load(ATLAS) as Texture2D
	check(atlas != null and atlas.get_image().has_mipmaps(), "atlas has a complete mip chain")
	await RenderingServer.frame_post_draw
	var image := root.get_texture().get_image()
	var stage: Rect2 = panel.get_node("%Stage").get_global_rect()
	var ratio := _black_ratio(image, Rect2i(Vector2i(stage.position), Vector2i(stage.size)))
	check(ratio < 0.03, "avatar area is not a black silhouette: %.4f" % ratio)
	panel.queue_free()
	await process_frame
	print("Avatar render: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
