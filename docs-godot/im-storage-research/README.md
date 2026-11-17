# 开源 IM 本地消息存储调研

> 调研日期：2026-11-16。范围是 GitHub 上仍在维护、且客户端确实把消息历史持久化到本地的开源即时通讯项目或官方客户端。每篇项目文档都锁定到具体 commit，并给出 `path:line` 级证据。

## 为什么是这七个项目

筛选标准有三条：

1. 项目是开源 IM 或 IM 协议实现，客户端有可读的本地存储代码，而不是只把消息留在服务端。
2. 本地库承担的是「消息历史」而不只是设置、草稿或联系人缓存。
3. 代码仍活跃，能在 2026 年的仓库里定位到完整读写、同步与离线路径。

因此，Zulip、Nextcloud Talk 这类以 Web 端在线使用为主、没有客户端消息库的项目没有入选；Jitsi 这类以音视频会话为主的项目也没有纳入。Mattermost 服务端以 PostgreSQL/MySQL 为权威存储，Rocket.Chat 服务端以 MongoDB 为权威存储；本文入选的是它们的官方 React Native 客户端，因为消息本地化发生在客户端 SQLite 中。

七个项目覆盖了五类典型路线：

- 服务端权威的移动端缓存：Mattermost、Rocket.Chat、OpenIM。
- 可重建的 Web 快照：matrix-js-sdk / Element Web。
- 原生端多库事件缓存：matrix-rust-sdk / Element X。
- 单库加追加日志：Telegram TDLib。
- 端上即历史权威：Signal、SimpleX。

## 项目清单

| 项目 | 本地存储介质 | 本地库角色 | 离线发送 | 数据库加密 | 文档 |
|---|---|---|---|---|---|
| Mattermost Mobile | WatermelonDB + SQLite，按 serverUrl 分库 | 服务端缓存 | 无 durable outbox，失败后手动重试 | 数据库层未配置 | [01-mattermost-mobile.md](01-mattermost-mobile.md) |
| Rocket.Chat Mobile | WatermelonDB + SQLite，按服务端分库 | 服务端缓存 | 无 durable outbox，TEMP/SENT/ERROR 状态 | 未配置 | [02-rocketchat-mobile.md](02-rocketchat-mobile.md) |
| Element / Matrix | Web 用 IndexedDB 快照；Element X 用 4 个 SQLite 库 | 可重建缓存 | Web：localStorage 待发；Rust：持久化 send queue | Web 无整库加密；Rust 为值加密 | [03-element-matrix.md](03-element-matrix.md) |
| Signal | SQLCipher SQLite（Desktop 与 Android 各一套） | 端上历史权威 | 入站 at-least-once 队列；发送状态与 job 队列 | SQLCipher 整库加密 | [04-signal.md](04-signal.md) |
| Telegram TDLib | 单 SQLite（`db.sqlite`）+ 追加式 binlog | 服务端权威的物化缓存 + 待发日志 | binlog 即 outbox，启动重放 | tddb 支持 SQLCipher，取决于传入 key | [05-telegram-tdlib.md](05-telegram-tdlib.md) |
| OpenIM SDK Core | 每用户一个 SQLite，每会话一张消息表 | 服务端缓存 | 失败置失败态，不自动重发 | 明文 | [06-openim-sdk.md](06-openim-sdk.md) |
| SimpleX Chat | SQLite，chat 库 + agent 库 | 端上唯一历史载体 | agent 层队列 + 群成员补发表 | 取决于打开参数 | [07-simplex-chat.md](07-simplex-chat.md) |

### 项目速览

