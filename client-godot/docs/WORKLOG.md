# Godot 客户端开发工作记录

本文件是 Agent-LuoTianyi Godot 客户端（`client-godot/`）**唯一的工作记录汇总**，由 2026-09 至 2026-11 期间散落的开发日志、五轮 PR 审查、整改自述、专项诊断与设计交接合并而成。

---

## 1. 文档定位与维护规则

- **本文件是记录，不是契约**。行为以源码与针对性测试为准，架构以 [现行架构](architecture.md) 为准，门禁以 [测试与门禁](testing.md) 为准。
- 冲突裁决顺序：源码/测试 > `architecture.md` > 本文件 > 归档原文。归档原文中已被后续推翻的结论**不会**在本文件重复。
- `client-godot/docs/*` 已被 `export_presets.cfg` 的 `docs/*` 排除，**不随便携包分发**。
- 新增记录只在本文件对应小节追加，并同步 §15 归档索引；不修改已归档原文。
- 不记录瞬时状态（"尚未提交""HEAD 仍是基线"之类），这类信息在 10 月的两份文档里已造成过审查歧义（见 §14 N31）。

## 2. 版本与发布史

版本权威字段只有三处：`release.json`、`project.godot` 的 `config/version`、`export_presets.cfg` 的 `application/file_version` 与 `product_version`。构建脚本会同时回写三者，`tests/test_review_documentation.py` 会校验它们一致。

| 版本 | 端 | 主要内容 | 证据 |
|---|---|---|---|
| V0.0.2 | 旧 Python 客户端 | 历史图片 UUID 重取、SSL 换受信证书、`picture`→`image` 类型名统一、思考气泡不再空转、右键菜单样式 | `client/changelog.md`（原文保留在 `client/` 语境） |
| v0.1.3 | 服务端 + 旧客户端 | 改 WS 全双工、TTS 回放、TTS 流式输出、去掉 redis、记忆读写收紧、vcpedia 日常更新、城市漫步 | 根 README 更新日志 |
| v0.2.1 | 同上 | 人设微调、触摸发声、服务器地址可配、邀请码重置、官方动态同步与主动发言、自动学歌、手机版夜间模式 | 根 README 更新日志 |
| v0.3.0 | 同上 | 动态功能（发布/评论/入口红点）、world 事件驱动发帖、管理端动态管理 | 根 README 更新日志 |
| v0.3.1 | 同上 | 每日日记、邀请码管理、Bug#1–#15 修复 | 根 README 更新日志 |
| **0.1.5** | Godot 客户端 | PR #186 引入完整 Windows 客户端；第四轮整改后树内版本统一为 0.1.5（此前为 0.1.3） | 归档 `review-186-4th-round.md` |
| **0.1.5.1** | Godot 客户端 | 首次按整改后源码打包，产物约 45 MB | `.workbuddy/memory/2026-11-08.md` |
| **0.1.5.2** | Godot 客户端 | 修 `verify_release_archive.py` 的 DLL 数量 2→3；ZIP 45,102,231 B，sha256 `7286316a…3752a1` | `.workbuddy/memory/2026-11-09.md` |
| **0.1.5.3** | Godot 客户端 | 当前版本；`agentluo.exe` 109,199,872 B + `agentluo.pck` 6,144,764 B + 3 个 DLL；ZIP 45,132,399 B / 15 条目 / sha256 `4497c7a4…` | 同上 |

**引擎口径**：目标 4.7.x；**交付与门禁锁定 `4.7.1.stable.official.a13da4feb`**（见 `dependencies.lock.json`，并对 GUI 可执行文件做 SHA-256 校验）。4.7.2 只在两处出现过，均非交付口径：动效方案作者的本机二进制（已归档），以及第 1 轮审查对 `rename_absolute` 做的 4.7.1/4.7.2 双版本对照实验。

## 3. 架构快照政策

仓库里同时存在三代架构描述，**只有一代是现行的**：

| 目录 | 基线 | 定位 |
|---|---|---|
| `docs-godot/`（约 40 份） | 2026-09-22 ~ 10-02 | 教程/模块/函数索引，**未被 Git 跟踪**，不得作为引用来源 |
| `architecture/01`–`10` + `ARCHITECTURE.md` | `42b5b1c`，2026-09-20 | 迁移前历史快照。文件头已声明行号、节点名、`preview_style.gd` 等描述不代表当前实现 |
| [`docs/architecture.md`](architecture.md) | 当前源码 | **现行唯一架构入口** |

引用历史快照时必须带基线号，且不能把其中的行号、文件数或验证数字当作当前交付证据。历史目录名 `client_godot` 仅作历史语境出现，现行命令一律用 `client-godot`（文档测试会在代码块中拦截旧名）。

## 4. PR #186 五轮审查

PR #186 是把完整 Windows 客户端引入上游的主 PR，经五轮审查。**原文全部归档于 [`archive/worklog/pr-186/`](../../archive/worklog/pr-186/)**，本节只保留可追溯骨架。

