# 用户语音消息 App 界面/交互细化实现蓝图

> 面向 VM-6「录音与发送」与 VM-7「播放与缓存」。
>
> 本文是实现前的 UI/UX 与客户端边界蓝图，不是产品代码。VM-6 / VM-7 已按本蓝图实现并合入 `feat/voice`（PR #221 / #222）。

## 1. 总览

### 1.1 目标与范围

在现有 Expo 54 / React Native 0.81.5 聊天页上增加 Android 手机端的语音输入与历史回放能力：

- 文字模式与语音待录模式可切换，切换不丢失文字草稿。
- 用户以「按住说话 → 松开发送」完成一次语音录制；上滑至少 80 dp 后进入取消区。
- 录音取消前不上传音频；有效录音松开后先显示乐观语音条，再进入录音提交中并由发送队列完成上传。
- 历史语音只在用户点击播放时下载；缓存以 `message_uuid` 为身份，单实例播放，100 MiB LRU 淘汰。
- 不改变桌面端布局，不实现边录边传、自动播放、提交后撤回、启动时恢复未完成上传或模型转写展示。

术语严格沿用 `CONTEXT.md`：录音过程叫「语音录制」，用户确认发送叫「录音提交」，上传阶段叫「录音提交中」，中断或上滑松开叫「录音取消」，正式历史项叫「语音消息」，可见控件叫「语音条」。

### 1.2 AC-01…AC-15 落点

| 验收标准 | App 蓝图落点 |
| --- | --- |
| AC-01 文字与语音模式切换 | `VoiceInputBar` 管理 `TextMode/VoiceReady`；左侧麦克风/键盘按钮切换，`inputText` 保存在 `useChatLogic`，语音模式隐藏文字发送按钮、保留图片按钮。桌面端不接入该组件。 |
| AC-02 首次麦克风授权 | `VoiceRecorder.requestPermission()` 只请求权限；首次按压进入 `PermissionPrompt`，允许/拒绝后回到 `VoiceReady`，本次不开始语音录制。 |
| AC-03 永久拒绝权限 | 权限状态为不可再次请求时显示含「去设置」的轻提示/对话框，调用系统应用设置；不产生临时文件、录音协调信号或语音气泡。 |
| AC-04 开始录音 | 权限已授予且无语音上传时，按压立即调用 `VoiceRecorder.start()`，发送一次 `user_voice_recording_started`；停止本地回放与 WebView 在线音频，显示约 55% 遮罩、计时、波纹和取消提示。 |
| AC-05 音量反馈 | `VoiceRecorder` 通过 metering 回调输出原始分贝；控制器以约 80 ms 节拍平滑，驱动三层同心波纹，颜色不作为唯一状态提示。 |
| AC-06 上滑取消与返回发送区 | `VoiceGestureController` 以初始触点为基准，`dy <= -80dp` 进入 `CancelZone`，只触发一次触觉；回移恢复 `Recording`；取消区抬手执行录音取消，发送区抬手进入录音提交。 |
| AC-07 过短录音 | 录音时长 `< 0.5s` 按录音取消处理：删除临时音频、发送取消协调信号、提示「说话时间太短」，不上传、不生成语音条。 |
| AC-08 30 秒强制结束 | 控制器在 `30.0s` 触发一次终止；发送区自动进入录音提交，取消区自动录音取消；显示时长不超过 `30''`。 |
| AC-09 提交录音 | 有效录音先创建右对齐、`waiting` 的乐观语音消息，再由 `MessageProcessor` 将完整本地文件作为一条不可交错发送项，进入录音提交中。 |
| AC-10 系统中断 | App 后台、离开聊天页、录音 API 报错或组件卸载时统一 `cancelRecording(reason)`；停止并删除临时音频，不展示语音条、不上传残片。录音提交中被杀死后不恢复。 |
| AC-11 语音条样式和时长 | `VoiceBubble` 复用用户气泡颜色、圆角和右边缘锚点；左侧依次为发送状态、播放/停止按钮、语音气泡；按规定格式化时长及 1–30 秒线性宽度。 |
| AC-12 乐观发送与失败重试 | `sendStatus=waiting/submitted/failed` 映射发送状态图标；`finalize` 成功才变已发送；失败图标可用同一逻辑消息 ID、仍存在的本地音频手工重试。 |
| AC-13 按需下载和播放 | `VoicePlaybackManager` 处理缓存命中、单个 in-flight 下载共享、Bearer 下载、原子写入及单实例播放；播放中显示停止方块，失败恢复播放图标并轻提示。 |
| AC-14 本地音频缓存 | 新录音文件立即作为消息初始缓存；历史不预取；缓存管理器按 `message_uuid` 写入正式文件，100 MiB 上限，LRU 只淘汰未播放且不在下载中的项目。 |
| AC-15 录音期间收到角色输出 | 角色文本照常进入历史；角色音频不播放、不在录音结束后补播。开始语音录制时仍调用现有停止本地/在线音频边界，但不把客户端停止播放误当作 Stage 已取消。 |

