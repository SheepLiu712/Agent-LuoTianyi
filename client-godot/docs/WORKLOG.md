# Godot 客户端开发工作记录

本文件是 Agent-LuoTianyi Godot 客户端（`client-godot/`）**唯一的工作记录汇总**，由 2026-09 至 2026-11 期间散落的开发日志、五轮 PR 审查、整改自述、专项诊断、重构取舍与全量排查记录合并而成。

---

## 1. 文档定位与维护规则

- **本文件是记录，不是契约**。行为以源码与针对性测试为准，架构以 [现行架构](architecture.md) 为准，门禁以 [测试与门禁](testing.md) 为准。
- 冲突裁决顺序：源码/测试 > `architecture.md` > 本文件 > 归档原文。归档原文中已被后续推翻的结论**不会**在本文件重复。
- `client-godot/docs/*` 已被 `export_presets.cfg` 的 `docs/*` 排除，**不随便携包分发**。
- 新增记录只在本文件对应小节追加，并同步 §16 归档索引；不修改已归档原文。
- 不记录瞬时状态（"尚未提交""HEAD 仍是基线"之类），这类信息在 10 月的两份文档里已造成过审查歧义（见 §15 N31）。
- 2026-11-10 的全量排查与两轮重构取舍已分别并入 §12、§7.1、§11.1；原 `audit-2026-11-10.md` 与 `conflicts.md` 已删除，**不再恢复独立副本**，避免同一结论多份漂移。

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
| **0.1.5.3** | Godot 客户端 | 该阶段版本；`agentluo.exe` 109,199,872 B + `agentluo.pck` 6,144,764 B + 3 个 DLL；ZIP 45,132,399 B / 15 条目 / sha256 `4497c7a4…` | 同上 |
| **0.1.5.7** | Godot 客户端 | 九类日志重构、质量审查与 Python 媒体导入；多次构建用于回归与单文件版验证 | 本文件 §7、§8 |
| **0.1.6** | Godot 客户端 | 首个 0.1.6 便携包；包含 Python 媒体导入、九类日志与目录整理 | `dist/agentluo-0.1.6/`、`artifacts/agentluo-0.1.6.zip` |
| **0.1.6.2** | Godot 客户端 | 聊天审阅图落地；动态滚动分页与点击刷新；发布浮层、文案与文字选区调整；0.1.6.2 包已生成 | `client-godot/README.md`、`release.json` |

**引擎口径**：目标 4.7.x；**交付与门禁锁定 `4.7.1.stable.official.a13da4feb`**（见 `dependencies.lock.json`，并对 GUI 可执行文件做 SHA-256 校验）。4.7.2 只在两处出现过，均非交付口径：动效方案作者的本机二进制（已归档），以及第 1 轮审查对 `rename_absolute` 做的 4.7.1/4.7.2 双版本对照实验。

## 3. 架构快照政策

仓库里同时存在三代架构描述，**只有一代是现行的**：

| 目录 | 基线 | 定位 |
|---|---|---|
| `docs-godot/`（38 份） | 2026-09-22 ~ 10-02（`f1cb9e2`） | 教程/模块/函数索引，已纳入 Git，但内容未随 0.1.6.x 同步；仅作历史参考，**不作为现行行为依据** |
| `architecture/01`–`10` + `ARCHITECTURE.md` | `42b5b1c`，2026-09-20 | 迁移前历史快照，已于 2026-11-10 删除；仅保留 Git 历史，不再作为工作区文档 |
| [`docs/architecture.md`](architecture.md) | 当前源码 | **现行唯一架构入口** |

历史快照目录已移除；如需追溯，使用 `git log -- client-godot/architecture` 与对应提交。历史目录名 `client_godot` 仅作历史语境出现，现行命令一律用 `client-godot`（文档测试会在代码块中拦截旧名）。

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

**Python→Godot 媒体导入**（只读、单向）：

- 字节级兼容：Python 的 `temp/tts_output/<uuid>.wav` 与服务端音频流相同，等于 `audio/<scope>/<sha256(uuid)>.audio` 的内容，无需转码。
- 唯一缺口：`AudioCache.lookup()` 必须有 `<sha256(uuid)>.json` manifest（version=1、rate 8000–192000、channels 1/2、bits 8/16/24/32、frames>0、bytes==文件长且 ≥44、waveform 24 个 0..1），Python 端不写。
- `wav_metadata.gd`：纯 RIFF 解析（rate/channels/bits/frames/data_offset）+ 24 桶 RMS 波形。`data` 声明长度超文件判 `TRUNCATED_AUDIO`，仅 0/0xFFFFFFFF 才用文件尾兜底；`_tag()` 过滤不可打印字节，否则 `String.chr(0)` 会抛 Unicode NUL 错误。
- `audio_import.gd`：成对原子写（`.part`→`.audio`、`.json.tmp`→`.json`）；幂等 —— `<stem>.json` 存在 → `ALREADY_CACHED`，`.part` 存在 → `STREAM_ACTIVE`；源文件只读、保留 mtime。波形优先用原生 `PcmStreamDecoder`，缺席退回 `Wav.waveform`。
- `python_client_locator.gd`：用户选择 Python exe（或目录）后，以 `config/config.json` 的 Live2D 模型路径或 `temp/user.json` + `temp/` 作为稳定指纹，定位 `temp/tts_output` 与 `temp/images`；只读账号的 `username/server_url`，不解密 token，也不自动扫盘猜目录。
- `image_import.gd` + `history_image_codec.gd`：只导入 UUID 命名的 PNG/JPEG/WebP，沿用 16MB/8192 边长/1600 万像素限制与 `.tmp`→rename 原子写；`.gif`、发送副本与损坏文件跳过。`history_images` 在缓存未命中、联网之前，先查所选目录并按需复制。
- `python_media_migration.gd` 实现 `python_media_migration_port.gd`：单线程 + semaphore + `_process` 里 `_drain()`，一个任务队列同时处理语音与图片。bulk 成功后写 `<audio_root>/migration/<scope>.json` 标记（含 `source_hash`）并置 `_bulk_done` 让增量短路；换源或清缓存都会使标记失效；bulk 有失败不写标记（`code="PARTIAL"`），失败项留待翻页/翻图重试。
- 接线：`application_services` 建 `python_media_migration`，注入音频目录、图片目录、设置存储与当前账号作用域；`imported(kind, ids)` 分别转给 `chat.refresh_message_audio()` / `refresh_message_images()`。`chat_session._restore_page` / `_history_page` 末尾调 `_request_missing_audio()`（只转 assistant 的 id，后台 catchup 页不触发）；`reply_audio.forget_audio()` 仅丢内存缓存并通知界面。
- 选择路径持久化在 `user://window_layout.cfg` 的 `[migration] python_client_path`，打开“缓存与导入”页时才重新校验；启动不阻塞、不弹窗。账号/服务器不一致只提示，用户确认后仍写入当前账号缓存。
- 反向（Godot→Python）不做：manifest 不含 `reply_id`，只能遍历 messages 做 sha256 反查，成本与收益不匹配。

