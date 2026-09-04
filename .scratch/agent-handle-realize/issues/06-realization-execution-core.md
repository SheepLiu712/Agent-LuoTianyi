# 06: 实现 realization、Execution Ledger 与 Say 输出核心

**What to build:** 通过公开 `realize_action_plan` 实现计划校验、Action 顺序、Execution Ledger、输出序列和安全重试，并让 Say 的文字、TTS/预制音频和内嵌表情能通过通道无关 output sink 实现。

**Blocked by:** 04: 扩展两接口 Agent façade 与内部路由。

**Status:** ready-for-agent

**GitHub Issue:** [#65](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/65)

## Decision rule

SPEC 第 5.3、5.4、6.3、6.6、7、8.7 节优先。音频、表情和失败 fallback 的细节仅在 SPEC 留白时参考当前 response realizer、TTS 和反射行为；不得让 Action Handler重新决定说什么，也不得在 output sink 中加入角色认知。

## Scope

- Execution Ledger 可靠绑定 execution ID 与 plan fingerprint，逐项记录 Action 状态、effect ref、不可逆标记、输出起始和下一个 sequence。
- realizer 严格按 Action 顺序执行，统一处理 cancellation、NOT_STARTED、部分成功、稳定错误和 report。
- 实现 Say Action：TEXT、TTS 或预制 AUDIO、内嵌 EXPRESSION，以及 CONVERSATION/EPHEMERAL_REACTION delivery。
- output sink 只负责接受、去重、顺序、背压和通道能力校验；真实 Adapter 编码由调用方完成。

## Acceptance criteria

- [ ] 同一 execution ID 只能绑定一个 plan；换 plan 重用明确失败。
- [ ] 已完成 Action 在同 execution 重试时返回 ALREADY_COMPLETED，输出和不可逆效果不重复；从第一个未完成 Action 继续。
- [ ] 输出 sequence 从 0 连续递增，相同 execution/sequence 只允许相同内容重投。
- [ ] interaction-bound 输出在 realization 开始时校验 current revision；旧计划返回 STALE_INTERACTION。
- [ ] Say 的 sound_content 与 prepared_audio_ref 互斥；瞬时反应不持久化/不显示气泡，非 normal 表情在音频或期限后恢复 normal。
- [ ] 首个输出前 TTS 失败可按相同 execution 重试；输出已开始或效果已提交后不自动从头重放。
- [ ] 一个 Action 失败/取消后后续 Action 为 NOT_STARTED，ExecutionReport 不掩盖部分失败。

## Verification

- 先从公开 `realize_action_plan` 写失败测试，使用 Fake TTS/expression/output sink 和隔离 ledger store。
- 覆盖普通 Say、预制音频、瞬时表情恢复、sink 拒绝、背压、取消、TTS 首块前/后失败和进程恢复重试。
- 运行 Agent、capability、domain 和存储 focused tests并记录结果。

## Explicit exclusions

- 不实现 Sing、Motion、发布、日记、日程、活动迁移或学歌 Action；它们由对应纵向工单增加。
- 不创建 ChatStage 或协议 Adapter。

## Handoff

一个 realization 核心 PR，包含 Red/Green 证据、进度更新和当前接口文档状态。
