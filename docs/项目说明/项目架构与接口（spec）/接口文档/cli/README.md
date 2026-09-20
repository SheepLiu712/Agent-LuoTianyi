# CLI 端到端测试客户端契约

- 状态：§1、§2 为**当前 interface**（§1 由 S3-S9 交付，§2 由 S2 交付）；§3 保留为后续扩展占位
- 关联：PRD [CLI 端到端测试客户端规格](../../../开发进程文档/需求说明（PRD）/CLI端到端测试客户端规格.md)；实施计划 [CLI端到端测试客户端-可行性分析与实施计划](../../../开发进程文档/实施计划/CLI端到端测试客户端-可行性分析与实施计划.md)；Issue #175
- 阅读约定：与 [`../README.md`](../README.md) 一致——只列跨调用者的稳定入口；每条记录"谁在调用 / 输入输出 / 调用后会发生什么 / 失败时会怎样"；未实现项必须标注"目标"。

## 范围

本域记录 CLI 端到端测试客户端（`client/` 侧、无 GUI）的对外契约：

1. **CLI 动作与机器输出契约**（S3 起填写）：动作名、JSONL 记录字段、稳定错误对象、进程退出码。
2. **无 GUI 会话门面**（S2 起填写）：连接/鉴权就绪/心跳/重连/事件订阅/ACK 等待/回复聚合（音频终止与落盘索引）；供 CLI 与 GUI 共同调用，不得出现第二套协议实现。
3. **后续切片**（S4 媒体与重放、S5/S6 图片与触摸、S7 动态、S8 偏好、S9 场景与报告）：各自 SPEC 阶段在本文增补。

## 契约清单（填写位置）

> 各切片开始（SPEC 阶段）时在此逐项填写；只写本切片要交付的条目，不写未来切片。

### 1. CLI 动作与机器输出（当前 interface，S3 交付）

#### 1.1 入口与动作信封

- 模块路径：`client/src/cli/`；可执行入口为 `client/cli.py`。实现只依赖 Python 标准库并复用 §2 的 `HeadlessSession`。
- 非交互模式接收单个 JSON 动作或从 stdin 逐行接收 JSON 动作；交互模式仅增加 stderr 提示符，仍把每行 JSON 交给同一动作执行器，不形成第二套业务路径。
- 输入信封：`{"action": str, "action_id": str?, "params": object?}`。缺失 `action_id` 时生成本进程内唯一 ID；`params` 默认 `{}`。未知字段允许忽略，未知动作、非对象输入、字段类型错误或缺少必需参数属于输入错误。
- 一次进程只持有一个 `HeadlessSession`。除 `session.connect` 外的会话动作使用当前会话；进程结束时关闭会话。

#### 1.2 S3 动作

| 动作 | 必需/可选参数 | 成功行为 |
| --- | --- | --- |
| `session.connect` | `base_url`、`username`；`password` 或 `password_env` 二选一；可选 `verify_ssl`、`timeout` | 创建 `HeadlessSession` 并等待 ready；不得请求持久化凭据 |
| `session.status` | 无 | 返回当前状态；尚未连接时返回 `new` |
| `session.close` | 无 | 幂等关闭当前会话；未创建会话也成功 |
| `chat.send_text` | 非空 `text`；可选 `client_msg_id`、`ack_timeout` | 调用 `HeadlessSession.send_text`；缺少 ID 时生成；只以肯定 ACK 判定该动作通过，不把 ACK 当作回复 |
| `reply.wait` | `reply_uuid`；可选 `timeout`、`non_empty`、`contains`、`regex` | 等待完整回复，随后执行文本断言 |
| `reply.read` | `reply_uuid`；可选 `non_empty`、`contains`、`regex` | 读取已聚合回复；不存在或未完成属于动作失败，完整回复执行文本断言 |

