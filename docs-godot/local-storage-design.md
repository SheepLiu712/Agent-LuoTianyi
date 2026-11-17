# 本地存储重构设计：聊天与动态持久化

## 1. 摘要

本文档定义 Godot 客户端本地 SQLite 存储的重构设计。方案将聊天历史从现有的 9 张表收缩为 3 张表（`messages`、`local_messages`、`sync_state`），新增动态持久化 3 张表（`dynamic_posts`、`dynamic_comments`、`dynamic_state`），共用单库、单 Worker 线程与 `ScopeSession`。版本升级采用一次性检查并清空旧库的硬重置策略（`user_version = 100`，`application_id = 0x4C544859`）。聊天读写采用“服务器历史槽位（`server_index`）+ 本地尾部（`local_seq`）”分离排序；动态未读放弃全局发布时间水位，采用每条动态独立的“活动水位（`last_activity`）与已读水位（`read_activity`）”，结合有界尾部拉取策略解决被回复旧动态的未读发现与离线恢复问题。

## 2. 背景与约束

客户端产品形态为 1:1 单会话 AI 对话客户端：单个账号仅存在一条用户与 Agent 的持续对话流，不存在群聊、多会话、分频道或联系人拓扑。动态模块是 Agent、系统与用户发布的内容信息流，每条动态支持嵌套/平行评论。

- **运行环境**：Godot 4.7.1，GDScript，`godot-sqlite` 4.9（静态链接 SQLite 3.51.0，`THREADSAFE=1`）。
- **插件能力边界**：支持 WAL 模式，支持 JSON1；**不具备 FTS5 全文索引、不具备 RTREE、不具备 SQLCipher 加密，不支持运行时加载外部扩展**。方案严禁依赖缺失特性。
- **数据权威性**：服务端持有唯一权威数据源；本地 SQLite 数据库仅作为可重建的高性能本地缓存与在途发送队列。
- **服务端接口不可变更**：重构仅限客户端内部实现，适配既有服务端限制：
  - `GET /history`：按 offset 分页滑动窗口，`start_index` 表示历史位置，非绝对稳定的增量游标。
  - `server_ack`：仅返回 `{ok, received_event_type, duplicate}`，不包含服务端分配的消息 UUID；历史拉取结果仅含 `uuid/content/source/timestamp/type`，不回显 `client_msg_id`。
  - 聊天去重机制：服务端仅在进程内存维持“用户 + client_msg_id”缓存，TTL 600 秒，上限 4096 条；进程重启后失效，多实例之间不共享。
  - `GET /dynamics`：固定按 `created_at DESC, id DESC` 排序，新产生的评论不会重排或提升旧动态的位置。
  - 动态未读接口：仅返回未读总数与 `last_read_dynamic_at` / `last_read_comment_at`，无“最近被回复动态”列表接口，无动态 WebSocket 实时事件推送。
  - `POST /dynamics/read`：仅支持全局标记已读，不支持单条动态或单条评论已读接口。
- **版本兼容取舍**：当前处于测试阶段，旧本地缓存数据允许直接作废，不编写旧版本 schema 的升级迁移逻辑。

## 3. 现状问题

当前聊天历史采用每账号单一 `history.db`（schema v3，共 9 张表），运行于单工作线程、单连接、WAL 模式及 `synchronous=FULL`。核心缺陷如下：

| 编号 | 问题分类 | 缺陷表现与代码路径 |
| :--- | :--- | :--- |
| 1 | 发送无跨重启持久化 | 传输层 `reliable_outbox` 与 `waiting_history` 仅保存在内存字典中，客户端退出或崩溃即丢失全部在途状态。 |
| 2 | 在途消息重启消失 | 重启时将未决在途消息置为 `uncertain`，而 UI 层（`client-godot/src/ui/virtual_message_list.gd`）直接过滤隐藏 `uncertain` 状态，导致用户感知“消息凭空消失”。 |
| 3 | 写失败静默丢弃 | 数据库写入异常时只累加内部计数器 `_discarded`，无用户感知通知与重试引导机制。 |
| 4 | 对账全表扫描 | `RECONCILE_LOCAL_UNCERTAIN` 基于 `id_source/delivery_state` 过滤，`RECONCILE_SERVER_CANDIDATES` 基于 `content` 过滤，缺乏对应索引，每页历史落库触发全表扫描（见 `client-godot/src/storage/history_page_writer.gd`）。 |
| 5 | 游标推进与写入倒置 | `client-godot/src/session/history_sync.gd` 中 `_advance_catchup` 发起异步 `_save` 后未等完成即推进 `_next_end`，落库失败时导致未写入页被永久跳过。 |
| 6 | Schema 冗余与废表 | `message_media`、`history_segments`、`segment_members` 从未发生写入；`history_positions` 与 `send_attempts` 引入多余复杂性。 |
| 7 | 动态完全依赖内存 | 动态列表与评论无本地缓存，重启后未读圆点、徽标数及头像预览全部归零，单条动态已读状态无法持久保留。 |