### 7.1 九类日志重构的冲突与取舍（2026-11-10）

以下为日志重构落地时记录的实际冲突与取舍。现行规范以 [日志规范](logging.md) 和源码为准，本节只解释“为什么这样定”。

1. **工作区已有大量无关改动**：执行前 `git status` 显示约 544 个 `client-godot` 文件已修改（行尾、资源 JSON、Live2D 与插件），不是本次日志重构产生的。本次只改日志相关源码、测试、主题、场景与文档，没有回滚或重排既有改动。
2. **单条日志变大**：新条目增加 `run_id`、`seq`、`category` 及分类必填字段，单条约 330–350 字节；旧的 512/260 字节上限断言不再成立。保留上限语义，测试上限改为 2048/600 字节；生产上限为 8 MiB / 5 万条 / 50 次。
3. **引擎错误原文与隐私策略**：旧测试要求“引擎警告不保留原始文本”；用户选择“原文保留 + 凭证正文脱敏”。`engine_log_sink` 写入 `detail` 与 `stack`，测试改为断言原始详情存在，同时继续断言 token/正文/Base64 不落盘。
4. **音频分片事件改为 DEBUG**：`audio_received`、`audio_format`、`audio_decoded` 属高频诊断，归入 `debug`；默认关闭后普通日志不再包含。音频测试显式 `set_debug_enabled(true)`，生产排障需 `--debug-log`；`audio_receive_finished`、播放开始/结束仍在 `info`，错误仍在 `error`。
5. **`cache_committed` 的归类**：该事件既是业务里程碑也是文件原子写完成。按“事务日志覆盖文件原子写”的决策，改写入 `transaction_file`（`operation=cache_commit`），不再单独写 `info_cache_committed`；需要业务统计时从 `transaction_file` 过滤。
6. **SQLite 影响行数不可得**：当前 `godot-sqlite` 插件未暴露 affected rows API。`transaction_sqlite` 记录 `transaction_id/scope/operation/phase/outcome/duration_ms/trace_id`，`affected_rows` 作为可选字段保留但未填充。
7. **音频导入事务的落点**：`audio_import.gd` 是静态工具，注入 logger 会扩散到多个静态调用点。改在 `audio_migration._drain()` 主线程按导入结果写 `transaction_file(operation=audio_import)`；`audio_cache.commit()` 单独记录 `cache_commit`。
8. **访问/安全日志注入 logger**：`json_request`、`account_api`、`history_api`、`websocket_transport`、`account_session`、`credential_store`、`model_store`、`sqlite_worker` 新增可选 logger 参数；旧构造方式仍可工作（logger 为空时不写日志）。`application_services` 统一注入同一个 `ClientLog`。
9. **事务标签由调用方提供**：`sqlite_access.transaction(action, label="")` 新增可选操作名；`history_page_writer` 与 `history_migration` 传入 `save_live/save_page/save_reconcile/update_attempt/migrate`；未传时记录为 `unknown`。
10. **原生崩溃处理器未实现**：按决策不引入 Windows native crash handler。硬崩溃靠“引擎 Logger 捕获脚本/着色器错误 + 下次启动扫描 `closed=false` 且进程不存在的 run 写 `runtime_previous_incomplete`”兜底。
11. **UI 访问日志去重**：`window_coordinator.open()` 记录设置/动态窗口的 `access_ui`；`application` 只记录聊天、日志等直接导航，避免同一打开动作写两条。关闭动作由 `window_coordinator` 写 `runtime_window`，`application._request_close` 只记录主窗关闭请求。
12. **独立测试环境限制**：`test_history_media.gd`、`test_account_api.gd`、`test_account_session.gd` 依赖 `GODOT_TEST_SERVER` 本地 fixture 或 `WindowsSecurity`；未启动 fixture 时 `test_history_media` 会等待网络超时，当时未单独判为失败。WSL 的 `binfmt_misc/WSLInterop` 偶发失效，需重新注册后重跑，属环境问题。
13. **旧事件名兼容**：`ClientLog.record()` 仍接受旧事件名，并通过 `LEGACY_ALIASES` 推导分类和中文说明；部分旧测试继续使用旧名作为兼容证据，新代码与新增测试使用 `<category>_<domain>_<action>`。
14. **性能采样范围**：桌面端每 30 秒写 `performance_sample`（内存/对象/绘制调用/FPS）与 `performance_queue`（SQLite 队列、未保存消息），并汇总上一条采样以来的 HTTP 访问为 `performance_http_summary`；headless 测试不启动定时器，避免固定条数断言被后台采样干扰。
15. **当时未完成的既有检查**：`test_review_documentation.py` 的版本头断言曾因 `release.json` 为 0.1.5.7、`PREVIEW.md` 仍写 0.1.5.3 而失败，已同步标题；`check_complexity.py` 在缺 `gdtoolkit` 的环境会把 231 个 GDScript 单元报成解析错误，不能据此判断复杂度；`test_application_window.gd`/`test_application_drafts.gd` 缺本地 HTTP fixture 时会出现既有 URL 解析与 SQLite 空连接错误。
16. **当时验证结果**：通过日志 schema/核心/集成/窗口、SQLite 事务、默认用户存储、UI 场景、主题契约、音频混音与错误恢复、文档检查、依赖边界检查；未完成账号/WebSocket/历史媒体/应用窗口等需本地 HTTP/WebSocket fixture 的项目，`test_build_prompt.py` 与 `test_check_gate.py` 当时因环境跳过，未作为交付证据。

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
| `scripts/check_network.ps1` | 4 个 WebSocket 场景：transport、live text chat、voice chat、**touch delivery** | 直接覆盖 §14.1 的 wire key |
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

### 11.1 质量审查与复杂度治理的取舍（2026-11-10）

**审查范围**：`client-godot/src` 下 126 个 GDScript、`tests` 下 97 个 GDScript；质量门禁为锁定的 gdtoolkit 4.5.0 + `scripts/check_complexity.py`，上限 CC=10；重点为日志 schema/管道、网络请求、账号与凭证、SQLite/文件存储、音频媒体、应用装配与日志窗口。行为基线是现有业务测试、日志专项测试、UI 场景/主题测试与音频链路测试。

**基线问题与处理**：初次门禁 15 个 CC>10 违规，逐项拆分如下；最终门禁为 `266 files, 3354 units, 0 violations, 0 parse errors`。

