# Agent `handle_stimulus / realize_action_plan` 深模块重构进度

- 大目标：以两个有限 Agent interface 统一角色对刺激的认知决策与动作实现，逐步迁移聊天、玩偶和 world 调用链，并最终删除旧 AgentRuntime 业务代理和任意 Mapping 协议。
- PRD：[`Agent-handle-realize-深模块重构.md`](../需求说明（PRD）/Agent-handle-realize-深模块重构.md)
- 总体设计背景：[`Agent-handle-realize-深模块重构.md`](../设计文档/Agent-handle-realize-深模块重构.md)
- interface spec 索引：[`Server 模块接口文档`](../../项目说明/项目架构与接口（spec）/接口文档/README.md)
- 对应工单：[GitHub #60—#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues?q=is%3Aissue%20number%3A60..89)
- 总体状态：进行中

## 已完成事实

### 2026-09-05 Agent 深模块需求与总体设计基线

- 交付内容：确定 Agent 只保留 `handle_stimulus` 与 `realize_action_plan` 两个业务 interface，明确 Agent、stage、Adapter、world、subconscious、capabilities 和 AgentRuntime 的职责与迁移边界，并发布实现工单 #60—#89。
- 文档：上述 PRD、总体设计背景和根目录 [`CONTEXT.md`](../../../CONTEXT.md)。
- commit 或 PR：`refactor/agent` 历史提交 `8e00241d` 至 `816db81a`。
- 验证及结果：完成设计文档、领域词汇和工单之间的静态核对；该记录不表示产品实现或端到端链路已经完成。
- 未验证范围：真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为。

### 2026-09-05 迁移期 `TextMessage` 最小公开入口

- 交付内容：`src.domain.agent` 已提供迁移期 `TextMessage`、`StimulusKind.TEXT_MESSAGE` 和 `StimulusSource.USER`，旧 Stimulus 与该入口暂时共用 `PersistPolicy`。
- interface spec：[`domain/README.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/README.md) 中标明的当前实现。
- commit 或 PR：PR #90，当前重放提交 `ede19abb`。
- 验证及结果：合入时的公开构造契约测试为 Green；该结果只证明迁移期入口，不证明本轮目标契约。
- 未验证范围：抽象 `Stimulus`、完整字段校验、稳定错误、移除目标包的 `PersistPolicy` 以及生产调用链迁移。

### 2026-09-05 `Stimulus / TextMessage` 首个行为切片 SPEC

- 交付内容：完成抽象 `Stimulus`、具体 `TextMessage`、`StimulusKind.TEXT_MESSAGE`、四种 `StimulusSource` 和构造错误的目标 interface 定义；明确无 `payload`、无公开 `PersistPolicy`、无字段组合白名单。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`。
- 验证及结果：只完成 SPEC 文件的静态检查，尚未产生 Red 或 Green 证据。
- 未验证范围：契约测试、产品实现、领域模块回归和所有真实外部环境。
