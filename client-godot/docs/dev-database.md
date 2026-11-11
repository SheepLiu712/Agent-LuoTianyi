# 开发者查看客户端 SQLite 数据库

Godot 客户端的历史库是标准、明文的 SQLite 文件，可以直接用 VS Code 的 SQLite 插件只读查看。客户端运行时工作线程持有一条连接，WAL 模式下第三方只读查看不会修改数据；正常退出会执行 `wal_checkpoint(TRUNCATE)`。

## 路径

```text
%APPDATA%\AgentLuo-Godot\history\<scope>\history.db
```

- `user://` 由 `project.godot` 的 `config/use_custom_user_dir` 指向 `%APPDATA%\AgentLuo-Godot`。
- 每个“服务器 + 账号”一个独立目录。
- `scope` 是 `sha256(JSON.stringify([normalized_server, username]))` 的 64 位小写十六进制。
- 迁移旧库后可能同时存在 `history.db.v1.bak`、`history.db.v2.bak`，它们不是当前库。

查找当前账号的库：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File client-godot/scripts/database_path.ps1
# 直接交给 VS Code：
powershell -NoProfile -ExecutionPolicy Bypass -File client-godot/scripts/database_path.ps1 -Open
```

## VS Code 插件

- `qwtel.sqlite-viewer`：打开 `history.db` 即可浏览表、单元格和图片字段；只读，适合快速看导入结果。
- `alexcvzz.vscode-sqlite`：可执行 SQL，适合统计和联表；需要把 `history.db`、`history.db-wal`、`history.db-shm` 一起复制到同一目录后再打开。

步骤：`File > Open Folder…` 选择 `%APPDATA%\AgentLuo-Godot\history`，展开账号 scope 目录，点击 `history.db`。

## 表与导入进度

| 表 | 用途 |
| --- | --- |
| `messages` | 消息正文、角色、时间戳、状态与稳定 UUID。 |
| `history_positions` | 服务端历史序号到本地消息的映射。 |
| `cached_ranges` | 已加载的历史窗口。 |
| `sync_state` | 同步纪元、序号修订、下一页位置、是否追平。 |
| `send_attempts` | 发送尝试与重试记录。 |
| `sync_epochs` | 历史同步纪元。 |
| `history_segments` / `segment_members` | 分段历史缓存。 |
| `message_media` | 媒体关联表；当前媒体导入不写此表。 |

常用查询：

```sql
select count(*) from messages;
select * from sync_state;
select * from cached_ranges order by start_index;
select id, role, timestamp, substr(content, 1, 40) from messages order by timestamp desc limit 20;
```

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
