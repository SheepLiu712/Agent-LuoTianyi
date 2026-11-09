# 函数索引

2026-10-01 按 `f1cb9e2` 从当前 `client-godot/src` 的 99 个 GDScript 文件提取。索引顶层 `signal`、`const`、`class_name`、`func`、`static func` 声明；行号对应本次源码快照。

从功能开始阅读请看 [场景与控件说明](场景与控件说明.md)，开发工具入口见 [测试与验证](tests-and-validation.md)。新增辅助方法是重构后的细分步骤，不自动代表新业务能力。

## [client-godot/src/application.gd](../client-godot/src/application.gd)

- `14` **常量** `const Services = preload("res://src/composition/application_services.gd")`
- `25` **常量** `const Avatar = preload("res://scenes/avatar/avatar_panel.tscn")`
- `26` **常量** `const ChatView = preload("res://scenes/ui/chat_view.tscn")`
- `70` **公开接口** `func setup(account_session: Node = null, layout_path: String = "user://window_layout.cfg", external_links: RefCounted = null) -> void:`
- `78` **生命周期/引擎回调** `func _ready() -> void:`
- `197` **内部流程** `func _account_changed(state: Dictionary) -> void:`
- `244` **内部流程** `func _resize_split() -> void:`
- `248` **内部流程** `func _apply_workspace_style() -> void:`
- `258` **内部流程** `func _resize_window(target: Vector2i, minimum: Vector2i) -> void:`
- `266` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `277` **内部流程** `func _open_settings(kind: String) -> void:`
- `282` **内部流程** `func _request_close(action: String) -> void:`
- `285` **内部流程** `func _restore_settings(settings: Resource) -> void:`
- `294` **内部流程** `func _capture_or_resume() -> void:`
- `309` **内部流程** `func _show_signed_out() -> void:`

## [client-godot/src/application/account_lifecycle.gd](../client-godot/src/application/account_lifecycle.gd)

- `2` **常量** `const Scope = preload("res://src/domain/account_scope.gd")`
- `15` **内部流程** `func _init(chat: Node, models: Node, dynamics: Node, appearance: Resource = null, world: Resource = null, devices: Resource = null) -> void:`
- `23` **公开接口** `func start(session: Dictionary) -> Error:`
- `52` **公开接口** `func get_context() -> Dictionary:`
- `55` **公开接口** `func stop() -> void:`

## [client-godot/src/application/ui_style.gd](../client-godot/src/application/ui_style.gd)

- `4` **信号** `signal style_changed`
- `6` **常量** `const SECTION := "ui"`
- `7` **常量** `const THEME_PATH := "res://theme/app_theme.tres"`
- `14` **公开接口** `func configure(store: Resource) -> void:`
- `24` **公开接口** `func save_preferences(style: String, icons: String) -> Error:`
- `48` **公开接口** `func is_crystal() -> bool:`
- `51` **公开接口** `func uses_emoji() -> bool:`
- `55` **公开接口** `func apply_view(view: Node, icons: Dictionary = {}) -> void:`
- `59` **内部流程** `func _apply_theme() -> void:`
- `76` **公开接口** `func register_icon(button: Button, name: String) -> void:`
- `85` **内部流程** `func _refresh_icons() -> void:`
- `94` **内部流程** `func _apply_icon(button: Button, name: String) -> void:`
- `101` **公开接口** `func apply_bubble_style(stylebox: StyleBoxFlat) -> void:`
- `127` **公开接口** `func apply_surface_style(stylebox: StyleBoxFlat) -> void:`
- `139` **公开接口** `func apply_post_style(stylebox: StyleBoxFlat, selected: bool) -> void:`
- `151` **公开接口** `func apply_input_style(stylebox: StyleBoxFlat) -> void:`
- `165` **内部流程** `func _apply_shadow(stylebox: StyleBoxFlat) -> void:`
- `175` **内部流程** `func _apply_panel_themes() -> void:`

## [client-godot/src/application/window_coordinator.gd](../client-godot/src/application/window_coordinator.gd)

- `2` **信号** `signal exit_requested`
- `3` **信号** `signal logout_requested`
- `16` **内部流程** `func _init(host: Control, dialog: Window, images: Node, geometry: Resource, settings_factory: Callable, dynamics_factory: Callable, chat_dirty: Callable) -> void:`
- `27` **公开接口** `func open(kind: String) -> void:`
- `43` **公开接口** `func request_close(action: String) -> void:`
- `60` **内部流程** `func _confirmed() -> void:`
- `73` **内部流程** `func _cancel() -> void:`
- `77` **公开接口** `func close_all() -> void:`
- `86` **内部流程** `func _return_dialog() -> void:`
- `90` **公开接口** `func dispose() -> void:`
- `100` **内部流程** `func _collect_drafts() -> Array[String]:`
- `109` **内部流程** `func _show_close_dialog(action: String, settings: Variant, drafts: Array[String]) -> void:`

## [client-godot/src/avatar/avatar_driver.gd](../client-godot/src/avatar/avatar_driver.gd)

- `3` **公开接口** `func load_character(_descriptor_path: String) -> Error: return ERR_UNAVAILABLE`
- `4` **公开接口** `func load_avatar(_model_path: String, _mapping_path: String = "") -> Error: return ERR_UNAVAILABLE`
- `5` **公开接口** `func apply_expression(_command: String) -> bool: return false`
- `6` **公开接口** `func play_motion(_group: String, _index: int = 0) -> bool: return false`
- `7` **公开接口** `func set_mouth_openness(_value: float) -> void: pass`
- `8` **公开接口** `func set_gaze(_target: Vector2) -> void: pass`
- `9` **公开接口** `func hit_test(_position: Vector2) -> Array[String]: return []`
- `10` **公开接口** `func get_status() -> Dictionary:`

## [client-godot/src/avatar/avatar_framing.gd](../client-godot/src/avatar/avatar_framing.gd)

- `3` **内部流程** `func _init(settings: Resource = null) -> void:`
- `10` **公开接口** `func zoom_by(factor: float) -> void:`
- `15` **公开接口** `func pan_by(delta: Vector2, panel_size: Vector2) -> void:`
- `21` **公开接口** `func reset() -> void:`
- `26` **公开接口** `func get_transform(panel: Vector2, canvas: Vector2) -> Transform2D:`
- `33` **公开接口** `func save_settings() -> Error:`
- `40` **公开接口** `func load_settings() -> Error:`

## [client-godot/src/avatar/avatar_panel.gd](../client-godot/src/avatar/avatar_panel.gd)

- `3` **信号** `signal touched(areas: Array[String])`
- `5` **常量** `const Driver = preload("res://src/avatar/avatar_driver.gd")`
- `6` **常量** `const Framing = preload("res://src/avatar/avatar_framing.gd")`
- `8` **常量** `const Ripple := preload("res://scenes/avatar/touch_ripple.tscn")`
- `17` **公开接口** `func set_unread_dynamic(post: Dictionary) -> void:`
- `27` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `34` **内部流程** `func _apply_ui_style() -> void:`
- `47` **生命周期/引擎回调** `func _ready() -> void:`
- `76` **内部流程** `func _layout_avatar() -> void:`
- `83` **内部流程** `func _handle_pointer(event: InputEvent) -> void:`
- `88` **内部流程** `func _save() -> void:`
- `93` **生命周期/引擎回调** `func _notification(what: int) -> void:`
- `101` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `106` **内部流程** `func _handle_button(event: InputEventMouseButton) -> void:`
- `120` **内部流程** `func _handle_touch(event: InputEventMouseButton) -> void:`
- `130` **内部流程** `func _handle_motion(event: InputEventMouseMotion) -> void:`

## [client-godot/src/avatar/avatar_preview.gd](../client-godot/src/avatar/avatar_preview.gd)

- `6` **生命周期/引擎回调** `func _ready() -> void:`

## [client-godot/src/avatar/touch_ripple.gd](../client-godot/src/avatar/touch_ripple.gd)

- `3` **生命周期/引擎回调** `func _ready() -> void:`

## [client-godot/src/composition/application_services.gd](../client-godot/src/composition/application_services.gd)

- `15` **公开接口** `static func create_geometry(layout_path: String) -> Resource:`
- `18` **内部流程** `func _init(layout_path: String, runtime: Resource) -> void:`
- `25` **公开接口** `func mount(host: Node, injected_account: Node, layout_path: String, encryption: Resource, secrets: Resource, decoder_factory: Resource) -> void:`
- `46` **公开接口** `func create_settings() -> Dictionary:`
- `53` **公开接口** `func create_dynamics() -> Dictionary:`
- `59` **公开接口** `static func external_links() -> RefCounted:`

## [client-godot/src/domain/account_scope.gd](../client-godot/src/domain/account_scope.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `4` **公开接口** `static func key(server: String, username: String) -> String:`

## [client-godot/src/domain/server_address.gd](../client-godot/src/domain/server_address.gd)

- `4` **公开接口** `static func normalize(address: String) -> String:`
- `28` **内部流程** `static func _valid_host(host: String) -> bool:`
- `33` **内部流程** `static func _valid_dns_labels(host: String) -> bool:`
- `39` **内部流程** `static func _valid_numeric_host(host: String) -> bool:`
- `47` **内部流程** `static func _valid_port(port: String) -> bool:`
- `50` **内部流程** `static func _canonical_port(port: String, scheme: String) -> String:`

## [client-godot/src/extensions/appearance_service.gd](../client-godot/src/extensions/appearance_service.gd)

- `3` **信号** `signal completed(request_id: String, result: Dictionary)`
- `4` **信号** `signal state_changed(state: Dictionary)`
- `5` **公开接口** `func get_capabilities() -> Dictionary:`
- `7` **公开接口** `func start(_context: Dictionary) -> Error:`
- `9` **公开接口** `func get_state() -> Dictionary:`
- `11` **公开接口** `func request_change(_request_id: String, _character_id: String, _resource_id: String, _origin: String) -> Dictionary:`
- `13` **公开接口** `func cancel(_request_id: String) -> void:`
- `15` **公开接口** `func stop() -> void:`

## [client-godot/src/extensions/device_service.gd](../client-godot/src/extensions/device_service.gd)

- `3` **信号** `signal state_changed(state: Dictionary)`
- `4` **信号** `signal event_received(event: Dictionary)`
- `5` **信号** `signal completed(request_id: String, result: Dictionary)`
- `6` **公开接口** `func get_capabilities() -> Dictionary:`
- `8` **公开接口** `func start(_context: Dictionary) -> Error:`
- `10` **公开接口** `func request_control(_request_id: String, _device_id: String, _intent: Dictionary) -> Dictionary:`
- `12` **公开接口** `func cancel(_request_id: String) -> void:`
- `14` **公开接口** `func stop() -> void:`

## [client-godot/src/extensions/world_service.gd](../client-godot/src/extensions/world_service.gd)

- `3` **信号** `signal interaction_received(event: Dictionary)`
- `4` **信号** `signal completed(request_id: String, result: Dictionary)`
- `5` **公开接口** `func get_capabilities() -> Dictionary:`
- `7` **公开接口** `func start(_context: Dictionary) -> Error:`
- `9` **公开接口** `func apply_state(_state: Dictionary) -> Dictionary:`
- `11` **公开接口** `func request_action(_request_id: String, _action: Dictionary) -> Dictionary:`
- `13` **公开接口** `func cancel(_request_id: String) -> void:`
- `15` **公开接口** `func stop() -> void:`

## [client-godot/src/media/cache_replay.gd](../client-godot/src/media/cache_replay.gd)

- `3` **信号** `signal changed`
- `4` **信号** `signal finished(id: String, code: String)`
- `5` **信号** `signal mouth_changed(value: float)`
- `19` **内部流程** `func _init() -> void:`
- `23` **公开接口** `func start(reply_id: String, metadata: Dictionary, stream: RefCounted, factory: Resource) -> Error:`
- `38` **公开接口** `func set_volume(value: float) -> void:`
- `41` **公开接口** `func pause() -> void:`
- `48` **公开接口** `func resume() -> void:`
- `55` **公开接口** `func stop() -> void:`
- `73` **内部流程** `func _end(code: String) -> void:`
- `78` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `100` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `103` **内部流程** `func _read_more(decoded: Dictionary) -> Dictionary:`
- `115` **内部流程** `func _pump_playback(decoded: Dictionary) -> bool:`

## [client-godot/src/media/decoder_factory.gd](../client-godot/src/media/decoder_factory.gd)

- `2` **公开接口** `func create_decoder() -> RefCounted:`

## [client-godot/src/media/image_attachment.gd](../client-godot/src/media/image_attachment.gd)

