extends RefCounted
## 单一职责：集中持有历史库的 SQL 文本与结构契约。
## 这里只有常量与纯函数：不建立连接、不读写文件、不依赖任何其它模块。
## 结构化校验所需的表/列/索引名单也放在这里，供存储层比对，
## 避免「schema 定义」与「schema 校验」分散在两个文件里漂移。

const VERSION := 3

## 每个 PRAGMA 必须单独执行：SQLite 的返回行语义不适合多语句一次提交。
const PRAGMAS := [
	"PRAGMA foreign_keys=ON",
	"PRAGMA journal_mode=WAL",
	"PRAGMA synchronous=FULL",
	"PRAGMA busy_timeout=3000",
]

const CREATE_V3 := """
CREATE TABLE messages (
 message_id TEXT PRIMARY KEY NOT NULL CHECK(length(message_id)>0),
 id_source TEXT NOT NULL CHECK(id_source IN ('server','local')),
 timeline_order INTEGER NOT NULL,
 origin TEXT NOT NULL,
 source TEXT NOT NULL,
 message_type TEXT NOT NULL,
 content TEXT NOT NULL DEFAULT '',
 timestamp_json TEXT NOT NULL,
 delivery_state TEXT NOT NULL,
 error_code TEXT NOT NULL DEFAULT '',
 stream_complete INTEGER NOT NULL DEFAULT 1 CHECK(stream_complete IN (0,1)),
 content_origin TEXT NOT NULL DEFAULT 'history',
 created_at_ms INTEGER NOT NULL,
 updated_at_ms INTEGER NOT NULL
);
CREATE UNIQUE INDEX messages_timeline ON messages(timeline_order);
CREATE TABLE send_attempts (
 attempt_id TEXT PRIMARY KEY NOT NULL,
 message_id TEXT NOT NULL REFERENCES messages(message_id),
 wire_id TEXT UNIQUE,
 state TEXT NOT NULL,
 ever_sent INTEGER NOT NULL DEFAULT 0 CHECK(ever_sent IN (0,1)),
 error_code TEXT NOT NULL DEFAULT ''
);
CREATE INDEX send_attempts_message ON send_attempts(message_id);
CREATE TABLE message_media (
 message_id TEXT NOT NULL REFERENCES messages(message_id),
 kind TEXT NOT NULL,
 relative_path TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL,
 PRIMARY KEY(message_id,kind)
);
CREATE TABLE sync_epochs (
 epoch INTEGER PRIMARY KEY,
 valid INTEGER NOT NULL CHECK(valid IN (0,1))
);
CREATE TABLE history_positions (
 epoch INTEGER NOT NULL REFERENCES sync_epochs(epoch),
 ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
 message_id TEXT NOT NULL REFERENCES messages(message_id),
 PRIMARY KEY(epoch,ordinal),
 UNIQUE(epoch,message_id)
);
CREATE TABLE cached_ranges (
 epoch INTEGER NOT NULL REFERENCES sync_epochs(epoch),
 start_index INTEGER NOT NULL,
 end_index INTEGER NOT NULL,
 first_message_id TEXT NOT NULL REFERENCES messages(message_id),
 last_message_id TEXT NOT NULL REFERENCES messages(message_id),
 PRIMARY KEY(epoch,start_index),
 CHECK(end_index > start_index)
);
CREATE TABLE history_segments (
 segment_id TEXT PRIMARY KEY NOT NULL,
 epoch INTEGER NOT NULL REFERENCES sync_epochs(epoch),
 state TEXT NOT NULL,
 first_message_id TEXT REFERENCES messages(message_id),
 last_message_id TEXT REFERENCES messages(message_id)
);
CREATE TABLE segment_members (
 segment_id TEXT NOT NULL REFERENCES history_segments(segment_id),
 message_id TEXT NOT NULL REFERENCES messages(message_id),
 member_order INTEGER NOT NULL,
 PRIMARY KEY(segment_id,message_id),
 UNIQUE(segment_id,member_order)
);
CREATE TABLE sync_state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 scope_key TEXT NOT NULL,
 active_epoch INTEGER REFERENCES sync_epochs(epoch),
 order_revision INTEGER NOT NULL DEFAULT 1,
 baseline_message_id TEXT REFERENCES messages(message_id),
 next_end INTEGER NOT NULL DEFAULT -1,
 head_message_id TEXT REFERENCES messages(message_id),
 caught_up INTEGER NOT NULL DEFAULT 0 CHECK(caught_up IN (0,1))
)
"""