## 2. 落点与组件结构

### 2.1 建议新增/修改文件

以下是建议落点，名称可在评审时调整；本蓝图不预先改动产品代码。

| 文件 | 类型 | 责任边界 |
| --- | --- | --- |
| `app/components/VoiceInputBar.tsx` | 新增 | 输入栏的文字/语音模式、按压手势承载、录音遮罩层与状态文案；不直接拼 WebSocket 帧。 |
| `app/components/VoiceBubble.tsx` | 新增 | 用户语音条视觉与播放按钮；只接收展示状态和回调，不管理下载/播放器。 |
| `app/components/VoiceRecordingOverlay.tsx` | 新增 | 录音时覆盖 Live2D 与历史区的 55% 黑色遮罩、波纹、计时、上滑指示；输入栏不被此层变暗。 |
| `app/hooks/useVoiceInput.ts` | 新增 | 组合权限、录音生命周期、手势状态、计时、metering 平滑、AppState/导航清理；对页面提供稳定动作接口。 |
| `app/utils/voice_recorder.ts` | 新增 | `expo-av` 的窄平台边界，固定 M4A/AAC-LC、metering、停止/取消和临时文件删除；不认识消息、队列或 UI。 |
| `app/utils/voice_playback_manager.ts` | 新增 | 本地播放、下载合并、原子缓存、单播放、LRU 淘汰和清理；不渲染组件。 |
| `app/utils/message_processor.ts` | 修改 | 增加一个不可交错的语音发送项，内部执行 begin/chunk/finalize、15 秒预算、ACK/重试和状态回调。 |
| `app/utils/ws_transport.ts` / `app/utils/network_client.ts` | 修改 | 增加录音开始/取消协调事件和语音分阶段发送窄方法，复用现有 ACK 归一化。 |
| `app/hooks/useChatLogic.ts` | 修改 | 暴露语音提交、播放/停止、状态回调；在开始语音录制时复用停止音频能力；维护乐观消息和历史合并。 |
| `app/components/ChatBubbles.tsx` | 修改 | `MessageItem` 分派 `type='audio'` 到 `VoiceBubble`；保留用户右对齐和发送状态槽位。 |
| `app/types/chat.ts` | 修改 | 增加 `audio` 消息类型、`durationMs`、本地 URI、播放/下载状态和语音发送元数据。 |
| `app/utils/theme.ts` | 修改 | 增加语音待录/按压/取消中性表面、遮罩、波纹和状态图标所需主题 token；不引入独立视觉系统。 |
| `app/app.json` | 修改 | Android `permissions` 增加 `RECORD_AUDIO`；权限文案/设置跳转以 Expo/Android 实际能力为准。 |

### 2.2 组件树建议

```text
Index
├─ Live2D layer
├─ Chat FlatList
│  └─ MessageItem
│     ├─ ChatBubble / ChatImageBubble
│     └─ VoiceBubble
└─ VoiceInputBar
   ├─ ModeToggleButton
   ├─ TextComposer 或 HoldToTalkButton
   ├─ ImageButton
   └─ VoiceRecordingOverlay（绝对定位，仅覆盖 Live2D + 历史区）
```