| 位置 | 基线 CC | 处理 |
|---|---:|---|
| `application._restore_settings` | 11 | 拆出比例/音量解析与数值校验 |
| `websocket_transport._process` | 11 | 拆出重连、超时、心跳、音频 flush 的 tick 函数 |
| `websocket_transport._receive_packets` | 12 | 拆出收包条件、解析、音频识别与记账 |
| `client_log.record` | 12 | 拆出写入提交与失败处理 |
| `client_log._apply_fields` | 13 | 拆出 metrics、字符串字段、payload 三组 |
| `client_log._normalize_entry` | 11 | 拆出 trace/transaction 与 runtime 归一化 |
| `credential_store.save` | 13 | 拆出加密写入与失败记录 |
| `log_schema._elevated_level` | 11 | 按 access/security/performance/transaction/runtime 拆分 |
| `log_schema.sanitize_data` | 13 | 拆出键校验、标量判断、标量清洗 |
| `model_store.save` | 11 | 拆出输入校验与临时文件清理 |
| 5 个日志测试函数 | 11–14 | 按场景拆成多个断言函数 |

**主要改动**：

- 新增 `src/storage/log_events.gd`，集中生成 HTTP/WS/UI 访问、安全认证/凭证、文件事务日志的字段形状；`json_request`、`account_api`、`history_api`、`history_images`、`websocket_transport`、`audio_cache`、`audio_migration`、`credential_store`、`model_store`、`account_session`、`application`、`window_coordinator` 同步改用，消除 10 余处重复拼接。
- 拆分协议 tick/收包、日志写入/归一化、凭证写入、模型配置保存等长函数，让每个函数只处理一个决策层，异常与正常路径可独立测试。
- 清理死代码：`ClientLog._module`、未使用的 `CATEGORIES/CATEGORY_LABELS`，`log_schema` 的 `LEVEL_RANK`/`COMMON_FIELDS`/`ARRAY_FIELDS`/`DICT_FIELDS`/`hash_id` 与未发射事件注册，`history_schema` 无引用 SQL 常量、`sqlite_history_database.OPERATIONS`、`profile_page.NO_ACCOUNT_TEXT`。
- 日志测试按“目录/级别/脱敏/缺失字段/调试/线程安全/旧归档”拆分断言；`test_log_integration` 改为直接测试 `LogEvents.http`，不再依赖已删除的 `JsonRequest._log_access`。

**未合并项与理由**：

1. **不统一各存储层的结果字典**：`sqlite_access`、`sqlite_history_database`、`message_persistence` 各自的结果构造器形状相同但错误码和语义归属不同，抽成全局工具会把层间依赖变成横向耦合。
2. **不统一 HTTP 响应解析**：`json_request` 接受 2xx，`account_api` 只认 200，`history_api` 有独立分页/认证映射与 body 限制；只统一访问日志与 HTTP method 映射，不合并响应解析。
3. **不抽象所有 UI 的 `set_ui_style` / `save_changes`**：GDScript 无多重继承，页面表单字段和保存语义差异大，抽象会扩大 UI 回归面。
4. **保留少量开发期诊断**：`avatar_preview.push_error` 与 `desktop_window_host.push_warning` 是平台诊断，不是临时调试输出；源码中未发现 `print`/`printerr` 残留。
5. **保留旧事件别名**：`LEGACY_ALIASES` 让旧 JSONL 归档仍可读，新代码已统一使用规范事件名。
6. **删除未引用的 schema SQL 常量**：`history_schema` 中若干 `UPSERT_SEGMENT`/`INVALIDATE_EPOCH` 等无调用方，已删除；未来迁移需要时按同一模式重新加入。
7. **`log_events` 对 HTTPClient 的轻微依赖**：`method_name()` 使用 `HTTPClient.METHOD_*`；再拆 `http_method.gd` 会增加模块数量，收益不足，保留在日志适配器中。
8. **复杂度工具环境**：项目锁定的 `artifacts/test-env` 内有 gdtoolkit 4.5.0，系统 Python 3.14 未安装；门禁使用锁定解释器，避免用未锁定解析器得出假通过。

**影响与验证**：未改网络协议、SQLite schema、用户数据格式、UI 文案或业务状态机；日志字段形状保持兼容，旧归档仍可读。通过日志 schema/核心/集成/窗口、SQLite 事务、默认用户存储、UI 场景、主题契约、音频混音与音频错误恢复、文档检查、依赖边界检查；复杂度 0 违规、0 解析错误。账号/WebSocket/历史媒体/应用窗口/动态草稿等需本地 fixture 的测试当时未完成（环境缺 `aiohttp`/`websockets`），不能计为通过。

## 12. 2026-11-10 全面排查与优化

本节合并自原 `docs-godot/audit-2026-11-10.md`（原文件已删除）。审计对象是 0.1.6.x 源码；第三方 `addons/`、Live2D 素材和导出产物只检查接口与使用方式，不审计其内部实现。方法为静态阅读 + 定向回归，瞬时工作树状态不入记录。

### 12.1 范围与结论

- 阅读入口、应用装配、账号/聊天/历史/存储/媒体/UI 的关键调用链。
- 对网络并发、SQLite、日志、图片/音频、UI 布局分别做独立审查。
- 对改动范围执行 headless 回归和 loopback WebSocket/HTTP 夹具回归。
- 未执行真实 Windows DPI 切换、多屏、GPU 截图全量比对、Android 真机或公共服务验收。

结论：没有发现可无条件利用的远程代码执行或 SQL 注入；最需要优先处理的是**明文 HTTP 传输认证材料**、**历史同步与发送队列的时序竞争**、**日志归档同步解析造成的启动卡顿**，以及**流式回复期间整表重排**。高价值项已在同日两阶段修复，剩余项见 §12.4 与 §12.6。

### 12.2 项目结构与职责

```text
scenes/*.tscn + src/ui/*.gd
        │ 控件、信号、展示状态
        ▼
src/application.gd / account_lifecycle.gd / window_coordinator.gd
        │ 账号生命周期、窗口复用、退出草稿汇总
        ▼
src/session/*.gd
        │ ChatSession / HistorySync / Dynamics / Model / Preferences
        ▼
src/network/*.gd   src/storage/*.gd   src/media/*.gd   src/avatar/*.gd
        │ HTTP/WS          SQLite/日志/缓存   音频/图片       Live2D
        ▼
src/platform/*.gd + addons/*（Windows 窗口、DPAPI/CNG、PCM、Cubism）
```

**优点**：

- `composition/application_services.gd` 是明确的组装根，业务代码没有普遍使用服务定位器。
- Session 层基本不直接拼 SQL 或访问 `FileAccess`；平台差异集中在 `platform/` 和各类 `*_store` 实现。
- 历史同步、消息持久化、网络传输、媒体播放的职责边界总体清楚，测试夹具也按层组织；账号切换用 `scope`/`generation` 隔离迟到回调。

