# ADR-0001：`call.v1` wire 协议边界

- 状态：Proposed
- 日期：2026-10-09
- 决策者：待指定

## 背景

实时通话需要独立 `call_ws`、JSON 控制消息与二进制音频帧。当前骨架尚未建立端点、Adapter 或二进制 codec，因此不能由值对象或 App 端口反推固定 wire 格式。

## 待决事项

以下事项必须在实现协议夹具、Web 端点或客户端实际传输前明确并记录为决策：

1. 二进制帧的字节序、帧头字段宽度与最大 payload
2. 协议版本、`audio_route`、`stream_id`、`response_id`、`seq`、`flags` 和 payload length 的编码及校验
3. 控制帧与音频帧是否使用同一连续 `seq`，以及 ACK、NACK、resume 与取消范围的统一结算语义
4. 稳定错误码、未知版本和超限帧的拒绝方式
5. 实时语音供应商使用 SDK 或直连 WebSocket，以及供应商失败降级
6. Android PCM 采集、AEC、通信音频模式、路由和 24 kHz 播放实现

## 当前约束

- `call.v1` 预期支持 JSON 控制与二进制音频，但本 ADR 不冻结任何字节布局。
- 供应商生成的回答不得绕过 Agent；RealtimeSpeechSession 只暴露规范化感知事件。
- App 音频端口不承诺 codec、采样率或原生实现；F1 AAC/M4A 文件录音不可直接复用为实时管线。
- 任何 UUIDv5 Conversation 身份派生均由调用方显式提供 namespace；本 ADR 不选择项目 namespace 常量。

## 后果

在本 ADR 被接受前，允许实现独立的领域值对象、纯状态机、端口和 fake；不得实现或对外宣称稳定的 `call_ws` wire 兼容性。接受后应补充协议夹具、WebSocket 集成测试和客户端互操作测试。
