extends RefCounted
## 平台无关的磁盘查询契约：未知量一律返回 -1 字节。

func query_directory(_path: String) -> Dictionary:
	return {"directory_bytes":-1,"total_bytes":-1,"free_bytes":-1,"file_count":-1,"code":"STORAGE_UNAVAILABLE"}

func read_login_profile() -> Dictionary:
	return {"ok":false,"code":"STORAGE_UNAVAILABLE","data":{}}

func write_login_profile(_data: Dictionary) -> Error:
	return ERR_UNAVAILABLE

func read_login_token(_server: String, _username: String) -> Dictionary:
	return {"ok":false,"code":"STORAGE_UNAVAILABLE","token":""}

func save_login_token(_server: String, _username: String, _token: String) -> Error:
	return ERR_UNAVAILABLE

func forget_login_token(_server: String, _username: String) -> Error:
	return ERR_UNAVAILABLE
