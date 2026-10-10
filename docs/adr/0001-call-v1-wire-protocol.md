# ADR-0001：`call.v1` wire 协议边界

- 状态：Proposed
- 日期：2026-10-09
- 最近修订：2026-10-10
- 决策者：待非作者开发者审核

## 背景

实时通话需要独立 `call_ws`、JSON 控制消息与二进制音频帧。Web 只处理鉴权、连接和原始帧收发；`adapter.websocket` 解释 wire 协议并持有 `WireAudioFrame`。本 ADR 记录阶段 A 的候选协议，供 Python 与 TypeScript 纯 codec 依据同一夹具实现；状态仍为 Proposed，不表示已经完成人工验收或生产接线。

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

## 尚未冻结

- JSON 控制消息的完整 schema、必填字段和 parser/endpoint 均不在阶段 A 实现。
- 控制消息如何占用统一 `seq`、ACK/NACK、resume、重放缓冲与取消范围仍待审；F2 spec 中的 envelope 仅是候选草案。
- `call.switch_prepare` 的聊天方向序号与后续 `call_ws` 双向序号边界尚待非作者审核，不能提前冻结 ACK/NACK 或切换 envelope。
- 连接方向与流登记违规对应的稳定 Adapter 错误、WebSocket close code、版本协商、供应商接入和 Android 音频实现另行决定。

## 后果

- 阶段 A 可以交付共享 fixture 和两端纯 codec 的精确任务规范，但不得宣称 `call_ws` 已具备生产兼容性。
- 在本 ADR 经非作者开发者审核并改为 Accepted 前，不实现 parser、endpoint、ACK/NACK、resume 或生产发送链路。
- 后续若修改任一 header 常量或错误语义，必须先修改 ADR 与共享 fixture，再同步两端实现和互操作测试。