- `2` **常量** `const MAX_BYTES := 6 * 1024 * 1024 - 4096`
- `3` **常量** `const MAX_SIDE := 8192`
- `4` **常量** `const MAX_PIXELS := 16000000`
- `6` **公开接口** `static func from_data_uri(uri: String) -> Dictionary:`
- `23` **公开接口** `static func from_image(image: Image) -> Dictionary:`
- `28` **公开接口** `static func from_bytes(bytes: PackedByteArray, mime: String) -> Dictionary:`
- `44` **公开接口** `static func detect_mime(bytes: PackedByteArray) -> String:`
- `50` **内部流程** `static func _dimensions_ok(image: Image) -> bool:`
- `53` **公开接口** `static func header_dimensions(bytes: PackedByteArray, mime: String) -> Dictionary:`
- `64` **内部流程** `static func _big_endian(bytes: PackedByteArray, index: int) -> int:`
- `67` **内部流程** `static func _little_endian(bytes: PackedByteArray, index: int, count: int) -> int:`
- `73` **内部流程** `static func _jpeg_dimensions(bytes: PackedByteArray) -> Dictionary:`
- `88` **内部流程** `static func _webp_dimensions(bytes: PackedByteArray) -> Dictionary:`
- `101` **内部流程** `static func _header_dimensions_ok(header: Dictionary) -> bool:`
- `105` **内部流程** `static func _is_png(bytes: PackedByteArray) -> bool:`
- `108` **内部流程** `static func _is_jpeg(bytes: PackedByteArray) -> bool:`
- `111` **内部流程** `static func _is_webp(bytes: PackedByteArray) -> bool:`
- `114` **内部流程** `static func _decode_format(image: Image, bytes: PackedByteArray, mime: String) -> Error:`
- `122` **内部流程** `static func _decode_bmp(image: Image, bytes: PackedByteArray) -> Error:`
- `126` **内部流程** `static func _next_jpeg_marker(bytes: PackedByteArray, index: int) -> int:`
- `131` **内部流程** `static func _jpeg_segment(bytes: PackedByteArray, index: int, marker: int) -> Dictionary:`
- `139` **内部流程** `static func _webp_chunk_dimensions(bytes: PackedByteArray, data: int, length: int, kind: String) -> Dictionary:`
- `148` **内部流程** `static func _vp8_dimensions(bytes: PackedByteArray, data: int, length: int) -> Dictionary:`
- `152` **内部流程** `static func _vp8l_dimensions(bytes: PackedByteArray, data: int, length: int) -> Dictionary:`

## [client-godot/src/media/reply_audio.gd](../client-godot/src/media/reply_audio.gd)

- `2` **信号** `signal message_audio_changed(id: String, state: Dictionary)`
- `3` **信号** `signal replay_finished(id: String, code: String)`
- `4` **信号** `signal receive_finished(id: String, code: String)`
- `5` **信号** `signal playback_finished(id: String, code: String)`
- `6` **信号** `signal mouth_changed(value: float)`
- `7` **信号** `signal state_changed(state: Dictionary)`
- `28` **内部流程** `func _init(logger: RefCounted = null, clock: Callable = Callable(), cache: RefCounted = null, decoder_factory: Resource = null) -> void:`
- `47` **公开接口** `func append_reply_audio(id: String, encoded: String, final: bool, audio_error: bool = false, ephemeral: bool = false) -> void:`
- `68` **公开接口** `func play_reply(id: String) -> void:`
- `73` **公开接口** `func get_state() -> Dictionary:`
- `76` **公开接口** `func set_volume(value: float) -> void:`
- `84` **公开接口** `func stop_current() -> void:`
- `94` **公开接口** `func reset() -> void:`
- `105` **内部流程** `func _log(event: String, id: String, fields: Dictionary = {}) -> void:`
- `110` **内部流程** `func _end_receive(id: String) -> void:`
- `117` **内部流程** `func _fail(id: String, code: String) -> void:`
- `128` **内部流程** `func _stop_player() -> void:`
- `137` **内部流程** `func _complete() -> void:`
- `147` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `164` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `167` **公开接口** `func set_scope(server: String, username: String) -> Error:`
- `175` **公开接口** `func get_message_audio(id: String) -> Dictionary:`
- `184` **公开接口** `func replay(id: String) -> Error:`
- `203` **公开接口** `func pause_replay() -> void:`
- `208` **公开接口** `func resume_replay() -> void:`
- `213` **公开接口** `func stop_replay() -> void:`
- `218` **公开接口** `func clear_cache(older_than_days: int = 0) -> Error:`
- `231` **内部流程** `func _cache_failed(id: String) -> void:`
- `238` **内部流程** `func _notify_audio(id: String) -> void:`
- `242` **内部流程** `func _notify_all_audio() -> void:`
- `246` **内部流程** `func _ensure_stream(id: String) -> bool:`
- `260` **内部流程** `func _append_encoded(id: String, item: Dictionary, encoded: String) -> bool:`
- `283` **内部流程** `func _append_cache(id: String, item: Dictionary, bytes: PackedByteArray) -> void:`
- `296` **内部流程** `func _check_queued_frames(id: String) -> bool:`
- `306` **内部流程** `func _finish_receive(id: String, item: Dictionary) -> void:`
- `315` **内部流程** `func _commit_cache(id: String, item: Dictionary, status: Dictionary) -> void:`
- `323` **内部流程** `func _start_playback(item: Dictionary, status: Dictionary) -> bool:`
- `344` **内部流程** `func _pump_playback(item: Dictionary, status: Dictionary, now: int) -> void:`
- `367` **内部流程** `func _ensure_decoder(id: String, item: Dictionary) -> bool:`
- `375` **内部流程** `func _valid_encoded_audio(encoded: String) -> bool:`

## [client-godot/src/network/account_api.gd](../client-godot/src/network/account_api.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal _http_finished(response: Dictionary)`
- `4` **常量** `const FIELDS := {`
- `13` **内部流程** `func _init(security: Object, timeout: float = 15.0) -> void:`
- `17` **公开接口** `func request(operation: String, server: String, fields: Dictionary) -> Dictionary:`
- `38` **公开接口** `func probe_server(address: String) -> Dictionary:`
- `53` **内部流程** `func _perform(operation: String, base: String, payload: Dictionary, generation: int) -> Dictionary:`
- `65` **内部流程** `func _exchange(url: String, method: int, payload: Dictionary = {}) -> Dictionary:`
- `96` **内部流程** `static func _failure(code: String, status: int = 0) -> Dictionary:`
- `99` **公开接口** `func cancel() -> void:`
- `105` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `108` **内部流程** `func _encrypt_payload(operation: String, base: String, payload: Dictionary, generation: int) -> Dictionary:`
- `124` **内部流程** `func _validated_response(operation: String, response: Dictionary) -> Dictionary:`

## [client-godot/src/network/history_api.gd](../client-godot/src/network/history_api.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal _completed(response: Dictionary)`
- `6` **内部流程** `func _init(timeout: float = 15.0) -> void:`
- `8` **公开接口** `func fetch_page(session: Dictionary, end_index: int = -1) -> Dictionary:`
- `40` **公开接口** `func cancel() -> void:`
- `44` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `46` **内部流程** `static func _failure(code: String, status: int = 0) -> Dictionary:`
- `48` **内部流程** `static func _valid_index(value: Variant) -> bool:`

## [client-godot/src/network/json_request.gd](../client-godot/src/network/json_request.gd)

- `2` **信号** `signal _done(response: Dictionary)`
- `6` **内部流程** `func _init(timeout: float = 15.0, limit: int = 8*1024*1024) -> void:`
- `9` **公开接口** `func send(url: String, method: int, data: Dictionary = {}, headers: PackedStringArray = []) -> Dictionary:`
- `39` **公开接口** `func cancel() -> void:`
- `43` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `45` **内部流程** `static func _failure(code: String,status: int = 0) -> Dictionary:`

## [client-godot/src/network/reliable_outbox.gd](../client-godot/src/network/reliable_outbox.gd)

- `2` **信号** `signal delivery_changed(id: String, state: String, code: String)`
- `4` **常量** `const MAX_AGE_MS := 240000`
- `5` **常量** `const RETRY_DELAYS := [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]`
- `8` **公开接口** `func enqueue(type: String, payload: Dictionary, durable: bool, now_ms: int) -> String:`
- `21` **公开接口** `func take_ready(now_ms: int, connected: bool) -> Array[Dictionary]:`
- `43` **公开接口** `func acknowledge(reply_to: String, payload: Dictionary, now_ms: int) -> void:`
- `54` **公开接口** `func disconnected(now_ms: int) -> void:`
- `62` **公开接口** `func stop(code: String = "TRANSPORT_STOPPED") -> void:`
- `68` **内部流程** `func _retry_or_finish(id: String, now_ms: int, code: String) -> void:`
- `85` **内部流程** `func _finish(id: String, state: String, code: String) -> void:`
- `89` **内部流程** `func _expire_pending(now_ms: int, connected: bool) -> void:`
- `99` **内部流程** `func _reject_delivery(reply_to: String, payload: Dictionary, now_ms: int) -> void:`

## [client-godot/src/network/websocket_transport.gd](../client-godot/src/network/websocket_transport.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal state_changed(state: Dictionary)`
- `4` **信号** `signal delivery_changed(id: String, state: String, code: String)`
- `5` **信号** `signal event_received(event: Dictionary)`
- `6` **信号** `signal system_error(code: String)`
- `7` **常量** `const Outbox = preload("res://src/network/reliable_outbox.gd")`
- `8` **常量** `const MAX_PACKET := 8 * 1024 * 1024`
- `22` **内部流程** `func _init(clock: Callable = Callable()) -> void:`
- `26` **公开接口** `func start(session: Dictionary) -> Error:`
- `44` **公开接口** `func send_event(type: String, payload: Dictionary, durable: bool = false) -> String:`
- `49` **公开接口** `func get_state() -> Dictionary:`
- `52` **公开接口** `func stop() -> void:`
- `59` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `72` **内部流程** `func _connect_socket(now: int) -> void:`
- `85` **内部流程** `func _handle_event(event: Dictionary, now: int) -> void:`
- `102` **内部流程** `func _send_control(type: String, payload: Dictionary, now: int) -> void:`
- `108` **内部流程** `func _disconnect(now: int, code: String) -> void:`
- `115` **内部流程** `func _close_socket() -> void:`
- `120` **内部流程** `func _protocol_error(now: int) -> void:`
- `124` **内部流程** `func _set_state(phase: String, code: String) -> void:`
- `128` **内部流程** `func _reject_auth(code: String) -> void:`
- `137` **内部流程** `static func _error_code(payload: Dictionary, fallback: String) -> String:`
- `140` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `143` **内部流程** `func _poll_socket(now: int) -> void:`
- `161` **内部流程** `func _receive_packets(now: int) -> void:`
- `176` **内部流程** `func _valid_event(event: Variant) -> bool:`
- `179` **内部流程** `func _dispatch_event(event: Dictionary, now: int) -> void:`
- `188` **内部流程** `func _send_pending(now: int) -> void:`

## [client-godot/src/platform/cubism_avatar_driver.gd](../client-godot/src/platform/cubism_avatar_driver.gd)

- `4` **常量** `const MAPPING_PATH = "res://assets/live2d/live2d_interface_config.json"`
- `21` **公开接口** `func load_character(descriptor_path: String) -> Error:`
- `36` **公开接口** `func load_avatar(model_path: String,mapping_path: String = MAPPING_PATH) -> Error:`
- `78` **公开接口** `func apply_expression(command: String) -> bool:`
- `91` **公开接口** `func play_motion(group: String, index: int = 0) -> bool:`
- `101` **公开接口** `func set_mouth_openness(value: float) -> void:`
- `106` **公开接口** `func set_gaze(target: Vector2) -> void:`
- `110` **公开接口** `func hit_test(local_position: Vector2) -> Array[String]:`
- `133` **公开接口** `func get_status() -> Dictionary:`
- `149` **内部流程** `func _apply_parameters(_source: Object, delta: float) -> void:`
- `165` **内部流程** `func _check_model_files(model_path: String, references: Dictionary) -> Error:`
- `183` **内部流程** `func _index_model(model_path: String, references: Dictionary) -> void:`
- `200` **内部流程** `func _index_touch_meshes() -> void:`
- `207` **内部流程** `func _read_mapping(mapping_path: String) -> Dictionary:`
- `215` **内部流程** `func _valid_references(references: Dictionary) -> bool:`

## [client-godot/src/platform/desktop_window_host.gd](../client-godot/src/platform/desktop_window_host.gd)

- `12` **公开接口** `func attach(window: Window, login: bool) -> void:`
- `20` **公开接口** `func set_login_mode(enabled: bool) -> void:`
- `27` **内部流程** `func _apply_presentation() -> void:`
- `33` **内部流程** `func _expanded_mode() -> bool:`
- `36` **公开接口** `func configure(store: RefCounted, key: String) -> void:`
- `41` **公开接口** `func select_layout(key: String, default_size: Vector2i, minimum: Vector2i) -> void:`
- `47` **内部流程** `func _restore(default_size: Vector2i, minimum: Vector2i) -> void:`
- `72` **公开接口** `func open_window() -> void:`
- `81` **内部流程** `func _clamp_visible_frame() -> void:`
- `90` **公开接口** `func tick(delta: float) -> void:`
- `103` **公开接口** `func save() -> void:`
- `111` **公开接口** `func detach() -> void:`

## [client-godot/src/platform/external_link_opener.gd](../client-godot/src/platform/external_link_opener.gd)

- `2` **常量** `const PROJECT_URL := "https://github.com/SheepLiu712/Agent-LuoTianyi"`
- `4` **公开接口** `func open_project() -> Error:`

## [client-godot/src/platform/file_interaction.gd](../client-godot/src/platform/file_interaction.gd)

