# ADR-0001：`call.v1` wire 协议边界

- 状态：Proposed
- 日期：2026-10-09
- 最近修订：2026-10-10
- 决策者：待非作者开发者审核

## 背景

实时通话需要独立 `call_ws`、JSON 控制消息与二进制音频帧。Web 只处理鉴权、连接和原始帧收发；`adapter.websocket` 解释 wire 协议并持有 `WireAudioFrame`。本 ADR 记录阶段 A 的候选协议，供 Python 与 TypeScript 纯 codec / parser 依据同一夹具实现；状态仍为 Proposed，不表示已经完成人工验收或生产接线。

## 阶段 A 候选决策

### 传输形态

- 控制消息使用 JSON 文本帧，音频使用 WebSocket 二进制帧。
- 生产协议不发送 Base64 音频。未来若确有文本传输需求，只允许在同一窄 codec 接口后增加可替换传输实现，不得引入 registry、plugin loader、自动嗅探或混合编码。
- 单个会话显式选择一个协议版本；版本协商属于未来工作，codec 不猜测版本。

### 二进制帧布局

帧头固定为 15 字节，所有多字节整数使用无符号 32 位大端序：

| 偏移 | 长度 | 字段 | 约束 |
| ---: | ---: | --- | --- |
| 0 | 1 | `version` | 第一版固定为 `1` |
| 1 | 1 | `route` | `CHAT=1`、`CALL=2` |
| 2 | 1 | `flags` | bit 0 为 `FINAL`；其他位必须为 0 |
| 3 | 4 | `stream_id` | `0..UINT32_MAX` |
| 7 | 4 | `seq` | `1..UINT32_MAX`，达到上限后不得回绕 |
| 11 | 4 | `payload_length` | `1..16384`，必须等于实际 payload 字节数 |

帧头不编码方向。`stream_id=0` 是合法 wire 值，预留给客户端麦克风流；服务端下行流从 1 开始且在同一呼叫内不得复用。方向、流登记及下行不复用由 Adapter 校验，纯 codec 不能仅凭帧字节声称已验证这些规则。

第一版 payload 是 PCM16 单声道，因此必须非空且字节数为偶数。采样率和声道数由对应控制消息声明，不增加 wire header 字段。未来格式若允许其他对齐规则，可由调用方给窄 codec 传入显式格式参数，不能根据 payload 自动嗅探。

规范示例：CALL、非 final、`stream_id=1`、`seq=1`、payload `0001` 的完整十六进制为：

```text
0102000000000100000001000000020001
```

其中前 15 字节为 `010200000000010000000100000002`，最后 2 字节为 payload。

### codec 边界

阶段 B 的两端实现只提供等价的窄接口：

```text
encode(frame) -> bytes | Uint8Array
decode(bytes | Uint8Array) -> WireAudioFrame
```

`WireAudioFrame` 属于 Adapter wire 层，不放入 `domain`，也不复用供应商 `AudioFrame` 或通话语义对象。codec 只负责字段类型、范围、固定头、长度、版本、route、flags、payload 上限和 PCM16 单声道对齐；连接方向、流登记、统一 seq 窗口、ACK/NACK、重放和 WebSocket close code 不属于纯 codec。

### 稳定 codec 错误集合

两端必须把夹具中的失败归一化为以下稳定错误码；异常类型和文字可以各端自定，WebSocket close code 尚未决定：

| 错误码 | 条件 |
| --- | --- |
| `HEADER_TRUNCATED` | 输入不足 15 字节 |
| `UNSUPPORTED_VERSION` | `version != 1` |
| `INVALID_ROUTE` | route 不是 `1` 或 `2` |
| `UNSUPPORTED_FLAGS` | flags 含 bit 0 以外的位 |
| `INVALID_SEQ` | seq 为 0 |
| `FIELD_OUT_OF_RANGE` | encode 输入整数超出对应无符号字段范围 |
| `INVALID_FIELD_TYPE` | encode 输入字段不是规定的整数或字节序列 |
| `PAYLOAD_LENGTH_MISMATCH` | 声明长度与实际 payload 不同 |
| `PAYLOAD_TOO_LARGE` | payload 超过 16384 字节 |
| `EMPTY_PAYLOAD` | payload 长度为 0 |
| `PCM_ALIGNMENT_ERROR` | PCM16 单声道 payload 长度不是偶数 |

`contracts/call_v1/fixtures/audio_frames.json` 是字段常量、有效 golden 与错误映射的唯一共享来源；实现测试不得复制一套会漂移的 fixture 常量。

### JSON 控制消息

