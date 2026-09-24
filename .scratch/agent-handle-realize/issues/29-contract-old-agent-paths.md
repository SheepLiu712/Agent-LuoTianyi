# 29: Contract 阶段删除旧 Agent 业务入口与所有旁路

**What to build:** 在所有调用方已经迁移后，删除旧 AgentRuntime/CharacterRuntime 业务代理、聊天 Topic/Reflection 旁路、旧内部回复类型外泄和 world 直接 capability 调用，使生产依赖图真正只剩 Agent 两个业务 interface。

**Blocked by:** 07: Chat 协调桥；08: 文字聊天；09: 多模态输入；10: 重新思考与结算；11: 慢 Recall；12: 显式记忆；13: settlement 反思；14: 压缩画像；15: 触摸；16: 首次登录；17: due event 主动提醒；18: ToyStage；19: WorldStage；20: 活动规划；21: citywalk；22: 歌曲知识；23: 学歌；24: 动态互动；25: 日记。

**Status:** ready-for-agent

**GitHub Issue:** [#88](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/88)

## Decision rule

SPEC 第 4、6.1、7、8.1，尤其 A1—A9，是唯一目标。遇到仍依赖旧入口的生产调用者时不得删除后让测试失效，也不得保留转发层蒙混验收；回到对应迁移工单完成该调用方。当前接口文档用于识别旧事实，不构成保留承诺。

## Architecture constraints

- 最终目录按 SPEC 6.1 收束：公开协议在 `domain.agent`（或已评审的同等 domain 归属），`agent/__init__.py` 只导出 Agent façade，内部 handlers/skills/context/planning/ledgers/reflection 不对外。
- 删除 `agent/reflex`、旧 `LuoTianyiAgent`/AgentRuntime/CharacterRuntime 业务代理、外部 `agent.main_chat` 响应类型依赖、stage ReflectionWorker 和无生产必要的迁移 adapter。
- Handler 不直接依赖 CapabilityManager/数据库/SystemRuntime；Skill 不反向依赖 Handler/stage/report；factory 只装配。发现违反项必须回到其迁移工单修复，不能在此加永久 compatibility shim。
- `CapabilityManager` 只有在不再承载角色业务选择且仅作为纯技术装配容器时才可保留；是否删除由真实剩余调用决定，不做无关基础设施重写。

## Scope

- 删除 AgentRuntime 的 preprocess/extract/plan/realize/memory/date/profile/reflex 等业务代理及生产使用。
- 删除 `get_character_runtime` 的业务使用和 CharacterRuntime 的角色表达/记忆代理；只保留确有生命周期职责且不泄漏 Agent 内部的结构。
- 删除/内收 TopicPlanner、TopicReplier、ReflectionWorker、OneSentenceChat、SongSegmentChat 等不再需要的生产路径与公开导出。
- 清理 world 为角色认知/表达直接取得 capability/subconscious/Agent 内部对象的依赖；纯机械窄 seam 保留。
- 更新 module interface/architecture 文档，从“目标”切换为当前已实现接口。

## Acceptance criteria

- [ ] `AgentRuntime.get_agent` 返回对象对外只有 handle/realize 两个业务方法；生命周期方法不承载角色业务。
- [ ] stage/world/system 不导入或调用 Handler、Skill、PlanEmitter、Store/Ledger、Reflection、Recall、提示词、模型会话、subconscious 或 capability 实例。
- [ ] 生产调用图不存在 SPEC A6 列出的旧代理、CharacterRuntime 业务或绕过 realize 的角色 capability 路径。
- [ ] 外部只依赖强类型领域协议，不依赖旧 Unread/ExtractedTopic/AttentionPlan/OneSentenceChat/SongSegmentChat。
- [ ] A9 包所有权/依赖扫描通过：无外部内部包导入、无 Handler→capability/database/runtime、无 Skill→Handler/stage/report 反向依赖、无空包/薄转发冒充迁移。
- [ ] 删除旧代码后所有已迁移流程测试仍绿；没有“新 façade + 旧代理”永久双轨或无调用者公开入口。
- [ ] Call/Realtime 和未实现事件没有因清理被顺便添加。

## Verification

- 先增加会因旧生产依赖存在而失败的架构/依赖测试，再做删除和最小修复。
- 使用静态依赖扫描、公开属性/导出检查和所有迁移流程回归；不要只搜索方法名，需确认动态导入/组装。
- 运行完整 Server 默认测试并记录收集数、通过/跳过/失败；外部真实依赖仍单列。

## Explicit exclusions

- 不重写已通过新 façade 的内部 Handler/Skill，不做无关目录美化。
- 不创建兼容转发层延长旧 API 寿命；发现缺失调用方迁移时停止。

## Handoff

这是 expand–migrate–contract 的 contract PR。必须附依赖扫描结果、删除清单、完整回归和进度更新。
