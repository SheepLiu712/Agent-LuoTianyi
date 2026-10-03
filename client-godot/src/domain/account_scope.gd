extends RefCounted
const ServerAddress = preload("res://src/domain/server_address.gd")

static func key(server: String, username: String) -> String:
	var address := ServerAddress.normalize(server)
	if address.is_empty() or username.is_empty(): return ""
	return JSON.stringify([address, username]).sha256_text()