**结构性问题**：

- `ChatSession`（约 710 行、8 个构造依赖）同时承担发送队列、收包聚合、历史合并、媒体入口和阅读状态，属于典型的上帝对象。
- `application.gd::_ready()` 和 `application_services.gd::mount()` 把启动、窗口、安全门禁、服务装配、设置恢复放在同一段流程里，新增依赖会持续放大构造签名。
- HTTP/JSON/URL 组装至少存在四套实现：`json_request.gd`、`account_api.gd`、`history_api.gd`、`history_images.gd`，错误码、超时和日志口径不一致。

### 12.3 已实施修复台账

位置中的行号是审计时的源码快照；后续改动使行号漂移时，以当前源码和测试为准。

| 级别 | 位置 | 修复内容 | 验证 |
|---|---|---|---|
| P1 | `src/session/chat_session.gd:550` | `restore_page` 改为“历史窗口替换 + 保留本地 pending 消息”，不再 `clear()` 掉等待历史期间发送的消息 | `test_message_reconcile` |
| P1 | `src/session/chat_session.gd:344` | 退出时先把未发送的 `waiting_history` 标记为 `failed/SEND_CANCELLED` 并落库，再清空映射 | `test_message_reconcile`、`test_live_chat` |
| P1 | `src/session/chat_session.gd:526` | 释放待发队列时先检查 `_by_id`，避免历史恢复后空条目下标崩溃 | `test_message_reconcile` |
| P1 | `src/session/history_sync.gd:310` | 首屏失败也释放发送边界，避免之后所有消息永久停在 `waiting_history` | `test_history_paging` |
| P1 | `src/session/history_sync.gd:128` | catchup 运行期间的上翻请求改为排队，避免与共用 fetcher 互相判 `CANCELLED/BUSY` | `test_history_paging` |
| P1 | `src/network/websocket_transport.gd:95` | 心跳增加 pong/最后收包超时；半开 TCP 不再永久停在 `ready` | `test_websocket_transport` |
| P1 | `src/network/websocket_transport.gd:130` | 只有 `auth_error` 才写永久拒绝指纹；认证期普通 `error` 改为重连 | `test_websocket_transport` |
| P1 | `src/storage/client_log.gd:215` | `list_runs` 优先读元数据中的条数/完整性，不再为每次列表逐行解析 8 MiB 归档 | `test_client_log`、`test_log_window` |
| P1 | `src/storage/client_log.gd:478` | 日志文件句柄常驻，去掉每条日志 open/close；保留逐条 flush 的崩溃可见性 | `test_client_log` |
| P1 | `src/ui/virtual_message_list.gd:54` | 去掉每帧遍历气泡高度的 `_process`，改为 `minimum_size_changed` 驱动 | `test_bubble_sizing`、`test_image_bubble_sizing` |
| P2 | `src/session/model_executor.gd:8` | 已完成结果改为 256 条有界缓存，淘汰最旧完成项，不再 4096 条后永久 `MODEL_BUSY` | 新增 `test_model_result_cache` |
| P2 | `src/storage/sqlite_worker.gd:63` | `_accepting` 与关闭哨兵同临界区；关闭后提交立即失败；线程退出结算剩余 Ticket | `test_sqlite_worker` |
| P2 | `src/storage/sqlite_history_database.gd:274` | 建表、scope、`user_version` 纳入同一事务；半成品库按缺失表/列重建 | `test_sqlite_database`、`test_sqlite_migration` |
| P2 | `src/storage/history_schema.gd:147` / `history_page_writer.gd:250` | 历史页更新前校验 `id_source/source/message_type`，服务端页不能覆盖同 UUID 的本地消息 | `test_sqlite_database` |
| P2 | `src/storage/history_page_writer.gd:355` | baseline/head 改用“本页最后一条服务器消息”，而不是“最后一条新插入消息” | `test_sqlite_database`、`test_history_paging` |
| P2 | `src/storage/python_client_locator.gd:83` | `find_image/find_audio` 先校验 UUID，阻断 `../` 路径穿越 | 静态审查 + 现有媒体测试 |
| P2 | `src/storage/history_images.gd:92` / `:107` | 读取缓存前检查文件长度，避免损坏/超大文件先整块读入 | 现有图片测试 |
| P2 | `src/storage/log_schema.gd:354` | 脱敏覆盖 JSON 引号键、`access_token`、`message_token`、`x-api-key` 等形态 | `test_log_schema` |
| P2 | `scenes/ui/account_view.tscn:346` | 登录历史弹层 `ScrollContainer` 改为四边 8px 内缩，移除右侧越界 | `test_login_presentation` |
| P2 | `src/platform/desktop_window_host.gd:59` | `min_size` 按当前屏幕可用区收缩，避免高 DPI/小屏把底栏顶出屏幕 | `test_application_window`（原生分支在 headless 下按预期跳过） |
| P2 | `src/ui/error_dialog.gd:101` | 增加 Esc 关闭、初始焦点、关闭后焦点归还；保留非 exclusive 以兼容其他模态窗 | `test_error_dialog` |
| P2 | `src/ui/preferences_page.gd:82` | 偏好加载失败显示“重新打开设置重试”浮层，不再只写 `push_warning` | `test_settings_control_states` |
| P2 | `src/ui/account_view.gd:264` | 拒绝中文密码时在页面显示原因，同时回退输入；不再静默吞键 | `test_login_presentation` |
| P2 | `src/ui/account_view.gd:290` | 登录/校验失败同时保留页内状态文案，弹窗关闭后仍能看到失败原因 | `test_account_view` |
| P2 | `src/application.gd:207` | `storage_error` 时保留登录态警告，不再每帧无条件隐藏 | `test_login_presentation` |
| P2 | `src/application/ui_style.gd:187` | 清透模式补上聊天/动态/Toast/日志终端；聊天区只改透明度，不破坏直角语义 | `test_ui_style`、`test_theme_contract` |
| P3 | `src/ui/settings_window.gd:102` | 隐藏窗口不再每帧深拷贝模型/偏好算脏；Esc 统一走关闭请求 | `test_settings_control_states`、`test_logout_confirmation` |
| P3 | `src/ui/log_window.gd:53` | 日志搜索 200ms 防抖，避免每个按键全量重建 RichTextLabel | `test_log_window` |
| P3 | `src/ui/chat_time.gd:38` | 日历时间正则改为静态编译，减少每条消息的 RegEx 分配 | `test_chat_timestamps` |
| P3 | `src/media/reply_audio.gd:64` | 无活跃流时关闭 `_process`，有音频入队再开启 | `test_voice_chat` |
| P3 | `src/domain/server_address.gd:9` | 地址正则改为 `static var`，避免登录/存储/重连路径反复编译 | 现有账号/地址测试 |

