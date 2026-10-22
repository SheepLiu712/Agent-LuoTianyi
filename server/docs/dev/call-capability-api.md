# 通话能力查询 API

`GET /call/capability?character_id={character_id}` 为已登录普通用户提供只读通话能力查询，不会创建 Stage、账本、供应商会话或自动发起通话。

## 鉴权

请求必须包含登录返回的 message token：

```http
Authorization: Bearer {message_token}
```

令牌缺失、格式错误、过期或无效时返回 `401`。接口不接收也不信任 `username`。

## 响应

成功查询总是返回 `200`，响应体严格为：

```json
{
  "available": false,
  "character_id": "luotianyi",
  "reason": "untrusted_host"
}
```

`reason` 是以下稳定枚举之一：`available`、`disabled`、`untrusted_host`、`provider_unavailable`、`call_tts_unavailable`、`summary_unavailable`、`settlement_unavailable`、`stage_binding_unavailable`、`character_unavailable`、`runtime_not_ready`。

当前实现不扫描或补写进程终止后未完成的通话，能力查询不再包含启动恢复门禁或 `recovery_unavailable`。这不影响同进程的三秒网络恢复与维护批次幂等。实现入口为 `src/application/user/call_capability.py`，验证入口为 `tests/unit/web/test_call_capability.py`。

运行时能力按上述就绪条件顺序投影；首个未满足条件决定 `reason`。运行时的能力状态不可用时，接口返回 `200`、`available: false` 和 `runtime_not_ready`，不泄露配置、密钥或内部异常。