| 轮次 | review id | head | base | 结论 | 阻断项 |
|---|---|---|---|---|---|
| R1 | `5267320830` | `92a46bd0` | `b367bb2` | **CHANGES REQUESTED** | N1–N5（P1），另 9 项 P2、7 项 P3 |
| R2 | `5274311665` | `a5e5ed6c` | `cf09483` | **维持 CHANGES** | N2/N3/N4 已修；N1 阶段链恢复但巨型 PR 例外批准仍缺；N5 冷缓存未解决 |
| R3 | `5280367770` | `1bb36b0` | `cf09483` | **无阻断项** | N5 通过定向重试修复（仅匹配主题纹理竞态签名） |
| R4 | `5379250373` | `f1cb9e27` | `114c569e` | **CHANGES REQUESTED** | N22–N24（三个官方入口在该 head 上失败） |
| R5 | `5381572229` | `2ea9870b` | `114c569e` | **未发现阻断项** | N22–N25、N30 已解决；N26–N28 树内已解决；N29 未解决；新增 N31(P2)、N32(P3) |

**规模演进**：R1 首轮为 540 文件 / +34,209 行（2 个提交）；R2 将分支重写为 315 个提交的阶段链；R4 相对 R3 为 692 文件变更（含目录改名 `client_godot/` → `client-godot/`）；R5 为 1 个提交 / 43 文件 / +1050−126。相对上游 `dev` 的累计增量始终是**纯新增客户端目录**，未夹带服务端或旧客户端改动。

**结论衔接**：阻断项在 R5 全部解除。剩余非阻断项为 N31（合并前更新对外叙述）、N32（元测试未接入正式入口）、N29（提交可追溯性）。N1 的巨型 PR 例外批准**仍待负责人确认**；Issue #187–#192 仍为 open。

## 5. N1–N32 整改台账

### 5.1 P1 阻断（N1–N5，R1 提出）

| 项 | 问题 | 处理 | 验证抓手 |
|---|---|---|---|
| N1 | SPEC/Red/Green 阶段链不可核验，540 文件巨型提交无例外批准 | R2 恢复 315 提交阶段链；大型 PR 例外仍待批准 | 提交对象可解析性 |
| N2 | 账号激活后半启动、失败不回滚 | `AccountLifecycle.start(session) -> Error`：先验证 chat transport，失败逆序回滚，可选能力 `ERR_UNAVAILABLE` 不阻断文字聊天 | `tests/application/test_account_lifecycle.gd` |
| N3 | 模型执行器未校验即转发服务端下发的图片 URL/data URI | `model_executor.gd` 走 `Attachment.from_data_uri`：MIME 白名单 png/jpeg/webp、Base64 字符集与往返校验、大小上限 | 非法输入返回明确错误码 |
| N4 | PRD 要求的 `user_typing` 无发送实现 | `ChatSession.set_typing(active, text_length=0) -> Error`，0–4096 瞬态事件；输入变更触发，发送/断线/stop 清理 | websocket runner 校验 payload |
| N5 | 冷缓存首次官方检查必然失败（干净检出/CI 无法一次通过） | `check.ps1` 对**唯一**已知签名（`.ctex` 缺失 + `app_theme.tres` 解析错误）定向重试一次，其他失败直接失败 | 删除 `.godot` 后复跑 |

### 5.2 P2（N6–N14，R1 提出）

N6 动态窗口不清理已删行导致详情缓存增长 → 四态互斥 + `_prune_comments` 释放；N7 动态窗口缺加载/空/失败/未选择状态 → `get_state().phase` 驱动；N8 图片预览仅鼠标可操作 → `image_thumb_button.gd` 焦点环 + Enter/Space；N9 音频缓存崩溃窗口产生永久孤儿 → 临时文件 + 原子重命名；N10 JPEG/WebP 解码后才校验尺寸（解压炸弹）→ 先校验头部尺寸；N11 三个 runner 只查退出码与 `ERROR:`，`FAIL:` 或提前 `quit(0)` 可被宣告 PASS → 判定改为「退出码 0 且 `SCRIPT ERROR` 计数 0」；N12 四组脚本不隔离 `APPDATA` → 强制临时目录；N13 导出目录不清空 + 验证器同源期望 → 先清目录再校验条目；N14 登录态无边框 + 手工拖动与契约冲突 → #190 交回系统标题栏（删 `%CloseLogin`、`%DragArea`），保持 480×690 不可缩放。

### 5.3 P3（N15–N21，R1 提出）

