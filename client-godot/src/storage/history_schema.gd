extends RefCounted
## 单一职责：集中持有聊天与动态库的 SQL 文本、结构契约与版本标识。
## 这里只有常量与纯函数：不建立连接、不读写文件、不依赖其它模块。
##
## 本地库是「可重建缓存 + 在途发送队列」：没有旧版本迁移，
## 文件头不是 (application_id, 100) 时由仓储层整库物理删除后重建。

## 0x4C544859 == "LTHY"
const APPLICATION_ID := 1280591961
const VERSION := 100

## 顺序有硬约束：auto_vacuum 必须最先执行，早于任何会初始化数据库头的 PRAGMA。
const PRAGMAS := [
	"PRAGMA auto_vacuum=INCREMENTAL",
	"PRAGMA application_id=1280591961",
	"PRAGMA journal_mode=WAL",
	"PRAGMA synchronous=FULL",
	"PRAGMA busy_timeout=3000",
	"PRAGMA journal_size_limit=16777216",
	"PRAGMA foreign_keys=ON",
]

const CREATE_SCHEMA := """
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  server_index INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','agent','system')),
  kind TEXT NOT NULL CHECK(kind IN ('text','image','sing','cmd')),
  content TEXT NOT NULL DEFAULT '',
  sent_ts_ms INTEGER NOT NULL,
  created_at_ms INTEGER NOT NULL
);
CREATE UNIQUE INDEX messages_server_index ON messages(server_index);

CREATE TABLE local_messages (
  id TEXT PRIMARY KEY,
  local_seq INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','agent','system')),
  kind TEXT NOT NULL CHECK(kind IN ('text','image','sing','cmd')),
  content TEXT NOT NULL DEFAULT '',
  sent_ts_ms INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN
    ('waiting_history','pending','sending','sent','failed','received')),
  error_code TEXT NOT NULL DEFAULT '',
  stream_complete INTEGER NOT NULL DEFAULT 1,
  payload_json TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE UNIQUE INDEX local_messages_seq ON local_messages(local_seq);

CREATE TABLE sync_state (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  scope_key TEXT NOT NULL,
  next_end INTEGER NOT NULL DEFAULT -1,
  baseline_index INTEGER NOT NULL DEFAULT -1,
  revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE dynamic_posts (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  author_type TEXT NOT NULL,
  author_id TEXT NOT NULL DEFAULT '',
  author_name TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  allow_comment INTEGER NOT NULL DEFAULT 0,
  comment_count INTEGER NOT NULL DEFAULT 0,
  comment_synced_count INTEGER NOT NULL DEFAULT 0,
  user_commented INTEGER NOT NULL DEFAULT 0,
  needs_comment_sync INTEGER NOT NULL DEFAULT 0,
  comment_cursor TEXT NOT NULL DEFAULT '',
  comment_has_more INTEGER NOT NULL DEFAULT 0,
  comment_loaded_at_ms INTEGER NOT NULL DEFAULT 0,
  last_activity_at TEXT NOT NULL DEFAULT '',
  last_activity_id TEXT NOT NULL DEFAULT '',
  last_activity_kind TEXT NOT NULL DEFAULT '',
  read_activity_at TEXT NOT NULL DEFAULT '',
  read_activity_id TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  first_seen_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE INDEX dynamic_posts_feed ON dynamic_posts(created_at DESC, id DESC);
CREATE INDEX dynamic_posts_activity ON dynamic_posts(last_activity_at DESC, last_activity_id DESC);
CREATE INDEX dynamic_posts_unread ON dynamic_posts(last_activity_at, last_activity_id)
  WHERE last_activity_at <> '';

CREATE TABLE dynamic_comments (
  id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES dynamic_posts(id) ON DELETE CASCADE,
  parent_comment_id TEXT,
  created_at TEXT NOT NULL,
  author_type TEXT NOT NULL,
  author_id TEXT NOT NULL DEFAULT '',
  author_name TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE INDEX dynamic_comments_post ON dynamic_comments(post_id, created_at, id);
CREATE INDEX dynamic_comments_unread ON dynamic_comments(created_at, id)
  WHERE author_type <> 'user';

CREATE TABLE dynamic_state (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  scope_key TEXT NOT NULL,
  server_read_at TEXT NOT NULL DEFAULT '',
  server_comment_read_at TEXT NOT NULL DEFAULT '',
  posts_cursor TEXT NOT NULL DEFAULT '',
  has_more INTEGER NOT NULL DEFAULT 0,
  refresh_version INTEGER NOT NULL DEFAULT 0,
  last_sync_ms INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 1
);
"""

