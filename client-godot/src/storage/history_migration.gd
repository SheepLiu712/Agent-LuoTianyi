extends RefCounted
## 草稿库（v1/v2）到 v3 的重建式迁移。
## 策略是「改名旧表 → 建 v3 → 复制可映射列 → 丢旧表 → 外键自检 → 写版本」，
## 而不是逐行改主键：后者会在唯一索引上制造暂时冲突。
## 复制只接受可安全映射的列，其余用明确默认值，绝不删除用户数据；
## 备份在连接关闭状态完成，由调用方负责关闭与重开。

const Schema = preload("res://src/storage/history_schema.gd")
const Installer = preload("res://src/storage/history_schema_installer.gd")

const LEGACY_PREFIX := "legacy_"

## 目标列 → 旧库可能使用的列名（按优先级）。
const ALIASES := {
	"message_id": ["message_id", "uuid"],
	"source": ["source"],
	"message_type": ["message_type", "type"],
	"content": ["content"],
	"timestamp_json": ["timestamp_json"],
	"delivery_state": ["delivery_state"],
	"error_code": ["error_code"],
	"stream_complete": ["stream_complete"],
	"content_origin": ["content_origin"],
	"id_source": ["id_source"],
	"origin": ["origin"],
	"timeline_order": ["timeline_order"],
	"created_at_ms": ["created_at_ms"],
	"updated_at_ms": ["updated_at_ms"],
}

## 旧库没有该列时的表达式：保持可读且不丢行。
const DEFAULTS := {
	"id_source": "'server'",
	"origin": "'history'",
	"source": "'user'",
	"message_type": "'text'",
	"content": "''",
	"timestamp_json": "'null'",
	"delivery_state": "'received'",
	"error_code": "''",
	"stream_complete": "1",
	"content_origin": "'history'",
	"timeline_order": "ROW_NUMBER() OVER(ORDER BY rowid) * 1048576",
	"created_at_ms": "0",
	"updated_at_ms": "0",
	"message_id": "lower(hex(randomblob(16)))",
}


## 关闭连接后的一致性备份；写失败不覆盖已有备份的语义由调用方决定。
static func backup(source_path: String, version: int) -> Dictionary:
	var source := FileAccess.open(source_path, FileAccess.READ)
	if source == null:
		return _failure("CACHE_BACKUP_FAILED")
	var bytes := source.get_buffer(source.get_length())
	source.close()
	var target_path := "%s.v%d.bak" % [source_path, version]
	var target := FileAccess.open(target_path, FileAccess.WRITE)
	if target == null:
		return _failure("CACHE_BACKUP_FAILED")
	target.store_buffer(bytes)
	target.close()
	if FileAccess.get_file_as_bytes(target_path).size() != bytes.size():
		return _failure("CACHE_BACKUP_FAILED")
	return {"ok": true, "code": "OK", "data": {"path": target_path}}


static func migrate(access: RefCounted, scope: String) -> Dictionary:
	return access.transaction(_in_transaction.bind(access, scope))


static func _in_transaction(access: RefCounted, scope: String) -> Dictionary:
	var renamed := _rename_legacy(access)
	if not renamed.ok:
		return renamed
	var created: Dictionary = access.execute_block(Schema.CREATE_V3)
	if not created.ok:
		return created
	var copied := _copy_messages(access)
	if not copied.ok:
		return copied
	var dropped := _drop_legacy(access)
	if not dropped.ok:
		return dropped
	var checked := _check_foreign_keys(access)
	if not checked.ok:
		return checked
	var installed := Installer.install_scope(access, scope)
	if not installed.ok:
		return installed
	return Installer.set_version(access)


static func _rename_legacy(access: RefCounted) -> Dictionary:
	for table in Schema.REQUIRED_TABLES:
		if not access.has_table(table):
			continue
		var renamed: Dictionary = access.execute("ALTER TABLE %s RENAME TO %s%s" % [table, LEGACY_PREFIX, table])
		if not renamed.ok:
			return renamed
	return _ok()


static func _drop_legacy(access: RefCounted) -> Dictionary:
	for table in Schema.REQUIRED_TABLES:
		var dropped: Dictionary = access.execute("DROP TABLE IF EXISTS %s%s" % [LEGACY_PREFIX, table])
		if not dropped.ok:
			return dropped
	return _ok()


static func _copy_messages(access: RefCounted) -> Dictionary:
	var legacy := LEGACY_PREFIX + "messages"
	if not access.has_table(legacy):
		return _ok()
	var available := _availability(access.column_names(legacy))
	var mapping := _mapping(available)
	var sql := "INSERT INTO messages(%s) SELECT %s FROM %s" % [
		Schema.column_list(mapping.keys()), Schema.column_list(mapping.values()), legacy,
	]
	return access.execute(sql)


static func _availability(columns: Array) -> Dictionary:
	var available := {}
	for name in columns:
		available[str(name)] = true
	return available


static func _mapping(available: Dictionary) -> Dictionary:
	var mapping := {}
	for target in Schema.REQUIRED_COLUMNS.messages:
		mapping[target] = _expression_for(str(target), available)
	return mapping


static func _expression_for(target: String, available: Dictionary) -> String:
	for candidate in ALIASES.get(target, []):
		if available.has(candidate):
			return candidate
	return str(DEFAULTS.get(target, "NULL"))


static func _check_foreign_keys(access: RefCounted) -> Dictionary:
	if access.foreign_key_violations().is_empty():
		return _ok()
	return _failure("CACHE_INTEGRITY_FAILED")


static func _ok() -> Dictionary:
	return {"ok": true, "code": "OK", "data": {}}


static func _failure(code: String) -> Dictionary:
	return {"ok": false, "code": code, "data": {}}