N15 设计系统集中度不足 → 主题语义类型化（见 §9）；N16 日志无单次运行容量上限、运行元数据非原子 → 三参数签名保留 + 显式条数上限 + 原子写；N17 依赖边界检查可被绕过 → 静态检查扩到 9 条；N18 两处测试名实不符 → 改名对齐；N19 原生构建与供应链校验不完整 → `dependencies.lock.json` 锁哈希；N20 原生与平台错误码不可区分 → 分码；N21 其他（含 `DirAccess.rename_absolute` 不覆盖目标的**证伪**：4.7.1/4.7.2 实测 `rename_err=0` 且覆盖成功，残余风险仅「固定 `.tmp` 名并发冲突 + 无 fsync」）。

### 5.4 第四轮整改（N22–N30，R4 提出、R5 确认）

| 项 | 问题 | 处理 |
|---|---|---|
| N22 | 测试调用不存在的 `Image.save_bmp_to_buffer()` | 改为内嵌 70 字节 2×2 24-bit BMP，保留 PNG 归一化、可解码、尺寸、行填充与像素断言 |
| N23 | 共享回复事件夹具随上游同步丢失 | 9 个事件迁入 `tests/fixtures/chat/reply_events.json`，与 `1bb36b0` 逐字节一致（1426 B）；Godot 与旧 Python 真解析器共同消费 |
| N24 | 动态详情阅读位置恢复竞态 | 每条详情保留待恢复目标 → 等请求与布局稳定后钳制应用 → 用户真实滚动取消旧目标；原固定 sleep 改为状态等待并补真实滚动范围断言 |
| N25 | 复杂度门禁未接入任何入口 | 接入 `check.ps1` 基础入口；新增可选 `-Python`；`ImportOnly` 例外、`SkipImport` 不例外；依赖缺失/版本不符/解析失败/超限一律失败 |
| N26 | 版本口径 0.1.4/0.1.5 混用 | 树内统一 0.1.5（后续打包推进至 0.1.5.1/.2/.3） |
| N27 | 目录改名后命令仍写旧名 | 现行命令改为 `client-godot`，旧名只作历史语境 |
| N28 | 自有文档依赖已删除的根 docs 或未跟踪的 `docs-godot` | 现行说明收进 `client-godot/docs/` |
| N29 | 提交信息不可追溯 | **未解决**；改为在 PR 描述按范围列内容与验证入口，不重写已推送历史 |
| N30 | `.import` 行尾噪声 | `.gitattributes` 固定 `*.import text eol=lf`；不批量删除 76 个导入描述、不改全局 Git |

### 5.5 第五轮新增（N31–N32）

- **N31（P2，未解决）**：PR 描述与两份「整改证据」文档仍按未提交口径书写，与当前 head 不符。本文件与归档改造即为消除该类瞬时口径（见 §1）。
- **N32（P3，未解决）**：`tests/test_check_gate.py` 与 `tests/test_review_documentation.py` 两个元测试未接入 `check*.ps1`，仅 `testing.md` 列为独立检查。当前靠人工执行；接入 CI 或正式静态入口是待办。

### 5.6 圈复杂度治理

工具 `scripts/check_complexity.py`，阈值 CC > 10，依赖锁定 gdtoolkit 4.5.0 / lizard 1.24.0 / tree-sitter 0.25.2 / tree-sitter-cpp 0.23.4。三棵树均 0 解析错误、0 路径删除。

| 指标 | `03778516` | `1bb36b0` | `f1cb9e27` |
|---|---|---|---|
| 违规（CC>10） | 122 | **108** | **0** |
| 最高 CC | 44 | 44 | **10** |
| 平均 CC | 3.39 | 3.32 | 2.93 |

典型下降：`tests/ui/test_login_presentation.gd` run 44→7、`tests/run_dynamics_tests.py` do_GET 44→9、`tests/run_websocket_tests.py` handler 40→8、`src/media/reply_audio.gd` append_reply_audio 38→10、`src/session/history_sync.gd` _load 35→10、`native/pcm_stream_decoder.cpp` append 27→9。共同单元中仅 3 处上升且全部 ≤10。详细三树对比见 [归档补充证据](../../archive/worklog/pr-186/comment-5931768270-complexity.md)。

## 6. 消息持久化与 SQLite

**设计文档**（不在本文件重复）：[增量加载 spec](../../docs/开发进程文档/Godot消息增量加载与SQLite持久化-spec.md) 定义范围与验收；[人工实施指南](../../docs/开发进程文档/Godot消息增量加载与SQLite持久化-人工实施指南.md) 为逐文件实施手册。实现已落地，与两份文档的偏离以源码为准。

**链路**：`src/composition/application_services.gd` 造 `sqlite_worker`（独立线程持连接）+ `message_persistence`（门面）；`chat_session` 写实时消息，`history_sync` 写历史页，`history_page_writer` 真正落 SQL。

**库位置**：`%APPDATA%\AgentLuo-Godot\history\<AccountScope.sha256([server,username])>\history.db`，WAL 模式。