## 4. 总体决策

| 模块 / 维度 | 决策方案 | 实施细节与替代说明 |
| :--- | :--- | :--- |
| **数据库拓扑** | 保留单库模式 | 账号目录下单 `history.db`，由单 Worker 线程维护单连接。 |
| **聊天 Schema** | 9 表收缩为 3 表 | 保留服务器历史表 `messages`、在途本地尾部表 `local_messages`、游标状态表 `sync_state`；废弃旧表与分段表。 |
| **动态 Schema** | 新增 3 张表 | 新增 `dynamic_posts`（含评论游标）、`dynamic_comments`、`dynamic_state`。 |
| **连接共享** | 统一管理基础设施 | 聊天与动态复用同一连接与同一 `ScopeSession`，禁止独立开库。 |
| **版本迁移策略** | 硬重置，不迁移 | 检查文件头大端标识；若非 `(0x4C544859, 100)`，物理删除 `.db`、`.db-wal`、`.db-shm` 并重建。 |
| **聊天排序模型** | 槽位与尾部拼接 | 服务器历史按 `server_index` 升序，本地尾部按 `local_seq` 升序，UI 依次拼接展示。 |
| **动态未读模型** | 独立复合活动水位 | 放弃单一全局发布时间水位；每条动态维护独立的 `last_activity` 与 `read_activity`。 |

## 5. 聊天存储

### 5.1 建库 PRAGMA

在建立任何数据表前，必须按顺序设置以下 PRAGMA 配置：

```sql
PRAGMA auto_vacuum = INCREMENTAL;     -- 必须最先执行
PRAGMA application_id = 0x4C544859;   -- "LTHY"
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 3000;
PRAGMA journal_size_limit = 16777216;
PRAGMA foreign_keys = ON;
```

> **PRAGMA 顺序约束**：`auto_vacuum` 必须在 `application_id`、`journal_mode` 和建表之前执行。后两者会初始化数据库头；一旦数据库已被初始化，再设置 `auto_vacuum` 会被静默忽略（实测值为 0，而不是 2）。
>
> **版本写入时机**：`user_version = 100` 必须在全部建表语句成功之后最后写入；否则建表中途崩溃会留下一个“版本已标记为 100、结构却不完整”的坏库。`user_version = 100` 同时作为防回滚护栏：旧客户端版本仅支持 0–3，检测到版本 100 将安全拒绝打开。

### 5.2 表结构定义 (DDL)

```sql
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
```

### 5.3 排序模型

- **服务器历史表 (`messages`)**：仅收录服务端已确认历史。`server_index = start_index + i` 来源于分页计算，作为**缓存槽位**而非消息的永久全局身份。
- **本地尾部表 (`local_messages`)**：维护尚未并入服务器历史的尾部记录（包含未发送、发送中、已收 ACK 未对账、实时流式回复）。
- **本地序数 (`local_seq`)**：在单写者事务中通过 `COALESCE(MAX(local_seq), 0) + 1` 生成，尾部记录严格按 `local_seq ASC` 排序。
- **UI 视图渲染序列**：先读取服务器历史按 `server_index ASC` 呈现，末尾直接追加本地尾部 `local_seq ASC`。
- **槽位漂移容错**：当发生 offset 漂移时，写入端依赖 `INSERT OR REPLACE` 覆盖槽位。ID 位置变更或新 ID 挤占均可在单写事务中自愈；异常情况表现为瞬态显示重复或缺失，下一次拉取分页即修正。
- **基线对齐**：`baseline_index` 记录首屏刷新时服务端的最新索引；追平过程检测到 `start_index <= baseline_index` 即可判定与既有历史接合。

### 5.4 读路径

#### 5.4.1 最新页加载

```sql
SELECT * FROM messages ORDER BY server_index DESC LIMIT 30;
SELECT * FROM local_messages ORDER BY local_seq ASC;
```

业务层将 `messages` 的逆序查询结果在内存中反转为升序，末尾拼接 `local_messages` 结果输出。

#### 5.4.2 上翻更早历史

```sql
SELECT * FROM messages WHERE server_index < ? ORDER BY server_index DESC LIMIT 30;
```