## 只用于 version=0 的不完整草稿库：按外键反序清理后整套重建。
const DROP_V3 := """
DROP TABLE IF EXISTS segment_members;
DROP TABLE IF EXISTS history_segments;
DROP TABLE IF EXISTS cached_ranges;
DROP TABLE IF EXISTS history_positions;
DROP TABLE IF EXISTS message_media;
DROP TABLE IF EXISTS send_attempts;
DROP TABLE IF EXISTS sync_state;
DROP TABLE IF EXISTS sync_epochs;
DROP TABLE IF EXISTS messages
"""

const SET_VERSION := "PRAGMA user_version=%d"

## 新库初始化：第一个 epoch 与 scope 绑定的 sync_state 单行。绑定参数为 scope_key。
const INSTALL_SCOPE := """
INSERT INTO sync_epochs(epoch,valid) VALUES(1,1);
INSERT INTO sync_state(singleton,scope_key,active_epoch,order_revision,next_end,caught_up)
VALUES(1,?,1,1,-1,0)
"""

const READ_VERSION := "PRAGMA user_version"
const FOREIGN_KEY_CHECK := "PRAGMA foreign_key_check"
const WAL_CHECKPOINT := "PRAGMA wal_checkpoint(TRUNCATE)"

const SCHEMA_TABLES := """
SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name
"""
const TABLE_COLUMNS := "PRAGMA table_info(%s)"
const TABLE_INDEXES := "PRAGMA index_list(%s)"

const READ_SYNC_STATE := "SELECT * FROM sync_state WHERE singleton=1"
const READ_ORDER_REVISION := "SELECT order_revision FROM sync_state WHERE singleton=1"
const READ_SCOPE_KEY := "SELECT scope_key FROM sync_state WHERE singleton=1"
## 空表返回 NULL；0 是合法位置，不能与「没有行」混为一谈。
const READ_MAX_ORDER := "SELECT MAX(timeline_order) AS tail FROM messages"
const READ_MIN_ORDER := "SELECT MIN(timeline_order) AS head FROM messages"

## 对账落位依据：库里出现过服务器来源的行，才说明服务器时间线已经在库内延续。
const READ_HAS_SERVER := "SELECT 1 AS present FROM messages WHERE id_source='server' LIMIT 1"

## 精确命中索引，不做全表排序：timeline_order 唯一，无需第二排序键。
## superseded 只表示「本地副本已被服务器历史确认」，不再进入用户时间线。
const READ_LATEST := "SELECT * FROM messages WHERE delivery_state<>'superseded' ORDER BY timeline_order DESC LIMIT ?"
const READ_ORDER_OF := "SELECT timeline_order FROM messages WHERE message_id=?"
const READ_BEFORE := """
SELECT * FROM messages WHERE delivery_state<>'superseded' AND timeline_order < ?
ORDER BY timeline_order DESC LIMIT ?
"""

## 页内已知锚点：除顺序外还取身份列，历史页不得覆盖来源/角色/类型不同
## 的同 UUID 记录（尤其本地消息）。只取这些 UUID 的顺序，用来把整页切成若干未知块。
const READ_KNOWN := """
SELECT message_id,timeline_order,id_source,source,message_type FROM messages WHERE message_id IN (%s)
"""

## 找真实邻居：缺一侧锚点时补边界；两侧锚点都在时收窄可分配区间，
## 避免均分出来的位置撞到本页没带上的旧行。
const READ_NEIGHBOR_BEFORE := """
SELECT message_id,timeline_order FROM messages
WHERE timeline_order < ? ORDER BY timeline_order DESC LIMIT 1
"""
const READ_NEIGHBOR_AFTER := """
SELECT message_id,timeline_order FROM messages
WHERE timeline_order > ? ORDER BY timeline_order ASC LIMIT 1
"""

