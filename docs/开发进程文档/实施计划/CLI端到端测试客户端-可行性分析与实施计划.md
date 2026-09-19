# CLI 端到端测试客户端 · 可行性分析与实施计划

- 状态：待评审（已整合 @momus 严格评审意见，2026-09-19；正式切片方案应按《开发守则》归档到 Issue Tracker）
- 日期：2026-09-19
- 关联 PRD：`docs/开发进程文档/需求说明（PRD）/CLI端到端测试客户端规格.md`（PR #174，待评审）
- 核查基线：当前工作区 `feat/cli-e2e-client`（基线 `dev@b367bb2`）
- 范围：只做可行性核查与切片规划；不含实现代码

## 1. 结论摘要

- **总体可行**，无技术阻断项。工程量集中在三块：无 GUI 会话抽取（中）、CLI 动作层与断言/场景/报告（大，主体新增）、契约测试与 e2e 夹具（中）。
- **关键纠偏（需求级）**：PRD 声称"当前生产服务端尚未把触摸/选图开始/选图取消纳入业务输入集合"在**当前源码中不成立**——三类事件已从网络层贯通到领域刺激并被 Stage 消费（证据见 §2.2）。真正的前置缺口是：*鉴权 WebSocket 入口的契约测试证明* 与 *部署版本一致性确认*。
- **次要纠偏**：PRD 列举的"可选包序号"在当前协议中不存在（`ChatResponse` 无序号字段）；回复聚合必须按到达顺序，并在结果中标记证据较弱（PRD 自身已含该降级口径）。
- **仍然成立的关键约束**：`agent_message` 不携带原始客户端消息 ID（无 `reply_to`）→ 首版"同一时刻只等待一个待回复动作"的串行设计是必要的。
- **建议**：先按 §6 修订 PRD 的事实陈述与防伪装约束表述，再启动切片。

## 2. 现状核查（证据）

### 2.1 客户端：可复用面与 GUI 耦合

| 模块 | 现有能力 | 复用评估 | 关键证据 |
| --- | --- | --- | --- |
| `client/src/network/ws_transport.py` | 连接、鉴权、心跳、退避重连（2s→30s）、ACK 等待者、`submit_user_text/image/typing/touch/image_selecting/image_selecting_cancel` | **直接复用**（无 Qt 依赖） | 163-200 各类 submit；304-344 重连；417-427 ACK 按 `reply_to` 关联 |
| `client/src/network/network_client.py` | `login/auto_login`、`send_*` 门面、`get/overwrite_preferences`、dynamics/history 全套 HTTP | **直接复用**（无 Qt 依赖） | 26-80 方法区 |
| `client/src/network/event_types.py` | `AgentMessage` 全字段（uuid/text/audio/expression/is_final_package/audio_error/display_in_chat/is_ephemeral）+ `is_audio_terminal` | **直接复用** | 58-64、119-131 |
| `client/src/message_process/message_processor.py` | 发送队列与重试、per-UUID 音频聚合与终止落盘（`temp/tts_output/<uuid>.wav`）、本地重放、触摸抑制 | **部分复用**：含 Qt signals 与展示逻辑，需抽取 headless 变体 | 74 音频缓冲；178 抑制；237-282 聚合；548-566 落盘 |
| `client/src/message_process/multi_media_stream.py` | pyaudio 播放流、服务端音频活跃标记 | **需抽象**：CLI 无音频设备环境的降级行为需定义 | `is_server_audio_active` / `feed_local_wav` |
| `client/src/utils/*` | TLS12 HTTP、图片预处理、音频解码/保存 | 直接复用 | — |
| `client/src/delivery_policy.py` | 可重试消息策略 | 直接复用 | — |
| `client/tests/ws_test_client.py` | argparse + NetworkClient 的文本流脚本（雏形） | 可作起点/参考，不满足规格（无 JSONL/断言/场景） | 文件头 |

### 2.2 服务端：协议链路核查（对照 PRD 声称）

- **三类事件已接纳并消费**：
  - `server/src/legacy/chat_input_adapter.py:14-25` `CHAT_RELATED_EVENT_TYPES` 含 `USER_TOUCH / USER_IMAGE_SELECTING / USER_IMAGE_SELECTING_CANCEL`（已抽查确认）；
  - 转换实现 `chat_input_adapter.py:193-235`（ephemeral、不持久化）；强类型 modality `server/src/domain/stimulus.py:18-28`；
  - Stage 消费：`chat_session/chat_pipeline/ingress_helper.py:86-117`（触摸先走 reflex）、`topic_planner.py:41-53/173-184`（选图开始延长等待 / 取消恢复）；触摸 reflex `agent/reflex/touch.py:141-164`。
