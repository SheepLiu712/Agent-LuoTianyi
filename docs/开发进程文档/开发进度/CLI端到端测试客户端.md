# CLI 端到端测试客户端

- 大目标：提供可由 AI 和开发者在终端稳定驱动的无 GUI 真实客户端，用于客户端—服务端端到端调试（认证、对话、媒体、动态、偏好全链路）。
- PRD：`docs/开发进程文档/需求说明（PRD）/CLI端到端测试客户端规格.md`
- 总体设计：—
- interface spec 索引：—
- 总体状态：进行中

## 已完成

### 2026-09-20 S1 服务端契约测试

- 交付行为：三类事件（`user_touch` / `user_image_selecting` / `user_image_selecting_cancel`）从鉴权 WebSocket 入口的接纳语义（肯定 ACK / 重复 ACK / `BAD_MESSAGE` 否定 ACK / 未知事件静默）与确定性副作用（转换为 Stimulus 并进入 ingress）的契约测试。
- interface spec：SPEC 已满足（复用既有协议，见 `server/docs/dev/统一事件协议.md`）；无契约变更。
- commit 或 PR：分支 `feat/cli-e2e-s1-contract-tests`（本切片提交）。
- 验证及结果：`cd server; python -m pytest tests/test_websocket_chat_input_contract.py -q` → 13 passed；回归 `tests/test_websocket_delivery.py tests/test_websocket_idempotency.py -q` → 20 passed（conda 环境 `agent`）。
- 未验证范围：触摸 reflex 的业务回复、选图等待状态行为、真实 LLM/TTS；鉴权失败/超时与 OVERLOADED 由既有测试覆盖。

### 2026-09-20 S2 无 GUI 会话核心

- 交付行为：抽取无 GUI 会话门面 `client/src/session/headless_session.py`（`HeadlessSession`）：连接与 ready 等待（登录/token）、状态与订阅事件、文本发送（ACK 委托）、按回复 UUID 聚合（文本/表情/音频终止落盘、临时反应不入索引）、`wait_for_reply`、`audio_path_for`、稳定失败分类；`WsTransport` 仅新增窄状态观察接口（`wait_until_ready` / `is_ready`）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §2（无 GUI 会话门面）。
- commit 或 PR：分支 `feat/cli-e2e-s2-session-core`：`d34fbc3`（SPEC）/ `0f5332a`（Red）/ `a9460d4`（Green）。
- 验证及结果：`cd client; python -m pytest tests/test_headless_session.py -q` → 7 passed；含 ACK/TTS 关联回归 → 21 passed；其余 client 用例 66 passed（3 个旧测试文件因既有导入问题无法收集，与本次改动无关）。
- 未验证范围：真实服务端登录/鉴权、真实断线重连时序、GUI 迁移与冒烟、音频播放/设备、CLI 层、图片/触摸/动态/偏好。