## 保存历史页：位置、范围、段与同步进度都必须和消息同事务提交。
const UPSERT_MESSAGE := """
INSERT INTO messages
(message_id,id_source,timeline_order,origin,source,message_type,content,timestamp_json,
 delivery_state,error_code,stream_complete,content_origin,created_at_ms,updated_at_ms)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(message_id) DO UPDATE SET
content=excluded.content,
timestamp_json=excluded.timestamp_json,
delivery_state=excluded.delivery_state,
error_code=excluded.error_code,
stream_complete=excluded.stream_complete,
content_origin=excluded.content_origin,
updated_at_ms=excluded.updated_at_ms
WHERE messages.id_source=excluded.id_source
 AND messages.source=excluded.source
 AND messages.message_type=excluded.message_type
"""

const UPDATE_MESSAGE_CONTENT := """
UPDATE messages SET content=?,timestamp_json=?,stream_complete=?,content_origin=?,updated_at_ms=?
WHERE message_id=?
"""

const UPDATE_DELIVERY := """
UPDATE messages SET delivery_state=?,error_code=?,updated_at_ms=? WHERE message_id=?
"""

## 位置是「观察记录」：同一条消息在一个 epoch 只记一次，
## 冲突时放弃写入而不是让整页失败——消息本身才是必须落库的事实。
const UPSERT_POSITION := """
INSERT INTO history_positions(epoch,ordinal,message_id) VALUES (?,?,?)
ON CONFLICT DO NOTHING
"""

const UPSERT_RANGE := """
INSERT INTO cached_ranges(epoch,start_index,end_index,first_message_id,last_message_id)
VALUES (?,?,?,?,?)
ON CONFLICT(epoch,start_index) DO UPDATE SET
end_index=excluded.end_index,
first_message_id=excluded.first_message_id,
last_message_id=excluded.last_message_id
"""

const UPDATE_SYNC_PROGRESS := """
UPDATE sync_state SET next_end=?,baseline_message_id=?,head_message_id=?,caught_up=?
WHERE singleton=1
"""

const UPDATE_NEXT_END := """
UPDATE sync_state SET next_end=?,caught_up=? WHERE singleton=1
"""

const READ_MESSAGE := "SELECT * FROM messages WHERE message_id=?"

const BUMP_ORDER_REVISION := """
UPDATE sync_state SET order_revision=order_revision+1 WHERE singleton=1
"""

const INSERT_ATTEMPT := """
INSERT INTO send_attempts(attempt_id,message_id,wire_id,state,ever_sent,error_code)
VALUES (?,?,?,?,?,?)
ON CONFLICT(attempt_id) DO UPDATE SET
wire_id=excluded.wire_id,
state=excluded.state,
ever_sent=MAX(send_attempts.ever_sent,excluded.ever_sent),
error_code=excluded.error_code
"""

const UPDATE_ATTEMPT_BY_WIRE := """
UPDATE send_attempts SET state=?,error_code=?,ever_sent=MAX(ever_sent,?) WHERE wire_id=?
"""

const UPDATE_ATTEMPT_BY_MESSAGE := """
UPDATE send_attempts SET state=?,error_code=?,ever_sent=MAX(ever_sent,?)
WHERE message_id=?
"""

## 重启后只影响展示，不恢复 outbox：
## 曾进入过发送流程且仍处于在途的记录显示「结果不确定」。
const RECOVER_UNCERTAIN := """
UPDATE messages
SET delivery_state='uncertain',error_code='DELIVERY_UNCERTAIN'
WHERE message_id IN (
	SELECT message_id FROM send_attempts
	WHERE ever_sent=1 AND state IN ('queued','sending')
)
AND delivery_state NOT IN ('superseded')
"""

## 启动/历史页落库后的本地副本对账：
## 只匹配「同正文、同角色、同类型、时间相邻」且候选唯一的文本消息。
const RECONCILE_LOCAL_UNCERTAIN := """
SELECT message_id,content,message_type,timestamp_json FROM messages
WHERE id_source='local' AND delivery_state='uncertain'
AND message_type='text' AND content<>''
ORDER BY timeline_order
"""

