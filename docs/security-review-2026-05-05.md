# 安全审计报告

**日期**: 2026-05-15 (更新)
**原审日期**: 2026-05-05
**范围**: 全代码库（server + client + app）
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

## 中危 | 重置账号接口的邀请码泄露风险

**文件**: `server/server_main.py:188`（新增 `/auth/reset_account` 端点）
**类别**: 数据暴露 | 认证绕过
**置信度**: 8/10

`reset_account` 端点使用已使用的邀请码作为重置凭证。日志中已截断邀请码前缀记录（`code[:4] + "****"`），但仍有以下风险：

### 风险分析

1. **邀请码可猜测性**：如果邀请码生成算法可预测（如递增整数、时间戳），攻击者可批量枚举已使用的邀请码
2. **社交工程**：攻击者可能通过社交工程获取用户的邀请码
3. **一次泄露，永久生效**：与注册不同，重置账号使用的是**已使用**的邀请码，一旦泄露无法重新生成

### 修复建议

- 增加重置请求的频次限制（建议每小时最多 3 次尝试）
- 考虑在邀请码之外增加二次验证（如旧密码验证）

---

## 新增功能安全评估

### 表达风格偏好接口

**文件**: `server/server_main.py` (`/preference/get`, `/preference/overwrite`)
**类别**: 数据安全
**置信度**: 6/10

偏好设置接口使用 `message_token` 进行身份验证，但 token 本身存在硬编码密钥问题（见高危漏洞）。偏好数据本身不敏感，但仍需注意：

1. 偏好数据不会泄露敏感信息
2. 不恰当的偏好注入可能导致 AI 回复风格偏移
3. 建议对 `preference_context` 的长度和内容做基本校验

### 重置账号频次限制

**文件**: `server/server_main.py` (`/auth/reset_account`)
**类别**: 安全加固
**置信度**: 7/10

当前 `/auth/reset_account` 端点未实现频次限制，建议补充：

- 每 IP 每小时最多 3 次请求
- 每个邀请码仅允许成功重置 1 次
- 记录重置历史日志便于审计
- 记录重置请求的 IP 和 User-Agent 以辅助事后追溯
- 重置成功后通过旧用户名推送通知（如果有通知渠道的话）
- 考虑新增更安全的验证方式（如短信验证码、邮箱验证）

---

## 新增 | 好感度系统移除带来的安全改进

**变更**: 好感度系统已从服务端 pipeline 中移除（保留模块代码未删除）
**影响**: 正面改进
- 好感度分析曾涉及 LLM API 调用，移除后减少了外部服务数据传输量
- 不再存储用户情感分析数据（`AffectionLog` 表），减少了隐私数据泄露面
- 减少了数据库写入操作和 API 调用，降低攻击面

---

## 新增 | 客户端自定义服务器地址功能风险

**文件**: `client/src/gui/login_dialog.py`, `app/app/login.tsx`
**类别**: 配置篡改 | 中间人攻击
**置信度**: 5/10

新增"自定义服务器地址"功能允许用户输入任意服务器 URL。虽然设计上会先验证 `/auth/public_key` 端点，但仍存在以下风险：

### 风险分析

1. **恶意服务器伪装**：用户可能被引导连接到攻击者控制的假服务器，该服务器可以：
   - 收集用户的登录凭据（密码经 RSA 加密，但恶意服务器可解密）
   - 记录用户的聊天对话内容
   - 模拟洛天依角色与用户交互（社交工程攻击）
2. **HTTPS 降级**：如果用户输入 HTTP 地址而非 HTTPS，通信将未加密传输
3. **地址持久化**：地址保存在本地配置/AsyncStorage 中，恶意软件可篡改

### 修复建议

- 默认使用内置的已知安全地址，仅在高级设置中开放修改
- 保存非默认地址前增加二次确认弹窗
- 通过 `credential.py` 加密存储自定义服务器地址

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
| XSS/前端注入 | 纯桌面 Qt 应用/React Native，无渲染用户 HTML 的场景 |
| 速率限制缺失 | 已排除（DoS/速率限制不在本次审计范围内） |
| 重置账号越权 | `/auth/reset_account` 需要 invite_code 且仅能重置其关联的账号，无法越权访问其他用户的账号 |
