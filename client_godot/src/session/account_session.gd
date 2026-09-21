extends Node
signal changed(state: Dictionary)
const Api = preload("res://src/network/account_api.gd")
const StorageService = preload("res://src/storage/storage_service.gd")
const DEFAULT_SERVER := "https://www-api.u3493359.nyat.app:11664"
var _api: Node
var _storage: StorageService
var _profile := {"version":2,"server":DEFAULT_SERVER,"username":"","accounts":[]}
var _session: Dictionary = {}
var _busy := false
var _generation := 0
var _storage_error := false
var _storage_ready := true

func _init(api: Node, storage: StorageService) -> void:
	_api = api
	_storage = storage
	add_child(api)
	_load_profile()

func _load_profile() -> void:
	var loaded := _storage.read_login_profile()
	if not loaded.ok:
		_storage_error = true
		_storage_ready = false
		return
	var data: Dictionary = loaded.data
	if data.is_empty(): return
	if not data.get("server") is String or not data.get("username") is String:
		_storage_error = true
		_storage_ready = false
		return
	var server := Api.normalize_server(data.server)
	if not data.has("version") and data.get("remember") is bool:
		var migrated := {"version":2,"server":DEFAULT_SERVER if server.is_empty() else server,"username":data.username,"accounts":[]}
		if not data.username.is_empty():
			var remember: bool = data.remember and not server.is_empty()
			migrated.accounts.append({"server":migrated.server,"username":data.username,"remember":remember,"auto_login":remember,"last_used":0})
		_profile = migrated
		_storage_error = _storage.write_login_profile(migrated) != OK
		_storage_ready = not _storage_error
		return
	if data.get("version") != 2 or server.is_empty() or not data.get("accounts") is Array:
		_storage_error = true
		_storage_ready = false
		return
	var accounts: Array = []
	var keys: Dictionary = {}
	for entry in data.accounts:
		if not entry is Dictionary or not entry.get("server") is String or not entry.get("username") is String or not entry.get("remember") is bool or not entry.get("auto_login") is bool or not (entry.get("last_used") is int or entry.get("last_used") is float):
			_storage_ready = false
			break
		var address := Api.normalize_server(entry.server)
		var key := JSON.stringify([address,entry.username])
		if address.is_empty() or entry.username.is_empty() or keys.has(key) or not is_finite(float(entry.last_used)):
			_storage_ready = false
			break
		keys[key] = true
		accounts.append({"server":address,"username":entry.username,"remember":entry.remember,"auto_login":entry.auto_login and entry.remember,"last_used":entry.last_used})
	if not _storage_ready:
		_storage_error = true
		return
	_profile = {"version":2,"server":server,"username":data.username,"accounts":accounts}

func get_login_defaults() -> Dictionary:
	var entry := _entry(_profile.server, _profile.username)
	return {"server":_profile.server,"username":_profile.username,"remember":entry.get("remember",false),"auto_login":entry.get("auto_login",false),"storage_error":_storage_error}

func get_history(server: String = "") -> Array:
	var address: String = _profile.server if server.is_empty() else Api.normalize_server(server)
	var entries: Array = _profile.accounts.filter(func(entry): return entry.server == address).duplicate(true)
	entries.sort_custom(func(a,b): return float(a.last_used) > float(b.last_used))
	return entries

func select_account(username: String) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	if _entry(_profile.server, username).is_empty(): return _result(false, "INVALID_INPUT")
	var profile := _profile.duplicate(true)
	profile.username = username
	var result := _persist(profile)
	_emit("ACCOUNT_SELECTED", result != OK)
	return _result(result == OK, "ACCOUNT_SELECTED" if result == OK else "STORAGE_ERROR", result != OK)

func set_login_options(username: String, remember: bool, auto_login: bool) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	var profile := _profile.duplicate(true)
	var index := _index(profile.accounts, profile.server, username)
	if index < 0: return _result(false, "INVALID_INPUT")
	remember = remember or auto_login
	if not remember and _storage.forget_login_token(profile.server, username) != OK:
		_emit("STORAGE_ERROR", true)
		return _result(false, "STORAGE_ERROR", true)
	profile.accounts[index].remember = remember
	profile.accounts[index].auto_login = auto_login and remember
	var result := _persist(profile)
	_emit("OPTIONS_CHANGED", result != OK)
	return _result(result == OK, "OPTIONS_CHANGED" if result == OK else "STORAGE_ERROR", result != OK)

func remove_account(username: String) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	var profile := _profile.duplicate(true)
	var index := _index(profile.accounts, profile.server, username)
	if index < 0: return _result(false, "INVALID_INPUT")
	if _storage.forget_login_token(profile.server, username) != OK:
		_emit("STORAGE_ERROR", true)
		return _result(false, "STORAGE_ERROR", true)
	profile.accounts.remove_at(index)
	if profile.username == username: profile.username = ""
	var result := _persist(profile)
	_emit("ACCOUNT_REMOVED", result != OK)
	return _result(result == OK, "ACCOUNT_REMOVED" if result == OK else "STORAGE_ERROR", result != OK)

