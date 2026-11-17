# 本地存储重构实施记录

本文记录 `local-storage-design.md` 落地时的取舍、遇到的问题与解决方式，供后续维护和复查使用。设计目标、表结构与模块边界以设计文档为准；这里只写实施中需要额外说明的部分。

## 1. 完成的改动

- 聊天库从 9 张表收缩为 `messages` / `local_messages` / `sync_state` 三张表。
- 新增 `dynamic_posts` / `dynamic_comments` / `dynamic_state` 三张动态表，与聊天共用同一连接。
- 建库 PRAGMA 按设计顺序执行，`user_version = 100`、`application_id = 0x4C544859`。
- 启动时只读文件头判断版本；不兼容旧库连同 `-wal`、`-shm` 一起删除后重建，失败返回 `CACHE_RESET_FAILED`。
- 新增 `ScopeSession`，聊天门面与动态门面共享同一条 Worker 连接；同一 scope 的 `ensure_open()` 幂等。
- 聊天写路径改为“本地尾部先提交，提交成功后才发网络帧”；失败状态保留在时间线上，可重试或删除。
- 动态控制器改为缓存优先；未读使用每条动态独立的 `(last_activity, read_activity)` 复合水位。
- 评论增量使用保存的 `comment_cursor`；首页刷新只清理本页最旧时间之后的缓存，更早分页保留。
- 删除 `history_migration.gd`、`timeline_slots.gd`、`history_runs.gd` 及其测试。
- 新增/重写测试：`test_sqlite_database.gd`、`test_dynamics_store.gd`、`test_scope_session.gd`、`test_message_persistence.gd`、`test_send_persistence_order.gd`、`test_history_paging.gd`、`test_message_merge.gd`、`test_dynamics.gd`。
- 补强测试：boundary 在 `save_local` 在途时不得越过提交、保存失败不得发帧、重试/删除失败不得改 UI、同秒水位复合比较、基线前动态活动记录、旧 sidecar/备份清理、状态单行自愈。
- `close_scope` 与其余命令一样校验作用域；关闭连接失败会沿 `flush` / 打开流程返回，不再被吞掉。
- 更新 `docs/dev-database.md`。

## 2. 与设计文字不完全一致的地方

### 2.1 `baseline_index` 的“本次写入”和“本次接合”分开

设计 5.5.1 要求首屏页把 `baseline_index` 更新为本页最新槽位；5.3 又要求追平过程用 `start_index <= baseline_index` 判断是否接合。如果两件事用同一个值，第二次登录时首屏一写入就把 baseline 推到最新，追平条件永远成立，缺口不会被补齐。

实现方式：

- 数据库中的 `baseline_index` 始终记录“本次首屏页的最新槽位”，供下一次登录使用。
- `HistorySync` 在打开库时先记住上一次的 baseline（`_join_target`），首屏保存后仍用这个旧值判断是否接合；首次登录旧值为 `-1`，视为已接合。

这样既保留了设计要求的持久化字段，又让“追平到上次边界”实际生效。

### 2.2 用户消息启发式确认只认已交给传输层的记录

设计按 `kind + content + 600 秒` 贪心配对。若把 `pending` / `waiting_history` 也纳入候选，用户刚输入一条与十分钟前历史完全相同的消息时，旧页面可能把尚未发送的新消息误删。

实现只让 `local_messages.state IN ('sending','sent')` 参与启发式配对；`pending` / `waiting_history` 必须先真正交给传输层。精确 UUID 匹配不受此限制（Agent 实时回复使用服务端 UUID）。

### 2.3 动态页清理只在首屏刷新做，且包含“更新时间之后”

服务端动态时间是秒级字符串，同一秒可以有多条动态。若每次翻页都按 `[min,max]` 清理，第二页的同秒条目会把第一页整页删掉。

实现方式：

- 只在首屏 `refresh()` 时清理：删除 `created_at >= 本页最旧时间` 且不在本页 id 集合中的缓存。
- `load_more()` 不清理；更早缓存留给下一次首屏刷新或服务端撤下后的完整刷新修正。
- 同秒并列时可能短暂清掉本应属于下一页的条目，下一次 `load_more` 会重新带回。

### 2.4 首屏历史失败不释放发送 boundary

设计 5.6 要求 `waiting_history` 继续等待 boundary。实现中只有以下情况释放 boundary：

- 首屏成功并显示；
- 本地已有缓存窗口（restore_page 先显示）；
- 用户显式“跳过”历史同步。

首屏失败保持发送等待，避免在服务端历史基线未知时先发出消息、随后分页无法对账。UI 同时提供重试与跳过入口；`waiting_history` 超过 24 小时会在下次启动时转为 `SEND_EXPIRED`。

### 2.5 动态自动补评论放在 30 秒轮询，而不是每次 refresh

设计 6.5 要求在刷新时对比 `comment_count` 并做有界尾部拉取。若每次 `refresh()` 都对前 5 条动态发评论请求，首屏加载会产生大量额外请求，也让 UI 测试难以确定“评论首页”到底是 20 条还是完整 22 条。