若锚点行位于本地尾部，先取 `local_seq < ?` 的本地行；若本地行数量不足 30，差额部分继续向前查询服务器历史行。

### 5.5 写路径

#### 5.5.1 服务器历史页落库（单事务执行）

1. 遍历当前页（30 条）记录，执行 `INSERT OR REPLACE INTO messages`，分配 `server_index = start_index + i`。
2. 更新同步游标：`sync_state.next_end = start_index`；若是首屏请求，同时记录 `baseline_index = start_index + rows.size() - 1`。
3. 校验并清除本地尾部：
   - 若服务器行 `id` 与 `local_messages.id` 精确匹配（Agent 实时回复），直接删除对应本地行。
   - 若为用户发送消息：按时间升序进行贪心配对。当 `kind` 相同、`content` 一致且时间差 `|Δt| <= 600s` 时，判定匹配成功，删除对应本地行。
4. 递增 `sync_state.revision += 1`。

#### 5.5.2 用户消息发送

1. 单写事务插入 `local_messages`，初始 `state` 设为 `'pending'`（网络就绪）或 `'waiting_history'`（等待首屏对齐）。
2. 将数据递交网络传输层；生成有效 wire id 后，更新状态为 `'sending'`。
3. 收到服务端 ACK 后，更新状态为 `'sent'`，继续保留在本地尾部等待历史轮询确认。
4. 发送失败更新为 `'failed'`，保留界面重试与删除入口，不执行跨重启的无限制自动退避重试。

#### 5.5.3 助手实时回复处理

Agent 流式回复下发的 `agent_message` 结构中自带服务端分配的 `uuid`。本地直接以该 `uuid` 插入 `local_messages`，状态标记为 `state = 'received'`。后续上行拉取历史页匹配到相同 UUID 时，删除本地行，由 `messages` 表统一接管。

### 5.6 重启恢复状态机

| 重启前状态 | 恢复动作 | 自动重发策略 |
| :--- | :--- | :--- |
| `waiting_history` | 继续等待 history boundary 对齐；若挂起超过 24 小时置为 `failed`（错误码 `SEND_EXPIRED`）。 | 是 |
| `pending` | 重新移交传输层排队进入发送流程。 | 是 |
| `sending` | 强制置为 `failed`（错误码 `DELIVERY_UNCERTAIN`），UI 层显式提示“可能已发送”。 | **否** |
| `sent` | 保持不变，持续等待后续历史分页确认并对账清除。 | — |
| `received` | 保持不变，持续等待后续历史分页覆盖并清除。 | — |
| `failed` | 维持失败状态不变，等待用户手动触发重试或清除。 | 否 |

> **禁止自动重发规则**：`sending` 状态严禁自动重发。由于 `server_ack` 响应不携带服务端消息 UUID，且服务端去重窗口仅 600 秒且跨进程失效，重启后重发高概率导致产生重复历史。

### 5.7 库重置流程

1. 关闭当前正在运行的旧数据库连接；若文件不存在，直接按新库创建。若文件存在，直接读取文件头部前 100 字节二进制数据：按大端字序提取偏移 60 处的 `user_version` 及偏移 68 处的 `application_id`。严禁直接打开旧库以防止触发 WAL 日志回放。
2. 校验文件头：若 `(application_id, user_version) != (0x4C544859, 100)`，立即执行物理删除，必须同时删除 `history.db`、`history.db-wal` 与 `history.db-shm` 三个文件。
3. 重新建立数据库连接，按顺序执行建库 PRAGMA（`auto_vacuum` 必须最先），执行建表 DDL，最后写入 `user_version = 100`。
4. 若因外部多开或句柄占用导致文件删除失败，抛出错误码 `CACHE_RESET_FAILED` 并中断流程，严禁降级使用不兼容旧库。
5. 备份支持：可在删除前将旧文件重命名为 `history.db.discarded` 并发延后清理，同时清除残留的旧 `.v1.bak` 与 `.v2.bak`。
6. **首次启动行为约定**：账号首次在重构版本启动时，本地历史记录完整清空，按分页从服务端重新拉取；多媒体附件目录建议同步清理或依赖既有 256MB LRU 缓存策略平滑淘汰。

## 6. 动态存储

### 6.1 表结构定义 (DDL)

```sql
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
```

> **字段拆分说明**：`payload_json` 存储服务端全量 JSON 对象；仅将参与列表排序、分页、状态聚合及未读计算的核心字段提升为关系列。`comment_cursor` / `comment_has_more` / `comment_loaded_at_ms` 是本地评论同步簿记，不是服务端字段；刷新 `/dynamics` 对动态做 upsert 时必须保留这三列，不能被空值覆盖。