**第二阶段（同日续）**：

- **传输安全**：`ServerAddress` 新增 `allows_insecure/is_loopback`；账号、历史、WebSocket、模型 provider、动态/偏好共用的 `JsonRequest` 和图片下载统一拒绝非 loopback 的明文 `http`。`localhost/127.0.0.0/8/[::1]` 保留给本地夹具；新增账号 API 回归断言。
- **消息可靠性**：`llm_response` 改为 durable；`ReliableOutbox` 增加 `parallel` 标记，避免它被前面等待 ACK 的 durable 消息阻塞。模型执行与 loopback WebSocket 回归通过。
- **日志启动成本**：`list_runs()` 对没有 `entries` 字段的旧归档不再逐行解析，标记 `legacy_unverified`；用户选中或导出时再按需读取。日志窗口显示“旧归档未校验”。
- **缓存配额**：语音缓存增加单条 16 MiB、单账号 256 MiB；历史图片增加单账号 256 MiB；按修改时间淘汰，`commit/save/start` 后执行。
- **原子写统一**：新增 `src/storage/atomic_file.gd`，模型配置、阅读位置、历史图片改用统一临时文件写入。
- **账号切换语义**：`perform()` 重试/切号只结束当前会话，不再删除旧账号 token/remember；显式 `logout()` 仍清理凭据。
- **UI/UX**：退出登录始终确认；聊天输入框 Tab/Shift+Tab 离开输入区；设置 Tab 使用 `ButtonGroup`；Toast 增加成功/错误/进行中语义色；发布浮层覆盖全窗、遮罩拦截点击并循环焦点；分栏比例按两侧最小宽度动态 clamp；`FrostSurface` 通过注入的 `RuntimeEnvironment.supports_blur()` 判断能力；新增 `ModalStack`，同一父窗口后开的 exclusive 弹窗自动降级，避免 Godot 拒绝 setter。
- **性能**：`ChatSession` 增加只读浅拷贝 `get_messages_view()`；`ChatView` 同帧合并刷新；日志搜索不再每次 `JSON.stringify` 整条记录；`ServerAddress` 正则静态复用；语音元数据改为 256 条 LRU。

**本阶段新增/调整回归**：

- `tests/session/test_model_result_cache.gd`（已加入 `check.ps1`）。
- `tests/test_account_api.gd` 新增明文非 loopback 拒绝断言。
- `tests/test_application_drafts.gd` 新增“保存完成后退出登录仍需确认”。
- `tests/ui/test_composer_resize.gd` 新增 Tab 离开输入框断言。

**仍待处理**：

- 图片解码移出 UI 线程：第一版 `WorkerThreadPool` 改动导致历史媒体测试超时，已回退；需要专门的线程生命周期/取消测试后再落地。
- `HttpTransport`/`JsonRequest`/`AccountApi`/`HistoryApi` 的统一传输层，以及 `ChatSession` 拆分、`ServiceGraph` 拆分，仍属结构性重构。
- `ModalStack` 只解决同父窗口 exclusive 冲突；窗口关闭后自动提升下一个模态、焦点恢复链仍未完整实现。
- `test_dynamics_review_actions` 仍有“自动刷新失败保留评论”“滚动触底分页”两项失败；本次未改动态分页逻辑，需单独定位夹具时序。

### 12.4 遗留问题与处理方案

#### P1 — 安全与数据一致性

- **P1-1 明文 HTTP 传输认证材料（部分修复）**：`server_address.gd:6`、`websocket_transport.gd:120`、`account_api.gd:126`、`history_api.gd:145`。`normalize()` 接受 `http`，WebSocket 对应生成 `ws://`；`user_auth` 明文发送 `message_token`，历史请求用 `Authorization: Bearer`；登录口令虽用 RSA，但公钥与登录请求同源获取，无法抵御主动 MITM。第二阶段已拒绝非 loopback 明文；**证书/公钥固定仍未实现**。剩余方案：发布构建只允许 `https/wss`（仅 loopback 例外）；自建 HTTP 服务需显式“不安全连接”确认并在设置页持续警告；对 `/auth/public_key` 做证书或公钥指纹固定。
- **P1-2 `llm_response` 非 durable（已修复）**：`chat_session.gd:48`、`reliable_outbox.gd:57`。原实现 `send_event(..., false)`，断线时 outbox 对非 durable 项直接 `failed/DISCONNECTED`，本地已展示回复但服务端未收到，重连后不补发。已改为 durable，并用 `parallel` 标记避免被前序 ACK 阻塞；`request_id` 具备幂等基础。
- **P1-3 流式回复触发整份快照与列表重建（部分缓解）**：`chat_session.gd:276`、`chat_view.gd:243`、`virtual_message_list.gd:55`。每个流式分片 `changed.emit()`，`get_messages()` 深拷贝全部消息，`set_messages()` 重新过滤、建索引、算偏移并遍历可见气泡；1000+ 条时每次分片 O(n)。已加只读 `get_messages_view()` 与同帧合并刷新；**完整增量事件仍未实现**。剩余方案：`message_appended` / `message_updated(id, patch)` 只更新对应气泡与尾部偏移；`changed` 30–60ms 节流，结束包立即刷新；阅读位置只在条数/锚点变化时更新。
- **P1-4 旧日志归档启动时全量解析（已修复）**：`client_log.gd:215`、`:338`。旧归档没有 `entries` 字段时 `list_runs()` 会逐行 JSON 解析，50 个 8 MiB 归档可能卡住启动/日志窗。已改为标记 `legacy_unverified` 并按需读取；**一次性后台迁移工具仍待补**，迁移完成后才能彻底消除差异。

#### P2 — 稳定性、资源与体验