实现方式：

- `refresh()` 只保存 `needs_comment_sync` 标记。
- 30 秒轮询（`_poll`）在刷新未读数后，按 `user_commented` 优先、`last_activity` 降序取最多 5 条执行尾部增量拉取。
- 用户打开详情时 `refresh_comments()` 仍会立即增量补齐。

### 2.6 预览卡片“点开即隐藏”持续到本次登录结束

原实现只清空内存里的预览。新实现会在打开一条未读动态时调用 `dismiss_preview()`；为了避免随后的 `_reload_all()` 又把下一条未读顶上来，本次登录内 `_preview_dismissed` 非空时不再显示预览卡片。退出/重新登录时清空该标记，离线启动仍会从本地库恢复最新未读预览。

### 2.7 图片消息的 `payload_json` 存完整发送载荷

重启后自动重发 `pending` 消息需要原始事件。文本消息很小；图片消息会把 base64 载荷写进 `payload_json`，上限受 6 MiB 附件限制。这样不依赖附件缓存目录也能重发。若后续需要减小库体积，可改为只存图片引用并在重发前从本地图片缓存重新编码。

### 2.8 `failed` / `DELIVERY_UNCERTAIN` 的 UI

- `virtual_message_list` 不再隐藏 `uncertain` / `superseded`；新状态机也不再产生 `uncertain`。
- `message_bubble` 对 `failed` 显示原因文案（“发送结果未确认，可能已送达”“本地保存失败”“排队超时，未发送”“发送失败”）以及“重试”“删除”按钮。
- 恢复出来的失败消息不再每次启动弹阻塞框，由气泡自身提示。

### 2.9 评论同步计数只在完整尾部同步后对齐

设计 6.6 要求每次成功写入评论都更新 `comment_synced_count`。实现改为：分页拉取只推进 `comment_cursor` / `comment_loaded_at_ms`；只有 `has_more = 0` 的完整尾部同步或用户自己发表评论时才对齐 `comment_synced_count`。

这样可避免“只拉到前 400 条、却把 `comment_synced_count` 标成服务端总数”导致后续回复永远不再触发补拉。达到单轮 20 页上限时保留 `comment_has_more = 1`，下一次刷新继续从游标增量拉取。

### 2.10 详情页自动已读按复合水位去重

设计 6.6 要求用户停留在详情页时，新回复渲染后同步推进已读水位。实现放在 `dynamics_window._mark_selected_read()`：

- 只处理带 `last_activity_*` 的本地缓存行；纯网络内存模式没有可持久化的水位，不做自动推进。
- 以 `(id, last_activity_at, last_activity_id)` 作为本次请求键，同一水位只请求一次，避免“标记失败 → changed → 再标记”的递归。
- 窗口不可见时不推进，避免后台窗口把用户未看的回复标成已读。

### 2.11 单行状态自愈与旧文件清理

`CREATE TABLE` 完整但 `sync_state` / `dynamic_state` 单行被异常删除时，打开库会补回绑定当前 scope 的状态行，而不是直接判定结构损坏。补建使用 `INSERT OR IGNORE`，正常启动不产生额外写事务。

重置/启动清理时先删 `-wal`、`-shm`，最后删主库；旧 `.v1.bak` / `.v2.bak` / `.discarded` 视为非关键备份，删除失败不阻塞正常库启动。没有主库时也会清理残留 sidecar，避免新库与旧 WAL 配对。

## 3. 遇到的问题与解决

### 3.1 GDScript 类型推断与 `RefCounted` 调用

`_access.query()` 通过无类型 `RefCounted` 调用，返回值是 `Variant`，使用 `:=` 会报 “Cannot infer the type”。所有存储层调用都显式标注 `Dictionary` / `Array`。

### 3.2 多行 lambda 中的 `return a or (b)`

`sort_custom(func(a,b): return a.x > b.x \n or ...)` 会被解析成语句结束。改为整体加括号：

```gdscript
return (a.x > b.x or (a.x == b.x and a.id > b.id))
```

### 3.3 `Array` 赋给 `Array[Dictionary]`

存储层返回无类型 `Array`；`DynamicsController._posts` 是 `Array[Dictionary]`。新增 `_typed_posts()` 做逐项拷贝，避免运行期类型错误。

### 3.4 `_load_post` 返回结构

重构时 `_load_post()` 返回 `{ok, data:{post, baseline}}`，调用方误用 `loaded.post`。改为 `loaded.data.post` / `loaded.data.baseline`，并补充了评论同步测试覆盖这条路径。

### 3.5 空评论缓存被误判为“已加载”

缓存缺失时 `_load_cached_comments()` 立即设置 `loaded = true`，详情页在评论网络页到达前就算“加载完成”，滚动位置断言会提前通过。

改为 `cache_attempted` 标记缓存是否尝试过；只有真正有缓存行或 `loaded_at_ms > 0` 时才设置 `loaded = true`。网络页保存后由 `_refresh_comments_from_store()` 设置 `loaded = true`。