- `2` **信号** `signal image_selected(result: Dictionary)`
- `3` **信号** `signal export_selected(target: RefCounted)`
- `4` **信号** `signal canceled`
- `5` **公开接口** `func bind(_dialog: FileDialog) -> void:`
- `7` **公开接口** `func select_image() -> void:`
- `9` **公开接口** `func select_export(_filename: String) -> void:`
- `11` **公开接口** `func cancel() -> void:`

## [client-godot/src/platform/godot_external_link_opener.gd](../client-godot/src/platform/godot_external_link_opener.gd)

- `3` **公开接口** `func open_project() -> Error:`

## [client-godot/src/platform/godot_file_interaction.gd](../client-godot/src/platform/godot_file_interaction.gd)

- `2` **常量** `const Images = preload("res://src/storage/image_file_reader.gd")`
- `6` **公开接口** `func bind(dialog: FileDialog) -> void:`
- `16` **公开接口** `func select_image() -> void:`
- `20` **公开接口** `func select_export(filename: String) -> void:`
- `25` **公开接口** `func cancel() -> void:`
- `29` **内部流程** `func _canceled() -> void:`
- `33` **内部流程** `func _selected(path: String) -> void:`

## [client-godot/src/platform/godot_input_service.gd](../client-godot/src/platform/godot_input_service.gd)

- `2` **公开接口** `func is_composing() -> bool:`
- `4` **公开接口** `func has_clipboard_image() -> bool:`
- `6` **公开接口** `func get_clipboard_image() -> Image:`
- `8` **公开接口** `func copy_text(text: String) -> Error:`

## [client-godot/src/platform/godot_runtime_environment.gd](../client-godot/src/platform/godot_runtime_environment.gd)

- `2` **公开接口** `func arguments() -> PackedStringArray:`
- `4` **公开接口** `func is_headless() -> bool:`
- `6` **公开接口** `func register_logger(logger: Logger) -> void:`
- `8` **公开接口** `func unregister_logger(logger: Logger) -> void:`
- `10` **公开接口** `func capture(viewport: Viewport, path: String) -> Error:`
- `12` **公开接口** `func process_id() -> int:`
- `14` **公开接口** `func process_running(id: int) -> bool:`
- `16` **公开接口** `func os_name() -> String:`

## [client-godot/src/platform/godot_window_system.gd](../client-godot/src/platform/godot_window_system.gd)

- `2` **公开接口** `func minimized(window: Window) -> bool:`
- `4` **公开接口** `func windowed(window: Window) -> bool:`
- `6` **公开接口** `func geometry(window: Window) -> Rect2i:`
- `8` **公开接口** `func focus(window: Window) -> void:`
- `10` **公开接口** `func focused(window: Window) -> bool:`
- `12` **公开接口** `func drag(window: Window) -> void:`
- `14` **公开接口** `func reparent_image(window: Window, source: Window) -> void:`

## [client-godot/src/platform/input_service.gd](../client-godot/src/platform/input_service.gd)

- `3` **公开接口** `func is_composing() -> bool:`
- `5` **公开接口** `func has_clipboard_image() -> bool:`
- `7` **公开接口** `func get_clipboard_image() -> Image:`
- `9` **公开接口** `func copy_text(_text: String) -> Error:`

## [client-godot/src/platform/native_decoder_factory.gd](../client-godot/src/platform/native_decoder_factory.gd)

- `2` **公开接口** `func create_decoder() -> RefCounted:`

## [client-godot/src/platform/native_pcm_decoder.gd](../client-godot/src/platform/native_pcm_decoder.gd)

- `3` **内部流程** `func _init(decoder: RefCounted) -> void:`
- `5` **公开接口** `func append(bytes: PackedByteArray) -> Dictionary:`
- `7` **公开接口** `func finish() -> Dictionary:`
- `9` **公开接口** `func read_frames(count: int) -> PackedVector2Array:`
- `11` **公开接口** `func get_status() -> Dictionary:`
- `13` **公开接口** `func get_amplitude(index: int) -> float:`
- `15` **公开接口** `func get_waveform(buckets: int = 24) -> PackedFloat32Array:`

## [client-godot/src/platform/password_encryption.gd](../client-godot/src/platform/password_encryption.gd)

- `2` **公开接口** `func is_available() -> bool:`
- `4` **公开接口** `func encrypt_password(_public_key: String, _password: String) -> Dictionary:`

## [client-godot/src/platform/runtime_environment.gd](../client-godot/src/platform/runtime_environment.gd)

- `2` **公开接口** `func arguments() -> PackedStringArray:`
- `4` **公开接口** `func is_headless() -> bool:`
- `6` **公开接口** `func register_logger(_logger: Logger) -> void:`
- `8` **公开接口** `func unregister_logger(_logger: Logger) -> void:`
- `10` **公开接口** `func capture(_viewport: Viewport, _path: String) -> Error:`
- `12` **公开接口** `func process_id() -> int:`
- `14` **公开接口** `func process_running(_id: int) -> bool:`
- `16` **公开接口** `func os_name() -> String:`

## [client-godot/src/platform/secret_protection.gd](../client-godot/src/platform/secret_protection.gd)

- `2` **公开接口** `func protect_secret(_plain: PackedByteArray, _scope: PackedByteArray) -> Dictionary:`
- `4` **公开接口** `func unprotect_secret(_cipher: PackedByteArray, _scope: PackedByteArray) -> Dictionary:`

## [client-godot/src/platform/window_host.gd](../client-godot/src/platform/window_host.gd)

- `2` **公开接口** `func attach(_window: Window, _login: bool) -> void:`
- `4` **公开接口** `func set_login_mode(_enabled: bool) -> void:`
- `6` **公开接口** `func configure(_store: RefCounted, _key: String) -> void:`
- `8` **公开接口** `func select_layout(_key: String, _size: Vector2i, _minimum: Vector2i) -> void:`
- `10` **公开接口** `func open_window() -> void:`
- `12` **公开接口** `func tick(_delta: float) -> void:`
- `14` **公开接口** `func save() -> void:`
- `16` **公开接口** `func detach() -> void:`

## [client-godot/src/platform/window_system.gd](../client-godot/src/platform/window_system.gd)

- `2` **公开接口** `func minimized(_window: Window) -> bool:`
- `4` **公开接口** `func windowed(_window: Window) -> bool:`
- `6` **公开接口** `func geometry(_window: Window) -> Rect2i:`
- `8` **公开接口** `func focus(_window: Window) -> void:`
- `10` **公开接口** `func focused(_window: Window) -> bool:`
- `12` **公开接口** `func drag(_window: Window) -> void:`
- `14` **公开接口** `func reparent_image(_window: Window, _source: Window) -> void:`

## [client-godot/src/platform/windows_password_encryption.gd](../client-godot/src/platform/windows_password_encryption.gd)

- `2` **公开接口** `func is_available() -> bool:`
- `4` **公开接口** `func encrypt_password(public_key: String, password: String) -> Dictionary:`

## [client-godot/src/platform/windows_secret_protection.gd](../client-godot/src/platform/windows_secret_protection.gd)

- `3` **内部流程** `func _security_unavailable() -> Dictionary:`
- `6` **公开接口** `func protect_secret(plain: PackedByteArray, scope: PackedByteArray) -> Dictionary:`
- `14` **公开接口** `func unprotect_secret(cipher: PackedByteArray, scope: PackedByteArray) -> Dictionary:`

## [client-godot/src/preview/chat_preview.gd](../client-godot/src/preview/chat_preview.gd)

- `7` **常量** `const Session = preload("res://src/preview/demo_session.gd")`
- `8` **常量** `const Bubble = preload("res://scenes/ui/message_bubble.tscn")`
- `9` **常量** `const ImagePresenter = preload("res://src/ui/image_presenter.gd")`
- `31` **生命周期/引擎回调** `func _ready() -> void:`
- `80` **内部流程** `func _resize_split() -> void:`
- `84` **内部流程** `func _change_scenario(value: String) -> void:`
- `93` **内部流程** `func _refresh() -> void:`
- `130` **内部流程** `func _to_latest() -> void:`
- `134` **内部流程** `func _send() -> void:`
- `141` **内部流程** `func _pick_image() -> void:`
- `144` **内部流程** `func _preview_image(image: Image) -> void:`
- `150` **内部流程** `func _open_image(texture: Texture2D, pending: bool) -> void:`
- `162` **内部流程** `func _toggle_play() -> void:`
- `168` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `172` **生命周期/引擎回调** `func _exit_tree() -> void:`

## [client-godot/src/preview/demo_session.gd](../client-godot/src/preview/demo_session.gd)

- `2` **信号** `signal changed`
- `7` **公开接口** `func select_scenario(name: String) -> bool:`
- `25` **公开接口** `func get_messages() -> Array[Dictionary]:`
- `28` **公开接口** `func submit_text(text: String) -> String:`
- `37` **公开接口** `func settle(id: String, success: bool) -> bool:`

## [client-godot/src/session/account_session.gd](../client-godot/src/session/account_session.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal changed(state: Dictionary)`
- `4` **常量** `const StorageService = preload("res://src/storage/storage_service.gd")`
- `5` **常量** `const DEFAULT_SERVER := "https://www-api.u3493359.nyat.app:11664"`
- `15` **内部流程** `func _init(api: Node, storage: StorageService) -> void:`
- `21` **内部流程** `func _load_profile() -> void:`
- `46` **公开接口** `func get_login_defaults() -> Dictionary:`
- `50` **公开接口** `func get_history(server: String = "") -> Array:`
- `56` **公开接口** `func select_account(username: String) -> Dictionary:`
- `65` **公开接口** `func set_login_options(username: String, remember: bool, auto_login: bool) -> Dictionary:`
- `80` **公开接口** `func remove_account(username: String) -> Dictionary:`
- `94` **公开接口** `func set_server(address: String) -> Dictionary:`
- `113` **公开接口** `func perform(operation: String, server: String, fields: Dictionary, remember: bool = false, auto_login: bool = false) -> Dictionary:`
- `132` **公开接口** `func resume() -> Dictionary:`
- `139` **公开接口** `func login_saved(username: String) -> Dictionary:`
- `153` **公开接口** `func cancel() -> void:`
- `157` **公开接口** `func logout() -> Error:`
- `166` **公开接口** `func get_session() -> Dictionary:`
- `169` **内部流程** `func _forget_options(server: String, username: String) -> Error:`
- `180` **内部流程** `func _disable_memory(server: String, username: String) -> void:`
- `186` **内部流程** `func _entry(server: String, username: String) -> Dictionary:`
- `190` **内部流程** `func _index(accounts: Array, server: String, username: String) -> int:`
- `195` **内部流程** `func _persist(profile: Dictionary) -> Error:`
- `202` **内部流程** `func _emit(code: String, storage_error: bool = false) -> void:`
- `206` **内部流程** `func _result(ok: bool, code: String, storage_error: bool = false) -> Dictionary:`
- `209` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `212` **内部流程** `func _migrate_profile(data: Dictionary, server: String) -> void:`
- `222` **内部流程** `func _profile_accounts(entries: Array) -> Array:`
- `238` **内部流程** `func _valid_account_entry(entry: Variant) -> bool:`
- `243` **内部流程** `func _accept_account(operation: String, server: String, fields: Dictionary, remember: bool, auto_login: bool, response: Dictionary) -> void:`
- `256` **内部流程** `func _accept_login(profile: Dictionary, address: String, username: String, remember: bool, auto_login: bool, response: Dictionary) -> void:`
- `268` **内部流程** `func _valid_profile_shape(data: Dictionary, server: String) -> bool:`

## [client-godot/src/session/chat_session.gd](../client-godot/src/session/chat_session.gd)

