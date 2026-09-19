# agent.skills 对外接口

## 模块职责

`server/src/agent/skills` 承载角色业务技能。一个 `AgentRuntime` 只创建一个 `SharedSkills`，所有角色 Agent 共享其中的 Skill 实例；角色、用户与交互身份不保存在 Skill 上，而由每次调用的 `SkillInvocation` 显式传入。

Skill 决定“角色如何理解、表达、记忆或行动”。TTS 模型、歌曲文件、VLM、媒体文件和歌曲知识库等中立资源由 `infrastructure` 提供，不能反向持有角色业务状态。

## 调用契约

### `SkillInvocation`

- `character_id`：本次调用代表的角色。
- `user_id`：本次调用所属用户；允许为 `None`，需要用户的 Skill 必须调用 `require_user_id()` 明确拒绝缺失值。
- `interaction_id`：本次交互的稳定标识。
- `cancellation`：请求隔离的取消令牌。

它是不可变值对象。Handler 必须从已认证请求和当前上下文创建它，不得依赖共享对象上的“当前角色/当前用户”。

### `SharedSkills`

`SharedSkills` 通过具名属性公开完整装配的 Skill，不提供字符串 `get/register` 服务定位器。主要属性包括：

- 认知：`text_preprocessing`、`image_preprocessing`、`response_composition`、`reflection`；
- 记忆：`intentional_memory`、`dynamic_topic_memory`、`learned_song_experience`；
- 表达：`speaking`、`singing`、`dynamic_publishing`、`dynamic_reply`、`diary_writing`；
- 反射与学习：`touch_reaction`、`song_learning`、`song_knowledge`；
- 会话：`conversation_compaction`。

这是 `AgentRuntime` 的内部装配面，不是 stage、world 或网络层可直接调用的公共入口。外部模块只调用 Agent 的 `handle_stimulus` 与 `realize_action_plan`。

## 资源选择与隔离

- 角色记忆、回复生成器、人设、表达风格和触摸资源以 `character_id -> resource` 映射注入共享 Skill。
- 用户记忆和私密动态必须使用 `SkillInvocation.user_id`；缺少用户身份时明确失败或走公开世界行为，不能使用默认用户。
- 并发调用不得修改全局角色上下文。两个角色、两个用户同时调用同一个 Skill 时，资源选择、模型参数、记忆写入和结果必须互不串线。
- Skill 构造时校验必需依赖；运行时遇到本应可调用却不可调用的依赖时应明确报错，不把装配错误伪装成业务降级。

## 正常与异常行为

- 说话和唱歌 Skill 返回可实现的动作素材；实际字节由注入的语音/歌唱后端生成。
- 图片预处理先通过 `MediaResolver` 做所有权和内容校验，再调用图片理解端口。
- 动态、回复和日记由 Skill 生成角色化内容并通过数据库操作对象持久化；幂等键仍由对应业务 owner 维护。
- 取消只影响所属请求；一个请求取消不得关闭共享模型，也不得中断其他 Agent 的调用。

## 必须覆盖的契约场景

- 多角色、多用户并发调用同一个 Skill，角色资源与用户数据不串线。
- 缺少角色资源、用户身份或必需依赖时稳定失败。
- 可取消的说话/回复调用只取消本请求，并完成本次生成器清理。
- 同一来源的动态、日记和歌曲学习结果保持各自既定幂等语义。