`VoiceRecordingOverlay` 不应包住输入栏，否则约 55% 遮罩会错误地压暗「松开发送」按钮。实现上建议让它作为聊天内容区域的兄弟层，输入栏位于更高 z-index；录音时图片按钮只呈禁用态，不能触发新选择。

### 2.3 与现有业务的接口草案

#### `useVoiceInput`

```ts
type VoiceMode = 'text' | 'voice';
type VoiceCaptureState =
  | 'TextMode' | 'VoiceReady' | 'PermissionPrompt'
  | 'Recording' | 'CancelZone' | 'Uploading' | 'Sent' | 'Failed';

interface UseVoiceInputOptions {
  canUpload: boolean;
  onRecordingStarted: (recordingId: string) => void;
  onRecordingCancelled: (recordingId: string, reason: string) => void;
  onRecordingCommitted: (input: { uploadId: string; localUri: string; durationMs: number }) => void;
  onStopAllAudio: () => Promise<void>;
  onNotice: (text: string) => void;
}

interface UseVoiceInputResult {
  mode: VoiceMode;
  captureState: VoiceCaptureState;
  elapsedMs: number;
  smoothedMeter: number;
  isCancelZone: boolean;
  toggleMode: () => void;
  pressIn: (event: GestureResponderEvent) => void;
  pressMove: (event: GestureResponderEvent) => void;
  pressOut: () => void;
  cancelBySystem: (reason: string) => Promise<void>;
}
```

`onRecordingCommitted` 只在录音提交决定成立后调用；它不代表上传成功。权限弹窗和录音取消不调用该回调。

#### `VoiceRecorder`

```ts
interface VoiceRecorder {
  getPermission(): Promise<'granted' | 'denied' | 'blocked'>;
  requestPermission(): Promise<'granted' | 'denied' | 'blocked'>;
  start(options: { onMetering: (db: number) => void }): Promise<{ recordingId: string; localUri: string }>;
  stop(): Promise<{ localUri: string; durationMs: number } | null>;
  cancel(): Promise<void>; // 停止并删除临时音频，幂等
  dispose(): Promise<void>; // 释放 recorder/listener
}
```

`VoiceRecorder` 只返回完整本地文件与测得时长；不在录音阶段切片或上传。`useVoiceInput` 负责将 metering 节流到 UI 频率，避免录音平台边界承担动画策略。

#### `MessageProcessor` / `useChatLogic`

```ts
sendVoice(uploadId: string, localUri: string, durationMs: number): Promise<void>;
sendVoiceRecordingStarted(recordingId: string): Promise<void>;
sendVoiceRecordingCancelled(recordingId: string): Promise<void>;
retryVoice(uploadId: string): Promise<void>;
toggleVoicePlayback(messageUuid: string): Promise<void>;
stopVoicePlayback(): Promise<void>;
```

语音发送项应带有 `uploadId === 乐观消息 uuid`，手工重试保持不变。`MessageProcessor` 逐阶段处理 begin/chunk/finalize，整个语音项在队列中不可被文字或图片插入中间；chunk 不是聊天消息，也不单独触发 UI 状态。

#### `ChatMessage` 扩展草案

```ts
type MessageType = 'text' | 'image' | 'audio' | 'sing' | 'system';
type AudioDownloadState = 'idle' | 'loading' | 'ready' | 'failed';
type AudioPlayState = 'idle' | 'playing';

interface ChatMessage {
  uuid: string;
  type: MessageType;
  content: string; // audio 历史可为 “[语音消息]”，不放音频描述
  isUser: boolean;
  durationMs?: number;
  audioLocalUri?: string;
  audioAvailable?: boolean;
  audioDownloadState?: AudioDownloadState;
  audioPlayState?: AudioPlayState;
  sendStatus?: 'waiting' | 'submitted' | 'failed';
}
```

## 3. 状态机与交互细节

### 3.1 状态与不变量

实现必须与 spec 状态图一致：

