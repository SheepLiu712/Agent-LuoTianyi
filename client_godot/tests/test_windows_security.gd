extends SceneTree
var failures: Array[String] = []

func check(value: bool, description: String) -> void:
	if not value:
		failures.append(description)
		print("FAIL: ", description)

func _initialize() -> void:
	if not ClassDB.class_exists("WindowsSecurity"):
		var unavailable = load("res://src/platform/windows_secret_protection.gd").new()
		var missing: Dictionary = unavailable.protect_secret("secret".to_utf8_buffer(), "scope".to_utf8_buffer())
		check(not missing.ok and missing.error == "SECURITY_UNAVAILABLE" and missing.data.is_empty(), "missing security DLL is explicit")
		print("ENVIRONMENT: WindowsSecurity extension unavailable")
		quit(2)
		return
	var security = ClassDB.instantiate("WindowsSecurity")
	var scope := "https://test.invalid/account-A".to_utf8_buffer()
	var plain := "synthetic-secret-中文".to_utf8_buffer()
	var protected: Dictionary = security.protect_secret(plain, scope)
	check(protected.ok, "DPAPI protection succeeds")
	check(protected.get("stage", "") == "native_code" and protected.has("native_code"), "native result identifies implementation stage")
	check(not security.protect_secret(PackedByteArray(), scope).ok, "empty secret rejected")
	check(not security.protect_secret(plain, PackedByteArray()).ok, "empty scope rejected")
	if protected.ok:
		check(protected.data != plain, "ciphertext differs from plaintext")
		var restored: Dictionary = security.unprotect_secret(protected.data, scope)
		check(restored.ok and restored.data == plain, "same user and scope restore secret")
		var wrong_scope: Dictionary = security.unprotect_secret(protected.data, "other-account".to_utf8_buffer())
		check(not wrong_scope.ok and wrong_scope.get("stage", "") == "native_code" and int(wrong_scope.get("native_code", 0)) != 0, "wrong scope rejected by native protection")
		var damaged: PackedByteArray = protected.data.duplicate()
		damaged[damaged.size() - 1] ^= 255
		check(not security.unprotect_secret(damaged, scope).ok, "tampered DPAPI blob rejected")
	var large := PackedByteArray()
	large.resize(65537)
	check(not security.protect_secret(large, scope).ok, "secret size bounded")
	var invalid: Dictionary = security.encrypt_password("not PEM", "test")
	check(not invalid.ok and invalid.error == "INVALID_KEY" and invalid.data.is_empty() and invalid.get("stage", "") == "native_code" and invalid.has("native_code"), "bad key has safe native error")
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--fixture="):
			var path := argument.trim_prefix("--fixture=")
			var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
			var ciphertexts: Array[String] = []
			for password in fixture.passwords:
				var encrypted: Dictionary = security.encrypt_password(fixture.public_key, password)
				check(encrypted.ok, "RSA encryption succeeds")
				ciphertexts.append(Marshalls.raw_to_base64(encrypted.data))
			check(not security.encrypt_password(fixture.public_key, "x".repeat(191)).ok, "OAEP maximum enforced")
			var file := FileAccess.open(path + ".out", FileAccess.WRITE)
			file.store_string(JSON.stringify(ciphertexts))
			file.close()
	print("Windows security: ", "PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
