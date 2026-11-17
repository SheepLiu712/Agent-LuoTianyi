# 开发者查看客户端 SQLite 数据库

Godot 客户端把聊天与动态缓存在同一个标准、明文的 SQLite 文件里，可以直接用 VS Code 的 SQLite 插件只读查看。客户端运行时工作线程持有一条连接；WAL 模式下第三方只读查看不会修改数据，正常退出会执行 `wal_checkpoint(TRUNCATE)`。

## 路径

```text
%APPDATA%\AgentLuo-Godot\history\<scope>\history.db
```

- `user://` 由 `project.godot` 的 `config/use_custom_user_dir` 指向 `%APPDATA%\AgentLuo-Godot`。
- 每个“服务器 + 账号”一个独立目录。
- `scope` 是 `sha256(JSON.stringify([normalized_server, username]))` 的 64 位小写十六进制。
- 聊天与动态共用这个文件，不再为动态单独开库。

查找当前账号的库：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File client-godot/scripts/database_path.ps1
# 直接交给 VS Code：
powershell -NoProfile -ExecutionPolicy Bypass -File client-godot/scripts/database_path.ps1 -Open
```

## 版本与重置

当前 schema 版本为 **100**，文件头 `application_id = 0x4C544859`（“LTHY”）。

- 启动时只读文件头前 100 字节判断 `(application_id, user_version)`，不会打开旧库触发 WAL 回放。
- 不是 `(0x4C544859, 100)` 的库会连同 `-wal`、`-shm` 一起物理删除后重建；测试期不提供旧 schema 迁移。
- 删除受外部句柄占用而失败时返回 `CACHE_RESET_FAILED`，应用不会降级使用旧库。
- 建库 PRAGMA 有顺序约束：`auto_vacuum = INCREMENTAL` 必须最先执行，早于 `application_id`、`journal_mode` 和建表；`user_version = 100` 在全部建表成功后最后写入。

验证：

```sql
PRAGMA application_id;
PRAGMA user_version;
PRAGMA auto_vacuum;   -- 2 = INCREMENTAL
PRAGMA journal_mode;  -- wal
```

## 表清单

| 表 | 用途 |
| --- | --- |
| `messages` | 服务端已确认的历史；`server_index` 是缓存槽位，不是消息身份。 |
| `local_messages` | 尚未并入历史的本地尾部：待发、发送中、已 ACK、实时流式回复。 |
| `sync_state` | 单行聊天游标：`next_end`、`baseline_index`、`revision`。 |
| `dynamic_posts` | 动态正文/计数/评论游标，以及每条动态独立的 `last_activity` / `read_activity` 水位。 |
| `dynamic_comments` | 按 `(created_at, id)` 升序的评论缓存，外键级联到动态。 |
| `dynamic_state` | 单行动态状态：服务端已读基线、feed 游标、`has_more`。 |

`local_messages.state` 只允许：

```text
waiting_history | pending | sending | sent | failed | received
```

重启时：

- `sending` → `failed` + `DELIVERY_UNCERTAIN`，不自动重发；
- `waiting_history` 超过 24 小时 → `failed` + `SEND_EXPIRED`；
- `pending` 保持，等历史 boundary 释放后重新发送；
- `sent` / `received` 保持，等历史页确认后删除本地行。

## 常用查询

```sql
-- 最新一页聊天（UI 会把结果反转成升序，再接上本地尾部）
select * from messages order by server_index desc limit 30;
select * from local_messages order by local_seq asc;

-- 上翻
select * from messages where server_index < ? order by server_index desc limit 30;
select * from local_messages where local_seq < ? order by local_seq desc limit 30;

-- 聊天游标
select next_end, baseline_index, revision from sync_state where id = 1;

-- 动态 feed
select id, created_at, author_type, comment_count, needs_comment_sync
from dynamic_posts order by created_at desc, id desc limit 20;

-- 未读动态（徽标口径）
select count(*) from dynamic_posts
where last_activity_at <> '' and (
  last_activity_at > read_activity_at
  or (last_activity_at = read_activity_at and last_activity_id > read_activity_id)
);

-- 单条动态的活动/已读水位
select id, last_activity_at, last_activity_id, last_activity_kind,
       read_activity_at, read_activity_id, comment_cursor, comment_has_more
from dynamic_posts where id = ?;

-- 已缓存评论
select id, author_type, created_at, content
from dynamic_comments where post_id = ? order by created_at, id;

-- 动态全局状态
select server_read_at, server_comment_read_at, posts_cursor, has_more
from dynamic_state where id = 1;
```

## 动态未读怎么读

- `last_activity` 只记录**非本人**的动态或评论；用户自己发布的内容不点亮未读。
- `read_activity` 在打开详情、单条标已读或全部已读时推进。
- 比较统一使用 `(时间, id)` 复合二元组；同一秒内 `id` 较大者视为更新，与服务端 `created_at DESC, id DESC` 一致。
- 徽标是“未读动态条数”，一条动态新增多条评论仍只算一个点。
- 服务端 `last_read_dynamic_at` / `last_read_comment_at` 只单向推进本地已读水位，不会让圆点重新亮起。
- 从未缓存、也未在已加载页出现过的老动态无法被定位；此时动态入口显示通用“有新的评论”提示。

## 媒体导入看哪里

“从 Python 客户端导入”只复制文件，不写 SQLite：

```text
%APPDATA%\AgentLuo-Godot\audio\<scope>\
%APPDATA%\AgentLuo-Godot\images\<scope>\
```

导入结果记录在 `%APPDATA%\AgentLuo-Godot\logs\*.jsonl`，事件名为 `python_media_import`，包含新增/跳过数量和事务状态。

## 注意

- 应用运行中，最新写入可能还在 `history.db-wal`；只读查看器可能显示稍旧快照。需要完整快照时先退出应用。
- 库内是明文聊天正文和账号哈希，不要提交到仓库、外传或包含在截图里。
- 多开客户端会争用同一个库；查看时避免同时触发写入。
- 旧的 `history.db.v1.bak` / `v2.bak` / `.discarded` 不再生成；启动时会与残留的 `-wal` / `-shm` 一起清理，避免新库配旧日志。