```text
TextMode ↔ VoiceReady
VoiceReady → PermissionPrompt → VoiceReady
VoiceReady → Recording ↔ CancelZone
Recording → Uploading → Sent / Failed
Recording → VoiceReady（过短、系统中断）
CancelZone → VoiceReady（抬手取消、30 秒时位于取消区）
Failed → Uploading（本地文件仍在且用户点击失败图标）
```

关键不变量：

1. 同时最多一个语音录制、一个语音上传、一个本地播放。
2. 取消前不上传；取消不生成语音消息、不进入历史、不进入上下文。
3. `Uploading` 已不可撤回；语音条可显示等待，但不提供取消手势。
4. `finalize` ACK 成功才把等待状态改为已发送；它表示媒体已持久化和正式语音消息已被 Stage 接纳，不表示 Agent 已回复。
5. 客户端停止角色音频只属于播放边界；不表示服务端回复已取消。录音开始协调信号仍独立发送。

### 3.2 文字/语音模式切换

- 文字模式：左侧显示麦克风；中间保留现有 `TextInput` 与草稿；图片、文字发送按钮均保留。
- 点击麦克风：收起键盘，进入语音待录；保留 `inputText`，中间替换为浅灰圆角「按住说话」；图片保留，文字发送隐藏。
- 语音待录点击键盘：恢复 `TextInput`、麦克风和文字发送按钮；原草稿不清空。
- `Uploading` 不阻止用户回到文字模式，但是否允许在语音上传期间提交新的文字，建议沿用发送队列顺序；不得插入语音 begin/chunk/finalize 中间。

### 3.3 按住说话与取消区

1. `pressIn`：记录初始触点 `pageY`、创建 `recordingId`；若没有权限只进入权限流，不开始录音。
2. 授权成功：回到 `VoiceReady`，等待下一次按住；本次按压不“顺便”开始语音录制。
3. 已授权按住：先调用停止当前本地/在线音频，再 `VoiceRecorder.start()`，成功后发送一次开始录音协调信号并进入 `Recording`。
4. `pressMove`：计算 `initialPageY - currentPageY`。达到 `80 dp` 即进入 `CancelZone`；回到阈值以内恢复 `Recording`。阈值判定应基于同一屏幕坐标，不随输入栏布局变化漂移。
5. 进入取消区仅一次 `Haptics.impactAsync(ImpactFeedbackStyle.Medium)`；离开再进入可再次触发一次新的进入事件，但单次连续按压不重复振动。
6. 发送区文案为「松开发送」，取消区文案为「松开取消发送」；按钮均使用中性灰，不使用红色。
7. `pressOut`：
   - `CancelZone`：停止并删除临时音频，发送录音取消协调信号，回到 `VoiceReady`。
   - `Recording` 且 `<0.5s`：同上，并提示「说话时间太短」。
   - `Recording` 且 `>=0.5s`：停止录音，建立乐观语音条，进入 `Uploading`。

### 3.4 录音中的视觉层级

- Live2D 与历史区覆盖约 55% 黑色遮罩；遮罩只覆盖内容区，不覆盖输入栏。
- 输入栏仍保持原亮度，以便用户确认手指位置和发送/取消区域。
- 中间显示三层同心波纹：中心层约 28 dp，中层约 45 dp，外层约 62 dp；半径可随平滑音量在有限范围内变化。
- 录音计时显示 `0'' / 30''` 到 `30'' / 30''`；建议每 100 ms 更新数字，但仅按整秒显示，避免文字抖动。
- 主提示「上滑取消发送」；取消区增加向上箭头和虚线阈值示意，主提示改为「松开取消发送」。
- 波纹可使用主题 accent `#66CCFF` 的不同透明度；取消态仅降低为较深中性灰，不把 accent 变红。

### 3.5 音量与 30 秒生命周期

- `VoiceRecorder` 的 metering 事件不直接 setState；控制器将分贝映射为 0–1，再用指数平滑或线性插值处理。
- UI 波纹约每 80 ms 更新一次，使用 `requestAnimationFrame`/动画值消费最近采样；不能为每个原始 metering 事件创建 React render。
- 30.0 秒由单一计时器/单一状态机事件处理，必须幂等，避免 `pressOut` 与自动结束同时提交两次。
- 到 30 秒：位于发送区自动录音提交；位于取消区自动录音取消。界面最大显示 `30'' / 30''`。

