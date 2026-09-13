# Stage 接口


新聊天交互实现位于 `server/src/stage`，按用户与角色管理一个 ChatStage。生产 `/chat_ws` 仍使用 `src/chat_session` 的兼容聊天链路。

## ChatStage

构造：`ChatStage(*, user_id: str, character_id: str, agent: Agent, adapter: WebSocketAdapter, context: InteractionContext, config: dict | None = None, timezone_name: str = "Asia/Shanghai")`。

私有配置类型只校验本模块参数：`max_stimuli=256`、`max_plans=64` 为正整数；`termination_timeout=30.0` 为交互结束处理的等待秒数，必须为正有限数。max_stimuli 同时限制尚未结束的 handle 数量和 pending 数量。

异步创建：`await ChatStage.create(*, user_id, character_id, agent, adapter, context_factory, config=None, timezone_name="Asia/Shanghai") -> ChatStage`。通过 factory.create 加载新上下文后构造 Stage；构造失败关闭已创建对象。同步构造器接管已加载的 context，并校验用户与角色一致，interaction_id 使用 context 的身份。

公共接口：

- `context: InteractionContext`：本交互独占持有的上下文，保留期内重连复用。
- `stimulus_input_sink: StimulusInputSink`：唯一刺激接收器。`can_accept(stimulus) -> bool` 检查当前可接收性；`submit(stimulus) -> bool` 同步入队，不等待 Agent。
- `agent_output_sink: AgentOutputSink`：唯一输出接收器。`await emit(output) -> OutputReceipt` 校验当前执行和消息身份后交给 adapter；成功结果表示入队，实际发送结果由 adapter 的 Future 表达。
- `await connection_changed(state: ConnectionState) -> None`：应用连接状态。断线停止当前 handle 和 realize，等待 Agent 清理，清空调度队列及计时器，保留已完成预处理且未消费的 pending；未完成预处理的输入退出当前流程。
- `await terminate(reason: InteractionEndingReason) -> StageTerminationResult`：停止普通工作，使用新的取消令牌向 Agent 发送 InteractionEnding，返回结束处理报告或失败说明。同一次结束请求共享结果。
- 只读身份与状态：`interaction_id`、`user_id`、`character_id`、`state`。

## 调度行为

ChatStage 持有 context、按接收顺序排列的待回复输入、每条输入的预处理结果、回复尝试和计时器。预处理可以并行完成，输入顺序不随完成顺序变化。Agent 每次只收到 Stage 为本次调用选定的输入范围，借用同一 context。

内部事件入口如下：

| 方法 | 行为 |
| --- | --- |
| `_on_raw_stimulus` | 内容输入登记为预处理中；启动单条 handle。新文本、图片、语音取消已有回复尝试及其排队或执行中的计划。打字和选图只调整等待，不取消回复。触摸独立处理。 |
| `_on_preprocessing_finished` | 将有效 `preprocessed_input` 写入对应输入，标记就绪并计算期限；失败记录日志并移除该输入。 |
| `_on_deadline(revision)` | 验证计时修订及全部输入已就绪，冻结有序批次，创建 InteractionDeadline 请求并启动回复。 |
| `_on_reply_finished` | 依据可信报告移除 consumed 输入及其召回记忆；保留未消费输入。被取消请求的晚返回不参与结算。 |
| `_on_execution_finished` | 移除回复尝试中的已结束计划；回复报告与全部计划均结束后，完成尝试清理并发起 REFLECT 调用。 |

所有状态转换方法同步执行；耗时处理交给独立异步任务，任务返回后调用相应完成方法。每个 handle 使用独立 request_id、令牌与计划接收器。回复期间产出的计划立即入队，不等待完整 HandlingReport。

普通等待从本批最后一条内容预处理完成时起算，默认 1 秒。继续打字把期限延后至该信号到达后至少 10 秒，打开选图为至少 60 秒，关闭选图为至少 1 秒，清空输入则在内容就绪后立即触发。预处理未全部完成时不启动回复。新内容清除旧的额外等待；旧 timer 回调用修订号失效。对应配置为 `response_wait`、`typing_wait`、`image_selection_wait`，均为正有限秒数。

取消回复会保留尚未消费输入的预处理结果，撤销该尝试未执行的计划，并取消当前相关 realize。等待取消清理结束后再开始下一次回复；已经确认消费的输入不会因播放被取消而重新加入。失败回复记录日志，不自动重试；成功但保留输入的回复重新安排普通等待。

realize 按计划交付顺序串行。上一轮 Agent 返回并提交必要收尾信号后才开始下一轮，不等待网络 Future 或客户端播放。触摸可以在文本 handle 等待时产生反馈计划，但不会并行抢占另一个 realize。取消及未关闭的输出经 CancelDelivery 收尾；过期执行不能继续提交输出。

StartThinking 由 Stage 转为呈现状态；最后一个思考请求结束时发送 WAITING。成功回复的报告和全部关联计划均结束后，Stage 以本次 consumed 输入发起 REFLECT；执行报告目前只用于结束关联，不携带给 reflection。占位 reflection 不产生副作用。

原始内容 handler 返回 `PreprocessedInput`；完整业务实现中的理解与持久化在该 handler 内完成。当前 ChatPreprocessingHandler 只返回文本或空的图片/语音理解结果，记录 ID 为空；ChatReplyHandler 只消费整批输入，不生成回复；ChatReflectionHandler 不修改上下文。

## 生命周期与管理

StageState 为 ONLINE、OFFLINE、TERMINATING、TERMINATED。初始为 OFFLINE，adapter.bind 通知上线。离线保留期内重连复用 Stage、interaction_id、pending 和 sink；已经开始终止的交互不会重新上线。

`StageManager(*, get_agent: Callable[[str], Agent], adapter: WebSocketAdapter, get_context_factory: Callable[[str], ContextFactory], config: dict | None = None)` 持有所有 Stage。私有配置类型校验 `offline_timeout=60.0` 为非负有限秒数；`stage` 子配置原样交给 ChatStage。

- `await connect(connection, character_id) -> ChatStage`：取得或创建 Stage，并完成 adapter 绑定。
- `await disconnect(connection) -> None`：标记连接失效、解除该连接当前绑定，并启动离线回收计时；不影响已重连的 Stage。
- `await close() -> None`：停止接入，取消回收计时，终止全部 Stage，等待已经开始的回收及投递清理。

离线超时发送 reason=USER_LEFT 的 InteractionEnding；服务器关闭使用 SHUTDOWN。结束刺激不进入 pending。结束 handler 在 AgentRuntime 中登记，确认结束并返回报告，不释放 context，也不产生客户端行动。Stage 在普通任务及结束处理收尾后调用 context.close；结束处理超时或失败也进入关闭流程。

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