- **P2-1 图片缓存/解码仍在 UI 线程（待办）**：`history_images.gd:126`、`:146`、`:217`；`history_image_codec.gd:11`。`HTTPRequest` 回调里直接 `Image.load_*_from_buffer()`，缩略图 `duplicate()+resize()` 也在主线程；16 MiB / 1600 万像素上限下滚动或开原图会卡顿。方案：解码与缩略图放 `WorkerThreadPool`，完成后 `call_deferred` 回主线程创建 `ImageTexture`；按 `(path, mtime)` 做有界 LRU；原图预览复用缓存纹理。
- **P2-2 语音/图片缓存无磁盘配额（已修复）**：`audio_cache.gd:75`、`:160`；`history_images.gd:161`。已加单条 16 MiB、单账号 256 MiB 上限与按 mtime 淘汰；**清理仍主线程同步执行**，超大目录首次扫描需 profile。
- **P2-3 账户存储失败警告被隐藏（已修复）**：`application.gd:207`。现按 `state.storage_error` 显示；后续可做成可关闭的持久通知并链到日志。
- **P2-4 偏好加载失败只有日志（已修复）**：`preferences_page.gd:82`。现显示 3.5 秒不挡输入的浮层；后续可在页面内加“重试”按钮。
- **P2-5 发布动态浮层不是真正模态（已修复）**：根节点原先 `offset_top=48` 未覆盖顶栏，`Shade/Center.mouse_filter=2`，遮罩可穿透。现覆盖全窗、遮罩 `STOP`、循环焦点，Esc 仍走本层草稿确认。
- **P2-6 退出登录没有二次确认（已修复）**：`settings_window.gd:75`、`window_coordinator.gd:60`。现始终确认，文案明确结束本机登录及草稿处理。
- **P2-7 聊天输入框吞掉 Tab（已修复）**：`composer_input.gd:6`、`chat_view.tscn:200`。现拦截 `KEY_TAB`，`Shift+Tab` 反向，Ctrl+Tab 保留制表符。
- **P2-8 设置页 Tab 没有 ButtonGroup（已修复）**：`settings_window.tscn:70-103`。现共享 `ButtonGroup`，`allow_unpress=false`。
- **P2-9 分栏比例与最小宽度冲突（已修复）**：`application.gd:216`、`:227`、`:238`、`:335`。现按实际可用宽度与两侧最小宽度动态 clamp；窄窗折叠头像栏仍未做。
- **P2-10 错误弹窗模态栈（部分修复）**：`error_dialog.tscn:14`、`error_dialog.gd:101`。`ModalStack.activate()` 已让同一父窗口后开的模态自动降级为非 exclusive；**关闭后提升下一个模态 + 完整焦点链仍待补**。
- **P2-11 日志搜索仍全量重建（部分缓解）**：`log_window.gd:101`、`:136`。已加 200ms 防抖、去掉逐条 `JSON.stringify`；仍是 `_text.clear()` 后逐条 `push_color/add_text`，5 万条时输入仍有延迟。方案：可搜索字段预计算小写缓存、结果分页/虚拟化、一次性 `append_text`。
- **P2-12 单条日志仍逐条 flush（待办）**：`client_log.gd:478`。已去掉 open/close，但每条仍 `flush()`；流式回复每个分片写日志时慢盘/杀软会造成帧抖动。方案：每 250ms 或每 64 条 flush，`finish()` 强制收口，或迁移后台写线程。

#### P3 — 代码质量、冗余与可维护性

- **P3-1 HTTP/URL/JSON 组装重复（待办）**：`json_request.gd`、`account_api.gd`、`history_api.gd`、`history_images.gd:126` 四套请求实现分别处理超时、取消、状态码、trace 与日志；`json_request` 按 2xx 判成功，`account_api` 只认 200。方案：新增 `HttpTransport`/`ApiClient`，统一 `Request -> Response`；`history_images` 改为注入 `ImageApi`。
- **P3-2 原子写模板复制 6 份（部分修复）**：`godot_settings_store.gd:19`、`model_store.gd:81`、`reading_position.gd:83`、`audio_cache.gd:269`、`client_log.gd:288`、`history_images.gd:173`。已新增 `src/storage/atomic_file.gd` 并迁移模型配置、阅读位置、历史图片；其余调用点仍各自实现。方案：统一临时后缀、flush/get_error、rename 与回滚。
- **P3-3 时间解析两套契约（待办）**：`chat_session.gd:484`、`chat_time.gd:17`。实时消息只接受数值并按毫秒除以 1000，非数值回退“现在”；UI 支持秒/毫秒/ISO/时区。无调用方的 `domain/server_history_time.gd` 已删除。服务端格式变化会导致消息被标成“现在”或 1970。方案：`domain/timestamps.gd` 统一 `parse_epoch_seconds(Variant) -> float`（失败返回 `NAN`），未知时间写 `NULL`。
- **P3-4 账户身份键三处手工拼装（待办）**：`account_scope.gd:4`、`model_store.gd:14`、`account_session.gd:243`。一处哈希、一处手写同逻辑、一处原串去重；规范化规则调整后可能指向不同身份。方案：`AccountScope.identity()` 统一返回规范化 server/username 与 key。
- **P3-5 UI 直接读渲染配置（已修复）**：`frost_surface.gd:5` 原直接读 `ProjectSettings` 的 `rendering_method`；现通过注入的 `RuntimeEnvironment.supports_blur()` 判断。
- **P3-6 设置页可见时仍每帧算 dirty（部分修复）**：`settings_window.gd:102`。隐藏状态已修；可见时仍每帧 `is_dirty()`，`ModelPage` 会深拷贝配置并 `JSON.stringify(params, "  ")`。方案：编辑动作置脏标志，`params_text` 懒计算并缓存。
- **P3-7 音频状态全量广播（部分修复）**：`reply_audio.gd:287`、`:386`。语音元数据已改 256 条 LRU；开始播放仍 `_notify_all_audio()` 遍历全部 `_metadata`，长会话会触发大量波形尺寸更新。方案：只通知状态实际变化的 id，波形更新合并到下一帧。
- **P3-8 状态/错误码/路由字符串散落（待办）**：`chat_session.gd:190`、`message_bubble.gd:10`、`log_schema.gd:311`。`queued/waiting_history/uncertain`、endpoint、日志路由白名单各自维护；新增状态或接口时日志分组会静默变化。方案：新增 `domain/chat_status.gd` 与 `network/api_routes.gd`，由同一张表派生请求、日志与 UI 文案。

### 12.5 UI/UX 专项审查

**布局与响应式**：登录页 480×690、工作区 1280×800、最小 960×640；设置 720×640、动态 900×640。已修 `desktop_window_host` 按屏幕可用区收缩 `min_size`、登录历史弹层四边内缩；发布浮层覆盖顶栏与分栏 clamp 已在第二阶段修复。**仍待验证**：设置/动态内容区底部固定操作栏在极窄高度下的可达性。

**交互流程**：错误弹窗 Esc/初始焦点/焦点归还、设置窗隐藏后不再每帧算脏、密码非法字符提示均已修；退出登录确认、发布层模态、聊天输入框 Tab、设置 Tab ButtonGroup 在第二阶段修复。**仍待**：错误弹窗关闭后的焦点链、设置/日志/动态/图片窗口 Esc 行为完全统一。

**视觉一致性**：清透模式已补 `ChatSurface` 透明度、`DynamicsSurface`、`DynamicsDetailSurface`、`SettingsToast`、`TerminalSurface`；聊天区仍保持直角/无边框语义。Toast 已在第二阶段加成功/错误/进行中语义色；**仍待**：部分图标按钮小于 44×44（图片/音量 36×32、移除账号 36×42、图片缩放无最小尺寸），以及可见 focus ring。