### 3.6 录音期间收到角色输出

- 角色文本照常进入 FlatList，不应被遮罩逻辑丢弃。
- 角色音频由 `MessageProcessor` 的播放优先级逻辑阻止播放；不在录音结束后自动补播。
- 录音开始时主动停止当前本地语音和 WebView 在线音频，符合 AC-04；Stage 是否可打断由服务端录音开始协调信号判定，不能由客户端播放状态推断。

### 3.7 系统中断、后台与页面离开

- 订阅 `AppState`：录音中进入非 active 即执行 `cancelBySystem('background')`。
- 聊天页卸载、导航离开、录音 API error、系统音频焦点丢失均走同一幂等清理路径。
- 清理顺序：停止 recorder → 删除临时 URI → 若已发送开始协调信号则发送取消协调信号 → 重置 UI。
- `Uploading` 不因页面重新挂载而恢复；若进程被杀，不能在启动时扫描并继续上传未完成项。若页面只是组件重建，应由上层发送队列生命周期决定是否继续当前进程内上传，避免重复创建消息。

## 4. 视觉规格

### 4.1 主题与布局

复用 `app/utils/theme.ts`：

- 文字模式：沿用现有 `inputBar`、`inputBackground`、`inputBorder`、`userBubble` 与 `userBubbleText`。
- 语音待录：浅色建议 `surfaceAlt` 或接近 `#e7e9ed`；深色使用 `surfaceAlt`，保证与输入栏分层但不刺眼。
- 按压态：使用 `surfacePressed` 的中性变体；取消态比按压态更深一级，仍不使用 `dangerSurface/dangerText`。
- 现有用户气泡圆角为 10 dp、右下角 2 dp；语音气泡沿用该规则。语音条外部行保持现有约 6 dp 水平内边距和 5 dp 垂直间距。
- 录音遮罩色为黑色约 55% 透明度；深色主题可维持同一透明度，不额外叠加第二层遮罩。
- 所有可点击播放/状态槽位保持约 32 dp hit area；视觉图标可小于 32 dp，但不压缩可访问点击范围。

### 4.2 语音条结构与对齐

从左到右必须是：

```text
[发送状态图标 32dp] [播放/停止圆形按钮 32dp] [用户语音气泡]
```

整行 `justifyContent: flex-end`，气泡右边缘与用户文字/图片气泡右边缘对齐。左侧状态和播放控件是语音条的附属区域，不能因为它们存在而把整行排到左侧。

语音气泡内部从左到右为「时长 + 音频图标」：

- 音频图标由一个圆点和三段同圆心、同圆角方向的弧线组成；不要使用会被误认为播放按钮的三角形。
- 气泡高度等同单行文字气泡，建议沿用现有文字字体和垂直 padding。
- 时长格式：`0.5–1.0s → 1''`；其余秒数向上取整；最大显示 `30''`。服务端 `30.5s` 仍显示 `30''`。
- 宽度线性插值：`width = 76 + (ceilSeconds - 1) * (200 - 76) / (30 - 1)`，结果限制在 76–200 dp；小屏仍受 `maxWidth` 约束。

### 4.3 状态图标与交互反馈

| 状态 | 发送状态图标 | 播放控件 | 语音条表现 |
| --- | --- | --- | --- |
| 录音提交中 | 复用现有 waiting 图标/动画 | 不可播放或显示禁用态 | 用户气泡保持可见，语音文件正在提交 |
| 已发送、未播放 | 无图标或复用已发送的现有空槽 | 圆形播放三角 | 正常用户气泡 |
| 下载中 | 无/已发送状态不变 | 加载 spinner，按钮仍占位 | 不改变宽度，不允许重复创建下载 |
| 播放中 | 无/已发送状态不变 | 停止方块 | 同时只能一条播放；再次点击停止 |
| 播放失败 | 若消息发送成功不显示发送失败 | 恢复播放三角，轻提示 | 可再次点击下载/播放 |
| 上传失败 | 复用现有 failed 图标 | 若本地文件存在，允许点击重试 | 仍保持消息宽度和时长 |

