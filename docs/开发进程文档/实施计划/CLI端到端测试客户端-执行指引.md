# CLI 端到端测试客户端 · 逐切片执行指引（供本地 agent）

- 状态：2026-09-20 初稿（配合《可行性分析与实施计划》的 S0-S9；工作分支 `feat/cli-e2e-client`）
- 用途：本地实现 agent 按切片取用；每切片独立分支、独立 PR，PR base 均为 `feat/cli-e2e-client`
- 必读：`开发守则`、`skills/spec-tdd-pr-guard/SKILL.md`、PRD（`需求说明（PRD）/CLI端到端测试客户端规格.md`）、实施计划（`实施计划/CLI端到端测试客户端-可行性分析与实施计划.md`）、Issue #175

## 0. 通用流程（所有切片适用）

1. **取切片**：从 `feat/cli-e2e-client` 拉短期切片分支（如 `feat/cli-e2e-s1-contract-tests`）；一个切片一个分支一个 PR（PR base = `feat/cli-e2e-client`，不直接进 dev）。
2. **门禁顺序**（spec-tdd-pr-guard）：SPEC（契约变化才提交，无变化则记录"SPEC 已满足"）→ Red（先写失败测试并记录失败原因）→ Green（最小实现 + 回归 + 进度记录）；每个 commit 后暂停自审；既有实现首次即绿时记录"补回归/契约测试"，不伪造 Red。
3. **测试命令**（项目 conda 环境 `agent`）：
   - server：`cd server; python -m pytest tests/<focused>.py -q`；关键词回归 `python -m pytest tests -q -k <关键词>`
   - client：`cd client; python -m pytest tests/<focused>.py -q`
   - 真实 LLM 用例默认跳过；显式启用：`--run-real-llm` 或 `RUN_REAL_LLM_TESTS=1`（server）
4. **红线**：不改既有 GUI 行为（S2 需回归保护）；不建 CLI 专用服务端后门；不以 mock 掩盖协议不一致；不把凭据 / 音频 Base64 / 本地绝对路径写入默认输出；单切片手写实现 ≤500 行，超了拆。
5. **进度记录**：只有完整 Green 后，才在 `开发进度/CLI端到端测试客户端.md` 的"已完成"追加一条（交付行为 / interface / commit 或 PR / 验证与结果 / 未验证范围）。
6. **external 场景**：真实 LLM / TTS / 音频设备 / 受测部署默认跳过；显式启用，并写明前置条件与验收记录。

## S0 文档前置（无产品 PR）

- 做什么：确定 **interface spec 归属**——在 `docs/项目说明/项目架构与接口（spec）/接口文档/` 下新增 client 域（建议 `cli/README.md`），承载：CLI 动作名 / JSONL / 错误对象 / 退出码（S3 起）、S2 会话门面 interface。
- 怎么做：a) 读 PRD §Solution 动作表 + 实施计划 §4；b) 起草文档：调用者、输入输出、副作用、正常/异常行为、从哪个 interface 验证；只写近期切片所需契约，不写未来切片；c) 提交 SPEC commit（`docs(spec)`）并自审；文档类切片 Red 记"不适用"。
- 完成标准：归属文档就位（至少 S2 门面接口草案 + 契约填写位置）。

## S1 服务端契约测试（补契约/回归测试）