### 3.6 测试夹具的排序假设

旧夹具让多条动态共享同一 `created_at`，并按 `d0..d9` 返回；本地 feed 按服务端契约 `created_at DESC, id DESC` 排序后首条是 `d9`。评论反馈测试原先默认 `get_posts()[0]` 是 `d0`，改为显式按 id 选 `d0`。

### 3.7 旧迁移测试失效

硬重置后不再存在 v1/v2 迁移路径，`test_sqlite_migration.gd` 删除；重置与文件头校验并入 `test_sqlite_database.gd`，新动态缓存测试为 `test_dynamics_store.gd`，作用域幂等测试为 `test_scope_session.gd`。

### 3.8 旧“预览翻页查找”测试失效

新设计不再为头像预览做网络深翻页；冷启动先显示服务端未读动态数，feed 刷新后从本地水位取最新未读。`test_dynamics.gd` 与 `test_dynamics_detail.gd` 已按本地缓存语义改写；未缓存老动态的通用提示由 `state.unread_hint` 覆盖。

### 3.9 boundary 放行越过本地提交

联调审计发现：等待历史期间发出的消息先登记在 `_pending_history`，boundary 可能在 `save_local` 仍排队时到达；旧实现会立刻 `_deliver`，违反“本地尾部提交成功后才发网络帧”。若随后保存失败，还会出现“已发网络帧但本地标记失败”的错位。

解决：新增 `_committed_local`。`_persist_and_deliver()` 保存成功后按当时 boundary 状态决定直接发送或标记为可发送；`_release_history_sends()` 只发送已提交记录，仍在途的记录由保存协程完成后自行发送。保存失败会同时移出待发队列并标记 `CACHE_WRITE_FAILED`。

### 3.10 `sending` 状态落库失败后的重复发送风险

网络帧发出后若 `update_local(sending)` 失败，库里可能仍保留 `pending`；重启恢复会自动重发。实现改为：帧发出后状态落库失败，立即在内存置 `failed + DELIVERY_UNCERTAIN` 并补写一次失败状态，至少避免 UI 继续显示可自动重发；只有用户手动重试才再次发送。

### 3.11 同秒水位只比较了时间

动态评论的 `_write_watermark()` 原先只比较 `last_activity_at` / `read_activity_at`，同一秒内 `id` 更大的新评论会被误判为“水位未变化”，导致不落库。已改为同时比较 `last_activity_id` / `read_activity_id`；`local_unread_comments` 对账 SQL 也补齐了同秒 id 比较。

### 3.12 详情页自动已读递归

第一版自动已读对纯网络内存动态也调用 `mark_post_read()`，但这类动态没有 `last_activity_at`，`is_unread()` 只能退回发布时间比较，标记后仍然未读；changed 信号再次触发，形成栈溢出。已加本地水位存在性与单次请求键两道保护，并由 `check_features.ps1` 的详情/阅读位置用例复验。

### 3.13 子代理编排不可用

本轮按仓库约定尝试派发只读审计子代理，`default`（`gpt-5.6-luna`）在当前 magpie 路由返回 404；随后改用主代理逐文件复核，未跳过实现检查。该问题属于会话运行环境，不是仓库代码。

### 3.14 评论尾部同步后 feed 仍是旧快照

`_sync_tail()` 只落评论并刷新 summary，没有重新读取 `dynamic_posts`；`needs_comment_sync` 与活动水位在内存里保持旧值，导致 30 秒轮询重复探测同一批帖子，也会让“详情页新回复自动已读”看不到新水位。解决：完整尾部同步后执行 `_reload_all()`，让 feed、未读汇总和详情共用最新行。

## 4. 验证证据

在 `Agent-LuoTianyi/client-godot` 下执行：

```powershell
python scripts/check_complexity.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 -Godot "D:\godot\godot4.7.1\godot.exe" -Python python -SkipImport
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_features.ps1 -Godot "D:\godot\godot4.7.1\godot.exe" -Python python
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_network.ps1 -Godot "D:\godot\godot4.7.1\godot.exe" -Python python
```

结果：

- 复杂度门禁：`302 files, 4204 units, 0 violations, 0 parse errors`。
- `check.ps1`：全部 headless 契约通过，包含 `sqlite-database`、`dynamics-store`、`scope-session`、`sqlite-worker`、`message-persistence`、`send-persistence-order`、`history-paging`、`message-merge`、`virtual-history`、`bubble-sizing`。
- `check_features.ps1`：历史/媒体、设置、动态、账号生命周期等全部通过。
- `check_network.ps1`：WebSocket 传输、真实文字聊天、语音聊天、触摸投递全部通过。

未覆盖：

- 旧客户端（version 3）读取 version 100 库的“优雅拒绝”无法在本仓库内真实复现；新客户端对非 `(LTHY, 100)` 文件头的删除/重建已覆盖。
- 真机 I/O、`synchronous=FULL` 的提交延迟、深分页同秒并列的服务端行为仍需实际账号与设备验证。