发送失败与播放失败必须分开：播放下载失败不能把已发送语音消息变成发送失败；上传永久失败才显示发送失败图标。

### 4.4 深浅色一致性

- 深色主题用户气泡沿用 `THEMES.dark.userBubble`，图标和文字使用 `userBubbleText`；浅色沿用对应 light token。
- 中性录音按钮在两种主题中都保持足够对比度，文案不能只靠灰度差异识别。
- 遮罩上的白色文案、计时和箭头在深浅色中保持一致；波纹使用 `accent`，但取消状态仍通过文案与形态表达。
- 应提供最小字号/对比度检查，尤其是 dark 主题的 `textMuted` 与取消提示。

## 5. 技术选型建议

### 5.1 录音平台边界

继续使用已安装的 `expo-av`，在 `VoiceRecorder` 内固定：

- M4A 容器、AAC-LC 编码、`audio/mp4` MIME。
- 录音前请求权限，录音期间启用 metering，停止后得到本地 URI 与时长。
- 仅平台边界接触 `Audio.Recording`；组件和发送队列不直接调用 Expo API。
- 保留迁移 `expo-audio` 的可能性，但 VM-6/VM-7 不扩大范围做迁移。

实现时应核对 Expo 54 `expo-av` 的 Android 录音配置、权限返回值与 `prepareToRecordAsync` 参数，避免把 API 细节泄漏到 UI 状态机。

### 5.2 动画：优先 Reanimated，状态机仍由 JS 控制

建议使用已安装但当前聊天 UI 尚未使用的 `react-native-reanimated`：

- 波纹半径/透明度/缩放是高频视觉更新，放在 UI 线程可减少 80 ms metering 对 JS render 的压力。
- JS 线程只更新最近的平滑音量共享值和离散状态（Recording/CancelZone），不在每个采样上重绘整个聊天页。
- 遮罩出现/消失可用简单的 opacity 动画；状态文案、计时和权限弹窗仍由 React 状态驱动。

若团队希望降低引入成本，可用 RN `Animated` 的 `useNativeDriver` 实现波纹，但不要使用 `setInterval + setState` 驱动三层 View 的全部样式。两者择一，不要同一组件混用两套动画生命周期。

### 5.3 触觉

使用 `expo-haptics`：仅在首次进入取消区触发一次中等冲击；开始录音、提交或每次 metering 不触发，避免噪声和耗电。设备不支持或系统关闭触觉时静默降级，不影响状态机。

### 5.4 线程、文件与网络性能

- metering 采样与 UI 消费解耦，保留最新值即可，不累积事件队列。
- 不在录音阶段读取或 Base64 化文件；录音提交后才由发送项读取并分片。
- chunk 发送按现有 transport ACK 机制串行/有限并发执行；语音发送项内部不可交错。
- 下载先写临时文件，完整响应成功后原子移动/替换为 `message_uuid` 命名的缓存文件。
- 下载的同一 `message_uuid` 只维护一个 in-flight Promise；播放中和下载中的文件禁止 LRU 淘汰。
- 日志不得写入音频字节、Base64、完整音频描述或鉴权 token；调试信息只记录 uuid、阶段、字节数和稳定错误类别。

### 5.5 需要拍板的技术开放项

1. 语音发送项在发送队列中应采用「严格 FIFO」还是允许普通文本在语音 `finalize` 后立即进入；本蓝图要求不穿插语音内部阶段，但允许评审 FIFO 规则。
2. `VoicePlaybackManager` 是由 `MessageProcessor` 持有，还是作为 `useChatLogic` 外部依赖注入；建议前者统一现有播放优先级，后者更利于单元测试。
3. Android 录音临时文件目录使用 Expo cache directory 还是 document directory；建议临时文件进 cache，提交成功的本地缓存进入独立 `voice_cache/<message_uuid>.m4a`。
4. 是否为录音提交中语音条显示细粒度上传进度；AC 未要求，默认不显示百分比，避免把 chunk 传输细节变成产品承诺。

