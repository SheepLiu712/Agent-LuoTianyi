# stage 对外接口

## 模块职责

stage 负责一次交互如何流动：接收规范化输入、按用户串行排队、等待话题完整、调用 Agent、安排语音并把响应交给 Adapter。它不决定角色人格，也不实现具体能力。

当前代码目录仍名为 `server/src/chat_session`，本页使用目标名称 stage 描述其现有接口。

## 对外接口

### `ChatSessionManager`

- `wire_dependencies(...)`、`ensure_dependencies()`：注入并检查会话所需服务。
- `start_background_services()`、`stop_background_services()`：启动或停止全局说话队列、主动话题等后台服务。
- `on_user_login(user_id, ...)`：处理登录后的会话级初始化。
- 当前公开属性：`chat_stream_manager`、`call_stream_manager`、`conversation_service`、`global_speaking_worker`、`proactive_topic_maker`、`activity_context_provider`。

### `ChatStreamManager`

- `await get_or_register_chat_stream(ws_connection, character=None, system_runtime=None) -> ChatStream`：按用户取得或建立聊天流。
- `get_stream_by_user_uuid(user_uuid) -> ChatStream | None`：查找活动聊天流。
- `iter_active_streams()`：遍历当前活动流。
- `ws_lost_connection(...)`：通知连接丢失并进入清理或重连等待。
- `start_cleanup_task()`、`await stop_cleanup_task()`、`await cleanup_expired_streams()`：管理过期流清理任务。
- `await stop_all_streams()`：停止全部聊天流。
- `get_GCSM()`：取得全局 ChatStreamManager 的兼容入口。

### `ChatStream`

- `await feed_event(event)`：将规范化输入放入该用户的串行流水线；流正在关闭时抛出 `RuntimeError`。
- `try_feed_event(event) -> bool`：尝试入队，不能接收时返回 `False`。
- `await feed_response(response)`：把响应放入发送阶段。
- `await start_if_needed()`、`await initialize_context()`、`await stop()`、`clean_up()`：控制单个流生命周期。
- `await reconnect(...)`、`lost_connection()`、`owns_connection(...)`：管理 WebSocket 所有权和重连。
- 上下文读取、空闲状态和 `record_sung_segment(...)`：供回复及主动话题逻辑使用。

### `ConversationService`

- `await persist_user_event(...)`：按持久化策略保存用户输入。
- `await persist_agent_replies(...)`：保存可进入对话历史的 Agent 回复。
- `await initialize_context_snapshot(...)`、`await get_context_snapshot(...)`、`await get_context(...)`：建立和读取当前对话上下文。
- 上下文快照包含用户、角色、摘要、最近对话、条数和版本，并可转换为提示词数据。
- `await compress_context_if_needed(...)`：在上下文过长时生成摘要并收缩窗口。

### 全局说话队列

- `await GlobalSpeakingWorker.enqueue(job)`：加入 `SpeakingJob`。
- `start_if_needed()`、`await stop()`：按需启动和停止串行语音工作器。
- `SpeakingJob`：包含待说内容、角色 ID 和完成回调等信息。

该队列在所有用户之间串行执行语音生成，避免 GPT-SoVITS 并发导致显存溢出。

### 主动话题与通话占位

- `ProactiveTopicMaker.configure(...)`、`dispatch_action(...)`、`run_periodic_checks()`、`on_user_login(...)`：生成并派发主动消息。
- `CallStreamManager.wire_dependencies(...)`、`ensure_dependencies()`、`start_background_services()`、`stop_background_services()`：当前只是生命周期占位，尚未提供可用的 `CallStream`。

## 正常与异常行为

- 同一用户的输入按顺序处理；不同用户有各自 ChatStream，但语音生成使用全局串行队列。
- 入队成功只代表已接收，不代表 Agent 回复、语音或发送已经成功。
- 停止流时会取消其拥有的任务；多个关闭错误可能聚合后抛出。
- 连接丢失不会自动等于删除用户会话，重连窗口和最终清理由管理器负责。
- 持久化、模型调用和语音生成都有副作用；stage 必须保留可观测的失败状态。

## 使用示例

用户快速发送两句话时，Adapter 把两条输入交给同一个 `ChatStream`。stage 等待输入完整并组成话题，然后通过 `agent_runtime.get_agent(character_id)` 调用 Agent；得到回复后把需要朗读的部分交给全局说话队列，最后交还 Adapter 发送。

## 应覆盖的契约场景

- 同一用户连续输入保持顺序，不同用户可以推进各自话题，但语音任务始终串行。
- 流关闭后 `feed_event(...)` 明确失败，`try_feed_event(...)` 返回 `False`。
- 连接断开后在允许时间内重连仍回到原流；过期清理后不能复活旧流。
- Agent、TTS 或发送失败时，本轮有可观察的终止结果且后台任务能够退出。

## 依赖边界

目标 handle 输入以 [handle 输入契约](../domain/handle-input.md)为准（输入领域对象已实现，stage 接入及以下运行时行为尚未实现）。stage 不提供历史对话/Recall 上下文引用，不注册或持久化输入快照。stage 拥有 interaction 身份、单调修订号、pending、等待控制及取消决策；快照冻结调用时事实，令牌负责在调用期间通知取消。新刺激使旧判断过时时使用 `SUPERSEDED`；决定无需继续处理时使用 `NO_LONGER_NEEDED`。删除快照里的打字和选图状态副本不删除 stage 的等待流程或既有协调 Stimulus。

目标依赖为 `Adapter -> stage -> agent_runtime -> agent`。当前 stage 仍直接使用部分 Agent 回复类型、SystemRuntime 和 capability 对象，这些属于迁移中的事实接口，不是鼓励新增的调用方式。