- **ACK 语义**：`server/src/system/user_interface/websocket_service.py:197-209`（肯定 ACK + `reply_to=client_msg_id`）、`:239-253`（重复输入 `duplicate=true` 且同样关联）、`:255-296` 去重、鉴权 `:87-146`。未接纳的非聊天事件被**静默忽略**（`server_main.py:169-205` 仅对已识别聊天事件回 NACK）——CLI 需把"无 ACK"作为超时/未知事件处理依据。
- **输出包**：`server/src/system/user_interface/types.py:20-29` `ChatResponse` 定义（含 `audio_error/error_code/display_in_chat/is_ephemeral`），**无包序号**；`chat_stream.py:256-270` 序列化发送时**不带 `reply_to`**；TTS 终止包 `global_speaking_worker.py:134-152/203-219`（`TTS_STREAM_ERROR`/`TTS_EMPTY`）。
- **缺口**：没有"鉴权 WS 入口 → 三类事件 → ACK/重复 ACK/NACK + Stage 效果"的集成测试；现有覆盖停留在领域消费者级（`server/tests/test_agent_reflex.py`、`test_topic_planner_waiting_signals.py`）。

### 2.3 测试与联调基建

- server：61 个测试文件（pytest，`server/pytest.ini` `asyncio_mode=auto`；`server/tests/conftest.py` 提供 `--run-real-llm` 开关，真实 LLM 场景默认跳过）；client：16 个测试文件。
- 可复用协议样例：`client/tests/test_ws_transport_ack.py`（ACK 归一化）、`client/tests/test_tts_terminal_event.py`（TTS 终止）；server 侧 `test_websocket_delivery / test_websocket_idempotency / test_websocket_auth_limits`、`test_chat_stream_lifecycle / test_chat_stream_reconnect`、`test_tts_lifecycle`。
- Fake 设施为各测试自带（`FakeWebSocket / FakeLLMModule / FakeEventStore` 等），无共享库。
- 缺口：跨进程 e2e 夹具（拉起真实服务端 + 真实 WS 客户端）与测试账号/环境准备脚本尚无；仓库根无 CI（无 `.github`）。

### 2.4 与 PRD"当前实现事实与完成前置"差异清单

| PRD 陈述 | 核查结论 | 处置 |
| --- | --- | --- |
| 生产服务端尚未接纳三类事件 | **不成立**（源码已接纳并消费） | 前置改为"受测部署能力确认 + 契约测试" |
| agent_message 含"可选包序号" | **不存在** | 聚合按到达顺序 + 弱证据标记 |
| Agent 输出无原始客户端消息 ID | 成立 | 保留串行口径 |
| 客户端已有触摸/选图发送能力 | 成立 | 无需改动客户端发送层 |

## 3. 可行性判断与主要风险

**判断：可行。** 无协议级阻断；主要新增是 CLI 工具层与无 GUI 抽取，属常规工程量；真正的环境不确定性在"部署一致性"与"真实媒体/设备"。

| # | 风险 | 影响 | 缓解 |
| --- | --- | --- | --- |
| R1 | 部署版本与源码不一致（PRD 声称或反映旧部署） | 触摸/选图 e2e 形式通过但部署环境不可用 | S0/S1 完成契约测试后核对部署版本；不一致先同步部署 |
| R2 | 无包序号、无因果关联 | 聚合证据弱、并发不可判定 | 沿用 PRD 串行口径；结果标记证据强度；未来协议加字段后再放开并发 |
| R3 | pyaudio/播放设备依赖 | CLI/CI 环境可能无可用设备 | `audio.replay` 定义"设备不可用"失败态；真实回放场景 external 默认跳过（S4 离线仅验收解码/索引/分类） |
| R4 | 抽取 headless 会话影响 GUI | GUI 回归破损 | S2 以现有 client 测试与手工验证保护；不改变 GUI 行为与协议语义 |
| R5 | 真实 LLM/TTS 输出不确定 | 断言不稳 | 采用 PRD 宽松断言（非空/格式/时限）；真实模型场景 external 默认跳过 |
| R6 | 测试数据与夹具缺失（无跨进程夹具、无隔离账号） | 动态发布、偏好覆盖等外部验证不可重复或污染数据 | 首个真实端点验证前定义外部夹具职责：隔离测试账号、唯一数据前缀、清理与人工恢复步骤、并发运行规则（§5.5） |
| R7 | 敏感信息泄漏面（凭据、媒体、正文、路径） | 违反 PRD 脱敏要求 | S3 起建立统一 redaction 边界，覆盖 stdout/stderr/异常/JSONL；S9 覆盖报告、产物目录、权限与清理 |