- 文本断言针对 `texts` 按到达顺序以空字符串连接后的结果；`non_empty=true` 要求结果非空，`contains` 要求包含给定字符串，`regex` 使用 Python 正则搜索。断言不满足使用 `ASSERTION_FAILED`。
- `reply.wait/read` 的 `data` 固定包含：`reply_uuid`、`text`、`texts`、`expressions`、`complete`、`audio`、`audio_error`、`error_code`、`display_in_chat`、`is_ephemeral`。`audio` 从 S3 起固定为 `{available, byte_count, format, reference}`；默认不输出 Base64 或绝对路径，S4 只填充这些既有字段。

#### 1.3 JSONL 输出

- schema 版本为字符串 `"1.0"`。stdout 只允许 UTF-8 JSON Lines；每个已解析动作恰好产生一条终态记录，stderr 只承载交互提示或经脱敏的诊断。
- 终态记录字段：

```json
{
  "schema_version": "1.0",
  "timestamp": "RFC3339 UTC",
  "session_id": "本进程稳定 ID",
  "action_id": "输入或生成的动作 ID",
  "action": "稳定动作名或 null",
  "event": "action_result",
  "status": "passed | failed | timed_out",
  "duration_ms": 0,
  "correlation_id": "client_msg_id/reply_uuid 或 null",
  "data": {},
  "error": null
}
```

- 成功时 `error=null`；失败时 `data` 只保留已确认的非敏感证据。时间和耗时允许测试注入，但字段不可省略。
- 稳定错误对象为 `{"code": str, "message": str, "category": "assertion | input | auth_transport | timeout"}`。S3 使用的稳定 code 至少包括：`INVALID_INPUT`、`UNKNOWN_ACTION`、`SESSION_NOT_READY`、`AUTH_OR_TRANSPORT_FAILED`、`ACK_REJECTED`、`REPLY_NOT_FOUND`、`ASSERTION_FAILED`、`TIMEOUT`。

#### 1.4 退出码

| 退出码 | 分类 | 例子 |
| --- | --- | --- |
| `0` | 全部动作通过 | 肯定 ACK、断言通过、正常关闭 |
| `2` | 断言或可观察结果失败 | 文本断言失败、reply 不存在、否定 ACK |
| `3` | 输入/配置错误 | JSON 非法、缺参、未知动作、正则非法 |
| `4` | 认证/传输错误 | 登录失败、会话未 ready、连接或发送失败 |
| `5` | 超时 | ready、ACK 或回复等待超时 |

- 多动作进程继续处理后续合法输入；最终退出码取所有动作中数值最大的非零码。输入行无法解析时仍输出一条 `action=null` 的结构化失败记录。

#### 1.5 凭据与敏感内容遮蔽

- `password`、message/login token、`Authorization` 值和音频 Base64 不得出现在 stdout、stderr、稳定错误对象或未处理异常文本中。
- redaction 在唯一序列化/诊断边界递归执行：键名大小写归一后命中 `password`、`token`、`authorization`、`audio_base64` 的值输出为 `"***"`；已知敏感值即使出现在普通字符串或异常消息中也替换为 `"***"`。
- `session.connect` 可从进程环境读取 `password_env` 指定的变量；环境变量名可以输出，变量值必须登记为敏感值。命令行直接提供密码虽可用，但帮助、回显和输出均不得显示其值。

#### 1.6 媒体回复与重放（S4 交付）

- S4 只填充 S3 已发布的 reply 输出结构，不增加或删除 `reply.wait/read.data.audio` 字段：
  - `available`：回复完整、非临时、无 `audio_error`，且索引文件存在、非空并可识别为音频时为 `true`；
  - `byte_count`：索引文件当前字节数，不读取时为 `0`；
  - `format`：由文件解码确认的格式小写名（S4 为 `wav`），不可识别时为 `null`；
  - `reference`：仅输出文件名形式的本地引用，不输出绝对路径；无可用音频时为 `null`。
