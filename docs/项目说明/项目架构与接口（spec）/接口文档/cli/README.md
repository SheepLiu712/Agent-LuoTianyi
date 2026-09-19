# CLI 端到端测试客户端契约

- 状态：§1 为**目标 interface**（待 S3 填写）；§2 为**当前 interface**（S2 已交付，源码见 `client/src/session/`）；§3 待后续切片逐项落地
- 关联：PRD [CLI 端到端测试客户端规格](../../../开发进程文档/需求说明（PRD）/CLI端到端测试客户端规格.md)；实施计划 [CLI端到端测试客户端-可行性分析与实施计划](../../../开发进程文档/实施计划/CLI端到端测试客户端-可行性分析与实施计划.md)；Issue #175
- 阅读约定：与 [`../README.md`](../README.md) 一致——只列跨调用者的稳定入口；每条记录"谁在调用 / 输入输出 / 调用后会发生什么 / 失败时会怎样"；未实现项必须标注"目标"。

## 范围

本域记录 CLI 端到端测试客户端（`client/` 侧、无 GUI）的对外契约：

1. **CLI 动作与机器输出契约**（S3 起填写）：动作名、JSONL 记录字段、稳定错误对象、进程退出码。
2. **无 GUI 会话门面**（S2 起填写）：连接/鉴权就绪/心跳/重连/事件订阅/ACK 等待/回复聚合（音频终止与落盘索引）；供 CLI 与 GUI 共同调用，不得出现第二套协议实现。
3. **后续切片**（S4 媒体与重放、S5/S6 图片与触摸、S7 动态、S8 偏好、S9 场景与报告）：各自 SPEC 阶段在本文增补。

## 契约清单（填写位置）

> 各切片开始（SPEC 阶段）时在此逐项填写；只写本切片要交付的条目，不写未来切片。

### 1. CLI 动作与机器输出（目标，S3）

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
