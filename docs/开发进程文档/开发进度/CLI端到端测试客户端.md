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

### 2026-09-20 S3 CLI 骨架与文本动作

- 交付行为：无 GUI CLI 骨架（`client/cli.py` + `client/src/cli/`）：交互/非交互 JSONL 双模式、统一动作执行器、稳定退出码、集中脱敏与诊断日志改道 stderr（stdout 纯 JSONL）；动作 `session.connect` / `session.status` / `session.close` / `chat.send_text` / `reply.wait` / `reply.read`（文本断言 non_empty/contains/regex）；`reply` 输出预置媒体字段占位（供 S4 填充，不破坏 schema）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1（CLI 动作与机器输出）。
- commit 或 PR：分支 `feat/cli-e2e-s3-cli-skeleton`：`f487eca`（SPEC）/ `dcdad99`（Red）/ `4aeefc7`（Green）。
- 验证及结果：focused → 17 passed；新增日志改道回归 `tests/test_cli_log_stream.py` → 2 passed；client 回归 → 85 passed（排除 3 个既有收集失败文件）；子进程冒烟（真实连接失败路径）→ 退出码 4、stdout 仅 1 行合法 JSONL、诊断日志全部在 stderr、无凭据泄漏。
- 未验证范围：真实服务端登录/鉴权与文本发送、真实 ACK/断线重连、真实 LLM/TTS、音频解码与重放、图片/触摸/动态/偏好、交互模式增强。

### 2026-09-20 S4 媒体回复与重放

- 交付行为：`audio.replay` 动作（资格校验 + 播放后端抽象 + 全部稳定失败分类：`AUDIO_REPLY_NOT_FOUND` / `AUDIO_NOT_READY` / `AUDIO_EPHEMERAL` / `AUDIO_STREAM_FAILED` / `AUDIO_FILE_MISSING` / `AUDIO_FORMAT_INVALID` / `DEVICE_UNAVAILABLE` / `PLAYBACK_INTERRUPTED`）；`reply.wait/read` 媒体字段最终语义（格式经解码确认、仅文件名引用、不输出 Base64 与绝对路径）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.6。
- commit 或 PR：分支 `feat/cli-e2e-s4-media-replay`：`85dc0cb`（SPEC）/ `5d0bbac`（Red）/ `3dd9eb2`（Green）。
- 验证及结果：focused `tests/test_cli_media_replay.py` → 11 passed；S3+日志回归 → 19 passed；client 回归 → 96 passed（排除 3 个既有收集失败文件）。
- 未验证范围：真实音频设备播放与"开始并正常结束"（external，需设备前置）、播放被中断的真实路径、非 WAV 格式支持。

### 2026-09-20 S5 图片动作

- 交付行为：`image.select` / `image.cancel` / `image.send` 状态机（选择信号先发、本地校验后记录、校验或 ACK 失败清空选择、取消后不可误发、显式路径覆盖当前选择、失败不自动改 ID 重发）；新增 `client/src/utils/image_rules.py`（镜像服务端媒体规则，含防漂移测试）与 `client/src/utils/image_encoding.py`（自 MessageProcessor 抽取共用编码管道，MIME 映射补齐 bmp/webp）；门面增补 `select_image` / `cancel_image_selection` / `send_image`（`SessionImageError`）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.7。
- commit 或 PR：分支 `feat/cli-e2e-s5-image-actions`：`dcbdbd5`（SPEC）/ `47b5af4`（Red）/ `6cc9d8a`（Green）。
- 验证及结果：focused `tests/test_cli_image_actions.py` + `tests/test_image_rules_mirror.py` → 19 passed；client 回归 → 115 passed（排除 3 个既有收集失败文件）。
- 未验证范围：真实服务端图片接纳与回复链路（依赖 S1 门槛与部署一致性）、图片内容解码（校验按扩展名与大小）、大文件真实发送时延、GUI 图片发送回归（编码管道已抽取共用，由既有测试与本次回归保护）。