const SET_VERSION := "PRAGMA user_version=%d"
const READ_VERSION := "PRAGMA user_version"
const READ_APPLICATION_ID := "PRAGMA application_id"
const READ_AUTO_VACUUM := "PRAGMA auto_vacuum"
const READ_JOURNAL_MODE := "PRAGMA journal_mode"
const READ_FOREIGN_KEYS := "PRAGMA foreign_keys"
const FOREIGN_KEY_CHECK := "PRAGMA foreign_key_check"
const WAL_CHECKPOINT := "PRAGMA wal_checkpoint(TRUNCATE)"
const OPTIMIZE := "PRAGMA optimize"
const INCREMENTAL_VACUUM := "PRAGMA incremental_vacuum"

const SCHEMA_TABLES := """
SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name
"""
const TABLE_COLUMNS := "PRAGMA table_info(%s)"
const TABLE_INDEXES := "PRAGMA index_list(%s)"

## 新库初始化：聊天游标与动态全局状态各一行，都绑定当前 scope。
const INSTALL_CHAT_STATE := """
INSERT OR IGNORE INTO sync_state(id,scope_key,next_end,baseline_index,revision)
VALUES(1,?,-1,-1,1)
"""
const INSTALL_DYNAMICS_STATE := """
INSERT OR IGNORE INTO dynamic_state(id,scope_key,server_read_at,server_comment_read_at,posts_cursor,has_more,refresh_version,last_sync_ms,revision)
VALUES(1,?,'','','',0,0,0,1)
"""

## ---------------------------------------------------------------- 聊天读

const READ_SYNC_STATE := "SELECT * FROM sync_state WHERE id=1"
const READ_SCOPE_KEY := "SELECT scope_key FROM sync_state WHERE id=1"
const READ_REVISION := "SELECT revision FROM sync_state WHERE id=1"
const READ_NEXT_END := "SELECT next_end FROM sync_state WHERE id=1"

## 最新窗口：服务端槽位倒序取一页，本地尾部单独按 local_seq 正序全取。
const READ_LATEST_SERVER := """
SELECT * FROM messages
WHERE server_index <= COALESCE((SELECT baseline_index FROM sync_state WHERE id=1), 2147483647)
ORDER BY server_index DESC LIMIT ?
"""
## 本地尾部有界读取：最近 500 条加上所有未完成/失败行，避免长期失败记录拖慢每次上翻。
const READ_ALL_LOCAL := """
SELECT * FROM local_messages
WHERE local_seq IN (SELECT local_seq FROM local_messages ORDER BY local_seq DESC LIMIT 500)
   OR state IN ('pending','waiting_history','sending','failed')
ORDER BY local_seq ASC
"""

const READ_SERVER_BY_ID := "SELECT * FROM messages WHERE id=?"
const READ_LOCAL_BY_ID := "SELECT * FROM local_messages WHERE id=?"

const READ_SERVER_BEFORE := """
SELECT * FROM messages WHERE server_index < ?
ORDER BY server_index DESC LIMIT ?
"""
const READ_LOCAL_BEFORE := """
SELECT * FROM local_messages WHERE local_seq < ?
ORDER BY local_seq DESC LIMIT ?
"""
## 从本地尾部向上翻、页内数量不足时，用服务器历史补足差额。
const READ_SERVER_TAIL := "SELECT * FROM messages ORDER BY server_index DESC LIMIT ?"
const READ_MAX_LOCAL_SEQ := "SELECT MAX(local_seq) AS tail FROM local_messages"

## ---------------------------------------------------------------- 聊天写

## 槽位是缓存位置而不是消息身份：同槽位换 id 或同 id 换槽位都由 REPLACE 自愈。
const INSERT_SERVER := """
INSERT OR REPLACE INTO messages
(id,server_index,role,kind,content,sent_ts_ms,created_at_ms)
VALUES (?,?,?,?,?,?,?)
"""
const INSERT_LOCAL := """
INSERT INTO local_messages
(id,local_seq,role,kind,content,sent_ts_ms,state,error_code,stream_complete,
 payload_json,attempts,created_at_ms,updated_at_ms)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
"""
const UPDATE_LOCAL_FULL := """
UPDATE local_messages SET
 role=?, kind=?, content=?, sent_ts_ms=?, state=?, error_code=?,
 stream_complete=?, payload_json=?, attempts=?, updated_at_ms=?
WHERE id=?
"""
const DELETE_LOCAL := "DELETE FROM local_messages WHERE id=?"

const UPDATE_PROGRESS := """
UPDATE sync_state SET next_end=?, baseline_index=?, revision=revision+1 WHERE id=1
"""
const DELETE_SERVER_AFTER := "DELETE FROM messages WHERE server_index > ?"
const BUMP_REVISION := "UPDATE sync_state SET revision=revision+1 WHERE id=1"

