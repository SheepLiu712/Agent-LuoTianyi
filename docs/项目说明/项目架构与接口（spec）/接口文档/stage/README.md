# Stage 接口

新聊天交互实现位于 `server/src/stage`，按用户与角色管理一个 ChatStage。生产 `/chat_ws` 仍使用 `src/chat_session` 的兼容聊天链路。

## ChatStage

构造：`ChatStage(*, user_id: str, character_id: str, agent: Agent, adapter: WebSocketAdapter, config: dict | None = None, timezone_name: str = "Asia/Shanghai")`。

私有配置类型只校验本模块参数：`max_stimuli=256`、`max_plans=64` 为正整数；`termination_timeout=30.0` 为交互结束处理的等待秒数，`response_wait=1.0` 为新内容的补全等待秒数，均为正有限数。

公共接口：

- `stimulus_input_sink: StimulusInputSink`：唯一刺激接收器。`can_accept(stimulus) -> bool` 检查当前可接收性；`submit(stimulus) -> bool` 同步入队，不等待 Agent。
- `agent_output_sink: AgentOutputSink`：唯一输出接收器。`await emit(output) -> OutputReceipt` 校验当前执行和消息身份后交给 adapter；成功结果表示入队，实际发送结果由 adapter 的 Future 表达。
- `await connection_changed(state: ConnectionState) -> None`：应用连接状态。断线停止当前 handle 和 realize，等待 Agent 清理，清空调度队列及计时器，保留 pending。
- `await terminate(reason: InteractionEndingReason) -> StageTerminationResult`：停止普通工作，使用新的取消令牌向 Agent 发送 InteractionEnding，返回结束处理报告或失败说明。同一次结束请求共享结果。
- 只读身份与状态：`interaction_id`、`user_id`、`character_id`、`state`。

## 调度行为

Stage 在内存中持有输入队列、pending、快照修订号、计划队列、handle 和 realize 任务以及回复期限。两条任务链各自串行，可以同时运行。

内容刺激进入 pending；打字、图片选择、回复期限等协调刺激不进入 pending。新文本、图片、语音和继续输入/选图信号，仅在 Agent 声明当前 handle 可中断时发布 SUPERSEDED；realize 的中断许可单独查询。输入清空、触摸及期限到达不取消当前工作。消费以 HandlingReport 为准；旧报告只移除其明确 consumed 的刺激，保留报告之外新到达的刺激。失败记录日志，不自动重试。

ActionPlanSink 是内部实现。StartThinking 转成 Stage 呈现状态信号；业务计划进入 realize 队列。被取消请求尚未开始的计划被丢弃，已经开始的 realize 不因新刺激自动取消。

每次 realize 分配独立 ExecutionContext 和取消令牌，使用同一个 agent_output_sink。上一轮 Agent 返回并完成必要收尾信号的提交后，才开始下一轮 realize；不等待网络 Future 或客户端播放。缺少终止标记的输出和取消执行通过 CancelDelivery 收尾。已经提交的失败终止包保留原错误。

新内容建立默认补全等待；有 pending 或正在提取时，打字长度大于零等待十秒，清空输入立即到期，打开选图等待六十秒，取消选图恢复默认等待。期限基于刺激 occurred_at 计算。更新补全安排会撤销尚未处理的旧期限刺激。成功报告的 reconsider_at 只在期间没有新补全信号时更新期限，旧报告不能覆盖新输入安排；pending 耗尽则撤销期限。到期由 Stage 自行提交 InteractionDeadline。

## 生命周期与管理

StageState 为 ONLINE、OFFLINE、TERMINATING、TERMINATED。初始为 OFFLINE，adapter.bind 通知上线。离线保留期内重连复用 Stage、interaction_id、pending 和 sink；已经开始终止的交互不会重新上线。

`StageManager(*, get_agent: Callable[[str], Agent], adapter: WebSocketAdapter, config: dict | None = None)` 持有所有 Stage。私有配置类型校验 `offline_timeout=60.0` 为非负有限秒数；`stage` 子配置原样交给 ChatStage。

- `await connect(connection, character_id) -> ChatStage`：取得或创建 Stage，并完成 adapter 绑定。
- `await disconnect(connection) -> None`：标记连接失效、解除该连接当前绑定，并启动离线回收计时；不影响已重连的 Stage。
- `await close() -> None`：停止接入，取消回收计时，终止全部 Stage，等待已经开始的回收及投递清理。

离线超时发送 reason=USER_LEFT 的 InteractionEnding；服务器关闭使用 SHUTDOWN。结束刺激不进入 pending。结束 handler 在 AgentRuntime 中登记，通过角色 ContextFactory 释放已有 context，不创建新 context，也不产生客户端行动。结束处理超时或失败会记录结果并结束 Stage。

SystemRuntime 创建共享 adapter 和 StageManager，并在 AgentRuntime、能力及数据库关闭前关闭 StageManager。StageManager 是新链路的生命周期入口；旧 GCSM 继续管理 ChatStream。

## 兼容聊天链路

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
- 持久化、模型调用和语音生成都有副作用。


## 与旧聊天链路对应的阶段

Agent 默认不允许普通刺激打断 handle 或 realize。话题提取 handler 显式允许中断时，新内容、继续打字或选图使其结果失效；协作取消不直接取消在途 LLM 任务。进入回复生成前关闭 handle 中断许可，之后到达的输入留给后续处理。SAY 保持 realize 不可中断。生命周期关闭仍取消并等待清理。

当前生产文本 handler 仍在旧 ChatStream 链路。新 Agent 的阶段声明和 Stage 调度通过离线 handler 及真实门面验证。