- reply 输出保留按到达顺序聚合的 `expressions`。stdout、stderr 和 JSONL 均不得包含音频 Base64 正文。

新增动作：

| 动作 | 必需/可选参数 | 成功行为 |
| --- | --- | --- |
| `audio.replay` | 必需 `reply_uuid` | 只引用当前会话中已完整结束、非临时、无音频错误且已成功落盘的回复；校验文件格式后，由播放后端阻塞至正常结束，返回 `playback="completed"` 和与 reply 相同的音频元数据 |

- 播放后端是无 GUI 的可替换 interface：`play(path: Path) -> PlaybackResult`。生产默认后端先解析 WAV，再使用当前平台已有播放能力；不得依赖 Qt、Live2D 或 GUI 播放状态。
- `audio.replay` 失败均为 S3 退出码 `2`、`category="assertion"`，并使用以下稳定分类：

| code | 条件 |
| --- | --- |
| `AUDIO_REPLY_NOT_FOUND` | 当前会话不存在指定回复 |
| `AUDIO_NOT_READY` | 回复存在但尚未收到终止包 |
| `AUDIO_EPHEMERAL` | `is_ephemeral=true` 或 `display_in_chat=false` |
| `AUDIO_STREAM_FAILED` | 回复以 `audio_error=true` 结束；保留文本但不可重放 |
| `AUDIO_FILE_MISSING` | 回复声称有落盘索引，但文件不存在或为空 |
| `AUDIO_FORMAT_INVALID` | 文件存在但不能解码为支持的 WAV |
| `DEVICE_UNAVAILABLE` | 文件合法，但默认播放后端没有可用设备或平台播放能力 |
| `PLAYBACK_INTERRUPTED` | 播放已开始但未正常结束 |

- 离线默认验收范围：索引规则、WAV 解码校验、媒体元数据、全部稳定失败分类，以及注入 Fake 后端时的“开始并正常结束”。
- 真实设备上"播放开始并正常结束"属于 external 验收：要求可用输出设备和操作者显式启用；默认测试不得访问真实音频设备，也不得把 `device_unavailable` 伪装成成功。

#### 1.7 图片动作（S5 交付）

同一会话内保持"当前图片选择"状态；状态由 CLI 动作执行器会话级持有（与 PRD"会话包含当前图片选择"一致）。

| 动作 | 必需/可选参数 | 成功行为 |
| --- | --- | --- |
| `image.select` | 必需 `path`；可选 `ack_timeout` | 先发送选择开始信号并取得肯定 ACK；再校验本地文件（可读、类型、大小），通过后记录当前选择；输出 `selected=true`、`reference`（仅文件名）、`mime_type`、`byte_count` |
| `image.cancel` | 可选 `ack_timeout` | 发送取消信号并取得肯定 ACK 后清空当前选择；输出 `selected=false` |
| `image.send` | 可选 `path`（显式路径覆盖当前选择）、`client_msg_id`、`ack_timeout` | 使用当前选择或显式路径，经当前客户端既有编码（读文件 → 临时副本 → Base64 → MIME）发送图片并取得肯定 ACK；输出 `ack=true` 与关联 ID |