## 本地用户消息对账候选：只有已经交给传输层的记录才允许被历史页认领，
## 还没发出去的 pending / waiting_history 不能因为正文相同而消失。
const READ_LOCAL_USER_CANDIDATES := """
SELECT * FROM local_messages
WHERE role='user' AND state='sent'
ORDER BY sent_ts_ms ASC, local_seq ASC
"""

## 重启恢复：sending 无法确认是否送达，只能显式失败且不自动重发。
const RECOVER_SENDING := """
UPDATE local_messages SET state='failed', error_code='DELIVERY_UNCERTAIN', updated_at_ms=?
WHERE state='sending'
"""
const RECOVER_EXPIRED_WAITING := """
UPDATE local_messages SET state='failed', error_code='SEND_EXPIRED', updated_at_ms=?
WHERE state='waiting_history' AND created_at_ms < ?
"""

## ---------------------------------------------------------------- 动态读

const READ_DYNAMICS_STATE := "SELECT * FROM dynamic_state WHERE id=1"
const READ_POSTS := """
SELECT * FROM dynamic_posts
ORDER BY created_at DESC, id DESC LIMIT ?
"""
const READ_POST := "SELECT * FROM dynamic_posts WHERE id=?"
const READ_COMMENTS := """
SELECT * FROM dynamic_comments WHERE post_id=?
ORDER BY created_at ASC, id ASC LIMIT ?
"""

## 徽标按「未读动态条数」计；一条动态多条新评论仍只算 1。
const UNREAD_POST_COUNT := """
SELECT COUNT(*) AS count FROM dynamic_posts
WHERE last_activity_at <> ''
  AND (
    last_activity_at > read_activity_at
    OR (last_activity_at = read_activity_at AND last_activity_id > read_activity_id)
  )
"""
const LATEST_UNREAD_POST := """
SELECT * FROM dynamic_posts
WHERE last_activity_at <> ''
  AND (
    last_activity_at > read_activity_at
    OR (last_activity_at = read_activity_at AND last_activity_id > read_activity_id)
  )
ORDER BY last_activity_at DESC, last_activity_id DESC
LIMIT 1
"""
const LOCAL_UNREAD_COMMENTS := """
SELECT COUNT(*) AS count FROM dynamic_comments c
WHERE c.author_type <> 'user'
  AND EXISTS (
    SELECT 1 FROM dynamic_posts p
    WHERE p.id = c.post_id
      AND (
        c.created_at > p.read_activity_at
        OR (c.created_at = p.read_activity_at AND c.id > p.read_activity_id)
      )
  )
"""

## ---------------------------------------------------------------- 动态写

## 首次见到一行时按服务端基线初始化活动/已读水位；
## 已存在的行只更新正文与计数，评论游标、水位与本地簿记列全部保留。
const INSERT_POST := """
INSERT INTO dynamic_posts
(id,created_at,author_type,author_id,author_name,content,allow_comment,comment_count,
 comment_synced_count,user_commented,needs_comment_sync,comment_cursor,comment_has_more,
 comment_loaded_at_ms,last_activity_at,last_activity_id,last_activity_kind,
 read_activity_at,read_activity_id,payload_json,first_seen_ms,updated_at_ms)
VALUES (?,?,?,?,?,?,?,?,0,0,?, '',0,0,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET
 created_at=excluded.created_at,
 author_type=excluded.author_type,
 author_id=excluded.author_id,
 author_name=excluded.author_name,
 content=excluded.content,
 allow_comment=excluded.allow_comment,
 comment_count=excluded.comment_count,
 needs_comment_sync=CASE
   WHEN excluded.comment_count > dynamic_posts.comment_synced_count THEN 1
   ELSE dynamic_posts.needs_comment_sync END,
 payload_json=excluded.payload_json,
 updated_at_ms=excluded.updated_at_ms
"""
## 无评论缓存的新动态：计数增长本身就是「有新回复」的信号。
const POST_NEEDS_SYNC := """
UPDATE dynamic_posts SET needs_comment_sync=1
WHERE id=? AND comment_count > comment_synced_count
"""
## 首屏刷新以本页最旧时间为下界：服务端撤下的、比本页更新的缓存都清掉。
## 更早的分页不清理，避免同秒并列把上一页的条目误删。
const DELETE_POSTS_SINCE := """
DELETE FROM dynamic_posts
WHERE created_at >= ? AND id NOT IN (%s)
"""
const EVICT_POSTS := """
DELETE FROM dynamic_posts WHERE id NOT IN (
  SELECT id FROM dynamic_posts ORDER BY created_at DESC, id DESC LIMIT ?
)
"""
const EVICT_OLD_POSTS := "DELETE FROM dynamic_posts WHERE created_at < ?"

