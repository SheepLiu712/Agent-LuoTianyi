# Android 通话音频模块

## 边界

- `app/modules/call-audio` 是 Expo SDK 54 本地 Android 模块，不引入新的第三方依赖
- 采集固定为 PCM16、16 kHz、单声道；播放固定为 PCM16、24 kHz、单声道，不做静默采样率回退
- Base64 只用于 Expo 原生桥接传递字节；`call.v1` WebSocket 仍使用现有二进制帧 codec
- 模块不发送 socket ACK，不决定通话生命周期；后台事件、音频错误、路由观察和停止回执交给上层 coordinator
- Expo Go、非 Android、模块缺失或实际格式初始化失败时能力为 unavailable
- 实现已随 PR #361 集成到 dev；真实设备验收由 [#362](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/362) 承接。已有编译、APK 和模拟器加载证据不能证明当前 Release 真机通过

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
- TS 上行恢复缓冲最多保留 3 秒 PCM，只接受 coordinator 分配的 `wireSequence`；传输层复用该缓冲，不能再创建第二份 3 秒队列或以设备计数代替协议序号
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

- 真机上的 New Architecture 模块装配与长期运行稳定性
- AEC 在目标设备上的实际效果，而不只是 `AcousticEchoCanceler` 创建/启用结果
- 有线耳机、听筒、扬声器、蓝牙路由行为；当前只观察系统输出设备，不强制承诺路由
- 真实播放头、延迟和 stop 延迟；Jest/Kotlin helper 测试不能替代设备证据

## 历史构建证据

以下是 CL-12 候选阶段的记录，详见[构建证据与真机清单](docs/android-validation.md)。后续播放回执、取消、提示音和 RMS 修改已进入 dev；旧测试数量、APK 哈希和模拟器结果不代表当前版本。当前行为测试位于 `app/__tests__/native_call_audio_adapter.test.ts`、`call_playback_completion_composition.test.ts`、`call_playback_progress.test.ts` 及本模块 `android/src/test`。

- `npx expo-modules-autolinking verify --verbose` 从默认 `./modules` 解析 `agent-luotianyi-call-audio@0.1.0` 与 `com.sheepliu712.callaudio.CallAudioModule`；根 `dependencies` 和额外 config plugin 均不需要。
- 真实模块任务 `compileDebugKotlin` 与 `testDebugUnitTest` 成功；`PlaybackAccountingTest` 9 passed，`CallAudioModule` 与 `reacquireAudioFocus` 已编译。
- 完整 New Architecture Debug APK：`ca8acf965a126d8824620f6659394dfad9d3bd0ee2ad3586ce0c0ce8aa0e2179`，四 ABI、minSdk 24、targetSdk 36、Debug v2 签名。`CallAudioModule` 与 `reacquireAudioFocus` 位于 APK DEX。APK 不含 JS bundle，单独 `am start` 只能证明原生壳启动。
- 隔离 Windows build 使用短 source/cache 和 `CMAKE_OBJECT_PATH_MAX=200`；生成路径实际 hash，完整 `.o` 最大 241 字符。APK、SDK、cache、debug keystore 和代理设置不进入 Git。
- AOSP ATD API 36 x86_64 + WHPX headless 设备完成安装和真实 Metro（1289 modules）启动；Expo JSI、Fabric 和 Native Module presence 成功。权限拒绝 fail-closed；授权后因模拟器无 AEC 返回 `aec_unavailable`，焦点 API 返回 `session_not_ready`，cleanup 成功且无 FATAL。
- N9 stop operation registry 已用于生产 stop command path；重复与 global/per-stream 重叠 waiter、termination drain 和迟到 settle-once 同时具有 Kotlin 9 tests 与 TS mock 证据。
- 历史 Oracle 第三轮 `CHANGES_REQUESTED` 是早期候选记录；本次归档不将其重写为通过，也不把它当作当前实现审核结论。真机效果和长期稳定性仍待 #362 验收

## 播放回执与视觉进度

TS 侧保留 enqueue Promise 返回前到达的有效完成回执及正常取消保护；实际完成仍以播放头消费为准。有效实时 RMS 到达即驱动嘴型，不等待 enqueue、不缓存补偿早到进度；普通零响度保留惯性，只有中断和确认话语完成才 reset。分析时间窗与聊天一致，旧 session/generation 不影响新流。统一嘴型实现与播放后端评估由 [#360](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/360) 跟踪。
