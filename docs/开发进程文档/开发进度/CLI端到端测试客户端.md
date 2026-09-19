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