## 4. 实施计划（行为切片）

依赖主链：`S0 → S2 → S3 → {S4,S5,S6,S7,S8} → S9`；`S1` 独立可先行（并为 S5/S6 提供部署门槛输入）。

| 切片 | 目标（一个完整行为） | 公开 interface 变化 | 验证口径 | 依赖 | 明确不包含 |
| --- | --- | --- | --- | --- | --- |
| S0 文档前置（非产品行为切片，走文档验证、不形成产品 PR） | PRD 事实修订 + Issue 归档切片方案 + interface 归属决策 | — | 不适用（文档；静态检查+评审） | — | 代码；进度文档不在此处维护 |
| S1 服务端契约测试 | 在可控测试装配（可注入 Fake Stage/Agent 边界）下，证明鉴权 WS 入口对三类事件的接纳语义：期望 ACK / 重复 ACK / NACK / 静默 + 确定性可观察副作用（转换并进入 ingress） | 无（复用既有协议） | 新增契约/回归测试；既有实现首次即绿时记录"补回归测试"，不伪造 Red；真实业务反应不在本切片声称；发现缺口转缺陷流程 | — | 触摸/选图业务语义变更；真实 LLM/异步业务反应 |
| S2 无 GUI 会话核心 | headless 会话门面：连接/鉴权就绪/心跳/重连/事件订阅/ACK 等待/回复聚合（音频终止与落盘索引） | 新增 client 侧会话 interface：先写入权威 interface spec（归属见 §5.4），再 Red | 现有 client 测试回归 + 门面行为测试 | S0 | CLI 展示层、音频设备播放 |
| S3 CLI 骨架与文本动作 | 双模式入口、JSONL/退出码；`session.*`、`chat.send_text`、`reply.wait/read`（文本聚合与断言）；统一 redaction 边界（stdout/stderr/异常/JSONL） | 首批动作、JSONL/错误对象/退出码契约先写入权威 spec 再 Red；`reply` 输出 schema 一次性定义（含媒体字段与兼容策略，避免 S4 破坏已发布契约） | 模块测试（解析/状态机/聚合/断言）+ 测试端点集成 + 脱敏测试 | S2 | 音频重放/图片/触摸 |
| S4 媒体回复与重放 | 音频聚合输出、表情、`audio.replay`（失败分类 + 无设备降级） | 仅填充 S3 已定义字段，不改变已发布契约 | 复用 TTS 终止样例；补失败路径（不存在/未完成/临时/音频错误）；离线验收限于解码/索引/`device_unavailable` 分类，真实播放结束为 external（设备前置+人工验收，播放器 Fake 契约随 S2 定义） | S3 | 图片/触摸；真实设备播放 |
| S5 图片动作 | `image.select/cancel/send` 状态机与真实媒体发送 | `image.*` | 选择状态可观察、取消后不可误发、真实编码发送；真实链路依赖 S1 已验证契约与部署一致性门槛，未满足时仅交付客户端状态行为 + 显式 external skip | S3 + S1 门槛 | 其他动作 |
| S6 触摸动作 | `touch.send`（含音频活跃期抑制=suppressed） | `touch.send` | 抑制语义用例 + 接纳用例；真实链路同 S5 的部署门槛与 external skip 口径 | S3 + S1 门槛 | 其他动作 |
| S7 动态动作 | `dynamics.open/read/load/post`（首屏/标记已读/分页/读后确认） | `dynamics.*` | 到底 `end_of_feed`；发布后可见性确认；外部运行使用隔离账号/唯一数据前缀/清理步骤（§5.5） | S3 | 评论发布 |
| S8 偏好动作 | `preferences.open/read/update`（合并/覆盖/读后确认） | `preferences.*` | 合并不误删、replace 语义、读后一致；更新失败保留更新前快照与差异摘要（不落敏感正文） | S3 | — |
| S9 场景引擎与报告 | `scenario.run` 串行执行、失败策略、脱敏报告、产物保留开关（超预算时拆为 S9a 调度 / S9b 报告与产物） | 场景文件 schema；SPEC 须枚举最小合法/非法场景、终态→退出码矩阵、失败后继续白名单（只读/副作用）、报告保留/清理 | JSONL 合法性、退出码矩阵全覆盖、失败后继续策略、报告产物保留/清理与脱敏断言 | S4-S8 | 外部真机验收 |

说明：

