extends RefCounted
## Pure canonical address rules shared by transport, sessions and storage.

static func normalize(address: String) -> String:
	var value := address.strip_edges()
	if value.is_empty() or value.contains("\\"):
		return ""
	if not value.contains("://"):
		value = "https://" + value
	var expression := RegEx.new()
	expression.compile("(?i)^(https?)://(\\[[0-9a-f:]+\\]|[a-z0-9][a-z0-9.-]*)(?::([0-9]{1,5}))?(/[^?#\\s]*)?$")
	var matched := expression.search(value)
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