- **Mattermost Mobile**：Mattermost 的官方 iOS/Android 客户端，用 WatermelonDB 把帖子、频道、用户与文件元数据按工作区缓存到本地；发送走本地乐观写入，失败后由用户手动重试，服务端始终是权威。
- **Rocket.Chat Mobile**：Rocket.Chat 的官方 React Native 客户端，用两套 WatermelonDB/SQLite 库保存服务端列表与房间消息；支持离线浏览与 TEMP 状态发送，但没有持久化 outbox，重连后不会自动重发失败消息。
- **Element / Matrix**：同一协议下的两代客户端存储。Element Web 通过 matrix-js-sdk 把整个 `/sync` 累积快照写进 IndexedDB；Element X 通过 matrix-rust-sdk 把状态、事件缓存、媒体与加密拆成四个 SQLite 库，并用双向链表分块组织时间线。
- **Signal**：以端到端加密为核心的 IM，Desktop 与 Android 都用 SQLCipher 保存消息历史；服务端只排队转发，本地库是历史权威，代价是密钥管理、两端 schema 分叉与多设备历史缺口。
- **Telegram TDLib**：Telegram 官方跨平台客户端库，把消息、会话、文件元数据与通用 KV 放进一个 `db.sqlite`，再用追加式 `td.binlog` 同时承担更新游标与发送 outbox。
- **OpenIM SDK Core**：OpenIM 各端 SDK 的 Go 公共内核，每个用户一个 SQLite 文件、每个会话一张消息表；服务端 `seq` 是唯一权威，客户端按区间补拉，失败发送交给上层 App 重试。
- **SimpleX Chat**：无用户标识符的去中心化 IM，chat 库保存协议消息体与 UI 会话项两层数据，agent 库负责投递；服务端不存历史，换机或丢库无法回拉。

## 横向对比

### 1. 本地库是缓存还是权威

这是影响全部设计的第一分界线。

Mattermost、Rocket.Chat、OpenIM 都把服务端视为唯一权威：客户端库可以离线读历史，但消息序号、删除、编辑和最终状态都由服务端决定。它们的同步问题因此可以简化为「拿到一个游标，补齐游标之后的变更」。

Signal、SimpleX 则相反。服务端只负责排队或转发，消息历史只存在设备上；换机、重装或库损坏都没有中心历史可回拉。它们必须自己承担去重、投递状态、附件生命周期与本地一致性。

Element 位于中间：协议坚持 Homeserver 权威，客户端库是可从 `next_batch` 重建的缓存；但 Element X 的 send queue 又承担了很强的本地持久化责任，保证未发送请求在进程重启后仍能恢复。

TDLib 也处于中间位置：消息以服务端为权威，但 binlog 同时承担更新游标与发送 outbox，本地恢复语义比普通缓存更重。

### 2. 数据模型的四种取向

| 取向 | 代表 | 优点 | 代价 |
|---|---|---|---|
| 整包快照 | matrix-js-sdk | 实现最简单，天然无脏数据累积 | 无事件级索引，无法本地分页或检索历史 |
| 窄列 + 序列化 BLOB | TDLib | 表结构稳定，服务端字段演化由 TL 层吸收 | 外部不可读，新增过滤维度要加列回填 |
| 宽表 + JSON 字段 | Signal Desktop、Rocket.Chat | 列可索引，消息对象仍可演进 | JSON 字段要生成列才能索引，宽表迁移成本高 |
| 按会话分表 | OpenIM | 单会话读写局部化，隔离彻底 | schema 对象随会话数膨胀，跨会话查询困难 |

SimpleX 还提供了第五种：把协议消息体与 UI 会话项拆成两层，用关联表连接。分页只扫 UI 层，正文留在消息层；代价是发送要跨多个事务，双写一致性需要自己兜。

### 3. 同步游标决定 gap 处理方式

- Mattermost 用 `lastFetchedAt` 或本地最新帖时间做 `GetPostsSince`，再用一页常规分页补齐历史空洞。
- Rocket.Chat 用 `subscriptions.last_open` 调 `chat.syncMessages`，必须等 UPDATED 分页排空才推进游标。
- Element 用 Matrix 的 `next_batch`；Web 端遇到 `limited` 直接清空房间时间线，Rust 端则在双向链表里插入 Gap 节点。
- TDLib 用 `pts/qts/date` 调 `getDifference`，小缺口单条修复，大缺口整体补差。
- OpenIM 用服务端 `seq` 区间补拉，内存游标重启后由本地各会话最大 `seq` 重建。
- Signal 与 SimpleX 没有中心历史游标：前者靠 envelope 队列与多设备 transcript，后者靠本地写入与 agent 投递状态。

### 4. 离线发送是最能拉开差距的一层

「能离线写一条消息」和「能可靠送达」是两件事。

Mattermost、Rocket.Chat、OpenIM 都只做到前者：消息先落本地，失败后标记状态，但没有跨重启的持久化 outbox，也没有自动重发。用户必须手动重试，或者由上层 App 自己补一套队列。

