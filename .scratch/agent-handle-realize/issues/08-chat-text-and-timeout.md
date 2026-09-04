# 08: 迁移文字聊天、聚合超时与普通回复

**What to build:** 让有效文字消息从外部入口经过 Adapter、ChatStage、Agent.handle、ActionPlan、Agent.realize 和 Chat output sink 完成回复，同时保持消息去重、pending 聚合、超时强制处理、回复持久化和当前失败行为。

**Blocked by:** 07: 让 ChatStage 通过新 façade 处理输入协调信号。

**Status:** ready-for-agent

**GitHub Issue:** [#67](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/67)

## Decision rule

SPEC 第 5.2—5.4、6.3—6.5、8.2—8.3 节优先。SPEC 没有描述的 LLM fallback、话题抽取和回复排序细节参考当前 TopicPlanner/TopicReplier/Agent failure tests；不得把旧内部对象加入新公开协议。开发守则要求先从公开 flow 得到真实 Red。

## Scope

- 适配 `USER_MESSAGE`/`USER_TEXT` 为 TextMessage，保留非空、长度、角色、client_msg_id、过载和一次持久化校验。
- ConversationTurnHandler 内部组合预处理、MemoryRecall、AttentionSelection、ResponseComposition，并通过 PlanEmitter 产生 Say 或 Sing。
- ChatStage 对每条新内容递增 revision、加入 pending并重置普通期限；当前缺省基线为 1 秒但实现读取配置。
- 普通期限到达形成 InteractionDeadline，以 force-complete 语义处理当时全部 pending。
- 实现 Sing Action 的 SONG_STATE、AUDIO、可选 bridge TEXT/EXPRESSION，并保持普通回复持久化和全局 speaking 顺序。

## Acceptance criteria

- [ ] 有效文字只持久化一次、只进入 pending 一次；相同 client_msg_id 重投不重复消息或回复。
- [ ] 聚合期限前允许多句合并；期限到达后不能因“话没说完”无限等待。
- [ ] deadline trigger 与内容消费分开，全部完成时 consumed 精确等于 snapshot pending 且 retained 为空。
- [ ] 角色明确沉默时以零计划 COMPLETED + consumed 表达，不存在 NO_REPLY Action。
- [ ] Say/Sing 输出顺序、文字/TTS/歌曲/表情和持久回复与当前行为等价。
- [ ] LLM/依赖失败使用稳定错误与现有非空 fallback 语义；不得把异常字符串作为调用方协议。
- [ ] 文字消息不再调用 AgentRuntime 的 preprocess/extract/plan/realize 业务代理。

## Verification

- 从 Adapter 或 ChatStage 公开入口写失败集成测试，最外层模型/TTS 使用 Fake，本项目 stage/Agent 尽量真实连接。
- 覆盖单句、多句、client_msg_id 重投、1 秒默认/配置覆盖、deadline、零计划、Say、Sing、失败 fallback 和顺序。
- 运行 chat integration、stage、Agent 与既有失败模式回归并记录结果。

## Explicit exclusions

- 不迁移图片/语音，不实现慢 Recall 多计划、Reflection 或触摸。
- 暂不删除被其他输入仍使用的旧 Topic pipeline。

## Handoff

一个可演示的文字聊天纵向 PR；进度中列出仍走旧链的输入种类。