**易用性**：偏好加载失败提示“重新打开设置重试”、本地登录状态写入失败保留 `AccountStorageWarning`、登录历史弹层右侧“移除账号”不再被裁出，均已修。**仍待**：消息失败/未确认仍主要通过全局对话框反馈，气泡内 `Caption` 对自己消息始终为空；建议失败气泡保留并可点击重发，避免“消息消失”。

### 12.6 分阶段优化清单（含状态）

**Phase 0（立即，发布前）**

1. 禁止 `http/ws` 传输认证材料（localhost 白名单除外）；评估公钥固定。——**部分完成**：非 loopback 明文已拒绝；证书/公钥固定、自建服务器兼容策略待产品确认。
2. `llm_response` 改 durable 或建立待回传队列。——**完成**。
3. 把 `list_runs()` 的旧归档迁移放到后台，迁移完成后彻底移除逐行回退。——**部分完成**：已改为按需读取并标记 `legacy_unverified`；一次性迁移工具待补。
4. 任何“发送中/排队中/不确定”消息在退出/切号时必须落库为确定状态；补一条覆盖 stop 的集成测试。——**进行中**：退出路径已修，stop 集成测试待补。
5. 真实 Windows 下验证 1366×768@150%、1024×600、多屏和最小窗口，确认底栏可达。——**待验收**。

**Phase 1（稳定性与数据一致性）**

1. `ChatSession` 拆分 `OutboundQueue`、`ReplyAssembler`、`HistoryCoordinator`、`MediaFacade`。——**待办**。
2. 统一 `HttpTransport`，消灭 `history_images` 自建 HTTP 和四套状态码口径。——**待办**。
3. 抽出 `atomic_file.gd` 与 `json_file.gd`，统一损坏文件语义。——**部分完成**：`atomic_file.gd` 已落地并迁移三处；`json_file.gd` 待办。
4. 为音频/图片缓存增加磁盘配额与账号切换清理。——**完成**（配额）；账号切换清理的覆盖范围需随新缓存点扩展。
5. 把 `AccountSession.perform()` 与显式 `logout()` 的凭据清理语义分开。——**完成**。

**Phase 2（性能）**

1. 流式回复改增量 `message_updated`，`changed` 30–60ms 节流；UI 不再每次深拷贝全量消息。——**部分完成**：只读视图与同帧合并已加；增量事件待办。
2. 图片解码/缩略图放工作线程；预览复用纹理；按文件 mtime 做有界 LRU。——**待办**（首版改动已回退，需线程生命周期测试）。
3. 日志写盘改批量 flush 或后台线程；日志搜索改字段缓存 + 一次性追加。——**部分完成**：搜索防抖与去 `JSON.stringify` 已加；批量 flush 与虚拟化待办。
4. 虚拟列表加对象池，减少滚动时 `instantiate/queue_free`。——**待办**。
5. 用 `--verbose`/Godot profiler 复测启动、长会话流式、图片滚动、日志打开四条路径。——**待办**。

**Phase 3（UI/UX 与架构）**

1. 建立 `ModalStack`，统一同父窗口的 exclusive 关系；发布浮层加真正遮罩与焦点陷阱。——**部分完成**：基础 `ModalStack` 与发布层已修；关闭后提升/焦点链待办。
2. 退出登录始终确认；危险按钮统一危险色/确认文案。——**部分完成**：确认已加；危险色统一待办。
3. 聊天输入框 Tab/Shift+Tab 焦点导航；所有图标按钮 ≥44×44；补齐可见 focus ring。——**部分完成**：Tab 已修；尺寸与 focus ring 待办。
4. 设置 Tab 加 `ButtonGroup`；Toast 增加 success/error/progress 三种语义样式。——**完成**。
5. 分栏比例按实际可用宽度动态 clamp；窄窗提供头像栏折叠。——**部分完成**：clamp 已修；折叠待办。
6. `Application._ready()`/`ApplicationServices.mount()` 拆成 `ServiceGraph` 阶段，逐段可测试、可回滚。——**待办**。

### 12.7 验证记录与边界

以下命令均在 `client-godot` 下执行，Godot `4.7.1.stable.official.a13da4feb`，使用隔离 `APPDATA`。

**已通过**：

- 日志与存储：`test_log_schema.gd`、`test_client_log.gd`、`test_log_window.gd`、`storage/test_sqlite_database.gd`、`storage/test_sqlite_migration.gd`、`storage/test_sqlite_runtime.gd`、`storage/test_sqlite_transaction_log.gd`、`storage/test_sqlite_worker.gd`、`session/test_message_persistence.gd`。
- 会话与网络：`session/test_message_reconcile.gd`、`session/test_history_paging.gd`、`session/test_model_result_cache.gd`、`test_websocket_transport.gd` + loopback WebSocket 契约、`test_live_chat.gd` + loopback 契约、`test_voice_chat.gd` + loopback 契约、`test_model_execution.gd` + offline feature API。
- UI：`ui/test_error_dialog.gd`、`ui/test_ui_style.gd`、`test_theme_contract.gd`、`ui/test_chat_timestamps.gd`、`ui/test_bubble_sizing.gd`、`ui/test_image_bubble_sizing.gd`、`ui/test_chat_reading_buttons.gd`、`test_ui_scenes.gd`、`ui/test_main_navigation.gd`、`ui/test_login_presentation.gd`、`ui/test_settings_control_states.gd`、`ui/test_logout_confirmation.gd`、`test_application_window.gd`（原生尺寸分支在 headless 下跳过）、`test_application_drafts.gd`。
- 第二阶段新增/调整：`session/test_model_result_cache.gd`（已入 `check.ps1`）、`test_account_api.gd` 的明文拒绝断言、`test_application_drafts.gd` 的退出确认断言、`ui/test_composer_resize.gd` 的 Tab 断言。

**未覆盖/未宣称**：

- 全量 `check.ps1`/`check_accounts.ps1`/`check_network.ps1`/`check_features.ps1`。
- GPU 截图逐像素比对、真实系统 DPI 切换、多屏、Windows 10、集显。
- Android/iOS 目标、真实麦克风/扬声器主观听感。
- 公共服务、生产 TTS/模型供应商、长期运行与磁盘写满场景。
- `test_dynamics_review_actions` 的“自动刷新失败保留评论”“滚动触底分页”两项失败未计入通过。

### 12.8 残余风险

