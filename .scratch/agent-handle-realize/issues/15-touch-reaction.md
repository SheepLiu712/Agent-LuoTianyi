# 15: 迁移触摸快速反应与普通回复回退

**What to build:** 让触摸从 Adapter/Chat 或 Toy stage 形成 TouchInteraction，经 Agent handle 决定快速反射或普通内容回复，再由 realize 输出预制音频和表情；保持当前触摸合流、非持久化和失败回退行为。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；07: 让 ChatStage 通过新 façade 处理输入协调信号。

**Status:** ready-for-agent

**GitHub Issue:** [#74](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/74)

## Decision rule

SPEC 第 5.2/5.3、6.3—6.5、7、8.4 节优先。触摸区域别名、概率、音频候选和 voice-to-expression 映射未说明时参考当前 reflex 配置与测试；不得保留 `try_handle_reflex` 或 Ingress 直接发送响应的旁路。

## Architecture constraints

- 触摸使用独立的 `TouchInteractionHandler`，目标归属 `agent/handlers/stimulus/touch.py`；不要塞入同时负责 typing/deadline 的 coordination Handler。
- 快速候选/注意力/普通回复中可复用的语义放入 `agent/skills/cognitive`，预制音频与表情实现通过 action Handler + `agent/skills/execution`；stimulus Handler 不直接播放媒体。
- 现有 `agent/reflex/*` 只作为迁移源，不保留为第二棵长期目录；本票迁走生产行为，29 号工单删除残余包/导出。

## Scope

- Adapter 校验并归一化 `touchArea/touch_area`、动作、强度/频率和持续时间为 TouchInteraction。
- TouchInteractionHandler/触摸 Skill 按角色配置决定快速反射，选择受支持预制音频与表情，产生 EPHEMERAL_REACTION Say。
- 资源缺失、读取失败或概率未命中时转入普通内容生成并产生 CONVERSATION Say。
- stage 保持待处理触摸合并：未开始时新触摸覆盖；已有触摸处理中后续触摸忽略。

## Acceptance criteria

- [ ] 当前概率 1.0 时从角色 touch_voice_dir 候选选择音频和映射表情，不写会话、不显示气泡。
- [ ] 非 normal 表情在音频结束或 duration 到期后恢复 normal。
- [ ] 快速路径失败不吞触摸，普通回复链仍可观察；两分支都经过 handle 和 realize。
- [ ] 原始供应商字段不进入 Handler，HAPTIC/PerformHaptic 和独立 expression Action 不存在。
- [ ] 合并/忽略规则阻止高频触摸无限排队，且不同 interaction 不串用。
- [ ] `AgentRuntime.try_handle_reflex` 不再有生产调用者。
- [ ] `agent/reflex` 没有新增依赖；新生产路径只经过 stimulus touch Handler、共享 Skill、Action Handler 和 realization seam。

## Verification

- 从触摸入口写失败集成测试，使用固定随机源、临时音频和 Fake output sink。
- 覆盖命中、概率 miss、目录空、读取失败、表情 reset、合并、处理中忽略和普通 fallback。
- 运行 reflex、stage、Agent realization 和 chat integration 回归。

## Explicit exclusions

- 不新增震动输出或硬件 haptic 协议。
- 不实现 ToyVibration/设备生命周期；由 18 号工单负责。

## Handoff

一个触摸纵向 PR；真实设备/音频未验证部分必须单独记录。
