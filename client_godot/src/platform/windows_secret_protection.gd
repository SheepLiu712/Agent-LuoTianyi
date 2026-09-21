extends "res://src/platform/secret_protection.gd"

func _security_unavailable() -> Dictionary:
	return {"ok":false,"data":PackedByteArray(),"error":"SECURITY_UNAVAILABLE"}

func protect_secret(plain: PackedByteArray, scope: PackedByteArray) -> Dictionary:
	if not ClassDB.class_exists("WindowsSecurity"):
		return _security_unavailable()
	var security = ClassDB.instantiate("WindowsSecurity")
	if security == null:
		return _security_unavailable()
	return security.protect_secret(plain,scope)

func unprotect_secret(cipher: PackedByteArray, scope: PackedByteArray) -> Dictionary:
	if not ClassDB.class_exists("WindowsSecurity"):
		return _security_unavailable()
	var security = ClassDB.instantiate("WindowsSecurity")
	if security == null:
		return _security_unavailable()
	return security.unprotect_secret(cipher,scope)