- `http/ws` 已在客户端边界拒绝非 loopback 明文；证书/公钥固定仍未实现，自建服务器兼容策略需产品确认。
- `ChatSession` 仍是上帝对象，本次只修复具体时序缺陷，没有完成结构性拆分。
- 语音/图片缓存已加字节配额，但清理仍是主线程同步执行；超大目录首次扫描仍需 profile。
- 图片解码仍在 UI 线程；异步解码需要单独的线程生命周期测试，本次未强行开启。
- 统一 HTTP 传输层和 `ServiceGraph` 拆分仍属结构性改造。
- 旧日志归档不再解析，但完整性标记为“未校验”；需要一次性迁移工具才能彻底消除差异。
- `ModalStack` 只解决同父窗口 exclusive 冲突；关闭后提升下一个模态与完整焦点链仍未实现。
- 动态分页/刷新失败的两项测试失败未定位，不能据此宣称动态回归全绿。

## 13. 诊断记录：2026-10-28 桌面卡顿

原文见 [归档](../../archive/worklog/diagnostics/display-stutter-20261028-090718-findings.md)。

- **结论与边界**：证据指向 Windows 桌面合成与 NVIDIA 显示驱动之间的呈现/同步状态异常。**未证明**缺陷位于 MPO、独立翻转、驱动电源管理或某个应用交互代码中，不得表述为「已确认 MPO 故障」。NVIDIA Overlay 当时未运行；游戏 `javaw.exe`（PID 32024）从 08:30:05 一直运行到恢复之后，用户确认采样中途恢复且未退出游戏 —— 所以「重启 Overlay 后恢复」只能证明那次操作有效，不是唯一根因证据。
- **关键数值**：卡顿期 CPU 十秒均值 3.57%、可用内存约 20,224 MiB、系统盘 I/O ≈0.11 ms，无资源饱和；`DwmFlush` 中位 31.11–31.36 ms（95 分位 45.54 ms），恢复后同法采样中位 6.04–6.06 ms（95 分位 6.3 ms）。GPU 从 P8 到 P0，未见温度/功耗限频。
- **重要限制**：启动 GPU 诊断本身会干预显示调度与硬件叠加状态，是这次恢复的合理解释，但时间相关性不等于因果。
- **后续方向**：先针对 NVIDIA 驱动与桌面呈现路径排查，优先评估更新到适配该机与 Windows 版本的稳定驱动；仍复发再单独做 MPO 禁用/恢复的受控对照。**不要同时改驱动、MPO、HAGS 多项设置。**
- 本次未修改驱动、注册表、显示配置、游戏配置或启动项；WPR 已停止。

## 14. 命名与术语约定

### 14.1 现行约定

| 层面 | 约定 | 示例 |
|---|---|---|
| 文件名 / 变量 / 函数 | `snake_case` | `history_page_writer.gd`、`_sync_details()` |
| 类 / preload 常量（当类型用） | `PascalCase` | `const Services = preload(...)` |
| 其他常量 | `SCREAMING_SNAKE` | `const MAX_COUNT := 100` |
| wire payload key | `snake_case` | `touch_area`、`client_msg_id` |
| 数据库列 | `snake_case` | `timeline_order`、`ever_sent` |
| 设置存储 | `section` + `key` | `ui` / `style` = `flat` |

**领域术语表是 [`CONTEXT.md`](../../CONTEXT.md)**，采用「术语 + _避免称为_」结构，明确禁止同义替换（语音录制 / 录音提交中 / 语音条 / 音频描述 / 录音协调信号 等）。**改领域命名必须先改词汇表再改代码** —— 这是语音 spec 的明文要求。

### 14.2 已知遗留漂移（登记，不改）

| 漂移 | 说明 | 为何不改 |
|---|---|---|
| `dynamic_detail.gd`、`dynamic_comment_row.gd` vs `dynamics_window.gd`、`dynamics_post_row.gd` | 同名实体单复数并存 | 改名要同步 4 个 `.import` / `.uid` / `.tscn` ExtResource 与多处 `preload`，且不改变行为 |
| `set_unread_dynamic(...)` | 单数 | 与上同源；属 API 名，测试与调用方散布 |
| `unread_dynamic_count` | 单数 | **这是服务端回包字段**，不是本地命名，不能单方面改 |
| `crystal` / `frost` | 清透外观的英文代号 | `crystal` 已持久化为设置值，改名需迁移；`frost` 指毛玻璃 shader，属通用 UI 术语 |
| `ever_sent` | DB 列 | 改名需 SQLite 迁移 + `user_version` bump |
| `*_window` / `*_page` / `*_overlay` | 同类弹层三种后缀 | 后缀反映容器类型（Window / Control 页 / Control 覆盖层），有语义 |

### 14.3 改名同步清单（任何一项改名都要走完对应行）

| 改什么 | 必须同步 |
|---|---|
| wire payload key | `docs/服务端接口-WebSocket.md` + `tests/run_websocket_tests.py` + `tests/avatar/test_touch_delivery.gd` + `tests/run_client_behavior_comparison.gd` + 旧 web/cli 客户端 |
| `.gd` 文件名 | 同名 `.uid`、`.import`（若为资源）、`.tscn` 的 `ext_resource`、所有 `preload("res://...")`、`export_presets` 引用、`docs/` 与 `README/PREVIEW` 中的链接 |
| DB 列名 | `history_schema.gd` 的建表与全部 SQL + 迁移函数 + `user_version` bump + `test_sqlite_database.gd` |
| 持久化设置值 | 读取处加旧值兼容分支（`ui_style.gd` 的 `style in [...]` 判断 + `configure()` 的兜底） |
| 主题类型名 | `theme/app_theme.tres` + `ui_style.gd` 的 `_apply_panel_themes()` + `tests/test_theme_contract.gd`（按名断言） |

## 15. 待办与陈旧文档

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
- `docs-godot/`（38 份）已纳入 Git，但内容停在 2026-10-02 的 `f1cb9e2`，部分已过时，**不作为现行行为依据**（见 §3）。
- 归档的动效方案含两处失效信息：`ui_motion.gd` 从未落地、Godot 4.7.2 非交付口径（见 §9）。

## 16. 归档索引

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
| PR 描述草稿与逐项回复 | [pr-186-response-draft.md](../../archive/worklog/pr-186/pr-186-response-draft.md) | §5.4、§15 |
| 2026-10-28 桌面卡顿诊断 | [display-stutter-20261028-090718-findings.md](../../archive/worklog/diagnostics/display-stutter-20261028-090718-findings.md) | §13 |
| 2026-10-02 动效交接方案 | [ui-motion-plan.md](../../archive/worklog/design/ui-motion-plan.md) | §9 |

**就地保留**（Agent 系统按日期读取，不移动）：`2026-11-08.md`、`2026-11-09.md`（位于工作区 `.workbuddy/memory/`，文末已加指向本文件的指针）。

**相关现行文档**：[现行架构](architecture.md) · [测试与门禁](testing.md) · [测试目录](../tests/README.md) · [构建与使用](../README.md) · [包内说明](../PREVIEW.md) · [项目路线图](../../docs/TODO.md)