**结构**：`history_schema.gd` `VERSION=3`，9 张表 —— `messages`、`send_attempts`、`message_media`、`sync_epochs`、`history_positions`、`cached_ranges`、`history_segments`、`segment_members`、`sync_state`。`timeline_order` 有唯一索引，位置由 `TimelineSlots` 以 2^20 间距分配，冲突时重编号并 bump `order_revision`。

**写语义**：所有写走 `BEGIN IMMEDIATE`。`save_live` 走尾部槽位插入或原位更新（非流式时 500 ms 节流）；`save_history` 在同一事务内写消息 + 位置 + 范围 + 同步进度；`save_reconcile` 只补消息与位置，**不动** `next_end/baseline/caught_up/cached_ranges/history_positions`。`message_media` 表存在但 `save_media()` 当前无调用方。

**读语义**：`timeline_reader` 走 keyset 分页（`read_latest` / `read_before` 锚点），页大小 30，**不用 OFFSET**。

**收口**：`MessagePersistence` 保存 inflight/pending 队列，失败命令留在 pending 由 `flush()` / `retry_pending_writes()` 重试；退出前 `application._request_persisted_close()` 调 `close_persistence()`，失败则提示保存失败并 resume。

**已知坑**：消息正文未加密（明文 SQLite）；关闭/备份必须连 `-wal`/`-shm` 一起处理；重启时 `RECOVER_UNCERTAIN` / `RECOVER_UNSENT` 修正投递态。

**送达不确定时的回补**：`reliable_outbox` → `websocket_transport` → `chat_session._delivery_changed()`（`status == "uncertain"`）→ `history_sync.request_reconcile()`。链路为防抖 1.2 s + 单飞 + `_wanted` 补跑，`initial/catchup/older` 进行中让路。落位规则：库里已有服务器行 → 贴 `MAX(timeline_order)`（tail）；只有本机记录 → 贴 `MIN` 之前（head）。内存侧 `_reconcile_page()` 用「页内已有 id 当锚点 + 游标插入」，已存在 id 只移动游标以保留本地 uncertain 文案。装配上必须给 `HistorySync` 注入**第二个** `history_api`，否则上翻与对账共用 `_generation` 会互相取消。失败一律静默（只记 `history_reconcile` 日志与 `reason`），气泡保持 uncertain。

## 7. 语音链路

**设计文档**：[用户语音消息 spec](../../docs/开发进程文档/用户语音消息-spec.md)（含 UI 验收与状态不变量）。该 spec 明确要求：**若领域命名改变，先更新 `CONTEXT.md` 词汇表再改代码**。

**播放与口型**：`ReplyAudio` 独家裁决声音与口型的归属，`cache_replay` 只是内部接收端。缓存对纯文字聊天可选——缺少重放能力**不得**让 transport 或账号会话启动失败。

**错误分类与去重**（2026-10-01 用户诊断包驱动）：诊断包显示服务端下发 `final=true, audio_error=true` 的空音频尾包，同一回复触发三次 `system_error AUDIO_ERROR`（分别来自展示队列、播放回调、完成后再次展示）。修复为：同 UUID 只提醒一次；`REMOTE_AUDIO_ERROR` 区分远端终止与本地 `AUDIO_ERROR`；诊断新增白名单 `TTS_EMPTY` / `TTS_STREAM_ERROR` / `TTS_CANCELLED` 及脱敏回复标识，不记录任意异常原文或用户音频；失败流不缓存，保留文字与后续播放。回归入口 `tests/session/test_reply_audio_errors.gd` 已纳入基础检查。

**未确认项**：旧诊断包未记录服务端 `error_code` 或 TTS traceback，**无法确定**是超时、TTS 异常还是取消。客户端只修了错误来源表达、重复提示与可追溯性；服务端底层原因须取同一时段的服务端日志再处理。

**Python→Godot 语音迁移**（只做单向）：

- 字节级兼容：Python 的 `temp/tts_output/<uuid>.wav` 与服务端音频流相同，等于 `audio/<scope>/<sha256(uuid)>.audio` 的内容，无需转码。
- 唯一缺口：`AudioCache.lookup()` 必须有 `<sha256(uuid)>.json` manifest（version=1、rate 8000–192000、channels 1/2、bits 8/16/24/32、frames>0、bytes==文件长且 ≥44、waveform 24 个 0..1），Python 端不写。
- `wav_metadata.gd`：纯 RIFF 解析（rate/channels/bits/frames/data_offset）+ 24 桶 RMS 波形。`data` 声明长度超文件判 `TRUNCATED_AUDIO`，仅 0/0xFFFFFFFF 才用文件尾兜底；`_tag()` 过滤不可打印字节，否则 `String.chr(0)` 会抛 Unicode NUL 错误。
- `audio_import.gd`：成对原子写（`.part`→`.audio`、`.json.tmp`→`.json`）；幂等 —— `<stem>.json` 存在 → `ALREADY_CACHED`，`.part` 存在 → `STREAM_ACTIVE`；源文件只读、保留 mtime。波形优先用原生 `PcmStreamDecoder`，缺席退回 `Wav.waveform`。
- `audio_migration.gd` 实现 `audio_migration_port.gd`：线程 + semaphore + `_process` 里 `_drain()`（仿 `sqlite_worker`）。bulk 成功后写 `<audio_root>/migration/<scope>.json` 标记并置 `_bulk_done` 让增量短路；清缓存后 `cached_count==0` 使标记失效自动退回增量；bulk 有失败不写标记（`code="PARTIAL"`），失败项留待翻页重试。
- 接线：`application_services` 建 `audio_migration` 并 `imported.connect(chat.refresh_message_audio)`；`chat_session._restore_page` / `_history_page` 末尾调 `_request_missing_audio()`（只转 assistant 的 id，后台 catchup 页不触发）；`reply_audio.forget_audio()` 仅丢内存缓存并通知界面。
- 反向（Godot→Python）不做：manifest 不含 `reply_id`，只能遍历 messages 做 sha256 反查，成本与收益不匹配。