- 选择状态语义：选择失败（信号未 ACK 或本地校验未通过）时一并清空已有选择，避免误发旧文件；取消后 `image.send` 必须以 `IMAGE_NOT_SELECTED` 失败（不可误发之前选中的文件）；发送成功后保留当前选择（允许重复发送）。
- 媒体规则来源：`client/src/utils/image_rules.py` 为客户端唯一规则来源，镜像服务端 `server/src/legacy/chat_input_adapter.py` 的 `ALLOWED_IMAGE_MIME_TYPES` 与 `MAX_IMAGE_BYTES`；`client/tests/test_image_rules_mirror.py` 读取服务端源码断言一致以防漂移。其他模块（含 CLI）不得另行维护独立常量。
- 编码复用：`client/src/utils/image_encoding.py` 承载客户端既有图片编码管道（自 `MessageProcessor` 抽取并与 GUI 共用，不复制第二套）；MIME 映射覆盖 `jpg/jpeg/png/gif/bmp/webp`（与规则集合一致）。
- 稳定失败分类：
  - `IMAGE_FILE_NOT_FOUND` / `IMAGE_FILE_UNREADABLE` / `IMAGE_FILE_EMPTY` / `IMAGE_TYPE_UNSUPPORTED` / `IMAGE_NOT_SELECTED` → `category="input"`、退出码 3；
  - `ACK_REJECTED`、`TIMEOUT` 沿用 S3 语义；发送失败不得自动改用新的 `client_msg_id` 重发。
  - stdout、stderr 与 JSONL 不出现本地绝对路径（只输出 `reference` 文件名）。
- 门面增补（§2 当前 interface 的 S5 扩展）：`HeadlessSession.select_image()`、`cancel_image_selection()`、`send_image(image_path, *, client_msg_id, ack_timeout)`；编码失败抛 `SessionImageError`。
- 真实链路依赖 S1 契约与部署一致性门槛；未满足时只交付客户端状态行为并显式标记 external skip。

#### 1.8 触摸动作（S6 交付）

| 动作 | 必需/可选参数 | 行为 |
| --- | --- | --- |
| `touch.send` | 必需 `touch_area`（非空字符串或非空字符串列表）；可选 `click_frequency`（对象）、`touch_meta`（对象）、`client_msg_id`、`ack_timeout` | 输入校验后：若会话处于"服务端音频活跃"等效状态则本地抑制并返回 `suppressed`；否则经当前客户端触摸发送能力发送并取得肯定 ACK |

- 抑制语义（headless 等效）："服务端音频活跃"定义为*已收到某回复的音频包且该回复尚未收到终止包*；与产品客户端"音频播放期间抑制触摸"的可观察意图一致（无播放层时的等效口径）。抑制时不发送任何协议事件、不伪造 ACK 或回复；动作结果为 `status="suppressed"`、`data={"suppressed": true, "reason": "server_audio_active"}`、退出码 `0`。
- 发送成功结果为 `{"ack": true}`；`ACK_REJECTED` / `TIMEOUT` 沿用 S3 语义。
- 输入校验：`touch_area` 必须为非空字符串或非空字符串列表；`click_frequency` / `touch_meta` 必须为对象；违反为 `INVALID_INPUT`（退出码 3）。
- 门面增补：`HeadlessSession.send_touch(touch_area, click_frequency=None, touch_meta=None, *, client_msg_id=None, ack_timeout=10.0)` 与只读属性 `is_server_audio_active`。
- 真实链路依赖 S1 契约与部署一致性门槛；未满足时只交付本地抑制与客户端状态行为并显式标记 external skip。

#### 1.9 动态动作（S7 交付）

会话级动态视图状态（CLI 执行器持有）：当前项目列表、下一页游标、是否还有更多、已见动态 ID 集合。

| 动作 | 必需/可选参数 | 成功行为 |
| --- | --- | --- |
| `dynamics.open` | 可选 `limit` | 获取首屏成功后将 `items` 与游标存入视图；随后尝试标记已读（结果单独报告）；输出 `items`、`count`、`has_more`、`marked_read`（失败时附 `mark_error`，不抹掉首屏读取成功的证据） |
| `dynamics.read` | 必需 `dynamic_id`；可选 `comment_limit` | 获取首批评论；若该动态在已加载视图中则一并输出帖子（否则 `post=null`）；输出 `dynamic_id`、`post`、`comments`、`comment_count` |
| `dynamics.load` | 可选 `limit` | 使用服务端返回的游标取下一页并追加（按稳定 ID 去重，`id` 缺失时回退 `dynamic_id`）；`has_more=false` 时输出稳定 `end_of_feed=true` 成功态（不重复取页）；未打开视图时报 `DYNAMICS_NOT_OPENED` |
| `dynamics.post` | 必需 `content`（非空） | 有副作用：创建动态后重新读取确认可见；输出 `content_length`、`preview`（前 80 字符）、`dynamic_id`（可得时）、`visible`；创建成功但不可见时报 `DYNAMICS_NOT_VISIBLE`；单次动作不自动重复发布 |

