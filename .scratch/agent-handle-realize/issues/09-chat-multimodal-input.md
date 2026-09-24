# 09: 迁移图片与非 Realtime 语音输入

**What to build:** 让图片和已结束的非 Realtime 语音使用与文字相同的 ChatStage/Agent 两接口链路，并在 Agent 内通过可复用 ImageReading、SpeechUnderstanding、Recall 和 Attention Skill 完成语义处理。

**Blocked by:** 08: 迁移文字聊天、聚合超时与普通回复。

**Status:** ready-for-agent

**GitHub Issue:** [#68](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/68)

## Decision rule

SPEC 第 5.2、6.3—6.5、8.3 节优先。图片 MIME/大小/Base64 和当前 VLM fallback 只在 SPEC 留白时参考当前 Adapter/preprocessor/capability；VoiceMessage 没有现有外部协议时只实现已存在调用入口需要的强类型内部链，不擅自新增 WebSocket 事件。

## Architecture constraints

- ImageReading 与 SpeechUnderstanding 归 `agent/skills/cognitive`，以强类型 input/result 包装现有 image/speech capability；不得把 capability API、供应商对象或任意 dict 暴露给 Handler。
- Conversation Handler 组合这些 Skill 与 Recall/Attention；stage 只持有公开 MediaRef/Stimulus，不识别任何认知中间对象。
- 一个技术 capability 可以被多个 Skill 复用，Skill 也可组合多个 capability/subconscious 对象；不得镜像 `capabilities/` 建同名薄代理树。

## Scope

- 适配并校验 ImageMessage，使用受控 MediaRef，保持 client_msg_id 去重、一次持久化和与文字共同 pending。
- 把图片读取、图文理解、歌曲/日期线索预处理移入 Agent 内部 Skill；stage 不调用预处理代理。
- 支持 VoiceMessage 的 media/transcript 至少一项约束，通过 SpeechUnderstanding 后复用对话 Handler。
- 允许同一 snapshot 混合文字、图片和语音，按 stage 顺序 considered/consumed/retained。

## Acceptance criteria

- [ ] 非法 Base64、MIME、大小、空语音内容或未授权媒体引用在进入 Agent/capability 前失败。
- [ ] 图片/语音只持久化一次，重投不重复；本地任意路径、原始供应商对象不进入 Stimulus。
- [ ] ImageReading/SpeechUnderstanding 结果只在 Agent 内流转，可复用相同 Recall/Attention/ResponseComposition。
- [ ] Handler 不直接导入 image/speech capability 或 CapabilityManager；所有供应商适配位于 Agent 私有 Skill adapter 后。
- [ ] 混合 pending 能产生一个有序计划或精确部分结算，stage 不需要知道图像/语音认知中间对象。
- [ ] VLM/ASR 不可用或超时按稳定错误/fallback 处理，并保持当前图片链的可观察行为。
- [ ] 若当前产品没有非 Realtime 语音外部事件，本票不新增客户端协议，只证明 typed stage/Agent seam。

## Verification

- 先从 Adapter/ChatStage 公共入口写图片 Red；语音从现有最外层可用 stage seam 测试，供应商使用 Fake。
- 覆盖图片与文字合并、未授权 MediaRef、VLM 失败、transcript-only、media-only、ASR 失败和跨用户隔离。
- 运行 chat integration、Adapter、Agent、image capability 相关回归。

## Explicit exclusions

- 不实现电话、Realtime PCM 或供应商会话。
- 不把图片/语音中间结果写入 InteractionSnapshot 或公开 report。

## Handoff

一个多模态纵向 PR；进度中明确是否存在真实 VoiceMessage 产品入口及未验证的真实模型范围。