## 8. 动态与未读语义（现行 = 纯客户端本地生效）

**这是本文件唯一保留的版本。2026-11-08 记录的「服务端 `before` 精确已读」方案已整体回退。**

- 决策：用户明确「不需要跑服务端，不要更改服务端的代码」。先前留在 `server/` 的 5 个未提交文件已 `git checkout` 回 HEAD，`git status -- server` 为空。**已废弃，不再执行。**
- 为什么客户端必须跟着改：旧服务端 `DynamicReadMarkRequest` 只认 `username` / `token`，body 里多带的 `before` 会被忽略并直接执行「全部已读」，且回包没有 `unread_count`，客户端会判 `INVALID_RESPONSE` 回滚并弹「未读操作失败」。
- `src/session/dynamics_controller.gd`：`mark_read(before)` 拆两路 —— **空** = `_mark_all_read()`（发 `/dynamics/read`、`unread=0`、`_read_last_read`）；**非空** = 纯本地推进 `_state.last_read` + `_clear_latest_unread()` + `changed.emit()`，不发请求。已删除 `_can_advance` / `_read_payload` / `_optimistic_read` / `_finish_read`。
- `_unread_preview()` 的基线由回包 `last_read_dynamic_at` 改为 `_state.last_read`；否则 30 秒轮询会把刚点开的动态又塞回预览卡片。
- **已知代价（用户已接受）**：本次运行内圆点消退但徽标数字不降；重启或换设备后未读恢复。
- 测试口径：`test_dynamics.gd` 断言「点开后不再未读 + 徽标仍 123」；`run_dynamics_tests.py` 的 `reply_read` 退回旧服务端行为（忽略额外字段、只全量已读、回包无 `unread_count`），若客户端再发 `before` 会直接失败；`test_dynamics_review_actions.gd` 的替身 `mark_read` 不再归零徽标，断言改 `state.unread == 1`。

## 9. UI 主题、动效与图标

**主题语义化**（#191）：`theme/app_theme.tres` 去重 56→40 个 `sub_resource`，引入语义类型 `ChatSurface` / `ChatComposer` / `DynamicsSurface` / `DynamicsDetailSurface` / `DropdownItem` / `DynamicInput` / `MessageBubbleOwn` / `MessageBubbleOther` / `MessageTimeChip` / `TerminalPanel` / `ImageEntry`，并统一六态 `ControlNormal` / `Hover` / `Pressed` / `Disabled` / `Focus`。契约测试覆盖五态且断言**同类控件同态共用一个实例**——按名断言，改主题类型名会直接红。

**双轴外观**：`flat` / `crystal`（中文文案「扁平」/「清透」）与 `svg` / `emoji`。这两个值已持久化进设置（`ui_style.gd` 的 `SECTION = "ui"`），**改名需要迁移**。`is_crystal()` 是全仓最热的样式判断点。

**图标与导航**：导航按钮统一 64×64；节点→图标映射按**图标语义**而非节点名（`NavDynamics` 用 @、`NavLogs` 用卷宗），代码中以 `NAV_ICONS` 常量承载，不再内联字面量。

**动效现状（必须如实记录）**：动效方案（[已归档](../../archive/worklog/design/ui-motion-plan.md)）设计的统一工具类 `src/ui/ui_motion.gd` **从未落地**，全仓无 `UiMotion` 引用。当前实际只有 `src/avatar/touch_ripple.gd` 等零星 `create_tween` 使用，其余状态切换仍是 `visible` 瞬变。归档方案里的 P0「已完成」清单不可信，只能当作设计意图参考。

**性能红线（若重启动效工作，仍需遵守）**：

1. 只动 `modulate` / `position` / `scale` / `rotation`；**不改** `size`、`custom_minimum_size`，不做显隐切换 —— 会触发布局重排。
2. 列表项入场必须做「新到达才播」门控；滚动历史与虚拟列表复用节点时**不播**。
3. 循环动画（spin/pulse/floaty）在节点隐藏或状态结束时必须 kill 并复位，否则泄漏、节点释放后报错。

