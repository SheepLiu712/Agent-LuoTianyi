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

### 2026-09-05 `Stimulus / TextMessage` 领域契约实现

- 交付内容：实现不可直接构造的抽象 `Stimulus`、不可变 `TextMessage`、四种 `StimulusSource`、固定 `TEXT_MESSAGE` 判别值和稳定构造错误；目标包不再导出 `PersistPolicy`，迁移期旧 Stimulus 继续从旧路径使用自己的持久化协议。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `31281005`。
- 验证及结果：Red 阶段聚焦测试为 39 failed、1 passed；最小实现后 `python -m pytest tests/domain/test_stimulus_text_message_contract.py -q` 与 `python -m pytest tests/domain -q` 均为 40 passed。启用临时测试收集策略前，默认 Server 回归为 477 passed、2 skipped、6 failed；失败位于 diary、preferences、proactive topic、runtime shutdown 和依赖真实数据的 Bilibili 测试，均不在本切片修改路径内。按项目负责人决定，之后只执行本切片新增契约测试；重新运行 `python -m pytest tests -q` 为 40 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：生产调用链迁移、真实聊天、玩偶、world、LLM、TTS、GPU、设备和生产环境行为；默认 Server 回归中的 6 个本切片外失败尚未在本切片处理。

### 2026-09-06 当前总 SPEC 的 Stimulus 领域契约实现

- 交付内容：实现当前总 SPEC 登记的全部 `StimulusKind`、15 个不可变可构造 Stimulus、7 个统一拒绝构造的占位类型，以及受控引用、动态消息、触摸频率、world/activity 事实和歌曲知识候选等领域值类型；所有构造入口保持仅限关键字、无任意 `payload`、无 `PersistPolicy`，也不校验字段间的生产场景组合。
- interface spec：[`domain/stimulus.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/stimulus.md)。
- commit 或 PR：分支 `codex/agent-01-stimulus-text-message-contract`；Red commit `f85c9e03`；Green commit `de71ae97`；审核补测与文件拆分为本记录所在收尾提交及其前一提交。
- 验证及结果：Red 阶段聚焦测试为 41 passed、92 failed，失败集中在尚未实现的登记类型、枚举、值对象和校验；Green 后聚焦测试为 133 passed。审核补充的 3 个受控引用名义隔离测试在既有实现上首次即通过，无 Red 证据；职责拆分后聚焦测试为 136 passed。`python -m ruff check src/domain/agent src/domain/stimulus.py tests/domain/test_stimulus_text_message_contract.py tests/domain/test_stimulus_registered_types_contract.py` 与 `python -m compileall -q src/domain/agent` 通过；按项目负责人要求运行 `python -m pytest tests -q` 为 136 passed、445 skipped，跳过项不构成回归通过证据。
- 未验证范围：15 个可构造类型尚未接入生产 Adapter、stage、world 或 Agent handle；受控引用读取 port、`HandleStimulusRequest.interaction.pending_stimuli`、真实数据库/媒体、聊天、通话、玩偶、LLM、TTS、GPU、设备和生产环境均不在本行为切片内。

### 2026-09-06 handle 输入 SPEC 第一版

- 交付内容：完成供评审的 handle 输入文档，定义 `HandleStimulusRequest`、Chat/Toy/World 快照、必要值类型及可变 `CancellationToken`；记录交互身份与修订号的区别、删除的状态字段、两类取消原因及首次取消语义，并同步接口索引、总体设计背景、PRD 说明和领域词汇。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，状态为第一版、待评审且尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：文档静态核对完成；新增 SPEC 的 UTF-8、代码围栏、九项用户结论相关词项及新增相对链接检查通过；`git diff --check` 通过。文档交付的运行时 Red/Green 不适用。
- 未验证范围：本记录只证明 SPEC 文档交付；没有新增产品代码或测试，没有实现 handle 输入类型、取消处理、Agent/stage 链路，也没有完成他人评审或远程 PR 合并。

### 2026-09-06 handle 输入 SPEC 的上下文归属修订

- 交付内容：删除输入中的 `conversation_ref`、`visible_world_ref` 和通用 `SnapshotRef`；明确 Agent 内部按角色与 interaction 管理历史对话、摘要及 Recall 工作上下文，清理临时上下文不删除长期正本，取消单次 handle 不等于结束 interaction。输入快照直接按值传递，不建立快照持久化或 ID 解析机制；world 内容通过已有强类型 Stimulus 传入。同步总体架构、设计背景、PRD、接口文档、领域词汇和验收场景。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)，修订版待评审、尚未实现。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：删除字段及导出、保留身份/修订/取消契约、文档 UTF-8、代码围栏、变更相对链接与 `git diff --check` 静态检查通过；运行时 Red/Green 不适用。
- 未验证范围：没有新增产品代码或运行时测试；Agent 工作上下文与清理、world 处理、后台反思证据生命周期均未实现或验证，本记录不代表运行时交付。

### 2026-09-06 删除独立演唱状态输出草案

- 交付内容：从 handle 输入的输出能力枚举、PRD 输出列表和总体设计中删除 `SONG_STATE`，移除 `SongPlaybackState` 草案引用；演唱使用音频及可选文字、表情输出。
- interface spec：[`domain/handle-input.md`](../../项目说明/项目架构与接口（spec）/接口文档/domain/handle-input.md)。
- commit 或 PR：分支 `codex/agent-02-handle-input-contract`，本记录所在 SPEC 提交。
- 验证及结果：三个相关契约文档的定义及引用残留检查、`git diff --check` 通过；文档修改的运行时 Red/Green 不适用。
- 未验证范围：未修改产品代码或测试，未验证运行时演唱链路。