- 分页只使用服务端返回的游标；`has_more=false` 是成功结束状态而非错误。
- 失败分类：`DYNAMICS_NOT_OPENED`、`DYNAMICS_NOT_VISIBLE`、`INVALID_INPUT` → `category="input"`（不可见为 `assertion`）；`ACK_REJECTED`/`TIMEOUT` 沿用 S3 语义。
- 门面增补：`HeadlessSession.get_dynamics(limit=50, cursor=None)`、`get_dynamic_comments(dynamic_id, limit=100, cursor=None)`、`create_dynamic(content)`、`mark_dynamics_read()`。
- 外部运行前置：隔离测试账号、唯一数据前缀、清理步骤（计划 §5.5）；真实读取依赖受测部署可达。

#### 1.10 偏好动作（S8 交付）

会话级偏好快照（CLI 执行器持有）。

| 动作 | 必需/可选参数 | 成功行为 |
| --- | --- | --- |
| `preferences.open` | — | 从服务端读取完整偏好对象并保存为当前快照；输出 `preferences`（完整 JSON 对象） |
| `preferences.read` | — | 输出当前快照；无快照时先自动执行打开（读取服务端）再输出 |
| `preferences.update` | 必需 `values`（对象）；可选 `replace`（布尔，默认 false） | 默认"读取最新 → 按键浅合并 → 覆盖接口 → 重新读取 → 比较目标键"；`replace=true` 时以 `values` 完整覆盖；成功输出 `updated_keys`、`confirmed=true` 与重新读取后的 `preferences` |

- 更新失败（目标键读回不一致）报 `PREFERENCES_NOT_CONFIRMED`（`category="assertion"`），数据中仅保留目标键的 `expected`/`actual` 差异摘要，不转储完整个人信息；失败时保留更新前快照（不更新会话快照）。
- `INVALID_INPUT`：`values` 缺失或非对象、`replace` 非布尔。
- `ACK_REJECTED` / `TIMEOUT` 沿用 S3 语义（覆盖接口拒绝）。
- 门面增补：`HeadlessSession.get_preferences()`、`overwrite_preferences(preferences)`。
- 真实链路依赖受测部署可达；external 账号数据由夹具管理（计划 §5.5）。

#### 1.11 场景引擎与报告（S9 交付）

场景输入（JSON 文件，`--scenario`）：

```json
{
  "actions": [{"action": "session.connect", "params": {}}, {"action": "session.status"}],
  "on_failure": "stop_side_effects"
}
```

- `actions`：非空数组，逐项为既有动作信封（`action`/`action_id?`/`params?`）；按顺序在同一会话内执行。
- `on_failure`：可选，默认 `stop_side_effects`；另一值 `continue`。
- 非法场景（文件缺失/非 JSON/非对象、`actions` 缺失或为空、条目缺有效动作名、`on_failure` 非法）→ 单条记录（`action="scenario.run"`、`status="failed"`、`error.code="INVALID_SCENARIO"`、`category="input"`）、退出码 3。

失败策略：

- 出现 `failed`/`timed_out` 后，默认仅继续执行**只读白名单**动作：`session.status`、`reply.read`、`reply.wait`、`preferences.read`、`dynamics.read`、`dynamics.load`、`audio.replay`、`session.close`；其余动作记为 `status="skipped"`（`data.reason="after_failure"`，不贡献退出码）。
- `on_failure="continue"` 时不做跳过。

终态 → 退出码矩阵：