## 6. 验收与测试映射

### 6.1 Jest 单元/组件测试

建议新增测试集中在 `app/__tests__`，测试公共行为而非私有字段：

| 测试范围 | 覆盖内容 |
| --- | --- |
| `voice_input_state.test.ts` | TextMode/VoiceReady 切换、草稿保留、权限三态、首次授权不开始录音、80 dp 双向阈值、取消区单次触觉、过短录音、30 秒两区域分支。 |
| `voice_recorder.test.ts` | `start/stop/cancel/dispose` 幂等、临时文件删除、录音异常归一化、metering 回调转发。Expo 原生对象用 mock。 |
| `voice_format.test.ts` | 0.5、1.0、1.1、15、29.1、30、30.5 秒格式化与宽度插值边界。 |
| `voice_message_processor.test.ts` | begin/chunk/finalize 顺序、一个 uploadId 的重试、15 秒预算、ACK 丢失重放、永久 NACK、同一逻辑 ID 不创建重复消息、状态回调。 |
| `voice_playback_manager.test.ts` | 缓存命中、下载失败恢复、同消息并发下载共享、单播放互斥、停止、原子写入、播放/下载期间不淘汰、100 MiB LRU。 |
| `VoiceBubble.test.tsx` | 用户右对齐、状态/播放控件在气泡左侧、时长和图标顺序、waiting/failed/loading/playing 图标、深浅主题 token 使用。 |
| `VoiceInputBar.test.tsx` | 文字/语音布局、图片按钮保留、文字发送隐藏、录音时输入栏不被遮罩、取消文案切换。 |

建议对状态机使用 fake timers，对 80 ms 平滑使用可注入 clock/采样源；不要以精确 setState 次数作为测试契约。

### 6.2 真机/集成手工清单

以下必须在 Android 真机或接近真实的集成环境验证：

- 首次权限允许、拒绝、永久拒绝与「去设置」返回。
- 真实 M4A/AAC-LC 可播放性、0.5 秒边界、30 秒强制结束。
- 按住、上滑 80 dp、回移、取消区抬手；手指漂移和屏幕边缘。
- 触觉只在进入取消区一次；不同厂商系统对触觉的降级表现。
- Live2D/历史区遮罩约 55%，输入栏保持原亮度；深浅色视觉与小屏布局。
- 录音时收到角色文本/音频，确认文本入历史、音频不播放且不补播。
- 后台、锁屏、来电/系统音频中断、离开聊天页、录音 API 异常后的清理。
- 弱网、断线重连、ACK 丢失、15 秒上传失败、失败图标手工重试且不重复消息。
- 历史语音懒下载、Bearer 鉴权、同一条并发点击、播放互斥、停止方块。
- 缓存接近/超过 100 MiB 时 LRU 淘汰，当前播放/下载项不被删除；退出登录/完全重置本地清理。

## 7. 实施拆分建议

每个原子提交只包含一个逻辑单元及其测试，避免 VM-6 与 VM-7 互相污染。

### VM-6：录音与发送

1. **扩展客户端类型和主题 token**：增加 audio 消息字段、录音状态类型、中性录音表面 token；补类型/格式化单测。
2. **接入 Android 麦克风权限配置与 `VoiceRecorder`**：增加 `RECORD_AUDIO` 和窄 Expo 录音边界；补权限与生命周期 mock 测试。
3. **实现纯手势状态机**：`TextMode → VoiceReady → Recording/CancelZone`，包含 80 dp、0.5 秒、30 秒和单次触觉；补 fake timer/gesture 测试。
4. **实现 `VoiceInputBar` 与遮罩视觉**：模式切换、草稿保留、输入栏层级、录音文案和波纹；补组件测试和手工视觉清单。
5. **增加录音协调 transport 方法**：started/cancelled 窄接口，复用 ACK 归一化；补 payload 和失败降级测试。
6. **增加乐观语音消息渲染**：`VoiceBubble`、MessageItem 分派、等待/失败状态；先使用本地占位回调，补右对齐和状态视觉测试。
7. **增加语音发送项**：`MessageProcessor`/`NetworkClient`/`WebSocketTransport` 的 begin/chunk/finalize、15 秒预算和同 ID 重试；补顺序、ACK 丢失、永久失败和幂等测试。
8. **接通 `useChatLogic`**：录音提交回调、状态更新、开始录音停止现有音频、页面/后台清理；补集成级 hook 测试或最小行为测试。

