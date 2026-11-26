extends RefCounted
## TLS 信任源快照：记录引擎实际会使用的 CA 配置，不修改或绕过信任链。

const Schema = preload("res://src/storage/log_schema.gd")

const OVERRIDE_SETTING := "network/tls/certificate_bundle_override"
const PEM_MARKER := "-----BEGIN CERTIFICATE-----"
const R46_LABEL := "Sectigo Public Server Authentication Root R46"
const MAX_BUNDLE_BYTES := 2 * 1024 * 1024


static func snapshot(reader: Resource) -> Dictionary:
	var path := str(ProjectSettings.get_setting(OVERRIDE_SETTING, "")).strip_edges()
	var result := _empty_snapshot(path)
	if path.is_empty():
		return result
	var probe: Dictionary = reader.read(path) if reader != null else {}
	result.bundle_present = bool(probe.get("present", false))
	if not result.bundle_present:
		return result
	_inspect_bundle(probe, result)
	return result


static func event_fields(reader: Resource) -> Dictionary:
	var started := Time.get_ticks_usec()
	var data := snapshot(reader)
	var code := _code_for(data)
	return {
		"operation":"tls_trust_snapshot",
		"outcome":"success" if code == "OK" else "failure",
		"duration_ms":int((Time.get_ticks_usec() - started) / 1000),
		"phase":"complete" if code == "OK" else "failed",
		"code":code,
		"detail":_detail(data),
		"data":data,
	}


static func _empty_snapshot(path: String) -> Dictionary:
	var override := not path.is_empty()
	return {
		"trust_source":"bundle_override" if override else "system_or_builtin",
		"bundle_path":Schema.sanitize_text(path, 128),
		"bundle_present":false,
		"bundle_loaded":false,
		"bundle_cert_count":0 if override else -1,
		"bundle_has_r46":false,
		"bundle_sha256":"",
	}


static func _inspect_bundle(probe: Dictionary, result: Dictionary) -> void:
	var bytes: PackedByteArray = probe.get("bytes", PackedByteArray())
	if bytes.is_empty() or bytes.size() > MAX_BUNDLE_BYTES:
		return
	var text := bytes.get_string_from_utf8()
	result.bundle_cert_count = text.count(PEM_MARKER)
	result.bundle_has_r46 = text.contains(R46_LABEL)
	result.bundle_sha256 = _sha256_prefix(bytes)
	result.bundle_loaded = bool(probe.get("loaded", false))


static func _code_for(data: Dictionary) -> String:
	if str(data.get("trust_source", "")) != "bundle_override":
		return "OK"
	if not bool(data.get("bundle_present", false)):
		return "TLS_BUNDLE_MISSING"
	if not bool(data.get("bundle_loaded", false)):
		return "TLS_BUNDLE_INVALID"
	return "OK"


static func _detail(data: Dictionary) -> String:
	var source := str(data.get("trust_source", "unknown"))
	if source != "bundle_override":
		return "trust_source=%s; root_store_count=unknown" % source
	return "trust_source=bundle_override; bundle=%s; present=%s; loaded=%s; certs=%d; r46=%s; sha256=%s" % [
		str(data.get("bundle_path", "")), bool(data.get("bundle_present", false)),
		bool(data.get("bundle_loaded", false)), int(data.get("bundle_cert_count", 0)),
		bool(data.get("bundle_has_r46", false)), str(data.get("bundle_sha256", "")),
	]


static func _sha256_prefix(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish().hex_encode().left(16)
