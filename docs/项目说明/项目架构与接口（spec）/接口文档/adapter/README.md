# Adapter 对外接口

## 模块职责

Adapter 把 WebSocket、HTTP、设备或电话等外部协议转换成系统内部数据，并把系统响应转换回外部协议。它负责鉴权、协议校验、ACK/NACK 和连接管理，不负责组织角色回复。

当前实现分布在 `server/src/system/user_interface`、`server/server_main.py` 以及 `server/src/legacy` 的协议转换函数中，尚未合并为顶层 `adapter` 代码目录。

## 当前公开接口

### `WebSocketService`

- `await try_recv_client_msg(connection) -> WSMessage | None`：接收并解析一条客户端消息。
- `await handle_auth_event(...)`：处理 WebSocket 鉴权事件。
- `try_accept_chat_event(...) -> ChatEventAcceptance`：校验一条聊天事件是否应进入流水线。
- `is_chat_related_event(...)`：判断是否为聊天相关事件。
- `convert_to_stimulus(...) -> Stimulus`：把外部消息转换成领域刺激。
- `convert_to_chat_input_event(...) -> ChatInputEvent`：转换为当前 stage 接收的聊天事件。
- `await send_system_ready_event(...)`、`await send_agent_state_event(...)`、`await send_error_event(...)`：发送系统状态。
- `await send_ack_event(...)`、`await send_nack_event(...)`、`await send_duplicate_ack_event(...)`：发送消息接收结果。
- 消息 ID 和重复消息检查方法：保证重试幂等。
- `await handle_ping_event(...)`：处理连接心跳。

### `WebSocketConnection`

- 保存当前连接、用户身份和认证状态。
- `set_user(...)`、`await auth(...)`：在鉴权成功后绑定用户。

### `UserInterface`

供 REST 路由调用的业务边界包括：

- 公钥取得和密码解密。
- 注册、登录、自动登录、密码重置。
- 用户偏好读取和修改。
- 历史记录、历史图片读取。
- 动态列表、评论、未读数量和已读标记。

具体 HTTP 路径由 `server_main.py` 注册；路由应只做参数/响应转换，再调用这些接口或 SystemRuntime 中的服务。

### 协议数据

- `WSMessage(event_type, payload, client_msg_id, ts, reply_to)`：解析后的客户端消息。
- `WSEventType`：WebSocket 事件类型枚举。
- `ChatResponse`：发送给客户端的聊天响应，含文本、音频、表情、最终包标记、音频错误、显示/临时标记等字段。

### legacy 转换函数

- `validate_ws_chat_message(...)`：检查旧 WebSocket 消息格式和大小。
- `ws_message_to_stimulus(...) -> Stimulus | None`：旧协议转换为领域刺激；非聊天事件返回 `None`。
- `stimulus_to_chat_input_event(...) -> ChatInputEvent | None`：领域刺激转换为当前 stage 输入；无法映射为聊天事件时返回 `None`。
- `is_chat_related_ws_message(...)`：判断旧消息是否属于聊天输入。

## 正常与异常行为

- 合法消息转换为 `Stimulus`/`ChatInputEvent` 后交给 stage；Adapter 不直接调用 subconscious 或 capability。
- 协议字段、类型、消息大小或目标角色不合法时抛出校验异常，或向客户端发送 NACK/错误事件。
- 未认证消息不得进入用户聊天流。
- ACK 表示服务器已接受该客户端消息，不等于 Agent 已经生成回复。
- 网络断开、重复 ID、认证失败和发送失败是预期分支，必须有显式行为和测试。

## 使用示例

客户端重发同一个 `client_msg_id` 时，Adapter 识别重复并返回重复确认，不再次把消息送进 stage。新消息通过校验后转换成内部输入，stage 完成处理后，Adapter 再将 `ChatResponse` 编码为 WebSocket 事件。

## 应覆盖的契约场景

- 同一 `client_msg_id` 重发只进入 stage 一次，并收到可识别的重复 ACK。
- 未认证、字段错误、超长文本、超限图片和未知事件都在 Adapter 边界被拒绝。
- 连接断开时发送失败不会被记录成已送达；重新连接后的新消息仍可正常鉴权和入队。