**为什么是 3 张表**：`dynamic_posts` 与 `dynamic_comments` 对应两个独立的分页资源——动态按 `created_at` 翻 feed，评论按 `post_id + created_at` 翻详情；`dynamic_state` 是单行全局状态，保存 feed 游标与服务端已读基线。评论游标原本单独成表，但它和动态严格 1:1，已并入 `dynamic_posts`，因此不再保留 `dynamic_comment_sync`。如果把评论改为纯网络请求、不做离线缓存，可进一步去掉 `dynamic_comments`，降为 2 张表。

动态列表分页由 `dynamic_state.posts_cursor` 与 `dynamic_state.has_more` 保存：首次刷新从空 cursor 拉取第一页，upsert 后写入下一页游标；`load_more` 使用已保存的游标继续向更早翻页。成功刷新一页后，删除“本页时间范围内、但本页未返回”的本地动态，以反映服务端撤下的内容；更早的缓存保留。

### 6.2 否定全局单一水位的架构分析

1. **发布时间与交互时间错位**：动态主体的 `created_at` 仅代表初始发布时间，后续评论发生在发布之后。旧动态产生新回复时，其 `created_at` 必然早于已推进的全局已读时间，使用全局发布水位无法识别未读。
2. **全局活动水位的交叉污染**：若维护单一的全局最新活动时间，用户查看动态 A 会整体推进该水位，导致动态 B 上的未读评论被连带错误标记为已读。
3. **服务端接口缺乏辅助**：`GET /dynamics` 严格按 `created_at DESC` 排序，新评论不会更新动态排序；`/dynamics/unread` 仅返回标量数字，无涉及帖子列表。
4. **架构决策**：将每条动态视为独立的“交互会话”，各自维护独立的活动水位与已读水位。

### 6.3 活动水位规则表

`last_activity` 维护该动态最近一次**非本人**的交互事件；`read_activity` 记录本地用户已查阅的水位。

| 业务触发事件 | `last_activity` 变更规则 | `read_activity` 变更规则 | 备注说明 |
| :--- | :--- | :--- | :--- |
| **收到新 agent / system 动态** | 记录 `(created_at, id, 'post')` | 若 `created_at <= server_read_at` 则同步，否则保持空 | 基线之后的新动态默认未读；基线之前的初始化为已读。 |
| **发布新 user 动态** | 保持空 | 保持空 | 用户自身发布的动态不计算为未读。 |
| **收到新 agent 评论** | 取 `max(当前水位, comment)` | 若 `comment.created_at <= server_comment_read_at` 则同步 | 使含有新回复的旧动态变为未读。 |
| **发布新 user 评论** | 保持不变 | 保持不变 | 置 `user_commented = 1`，纳入优先轮询。 |
| **打开 / 浏览动态详情** | 保持不变 | 更新为当前 `last_activity` | 用户查阅详情后清除未读。 |
| **点击全部已读** | 保持不变 | 所有行置为自身的 `last_activity` | 本地优先推进，服务端同步更新基线。 |

> **排序一致性约束**：水位比较统一采用 `(时间, id)` 复合二元组；同一时间戳内 `id` 较大者为更新，对应服务端 `created_at DESC, id DESC` 的排列顺序。

### 6.4 未读查询与状态推进

#### 6.4.1 未读总数（徽标数字）

```sql
SELECT COUNT(*) FROM dynamic_posts
WHERE last_activity_at <> ''
  AND (
    last_activity_at > read_activity_at
    OR (last_activity_at = read_activity_at AND last_activity_id > read_activity_id)
  );
```

徽标按“未读动态条数”计：一条动态即使新增多条评论，也只贡献 1 个未读点。评论条数只作为“是否有新回复”的诊断信号，不直接与动态条数相加。

#### 6.4.2 列表圆点判断

在内存中使用与上述相同的谓词逻辑计算单条动态的未读状态。当 `last_activity_kind = 'comment'` 时，列表可呈现“有新回复”专属角标。

#### 6.4.3 头像外露最新未读预览

```sql
SELECT payload_json, last_activity_kind, last_activity_at
FROM dynamic_posts
WHERE last_activity_at <> ''
  AND (
    last_activity_at > read_activity_at
    OR (last_activity_at = read_activity_at AND last_activity_id > read_activity_id)
  )
ORDER BY last_activity_at DESC, last_activity_id DESC
LIMIT 1;
```

#### 6.4.4 单帖标记已读

```sql
UPDATE dynamic_posts
SET read_activity_at = last_activity_at,
    read_activity_id = last_activity_id
WHERE id = ?;
```