**三个已踩过的实现坑**：

- `%UniqueName` 只认场景里标了 `unique_name_in_owner = true` 的节点；未标的要用 `get_node("...")`。
- `ui_style.gd _apply_theme()` 会重建主题面板样式，**覆盖**运行时 `add_theme_stylebox_override` 的结果。样式放主题资源里改是正解，或把该面板类型加进 `_apply_panel_themes()` 适配列表。
- tween 与容器冲突：对 BoxContainer 管理的子节点做 `position` 动画，容器下一帧会排回去（虚拟消息列表每帧 `_render()` 重排）。所以气泡入场**只用 `modulate` 淡入**，不用位移。

## 10. 构建与发布

**命令**：

```powershell
scripts/build.ps1 -Godot <godot.exe> -Version 0.1.5.3 -OutputDirectory <目标>
```

- `-Version` **必须显式传**，否则脚本走 `Read-Host` 交互，非交互执行会挂死。
- 流程：`--import` → `--export-release "Windows Desktop"` → 导出产物 `--headless --quit-after 3` 自检 → 校验 zip 条目数与长度 → 目录与 zip 原子发布。
- 脚本副作用：回写 `release.json` / `project.godot` / `export_presets.cfg` 三处版本。

**产物结构**：`agentluo.exe` + `agentluo.pck` + `libgdsqlite.*.dll` + `libgd_cubism.*.dll` + `windows_security.dll` + `licenses/` + `PREVIEW.md` + `release.json`（共 15 条目）。

**两次工具修正**：

1. `tests/verify_release_archive.py` 的 `DLL_FILES` 曾写死 2 个 DLL，产物早已有 `libgdsqlite` → 改为 3 项并各自指向锁文件字段（`godot_sqlite.windows_release_sha256`）；同步修正 `ARCHITECTURE.md`、`architecture/09-build-and-release.md` 里「两个 DLL」的说法。
2. 该脚本只认 `dist/<name>` 布局（要同级 `dependencies.lock.json`）；导出到任意目录时用 `v._lock_for = lambda s: lock` 打补丁再跑。

**校验链**：`Resolve-Godot` 强校验 `--version` 等于 `dependencies.lock.json.engine.version_output`，并对 GUI exe 做 SHA-256 比对（传 `*_console.exe` 时会自动找同级 GUI exe 验哈希）。

## 11. 质量门禁

| 入口 | 覆盖 | 说明 |
|---|---|---|
| `scripts/check.ps1` | 冷导入（含已知竞态定向重试）+ 复杂度门禁 + 30 余项契约脚本 + 启动自检 | 基础入口，最慢 |
| `scripts/check_accounts.ps1` | 真实 Python 解密互操作 + 账户脚本 + 依赖边界 9/9 | 需 Python 环境 |
| `scripts/check_network.ps1` | 4 个 WebSocket 场景：transport、live text chat、voice chat、**touch delivery** | 直接覆盖 §13.1 的 wire key |
| `scripts/check_features.ps1` | 动态详情/阅读位置/历史分页/偏好/模型卡/草稿/登出确认 | — |
| `scripts/check_complexity.py` | CC ≤ 10、0 解析错误 | 可独立跑 |
| `tests/test_dependency_boundaries.py` | 9 条分层边界（如 `session`/`ui` 禁 `FileAccess`） | 纯静态 |
| `tests/test_check_gate.py`、`tests/test_review_documentation.py`、`tests/test_build_prompt.py` | 门禁编排语义、文档链接/版本/行尾、构建 `-Version` 语义 | **尚未接入正式入口**（N32） |

**不写死文件数与单元数**：各次运行的 `N files / M units` 随新增测试变化（历史值从 195/1624 到 252/2941 都出现过），以当次输出为准；**稳定口径是「0 violations / 0 parse errors」**。

**四条环境陷阱**（都实际踩过）：

1. **PowerShell 5.1** 的 `ProcessStartInfo.EnvironmentVariables` 为 `null`，必须用 `[Environment]::SetEnvironmentVariable`。
2. **gdtoolkit 缺失**时 `check_complexity.py` 刷大量 `PARSE ERROR`，但仍打印 `0 violations`，极易误判为通过 —— 必须用装了 `tests/requirements-complexity.txt` 的解释器。
3. **headless 下 `SceneTree.root.mode` 是 `MINIMIZED`**，图片窗口测试必须用场景里的 Window 作 source，否则被 `_process` 隐藏。
4. **假通过**：断言全绿但日志里有 `SCRIPT ERROR`（例如假 history 漏 `reconciled` 信号会让 `_init` 中断而断言仍通过）。**判定通过 = 退出码 0 且 `SCRIPT ERROR` 计数 0。**