const RECONCILE_SERVER_CANDIDATES := """
SELECT message_id,timestamp_json FROM messages
WHERE id_source='server' AND source='user' AND message_type=?
AND content=? AND message_id<>?
ORDER BY timeline_order
"""

const MARK_SUPERSEDED := """
UPDATE messages
SET delivery_state='superseded',error_code='SERVER_COPY_MATCHED',updated_at_ms=?
WHERE message_id=? AND delivery_state='uncertain'
"""

const MARK_ATTEMPT_SUPERSEDED := """
UPDATE send_attempts SET state='superseded',error_code='SERVER_COPY_MATCHED'
WHERE message_id=?
"""

## 从未真正发出的排队记录退回「未发送」。
const RECOVER_UNSENT := """
UPDATE messages
SET delivery_state='unsent',error_code=''
WHERE delivery_state IN ('queued','waiting_history')
AND NOT EXISTS (
	SELECT 1 FROM send_attempts
	WHERE send_attempts.message_id=messages.message_id AND ever_sent=1
)
"""

## 重编号：只改位置数值，不改相对顺序，禁止用负数充当临时命名空间。
const RENUMBER := """
CREATE TEMP TABLE IF NOT EXISTS order_rebuild(
	message_id TEXT PRIMARY KEY,
	new_order INTEGER NOT NULL
);
DELETE FROM order_rebuild;
INSERT INTO order_rebuild(message_id,new_order)
SELECT message_id,ROW_NUMBER() OVER(ORDER BY timeline_order)*1048576 FROM messages;
DROP INDEX IF EXISTS messages_timeline;
UPDATE messages SET timeline_order=(
	SELECT new_order FROM order_rebuild WHERE order_rebuild.message_id=messages.message_id
);
CREATE UNIQUE INDEX messages_timeline ON messages(timeline_order);
DROP TABLE order_rebuild
"""

const REQUIRED_TABLES := [
	"messages", "send_attempts", "message_media", "sync_epochs",
	"history_positions", "cached_ranges", "history_segments",
	"segment_members", "sync_state",
]

const REQUIRED_COLUMNS := {
	"messages": [
		"message_id", "id_source", "timeline_order", "origin", "source",
		"message_type", "content", "timestamp_json", "delivery_state",
		"error_code", "stream_complete", "content_origin",
		"created_at_ms", "updated_at_ms",
	],
	"send_attempts": ["attempt_id", "message_id", "wire_id", "state", "ever_sent", "error_code"],
	"message_media": ["message_id", "kind", "relative_path", "state"],
	"sync_epochs": ["epoch", "valid"],
	"history_positions": ["epoch", "ordinal", "message_id"],
	"cached_ranges": [
		"epoch", "start_index", "end_index", "first_message_id", "last_message_id",
	],
	"history_segments": ["segment_id", "epoch", "state", "first_message_id", "last_message_id"],
	"segment_members": ["segment_id", "message_id", "member_order"],
	"sync_state": [
		"singleton", "scope_key", "active_epoch", "order_revision",
		"baseline_message_id", "next_end", "head_message_id", "caught_up",
	],
}

## 重编号与分页都依赖的唯一索引必须存在。
const REQUIRED_UNIQUE_INDEX := "messages_timeline"


## 把多语句块拆成可逐条执行的语句。
## 只按分号拆分，块内不放含分号的字面量，避免误切。
static func statements(block: String) -> Array[String]:
	var result: Array[String] = []
	for piece in block.split(";"):
		var sql := piece.strip_edges()
		if not sql.is_empty():
			result.append(sql)
	return result


static func placeholders(count: int) -> String:
	return ",".join(repeated("?", count))


static func column_list(names: Array) -> String:
	return ",".join(names)


static func repeated(token: String, count: int) -> Array[String]:
	var items: Array[String] = []
	for _index in range(count):
		items.append(token)
	return items


static func is_supported_version(version: int) -> bool:
	return version == 0 or version == VERSION
