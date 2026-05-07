# 安全审计报告

**日期**: 2026-05-05
**范围**: 全代码库（server + client）
**方法**: 静态代码审查

---

## 高危 | 硬编码弱 JWT 密钥 + 永不过期 Token

**文件**: `server/src/interface/account.py:73, 81-82`
**类别**: 加密 | 认证绕过
**置信度**: 10/10

JWT 消息令牌使用硬编码的对称密钥 `PRIVATE_KEY = "LUOTIANYI_PRIVATE_KEY_73991"`（仅 27 字符、低熵、纯 ASCII 可打印字符），且 payload 不含 `exp` 过期声明。

### 利用路径

1. 任何拥有源码访问权限的攻击者可用此密钥签发任意 `message_token`
2. 伪造的 token 可通过 WebSocket 认证（`websocket_service.py:78`），以任意用户身份连接
3. 认证后可调用 `GET /history?username=X&token=Y` 读取该用户的全部历史对话
4. 认证后可通过 WebSocket 发送消息冒充用户，或调用 `/get_image` 读取该用户的图片数据
5. Token 永不过期，即使被发现也可持续使用

### 修复建议

- 使用 `secrets.token_hex(32)` 生成随机密钥，从环境变量或配置文件加载
- 在 JWT payload 中添加 `exp` 字段（如 `exp = datetime.now() + timedelta(hours=2)`）
- 在 `decode_message_token()` 中验证 `exp`

---

## 高危 | 密码明文存储

**文件**: `server/src/database/sql_database.py:14`
**类别**: 加密 | 数据泄露
**置信度**: 10/10

```python
password = Column(String, nullable=False) # Plain text as per requirements
```

密码以明文存储在 SQLite 数据库文件中。代码注释说明这是"按需求实现"，但不代表这不是安全漏洞。

### 利用路径

1. 攻击者若获得服务器文件系统访问权限（通过其他漏洞、备份泄露、或服务器失陷），可直接读取 SQLite 数据库文件
2. 所有用户的密码立即可见，且用户可能在其他服务复用相同密码
3. SQLite 数据库文件位于 `data/` 目录下，若存在路径遍历或文件读取漏洞则可直接被读取

### 修复建议

- 使用 `passlib` + `bcrypt` 或 `werkzeug.security.generate_password_hash` 进行哈希存储
- 即使需求文档说"可以明文存储"，也应增加防御纵深

---

## 中危 | 邀请码明文记录日志

**文件**: `server/server_main.py:213`
**类别**: 数据暴露
**置信度**: 9/10

```python
logger.info(f"Register request: {req.username} with code {req.invite_code}")
```

注册请求时会将被邀请码完整地写入日志。邀请码是控制注册权限的唯一凭据（一次性使用）。

### 利用路径

1. 攻击者若获得服务器日志文件访问权限
2. 可从日志中提取尚未使用的邀请码
3. 使用恢复的邀请码完成注册，绕过注册控制

### 修复建议

- 日志中只记录邀请码的哈希或掩码（如 `code[:4] + "****"`）
- 或完全不记录邀请码

---

## 已排除的潜在发现

以下项目经审查后确认不是有效漏洞：

| 项目 | 原因 |
|------|------|
| `__import__` 动态导入 | 遍历硬编码字符串列表，不可注入 |
| `subprocess.run` 在 `generate_cert.py` | curl fallback URL 来自硬编码常量，不可注入 |
| `subprocess.run` 在 `daily_new_song_fetcher.py` | URL 来自硬编码的 `TEMPLATE_URL` 常量 |
| 图片路径遍历 (`/get_image`) | `get_image` 读取 `image_server_path`（服务端代码设定）；`update_image_client_path` 写入不同的键 `image_client_path`，不影响文件读取 |
| HTTP 明文传输 | 密码经 RSA-OAEP 加密；intended deployment 为 127.0.0.1 + SakuraFrp TLS 隧道 |
| LLM 提示词注入 | 属功能设计，用户输入须注入提示词才能让 LLM 理解对话上下文 |
| SQL 注入 | 全部使用 SQLAlchemy ORM 参数化查询 |
| XSS/前端注入 | 纯桌面 Qt 应用，无渲染用户 HTML 的场景 |
| 速率限制缺失 | 已排除（DoS/速率限制不在本次审计范围内） |
