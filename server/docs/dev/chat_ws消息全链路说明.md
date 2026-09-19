# Chat WebSocket 消息全链路

本文记录 Agent contract 收口后的唯一生产链路。旧 `chat_session`、`subconscious`、`legacy` 包已删除，不再作为兼容入口或运行时对象图存在。

## 入站链路

1. `server_main.py` 接收并认证 WebSocket 消息。
2. `WebSocketService.try_accept_stimulus_event` 完成消息 ID 校验、去重和接收状态映射。
3. `WebSocketAdapter.receive_event` 校验协议载荷，把消息转换为 `src.domain.agent.Stimulus`，并投递给目标 `ChatStage`。
4. `ChatStage` 持有 pending、调度、取消和交互修订；到期时只调用 `Agent.handle_stimulus`。
5. `StimulusRouter` 把强类型刺激路由到对应 handler。文本/图片等输入先预处理；回复到期由 `ChatReplyHandler` 处理。

## Agent 内部

`AgentRuntime` 是组装根，但不再构造 `CharacterRuntime` 或意识/潜意识聚合对象。每个启用角色直接拥有四类私有技能：

- `AgentMemory`：长期记忆召回、写入和用户画像适配；
- `CharacterReplyGenerator`：角色提示组装、模型调用与结构化回复解析；
- `ResponseCompositionSkill`：组合记忆召回、演唱计划、回复生成和歌词补全；
- `ReflectionSkill`：结算后的记忆沉淀与画像更新。

共享技能仍由 `Skills` 持有，例如输入预处理、对话压缩、说话与演唱。handler 只依赖所需技能的窄接口，不读取角色聚合对象。

## 出站链路

1. `ChatReplyHandler` 生成 `ReplyDraft`，持久化正式对话记录，并提交 `ActionPlan`。
2. `ChatStage` 接受计划并调用 `Agent.realize_action_plan`。
3. `ActionRouter` 将 `Say`、`Sing` 等行动交给对应 handler。
4. handler 通过能力层产生 `StageOutput`；`WebSocketAdapter` 负责连接绑定、顺序发送、取消和背压。

## 边界约束

- 外部认知调用只有 `handle_stimulus` 与 `realize_action_plan`，调用点只允许在 Stage。
- WebSocket 层只接受 `src.domain.agent` 的强类型刺激，不提供旧 `ChatInputEvent` 或旧 `Stimulus` 转换入口。
- Agent 记忆实现位于 `src/agent/skills/adapters/memory`；歌曲知识数据库与实体链接位于 `src/capabilities/song_knowledge`。
- 架构扫描禁止重新引入 `src.chat_session`、`src.subconscious`、`src.legacy`、旧领域刺激或旧角色对象图。
- wheel 打包测试同时验证新包存在、三个旧包不存在。

静态验收命令：

```powershell
python scripts/check_architecture_boundaries.py
```
