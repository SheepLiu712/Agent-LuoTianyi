# WebSocket adapter 接口

源码位于 `server/src/adapter/websocket`。SystemRuntime 创建一个共享 WebSocketAdapter，StageManager 持有同一实例；adapter 按交互保存 Stage 与连接的绑定，按实际连接管理投递队列。

## 公共接口

构造：`WebSocketAdapter(config: dict | None = None, *, default_character_id: str = "luotianyi")`。私有配置类型校验每条连接的容量：`max_outputs=256`、`max_bytes=16777216`、`max_messages=64`，均为正整数。呈现状态控制任务也有数量上限。

- `submit_output(output: StageOutput) -> asyncio.Future[None]`：同步接受业务输出或控制命令，返回实际发送结果。无连接、类型不支持或容量不足时抛出 `SinkRejectedError`。Future 成功表示服务端发送完成；取消表示输出被丢弃；异常表示发送失败。
- `receive_event(connection: WebSocketConnection, event: WSMessage) -> bool`：以认证身份转换事件，按绑定找到全部目标 Stage，再向其 `stimulus_input_sink` 投递。全部目标可接收才入队。无目标绑定或非法字段抛出 ValueError；容量或生命周期不允许接收时返回 False。
- `await bind(stage: ChatStage, connection: WebSocketConnection) -> None`：校验用户身份并绑定；重绑先停止旧执行、清理旧投递，再通知 Stage 上线。
- `await disconnect(stage: ChatStage, connection: WebSocketConnection | None = None) -> None`：拆除绑定，通知 Stage 离线，结算待发送输出并等待在途发送退出。指定 connection 时只解除这一连接；旧断线通知不会解除新连接。最后一个绑定移除后释放连接投递任务。
- `supports_input(event: WSMessage) -> bool`：识别文本和打字业务事件。

绑定和拆除操作在调用者取消后仍完成已经开始的生命周期变更。adapter 不另设 send_agent_state、cancel_execution、release 或 close 公共方法。

## 输入协议

`_input.py` 负责输入转换。文本兼容 user_text、user_message、message、chat_message、chat，依次取 message、text、content 的首个非空字符串，清理首尾空白，最多 20,000 字符。user_typing 转成 UserTyping，text_length 为 0 至 100,000 的整数。

认证用户身份来自 connection；payload 不能覆盖身份。文本 ephemeral=false，打字 ephemeral=true，source=USER。顶层 client_msg_id 非空白且不超过 128 字符。刺激 ID 由认证用户和客户端消息 ID 生成。合法非负毫秒 ts 转为 UTC 时间，省略时使用当前时间。

目标兼容 target_character_ids、target_characters、character_ids、target_character_id、character_id；最多八个目标，每项最多 64 字符。省略目标时使用构造时指定的默认角色。

`WebSocketService.try_accept_stimulus_event(connection, event, *, adapter)` 保留网络侧的接收状态、客户端重试去重；重复事件不再次交给 adapter。心跳、认证等连接维护事件不进入 adapter。生产 `/chat_ws` 当前仍使用旧 ChatStream，输入落库也沿用旧流程。

## 输出和控制

`StageOutput` 定义在 `src/domain/stage`，包括：

- `AgentOutput`：支持 TextFinalOutput、ExpressionOutput、AudioChunkOutput、MessageEndOutput。
- `AgentPresentationChanged(interaction_id, state)`：转成 `agent_state_changed`，state 为 thinking 或 waiting。
- `CancelDelivery(interaction_id, execution_id)`：同步标记该执行取消，丢弃未发送内容，返回等待取消收尾的 Future。

`_protocol.py` 转换业务字段，`_delivery.py` 组装 ChatResponse。音频每包最多 48 KiB 原始字节，Base64 编码后发送。消息 UUID 来自交互、执行、行动身份；packet_sequence 在每条消息内从零递增。

同一连接按完整消息顺序投递，一条消息的终止包之后才能发送下一条消息。不同连接独立。CONVERSATION 显示并保留聊天内容；EPHEMERAL_REACTION 不输出文字，使用 display_in_chat=false、is_ephemeral=true。结束不自动恢复表情。

取消不会中断正在发送的单包。已经开始且尚未终止的消息，在当前包结束后发送文字、音频、表情均为空的终止包，error_code=TTS_CANCELLED。尚未开始的消息直接移除。该终止包位于后续消息之前。

已明确提交的失败终止包保留 TTS_EMPTY 或 TTS_STREAM_ERROR。单包发送限时十秒，发送失败标记连接失效、结束待投递 Future，不重发。Future 不表示客户端已播放完成。