- 目标：三类事件（`user_touch` / `user_image_selecting` / `user_image_selecting_cancel`）从**鉴权 WS 入口**的接纳语义 + 确定性副作用（可控装配，不依赖 LLM）。
- 看哪里：`server/src/system/user_interface/websocket_service.py`（鉴权 87-146、ACK 197-209 / 重复 239-253、去重 255-296）；`server/server_main.py`（ACK/NACK 169-205）；`server/src/legacy/chat_input_adapter.py`（事件集合 14-25、转换 193-235）；样例测试 `server/tests/test_websocket_delivery.py`、`test_websocket_idempotency.py`（FakeWebSocket 套路）。
- 怎么做：1) 复用 FakeWebSocket 起鉴权会话；2) 三类事件各断言：肯定 ACK（`received_event_type` + `reply_to=client_msg_id`）、重复 ACK（`duplicate=true` 且 `reply_to` 不变）、无效 payload → NACK（`BAD_MESSAGE`）、未识别非聊天事件 → 静默；3) 断言事件被转换为 Stimulus 并进入 ingress（不依赖 LLM 的确定性观察点）；4) 测试 commit 记录"既有实现首次即绿——补契约测试"。
- 验证：`cd server; python -m pytest tests/test_websocket_delivery.py -q` + 新增测试文件。
- 不包含：触摸 reflex 的业务回复、选图等待状态行为（留给受控 e2e）。

## S2 无 GUI 会话核心（抽取型切片，先 SPEC）

- 目标：headless 会话门面：连接 / 鉴权就绪 / 心跳 / 重连 / 事件订阅 / ACK 等待 / 回复聚合（per-UUID 音频缓冲、终止判定、落盘索引）。
- 看哪里：`client/src/network/ws_transport.py`（submit 系列 163-200、重连 304-344、ACK 关联 417-427）、`network_client.py`、`event_types.py`（58-64 / 119-131）、`message_processor.py`（音频缓冲 74、聚合 237-282、落盘 548-566；Qt signals 只在此文件）。
- 怎么做：1) SPEC：门面 interface（方法、事件、状态机、错误）写入 S0 的 client 域文档；2) Red：门面行为测试（本地 WS 测试端点 / Fake）；3) Green：抽取实现；GUI 保持可用，最终 GUI 与 CLI 共用该接口（禁止第二套协议实现）；4) 回归：`cd client; python -m pytest tests -q` + GUI 启动冒烟（环境允许时）。
- 完成标准：门面测试绿、GUI 未回归、无重复协议实现。

## S3 CLI 骨架与文本动作

- 目标：CLI 入口（交互 + 非交互 JSONL 双模式）、动作执行器、退出码、统一 redaction 边界；`session.connect/status/close`、`chat.send_text`、`reply.wait/read`（文本聚合与断言）。
- 契约先行：动作名 / JSONL 字段 / 错误对象 / 退出码写入 client 域文档后，再 Red。
- 怎么做：1) 以 `client/tests/ws_test_client.py`（argparse + NetworkClient）为起点升级为动作执行器；2) JSONL 每条至少含：schema 版本 / 时间 / 会话 ID / 动作 ID / 事件类别 / 状态 / 耗时 / 关联 ID / 数据摘要 / 稳定错误对象；stdout 只放 JSONL，人类日志走 stderr；3) redaction 集中实现并写测试（stdout / stderr / 异常 / JSONL 中不得出现 password、message token、Authorization、音频 Base64）；4) 断言：ACK 成功/失败、文本非空/包含/正则、超时；5) `reply` 输出 schema 一次性定义（含媒体字段占位与兼容策略，避免 S4 破坏契约）。
- 验证：`cd client; python -m pytest tests -q` + 新增用例；用测试端点跑通一条 send_text → ACK → 回复。

## S4 媒体回复与重放

- 目标：`reply.read` 输出音频元数据（存在性 / 字节数 / 格式 / 摘要 / 本地引用，不打印 Base64）、表情按到达顺序输出；`audio.replay` 按回复 UUID 重放（失败分类：不存在 / 未完成 / 临时 / 音频错误 / 设备不可用）。
- 看哪里：`event_types.is_audio_terminal`、`message_processor` 音频聚合与 `_save_audio_to_temp`（`temp/tts_output/<uuid>.wav`）、样例 `client/tests/test_tts_terminal_event.py`。
- 要点：`audio_error=true` 结束等待但丢弃部分音频（已收文本仍可断言）；临时反应（`display_in_chat=false` / `is_ephemeral=true`）不进重放索引；离线只验收解码 / 索引 / `device_unavailable` 分类，真实播放结束单列 external（设备前置 + 人工验收）。
- 验证：`cd client; python -m pytest tests/test_tts_terminal_event.py -q` + 新增失败路径用例。