## 12. 诊断记录：2026-10-28 桌面卡顿

原文见 [归档](../../archive/worklog/diagnostics/display-stutter-20261028-090718-findings.md)。

- **结论与边界**：证据指向 Windows 桌面合成与 NVIDIA 显示驱动之间的呈现/同步状态异常。**未证明**缺陷位于 MPO、独立翻转、驱动电源管理或某个应用交互代码中，不得表述为「已确认 MPO 故障」。NVIDIA Overlay 当时未运行；游戏 `javaw.exe`（PID 32024）从 08:30:05 一直运行到恢复之后，用户确认采样中途恢复且未退出游戏 —— 所以「重启 Overlay 后恢复」只能证明那次操作有效，不是唯一根因证据。
- **关键数值**：卡顿期 CPU 十秒均值 3.57%、可用内存约 20,224 MiB、系统盘 I/O ≈0.11 ms，无资源饱和；`DwmFlush` 中位 31.11–31.36 ms（95 分位 45.54 ms），恢复后同法采样中位 6.04–6.06 ms（95 分位 6.3 ms）。GPU 从 P8 到 P0，未见温度/功耗限频。
- **重要限制**：启动 GPU 诊断本身会干预显示调度与硬件叠加状态，是这次恢复的合理解释，但时间相关性不等于因果。
- **后续方向**：先针对 NVIDIA 驱动与桌面呈现路径排查，优先评估更新到适配该机与 Windows 版本的稳定驱动；仍复发再单独做 MPO 禁用/恢复的受控对照。**不要同时改驱动、MPO、HAGS 多项设置。**
- 本次未修改驱动、注册表、显示配置、游戏配置或启动项；WPR 已停止。

## 13. 命名与术语约定

### 13.1 现行约定

| 层面 | 约定 | 示例 |
|---|---|---|
| 文件名 / 变量 / 函数 | `snake_case` | `history_page_writer.gd`、`_sync_details()` |
| 类 / preload 常量（当类型用） | `PascalCase` | `const Services = preload(...)` |
| 其他常量 | `SCREAMING_SNAKE` | `const MAX_COUNT := 100` |
| wire payload key | `snake_case` | `touch_area`、`client_msg_id` |
| 数据库列 | `snake_case` | `timeline_order`、`ever_sent` |
| 设置存储 | `section` + `key` | `ui` / `style` = `flat` |

**领域术语表是 [`CONTEXT.md`](../../CONTEXT.md)**，采用「术语 + _避免称为_」结构，明确禁止同义替换（语音录制 / 录音提交中 / 语音条 / 音频描述 / 录音协调信号 等）。**改领域命名必须先改词汇表再改代码** —— 这是语音 spec 的明文要求。

### 13.2 已知遗留漂移（登记，不改）

| 漂移 | 说明 | 为何不改 |
|---|---|---|
| `dynamic_detail.gd`、`dynamic_comment_row.gd` vs `dynamics_window.gd`、`dynamics_post_row.gd` | 同名实体单复数并存 | 改名要同步 4 个 `.import` / `.uid` / `.tscn` ExtResource 与多处 `preload`，且不改变行为 |
| `set_unread_dynamic(...)` | 单数 | 与上同源；属 API 名，测试与调用方散布 |
| `unread_dynamic_count` | 单数 | **这是服务端回包字段**，不是本地命名，不能单方面改 |
| `crystal` / `frost` | 清透外观的英文代号 | `crystal` 已持久化为设置值，改名需迁移；`frost` 指毛玻璃 shader，属通用 UI 术语 |
| `ever_sent` | DB 列 | 改名需 SQLite 迁移 + `user_version` bump |
| `*_window` / `*_page` / `*_overlay` | 同类弹层三种后缀 | 后缀反映容器类型（Window / Control 页 / Control 覆盖层），有语义 |

### 13.3 改名同步清单（任何一项改名都要走完对应行）

| 改什么 | 必须同步 |
|---|---|
| wire payload key | `docs/服务端接口-WebSocket.md` + `tests/run_websocket_tests.py` + `tests/avatar/test_touch_delivery.gd` + `tests/run_client_behavior_comparison.gd` + 旧 web/cli 客户端 |
| `.gd` 文件名 | 同名 `.uid`、`.import`（若为资源）、`.tscn` 的 `ext_resource`、所有 `preload("res://...")`、`export_presets` 引用、`docs/` 与 `architecture/` 中的链接 |
| DB 列名 | `history_schema.gd` 的建表与全部 SQL + 迁移函数 + `user_version` bump + `test_sqlite_database.gd` |
| 持久化设置值 | 读取处加旧值兼容分支（`ui_style.gd` 的 `style in [...]` 判断 + `configure()` 的兜底） |
| 主题类型名 | `theme/app_theme.tres` + `ui_style.gd` 的 `_apply_panel_themes()` + `tests/test_theme_contract.gd`（按名断言） |

