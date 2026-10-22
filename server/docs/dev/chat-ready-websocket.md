# 聊天 WebSocket 就绪标记

`/chat_ws` 保留原有 `system_ready`、认证和 `auth_ok` 握手。`auth_ok` 只代表凭据校验成功，不能代表聊天已可用。

只有 `WebSocketAdapter.open`（内部通过 `StageManager.try_to_get_stage` 获取交互） 完成真实 `ChatStage` 绑定后，服务端才发送：

```json
{
  "type": "chat.ready",
  "payload": {
    "character_id": "luotianyi",
    "interaction_id": "...",
    "schema_version": 1
  }
}
```

当同一用户和角色被 `CALL` 或 `CALL_TRANSITION` lease 占用时，聊天接入不会创建或绑定 ChatStage，而是发送：

```json
{
  "type": "error",
  "payload": {
    "code": "INTERACTION_OWNED_BY_CALL",
    "message": "chat interaction is temporarily owned by a call",
    "retryable": true
  }
}
```

随后服务端以 close code `1013` 关闭该连接。无效认证仍使用既有认证错误与关闭路径，不是可重试的 ownership 错误。旧客户端可安全忽略未知 `chat.ready`：桌面和 CLI 的事件解析会将未知 type 解析为 `None`，App transport 仅处理已知事件类型。