- `2` **信号** `signal message_audio_changed(id: String, state: Dictionary)`
- `3` **信号** `signal message_image_changed(id: String, state: Dictionary)`
- `4` **信号** `signal changed`
- `5` **信号** `signal state_changed(state: Dictionary)`
- `6` **信号** `signal expression_requested(command: String)`
- `7` **信号** `signal mouth_changed(value: float)`
- `8` **常量** `const Audio = preload("res://src/media/reply_audio.gd")`
- `9` **常量** `const Attachment = preload("res://src/media/image_attachment.gd")`
- `30` **内部流程** `func _init(transport: Node, logger: RefCounted = null, media: Node = null, history: Node = null, reading: RefCounted = null, images: Node = null, models: Node = null) -> void:`
- `69` **公开接口** `func start(session: Dictionary) -> Error:`
- `93` **公开接口** `func set_typing(active: bool, text_length: int = 0) -> Error:`
- `104` **公开接口** `func send_text(text: String) -> String:`
- `128` **公开接口** `func send_image(bytes: PackedByteArray, mime: String) -> String:`
- `160` **公开接口** `func set_image_selecting(active: bool) -> void:`
- `163` **公开接口** `func record_touch(areas: Array[String]) -> void:`
- `182` **公开接口** `func get_messages() -> Array[Dictionary]:`
- `185` **公开接口** `func get_state() -> Dictionary:`
- `190` **公开接口** `func set_volume(value: float) -> void:`
- `193` **公开接口** `func get_audio_state() -> Dictionary:`
- `196` **公开接口** `func stop_voice() -> void:`
- `199` **公开接口** `func stop() -> void:`
- `227` **内部流程** `func _connection_changed(connection: Dictionary) -> void:`
- `243` **内部流程** `func _delivery_changed(id: String, status: String, code: String) -> void:`
- `252` **内部流程** `func _system_error(code: String) -> void:`
- `258` **内部流程** `func _receive(event: Dictionary) -> void:`
- `269` **内部流程** `func _receive_reply(payload: Dictionary, event_timestamp: Variant = null) -> void:`
- `286` **内部流程** `func _audio_finished(id: String, code: String) -> void:`
- `295` **内部流程** `func _present_replies() -> void:`
- `318` **内部流程** `func _reply_timestamp(raw: Variant) -> float:`
- `323` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `326` **公开接口** `func get_message_audio(id: String) -> Dictionary:`
- `329` **公开接口** `func replay(id: String) -> Error:`
- `334` **公开接口** `func pause_replay() -> void:`
- `337` **公开接口** `func resume_replay() -> void:`
- `340` **公开接口** `func stop_replay() -> void:`
- `343` **公开接口** `func clear_cache(older_than_days: int = 0) -> Error:`
- `349` **公开接口** `func get_history_state() -> Dictionary:`
- `352` **公开接口** `func retry_history() -> void:`
- `356` **公开接口** `func skip_history() -> void:`
- `360` **内部流程** `func _release_history_sends() -> void:`
- `375` **内部流程** `func _history_page(messages: Array[Dictionary]) -> void:`
- `391` **公开接口** `func get_reading_state() -> Dictionary:`
- `394` **公开接口** `func note_read_interaction() -> void:`
- `398` **公开接口** `func reading_located() -> void:`
- `402` **公开接口** `func report_visible_messages(ids: Array[String], foreground: bool) -> void:`
- `406` **内部流程** `func _update_reading() -> void:`
- `410` **公开接口** `func request_message_image(id: String, retry: bool = false) -> void:`
- `417` **公开接口** `func get_message_image(id: String) -> Dictionary:`
- `420` **公开接口** `func preview_message_image(id: String) -> Texture2D:`
- `423` **内部流程** `func _model_types() -> Array:`
- `426` **内部流程** `func _log_reply(id: String, payload: Dictionary) -> void:`
- `432` **内部流程** `func _update_reply(reply: Dictionary, payload: Dictionary) -> void:`

## [client-godot/src/session/dynamics_controller.gd](../client-godot/src/session/dynamics_controller.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal changed`
- `4` **信号** `signal unread_changed(count: int)`
- `5` **信号** `signal latest_unread_changed(post: Dictionary)`
- `6` **常量** `const Http = preload("res://src/network/json_request.gd")`
- `21` **内部流程** `func _init(logger: RefCounted = null,timeout: float = 15.0) -> void:`
- `25` **生命周期/引擎回调** `func _ready() -> void:`
- `31` **公开接口** `func start(session: Dictionary) -> void:`
- `39` **公开接口** `func stop() -> void:`
- `57` **公开接口** `func get_state() -> Dictionary:`
- `60` **公开接口** `func get_posts() -> Array[Dictionary]:`
- `63` **公开接口** `func get_latest_unread() -> Dictionary:`
- `66` **公开接口** `func get_comments(id: String) -> Dictionary:`
- `69` **公开接口** `func refresh() -> void:`
- `72` **公开接口** `func load_more() -> void:`
- `76` **内部流程** `func _load_posts(more: bool) -> void:`
- `96` **公开接口** `func load_comments(id: String,more: bool = false) -> void:`
- `120` **公开接口** `func refresh_comments(id: String) -> void:`
- `153` **公开接口** `func refresh_unread() -> void:`
- `172` **内部流程** `func _load_latest_unread(generation: int, last_read: String) -> Dictionary:`
- `188` **公开接口** `func mark_read() -> void:`
- `207` **内部流程** `func _request(path: String,method: int = HTTPClient.METHOD_GET,data: Dictionary = {},limit: int = 0,cursor: String = "") -> Dictionary:`
- `230` **公开接口** `func publish(content: String) -> Dictionary:`
- `233` **公开接口** `func comment(id: String,content: String,parent_comment_id: String = "") -> Dictionary:`
- `245` **内部流程** `func _write(id: String,content: String,parent: String) -> Dictionary:`
- `268` **内部流程** `func _page(data: Dictionary,cursor: String,comments: bool,id: String = "") -> Dictionary:`
- `280` **内部流程** `func _valid_item(item: Variant,comment: bool,id: String = "") -> bool:`
- `292` **内部流程** `func _merge(existing: Array,incoming: Array) -> Array[Dictionary]:`
- `301` **内部流程** `func _find_post(id: String) -> Dictionary:`
- `307` **内部流程** `func _empty_comments() -> Dictionary:`
- `310` **内部流程** `func _sort_comments(items: Array) -> void:`
- `313` **内部流程** `func _failure(code: String) -> Dictionary:`
- `316` **内部流程** `func _notify() -> void:`
- `320` **内部流程** `func _log(phase: String,code: String) -> void:`
- `324` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `327` **内部流程** `func _comments_blocked(id: String) -> bool:`
- `330` **内部流程** `func _ensure_comments(id: String) -> Dictionary:`
- `335` **内部流程** `func _read_unread_count(result: Dictionary) -> Dictionary:`
- `343` **内部流程** `func _unread_preview(result: Dictionary, generation: int) -> Dictionary:`
- `356` **内部流程** `func _first_unread_post(items: Array, last_read: String) -> Dictionary:`
- `363` **内部流程** `func _write_blocked(id: String) -> bool:`
- `366` **内部流程** `func _accept_written_item(id: String, item: Dictionary) -> void:`
- `377` **内部流程** `func _valid_next_cursor(data: Dictionary, next: Variant, cursor: String) -> bool:`
- `380` **内部流程** `func _has_unread_dynamics(count: Variant) -> bool:`

## [client-godot/src/session/history_sync.gd](../client-godot/src/session/history_sync.gd)

- `2` **信号** `signal page_received(messages: Array[Dictionary])`
- `3` **信号** `signal boundary_ready`
- `4` **信号** `signal state_changed(state: Dictionary)`
- `12` **内部流程** `func _init(api: Node, logger: RefCounted = null) -> void:`
- `17` **公开接口** `func start(session: Dictionary) -> void:`
- `23` **公开接口** `func stop() -> void:`
- `31` **公开接口** `func get_state() -> Dictionary:`
- `33` **公开接口** `func retry() -> void:`
- `40` **公开接口** `func skip() -> void:`
- `48` **内部流程** `func _load(generation: int) -> void:`
- `78` **内部流程** `func _fail(code: String) -> void:`
- `82` **内部流程** `func _notify() -> void:`
- `86` **内部流程** `func _empty() -> Dictionary:`
- `88` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `91` **内部流程** `func _valid_page_bounds(start: Variant, row_count: int) -> bool:`
- `98` **内部流程** `func _valid_page_start(start: Variant, row_count: int) -> bool:`
- `103` **内部流程** `func _page_messages(rows: Array) -> Array[Dictionary]:`
- `111` **内部流程** `func _valid_history_row(row: Variant) -> bool:`
- `118` **内部流程** `func _valid_history_content(row: Dictionary) -> bool:`
- `123` **内部流程** `func _deduplicate(messages: Array[Dictionary]) -> Array[Dictionary]:`

## [client-godot/src/session/model_executor.gd](../client-godot/src/session/model_executor.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **常量** `const Attachment = preload("res://src/media/image_attachment.gd")`
- `4` **信号** `signal completed(response: Dictionary)`
- `5` **常量** `const Http = preload("res://src/network/json_request.gd")`
- `14` **内部流程** `func _init(settings: Node,logger: RefCounted = null,timeout: float = 120.0) -> void:`
- `19` **公开接口** `func start() -> void:`
- `23` **公开接口** `func stop() -> void:`
- `30` **公开接口** `func enabled_types() -> Array[String]:`
- `33` **公开接口** `func submit(payload: Dictionary) -> void:`
- `57` **公开接口** `func test_config(type_id: String,config: Dictionary) -> Dictionary:`
- `64` **内部流程** `func _execute(request: Dictionary,config: Dictionary) -> Dictionary:`
- `92` **内部流程** `func _parse(result: Dictionary,use_json: bool) -> Dictionary:`
- `103` **内部流程** `func _failure(code: String) -> Dictionary:`
- `106` **内部流程** `func _log(phase: String,code: String,type_id: String,elapsed: int) -> void:`
- `110` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `113` **内部流程** `func _validate_request(request: Dictionary, config: Dictionary) -> Dictionary:`
- `127` **内部流程** `func _validate_media(request: Dictionary, config: Dictionary, use_json: bool, thinking: bool) -> Dictionary:`
- `139` **内部流程** `func _request_body(request: Dictionary, config: Dictionary, params: Dictionary, image: String, thinking: bool, use_json: bool) -> Dictionary:`
- `151` **内部流程** `func _response_usage(data: Dictionary) -> Dictionary:`

## [client-godot/src/session/model_settings.gd](../client-godot/src/session/model_settings.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal changed(state: Dictionary)`
- `12` **内部流程** `func _init(http: Node,store: RefCounted,logger: RefCounted = null) -> void:`
- `17` **公开接口** `func start(session: Dictionary) -> void:`
- `41` **公开接口** `func reload() -> void:`
- `43` **公开接口** `func get_types() -> Array[Dictionary]:`
- `48` **公开接口** `func get_config(type_id: String) -> Dictionary:`
- `50` **公开接口** `func get_state() -> Dictionary:`
- `52` **公开接口** `func validate(type_id: String,config: Dictionary) -> Dictionary:`
- `64` **公开接口** `func save(type_id: String,config: Dictionary,allow_plain: bool = false) -> Dictionary:`
- `74` **公开接口** `func enabled_types() -> Array[String]:`
- `80` **公开接口** `func copy_config(source: Dictionary,target_id: String) -> Dictionary:`
- `86` **公开接口** `func stop() -> void:`
- `95` **内部流程** `func _default(type: Dictionary) -> Dictionary:`
- `97` **内部流程** `func _notify() -> void:`
- `101` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `104` **内部流程** `func _valid_config_fields(config: Dictionary) -> bool:`
- `115` **内部流程** `func _validate_enabled(type_id: String, config: Dictionary) -> Dictionary:`
- `122` **内部流程** `func _parse_types(items: Array) -> Dictionary:`
- `132` **内部流程** `func _valid_model_type(item: Variant) -> bool:`
- `139` **内部流程** `func _restore_configs() -> String:`

## [client-godot/src/session/preferences_controller.gd](../client-godot/src/session/preferences_controller.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `3` **信号** `signal changed(state: Dictionary)`
- `4` **常量** `const FIELDS := ["relationship","speaking_style","personality_text","custom_context"]`
- `11` **内部流程** `func _init(http: Node,logger: RefCounted = null) -> void:`
- `15` **公开接口** `func start(session: Dictionary) -> void:`
- `20` **公开接口** `func reload() -> void:`
- `38` **公开接口** `func edit(fields: Dictionary) -> void:`
- `46` **公开接口** `func save() -> void:`
- `72` **公开接口** `func get_state() -> Dictionary:`
- `74` **公开接口** `func stop() -> void:`
- `81` **内部流程** `func _fetch_preferences() -> Dictionary:`
- `86` **内部流程** `func _auth() -> Dictionary:`
- `88` **内部流程** `func _fields(preferences: Dictionary) -> Dictionary:`
- `102` **内部流程** `func _notify() -> void:`
- `107` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `110` **内部流程** `func _merge_preferences(preferences: Dictionary, draft: Dictionary) -> Dictionary:`
- `122` **内部流程** `func _merge_traits(merged: Dictionary, value: String) -> void:`

## [client-godot/src/storage/audio_cache.gd](../client-godot/src/storage/audio_cache.gd)

- `2` **常量** `const AccountScope = preload("res://src/domain/account_scope.gd")`
- `3` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `11` **内部流程** `func _init(root: String = "user://audio", logger: RefCounted = null, now_seconds: Callable = Callable()) -> void:`
- `17` **公开接口** `func set_scope(server: String, username: String) -> Error:`
- `41` **内部流程** `func _cleanup_incomplete_and_orphans() -> Error:`
- `51` **内部流程** `func _path(id: String, extension: String) -> String:`
- `54` **公开接口** `func get_directory() -> String:`
- `57` **公开接口** `func begin(id: String) -> Error:`
- `70` **公开接口** `func append(id: String, bytes: PackedByteArray) -> Error:`
- `84` **公开接口** `func commit(id: String, status: Dictionary, waveform: PackedFloat32Array) -> Error:`
- `112` **公开接口** `func lookup(id: String) -> Dictionary:`
- `132` **内部流程** `func _valid(data: Dictionary) -> bool:`
- `135` **内部流程** `func _valid_saved_time(data: Dictionary) -> bool:`
- `141` **内部流程** `func _valid_metadata_shape(data: Dictionary) -> bool:`
- `144` **内部流程** `func _valid_integer_fields(data: Dictionary) -> bool:`
- `151` **内部流程** `func _valid_audio_ranges(data: Dictionary) -> bool:`
- `156` **内部流程** `func _valid_waveform(waveform: Array) -> bool:`
- `161` **公开接口** `func abort(id: String) -> void:`
- `167` **公开接口** `func abort_all() -> void:`
- `171` **公开接口** `func clear(older_than_days: int = 0) -> Error:`
- `187` **内部流程** `func _now() -> int:`
- `190` **内部流程** `func _saved_at(metadata: Dictionary, audio_path: String) -> int:`
- `196` **内部流程** `func _clear_older(days: int) -> Error:`
- `207` **内部流程** `func _error(id: String, result: Error) -> Error:`
- `212` **公开接口** `func open_stream(id: String) -> RefCounted:`
- `217` **内部流程** `func _cache_pairs() -> Dictionary:`
- `239` **内部流程** `func _incomplete_files(files: Dictionary) -> Array[String]:`
- `253` **内部流程** `func _valid_completion(status: Dictionary, metadata: Dictionary) -> bool:`
- `258` **内部流程** `func _write_manifest(id: String, metadata: Dictionary) -> Error:`
- `270` **内部流程** `func _clear_old_manifest(manifest_path: String, cutoff: float) -> Error:`
- `284` **内部流程** `func _remove_cache_pair(audio_path: String, manifest_path: String) -> Error:`