const INSERT_COMMENT := """
INSERT INTO dynamic_comments
(id,post_id,parent_comment_id,created_at,author_type,author_id,author_name,content,payload_json,updated_at_ms)
VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET
 parent_comment_id=excluded.parent_comment_id,
 created_at=excluded.created_at,
 author_type=excluded.author_type,
 author_id=excluded.author_id,
 author_name=excluded.author_name,
 content=excluded.content,
 payload_json=excluded.payload_json,
 updated_at_ms=excluded.updated_at_ms
"""
const UPDATE_POST_COMMENT_SYNC := """
UPDATE dynamic_posts
SET comment_cursor=?, comment_has_more=?, comment_loaded_at_ms=?
WHERE id=?
"""
const UPDATE_POST_ACTIVITY := """
UPDATE dynamic_posts
SET last_activity_at=?, last_activity_id=?, last_activity_kind=?,
    read_activity_at=?, read_activity_id=?
WHERE id=?
"""
const MARK_COMMENT_SYNCED := """
UPDATE dynamic_posts SET comment_synced_count=comment_count, needs_comment_sync=0
WHERE id=?
"""
const MARK_USER_COMMENT := """
UPDATE dynamic_posts
SET user_commented=1,
    comment_count=comment_count+1,
    comment_synced_count=comment_synced_count+1
WHERE id=?
"""
const MARK_USER_COMMENT_FLAG := "UPDATE dynamic_posts SET user_commented=1 WHERE id=?"

const MARK_ALL_READ := """
UPDATE dynamic_posts
SET read_activity_at=last_activity_at, read_activity_id=last_activity_id
WHERE last_activity_at <> ''
"""
const MARK_ONE_READ := """
UPDATE dynamic_posts
SET read_activity_at=last_activity_at, read_activity_id=last_activity_id
WHERE id=? AND last_activity_at <> ''
"""
## 服务端基线只单向推进：本地已读水位不回退。
const APPLY_SERVER_READ_BASELINE := """
UPDATE dynamic_posts
SET read_activity_at=last_activity_at, read_activity_id=last_activity_id
WHERE last_activity_at <> '' AND last_activity_at <= ?
"""
const APPLY_SERVER_COMMENT_BASELINE := """
UPDATE dynamic_posts
SET read_activity_at=last_activity_at, read_activity_id=last_activity_id
WHERE last_activity_kind='comment' AND last_activity_at <> '' AND last_activity_at <= ?
"""
const WRITE_DYNAMICS_STATE := """
UPDATE dynamic_state SET
 scope_key=?, server_read_at=?, server_comment_read_at=?, posts_cursor=?,
 has_more=?, refresh_version=?, last_sync_ms=?, revision=revision+1
WHERE id=1
"""

const REQUIRED_TABLES := [
	"messages", "local_messages", "sync_state",
	"dynamic_posts", "dynamic_comments", "dynamic_state",
]

const REQUIRED_COLUMNS := {
	"messages": [
		"id", "server_index", "role", "kind", "content", "sent_ts_ms", "created_at_ms",
	],
	"local_messages": [
		"id", "local_seq", "role", "kind", "content", "sent_ts_ms", "state",
		"error_code", "stream_complete", "payload_json", "attempts",
		"created_at_ms", "updated_at_ms",
	],
	"sync_state": ["id", "scope_key", "next_end", "baseline_index", "revision"],
	"dynamic_posts": [
		"id", "created_at", "author_type", "author_id", "author_name", "content",
		"allow_comment", "comment_count", "comment_synced_count", "user_commented",
		"needs_comment_sync", "comment_cursor", "comment_has_more", "comment_loaded_at_ms",
		"last_activity_at", "last_activity_id", "last_activity_kind",
		"read_activity_at", "read_activity_id", "payload_json",
		"first_seen_ms", "updated_at_ms",
	],
	"dynamic_comments": [
		"id", "post_id", "parent_comment_id", "created_at", "author_type",
		"author_id", "author_name", "content", "payload_json", "updated_at_ms",
	],
	"dynamic_state": [
		"id", "scope_key", "server_read_at", "server_comment_read_at", "posts_cursor",
		"has_more", "refresh_version", "last_sync_ms", "revision",
	],
}

const REQUIRED_INDEXES := {
	"messages": ["messages_server_index"],
	"local_messages": ["local_messages_seq"],
	"dynamic_posts": ["dynamic_posts_feed", "dynamic_posts_activity", "dynamic_posts_unread"],
	"dynamic_comments": ["dynamic_comments_post", "dynamic_comments_unread"],
}


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
