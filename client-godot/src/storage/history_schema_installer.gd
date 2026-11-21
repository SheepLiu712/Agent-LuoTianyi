extends RefCounted
## 新库初始化：只负责「把空库变成可用的 version 100 库」。
## 建表、绑定 scope、写版本必须同事务；user_version 最后写，
## 避免建表中途崩溃留下「版本已标记、结构却不完整」的坏库。

const Schema = preload("res://src/storage/history_schema.gd")


## 建 6 张表，并写入绑定 scope 的聊天/动态单行状态。
static func install(access: RefCounted, scope: String) -> Dictionary:
	var created: Dictionary = access.execute_block(Schema.CREATE_SCHEMA)
	if not created.ok:
		return created
	var chat: Dictionary = access.execute(Schema.INSTALL_CHAT_STATE, [scope])
	if not chat.ok:
		return chat
	var dynamics: Dictionary = access.execute(Schema.INSTALL_DYNAMICS_STATE, [scope])
	if not dynamics.ok:
		return dynamics
	return set_version(access)


## user_version 是最后一道写入：结构没建全之前不宣称已完成迁移。
static func set_version(access: RefCounted) -> Dictionary:
	return access.execute(Schema.SET_VERSION % Schema.VERSION)


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}