- 控制帧是最大 16384 UTF-8 字节的 JSON 文本对象。UTF-8 必须严格解码；非法字节序列归一化为 `BAD_JSON`，不得替换为 U+FFFD。顶层及嵌套对象都拒绝重复字段和未知字段。
- `contracts/call_v1/control.schema.json` 是 Draft 2020-12 结构契约；`contracts/call_v1/fixtures/control_messages.json` 是原始文本、方向、传输、稳定错误和路径的共享事实来源。JSON Schema 不能检测重复字段、整数词法、原始 UTF-8 字节数或 lone surrogate，这些由后续双端 raw-text parser 在 schema 校验前后补足。
- 普通会话业务消息与二进制音频共享每方向一条 `1..UINT32_MAX` 序列。会话首个有序帧声明为 1，但这是 Adapter 会话状态规则，不是纯 parser 限制；纯 parser 必须接纳范围内任意 `seq`，包括上界。
- `call.switch_prepare` / `call.switch_ready` 走 `chat_ws` 且不占通话序号；`call.resume` / `call.resumed`、`ack`、`nack` 是 `call_ws` 握手或反馈，也不占序号、不进入重放缓冲。
- `call.resume` 携带客户端已连续结算的服务端游标；`call.resumed` 同时回传服务端已连续结算的客户端游标和客户端声明的服务端游标。游标与 `ack_seq` 可为 0，`missing_seq` 从 1 开始。
- `playback.stop` 是服务端有序取消消息；`retire_server_seq.from <= through < playback.stop.seq`。`playback.stopped` 只回传 `response_id` 与 `stop_seq`，不重复 `stream_id`。
- `connected_at_ms` 与 `active_duration_ms` 使用 `0..9007199254740991`，避免把 Unix epoch 毫秒错误限制为 UINT32，同时保证 Python 与 JavaScript 精确互操作。
- 所有整数只接受十进制规范词法 `0|[1-9][0-9]*`；拒绝布尔值、负数、`-0`、小数、指数、字符串及 NaN/Infinity。Schema 的 `integer` 不能区分 `1` 与 `1.0`，因此词法限制仍由 raw-text parser 承担。
- 字符串按 Unicode 标量值处理，拒绝 NUL、U+FFFD 与 lone surrogate。非法 UTF-8 或不能形成合法 JSON 字符串的 surrogate 归 `BAD_JSON`；成功解码后字段内出现 NUL 或 U+FFFD 归 `INVALID_FIELD_VALUE`。

控制消息稳定错误码为 `BAD_JSON`、`CONTROL_TOO_LARGE`、`TOP_LEVEL_NOT_OBJECT`、`DUPLICATE_FIELD`、`MISSING_FIELD`、`UNKNOWN_FIELD`、`UNKNOWN_TYPE`、`UNSUPPORTED_PROTOCOL`、`INVALID_TRANSPORT`、`INVALID_DIRECTION`、`INVALID_FIELD_TYPE`、`FIELD_OUT_OF_RANGE`、`INVALID_FIELD_VALUE`、`INVALID_ENUM`。若同一输入有多个问题，按 UTF-8/尺寸 → JSON 语法/重复字段 → 顶层对象 → protocol → type → transport/direction → required → unknown → field type → range → enum → cross-field 的顺序报告首个错误。字段路径使用 JSONPath 风格（如 `$.audio.sample_rate`），消息级错误使用 `$`。

JSON 编码器输出无空白 UTF-8，字段顺序按共享 fixture 的 `field_order` 固定，且不得输出 NUL、U+FFFD、lone surrogate、NaN 或 Infinity。双方不依赖对象运行时的默认枚举顺序；跨端 decoder 比较结构值，golden 编码比较各自按该顺序产生的规范文本。

控制可靠性机制只借鉴官方文档中已经公开的机制事实：Socket.IO connection-state recovery 保存会话与 offset 并在有限窗口内重放遗漏 packet；ASP.NET Core 9 SignalR stateful reconnect 需要两端启用，并通过 buffer、ACK 与 replay 恢复消息。`call.v1` 的字段、序号和取消范围均为本项目自研契约，不宣称是上述框架的行业标准实现。

- Socket.IO: <https://socket.io/docs/v4/connection-state-recovery>
- SignalR: <https://learn.microsoft.com/aspnet/core/signalr/configuration#configure-stateful-reconnect>

## 尚未冻结

- JSON 控制 schema、统一 `seq`、ACK/NACK、resume 与取消范围已形成阶段 A 工程候选，但 ADR 仍为 Proposed，须经非作者开发者审核后才能作为生产实现依据。
- Python 与 TypeScript 无状态 parser/encoder 已实现；endpoint、重放缓冲、会话状态校验和 WebSocket close code 未实现，纯 parser 不能冒充这些生产能力。
- 连接方向与流登记违规对应的稳定 Adapter 错误、WebSocket close code、版本协商、供应商接入和 Android 音频实现另行决定。

## 后果

- 阶段 A 可以交付共享 schema/fixture 和两端纯 codec/parser 的精确任务规范，但不得宣称 `call_ws` 已具备生产兼容性。
- 在本 ADR 经非作者开发者审核并改为 Accepted 前，不把候选 parser 接入生产 endpoint，也不实现生产 ACK/NACK、resume 或发送链路。
- 后续若修改任一 header 常量或错误语义，必须先修改 ADR 与共享 fixture，再同步两端实现和互操作测试。
