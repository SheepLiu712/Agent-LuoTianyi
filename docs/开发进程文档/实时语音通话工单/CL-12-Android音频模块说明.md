# CL-12 Android 音频模块说明

## 边界

- `app/modules/call-audio` 是 Expo SDK 54 本地 Android 模块，不引入新的第三方依赖
- 采集固定为 PCM16、16 kHz、单声道；播放固定为 PCM16、24 kHz、单声道，不做静默采样率回退
- Base64 只用于 Expo 原生桥接传递字节；`call.v1` WebSocket 仍使用现有二进制帧 codec
- 模块不发送 socket ACK，不决定通话生命周期；后台事件、音频错误、路由观察和停止回执交给上层 coordinator
- Expo Go、非 Android、模块缺失或实际格式初始化失败时能力为 unavailable
- 当前实现仍是 Proposed 原型；Android SDK 缺失时不能据此宣称原生已编译、真机通过或 AC 完成

## 完成与停止语义

- final 入队、写入 `AudioTrack` 或服务端 final 帧均不产生完成回执
- 模块累计 `playbackHeadPosition` 的无符号 32 位差值；只有播放头消费到 final 对应的最后一帧才发送 `onPlaybackCompleted`
- 共享 `AudioTrack` 第一版严格保持单活跃流：后续流有界排队，直到当前流完成或被停止才写入 Track
- stop queued 只移除目标流，不 flush active；stop active 才由播放线程 flush，随后继续无关排队流
- 播放线程实际使用 `PlaybackCommandProcessor` 与 `PlaybackLoopAccounting`；queued stop 不重置 active 的 submitted/played/final target 账本
- 每个 `(response_id, stream_id)` 具有 generation；stop 命令先登记，播放线程完成必要 flush 后才发送一次 `onPlaybackStopped` 并 resolve 原生 Promise
- TS ledger 丢弃旧 generation、重复 completion 和 tombstone 后迟到 completion
- 每次 `startSession` 生成 session generation，原生与 TS 在 close/start 间清空 stream、tombstone、receipt、final 与恢复状态；旧线程事件被 generation 隔离

## 缓冲与隐私

- 原生播放队列有界为 4 秒 PCM，满时返回稳定错误 `playback_buffer_full`
- 原生 capture `deviceSequence` 只是当前 session 内设备帧计数，capture restart 不重置；它不是 `call.v1` wire seq
- TS 上行恢复缓冲最多保留 3 秒 PCM，只接受 coordinator 分配的 `wireSequence`；传输层接入后必须复用该缓冲，不能再创建第二份 3 秒队列或以设备计数代替协议序号
- 原生到 JS 最多允许 30 个未确认 capture 事件；TS 收到事件后回 ACK，超限以 `capture_bridge_backpressure` 失败，不无限堆积 Base64
- 模块不持久化 PCM，不记录 PCM/Base64/逐字内容

## 能力与清理

- `available` 仅在固定 capture/playback 格式、通信 AudioFocus、AEC 与 NoiseSuppressor 均成功初始化后返回；不支持时 fail closed 并给稳定 reason
- `available` 只证明 Android API 初始化与启用结果，不证明 AEC/降噪实际效果
- 初始化失败统一撤销焦点、路由回调、通信 mode、生命周期回调并释放已创建对象
- capture/playback 线程先请求停止并有限等待；若 250 ms 内仍存活，报告稳定 timeout，且不在线程仍可能访问对象时 release
- 任一 worker 停止超时后，模块进入实例级 `session_termination_failed` fail-closed；`startSession`、`startCapture`、enqueue 和 stop 均拒绝重新取得所有权，后续 close 只允许收束原 worker，不创建新 generation 或复用共享队列/设备
- worker 启动时捕获不可变 session generation；completion、failure 与 stop receipt 不读取当前 generation 冒充新会话事件
- stop operation 使用独立于 receipt 去重的 pending/completed registry：重复或 global/per-stream 重叠请求共享同一次物理停止，所有 waiter 只在实际完成后 settle；仅已完成请求可立即 resolve
- termination failure 会原子清空未执行命令并 reject 所有 pending stop waiter；worker 迟到返回不能再次 resolve/reject，正常 close 要求 stop registry 已为空

## 仍需真机证据

- Android 原生编译与 New Architecture 装配
- AEC 在目标设备上的实际效果，而不只是 `AcousticEchoCanceler` 创建/启用结果
- 有线耳机、听筒、扬声器、蓝牙路由行为；当前只观察系统输出设备，不强制承诺路由
- 真实播放头、延迟和 stop 延迟；Jest/Kotlin helper 测试不能替代设备证据

## 当前验证状态

- 候选代码尚未经过 Android/Kotlin 编译；本机没有 Android SDK、ADB、Gradle wrapper、`kotlinc` 或预构建原生工程
- `npx expo-modules-autolinking verify --verbose` 已从默认 `./modules` 搜索路径解析 package `agent-luotianyi-call-audio@0.1.0`、模块 `com.sheepliu712.callaudio.CallAudioModule` 与本地 source directory；无需根 `dependencies` 或额外 config plugin，但这不证明 Android 能编译或加载模块
- N9 stop operation registry 已用于生产 stop command path；重复与 global/per-stream 重叠 waiter、termination drain 和迟到 settle-once 有纯 Kotlin 测试源码及 TS mock 证据，但 Kotlin 测试未执行
- 历史 Oracle 第三轮仍为 `CHANGES_REQUESTED`；本文件记录的是供后续 focused 核对的 Draft candidate，不是 native gate、AC 或硬件能力通过证明