| 终态 | 退出码贡献 |
| --- | --- |
| `passed` / `suppressed` / `skipped` | 0 |
| `failed`（断言=2 / 输入=3 / 认证传输=4，沿用 S3 分类） | 2 / 3 / 4 |
| `timed_out` | 5 |

- 场景最终退出码 = 各动作出现过的最大非零退出码（全为 0 则 0）。
- 每个动作后追加一条终态记录；场景结束追加一条汇总记录：`action="scenario.run"`、`event="scenario_result"`、`status=passed|failed`、`data={action_count, passed, failed, timed_out, skipped, suppressed, exit_code}`。

报告（`--report PATH`，可选）：

- 单文件 JSON；默认只含脱敏结构化元数据：每个动作记录 `action`/`status`/`duration_ms`/`correlation_id`/`error` 与 `data_keys`（仅键名，不含内容值）；另含场景 `summary`、起止时间与最终 `exit_code`。
- `--report-include-content` 显式开启后，动作记录改用 `data`（完整、经统一脱敏）替代 `data_keys`。
- 保留与清理：只写该单文件、不产生其他产物；清理由调用方负责（报告路径由调用方指定）。写入失败时汇总记录附 `error.code="REPORT_WRITE_FAILED"`（`category="input"`）并计入退出码。
- 报告与 stdout 均不得出现凭据、音频 Base64 或本地绝对路径。

#### 1.12 等待下一条完整回复（S3b 交付）

- `reply.wait` 的 `reply_uuid` 变为**可选**：提供时保持 S3 语义（等待指定 UUID 的完整回复）；未提供时等待*调用时刻之后第一条新的完整回复*（PRD 串行语义："同一时刻只允许一个期待回复的动作"），并返回该回复的 `reply_uuid` 与聚合结果；超时沿用 `TIMEOUT`（退出码 5）。
- 门面增补（§2 当前 interface 扩展）：`HeadlessSession.wait_for_next_reply(timeout)`——按完成顺序返回下一条完整回复；并发多条回复时因果关联不保证（与 PRD 口径一致，结果标记证据强度）。
- 既有限制保留：服务端回复不携带原始客户端消息 ID，无法将回复与某次输入做确定性关联；串行使用是默认安全口径。

### 2. 无 GUI 会话门面（当前 interface，S2 交付）

#### 2.1 归属与调用者

- 模块路径：`client/src/session/headless_session.py`，由 `client/src/session/__init__.py` 导出稳定类型。
- `HeadlessSession` 是 CLI 使用的无 GUI 会话门面；后续 GUI 迁移后也应调用同一门面或其下沉的无 UI 组件，不得复制 WebSocket 协议、ACK 关联或回复聚合实现。
- 本切片内部组合既有 `NetworkClient` 与 `WsTransport`：HTTP 登录仍由 `NetworkClient` 完成；鉴权、心跳、断线重连、协议解析和按 `reply_to` 关联 ACK 仍由 `WsTransport` 完成。
- S2 不迁移现有 GUI，不依赖 Qt、Live2D、`MultiMediaStream` 或音频播放设备。

#### 2.2 状态与事件模型

```python
class SessionState(str, Enum):
    NEW = "new"
    CONNECTING = "connecting"
    READY = "ready"
    DISCONNECTED = "disconnected"
    AUTH_FAILED = "auth_failed"
    CLOSED = "closed"

@dataclass(frozen=True)
class SessionEvent:
    kind: str                    # state / agent_state / agent_message / reply_completed / system_message
    data: object

@dataclass(frozen=True)
class AggregatedReply:
    uuid: str
    texts: tuple[str, ...]
    expressions: tuple[str, ...]
    complete: bool
    audio_path: str | None
    audio_error: bool
    error_code: str | None
    display_in_chat: bool
    is_ephemeral: bool
```