#### 6.4.5 全量标记已读

```sql
UPDATE dynamic_posts
SET read_activity_at = last_activity_at,
    read_activity_id = last_activity_id
WHERE last_activity_at <> '';
```

> **执行次序原则**：全量已读在客户端本地事务中立即执行并刷新界面，随后异步调用 `POST /dynamics/read`。若服务端接口调用失败，仅提示网络异常，严禁回滚或重新点亮本地未读状态。启动同步时采用 `max(本地 read_activity, 服务端 last_read)` 融合，保证游标单调递增。

### 6.5 动态回复发现的有界策略与能力边界

由于服务端未提供“最近活跃动态”查询，且无 WebSocket 事件推送，系统采用有界轮询发现机制：

1. **信息流计数对比**：刷新 `/dynamics` 时，对比每条动态的 `comment_count` 与本地缓存的 `comment_synced_count`，若数值增加则置 `needs_comment_sync = 1`；尾部拉取成功后清零，并同步更新 `comment_synced_count`。
2. **游标保持**：评论拉取游标形式为 `created_at > cursor_time OR (= AND id > cursor_id)`；拉取完成后将最后一条已缓存评论游标写入 `dynamic_posts.comment_cursor`，即使 `comment_has_more = 0` 亦予以保留。后续刷新直接从该游标请求增量。
3. **用户参与帖加权**：用户发表评论后标记 `user_commented = 1`；列表刷新时优先拉取此类动态的尾部增量，覆盖“Agent 回复用户”的核心业务场景。
4. **差额启发式轮询**：若 `/dynamics/unread` 下发的 `unread_comment_count` 大于本地聚合算出的未读评论总数（本地已缓存评论中 `author_type <> 'user'` 且晚于该帖 `read_activity` 的条数，仅用于对账、不并入徽标），依据 `last_activity DESC` 选取本地前 5–10 条动态执行尾部探测，优先覆盖 `user_commented = 1`。
5. **降级通用提示**：若探测完成后未读差额依然存在，表明回复落在未曾缓存且未在当前分页列表中的远古动态；此时动态入口直接常驻提示“有新的评论”，禁止发起无限制的全量深翻页。

**能力边界声明**：
- **可完全保障**：已加载信息流各页中 `comment_count` 发生递增的动态；用户主动发表过评论的动态；当前正打开查看的动态；处于轮询命中窗口内的动态。
- **无法保障**：从未载入本地缓存、未出现在已加载页码且用户未曾评论过的历史老动态。在缺乏服务端定向索引接口的前提下，客户端不可逾越该物理边界。

### 6.6 评论缓存生命周期

- 详情调用 `load_comments(post_id)` 时，优先读取本地评论列表完成首屏秒开渲染，随后异步拉取服务端第一页。
- `refresh_comments` 依序遍历直至 `comment_has_more = 0`，每页在一个写事务中 upsert 评论数据并刷新 `comment_cursor` 与 `comment_loaded_at_ms`。
- 评论查询固定按 `(created_at, id)` 升序，`comment_cursor` 严格锚定至最新一条评论记录。
- 写入 `author_type = 'user'` 的评论时同时置 `user_commented = 1`；每次成功写入评论后更新 `comment_synced_count`，用于与刷新返回的 `comment_count` 比较。
- 动态记录被清理或淘汰时，依赖外键 `ON DELETE CASCADE` 自动级联清理关联的评论数据。
- 打开详情并呈现评论内容时，立即推进该动态的 `read_activity`；若用户正停留于详情界面，当新回复到达渲染后同步推进水位，避免当前动态持续常驻未读状态。

### 6.7 首次同步与跨设备基线

- 账号初次登录时，以服务端返回的 `server_read_at` 与 `server_comment_read_at` 为界，将早于该基线的动态与评论批量初始化为已读状态。
- 服务端 `last_read_dynamic_at` 与 `last_read_comment_at` 仅用于单向推进本地基线，不强制回退本地已有的超前已读状态。
- 用户自身发表的评论不推进 `last_activity`，但触发 `user_commented = 1` 进入轮询管线；自身动态收到 Agent 回复时正常更新 `last_activity` 并触发未读。

## 7. 共享基础设施