## [client-godot/src/storage/client_log.gd](../client-godot/src/storage/client_log.gd)

- `2` **信号** `signal entry_added(entry: Dictionary)`
- `3` **信号** `signal write_failed(error: int)`
- `4` **常量** `const Release = preload("res://src/storage/release_info.gd")`
- `5` **常量** `const METRICS := ["has_audio", "audio_chars", "bytes", "frames", "sample_rate", "channels", "bits", "final", "audio_error", "queued", "volume", "latency_ms", "skips", "count", "status", "index", "duration_ms"]`
- `6` **常量** `const MODULES := ["app", "account", "network", "message", "audio", "cache", "history", "settings", "dynamics", "engine"]`
- `7` **常量** `const CODES := "OK UNKNOWN INVALID_INPUT INVALID_RESPONSE BUSY CANCELLED TIMEOUT NETWORK_ERROR HTTP_ERROR AUTH_REJECTED PUBLIC_KEY_ERROR ENCRYPTION_ERROR CREDENTIAL_UNAVAILABLE NO_SAVED_LOGIN LOGGED_OUT PENDING SEND_REJECTED DELIVERY_UNCERTAIN TRANSPORT_STOPPED ACK_TIMEOUT DISCONNECTED CONNECT_TIMEOUT AUTH_TIMEOUT INVALID_BASE64 AUDIO_ERROR AUDIO_TIMEOUT BUFFER_LIMIT DECODER_UNAVAILABLE PLAYBACK_FAILED REPLAY_FAILED CACHE_WRITE_FAILED CACHE_CLEAR_FAILED INVALID_WAV UNSUPPORTED_FORMAT TRUNCATED_AUDIO EMPTY_AUDIO STREAM_FINISHED STOPPED INTERRUPTED ENGINE_ERROR ENGINE_WARNING HISTORY_FAILED HISTORY_INVALID HISTORY_DUPLICATE MODEL_ERROR MODEL_DISABLED MODEL_INVALID SAVE_FAILED INVALID_JSON MODEL_BUSY UNKNOWN_MODEL_TYPE INVALID_CONFIG MODEL_KIND_MISMATCH MODEL_CAPABILITY_MISMATCH MODEL_FIELDS_REQUIRED STREAMING_NOT_SUPPORTED PLAINTEXT_CONFIRMATION_REQUIRED KEY_UNAVAILABLE NOT_FOUND COMMENT_NOT_ALLOWED INVALID_REPLY_TARGET"`
- `8` **常量** `const PHASES := "saving first_loading first_failed idle connecting authenticating ready reconnecting auth_rejected signed_out signed_in busy queued sending sent failed uncertain loading complete error skipped playing paused stopped"`
- `9` **常量** `const EXPLANATIONS := {"dynamics_state":"动态读取与写入状态", "settings_models":"模型配置状态", "settings_model_execution":"模型请求执行", "settings_preference":"相处偏好操作", "client_started":"客户端启动", "client_stopped":"客户端正常退出", "history_state":"历史同步状态", "account_state":"账户操作状态", "message_queued":"消息已进入发送队列", "message_delivery":"消息投递状态", "engine_error":"引擎报告异常（原始内容不写入日志）", "connection_state":"聊天连接状态变化", "reply_received":"收到回复分片", "system_error":"操作出现错误", "cache_committed":"完整语音已保存", "cache_error":"语音未能保存", "cache_cleared":"已执行语音缓存清理", "audio_received":"收到音频数据", "audio_format":"已识别音频格式", "audio_decoded":"音频解码完成", "audio_receive_finished":"音频接收结束", "audio_error":"音频处理失败", "audio_underrun":"音频缓冲暂时不足", "audio_playback_started":"开始播放在线语音", "audio_playback_finished":"在线语音播放结束", "replay_preempted":"在线语音打断本地重放", "replay_finished":"重放结束", "replay_started":"开始重放", "replay_paused":"重放已暂停", "replay_resumed":"继续重放", "replay_stopped":"重放已停止"}`
- `25` **内部流程** `func _init(directory: String = "user://logs", max_bytes: int = 2097152, environment: Variant = null, max_entries: int = 10000) -> void:`
- `42` **公开接口** `func record(event: String, fields: Dictionary = {}) -> Error:`
- `69` **公开接口** `func get_directory() -> String:`
- `72` **公开接口** `func get_run_id() -> String:`
- `75` **公开接口** `func finish() -> void:`
- `85` **公开接口** `func list_runs() -> Array[Dictionary]:`
- `101` **公开接口** `func read_entries(run_id: String = "") -> Array[Dictionary]:`
- `108` **公开接口** `func export_run(run_id: String, destination_zip: String) -> Error:`
- `130` **内部流程** `func _ensure_directory() -> Error:`
- `156` **内部流程** `func _save_metadata() -> Error:`
- `171` **内部流程** `func _prune() -> void:`
- `192` **内部流程** `func _path(id: String, suffix: String) -> String:`
- `195` **内部流程** `func _jsonl_size(path: String) -> int:`
- `205` **内部流程** `func _module(event: String) -> String:`
- `217` **内部流程** `func _read_archive(id: String) -> Dictionary:`
- `235` **内部流程** `func _safe_code(key: String, value: String) -> String:`
- `238` **内部流程** `func _apply_fields(entry: Dictionary, fields: Dictionary) -> void:`
- `249` **内部流程** `func _write_entry(serialized: PackedByteArray) -> Dictionary:`
- `263` **内部流程** `func _append_entry_file(path: String, serialized: PackedByteArray) -> Error:`
- `282` **内部流程** `func _apply_metrics(entry: Dictionary, fields: Dictionary) -> void:`
- `288` **内部流程** `func _valid_run_metadata(data: Variant, id: String) -> bool:`
- `291` **内部流程** `func _write_export(destination_zip: String, files: Array) -> Error:`
- `311` **内部流程** `func _valid_archive_entry(value: Variant) -> bool:`
- `314` **内部流程** `func _safe_archive_entry(value: Dictionary) -> Dictionary:`

## [client-godot/src/storage/credential_store.gd](../client-godot/src/storage/credential_store.gd)

- `2` **常量** `const AccountScope = preload("res://src/domain/account_scope.gd")`
- `6` **内部流程** `func _init(security: Object, root: String = "user://accounts") -> void:`
- `10` **内部流程** `func _scope(server: String, username: String) -> String:`
- `13` **公开接口** `func save(server: String, username: String, token: String) -> Error:`
- `38` **公开接口** `func read(server: String, username: String) -> Dictionary:`
- `56` **公开接口** `func forget(server: String, username: String) -> Error:`

## [client-godot/src/storage/engine_log_sink.gd](../client-godot/src/storage/engine_log_sink.gd)

- `3` **内部流程** `func _init(logger: RefCounted) -> void:`
- `5` **内部流程** `func _log_error(_function: String, _file: String, _line: int, _code: String, _rationale: String, _editor_notify: bool, error_type: int, _script_backtraces: Array[ScriptBacktrace]) -> void:`
- `7` **内部流程** `func _save(error_type: int) -> void:`
- `10` **公开接口** `func stop() -> void:`

## [client-godot/src/storage/godot_read_stream.gd](../client-godot/src/storage/godot_read_stream.gd)

- `3` **内部流程** `func _init(file: FileAccess) -> void:`
- `5` **公开接口** `func get_buffer(size: int) -> PackedByteArray:`
- `7` **公开接口** `func get_length() -> int:`
- `9` **公开接口** `func get_position() -> int:`
- `11` **公开接口** `func close() -> void:`

## [client-godot/src/storage/godot_settings_store.gd](../client-godot/src/storage/godot_settings_store.gd)

- `5` **内部流程** `func _init(path: String = "") -> void:`
- `8` **公开接口** `func load_settings() -> Error:`
- `14` **公开接口** `func get_value(section: String, key: String, fallback: Variant = null) -> Variant:`
- `17` **公开接口** `func set_value(section: String, key: String, value: Variant) -> void:`
- `20` **公开接口** `func save_settings() -> Error:`

## [client-godot/src/storage/godot_storage_service.gd](../client-godot/src/storage/godot_storage_service.gd)

- `7` **内部流程** `func _init(profile_path: String = "user://account.cfg", credentials: RefCounted = null) -> void:`
- `13` **公开接口** `func read_login_profile() -> Dictionary:`
- `22` **公开接口** `func write_login_profile(data: Dictionary) -> Error:`
- `36` **公开接口** `func read_login_token(server: String, username: String) -> Dictionary:`
- `39` **公开接口** `func save_login_token(server: String, username: String, token: String) -> Error:`
- `42` **公开接口** `func forget_login_token(server: String, username: String) -> Error:`
- `45` **公开接口** `func query_directory(path: String) -> Dictionary:`
- `60` **内部流程** `func _measure(path: String) -> Dictionary:`
- `85` **内部流程** `func _fill_free_bytes(result: Dictionary, absolute: String) -> void:`

## [client-godot/src/storage/history_image_source.gd](../client-godot/src/storage/history_image_source.gd)

- `2` **信号** `signal changed(id: String, state: Dictionary)`
- `3` **公开接口** `func start(_session: Dictionary) -> void:`
- `5` **公开接口** `func stop() -> void:`
- `7` **公开接口** `func get_state(_id: String) -> Dictionary:`
- `9` **公开接口** `func ensure(id: String) -> void:`
- `11` **公开接口** `func retry(id: String) -> void:`
- `13` **公开接口** `func preview(_id: String) -> Texture2D:`
- `15` **公开接口** `func store_local(_id: String, _bytes: PackedByteArray) -> Error:`

## [client-godot/src/storage/history_images.gd](../client-godot/src/storage/history_images.gd)

- `2` **常量** `const Attachment = preload("res://src/media/image_attachment.gd")`
- `3` **常量** `const AccountScope = preload("res://src/domain/account_scope.gd")`
- `4` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `15` **内部流程** `func _init(root: String = "user://images",logger: RefCounted = null) -> void:`
- `18` **公开接口** `func start(session: Dictionary) -> void:`
- `25` **公开接口** `func stop() -> void:`
- `37` **公开接口** `func get_state(id: String) -> Dictionary:`
- `39` **公开接口** `func store_local(id: String, bytes: PackedByteArray) -> Error:`
- `47` **公开接口** `func ensure(id: String) -> void:`
- `61` **公开接口** `func retry(id: String) -> void:`
- `65` **公开接口** `func preview(id: String) -> Texture2D:`
- `73` **内部流程** `func _pump() -> void:`
- `105` **内部流程** `func _ready_image(id: String,image: Image,code: String) -> void:`
- `120` **内部流程** `func _error(id: String,code: String) -> void:`
- `125` **内部流程** `func _save(id: String,bytes: PackedByteArray) -> Error:`
- `142` **内部流程** `func _path(id: String) -> String:`
- `144` **内部流程** `func _decode(bytes: PackedByteArray) -> Image:`
- `153` **内部流程** `func _header_safe(header: Dictionary) -> bool:`
- `155` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `158` **内部流程** `func _decode_image(bytes: PackedByteArray, image: Image) -> Error:`

## [client-godot/src/storage/image_file_reader.gd](../client-godot/src/storage/image_file_reader.gd)

- `2` **常量** `const Attachment = preload("res://src/media/image_attachment.gd")`
- `3` **公开接口** `static func read(path: String) -> Dictionary:`

## [client-godot/src/storage/log_export_target.gd](../client-godot/src/storage/log_export_target.gd)

- `4` **内部流程** `func _init(path: String) -> void:`
- `6` **公开接口** `func export_log(logger: RefCounted, run_id: String) -> Error:`

## [client-godot/src/storage/model_store.gd](../client-godot/src/storage/model_store.gd)

- `2` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `7` **内部流程** `func _init(security: Object,root: String = "user://models") -> void:`
- `10` **公开接口** `func set_scope(server: String,username: String) -> void:`
- `14` **公开接口** `func read(type_id: String) -> Dictionary:`
- `23` **公开接口** `func save(type_id: String,config: Dictionary,allow_plain: bool = false) -> Dictionary:`
- `37` **内部流程** `func _path(type_id: String) -> String:`
- `40` **内部流程** `func _read_key(type_id: String, data: Dictionary, config: Dictionary) -> Dictionary:`
- `51` **内部流程** `func _protect_key(type_id: String, config: Dictionary, data: Dictionary, allow_plain: bool) -> Dictionary:`
- `62` **内部流程** `func _write_config(type_id: String, data: Dictionary) -> Error:`

