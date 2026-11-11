extends RefCounted
## 新库初始化：只负责「把空库变成可用的 v3 库」。
## 新建与迁移都需要这两步，因此单独收口，避免两处写法漂移
## （尤其 user_version 必须最后写，否则半成品库会被当成已升级）。

const Schema = preload("res://src/storage/history_schema.gd")


## 建立第一个 epoch 与绑定 scope 的 sync_state 单行。
static func install_scope(access: RefCounted, scope: String) -> Dictionary:
	var statements := Schema.statements(Schema.INSTALL_SCOPE)
	if statements.size() != 2:
		return _failure("CACHE_METADATA_INVALID")
	var epoch: Dictionary = access.execute(statements[0])
	if not epoch.ok:
		return epoch
	return access.execute(statements[1], [scope])


## user_version 是最后一道写入：结构没建全之前不宣称已完成迁移。
static func set_version(access: RefCounted) -> Dictionary:
	return access.execute(Schema.SET_VERSION % Schema.VERSION)


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}