- **连接复用**：聊天历史与动态数据存储在同一物理文件 `history.db` 中，由单一的 `SqliteWorker` 线程处理，保持单连接。
- **`ScopeSession`**：封装账号作用域打开逻辑（`root + scope + ensure_open()`）。当检测到指定 scope 已打开时直接返回元数据，避免并发重复调用 `close/open`。
- **持久化门面集成**：`MessagePersistence` 与新增的 `DynamicsPersistence` 均注入同一个 `ScopeSession` 实例，动态模块启动不得尝试重复建立数据库连接。
- **安全白名单与调度隔离**：`SqliteHistoryDatabase` 维持 SQL 命令白名单与作用域拦截；新增 `DynamicsStore`，底层复用既有 `Access` 句柄执行指令。
- **Worker 调度命令集**：
  - 聊天命令：`open_scope`、`read_latest`、`read_before`、`save_page`、`save_local`、`update_local`、`read_sync_state`、`flush`。
  - 动态命令：`dynamics_load`、`dynamics_save_posts`、`dynamics_save_comments`、`dynamics_mark_read`、`dynamics_state`。

## 8. 性能与并发

- **单写模型**：严格采用单写者 FIFO 排队。聊天数据每页 30 条合并为一个写入事务；动态数据每页 10 条或评论每页 20 条合并为一个写入事务。
- **查询路径优化**：
  - 聊天最新页与历史翻页分别命中 `server_index` 唯一索引的反向扫描与 `local_seq` 唯一索引的正向扫描；彻底移除全表对账扫描与本地重编号操作。
  - 动态 Feed 列表查询走 `(created_at DESC, id DESC)` 复合索引；未读聚合命中部分索引（Partial Index）；最新预览走 `(last_activity_at DESC, last_activity_id DESC)`。
- **刷盘机制**：初期维持 `synchronous = FULL` 以保证最高可靠性。若真机量测发现提交延迟成为瓶颈，再权衡降级至 `NORMAL`（降级需承受断电丢失最后少量事务的风险）。
- **生命周期优化**：关闭连接或执行 `flush` 时执行 `PRAGMA wal_checkpoint(TRUNCATE)`，并追加调用 `PRAGMA optimize`。
- **缓存容量淘汰**：聊天历史按需保留；动态数据建议保留最近 500 条或最近 90 天记录，执行批量清理后触发 `PRAGMA incremental_vacuum`。
- **技术边界坚守**：坚决不引入 FTS5、SQLCipher 或独立的附件关联表，避免插件重编译风险并保持数据库文件的可读性。

## 9. 模块影响

| 模块文件路径 | 改动性质 | 职责与变更说明 |
| :--- | :--- | :--- |
| `client-godot/src/storage/history_schema.gd` | 重写 | 落地 6 张新表 DDL、索引定义及预编译查询常量。 |
| `client-godot/src/storage/history_schema_installer.gd` | 重写 | 执行新库初始化：设置 `application_id`、`auto_vacuum` 及写入版本号 100。 |
| `client-godot/src/storage/history_migration.gd` | 删除 | 彻底移除增量迁移逻辑，统一由 Reset 硬重置接管。 |
| `client-godot/src/storage/sqlite_history_database.gd` | 修改 | 集成头部二进制检测与文件清理；收敛命令路由；接入 `DynamicsStore`。 |
| `client-godot/src/storage/history_page_writer.gd` | 重写 | 整页 `INSERT OR REPLACE` 写入；确认并移除本地尾部；更新游标；移除锚点计算与重编号。 |
| `client-godot/src/storage/timeline_reader.gd` | 重写 | 执行服务器历史与本地尾部双查询拼接逻辑。 |
| `client-godot/src/storage/dynamics_store.gd` | 新增 | 承载动态、评论与同步状态的 SQL 语句与对象映射。 |
| `client-godot/src/storage/scope_session.gd` | 新增 | 负责幂等打开账号作用域，供给聊天与动态模块共享。 |
| `client-godot/src/domain/timeline_slots.gd` | 删除 | 移除槽位计算逻辑，由数据库自愈替代。 |
| `client-godot/src/domain/history_runs.gd` | 删除 | 移除旧分段合并模型。 |
| `client-godot/src/session/message_persistence.gd` | 修改 | 提供本地尾部操作接口，关键写操作支持 await，实现启动状态恢复。 |
| `client-godot/src/session/dynamics_persistence.gd` | 新增 | 提供动态 Worker 门面服务，负责 scope 校验与行数据转 DTO。 |
| `client-godot/src/session/history_sync.gd` | 修改 | 移除 epoch 机制、reconcile 抓取器与防抖层；保留首屏拉取、追平、上翻及写失败停游标逻辑。 |
| `client-godot/src/session/chat_session.gd` | 修改 | 流程改为先落本地尾部再发起网络请求；重启继续分发 pending；`waiting_history` 落库。 |
| `client-godot/src/session/dynamics_controller.gd` | 修改 | 切换为本地缓存优先；刷新/翻页/发评落库；接入活动水位与对账逻辑。 |
| `client-godot/src/composition/application_services.gd` | 修改 | 统一创建并单例注入 `ScopeSession` 与 `DynamicsPersistence`，编排服务依赖。 |
| `client-godot/src/ui/message_bubble.gd` | 修改 | 支持 `failed` 状态消息渲染与交互，提供重试与删除操作。 |
| `client-godot/src/ui/virtual_message_list.gd` | 修改 | 取消对 `failed`（含 `DELIVERY_UNCERTAIN`）消息的隐藏过滤；新状态机不再产生 `uncertain`。 |
| `client-godot/src/ui/dynamics_window.gd` | 修改 | 数据源与未读判定对接本地活动水位。 |
| `client-godot/src/avatar/avatar_panel.gd` | 修改 | 头像外露红点与最新未读预览直接从本地存储恢复，支持离线启动。 |
| `client-godot/tests/storage/*` | 重写/新增 | 编写新 schema、读写分离与重置逻辑单元测试。 |
| `client-godot/tests/test_dynamics.gd` | 新增/修改 | 覆盖动态缓存、游标迭代与未读计算测试。 |
| `client-godot/tests/ui/test_dynamics_reading_position.gd` | 修改 | 适配基于复合活动水位的阅读位置断言。 |
| `client-godot/docs/dev-database.md` | 更新 | 更新 6 表完整清单、版本 100 说明、重置约定及动态存储规范。 |