## [client-godot/src/storage/read_stream.gd](../client-godot/src/storage/read_stream.gd)

- `2` **公开接口** `func get_buffer(_size: int) -> PackedByteArray:`
- `4` **公开接口** `func get_length() -> int:`
- `6` **公开接口** `func get_position() -> int:`
- `8` **公开接口** `func close() -> void:`

## [client-godot/src/storage/reading_position.gd](../client-godot/src/storage/reading_position.gd)

- `2` **常量** `const AccountScope = preload("res://src/domain/account_scope.gd")`
- `3` **常量** `const ServerAddress = preload("res://src/domain/server_address.gd")`
- `8` **内部流程** `func _init(root: String = "user://reading") -> void:`
- `11` **公开接口** `func start(server: String, username: String) -> void:`
- `23` **公开接口** `func update(messages: Array, history_state: Dictionary) -> void:`
- `38` **公开接口** `func get_state() -> Dictionary:`
- `40` **公开接口** `func interact() -> void:`
- `42` **公开接口** `func located() -> void:`
- `45` **公开接口** `func report_visible(ids: Array, foreground: bool) -> Error:`
- `59` **内部流程** `func _index(id: String) -> int:`
- `65` **内部流程** `func _visible_candidate(ids: Array) -> String:`
- `78` **内部流程** `func _save_candidate(candidate: String) -> Error:`

## [client-godot/src/storage/release_info.gd](../client-godot/src/storage/release_info.gd)

- `3` **公开接口** `static func get_info() -> Dictionary:`
- `6` **公开接口** `static func title() -> String:`

## [client-godot/src/storage/settings_store.gd](../client-godot/src/storage/settings_store.gd)

- `3` **公开接口** `func load_settings() -> Error:`
- `5` **公开接口** `func get_value(_section: String, _key: String, fallback: Variant = null) -> Variant:`
- `7` **公开接口** `func set_value(_section: String, _key: String, _value: Variant) -> void:`
- `9` **公开接口** `func save_settings() -> Error:`

## [client-godot/src/storage/storage_service.gd](../client-godot/src/storage/storage_service.gd)

- `4` **公开接口** `func query_directory(_path: String) -> Dictionary:`
- `7` **公开接口** `func read_login_profile() -> Dictionary:`
- `10` **公开接口** `func write_login_profile(_data: Dictionary) -> Error:`
- `13` **公开接口** `func read_login_token(_server: String, _username: String) -> Dictionary:`
- `16` **公开接口** `func save_login_token(_server: String, _username: String, _token: String) -> Error:`
- `19` **公开接口** `func forget_login_token(_server: String, _username: String) -> Error:`

## [client-godot/src/storage/window_geometry.gd](../client-godot/src/storage/window_geometry.gd)

- `3` **内部流程** `func _init(file_path: String = "user://window-geometry.cfg") -> void:`
- `5` **公开接口** `func read_layout(key: String, fallback: Rect2i, minimum: Vector2i, screens: Array[Rect2i]) -> Dictionary:`
- `24` **公开接口** `func write_layout(key: String, rect: Rect2i, maximized: bool) -> Error:`

## [client-godot/src/ui/account_view.gd](../client-godot/src/ui/account_view.gd)

- `3` **信号** `signal log_requested`
- `4` **信号** `signal feedback_requested`
- `5` **信号** `signal exit_requested`
- `6` **常量** `const Session = preload("res://src/session/account_session.gd")`
- `7` **常量** `const HistoryRow = preload("res://scenes/ui/login_account_row.tscn")`
- `8` **常量** `const PASSWORD_HINT := "密码只允许英文字母、数字和英文符号，不接受中文或其他字符。"`
- `28` **公开接口** `func setup(session: Node) -> void:`
- `32` **生命周期/引擎回调** `func _ready() -> void:`
- `44` **内部流程** `func _initialize() -> void:`
- `77` **公开接口** `func select_mode(mode: String) -> void:`
- `86` **内部流程** `func _apply_mode() -> void:`
- `111` **内部流程** `func _remembered() -> Dictionary:`
- `116` **内部流程** `func _sync_selected() -> void:`
- `128` **内部流程** `func _username_changed(_text: String) -> void:`
- `139` **内部流程** `func _options_changed(automatic_source: bool) -> void:`
- `152` **内部流程** `func _send() -> void:`
- `168` **内部流程** `func _update_state(state: Dictionary) -> void:`
- `180` **内部流程** `func _open_menu() -> void:`
- `188` **内部流程** `func _popup(window: Window, position: Vector2, requested: Vector2i) -> void:`
- `197` **内部流程** `func _open_history() -> void:`
- `220` **内部流程** `func _remove_record() -> void:`
- `225` **内部流程** `func _open_server() -> void:`
- `234` **内部流程** `func _save_server() -> void:`
- `244` **内部流程** `func _cancel_server() -> void:`
- `248` **公开接口** `func report_feedback_result(error: Error) -> void:`
- `253` **内部流程** `func _drag_window(event: InputEvent) -> void:`
- `257` **内部流程** `func _layout_form() -> void:`
- `260` **内部流程** `func _clear_secrets() -> void:`
- `265` **内部流程** `func _password_changed(field: String, value: String) -> void:`
- `275` **内部流程** `static func _ascii_password(value: String) -> bool:`
- `281` **内部流程** `static func _error_text(code: String, status: int = 0) -> String:`
- `290` **内部流程** `func _validate_passwords(operation: String) -> bool:`
- `300` **内部流程** `func _present_response(operation: String, response: Dictionary) -> void:`

## [client-godot/src/ui/audio_settings_page.gd](../client-godot/src/ui/audio_settings_page.gd)

- `2` **常量** `const StorageService = preload("res://src/storage/storage_service.gd")`
- `10` **公开接口** `func setup(clear_cache: Callable, storage_service: StorageService = null, cache_directory: String = "") -> void:`
- `18` **生命周期/引擎回调** `func _ready() -> void:`
- `28` **内部流程** `func _request_clear() -> void:`
- `37` **内部流程** `func _clear() -> void:`
- `51` **内部流程** `func _refresh_usage() -> void:`
- `73` **内部流程** `func _position_marker() -> void:`
- `79` **内部流程** `func _format_bytes(bytes: int) -> String:`

## [client-godot/src/ui/chat_time.gd](../client-godot/src/ui/chat_time.gd)

- `3` **常量** `const GAP_SECONDS := 300.0`
- `5` **公开接口** `static func markers(messages: Array[Dictionary]) -> Dictionary:`
- `17` **公开接口** `static func seconds(raw: Variant) -> float:`
- `24` **公开接口** `static func label(value: float) -> String:`
- `30` **内部流程** `static func _numeric_seconds(value: float) -> float:`
- `35` **内部流程** `static func _calendar_seconds(text: String) -> float:`
- `50` **内部流程** `static func _zone_minutes(zone: String) -> float:`
- `57` **内部流程** `static func _valid_calendar(text: String) -> bool:`
- `66` **内部流程** `static func _february_days(year: int) -> int:`

## [client-godot/src/ui/chat_view.gd](../client-godot/src/ui/chat_view.gd)

- `4` **信号** `signal image_requested(provider: Callable)`
- `5` **信号** `signal attachment_requested(provider: Callable, confirm: Callable)`
- `6` **信号** `signal attachment_cleared`
- `7` **常量** `const Attachment = preload("res://src/media/image_attachment.gd")`
- `28` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `37` **内部流程** `func _apply_ui_style() -> void:`
- `47` **公开接口** `func setup(session: Node) -> void:`
- `52` **公开接口** `func is_dirty() -> bool:`
- `55` **生命周期/引擎回调** `func _ready() -> void:`
- `79` **内部流程** `func _initialize() -> void:`
- `120` **内部流程** `func _show_volume() -> void:`
- `127` **内部流程** `func _send() -> void:`
- `134` **内部流程** `func _attach(result: Dictionary) -> void:`
- `146` **内部流程** `func _preview_attachment() -> void:`
- `151` **内部流程** `func _confirm_attachment(_texture: Texture2D) -> bool:`
- `160` **内部流程** `func _clear_attachment(canceled: bool) -> void:`
- `169` **内部流程** `func _refresh() -> void:`
- `176` **内部流程** `func _visible_audio(ids: Array[String]) -> void:`
- `184` **内部流程** `func _to_latest() -> void:`
- `188` **内部流程** `func _state_changed(state: Dictionary) -> void:`
- `206` **内部流程** `func _audio_changed(id: String, state: Dictionary) -> void:`
- `209` **内部流程** `func _audio_action(id: String, action: String) -> void:`
- `216` **内部流程** `func _apply_reading() -> void:`
- `226` **内部流程** `func _jump_reading() -> void:`
- `236` **内部流程** `func _report_reading() -> void:`
- `240` **内部流程** `func _image_action(id: String, action: String) -> void:`
- `249` **生命周期/引擎回调** `func _exit_tree() -> void:`
- `252` **内部流程** `func _update_density() -> void:`
- `258` **内部流程** `func _update_history_status(state: Dictionary) -> void:`

## [client-godot/src/ui/composer_input.gd](../client-godot/src/ui/composer_input.gd)

- `3` **信号** `signal send_requested`
- `4` **信号** `signal image_pasted(image: Image)`
- `6` **生命周期/引擎回调** `func _gui_input(event: InputEvent) -> void:`
- `15` **内部流程** `func _submit_key(event: InputEventKey) -> void:`

## [client-godot/src/ui/decision_dialog.gd](../client-godot/src/ui/decision_dialog.gd)

- `2` **信号** `signal confirmed`
- `3` **信号** `signal canceled`
- `4` **信号** `signal custom_action(action: String)`
- `10` **生命周期/引擎回调** `func _ready() -> void:`
- `19` **内部流程** `func _display() -> void:`
- `27` **内部流程** `func _cancel() -> void:`
- `31` **公开接口** `func get_ok_button() -> Button:`
- `34` **公开接口** `func get_cancel_button() -> Button:`
- `37` **生命周期/引擎回调** `func _input(event: InputEvent) -> void:`

## [client-godot/src/ui/draft_window.gd](../client-godot/src/ui/draft_window.gd)

- `3` **内部流程** `func _init() -> void:`
- `5` **生命周期/引擎回调** `func _ready() -> void:`
- `17` **公开接口** `func open() -> void:`
- `19` **公开接口** `func is_dirty() -> bool:`

## [client-godot/src/ui/dropdown_item.gd](../client-godot/src/ui/dropdown_item.gd)

- `3` **公开接口** `func setup(item: Dictionary) -> void:`

## [client-godot/src/ui/dynamic_comment_row.gd](../client-godot/src/ui/dynamic_comment_row.gd)

- `17` **公开接口** `func setup(avatar_path: String,author: String,body: String,time_text: String,created_at: String,allow_comment: bool,reply_action: Callable) -> void:`
- `28` **生命周期/引擎回调** `func _ready() -> void:`
- `32` **内部流程** `func _apply() -> void:`

## [client-godot/src/ui/dynamic_detail.gd](../client-godot/src/ui/dynamic_detail.gd)

- `2` **常量** `const CommentRow = preload("res://scenes/ui/dynamic_comment_row.tscn")`
- `28` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `36` **内部流程** `func _apply_ui_style() -> void:`
- `47` **公开接口** `func setup(controller: Node,post: Dictionary) -> void:`
- `52` **生命周期/引擎回调** `func _ready() -> void:`
- `56` **内部流程** `func _initialize() -> void:`
- `72` **公开接口** `func update_post(post: Dictionary) -> void:`
- `81` **公开接口** `func is_dirty() -> bool:`
- `84` **公开接口** `func update_comments() -> void:`
- `111` **内部流程** `func _place_reply() -> void:`
- `121` **内部流程** `func _submit(reply: bool) -> void:`
- `140` **内部流程** `func _set_status(text: String) -> void:`
- `144` **公开接口** `func refresh_comments() -> void:`
- `147` **内部流程** `func _at_bottom() -> void:`
- `154` **公开接口** `static func avatar_path(item: Dictionary) -> String:`
- `157` **公开接口** `static func relative_time(raw: String) -> String:`
- `173` **内部流程** `func _update_comment_status(state: Dictionary) -> void:`
- `179` **内部流程** `static func _valid_calendar_time(raw: String) -> bool:`
- `188` **内部流程** `static func _february_days(year: int) -> int:`

## [client-godot/src/ui/dynamics_post_row.gd](../client-godot/src/ui/dynamics_post_row.gd)

- `3` **常量** `const TYPES := {"citywalk":"城市漫步","diary":"天依日记","song_learned":"学会新歌","system_notice":"系统通知","user_post":"生活动态"}`
- `11` **公开接口** `func setup(post: Dictionary,avatar_path: String) -> void:`
- `16` **生命周期/引擎回调** `func _ready() -> void:`
- `20` **内部流程** `func _apply() -> void:`

