extends RefCounted
## Platform-neutral disk query contract. Unknown quantities are always -1 bytes.

func query_directory(_path: String) -> Dictionary:
	return {"directory_bytes":-1,"total_bytes":-1,"free_bytes":-1,"file_count":-1,"code":"STORAGE_UNAVAILABLE"}