## 10. 测试计划

### 10.1 聊天模块验证

- **槽位自愈与覆盖**：模拟相同 `server_index` 注入不同 `id`，以及相同 `id` 分配不同 `server_index`，断言数据库内最终只有唯一单行数据。
- **分页顺序拼接**：验证最新页与多轮上翻时，服务器历史行与本地尾部行的衔接无缝且时间严格递增。
- **本地尾部重启状态转移**：
  - 构造 `pending` 状态消息，重启后断言重新提交传输层。
  - 构造 `sending` 状态消息，重启后断言流转为 `failed`，错误码为 `DELIVERY_UNCERTAIN`。
  - 构造 `waiting_history` 消息，断言重启后保留并继续等待。
- **对账精确与启发式清除**：
  - 校验 Agent 回复依据 UUID 精确匹配删除本地行。
  - 校验用户消息基于同 `kind`、同文本、600 秒窗口的贪心策略按既定规则匹配并删除本地行。
- **硬重置机制**：提供旧 v3 数据库文件，验证启动时检测到头信息不匹配并正确删除三件套文件，新建版本 100 数据库；验证旧版客户端读取版本 100 库时优雅拒绝。
- **建库配置断言**：新库创建后断言 `PRAGMA auto_vacuum = 2`、`PRAGMA journal_mode = wal`、`PRAGMA user_version = 100`、`PRAGMA application_id = 0x4C544859`；防止 PRAGMA 顺序错误导致 `auto_vacuum` 被静默忽略。
- **查询计划审计**：执行 `EXPLAIN QUERY PLAN`，断言最新页读取与范围上翻均命中对应索引。

### 10.2 动态模块验证

- **回复未读触发与清除**：旧动态获得 Agent 新评论后断言其状态转为未读；进入详情查看后断言清除未读；同一动态再次获得回复断言重新置为未读。
- **用户自评与 Agent 回复隔离**：用户自行发表评论后断言该动态不置为未读；随后 Agent 回复该评论断言动态转为未读。
- **同秒并发仲裁**：构造 `created_at` 相同的多条评论，验证基于 `id` 排序后活动水位与阅读水位计算准确。
- **跨设备水位单向推进**：模拟服务端返回的 `last_read` 分别领先或落后于本地水位，断言本地水位始终单调递增，不发生倒退。
- **评论尾部增量拉取**：验证 `comment_cursor` 增量拉取不丢、不重；在 `comment_has_more = 0` 状态下追加评论后仍能持续拉取。
- **未缓存老帖回复防御**：模拟未命中缓存的旧动态回复场景，断言系统不崩溃，且入口正确展示“有新的评论”通用角标。
- **冷启动状态恢复**：断开网络启动客户端，验证未读圆点、未读角标数及头像最新预览均能准确重现。

### 10.3 共享基础设施验证

- **作用域打开幂等性**：针对同一账号 scope 反复调用 `ensure_open()`，断言底层连接句柄保持不变，不触发重新建链。
- **作用域错位拦截**：跨 scope 调用接口时，断言底层抛出 `STALE_SCOPE` 异常并拒绝执行。
- **Worker 退出安全清空**：触发 Worker 终止信号时，队列中排队的待办任务全部完成结算或报错，不产生线程悬挂。

