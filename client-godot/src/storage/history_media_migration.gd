extends RefCounted
## Upgrade only the two kind constraints, preserving history, pending messages and dynamics.
const Schema = preload("res://src/storage/history_schema.gd")

static func migrate(access: RefCounted) -> Dictionary:
	return access.transaction(func(): return _apply(access), "media_schema_upgrade")

static func _apply(access: RefCounted) -> Dictionary:
	var prefix := """
ALTER TABLE messages RENAME TO messages_v100;
ALTER TABLE local_messages RENAME TO local_messages_v100;
DROP INDEX messages_server_index;
DROP INDEX local_messages_seq;
"""
	var tables := Schema.CREATE_SCHEMA.split("CREATE TABLE sync_state")[0]
	var suffix := """
INSERT INTO messages SELECT * FROM messages_v100;
INSERT INTO local_messages SELECT * FROM local_messages_v100;
DROP TABLE messages_v100;
DROP TABLE local_messages_v100;
"""
	var result: Dictionary = access.execute_block(prefix + tables + suffix)
	if not result.ok: return result
	return access.execute(Schema.SET_VERSION % Schema.VERSION)