## [client-godot/src/ui/dynamics_window.gd](../client-godot/src/ui/dynamics_window.gd)

- `3` **常量** `const Detail = preload("res://src/ui/dynamic_detail.gd")`
- `4` **常量** `const DetailScene = preload("res://scenes/ui/dynamic_detail.tscn")`
- `5` **常量** `const PostRow = preload("res://scenes/ui/dynamics_post_row.tscn")`
- `30` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `38` **内部流程** `func _apply_ui_style() -> void:`
- `49` **公开接口** `func setup(controller: Node,settings_store: Resource = null) -> void:`
- `54` **生命周期/引擎回调** `func _ready() -> void:`
- `59` **内部流程** `func _initialize() -> void:`
- `85` **公开接口** `func get_selected_id() -> String:`
- `88` **公开接口** `func select_post(id: String) -> bool:`
- `113` **内部流程** `func _refresh_selected_comments(id: String) -> void:`
- `117` **公开接口** `func is_dirty() -> bool:`
- `121` **内部流程** `func _update_unread(count: int) -> void:`
- `132` **内部流程** `func _update() -> void:`
- `149` **内部流程** `func _select_style() -> void:`
- `154` **内部流程** `func _refresh() -> void:`
- `161` **内部流程** `func _open_publisher() -> void:`
- `174` **内部流程** `func _list_input(event: InputEvent) -> void:`
- `178` **内部流程** `func _at_bottom() -> void:`
- `184` **内部流程** `func _resize_split() -> void:`
- `187` **内部流程** `func _save_layout() -> void:`

## [client-godot/src/ui/frost_surface.gd](../client-godot/src/ui/frost_surface.gd)

- `4` **生命周期/引擎回调** `func _ready() -> void:`

## [client-godot/src/ui/image_presenter.gd](../client-godot/src/ui/image_presenter.gd)

- `2` **常量** `const ImageScene = preload("res://scenes/ui/image_window.tscn")`
- `8` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `12` **内部流程** `func _style_window() -> void:`
- `15` **内部流程** `func _init(geometry: Resource = null, window_system: Resource = null) -> void:`
- `18` **公开接口** `func open_image(source: Window, provider: Callable, confirm: Callable = Callable()) -> Window:`
- `28` **公开接口** `func close() -> void:`
- `30` **公开接口** `func close_confirmation(source: Window) -> void:`
- `33` **生命周期/引擎回调** `func _exit_tree() -> void:`

## [client-godot/src/ui/image_window.gd](../client-godot/src/ui/image_window.gd)

- `12` **生命周期/引擎回调** `func _ready() -> void:`
- `25` **公开接口** `func present(source: Window, provider: Callable, confirm: Callable = Callable()) -> void:`
- `42` **内部流程** `func _reveal() -> void:`
- `45` **内部流程** `func _load_image() -> void:`
- `54` **内部流程** `func _resize_image() -> void:`
- `64` **内部流程** `func _zoom_by(factor: float) -> void:`
- `69` **公开接口** `func close_image() -> void:`
- `82` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `94` **生命周期/引擎回调** `func _input(event: InputEvent) -> void:`

## [client-godot/src/ui/log_window.gd](../client-godot/src/ui/log_window.gd)

- `19` **公开接口** `func setup(logger: RefCounted) -> void:`
- `24` **生命周期/引擎回调** `func _ready() -> void:`
- `30` **内部流程** `func _initialize() -> void:`
- `64` **公开接口** `func open() -> void:`
- `83` **内部流程** `func _refresh() -> void:`
- `94` **内部流程** `func _matches(entry: Dictionary) -> bool:`
- `97` **内部流程** `func _append(entry: Dictionary) -> void:`
- `105` **生命周期/引擎回调** `func _exit_tree() -> void:`

## [client-godot/src/ui/message_audio.gd](../client-godot/src/ui/message_audio.gd)

- `2` **信号** `signal action(value: String)`
- `12` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `17` **内部流程** `func _update_icon() -> void:`
- `21` **生命周期/引擎回调** `func _ready() -> void:`
- `25` **公开接口** `func update_state(state: Dictionary) -> void:`

## [client-godot/src/ui/message_bubble.gd](../client-godot/src/ui/message_bubble.gd)

- `2` **信号** `signal audio_action(action: String)`
- `3` **信号** `signal image_opened(texture: Texture2D)`
- `4` **信号** `signal image_action(action: String)`
- `5` **常量** `const USER_ICON := preload("res://assets/ui/user_icon.png")`
- `6` **常量** `const TIANYI_ICON := preload("res://assets/ui/tianyi_icon.png")`
- `7` **常量** `const AudioRow = preload("res://scenes/ui/message_audio.tscn")`
- `35` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `43` **内部流程** `func _apply_ui_style() -> void:`
- `50` **生命周期/引擎回调** `func _ready() -> void:`
- `67` **公开接口** `func configure(message: Dictionary, image_texture: Texture2D = null) -> void:`
- `96` **内部流程** `func _resize_bubble() -> void:`
- `118` **内部流程** `func _queue_layout() -> void:`
- `123` **内部流程** `func _sync_height() -> void:`
- `129` **公开接口** `func update_message(message: Dictionary) -> void:`
- `138` **公开接口** `func set_time_marker(text: String) -> void:`
- `142` **公开接口** `func set_audio_state(state: Dictionary) -> void:`
- `153` **公开接口** `func set_image_state(state: Dictionary) -> void:`

## [client-godot/src/ui/message_waveform.gd](../client-godot/src/ui/message_waveform.gd)

- `13` **生命周期/引擎回调** `func _ready() -> void:`
- `16` **内部流程** `func _refresh() -> void:`

## [client-godot/src/ui/model_page.gd](../client-godot/src/ui/model_page.gd)

- `2` **信号** `signal plaintext_answer(allowed: bool)`
- `3` **常量** `const Card = preload("res://scenes/ui/model_purpose_card.tscn")`
- `17` **公开接口** `func setup(settings: Node, executor: Node = null) -> void:`
- `22` **生命周期/引擎回调** `func _ready() -> void:`
- `26` **内部流程** `func _initialize() -> void:`
- `37` **公开接口** `func is_dirty() -> bool:`
- `42` **内部流程** `func _as_draft(config: Dictionary) -> Dictionary:`
- `47` **内部流程** `func _update(state: Dictionary) -> void:`
- `68` **内部流程** `func _set_editable() -> void:`
- `73` **内部流程** `func _reload() -> void:`
- `83` **内部流程** `func _locate_error(id: String, code: String) -> void:`
- `88` **内部流程** `func _reveal_error_card(card: Control) -> void:`
- `92` **公开接口** `func validate_changes() -> Dictionary:`
- `109` **公开接口** `func save_changes() -> Dictionary:`
- `140` **内部流程** `func _copy_config(id: String, source_id: String) -> void:`
- `147` **内部流程** `func _request_test(id: String, draft: Dictionary) -> void:`
- `159` **内部流程** `func _test() -> void:`

## [client-godot/src/ui/model_purpose_card.gd](../client-godot/src/ui/model_purpose_card.gd)

- `2` **信号** `signal edited(id: String, draft: Dictionary)`
- `3` **信号** `signal copy_requested(id: String, source_id: String)`
- `4` **信号** `signal test_requested(id: String, draft: Dictionary)`
- `12` **公开接口** `func setup(purpose: Dictionary, draft: Dictionary, purposes: Array, can_test: bool = false) -> void:`
- `18` **生命周期/引擎回调** `func _ready() -> void:`
- `38` **公开接口** `func set_draft(draft: Dictionary) -> void:`
- `50` **公开接口** `func set_editable(value: bool) -> void:`
- `56` **公开接口** `func show_error(text: String) -> void:`
- `60` **内部流程** `func _edit() -> void:`

## [client-godot/src/ui/popup_trigger.gd](../client-godot/src/ui/popup_trigger.gd)

- `8` **内部流程** `func _init(trigger: BaseButton, popup: Popup) -> void:`
- `13` **公开接口** `func should_open() -> bool:`
- `23` **内部流程** `func _on_hidden() -> void:`
- `27` **内部流程** `func _clear_dismissal() -> void:`

## [client-godot/src/ui/preferences_page.gd](../client-godot/src/ui/preferences_page.gd)

- `9` **公开接口** `func setup(controller: Node) -> void:`
- `12` **生命周期/引擎回调** `func _ready() -> void:`
- `16` **内部流程** `func _initialize() -> void:`
- `46` **公开接口** `func is_dirty() -> bool:`
- `48` **内部流程** `func _edit() -> void:`
- `55` **内部流程** `func _update(state: Dictionary) -> void:`
- `68` **公开接口** `func save_changes() -> Dictionary:`
- `74` **内部流程** `func _update_presets(state: Dictionary) -> void:`

## [client-godot/src/ui/publish_overlay.gd](../client-godot/src/ui/publish_overlay.gd)

- `2` **信号** `signal close_requested`
- `3` **信号** `signal published(id: String)`
- `9` **公开接口** `func setup(controller: Node) -> void:`
- `11` **生命周期/引擎回调** `func _ready() -> void:`
- `16` **公开接口** `func is_dirty() -> bool:`
- `18` **内部流程** `func _publish() -> void:`
- `34` **公开接口** `func open() -> void:`
- `37` **内部流程** `func _request_close() -> void:`
- `42` **生命周期/引擎回调** `func _input(event: InputEvent) -> void:`

## [client-godot/src/ui/settings_window.gd](../client-godot/src/ui/settings_window.gd)

- `3` **常量** `const StorageService = preload("res://src/storage/storage_service.gd")`
- `4` **信号** `signal saving_finished(ok: bool)`
- `5` **信号** `signal logout_requested`
- `22` **公开接口** `func set_ui_style(ui_style: RefCounted) -> void:`
- `26` **公开接口** `func setup(preferences: Node, models: Node, executor: Node = null, clear_cache: Callable = Callable(), storage_service: StorageService = null, cache_directory: String = "") -> void:`
- `34` **生命周期/引擎回调** `func _ready() -> void:`
- `59` **公开接口** `func select_page(page: String) -> void:`
- `69` **公开接口** `func open() -> void:`
- `73` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `85` **公开接口** `func is_dirty() -> bool:`
- `89` **公开接口** `func is_saving() -> bool:`
- `92` **内部流程** `func _request_close() -> void:`
- `101` **公开接口** `func save_changes() -> Dictionary:`
- `130` **内部流程** `func _report(results: Array) -> void:`
- `143` **内部流程** `func _set_result(text: String, kind: String) -> void:`
- `149` **生命周期/引擎回调** `func _input(event: InputEvent) -> void:`

## [client-godot/src/ui/style_page.gd](../client-godot/src/ui/style_page.gd)

- `7` **生命周期/引擎回调** `func _ready() -> void:`
- `10` **公开接口** `func set_ui_style(ui_style: RefCounted) -> void:`
- `15` **内部流程** `func _initialize_ui_style() -> void:`
- `28` **内部流程** `func _sync_ui_style_controls(style: String, icons: String) -> void:`
- `45` **内部流程** `func _on_ui_style_selected(id, field: String) -> void:`
- `56` **公开接口** `func ui_style_dirty() -> bool:`
- `61` **公开接口** `func save_ui_style() -> Dictionary:`

## [client-godot/src/ui/unified_dropdown.gd](../client-godot/src/ui/unified_dropdown.gd)

- `4` **信号** `signal activated(id: String)`
- `5` **常量** `const Item = preload("res://scenes/ui/dropdown_item.tscn")`
- `6` **常量** `const SeparatorScene = preload("res://scenes/ui/dropdown_separator.tscn")`
- `22` **生命周期/引擎回调** `func _ready() -> void:`
- `30` **公开接口** `func set_items(items: Array) -> Error:`
- `42` **公开接口** `func get_items() -> Array:`
- `45` **公开接口** `func set_selected_id(id: String) -> bool:`
- `51` **公开接口** `func get_selected_id() -> String:`
- `54` **公开接口** `func clear_selection() -> void:`
- `58` **公开接口** `func set_item_enabled(id: String, enabled: bool) -> void:`
- `64` **内部流程** `func _available(id: String) -> bool:`
- `67` **内部流程** `func _caption() -> void:`
- `74` **内部流程** `func _build() -> void:`
- `91` **公开接口** `func open_menu() -> void:`
- `114` **内部流程** `func _label(id: String) -> String:`
- `119` **公开接口** `func close_menu() -> void:`
- `122` **公开接口** `func is_menu_open() -> bool:`
- `125` **内部流程** `func _activate(id: String) -> void:`
- `131` **内部流程** `func _key_input(event: InputEvent) -> void:`
- `148` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `154` **内部流程** `func _valid_items(items: Array) -> bool:`
- `164` **内部流程** `func _focus_menu_items() -> void:`

## [client-godot/src/ui/virtual_message_list.gd](../client-godot/src/ui/virtual_message_list.gd)

