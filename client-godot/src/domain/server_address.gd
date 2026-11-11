extends RefCounted
## 传输、会话与存储共用的纯地址规范化规则。

static var _pattern: RegEx

static func normalize(address: String) -> String:
	var value := address.strip_edges()
	if value.is_empty() or value.contains("\\"):
		return ""
	if not value.contains("://"):
		value = "https://" + value
	if _pattern == null:
		_pattern = RegEx.create_from_string("(?i)^(https?)://(\\[[0-9a-f:]+\\]|[a-z0-9][a-z0-9.-]*)(?::([0-9]{1,5}))?(/[^?#\\s]*)?$")
	var matched := _pattern.search(value)
	if matched == null:
		return ""
	var scheme := matched.get_string(1).to_lower()
	var host := matched.get_string(2).to_lower()
	if not _valid_host(host):
		return ""
	var port := matched.get_string(3)
	if not _valid_port(port):
		return ""
	port = _canonical_port(port, scheme)
	var path := matched.get_string(4)
	while path.ends_with("/"):
		path = path.left(-1)
	return scheme + "://" + host + (":" + port if not port.is_empty() else "") + path


## 发布版只允许 TLS；localhost/127.0.0.0/8/[::1] 保留明文，供本地夹具与自测。
static func is_secure(address: String) -> bool:
	var value := normalize(address)
	return value.begins_with("https://")


static func is_loopback(address: String) -> bool:
	var host := canonical_host(address).trim_prefix("[").trim_suffix("]")
	if host == "localhost" or host == "::1":
		return true
	if not host.begins_with("127."):
		return false
	var parts := host.split(".")
	if parts.size() != 4:
		return false
	for part in parts:
		if not part.is_valid_int() or int(part) < 0 or int(part) > 255:
			return false
	return true


static func allows_insecure(address: String) -> bool:
	var value := normalize(address)
	return not value.is_empty() and (value.begins_with("https://") or is_loopback(value))


static func canonical_host(address: String) -> String:
	var value := normalize(address)
	if value.is_empty():
		return ""
	if _pattern == null:
		_pattern = RegEx.create_from_string("(?i)^(https?)://(\\[[0-9a-f:]+\\]|[a-z0-9][a-z0-9.-]*)(?::([0-9]{1,5}))?(/[^?#\\s]*)?$")
	var matched := _pattern.search(value)
	return "" if matched == null else matched.get_string(2).to_lower()

static func _valid_host(host: String) -> bool:
	if host.begins_with("["):
		return host.substr(1, host.length() - 2).is_valid_ip_address()
	return _valid_dns_labels(host) and _valid_numeric_host(host)

static func _valid_dns_labels(host: String) -> bool:
	for part in host.split("."):
		if part.is_empty() or part.begins_with("-") or part.ends_with("-") or part.length() > 63:
			return false
	return true

static func _valid_numeric_host(host: String) -> bool:
	if not host.contains("."):
		return true
	for part in host.split("."):
		if not part.is_valid_int():
			return true
	return host.is_valid_ip_address()

static func _valid_port(port: String) -> bool:
	return port.is_empty() or (int(port) >= 1 and int(port) <= 65535)

static func _canonical_port(port: String, scheme: String) -> String:
	if port.is_empty():
		return ""
	var canonical := str(int(port))
	if (scheme == "https" and canonical == "443") or (scheme == "http" and canonical == "80"):
		return ""
	return canonical
