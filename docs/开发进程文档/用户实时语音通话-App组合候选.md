# Android 实时语音通话 App 组合候选

> 状态：离线组合候选，等待后续集成与人工验收
>
> 对应工单：CL-11 / Issue #282
>
> 依赖：CL-12 普通合并提交 `e16fd352`；服务端 capability 与 `chat.ready` 契约提交 `878337d3`

## 候选范围

本候选把现有通话 UI、App 网络层、通话传输和 Android 原生音频模块接入生产组合。它保留 App composition Gate 1、2、3 的历史 `BLOCKED` 记录；Gate 3 后的 focused 修复只证明已知 socket 身份和 resolver 生命周期问题得到针对性修复，不构成第四次 Oracle review，也不构成人工验收或整个实时通话功能验收。

## 能力探测与权限顺序

- App 使用当前登录的 `message_token`，通过 Bearer 鉴权请求 `/call/capability?character_id=<当前角色>`。
- 服务端通话能力默认关闭；只有 capability 响应明确返回 `available=true` 且 `reason=available` 时，客户端才把服务端能力视为可用。
- 请求麦克风权限前只执行技术可用性探测：Android 平台、非 Expo Go 环境且原生模块存在。
- 用户授予权限后，才为本次 attempt 初始化原生通信音频会话。初始化结果决定本次呼叫能否继续，不以模块存在冒充设备初始化成功。
- 每个 username/token generation 拥有新的 `ProductionCallResolver`。旧 probe、旧 401 和旧 capability 结果不能覆盖新用户状态；Strict Effects 的 setup/cleanup/setup 使用新 resolver，不复用已经关闭的实例。
- 每次呼叫创建 fresh attempt。进程内共享 `NativeCallOwnership` 保证跨凭据 resolver 也只有一个 native owner；超时但尚未 settle 的初始化继续占用 owner，迟到成功会关闭原 native 资源后才释放，期间新 attempt 准确返回 busy/unavailable。

## 聊天与通话切换契约

- `auth_ok` 只代表凭据通过，不能代表 ChatStage 已绑定，也不能开放聊天发送。
- 客户端仅在收到真实 `chat.ready` 后开放业务发送。该消息必须满足 `schema_version=1`、非空 `interaction_id`，且 `character_id` 与当前显式角色身份一致。
- 每次 chat socket 都有独立 epoch 与 socket identity。旧 socket 的迟到 open/message/error/close 不能改变新 socket 的鉴权、ready、重试预算、timer 或 waiter。
- 通话结束恢复聊天时，若服务端返回 `INTERACTION_OWNED_BY_CALL`，客户端使用同一固定 10 秒总预算进行有界退避；重连不能重置预算，认证失败不可重试。
- `call.switch_prepare` 通过当前已绑定的 chat socket 发送。只有相同 socket generation、相同 `client_request_id` 和相同角色的 `call.switch_ready` 才算成功，随后才断开聊天。
- 错误角色或明确错误 marker 会拒绝对应 switch waiter，但不会断开仍然有效的聊天连接。
- logout、unmount、token/username 改变会使旧 generation 失效；迟到 ready、probe 或回调不能复活旧连接或旧 resolver。

## 原生音频与恢复所有权

- 麦克风帧使用设备序号，客户端 transport 负责会话序号、确认和至多 3 秒的未确认 PCM 缓冲。
- 播放完成只在 Android 播放管线实际消费最后一个 PCM sample 后产生；停止和 tombstone 会阻止迟到或重放帧恢复已取消的回复。
- 音频焦点丢失进入原 CallStage 的恢复流程，不创建新呼叫。恢复期限固定为首次断开起 3 秒，网络和焦点事件不会重置该期限。
- 恢复成功后通过窄 `reacquireAudioFocus` API 重新申请焦点并恢复原 call 的采集；失败继续走既有恢复终止规则。
- `reacquireAudioFocus` 的 Kotlin 实现已进入候选，但尚未完成 Android 原生编译或真机验证。

## 呼叫音生命周期

- `PREPARING` 和 `RINGING` 共享同一个循环呼叫音资源。
- ringtone 使用 desired-state generation 管理异步创建、播放、停止和卸载。停止发生在异步创建完成前时，迟到资源会被卸载，不能重新播放。
- ACTIVE、终止、logout 和 unmount 都停止或释放相应资源；旧 generation 不得影响新 attempt。

## 离线验证证据

- App 全量 Jest：42 suites / 455 tests passed，`--runInBand --detectOpenHandles` 自然退出。
- App 组合具名范围：8 suites / 88 tests passed。
- focused 独立探针：3 suites / 5 tests passed。
- TypeScript：`npx tsc --noEmit` 通过。
- touched-scope ESLint：0 warnings。
- `git diff --check`、严格 UTF-8、raw NUL / U+FFFD 检查通过。

以上证据是离线候选证据，不等同于真实服务端或设备验收。

## 明确未验证范围

- Kotlin 新增音频焦点 API 未执行原生编译。
- 未验证 Android 真机 AEC、噪声抑制、音频焦点、蓝牙路由和设备差异。
- 未执行真实 App ↔ Server 通话 E2E、真实实时语音供应商或 P95 延迟验证。
- 未补充真实设备截图或视觉验收；本候选没有改变既有 UI 布局、间距、动效或 Live2D 设计。
- 仓库完整 App lint 仍有既有 `VoiceRecordingOverlay.tsx` 的 4 个 `react/no-unescaped-entities` 错误；本候选 touched-scope lint 为零警告。
- CL-11、CL-12 和整个 F2 均不得据此标记为已验收。CL-8 / CL-9 owner publication 仍由后续集成流程处理。
