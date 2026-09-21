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
	if host.begins_with("["):
		if not host.substr(1, host.length() - 2).is_valid_ip_address():
			return ""
	else:
		for part in host.split("."):
			if part.is_empty() or part.begins_with("-") or part.ends_with("-") or part.length() > 63:
				return ""
	var port := matched.get_string(3)
	if not port.is_empty():
		if int(port) < 1 or int(port) > 65535:
			return ""
		port = str(int(port))
		if (scheme == "https" and port == "443") or (scheme == "http" and port == "80"):
			port = ""
	var path := matched.get_string(4)
	while path.ends_with("/"):
		path = path.left(-1)
	return scheme + "://" + host + (":" + port if not port.is_empty() else "") + path