## 11. 实施顺序

本工程预计单人研发工期约为 8–9 个工作日，按以下阶段分步推进：

```
[阶段 1: 2-3 天] 聊天 Schema 重写 + Reset 流程 + ScopeSession 基础设施
       │
[阶段 2: 2 天]   聊天本地尾部状态机 + 发送恢复 + UI 失败态交互支持
       │
[阶段 3: 2 天]   动态 4 表落地 + 缓存读写管道 + 独立活动水位算法
       │
[阶段 4: 1 天]   动态回复有界发现 + 尾部游标轮询 + 头像预览与红点接入
       │
[阶段 5: 1 天]   测试用例重构补齐 + 开发设计文档同步更新
```

## 12. 风险与注意事项

1. **服务端 Offset 漂移风险**：历史分页基于相对 offset，服务端追加删除可能导致游标位置偏移。方案采用 `INSERT OR REPLACE INTO messages` 按槽位覆盖自愈，极端情况下可能出现短暂重复或漏看，下一次分页拉取即可自动修复；在单会话仅追加的历史形态下发生概率极低。
2. **同秒级排序歧义**：服务端接口未定义绝对纳秒序或全局连续自增 ID。本地使用 `(时间, id)` 作为复合排序键，可确保本地呈现绝对幂等与自洽，但极端情况下无法保证与服务端未定序的顺序绝对镜像。
3. **本地尾部视图假设**：本地尾部记录（`local_messages`）始终追加显示在所有服务端已确认历史的最下方。若用户在昨日网络断开残留发送失败消息，今日上线后该消息仍排列在今日拉取的最新历史之后。此为 1:1 单会话模型的既定产品取舍。
4. **用户消息启发式消除局限**：因服务端缺少客户端消息 ID 回显，用户消息清除依赖“同内容 + 600 秒时间窗口 + 时间升序”贪心配对。极端并发连续发送完全相同内容并发生网络抖动时，可能产生配对错位。
5. **在途消息禁止重发**：`sending` 状态重启后严禁无脑重传。由于服务端 ACK 缺失消息 UUID，且服务端去重缓存生命周期仅为 600 秒且单进程受限，客户端盲目重发将直接导致服务端生成多条重复消息。
6. **动态未读发现的物理限制**：对于从未拉入本地缓存、未在已翻阅页呈现且用户未曾评论的老动态，客户端无法无中生有定位帖子 ID，只能依据服务端宏观未读差额提供“有新评论”的通用入口提示。
7. **硬重置破坏性**：重置操作会彻底清空本地所有聊天与动态缓存。执行删除时必须确保 `.db`、`.db-wal`、`.db-shm` 三文件一并删除。
8. **跨进程文件锁冲突**：若用户多开客户端实例导致 SQLite 数据库文件句柄被锁定，重置逻辑将抛出 `CACHE_RESET_FAILED` 终止运行，禁止回退使用破损数据库。
9. **I/O 写入性能权衡**：`synchronous = FULL` 在每次事务提交时调用文件系统 `fsync`。需在实际目标平台上测试磁盘 I/O 耗时，确有必要时再评估降级方案。
10. **`auto_vacuum` 约束**：`PRAGMA auto_vacuum = INCREMENTAL` 必须在全新建库时最先执行，且早于 `application_id`、`journal_mode` 与建表；顺序错误会静默退化为 0。建表后修改需要整库 `VACUUM`，成本高。本次重建正好一次性规范化，后续不得随意变更该配置。

## 13. 参考

- 既有聊天 Schema：`client-godot/src/storage/history_schema.gd`
- 既有历史页写入/对账：`client-godot/src/storage/history_page_writer.gd`
- 既有持久化门面实现：`client-godot/src/session/message_persistence.gd`
- 既有历史同步控制器：`client-godot/src/session/history_sync.gd`
- 既有动态业务控制器：`client-godot/src/session/dynamics_controller.gd`
- 动态 UI 与红点渲染：`client-godot/src/ui/dynamics_window.gd`、`client-godot/src/ui/dynamics_post_row.gd`、`client-godot/src/avatar/avatar_panel.gd`
- 服务端历史 HTTP 接口定义：`docs/服务端接口-HTTP.md`
- 服务端 WebSocket 协议与幂等规范：`docs/服务端接口-WebSocket.md`
- 动态服务端底层实现：`server/src/infrastructure/persistence/database/services/dynamic_store.py`
- 开源客户端 IM 存储架构调研：`docs-godot/im-storage-research/`
