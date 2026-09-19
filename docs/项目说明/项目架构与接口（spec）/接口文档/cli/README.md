# CLI 端到端测试客户端契约

- 状态：**目标 interface**（源码尚未实现；随 S0-S9 行为切片逐步落地，逐项转为"当前"）
- 关联：PRD [CLI 端到端测试客户端规格](../../../开发进程文档/需求说明（PRD）/CLI端到端测试客户端规格.md)；实施计划 [CLI端到端测试客户端-可行性分析与实施计划](../../../开发进程文档/实施计划/CLI端到端测试客户端-可行性分析与实施计划.md)；Issue #175
- 阅读约定：与 [`../README.md`](../README.md) 一致——只列跨调用者的稳定入口；每条记录"谁在调用 / 输入输出 / 调用后会发生什么 / 失败时会怎样"；未实现项必须标注"目标"。

## 范围

本域记录 CLI 端到端测试客户端（`client/` 侧、无 GUI）的对外契约：

1. **CLI 动作与机器输出契约**（S3 起填写）：动作名、JSONL 记录字段、稳定错误对象、进程退出码。
2. **无 GUI 会话门面**（S2 起填写）：连接/鉴权就绪/心跳/重连/事件订阅/ACK 等待/回复聚合（音频终止与落盘索引）；供 CLI 与 GUI 共同调用，不得出现第二套协议实现。
3. **后续切片**（S4 媒体与重放、S5/S6 图片与触摸、S7 动态、S8 偏好、S9 场景与报告）：各自 SPEC 阶段在本文增补。

## 契约清单（填写位置）

> 各切片开始（SPEC 阶段）时在此逐项填写；只写本切片要交付的条目，不写未来切片。

### 1. CLI 动作与机器输出（目标，待 S3 填写）

- 动作名与语义：待填写
- JSONL 记录字段（schema 版本 / 时间 / 会话 ID / 动作 ID / 事件类别 / 状态 / 耗时 / 关联 ID / 数据摘要 / 错误对象）：待填写
- 进程退出码分类：待填写
- 失败方式：待填写

### 2. 无 GUI 会话门面（目标，S2）

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
