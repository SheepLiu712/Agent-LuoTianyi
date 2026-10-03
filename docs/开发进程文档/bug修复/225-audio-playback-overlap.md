# #225 · 手机版重放唱歌音频时可以同时播放其他音频

| 项 | 值 |
| --- | --- |
| 分支 | `fix/audio-playback-overlap` |
| Issue | [#225](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/225) |
| 来源 | 《AgentLuo bug收集》（腾讯文档） |
| 流程 | 普通修复：dev → fix/ → PR → dev |
| 状态 | 实现完成，待验证 |

## 触发条件
重放本地唱歌音频（`type='sing'` 历史消息）时，WebView 仍在线播放 TTS/其它音频，出现重叠播放。

## 被违反的不变量
同一时刻至多一个音频源在播放（本地播放器与在线 TTS 互斥）。

## 根因（详见 #225 调查记录）
- `app/utils/message_processor.ts:239` `playLocalTtsByUuid` 只做内存标志门禁，未强制停播——历史修复 `573c9f78` 的防御调用在 `450c1a53`（2026-08-20）重写时丢失；
- `serverAudioPlaying` 失步路径：后台收尾（`:639-643`）与 90s 超时（`:697-702`）只清标志、不停播。

## 修复点
1. `playLocalTtsByUuid` 开场恢复 `stopServerAudio()` 强制停播（WebView 侧实现健在：`live2d.html:436`）；
2. 失步路径收敛：仅权威结束回执清标志；超时/后台路径「清标志 + 停播」或不清标志。

## 改动范围
`app/utils/message_processor.ts`；测试 `message_processor_audio_priority.test.ts` 增补「重放启动时在线仍在播」方向。

## 验收标准（拟 · 待人审）
- 重放唱歌音频时不再与其他音频重叠；
- 两个互斥方向（服务端音频打断重放 / 重放压制服务端）均有测试证据。

## 验证计划
- 单测：音频互斥用例（双向）；
- 真机：文档复现路径（重放 + 触发其他音频）回归。

## 待定与前置
- 真机复现确认（Android WebView 后台行为差异）。
