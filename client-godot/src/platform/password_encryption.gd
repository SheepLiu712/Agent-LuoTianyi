extends Resource
func is_available() -> bool:
	return false
func encrypt_password(_public_key: String, _password: String) -> Dictionary:
	return {"ok":false,"data":PackedByteArray(),"error":"ENCRYPTION_UNAVAILABLE"}
