extends SceneTree

const TlsTrust = preload("res://src/network/tls_trust.gd")
const CaBundleReader = preload("res://src/platform/godot_ca_bundle_reader.gd")
const BUNDLE_PATH := "res://certs/ca-bundle.pem"
const LOCK_PATH := "res://dependencies.lock.json"
const PRESET_PATH := "res://export_presets.cfg"
const PEM_MARKER := "-----BEGIN CERTIFICATE-----"
const R46 := "Sectigo Public Server Authentication Root R46"
const SOURCE_URL := "https://curl.se/ca/cacert.pem"
const OVERRIDE_SETTING := "network/tls/certificate_bundle_override"

var failures: Array[String] = []


func _initialize() -> void:
	run()


func check(ok: bool, label: String) -> void:
	if not ok:
		failures.append(label)
		print("FAIL: ", label)


func run() -> void:
	check(str(ProjectSettings.get_setting("network/tls/certificate_bundle_override", "")) == BUNDLE_PATH,
		"project setting points at the bundled CA file")
	check(FileAccess.file_exists(BUNDLE_PATH), "CA bundle exists")
	var text := FileAccess.get_file_as_string(BUNDLE_PATH)
	check(text.split(PEM_MARKER).size() - 1 >= 100, "CA bundle is the full Mozilla set")
	check(text.contains(R46), "CA bundle trusts Sectigo R46")
	check(X509Certificate.new().load(BUNDLE_PATH) == OK, "engine parses the whole bundle")
	_check_snapshot()
	_check_missing_bundle()
	_check_system_source()
	_check_event_fields()
	_check_lock()
	_check_export_preset()
	print("TLS trust: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)


func _check_snapshot() -> void:
	var snapshot: Dictionary = TlsTrust.snapshot(CaBundleReader.new())
	check(str(snapshot.get("trust_source", "")) == "bundle_override", "snapshot reports bundle override")
	check(bool(snapshot.get("bundle_present", false)), "snapshot sees the bundle file")
	check(bool(snapshot.get("bundle_loaded", false)), "snapshot loads the bundle")
	check(int(snapshot.get("bundle_cert_count", 0)) >= 100, "snapshot counts the Mozilla certificates")
	check(bool(snapshot.get("bundle_has_r46", false)), "snapshot detects Sectigo R46")
	check(str(snapshot.get("bundle_sha256", "")) == _digest().left(16), "snapshot hashes the bundle")


func _check_missing_bundle() -> void:
	var original := str(ProjectSettings.get_setting(OVERRIDE_SETTING, ""))
	ProjectSettings.set_setting(OVERRIDE_SETTING, "res://certs/missing.pem")
	var reader := CaBundleReader.new()
	var snapshot: Dictionary = TlsTrust.snapshot(reader)
	check(str(snapshot.get("trust_source", "")) == "bundle_override", "missing bundle keeps override source")
	check(not bool(snapshot.get("bundle_present", true)), "missing bundle is reported absent")
	var fields: Dictionary = TlsTrust.event_fields(reader)
	check(str(fields.get("code", "")) == "TLS_BUNDLE_MISSING", "missing bundle event code")
	check(str(fields.get("phase", "")) == "failed", "missing bundle event fails")
	ProjectSettings.set_setting(OVERRIDE_SETTING, original)


func _check_system_source() -> void:
	var original := str(ProjectSettings.get_setting(OVERRIDE_SETTING, ""))
	ProjectSettings.set_setting(OVERRIDE_SETTING, "")
	var snapshot: Dictionary = TlsTrust.snapshot(CaBundleReader.new())
	check(str(snapshot.get("trust_source", "")) == "system_or_builtin", "empty setting reports system source")
	check(int(snapshot.get("bundle_cert_count", 0)) == -1, "system source leaves certificate count unknown")
	ProjectSettings.set_setting(OVERRIDE_SETTING, original)


func _check_event_fields() -> void:
	var fields: Dictionary = TlsTrust.event_fields(CaBundleReader.new())
	check(str(fields.get("code", "")) == "OK", "loaded bundle event succeeds")
	check(str(fields.get("phase", "")) == "complete", "loaded bundle event completes")
	check(str(fields.get("detail", "")).contains("r46=true"), "event detail records R46")
	var data: Dictionary = fields.get("data", {})
	check(bool(data.get("bundle_loaded", false)), "event data carries bundle load state")


func _check_lock() -> void:
	var parser := JSON.new()
	check(parser.parse(FileAccess.get_file_as_string(LOCK_PATH)) == OK, "dependency lock parses")
	if not (parser.data is Dictionary):
		return
	var ca_bundle: Dictionary = parser.data.get("ca_bundle", {})
	check(str(ca_bundle.get("url", "")) == SOURCE_URL, "CA bundle source is recorded")
	check(str(ca_bundle.get("sha256", "")).to_lower() == _digest(), "CA bundle matches the lock hash")


func _check_export_preset() -> void:
	if not FileAccess.file_exists(PRESET_PATH):
		print("note: export_presets.cfg absent; export filter is not checked")
		return
	check(FileAccess.get_file_as_string(PRESET_PATH).contains("*.pem"), "export preset includes PEM files")


func _digest() -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(FileAccess.get_file_as_bytes(BUNDLE_PATH))
	return context.finish().hex_encode()