TDLib 把 outbox 藏进 binlog：发送前写 `SendMessage` 事件，启动时重放并重发。SimpleX 把发送队列放在 agent 层，chat 库只记录投递状态；Signal Android 用 `job_spec` 做持久化任务与退避，Desktop 用消息 JSON 里的发送状态加 `jobs` 表；Element X 用 `send_queue_events` 做严格保序队列，并用 `Wedged` 显式表达队头阻塞。

这条差异比「用了 SQLite 还是 IndexedDB」重要得多：没有持久化 outbox 的客户端，断网、杀进程或崩溃之后无法保证用户点过发送的消息还会继续投递。

### 5. 加密与可检索性存在直接冲突

Signal 用 SQLCipher 做整库加密，代价是密钥管理与页级加解密开销；TDLib 也支持 SQLCipher，但空 key 会退化为明文，加密是调用方的选择；SimpleX 的库层是否加密取决于打开参数。

Mattermost、Rocket.Chat、OpenIM 的数据库层没有加密配置，安全边界主要交给操作系统沙箱与磁盘加密。Element 的 Rust SDK 选择了另一条路：不加密整库，而是对键做哈希、对值做应用层加密，从而保留按哈希键查询的能力；Web 端则把加密密钥库单独放在另一个 IndexedDB 中。

没有一个方案同时做到「整库加密、任意字段可索引、零密钥管理成本」。这通常要在威胁模型、查询能力与实现复杂度之间做取舍。

## 关键结论

1. **本地存储的难点不在「存」，而在「什么时候敢删、什么时候敢推进游标」。** 所有服务端权威方案都在处理同一个问题：游标推进早了会丢消息，推进晚了会重复拉取。幂等 upsert 与「排空后再推进」是两种最常见的答案。
2. **持久化 outbox 是离线可靠性的分水岭。** 仅把失败消息留在消息表里，不等于它会被重发；binlog、send queue、job 表才是跨重启的投递保证。
3. **数据模型的选择取决于是否需要本地查询。** 如果客户端只按会话时间线翻页，快照或窄表加 BLOB 足够；如果要本地搜索、跨会话聚合或离线分析，就必须把可检索字段提升为列并维护索引。
4. **schema 演进成本常被低估。** 整包快照最容易迁移，按会话动态建表最难迁移；TDLib 用 BLOB 把字段演化推给序列化层，但也把「新增过滤维度」变成了加列回填工作。
5. **端上权威会改变整个系统。** Signal 与 SimpleX 一旦把历史放在本地，就必须自己承担多设备缺口、备份恢复与去重；反过来，它们也换来了服务端不可见的历史与更强的隐私边界。

## 阅读顺序

建议先读 Mattermost 与 Rocket.Chat，建立「服务端权威 + 本地缓存」的基线；再读 Element，对比 Web 快照与 Rust 事件缓存两代路线；然后读 TDLib，看单库加 binlog 如何把游标与 outbox 合并；最后读 Signal、OpenIM 与 SimpleX，分别观察整库加密、按会话分表与双层消息模型三种不同的取舍。

## 调研方法

1. 先用 GitHub API 核对仓库活跃度、许可证、主语言与 stars，再按「客户端是否有消息本地持久化代码」筛掉纯服务端或纯 Web 项目。
2. 对每个入选项目做浅克隆或 sparse checkout，锁定 `git rev-parse HEAD`，用 `rg` 定位数据库初始化、schema/migration、消息读写、同步游标、outbox/重试与附件路径。
3. 只把能落到 `path:line` 的结论写进文档；无法验证的机制标为「未找到证据」或「推断」，并在每篇末尾集中列出未覆盖项。
4. 不做编译、真机运行、崩溃注入或性能压测，因此文档分析的是代码表达的设计与边界，不是实测性能结论。

## 证据与边界

- 每个项目都锁定到文档内标注的 commit；行号以该 commit 的工作区为准。
- 主要证据来自源码静态阅读与 GitHub API 元数据，没有做编译、真机运行、崩溃注入或性能压测。
- Stars 是 2026-11-16 的快照，仅用于说明项目规模，不代表质量排名。
- 各项目的「未验证与材料未覆盖」小节列出了没有查清的部分；涉及推断的结论在正文中保留了不确定性措辞。
- 原始素材保存在 `.codex/doc-material/im-storage/`，可按项目复核 `path:line`。