- `2` **信号** `signal visible_messages(ids: Array[String])`
- `3` **信号** `signal interacted`
- `4` **信号** `signal audio_action(id: String, action: String)`
- `5` **信号** `signal image_opened(texture: Texture2D)`
- `6` **信号** `signal image_action(id: String, action: String)`
- `7` **常量** `const Bubble = preload("res://scenes/ui/message_bubble.tscn")`
- `8` **常量** `const ChatTime = preload("res://src/ui/chat_time.gd")`
- `26` **公开接口** `func set_ui_style(style: RefCounted) -> void:`
- `30` **生命周期/引擎回调** `func _ready() -> void:`
- `38` **公开接口** `func set_messages(messages: Array[Dictionary]) -> void:`
- `57` **公开接口** `func scroll_to_message(id: String) -> bool:`
- `63` **公开接口** `func scroll_to_latest() -> void:`
- `66` **公开接口** `func get_visible_ids() -> Array[String]:`
- `69` **公开接口** `func get_reading_anchor() -> Dictionary:`
- `81` **公开接口** `func is_at_latest() -> bool:`
- `86` **公开接口** `func set_audio_state(id: String, state: Dictionary) -> void:`
- `90` **公开接口** `func set_image_state(id: String, state: Dictionary) -> void:`
- `94` **内部流程** `func _user_input(event: InputEvent) -> void:`
- `99` **生命周期/引擎回调** `func _input(event: InputEvent) -> void:`
- `104` **内部流程** `func _resized() -> void:`
- `112` **生命周期/引擎回调** `func _process(_delta: float) -> void:`
- `129` **内部流程** `func _layout(anchor: Dictionary, follow: bool) -> void:`
- `156` **内部流程** `func _defer_scroll_restore() -> void:`
- `161` **内部流程** `func _finish_scroll_restore() -> void:`
- `176` **内部流程** `func _render() -> void:`
- `203` **内部流程** `func _remove(id: String) -> void:`
- `209` **内部流程** `func _at(position_y: float) -> int:`
- `220` **内部流程** `func _create_bubble(id: String, message: Dictionary) -> void:`

## [client-godot/src/ui/window_chrome.gd](../client-godot/src/ui/window_chrome.gd)

- `4` **生命周期/引擎回调** `func _enter_tree() -> void:`
- `6` **公开接口** `func set_login_mode(enabled: bool) -> void:`
- `9` **公开接口** `func configure(store: RefCounted, key: String) -> void:`
- `11` **公开接口** `func select_layout(key: String, size: Vector2i, minimum: Vector2i) -> void:`
- `13` **公开接口** `func open_window() -> void:`
- `15` **生命周期/引擎回调** `func _process(delta: float) -> void:`
- `17` **生命周期/引擎回调** `func _exit_tree() -> void:`
## 关键调用关系

- `application.gd._ready` → `ApplicationServices.mount` → `AccountSession/ChatSession/AccountLifecycle/WindowCoordinator`；`_account_changed` 根据状态切换 `account_view` 与双栏布局。
- `AccountView` → `AccountSession.perform/resume/logout` → `AccountApi` + `StorageService`；成功后 `AccountLifecycle.start` 建立新 generation。
- `ChatView` → `ChatSession` → `WebSocketTransport`/`HistorySync`/`ReplyAudio`/`HistoryImages`；Transport → `ReliableOutbox`。ChatSession 保留消息 timestamp，ChatTime 与 VirtualMessageList 负责时间条分组。
- `SettingsWindow` → `PreferencesPage`/`ModelPage`/`AudioSettingsPage`/`StylePage`；统一保存模型、服务器偏好和本地 UiStyle，缓存清理独立执行。
- `DynamicsWindow` → `DynamicsController` → `JsonRequest`；列表滚动分页、当前卡片刷新评论；未读预览经 Application 转发到 AvatarPanel。
- `MessageBubble`/`VirtualMessageList` → `ImagePresenter`/`ReplyAudio`；图片窗口关闭后恢复来源窗口焦点。
- `WindowChrome` → `WindowHost`/`WindowSystem`；`Godot*` 和 Windows 实现是唯一平台 API 入口。
- `AppearanceService`、`WorldService`、`DeviceService` 只由 `AccountLifecycle` 可选启动，默认立即拒绝。

函数声明上方的 `信号/常量/生命周期/公开接口/内部流程` 标记来自当前源码扫描；未把历史迁移路径写入现行函数列表。

## 按模块的主要函数详解

以下表格只解释会改变状态、发起异步操作、管理资源或连接平台的函数；简单控件赋值函数仍以源码签名索引为准。

### application / composition

| 函数 | 调用关系 | 关键行为 |
|---|---|---|
| `Application._ready` | main → composition | 创建服务、日志、WindowCoordinator，绑定账号；安全组件不可用时停止正式装配但保留反馈/日志。 |
| `Application._account_changed` | AccountSession → lifecycle/UI | signed_in 时懒创建 Avatar/Chat 并启动 lifecycle；其他状态停止并释放业务视图。 |
| `AccountLifecycle.start/stop` | Application → controllers | 计算 scope+message_token identity，递增 generation，按依赖启动；失败调用 stop 回滚，按实现顺序停止可选能力、模型、动态和聊天。 |
| `ApplicationServices.mount` | composition → all services | 创建并注入 Account、Model、Dynamics、History、Audio、Chat 及存储实现。 |
| `UiStyle.configure/save_preferences/register_icon` | 本地设置 → theme/views | 装配时读取本地风格；两项成功保存后更新共享主题和图标、发 style_changed，失败回滚。 |

### domain

| 函数 | 关键行为 |
|---|---|
| `ServerAddress.normalize` | 补 scheme、校验 host/IP/端口、去默认端口与尾斜杠；非法输入返回空串。 |
| `AccountScope.key` | 对规范化 server+username JSON 做 SHA-256；空值返回空串。 |

### session

| 函数 | 关键行为 |
|---|---|
| `AccountSession._load_profile` | 读取旧版配置并迁移到 version 2 账号数组，失败标记 storage error。 |
| `AccountSession.perform/set_server/logout` | 认证、服务器探测、令牌保存/清理；generation 变化返回 CANCELLED，退出清理当前 scope。 |
| `ChatSession.start/send_text` | 先验证 transport，再启动历史/媒体；历史边界前把消息放 pending，边界释放后转 durable。 |
| `ChatSession._receive_reply/_reply_timestamp/_update_reply/_present_replies` | 首次 UUID 记录事件毫秒时间或本地到达时间；后续分片不移动时间，聚合后交付音频并顺序展示。 |
| `HistorySync._load/_valid_page_bounds/_page_messages/_deduplicate` | 分步校验分页连续性与消息内容、UUID 去重、发 boundary_ready；retry/skip 仍为失败处理入口。 |
| `DynamicsController._request/_write` | 通过 JsonRequest 访问动态接口，校验分页/评论；调用方 UI 在写入失败时保留草稿。 |
| `DynamicsController.refresh_unread/_load_latest_unread/get_latest_unread` | 获取数量与非用户未读动态预览；失败尽量保留已知预览，成功标记已读后清空。 |
| `ModelSettings.validate/save` | 校验模型用途和 capability 后逐项保存；部分失败保留对应草稿。 |
| `PreferencesController.reload/edit/save` | 读取基线、计算 dirty、合并四字段并写回；保存期间拒绝重复操作。 |
| `ModelExecutor.submit/_execute` | 校验 request/config/VLM 图片，发送非流式模型请求，按 generation 回收结果。 |

### network

| 函数 | 关键行为 |
|---|---|
| `AccountApi._perform/_exchange` | 获取公钥、加密密码、调用 auth endpoint；单请求、64 KiB body、generation 取消。 |
| `HistoryApi.fetch_page` | 按 server/user/token 拉取 50 条分页，校验 history 和 start_index。 |
| `JsonRequest.send/cancel` | 单请求、8 MiB body、JSON 顶层 Dictionary 约束；取消释放 await。 |
| `ReliableOutbox.take_ready/acknowledge` | durable 严格顺序、断线过期、ACK/NACK/退避和 uncertain 结果。 |
| `WebSocketTransport._process/_handle_event` | 管理连接/认证/心跳/重连，每帧最多消费 64 包并交给 outbox 或上层。 |

### storage

| 函数 | 关键行为 |
|---|---|
| `GodotStorageService.read/write_login_profile` | 保留兼容配置格式并原子保存登录资料。 |
| `CredentialStore.save/read/forget` | 以 AccountScope 定位受保护 token；安全失败不明文降级。 |
| `AudioCache.begin/append/commit/open_stream/clear_cache` | `.part/.tmp` 写入、manifest 配对、账号隔离和按天清理；流关闭幂等。 |
| `HistoryImages.ensure/retry/_decode` | 下载/缓存图片，先验证可信头部和像素上限，再创建纹理。 |
| `ClientLog.record/_save_metadata/finish/export_run` | 记录条数/字节上限、运行元数据和导出；中断状态保持 incomplete。 |
| `WindowGeometry.read_layout/write_layout` | 恢复可见位置/尺寸/最大化状态，不恢复最小化。 |

### media / avatar

| 函数 | 关键行为 |
|---|---|
| `ReplyAudio.append_reply_audio/play_reply/replay` | 接收分片、提交缓存、创建 decoder/播放器并发状态/口型信号。 |
| `CacheReplay._process/stop` | 从 ReadStream 增量读帧、更新波形，停止时关闭流。 |
| `ImageAttachment.from_data_uri/from_bytes` | 统一 MIME/base64/字节/像素/边长校验，超限前拒绝。 |
| `AvatarPanel._handle_pointer/_layout_avatar/set_unread_dynamic` | 以 Stage 尺寸计算构图和触摸；显示最新未读动态卡片，重置按钮悬浮右下角。 |
| `CubismAvatarDriver.load_avatar/_apply_parameters` | 加载模型资源并每帧驱动表情、动作、口型和视线。 |

### ui / preview

| 函数 | 关键行为 |
|---|---|
| `AccountView._send/_update_state` | 处理登录/注册/重置提交和结果，控制请求中状态与错误文案。 |
| `ChatView._send/_state_changed/_show_volume/_update_density` | 提交消息、按需显示历史状态、弹出音量滑条、窄窗口调整按钮文案。 |
| `MessageBubble.update_message/set_time_marker/set_ui_style` | VBox 内时间条与 Row 分层；Caption 仅显示失败/不确定；时间条、气泡和语音行同步风格。 |
| `ChatTime.markers/seconds/label` | 解析数字/日历时间，首条与至少 300 秒间隔显示时间，系统/无效时间不参与分组，乱序不回退基线。 |
| `SettingsWindow.save_changes/_request_close` | 校验后依次保存模型、服务器偏好和本地风格，汇总结果；保存中关闭等待结果。 |
| `StylePage._on_ui_style_selected/ui_style_dirty/save_ui_style` | 选择只改草稿，成功持久化后才改变外观；失败保留草稿。 |
| `DynamicsWindow._list_input/_at_bottom/select_post/_refresh_selected_comments` | 滚动加载或重试；点击当前动态刷新评论，切换时保存阅读位置。 |
| `DynamicsWindow._open_publisher` | 打开发布层，底部取消/Esc 走草稿保护，标题栏无关闭按钮。 |
| `DynamicDetail._at_bottom/_update_comment_status` | 评论触底自动分页，无 LoadMore 按钮；加载失败保留内容并提示点击动态卡片重试。 |
| `ImagePresenter.open_image` / `UnifiedDropdown.open_menu` | 复用单例图片窗、来源归属和焦点；下拉第一次开、第二次关。 |
| `VirtualMessageList.set_messages/_layout/_render/_create_bubble` | 计算时间标记、失效高度缓存、按阅读锚点虚拟化气泡；时间条不额外创建消息 ID。 |
| `DemoSession.submit_text/settle` | 只修改离线样例，不创建网络或正式账号状态。 |

### platform / native / extensions

| 函数 | 关键行为 |
|---|---|
| `DesktopWindowHost.select_layout/tick/save` | 恢复/限制窗口几何，处理最小化和显示器可见范围。 |
| `GodotFileInteraction._selected/_canceled` | 将原生 FileDialog 结果转换成 bytes/mime/受控导出目标。 |
| `WindowsSecretProtection.protect_secret/unprotect_secret` | 封装 DPAPI/原生错误阶段，DLL 缺失返回 SECURITY_UNAVAILABLE。 |
| `NativeDecoderFactory.create_decoder` | 返回 PcmStreamDecoder wrapper 或 null。 |
| `Appearance/World/Device.start/request/stop` | 当前默认立即拒绝，不建立连接、轮询或完成任务。 |

### tests-and-build

| 函数/脚本 | 关键行为 |
|---|---|
| `Invoke-GodotChecked` | 校验引擎版本、退出码、Parse Error、ERROR、FAIL 并保存日志。 |
| `run_*_tests.py` | 创建隔离 APPDATA/LOCALAPPDATA 和本地 fixture，执行 Godot 后清理。 |
| `build.ps1` | 当前工作区默认打 ZIP；交互/显式输入版本与引擎，校验并同步版本，同版本旧包保留，临时导出验证后移动产物。 |
| `verify_release_archive.py` | 校验 release metadata、精确文件集合、ZIP CRC、DLL 锁定哈希。 |
| `check_complexity.py` / `complexity/*` | 独立多语言静态检查，固定 CC 阈值 10，依赖版本/解析错误同样判失败。 |
| `test_complexity_check.py` / `test_build_prompt.py` | 分别验证分析规则与 fake exporter 构建编排，不代替 Godot 行为或真实导出。 |
