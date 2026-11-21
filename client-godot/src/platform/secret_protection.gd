extends Resource
func protect_secret(_plain: PackedByteArray, _scope: PackedByteArray) -> Dictionary:
	return {"ok":false,"data":PackedByteArray(),"error":"PROTECT_FAILED"}
func unprotect_secret(_cipher: PackedByteArray, _scope: PackedByteArray) -> Dictionary:
	return {"ok":false,"data":PackedByteArray(),"error":"UNPROTECT_FAILED"}