## 14. 待办与陈旧文档

**当前工作树已知红灯（`feat/sqlite-test` 未提交改动引入，待修复）**

- `check_complexity.py` 报 4 处超限，全部落在尚未提交的语音迁移文件：`src/storage/audio_migration.gd` 的 `request_ids` CC=14、`src/storage/wav_metadata.gd` 的 `describe` CC=14 / `waveform` CC=15 / `_scan_chunks` CC=17。修复前 `check.ps1` 会在复杂度门禁处直接失败（解析错误为 0，不是工具环境问题）。
- `tests/test_voice_chat.gd` 的「clear cache requires confirmation」在同树上**稳定失败**（非偶发），由音频迁移改动引入，与命名/注释清理无关。修复后 `check_network.ps1` 才能恢复全绿。

**代码与流程层**

- N1 巨型 PR 例外批准仍待负责人确认；Issue #187–#192 仍 open（#187/#188 动态四态、#189 图片键盘可访问性、#190 登录窗回退系统标题栏、#191 主题语义化、#192 待确认）。
- N29 提交可追溯性：`2ea9870b`「修复了一些bug」同时承载阻断修复、行为修复、门禁接线、夹具迁移与文档整理。
- N32 两个元测试未接入正式入口。
- 服务端 TTS 根因未定位（需同一时段服务端日志）。
- 服务端 pytest 在本机无 fastapi/sqlalchemy 环境时**未执行**，只做过 `py_compile`；不要把它当作已通过。
- 未验收边界：公共服务器、真实系统 DPI、多屏、Windows 10、集显、长期运行、移动端。

**文档层**

- [`../../docs/TODO.md`](../../docs/TODO.md) 仍是权威路线图，但**落后于实际进度**：v0.5.0 的「桌面膜录制并发送语音」等项已落地却未勾选。远期项目（World / LuoCamera / Doll / Infinite）不在本仓交付范围，仅在该文件维护。
- 变更记录曾分散在三处：根 README 的更新日志、`client/changelog.md`、`release.json`。已由 §2 统一；后续以 §2 与 `release.json` 为准。
- 曾存在的 `docs-godot/`（约 40 份）未被 Git 跟踪且部分内容已过时，**不再作为引用来源**（见 §3）。
- 归档的动效方案含两处失效信息：`ui_motion.gd` 从未落地、Godot 4.7.2 非交付口径（见 §9）。

## 15. 归档索引

原始记录全部位于 [`archive/worklog/`](../../archive/worklog/)，索引与「为何归档而非删除」的说明见其 [README](../../archive/worklog/README.md)。

| 原文 | 归档位置 | 去向 |
|---|---|---|
| PR #186 第一轮审查（`92a46bd0`） | [review-5267320830-round1.md](../../archive/worklog/pr-186/review-5267320830-round1.md) | §4、§5.1–§5.3 |
| 第二轮复审（`a5e5ed6c`） | [review-5274311665-round2.md](../../archive/worklog/pr-186/review-5274311665-round2.md) | §4、§5.1 |
| 第三轮复审（`1bb36b0`） | [review-5280367770-round3.md](../../archive/worklog/pr-186/review-5280367770-round3.md) | §4 |
| 第四轮审查（`f1cb9e27`） | [review-5379250373-round4.md](../../archive/worklog/pr-186/review-5379250373-round4.md) | §4、§5.4 |
| 第五轮复审（`2ea9870b`） | [review-5381572229-round5.md](../../archive/worklog/pr-186/review-5381572229-round5.md) | §4、§5.5 |
| 圈复杂度三树对比补充证据 | [comment-5931768270-complexity.md](../../archive/worklog/pr-186/comment-5931768270-complexity.md) | §5.6 |
| 作者侧第四轮整改自述与验证状态 | [review-186-4th-round.md](../../archive/worklog/pr-186/review-186-4th-round.md) | §4、§5.4、§7 |
| PR 描述草稿与逐项回复 | [pr-186-response-draft.md](../../archive/worklog/pr-186/pr-186-response-draft.md) | §5.4、§14 |
| 2026-10-28 桌面卡顿诊断 | [display-stutter-20261028-090718-findings.md](../../archive/worklog/diagnostics/display-stutter-20261028-090718-findings.md) | §12 |
| 2026-10-02 动效交接方案 | [ui-motion-plan.md](../../archive/worklog/design/ui-motion-plan.md) | §9 |

**就地保留**（Agent 系统按日期读取，不移动）：`2026-11-08.md`、`2026-11-09.md`（位于工作区 `.workbuddy/memory/`，文末已加指向本文件的指针）。

**相关现行文档**：[现行架构](architecture.md) · [测试与门禁](testing.md) · [测试目录](../tests/README.md) · [构建与使用](../README.md) · [包内说明](../PREVIEW.md) · [项目路线图](../../docs/TODO.md)
