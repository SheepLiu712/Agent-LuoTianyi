# legacy 对外接口

## 模块职责

`server/src/legacy` 只保存迁移期间仍被调用的旧协议兼容代码。这里不是新功能的落点；接口使用者应能明确说明它在替代哪一段旧行为以及何时删除。

## 当前对外接口

包级公开接口：

- `ws_message_to_stimulus(message, ...) -> Stimulus | None`：把旧 WebSocket 消息转换成领域刺激；非聊天事件返回 `None`。
- `stimulus_to_chat_input_event(stimulus) -> ChatInputEvent | None`：把新领域刺激转换成当前 stage 仍使用的聊天输入；不支持的刺激返回 `None`。

实现模块还提供：

- `validate_ws_chat_message(message)`：校验旧消息。
- `is_chat_related_ws_message(message) -> bool`：判断旧消息是否应进入聊天链路。

## 协议限制

- 文本最大 20,000 个字符。
- 图片 Base64 字符串最大约 8 MB，解码后最大约 6 MB。
- 单条刺激的目标角色最多 8 个。
- touch 数据的单个序列最多 16 项。

具体字段和限制以实现中的校验常量为准；修改时必须同步 Adapter 契约测试。

## 正常与异常行为

- 转换本身不访问网络、数据库或模型。
- 字段缺失、类型错误、内容过大或目标不合法时抛出 `TypeError`/`ValueError`。
- 转换必须保留 `client_msg_id`、目标角色、临时/持久化策略等语义，不能只复制文本。

## 使用示例

迁移期间，旧客户端消息先经 `ws_message_to_stimulus` 进入新领域协议，再由 `stimulus_to_chat_input_event` 适配尚未迁移的 stage。等 stage 直接接收 `Stimulus` 后，第二层适配即可连同测试一起删除。

## 应覆盖的契约场景

- 转换前后的 `client_msg_id`、用户、目标角色、临时标记和持久化策略保持一致。
- 非聊天事件返回 `None`；文本、图片、touch 和目标数量超限时在转换前被拒绝。
- 支持的旧事件都映射为确定的 `StimulusModality`，不存在静默降级为普通文本的路径。

## 新代码约束

- 不得在 legacy 中实现新的业务分支。
- 不得让新模块依赖旧数据结构；兼容方向只能是“旧输入转成新协议”。
- 删除接口前先用 `rg` 确认所有调用点，并更新本目录文档与相关测试。
