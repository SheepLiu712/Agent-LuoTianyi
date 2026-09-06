# 04: 扩展两接口 Agent façade 与内部路由

**What to build:** 让 `AgentRuntime.get_agent(character_id)` 返回稳定的 Agent façade；新 façade 对业务调用方只提供 `handle_stimulus` 与 `realize_action_plan`，统一做契约校验、角色绑定、错误转换、取消入口和 Handler 路由，保留旧业务流程，仅调整兼容对象获取位置。

**Blocked by:** 01: 固定 handle 侧强类型领域契约；02: 固定 realization 侧强类型领域契约。

**Status:** ready-for-agent

**GitHub Issue:** [#63](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/63)

当前契约以 [Agent 门面 SPEC](../../../docs/项目说明/项目架构与接口（spec）/接口文档/agent/facade.md) 为准。

## Decision rule

SPEC 第 4.2、5.1、6.1、6.3、7、8.1 节优先。装配细节不清时参考当前 AgentRuntime/角色注册和 SystemRuntime 生命周期；不得把旧代理方法复制到 façade，也不得新增 service locator。需要第三个业务方法时停止并修订 SPEC。

## Architecture constraints

- 只新增 `agent/facade.py` 定义 Agent；AgentRuntime 初始化时直接组装新 Agent，SystemRuntime 仍是系统 composition root。
- 路由注册暂留 facade.py 内部，精确注册/失败，不做内容决策；本版生产注册集合为空。
- `agent/__init__.py` 只导出 façade 对外所需的 `Agent` 类型；装配由 AgentRuntime 负责。Handler、Skill、context、planning、ledger、reflection 均为私有包，外部生产模块不得导入。
- 迁移期适配旧实现只能藏在 façade/Handler 之后并有后续删除工单；不得把 `LuoTianyiAgent` 或 `CharacterRuntime` 作为新 façade 字段泄漏。

## Scope

- 每个启用角色创建并缓存一个 façade，明确绑定角色身份和内部依赖。
- `handle_stimulus` 根据 StimulusKind 唯一路由 Stimulus Handler；`realize_action_plan` 根据 ActionKind 唯一路由 Action Handler。
- façade 负责公开 request/plan 校验、稳定错误码、统一观测和 shutdown 接受边界；Handler/Skill 仍为内部对象。
- 迁移期保留旧 AgentRuntime 代理和 CharacterRuntime 供未迁移调用者使用，但新 façade 不暴露它们。

## Acceptance criteria

- [ ] 相同 character ID 返回同一 façade；未知显式 ID 稳定失败且不回退默认角色。
- [ ] façade 的业务表面只有两个 SPEC 方法；sink 是调用参数，不是额外业务入口。
- [ ] `agent/__init__.py` 的公开导出检查通过；外部测试和调用方不能取得 Router/Handler/Skill 或旧 runtime 对象。
- [ ] 未注册 kind、版本不兼容、目标角色或 interaction 不匹配在进入模型/capability 前失败且不消费 pending。
- [ ] 每个 kind 至多注册一个 Handler；未知 kind 不回退通用 LLM。
- [ ] shutdown 后拒绝新工作，并对已接受内部工作执行完成、可靠保留或明确失败的策略。
- [ ] 生产旧链通过保留的兼容入口工作；本票不宣称 A6 已完成。

## Verification

- 通过 `AgentRuntime.get_agent` 和两个公开方法编写失败测试，外部测试不直接实例化或断言私有 Router/Handler。
- 使用 Fake sink/已注册内部测试协作者验证路由和失败面；记录 AgentRuntime/lifecycle focused tests。

## Explicit exclusions

- 不实现具体聊天、触摸、world 语义，不实现 ledger 或真正的 Action capability。
- 不删除全局兼容入口；删除由 29 号 contraction 工单负责。

## Handoff

一个 expand PR，只包含 façade/路由、测试、接口文档当前状态和进度更新。
