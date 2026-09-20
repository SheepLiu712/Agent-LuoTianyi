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

### 2026-09-20 S6 触摸动作

- 交付行为：`touch.send`（输入校验 + "服务端音频活跃"等效状态下的本地抑制：`status="suppressed"`、不发送、不伪造 ACK/回复；ACK 拒绝/超时沿用 S3 语义）；门面增补 `send_touch` 与 `is_server_audio_active`（收到音频包置位、终止包复位）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.8。
- commit 或 PR：分支 `feat/cli-e2e-s6-touch-actions`：`34f010b`（SPEC）/ `4518e93`（Red）/ `31b4a59`（Green）。
- 验证及结果：focused `tests/test_cli_touch_actions.py` → 13 passed；client 回归 → 128 passed（排除 3 个既有收集失败文件）。
- 未验证范围：真实服务端触摸接纳/反应（依赖 S1 门槛与部署一致性）、真实播放期的抑制时序。

### 2026-09-20 S7 动态动作

- 交付行为：`dynamics.open` / `read` / `load` / `post`（会话级视图状态：项目/游标/已见 ID；首屏成功后单独报告标记已读结果；按稳定 ID 去重追加；`has_more=false` → `end_of_feed` 成功态且不重复取页；发布后重新读取确认可见，不可见报 `DYNAMICS_NOT_VISIBLE`；单次动作不重复发布）；门面增补 `get_dynamics` / `get_dynamic_comments` / `create_dynamic` / `mark_dynamics_read`。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.9。
- commit 或 PR：分支 `feat/cli-e2e-s7-dynamics-actions`：`a0ac9f9`（SPEC）/ `fcf7357`（Red）/ `6ff7217`（Green）。
- 验证及结果：focused `tests/test_cli_dynamics_actions.py` → 13 passed；client 回归 → 141 passed（排除 3 个既有收集失败文件）。
- 未验证范围：真实动态接口形状与分页行为（依赖受测部署可达性与隔离账号）、发布副作用的清理与重复运行策略（S9 场景层）。

### 2026-09-20 S8 偏好动作

- 交付行为：`preferences.open` / `read` / `update`（会话级快照；无快照时读取动作自动打开；默认按键浅合并、显式 `replace` 完整覆盖；覆盖后重新读取确认目标键，不一致报 `PREFERENCES_NOT_CONFIRMED` 且仅保留目标键差异摘要、失败保留更新前快照）；门面增补 `get_preferences` / `overwrite_preferences`。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.10。
- commit 或 PR：分支 `feat/cli-e2e-s8-preferences-actions`：`53fb008`（SPEC）/ `ace6c7b`（Red）/ `3f4d1f6`（Green）。
- 验证及结果：focused `tests/test_cli_preferences_actions.py` → 13 passed；client 回归 → 154 passed（排除 3 个既有收集失败文件）。
- 未验证范围：真实偏好接口与账号数据（依赖受测部署与隔离账号）、嵌套字段合并语义（当前为顶层浅合并）。

### 2026-09-20 S9 场景引擎与报告

- 交付行为：`scenario.run`（`--scenario` 文件：动作信封数组 + `on_failure` 策略）；失败后默认仅继续只读白名单动作（其余 `skipped`、不贡献退出码），`on_failure="continue"` 时全量继续；终态→退出码矩阵（passed/suppressed/skipped=0、failed=2/3/4、timed_out=5，取最大非零）；每个动作后追加终态记录、场景结束追加 `scenario_result` 汇总；`--report` 默认脱敏元数据（`data_keys` 仅键名）、`--report-include-content` 显式包含完整脱敏 `data`；报告写入失败报 `REPORT_WRITE_FAILED`；场景文件容忍 UTF-8 BOM。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.11。
- commit 或 PR：分支 `feat/cli-e2e-s9-scenario-report`：`e69a4ca`（SPEC）/ `30887e3`（Red）/ `77e2604`（Green）。
- 验证及结果：focused `tests/test_cli_scenario.py` → 17 passed；client 回归 → 171 passed（排除 3 个既有收集失败文件）；子进程冒烟（2 动作场景 + 报告）→ 退出码 0、stdout 3 行合法 JSONL、报告结构正确。
- 未验证范围：真实服务端动作混合场景；产物文件保留（图片/音频副本）未实现（如需可按 S9b 拆分）；报告清理策略由调用方负责。

### 2026-09-20 S3b 等待下一条完整回复 + 真实链路首测

- 交付行为：`reply.wait` 的 `reply_uuid` 变为可选（未提供时等待调用时刻之后第一条新的完整回复，PRD 串行语义）；门面增补 `wait_for_next_reply`；修复 Windows 重定向流编码缺陷（非终端 stdin/stdout/stderr 固定 UTF-8，JSONL 中文不再损坏）。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.12。
- commit 或 PR：分支 `feat/cli-e2e-s3b-next-reply`：`2be86a0`（SPEC）/ `28a5b17`（Red）/ `d00e264`（Green）/ `f31d5df`（编码修复）。
- 验证及结果：focused 6 passed + 编码回归 1 passed；client 回归 178 passed；**真实服务器（release）全链路首测通过**：注册（邀请码）→ `session.connect` ready（1.26s）→ `chat.send_text` ACK（110ms）→ `reply.wait` 完整回复（文本"收到啦，CLI 端到端测试客户端你好呀！"、表情 ×4"卖萌"、TTS 音频 296,012 字节 WAV 落盘索引），退出码 0、stdout 纯 UTF-8 JSONL、日志全在 stderr。
- 未验证范围：`audio.replay` 真实设备播放（本机可试听）；动态/偏好/图片/触摸的受测部署链路；并发回复因果关联。

### 2026-09-20 真实链路扩展验证（动态/偏好/图片/触摸）+ S8b 修复

- 交付行为：S8b——偏好覆盖响应归一化（门面将真实服务端 `{"status": "success"}` 成功形状与错误消息归一化为 `{"ok": bool, "error": str|None}`），修复真实链路把成功写入误判为 `ACK_REJECTED` 的问题。
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/cli/README.md` §1.10（响应归一化条目）。
- commit 或 PR：分支 `feat/cli-e2e-s3b-next-reply`：`da6fca0`（SPEC）/ `d66bfca`（Red）/ `c573ad1`（Green）；PR #185。
- 验证及结果：focused 5 passed；client 回归 183 passed。真实服务器（release）扩展链路全部通过：
  - 动态：`dynamics.open`（10 条真实动态、marked_read=true）/ `dynamics.read`（帖子+评论）/ `dynamics.load`（游标翻页+去重、has_more=true）/ `dynamics.post`（创建并 `visible=true`，账号私有可见）→ 6/6；
  - 偏好：`preferences.update`（confirmed=true）→ `replace=true` 清理 → `preferences.open` 复核 `{}` → 4/4（S8b 修复后）；
  - 图片：`image.select`（3,385B PNG 校验）→ `image.send`（ACK）→ `reply.wait`（视觉回复"哇，这个红蓝配色的图看起来好醒目呀！"，8.8s，TTS 274,500B WAV 落盘）→ 4/4；
  - 触摸：`touch.send`（ACK）→ `reply.wait` 捕获服务端触摸反射（`touch-` UUID、空文本、`moemoe` 表情、`is_ephemeral=true`、`display_in_chat=false`；按 S4 语义 `audio.available=false` 属规范行为）→ 3/3。
- 未验证范围：`audio.replay` 真实设备播放；触摸"服务端音频活跃抑制"时序（需与音频流并发）；并发回复因果关联；各动作其余失败分类的受测部署覆盖。
