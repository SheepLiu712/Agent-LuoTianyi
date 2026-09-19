# Agent 架构与行为不变量

- **状态**：当前有效
- **更新日期**：2026-09-19
- **适用范围**：`server/src/agent`、`agent_runtime`、`stage`、`infrastructure`、Agent 相关 world 与 Adapter 链路
- **自动化映射**：[`server/tests/INVARIANTS.md`](../../../server/tests/INVARIANTS.md)

本文只保存跨迭代仍需成立的架构和行为约束。旧架构对照、迁移方案、PR 顺序和阶段验收数字已移入 [`归档/Agent重构`](../归档/Agent重构/)。

## 1. 模块归属

1. **Adapter 翻译协议**：外部 WebSocket、电话、机器人或其他供应商事件先转换为强类型 Stimulus；Adapter 不做角色决策。
2. **Stage 拥有交互状态**：pending、准备状态、context 生命周期、期限、打断、重连、计划队列和输出结算归 Stage。
3. **Agent 是深模块**：Stage 与 world 只通过 `handle_stimulus` 和 `realize_action_plan` 使用 Agent，不读取 Handler、Skill、记忆或模型对象。
4. **所有 Agent 共享 Skill**：一个 `AgentRuntime` 只创建一套 `SharedSkills`。每次调用通过不可变的 `SkillInvocation` 注入角色、用户、交互和取消上下文。
5. **Infrastructure 保持中立**：TTS、歌唱资源、VLM、媒体解析和歌曲知识等后端不保存角色业务状态，不反向依赖 agent、world、stage 或 system。
6. **World 提交事实**：world 决定外部何时发生什么，经 WorldStage 提交事实或到期刺激；角色化表达、记忆和行动仍由 Agent 决定。

## 2. 请求与身份隔离

1. 角色资源由 `SkillInvocation.character_id` 选择，用户私有数据由 `SkillInvocation.user_id` 选择；不得依赖共享对象上的“当前角色”或“当前用户”。
2. 不需要用户的世界行为允许 `user_id=None`；需要用户所有权的 Skill 必须明确拒绝缺失身份。
3. 取消令牌只影响所属请求。取消一个请求不得关闭共享模型、清空其他请求状态或中断另一个 Agent。
4. 同一 Shared Skill 并发服务不同角色和用户时，记忆、提示词、模型参数、媒体所有权和结果不得串线。

## 3. 认知、计划与副作用

1. `handle_stimulus` 负责认知决策、Agent 自有状态更新和 ActionPlan 交付；它不直接发送网络输出或伪造外部效果。
2. `realize_action_plan` 只实现既定 Action；每项真实提交的副作用以 `EffectRef` 报告。
3. 行动按计划顺序执行，首个失败停止后续行动；已经成功提交的效果不回滚。
4. 计划已生成不等于效果已发生。world 业务状态和持久化结算只能依据处理/执行回执更新。
5. 当前不提供通用 ledger、outbox、自动重投或进程恢复语义。去重由各业务 owner 的 claim、source identity 和唯一约束负责。

## 4. 持久化与所有权

1. 对话、记忆、动态、日记、事件和媒体分别由其存储 owner 管理；Handler 不直接取得数据库管理器。
2. 用户媒体在调用 VLM 前验证认证用户所有权、大小、MIME、内容完整性和路径安全。
3. 日记、动态、歌曲学习和到期事件沿用各自稳定来源标识；失败不得写成成功或吞掉可诊断原因。
4. 用户明确记忆意图必须先完成可靠写入，再承诺成功；写入失败不能生成虚假确认。

## 5. 输出与世界链路

1. 聊天 Stage 可以通过显式 sink 交付文本、状态、表情、TTS 和歌唱音频；world 不借用聊天连接产生实时 SAY/SING 输出。
2. WorldTask 可以执行外部机械过程并产生事实，但不得直接生成角色人格表达或替代 Agent 写角色记忆。
3. 首次登录、主动提醒、慢召回、触摸反射等路径仍遵守同一 handle → plan → realize 顺序和请求隔离。

## 6. 验证要求

1. 架构依赖由 `server/scripts/check_architecture_boundaries.py` 静态门禁约束。
2. 行为主证据按 [`server/tests/INVARIANTS.md`](../../../server/tests/INVARIANTS.md) 分布在 unit、integration 和少量显式 E2E。
3. 外部 E2E 默认跳过不代表通过；真实模型、凭据、网络、客户端播放和人工交互必须单独记录环境与结果。
4. 当前质量门禁以 Ruff、Black、圈复杂度函数级审查和覆盖率下限为准。规则以 [`server/pyproject.toml`](../../../server/pyproject.toml) 为唯一配置来源；当前结果应直接运行检查取得，测试命令见 [`server/tests/README.md`](../../../server/tests/README.md)，不维护会快速失效的通过数量或覆盖率快照。
