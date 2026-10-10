# `call.v1` 传输阶段 1 验证

## 交付边界

本阶段实现物理 `/call_ws` 鉴权入口和 Adapter 所有的 `CallTransportSession`：

- JSON 业务控制与二进制音频共享客户端/服务端各自的 UINT32 `seq`
- 业务 sink 成功接纳后才推进客户端连续游标并发送 ACK
- 首缺口 NACK、有界 pending frame/byte 窗口、相同序号同字节幂等及不同内容冲突
- 服务端原序号、原文本/二进制 bytes 的有限重放；ACK、NACK、resume/resumed 不占序号
- 4 MiB 全呼叫重放上限与每 response 最多 30 秒未 ACK / 未退休 PCM；按登记的编码、采样率和声道计算，不使用 stream 墙钟
- `playback.stop` 退休 payload，保留范围 tombstone；针对退休音频的 NACK 只重放 stop
- Adapter 校验客户端麦克风 `CALL/stream_id=0`，以及服务端下行 `CALL/stream_id>=1`、stream registration 和 final 后播放完成
- 恢复按新连接正常鉴权，并校验 `call_id + user + character`

当前 `call_transport.enabled` 默认 `false` 且只接受 JSON boolean。即使配置为 true，生产 `ServerRuntime.call_transport_available` 在缺少 CallStage、账本和供应商结构绑定时恒为 false，不存在可写 `dependencies_ready` 绕过。外部多 worker 拓扑无法从当前进程权威证明，因此生产 call 保持关闭，chat 不受影响。`call.start` 在本阶段明确返回不可用，不消费切换 intent、不建立账本。

## 容量与隐私

- pending 默认最多 256 帧 / 4 MiB
- replay 默认最多 4 MiB；满载对 producer 返回独立 backpressure，并可等待 ACK 释放容量，不关闭通话
- 每 response 音频默认最多 30 秒；当前 `pcm_s16le / 24000 Hz / mono` 对应 1440000 payload bytes，ACK 或 retirement 会释放该预算
- `wait_for_audio_capacity(response_id, wire_bytes, payload_bytes)` 同时等待全局 replay 和目标 response PCM 预算；ACK、retirement、close 都会唤醒，虚假或其他 response 唤醒后重新检查，不持有 hub lock、不忙循环
- 单个 wire 或 payload 永远不可能装入对应上限时立即拒绝，避免永久等待
- 已接纳客户端序号指纹最多 131072 条；达到上限时关闭该 transport，不删除旧指纹后继续接收
- business sink 以 `(call_id, client_to_server, seq, fingerprint)` receipt 做幂等；transport 等待已经启动的接纳完成，先提交指纹/游标再传播调用者取消。sink 异常可能发生在部分副作用之后，因此调用方必须幂等，本层不宣称 exactly-once
- hub 使用 generation 原子绑定单一物理连接；活动连接存在时拒绝第二连接，旧 generation 的 finally 不能解绑新连接
- stop 身份元数据独立于 replay 生命周期；普通 ACK 清除 stop wire 后，合法 `playback.stopped` 仍可验证。元数据按 call scope 有界并在 session close 清理
- `playback.stop` 以“当前 replay bytes - 实际退休 bytes + stop encoded bytes”做原子容量判断；净容量足够时一次提交 stop、tombstone 和序号，否则返回 backpressure 且不产生部分状态
- 内存重放仅保存 wire bytes 和关联 ID，不写磁盘、数据库或普通日志；不记录 PCM、转录或上下文内容
- 没有无限后台 task；endpoint 在单连接 receive/send 循环内串行处理

## Close code 工程映射

- `1002`：协议结构、方向、序号冲突、非法流/范围
- `1008`：恢复所有权不匹配或不存在的私有 call
- `1009`：控制帧超过已冻结 16384-byte 上限
- `1013`：能力未就绪、入站 pending/history 容量耗尽或 response window 超限；出站 replay 满使用 producer backpressure，不映射为 close
- `1011`：物理入口未预期内部异常

该映射只选择 RFC 6455 / ASGI 常用标准 close code，不改变 `call.v1` 自研 error envelope，也不表示 ADR 已 Accepted。

## 尚未实现

- CallStage、账本、供应商和新呼叫建立
- 持久恢复、跨进程或多节点协调
- Agent/TTS 生产输出接线、沉默时钟和实际播放结算
- App transport、设备、AEC、蓝牙与性能验收

## 阶段 1 验证

- 三轮 Oracle gate 均为历史 `BLOCKED`，没有第四轮 Oracle，也不宣称 gate 通过
- material findings 修复后，独立只读 focused 验证以 51 passed 和受控 `CountingEvent` 复现确认 retirement wake、全局 replay 与 response PCM 联合等待、虚假唤醒重查、close/impossible request，以及 stop 失败无部分状态均已关闭；这只支持隔离 transport 阶段提交
- 本轮提交前对 transport / capability / 真实 FastAPI WebSocket 入口重新执行一次定向复验：51 passed
- 历史扩大回归记录：`tests/integration/websocket` 119 passed、2 个既有 TIFF fixture 失败；system/入口 7 passed。这些历史结果不作为本轮执行结果
- Black、Ruff、架构边界 B1–B10、`git diff --check` 纳入本轮提交前检查
- 测试鉴权使用 fake credential service；业务 sink receipt 的保障是以 receipt 为幂等键的 at-least-once 重试安全，不是 arbitrary sink 副作用的 exactly-once
- 测试仅使用内存 sink 和真实 FastAPI WebSocket 入口；没有真实供应商、付费调用、生产凭据、设备或生产验收