## S5 图片动作

- 目标：`image.select` / `image.cancel` / `image.send` 状态机与真实媒体发送。
- 看哪里：`network_client.py` send_image*、`ws_transport.py` submit_user_image*、`utils/image_process.image_preprocess`、样例 `client/tests/test_network_client_images.py`。
- 要点：类型 / 大小规则来自现有客户端/服务端媒体规则，不新建独立常量；取消后不可误发；发送失败不得自动改用新 ID 重发同一输入。
- 门槛：真实链路依赖 S1 已验证契约 + 部署一致性确认；未满足时只交付客户端状态行为 + 显式 external skip。
- 验证：选择状态可观察、取消后不可误发、真实编码（测试端点）。

## S6 触摸动作

- 目标：`touch.send`（区域 / 点击频率 / 元数据形态沿用现有客户端）；服务端音频活跃时按现有产品语义抑制并返回 `suppressed`，不伪造 ACK/回复。
- 看哪里：`message_processor.py` 抑制逻辑（178 附近）与 `is_server_audio_active`（201-202）、`ws_transport.submit_user_touch`。
- 门槛：同 S5（S1 契约 + 部署一致性）。
- 验证：抑制语义用例 + 接纳用例。

## S7 动态动作

- 目标：`dynamics.open` / `read` / `load` / `post`。
- 看哪里：`network_client.py`（get_dynamics / create_dynamic / get_dynamic_comments / get_dynamic_unread_status / mark_dynamics_read）。
- 要点：open = 首屏成功后再标记已读，标记失败单独报告；load = 服务端游标 + 稳定 ID 去重，`has_more=false` → `end_of_feed` 成功态；post = 有副作用，输出内容摘要 + 返回项或重读确认可见，场景默认不重复发布。
- 外部运行：隔离测试账号 + 唯一数据前缀 + 清理/恢复步骤。

## S8 偏好动作

- 目标：`preferences.open` / `read` / `update`。
- 看哪里：`network_client.get_preferences / overwrite_preferences`；服务端样例 `server/tests/test_preferences_normalization.py`。
- 要点：update 默认"读取最新 → 按键合并 → 覆盖接口 → 重读 → 比较目标键"；完整覆盖必须显式 replace 模式；失败保留更新前快照与差异摘要（不落敏感正文）。

## S9 场景引擎与报告

- 目标：`scenario.run`（同一会话串行执行动作 + 断言）、失败策略（默认停止有副作用动作；只读是否继续由场景策略决定）、脱敏报告（默认仅结构化元数据；保存正文/媒体需显式开关 + 输出目录 + 清理策略）、退出码矩阵。
- SPEC 必须枚举：最小合法 / 非法场景；`passed/failed/timed_out/skipped/suppressed` → 进程退出码矩阵；失败后继续白名单（只读 / 副作用）；报告保留与清理的可执行断言。
- 超预算时拆 S9a（调度）/ S9b（报告与产物）。
- 验证：JSONL 合法性（含失败路径）、退出码矩阵全覆盖、脱敏（stdout / stderr / 异常 / 报告 / 产物目录）、串行执行。

## 附：常见坑

- ACK ≠ 回复：肯定 ACK 只满足"已接纳"；否定 ACK、超时、业务回复分别观察。
- 串行约束：同一时刻只允许一个"等待回复"动作；并发观察必须标记"未确定关联"。
- 音频失败终止包：结束等待但判定音频失败；部分音频不进重放索引。
- 未识别非聊天事件会被服务端静默忽略 → 客户端"无 ACK"必须按超时/未知事件处理。
- 部署不一致：按测试类型明确 failed 或 skipped 并报告版本/能力差异，不得用 mock 掩盖。
