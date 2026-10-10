# `call.v1` shared contracts

本目录保存服务端 Python 与 Android TypeScript 共同消费的 wire fixture。当前仅包含 Proposed ADR 阶段 A 的二进制音频帧候选，不表示 `call_ws`、控制消息 schema 或生产端点已经实现。

## 唯一共享来源

`fixtures/audio_frames.json` 同时定义：

- header 常量、字段宽度、字节序、route、flags 与 payload 上限
- 有效帧的结构化输入和精确编码结果
- 无效 decode 字节或 encode 输入及其稳定 codec 错误码

Python 与 TypeScript 测试必须直接读取该文件，不在各自源码中复制 fixture 数据。`encoded_hex` 为完整帧的精确小写十六进制；最大 payload fixture 使用 `encoded_hex_pattern`，其 `prefix` 与有限次数的 `repeat_hex` 拼接结果就是精确完整帧，避免在评审文档中内联 32798 个十六进制字符。

## 阶段 B 实现任务

两端各自实现窄 `encode(frame)` / `decode(bytes)`：

1. 返回 Python `bytes` 或 TypeScript `Uint8Array`
2. `WireAudioFrame` 只属于 Adapter wire 层，不放入 domain
3. 严格验证 fixture 指定的类型、范围、header、长度、版本、route、flags、payload 上限和 PCM16 单声道偶数字节
4. 产生 fixture 指定的稳定错误码，但不决定 WebSocket close code
5. 不实现 registry、plugin loader、自动格式嗅探、混合编码、Base64 生产路径或 WebSocket 接线

连接方向、麦克风/下行流登记、下行 stream ID 不复用、统一控制/音频序号窗口、ACK/NACK、resume 和取消范围属于未来 Adapter 与传输阶段，不可由纯 codec 测试冒充已验证。