### VM-7：播放与缓存

9. **实现缓存身份与文件操作**：`message_uuid` 命名、临时文件原子写入、100 MiB LRU、保护播放/下载项；补缓存管理器单测。
10. **实现历史按需下载**：Bearer 下载、in-flight Promise 合并、失败恢复与轻提示；补并发和失败测试。
11. **统一播放控制器**：复用现有 `expo-av` 播放能力，单实例播放、停止、播放状态回调；补互斥/停止测试。
12. **接入语音条播放 UI**：播放、停止、加载、失败图标和触摸区域；补 `VoiceBubble` 组件测试。
13. **接入历史映射与清理**：历史 audio 元数据、缓存命中、退出登录/完全重置清理；补 history merge 与清理测试。
14. **真机验收提交**：权限、弱网、系统中断、深浅色、缓存淘汰和录音期间角色输出手工记录；不把未验证项写成通过。

## 8. 开放问题

提交实现前请人类确认：

1. 语音录制时，是否允许点击左侧键盘按钮立即取消语音录制，还是按钮在录音期间完全不可切换？本蓝图默认录音期间不提供切换入口，避免与 `pressOut` 竞态。
2. 进入 `Uploading` 后，用户切回文字模式并发送文字时，是否严格排在语音 `finalize` 后？建议保持队列 FIFO，保证语音作为一个不可交错发送项。
3. 上传等待状态是否需要显示 spinner，还是只复用现有 waiting 图标？建议复用现有 waiting 图标，保持图片/文字/语音发送状态一致。
4. 语音消息已发送但历史 `audio_available=false` 时，语音条显示「播放失败」图标还是仍显示普通播放按钮？本蓝图建议进入不可重试失败态并给轻提示，避免无休止下载。
5. `VoiceRecorder` 临时文件与语音缓存的目录、退出登录清理时机是否由现有文件管理策略统一决定？需避免清理正在播放的文件。
6. 录音期间收到角色输出的文本是否允许滚动位置自动变化？建议正常插入历史但不强制滚动，以免手势反馈区域随列表变化造成认知负担。
7. 波纹是否需要依据设备 reduced-motion/无障碍设置降低动画？建议支持：保留音量反馈与计时，取消连续缩放动画。
8. 是否要求发送失败气泡在 App 重启后仍可手工重试？spec 明确不恢复被杀进程未完成上传；本蓝图默认仅保留当前进程内本地失败项。
9. 失败语音点击范围是否只限发送状态图标，还是整条语音条均可重试？建议只让状态图标承担重试，播放按钮仍保持播放语义，减少误操作。
10. 是否需要为语音条增加可访问性标签，例如「用户语音消息，15 秒，播放」和「录音中，松开发送」？建议纳入实现，标签不得读出音频描述或隐藏转写文本。

## 9. 评审结论记录位

- 人类评审人：项目负责人（GitHub @jinyiwei2012）
- 评审日期：2026-10-01
- 已确认的开放问题：全部 10 项按蓝图推荐默认确认 —— ①录音期间不提供模式切换；②语音发送项严格 FIFO（不可交错）；③复用现有 waiting 图标；④`audio_available=false` 显示不可重试失败态（spec AC-18）；⑤临时文件进 cache、正式缓存 `voice_cache/<message_uuid>.m4a`；⑥录音时角色文本不强制滚动；⑦支持 reduced-motion 降级；⑧失败重试仅限当前进程内（spec：不恢复被杀进程）；⑨重试入口仅限状态图标；⑩纳入无障碍标签
- 需要回写 spec 的冲突：无
- 可进入编码的 VM-6 提交：第 7 节 VM-6 第 1–8 步（按原子提交执行）
- 可进入编码的 VM-7 提交：第 7 节 VM-7 第 9–14 步