- 每切片遵守"小提交、完整切片、他人审核"；PR 均进入 `feat/cli-e2e-client`（origin 集成分支），最终由 `feat/cli-e2e-client → dev` 提功能 PR。S0 为非产品行为切片（文档验证、不形成产品 PR）；S1 为补契约/回归测试，记录"既有实现首次即绿"，不按 Red→Green 行为 PR 描述。
- 预算以完整 diff（实现+测试+文档）计：单切片目标 ≤500 行手写实现；逼近上限或出现两个可独立发布的行为时必须在切片内拆分（S9 至少预拆为 S9a/S9b）。
- 契约先行：S2 的会话 interface、S3 的首批动作与 JSONL/错误/退出码必须写入权威 interface spec 后才进入 Red；PRD 只保留需求与验收标准，不作为契约权威位置。
- S2 是唯一抽取型切片，不得改变既有 GUI 行为；S4-S8 之间无相互依赖，可按人力并行；本计划默认串行推进。
- 真实端点前置：S5/S6 的真实链路依赖 S1 契约验证 + 部署一致性确认；S7/S8/S9 的外部运行依赖 §5.5 的夹具与数据生命周期约定。未满足时只交付离线行为并显式 skip external。
- 粗略规模预估（手写，不含测试；S1 为测试代码本身）：S1≈0.15-0.3k、S2≈0.2-0.4k、S3≈0.3-0.5k、S4≈0.2-0.35k、S5≈0.15-0.25k、S6≈0.1-0.2k、S7≈0.25-0.4k、S8≈0.2-0.3k、S9≈0.3-0.5k；合计约 2-3k 行 + 测试。

## 5. 需要的文档与归属

1. **本文件**（可行性 + 计划）：临时收录于仓库；正式切片方案已归档到 Issue Tracker（[#175](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/175)，2026-09-20）。
2. **进度文档**：`docs/开发进程文档/开发进度/CLI端到端测试客户端.md` 已建壳（标题+索引）；仅在切片 Green 后追加完成事实，不作为任何切片的前置交付，也不用作计划维护位置。
3. **PRD 修订**：见 §6（已于 2026-09-20 应用，随 PR #174 更新）。
4. **interface spec 归属（S2 前必须决定）**：`docs/项目说明/项目架构与接口（spec）/接口文档/` 仍是唯一契约权威位置（建议新增 client 域子目录）。S2 的会话 interface、S3 的首批动作/JSONL/错误对象/退出码与 `reply` 输出 schema 都先写入此处再进入 Red；PRD 不作为契约权威。
5. **环境与夹具前置（首个真实端点验证前必须定义）**：外部夹具职责、隔离测试账号、唯一数据前缀、清理/人工恢复步骤、并发运行规则、external marker 与启用命令（默认离线 Fake、显式启用 external）。
6. （可选）`接口文档/当前实现项目架构总览.md` 在 CLI 落地后补充客户端侧组件说明。
7. **逐切片执行指引（供本地 agent）**：`docs/开发进程文档/实施计划/CLI端到端测试客户端-执行指引.md`。

## 6. PRD 修订（已应用，2026-09-20）

1. "当前生产服务端尚未把触摸和图片选择事件纳入业务输入集合；完成本规格必须补齐真实协议链路，而不是只完成 CLI 命令表面。" → 改为："当前源码的链路已存在（见 `server/src/legacy/chat_input_adapter.py`、`server/src/domain/stimulus.py`）；受测部署的能力须在 e2e 前确认。"（契约测试要求保留在实施计划与 Testing Decisions，不作为产品需求条目。）
2. agent_message 字段列举中的"可选包序号" → 删除；聚合口径明确为"按到达顺序 + 证据弱标记"（与 PRD 已含的降级表述合并）。
3. Out of Scope：保留"不得以 CLI mock 掩盖协议不一致"的防伪装约束，仅调整其后半句 → "……；部署或受测服务未接纳时，按测试类型明确 failed 或 skipped，并报告版本/能力差异。"

## 7. 验证口径（各切片通用）

- server 回归：工作目录 `server/`，`python -m pytest tests/... -q`（conda 环境 `agent`）。
- client 回归：工作目录 `client/`，以现有 `tests/` 用例为基线。
- 契约/e2e：使用真实 HTTP/WS 测试端点；真实 LLM/TTS/音频设备/远程服务属 external，默认跳过、显式启用。
- 每切片至少一条成功路径 + 一条最重要失败路径，并记录经过的真实外部边界；不得以测试数量替代行为证据。
- 脱敏验证：自 S3 起对 stdout/stderr/异常/JSONL 做敏感信息检查；默认不保留回复正文、动态/偏好原文、媒体文件与绝对路径（除非调用方显式开启）。
