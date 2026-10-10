# `call.v1` shared contracts

本目录保存服务端 Python 与 Android TypeScript 共同消费的 Proposed `call.v1` wire 契约。双端纯音频 codec 与无状态控制 parser/encoder 已实现，但尚未接入 `call_ws` 或生产端点。

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

连接方向、麦克风/下行流登记、下行 stream ID 不复用、统一控制/音频序号窗口的状态推进、ACK/NACK 响应、resume 重放和取消执行属于未来 Adapter 与传输阶段，不可由纯 codec/parser 测试冒充已验证。

## 控制消息契约

`control.schema.json` 与 `fixtures/control_messages.json` 共同定义 16 种控制消息的精确字段、方向、传输、枚举、ID、UUID、整数范围、嵌套对象边界、稳定错误和规范字段顺序。

fixture 中 `raw` 是精确输入文本；`raw_pattern` 必须先展开，再严格编码为 UTF-8 并计算真实字节数，不能信任预填 byte count。`expected.path` 使用 JSONPath。JSON Schema 无法检测重复字段、`1.0`/指数/`-0` 等整数词法、原始字节数或 lone surrogate，后续 Python 与 TypeScript parser 必须补齐。

控制 parser/encoder 已按以下边界实现并由共享 fixture 参数化验证：

1. raw text 严格 UTF-8，最大 16384 字节，拒绝所有层级重复字段
2. 按 ADR 固定优先级返回 fixture 的稳定错误码与路径，不泄露 Python `UnicodeEncodeError`，也不接受 TypeScript replacement character
3. 只接受规范非负整数词法，排除 bool、float、指数、字符串、NaN/Infinity 与 `-0`
4. 拒绝未知字段、NUL、U+FFFD 和 lone surrogate；`call_id` 按 UUID 校验
5. 纯 parser 只验证单条消息，不检查首个有序帧必须为 1、单调递增、重放、ACK 推进或流登记
6. 编码器输出紧凑 UTF-8，并按 fixture `field_order` 排列；decoder 互操作比较结构值
7. 两端直接参数化消费同一 fixture，运行目标测试、类型检查、格式检查与 `git diff --check`