func set_server(address: String) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	_busy = true
	var generation := _generation
	_emit("CHECKING_SERVER")
	var response: Dictionary = await _api.probe_server(address)
	_busy = false
	response.storage_error = false
	if generation != _generation: response = _result(false, "CANCELLED")
	if response.ok:
		var profile := _profile.duplicate(true)
		profile.server = Api.normalize_server(address)
		var history := get_history(profile.server)
		profile.username = "" if history.is_empty() else history[0].username
		if _persist(profile) != OK: response = _result(false, "STORAGE_ERROR", true)
		else: response.code = "SERVER_CHANGED"
	_emit(response.code, response.storage_error)
	return response

func perform(operation: String, server: String, fields: Dictionary, remember: bool = false, auto_login: bool = false) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	if not _session.is_empty(): logout()
	remember = remember or auto_login
	var payload := fields.duplicate(true)
	if operation == "login": payload.request_token = remember
	_busy = true
	var generation := _generation
	_emit("PENDING")
	var response: Dictionary = await _api.request(operation, server, payload)
	_busy = false
	response.storage_error = false
	if generation != _generation: response = _result(false, "CANCELLED")
	if response.ok:
		var address := Api.normalize_server(server)
		var username: String = fields.get("username", fields.get("new_username", ""))
		var profile := _profile.duplicate(true)
		profile.server = address
		profile.username = username
		if operation in ["login", "auto_login"]:
			_session = response.data.duplicate(true)
			_session.server = address
			_session.username = username
			var stored := ERR_UNAVAILABLE
			if _storage_ready:
				stored = _storage.save_login_token(address, username, _session.login_token) if remember else _storage.forget_login_token(address, username)
			response.storage_error = stored != OK
			var index := _index(profile.accounts, address, username)
			if index >= 0: profile.accounts.remove_at(index)
			profile.accounts.push_front({"server":address,"username":username,"remember":remember and stored == OK,"auto_login":auto_login and stored == OK,"last_used":Time.get_unix_time_from_system()})
		if _persist(profile) != OK: response.storage_error = true
		if response.storage_error and operation in ["login", "auto_login"]:
			_storage.forget_login_token(address, username)
			_disable_memory(address, username)
	elif operation == "auto_login" and response.code == "AUTH_REJECTED":
		response.storage_error = _forget_options(Api.normalize_server(server), str(fields.get("username", ""))) != OK
	_emit(response.code, response.storage_error)
	return response

func resume() -> Dictionary:
	var defaults := get_login_defaults()
	if not defaults.auto_login or not defaults.remember or defaults.username.is_empty():
		if _storage_error: _emit("STORAGE_ERROR", true)
		return _result(false, "NO_SAVED_LOGIN", _storage_error)
	return await login_saved(defaults.username)

func login_saved(username: String) -> Dictionary:
	if _busy: return _result(false, "BUSY")
	var entry := _entry(_profile.server, username)
	if entry.is_empty() or not entry.remember: return _result(false, "NO_SAVED_LOGIN")
	if not _storage_ready:
		_emit("STORAGE_ERROR", true)
		return _result(false, "STORAGE_ERROR", true)
	var stored := _storage.read_login_token(_profile.server, username)
	if not stored.ok:
		var error := _forget_options(_profile.server, username)
		_emit("CREDENTIAL_UNAVAILABLE", error != OK)
		return _result(false, "CREDENTIAL_UNAVAILABLE", error != OK)
	return await perform("auto_login", _profile.server, {"username":username,"token":stored.token}, true, entry.auto_login)

func cancel() -> void:
	_generation += 1
	_api.cancel()

func logout() -> Error:
	cancel()
	var server: String = _session.get("server", _profile.server)
	var username: String = _session.get("username", _profile.username)
	_session.clear()
	var result := _forget_options(server, username)
	_emit("LOGGED_OUT", result != OK)
	return result

func get_session() -> Dictionary:
	return _session.duplicate(true)

func _forget_options(server: String, username: String) -> Error:
	var removed := _storage.forget_login_token(server, username) if not username.is_empty() else OK
	var profile := _profile.duplicate(true)
	var index := _index(profile.accounts, server, username)
	if index >= 0:
		profile.accounts[index].remember = false
		profile.accounts[index].auto_login = false
	var saved := _persist(profile)
	_disable_memory(server, username)
	return removed if removed != OK else saved

func _disable_memory(server: String, username: String) -> void:
	var index := _index(_profile.accounts, server, username)
	if index >= 0:
		_profile.accounts[index].remember = false
		_profile.accounts[index].auto_login = false

func _entry(server: String, username: String) -> Dictionary:
	var index := _index(_profile.accounts, server, username)
	return {} if index < 0 else _profile.accounts[index]

func _index(accounts: Array, server: String, username: String) -> int:
	for index in accounts.size():
		if accounts[index].server == server and accounts[index].username == username: return index
	return -1

func _persist(profile: Dictionary) -> Error:
	if not _storage_ready: return ERR_INVALID_DATA
	var result := _storage.write_login_profile(profile)
	_storage_error = result != OK
	if result == OK: _profile = profile
	return result

func _emit(code: String, storage_error: bool = false) -> void:
	_storage_error = storage_error or not _storage_ready
	changed.emit({"phase":"busy" if _busy else ("signed_in" if not _session.is_empty() else "signed_out"),"code":code,"storage_error":_storage_error})

func _result(ok: bool, code: String, storage_error: bool = false) -> Dictionary:
	return {"ok":ok,"code":code,"storage_error":storage_error}

func _exit_tree() -> void:
	cancel()
