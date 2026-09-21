extends "res://src/platform/secret_protection.gd"
func protect_secret(plain: PackedByteArray, scope: PackedByteArray) -> Dictionary:
	if not ClassDB.class_exists("WindowsSecurity"): return super.protect_secret(plain,scope)
	return ClassDB.instantiate("WindowsSecurity").protect_secret(plain,scope)
func unprotect_secret(cipher: PackedByteArray, scope: PackedByteArray) -> Dictionary:
	if not ClassDB.class_exists("WindowsSecurity"): return super.unprotect_secret(cipher,scope)
	return ClassDB.instantiate("WindowsSecurity").unprotect_secret(cipher,scope)