- `state` 是可同步读取的当前会话状态。只有 `READY` 允许发送业务输入。
- `AgentMessage` 原始包按到达顺序通过 `agent_message` 事件发布；同一 UUID 的文本、表情和已解码音频分别聚合。
- 仅 `is_audio_terminal(message)` 为真时将回复标记为完整并发布一次 `reply_completed`。当前协议没有包序号，S2 不声称能够对内容相同的重复包做确定性去重。
- 非临时、`display_in_chat=true`、无 `audio_error` 且有音频字节的完整回复落盘至构造时指定的 `audio_output_dir/<安全 UUID>.wav`，并通过 `audio_path` 建立索引。临时、隐藏或音频失败回复不得进入音频索引；音频失败仍保留已聚合文本并结束等待。

#### 2.3 公开 interface

```python
class HeadlessSession:
    def __init__(
        self,
        base_url: str,
        *,
        verify_ssl: bool = True,
        audio_output_dir: str | Path | None = None,
        network_client: NetworkClient | None = None,
    ) -> None: ...

    @property
    def state(self) -> SessionState: ...

    def connect(
        self,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
    ) -> None: ...

    def connect_with_token(
        self,
        username: str,
        login_token: str,
        *,
        timeout: float = 10.0,
    ) -> None: ...

    def close(self) -> None: ...
    def subscribe(self, listener: Callable[[SessionEvent], None]) -> Callable[[], None]: ...
    def send_text(self, text: str, *, client_msg_id: str, ack_timeout: float = 10.0) -> dict: ...
    def get_reply(self, reply_uuid: str) -> AggregatedReply | None: ...
    def wait_for_reply(self, reply_uuid: str, timeout: float) -> AggregatedReply: ...
    def audio_path_for(self, reply_uuid: str) -> str | None: ...
```

- `connect` 调用既有 HTTP 登录但不请求持久化 token；`connect_with_token` 调用既有自动登录。二者都必须等待 `WsTransport` 完成 WebSocket 鉴权并进入 ready，成功后才返回。
- `subscribe` 注册线程安全的同步监听器并返回幂等取消函数。监听器由 `WsTransport` 后台线程调用，调用者若需要 UI 更新，必须自行切换到 UI 线程；门面不得引入 Qt 调度。
- `send_text` 原样委托 `NetworkClient.send_chat`，由 `WsTransport` 生成/发送协议事件并等待 ACK；返回值保持既有 ACK 字典语义。门面不得把 ACK 当成完整回复。
- `get_reply` 返回当前快照；`wait_for_reply` 等待指定 UUID 的终止包。S2 不提供“下一条回复与某次输入确定关联”的并发能力。
- `close` 停止既有 `WsTransport`，唤醒等待者并进入不可发送的 `CLOSED`；重复关闭无副作用。

#### 2.4 线程模型与失败行为

- 沿用 `WsTransport` 的“一个 daemon 后台线程 + 该线程内 asyncio loop”模型；`HeadlessSession` 不创建第二个网络线程或事件循环，只用锁与条件变量保护状态、订阅者、聚合结果和等待者。
- HTTP 登录失败抛出 `SessionConnectionError`，状态为 `AUTH_FAILED`；WebSocket 在 timeout 内未 ready 抛出 `SessionReadyTimeout`，状态为 `DISCONNECTED`。异常文本不得包含密码或 token。
- 非 `READY` 状态调用 `send_text` 抛出 `SessionNotReadyError`。既有 ACK 的否定、断线和超时结果不改写为成功，也不自动生成新的 `client_msg_id`。
- `wait_for_reply` 超时抛出 `ReplyTimeoutError`；关闭会话后仍在等待的调用抛出 `SessionClosedError`。
- 缺少 UUID 的 Agent 包仍可作为原始事件观察，但不能建立聚合项或音频文件。非法 UUID 不得用于文件路径，且该回复不进入音频索引。

### 3. 其他切片（目标，按需增补）

（S4-S9 各自 SPEC 阶段填写。）
