extends "res://src/platform/password_encryption.gd"
func is_available() -> bool:
	return ClassDB.class_exists("WindowsSecurity")
func encrypt_password(public_key: String, password: String) -> Dictionary:
	if not is_available(): return super.encrypt_password(public_key,password)
	return ClassDB.instantiate("WindowsSecurity").encrypt_password(public_key,password)
