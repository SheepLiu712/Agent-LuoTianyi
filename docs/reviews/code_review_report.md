# Agent-LuoTianyi 全仓库代码审查报告

**审查范围**: `server/` (FastAPI), `client/` (PySide6), `app/` (React Native)  
**审查日期**: 2026-05-25  
**审查版本**: `live-2d` branch @ `de999f4` (merged `upstream/dev`)

---

## 目录

- [总体评分](#总体评分)
- [Critical 级问题](#critical-级问题)
- [High 级问题](#high-级问题)
- [Medium 级问题](#medium-级问题)
- [Low 级问题](#low-级问题)
- [架构设计评审](#架构设计评审)
- [数据流评审](#数据流评审)
- [整改建议优先级](#整改建议优先级)

---

## 总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **安全性** | ⚠ 3/10 | 8个 Critical 漏洞，涉及密码明文存储、硬编码密钥、令牌泄露、文件路径穿越 |
| **架构** | ✅ 6/10 | 分层清晰但全局可变单例泛滥，fire-and-forget 异步任务无错误追踪 |
| **代码质量** | ⚠ 5/10 | 多处遗留死代码、重复声明、未使用变量、TODO 未清理 |
| **可测试性** | ⚠ 3/10 | 全局单例、模块级副作用、文件/网络耦合导致单元测试困难 |
| **文档** | ✅ 7/10 | 有 PRD 和部分文档，但代码内注释不足 |

---

## Critical 级问题

### CR-1: 密码明文存储 (Server)

**文件**: `server/src/database/sql_database.py:14`  
**文件**: `server/src/interface/account.py:118,131`

```python
# sql_database.py:14
password = Column(String, nullable=False)  # actual: plain text per requirements
```

代码注释明确承认密码以明文存储。`register_user` 和 `verify_user` 直接在原始密码字符串上操作。数据库泄露将导致所有用户密码泄露。

**整改**: 使用 `bcrypt` 或 `argon2` 哈希密码。

---

### CR-2: 硬编码 JWT 签名密钥 (Server)

**文件**: `server/src/interface/account.py:73`

```python
PRIVATE_KEY = "LUOTIANYI_PRIVATE_KEY_73991"
```

硬编码、静态字符串用作 HS256 JWT 的 HMAC 密钥。任何能读取源代码的攻击者都可以伪造任意用户的 `message_token`，实现会话劫持。

**整改**: 使用 env 变量注入密钥，启动时检查 `os.environ.get("JWT_SECRET")`，若不存在则拒绝启动。

---

### CR-3: 明文凭据存储 (Client)

**文件**: `client/src/safety/credential.py:39-47`

```python
data = {
    "username": username,
    "token": token,         # <-- PLAINTEXT
    "auto_login": do_auto_login,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ...)
```

`login_token` 和 `message_token` 以明文 JSON 存储在 `<cwd>/temp/user.json`。任何以同一用户身份运行的进程都可以读取该文件并窃取令牌。

**整改**: 使用 Windows Credential Manager 或加密存储。

---

### CR-4: SSL/TLS 验证可被静默禁用 (Client)

**文件**: `client/config/config.json:6`  
**文件**: `client/src/network/ws_transport.py:399-404`  
**文件**: `client/src/utils/http_client.py:17-19`

`config.json` 中 `"verify_ssl": false`，导致：
- HTTP: `CERT_NONE`, `check_hostname = False`
- WebSocket: `ssl._create_unverified_context()`

**整改**: 移除 debug 配置中的 `verify_ssl: false`，任何时候都改用验证模式。

---

### CR-5: 令牌泄露至 URL 查询参数 (Client + App)

**文件**: `client/src/network/network_client.py:217-222`  
**文件**: `app/utils/getHistory.ts:43-49`  
**文件**: `app/utils/getAffection.ts:19-23`

`message_token` 以 URL 查询参数形式传递：

```
/history?username=xxx&token=xxx&count=20&end_index=-1
```

令牌暴露给：服务器访问日志、Referrer 头、网络中间设备（代理/CDN）、浏览器历史。

**整改**: 移至 `Authorization: Bearer <token>` 头或 POST body。

---

### CR-6: 路径穿越 — 服务器返回的 UUID 直接用于文件路径 (Client)

**文件**: `client/src/network/network_client.py:284`  
**文件**: `client/src/message_process/message_processor.py:177`

```python
new_file_path = os.path.join(cwd, "temp", "images", item.uuid + postfix)
wav_path = os.path.join(os.getcwd(), "temp", "tts_output", f"{conv_uuid}.wav")
```

如果服务器被攻陷或返回恶意 `uuid`（含 `../`），攻击者可在任意位置写入/读取文件。

**整改**: 对 `uuid` 进行白名单校验（仅允许 `[a-zA-Z0-9_-]`），拒绝包含路径分隔符的值。

---

### CR-7: 非 UI 线程操作 OpenGL/Live2D 模型 (Client)

**文件**: `client/src/message_process/message_processor.py:208`

```python
if response.expression and self.model:
    self.model.set_expression_by_cmd(response.expression)
```

`process_transport_message()` 在后台 daemon 线程中运行，直接调用操作 Live2D 模型（包含 GL 调用）。PySide6 的 OpenGL 上下文是线程绑定的，跨线程操作导致未定义行为或崩溃。

**整改**: 通过 Qt 信号将表达式更新发回 UI 线程执行。

---

### CR-8: WebView 权限配置过度 (App)

**文件**: `app/app/index.tsx:154-159`

```typescript
originWhitelist={["*"]}
allowFileAccess={true}
allowUniversalAccessFromFileURLs={true}  // also allowFileAccessFromFileURLs
```

WebView 允许访问任意源、文件系统。攻击者若通过 MITM 或恶意模型文件注入 JS，可读取设备文件系统。

**整改**:
- `originWhitelist={['file://']}`
- 移除 `allowFileAccessFromFileURLs` 和 `allowUniversalAccessFromFileURLs`
- 添加 Content Security Policy

---

### CR-9: 令牌存储在明文 AsyncStorage (App)

**文件**: `app/hooks/useAuth.ts:119-127`

自动登录令牌以明文存储在 `@react-native-async-storage` 中。Android 上该数据位于未加密的 SQLite 数据库，root 设备、备份均可读取。

**整改**: 使用 `expo-secure-store`。

---

## High 级问题

### H-1: 认证端点无频率限制 (Server)

**文件**: `server/server_main.py:188-298`

`/auth/login`、`/auth/register`、`/auth/auto_login` 等端点均无频率限制、无验证码、无帐号锁定机制。可被暴力破解。

### H-2: 用户名枚举（差异化错误消息）(Server)

**文件**: `server/src/interface/account.py:107-110`

注册返回 "邀请码无效" vs "用户名已存在"，登录返回差异化消息。允许攻击者枚举有效用户名。

### H-3: 敏感信息记录到日志 (Server)

**文件**: `server/server_main.py:206,233,257,284`

```python
logger.info(f"Register request: {req.username} with code {req.invite_code}")
logger.info(f"Login request: {req.username}")
```
**文件**: `server/src/agent/luotianyi_agent.py:111`
```python
self.logger.info(f"Saved preferences for user {user_uuid}: {preferences}")
```

用户名、邀请码、偏好设置全部明文写入日志。

### H-4: `eval()` 调用在 MSAF 模块中 (Server)

**文件**: `server/src/plugins/music/song_learner/src/msaf/run.py:37`

```python
module = eval(algorithms.__name__ + "." + boundaries_id)
```

`eval()` 用字符串拼接调用，若 `boundaries_id` 可受外部输入影响，即任意代码执行。

### H-5: WebSocket 认证仅连接时一次 (Server)

**文件**: `server/src/interface/websocket_service.py:301-318`

WebSocket 认证握手仅在连接时执行一次，后续消息不再重新验证。若 WebSocket 连接被劫持，攻击者可冒充用户发送任意消息。

### H-6: 子进程 API Key 泄露 (Server)

**文件**: `server/src/plugins/music/auto_song_learner.py:281-293`

API Key 通过环境变量传递给子进程，在 Linux 上可通过 `/proc/<pid>/environ` 读取。

### H-7: Logger 装饰器记录所有函数参数 (Client)

**文件**: `client/src/utils/logger.py:185`

```python
logger.debug(f"调用函数: {func.__name__} with args={args}, kwargs={kwargs}")
```

若装饰器应用于登录/注册函数，密码将以明文出现在日志文件中。

### H-8: 服务端 URL 一键信任 (TOFU) (Client)

**文件**: `client/src/gui/login_dialog.py:292-317`

用户输入任意 URL，自动加 `https://`，成功获取 `/auth/public_key` 即信任。无证书指纹验证、无二次确认。

### H-9: WebView 消息输入校验不足 (App)

**文件**: `app/hooks/useChatLogic.ts:180-214`

`handleWebViewMessage` 仅校验 JSON 格式，未校验 schema 或白名单。被攻陷的 WebView 可注入任意触摸事件。

### H-10: 调试日志在生产环境暴露敏感路径 (App)

**文件**: `app/utils/debug_trace.ts:52-59`  
**文件**: `app/hooks/useChatLogic.ts:269`

`imageUri`、`audioLocalUri` 等路径通过 `console.log` 输出，可通过 `adb logcat` 查看。

### H-11: 全局可变认证单例 (App)

**文件**: `app/components/auth.ts:1-11`

```typescript
export const auth = new userAuth("", "")
```

全局可变单例，`auth.username` 和 `auth.message_token` 可在代码库任意位置被修改，产生隐式依赖和竞态条件。

---

## Medium 级问题

### M-1: 无 CORS 配置 (Server)

**文件**: `server/server_main.py:134`

未配置 CORS 中间件。若服务器需被浏览器访问，所有跨域请求将被默认拒绝。

### M-2: Playwright 同步 API 阻塞事件循环 (Server)

**文件**: `server/src/plugins/schedule/cookie_manager.py:197-260`

使用 `playwright.sync_api` 的阻塞调用（可能耗时 30+ 秒），未包装在 `asyncio.to_thread` 中。

### M-3: SQLite 并发写入争用 (Server)

**文件**: `server/src/database/sql_database.py:169-181`

WAL 模式+`busy_timeout=5000`，并发写入时最多等待 5 秒。`autocommit=False` 进一步增加争用窗口。

### M-4: 无输入长度限制 (Server + Client + App)

- **Server**: `server/src/interface/types.py` — Pydantic models 无 `max_length`
- **Client**: QTextEdit 无长度限制
- **App**: `TextInput` 无 `maxLength`

### M-5: Fire-and-Forget 异步任务无声错误 (Server)

**文件**: `server/src/pipeline/topic_replier.py:111,154,157`

多个 `asyncio.create_task()` 返回的 Task 对象未被存储或 await。未捕获的异常仅被记录然后 GC 回收。

### M-6: 全局可变单例导致不可测试 (Server)

**文件**: `server/src/interface/websocket_service.py:281-286`
**文件**: `server/src/database/vector_store.py:330-344`
**文件**: `server/src/agent/luotianyi_agent.py:609-645`

多处全局单例模式，使单元测试需要模块重载 hack。

### M-7: 多个 LLM 客户端重复初始化 (Server)

**文件**: `server/src/agent/main_chat.py:58`
**文件**: `server/src/agent/conversation_manager.py:27`

`MainChat`、`TopicExtractor`、`ConversationManager`、`VisionModule` 各自创建独立的 `LLMModule` 实例，每个都有自己的线程池和 OpenAI 客户端。

### M-8: N+1 文件读取 (Server)

**文件**: `server/src/agent/luotianyi_agent.py:220-236`

遍历所有 `citywalk_*.json` 文件逐个读取解析以查找日期匹配，随报告增多性能下降。

### M-9: 权限设置文件无权限限制 (Client)

**文件**: `client/src/safety/credential.py:46`

`temp/user.json` 使用默认 Windows 权限创建，同一用户下的任何进程（包括恶意软件）都可读取。

### M-10: 调试面板在生产环境可访问 (App)

**文件**: `app/app/index.tsx:208-232`

调试面板按钮无条件渲染，未用 `__DEV__` 守卫。显示内部状态（WebSocket 事件、文件路径、用户 ID）。

### M-11: 发送循环停止/重置竞态条件 (App)

**文件**: `app/utils/message_processor.ts:386-394`

`startSendLoop()` 将 `stopRequested` 重置为 `false`，已停止的处理器可能因新消息被意外重启。

### M-12: Orphan 文件及重复声明 (App)

**文件**: `app/public/live2d/live2d.html:81,131` — `const canvas` 重复声明  
**文件**: `app/public/live2d/live2d copy.html` — 未清理的调试副本

---

## Low 级问题

### L-1: `is_debug: true` 提交到 VCS (Server)

**文件**: `server/config/config.json:1`

### L-2: 请求模型类无 `max_length` 验证 (Server)

### L-3: 无内容安全策略 CSP (App)

### L-4: `Math.random()` 用于 ID 生成 (App)

### L-5: Live2D HTML 中 `console.log` 生产环境残留 (App)

### L-6: `winsound` 模块级导入导致非 Windows 崩溃 (Client)

**文件**: `client/src/utils/audio_processor.py:3`

### L-7: 相对路径硬编码 (Client)

### L-8: SVG 包含在图片选择过滤器 (Client)

---

## 架构设计评审

### 亮点

- **分离关注点**: 三层架构清晰 — 服务端/PC客户端/移动端
- **Pipeline 模式**: ChatStream 的 `ingress → planner → replier → speaker` 流水线设计良好
- **消息驱动**: WebSocket + asyncio.Queue 的解耦方式合理
- **服务端 TTS 串行化**: GlobalSpeakingWorker 的串行设计防止 GPU OOM

### 主要问题

1. **全局可变单例泛滥**: `_websocket_service`, `agent`, `vector_store`, `chat_stream_manager` 全为模块级单例，导致：
   - 无法单元测试（需要模块重载）
   - 隐式初始化依赖顺序
   - import 时产生副作用

2. **三种 SQL Session 管理模式并存**:
   - FastAPI `Depends(get_sql_db)` — `server_main.py`
   - 直接工厂调用: `get_sql_session()` — `websocket_service.py`
   - `_runtime_hub.open_sql_session()` — `luotianyi_agent.py`
   
   导致会话生命周期不清晰，潜在连接泄露。

3. **Fire-and-forget 异步任务泛滥**: `asyncio.create_task()` 返回的 Task 对象从不被存储。异常在不可预测的时间点静默丢失。

4. **客户端线程模型混乱**: 后台 daemon 线程直接操作 OpenGL 资源和 Qt 组件。应全部通过 Qt Signal/Slot 机制桥接到 UI 线程。

---

## 数据流评审

### 用户输入到输出的完整路径

```
UI 输入 (QTextEdit / TextInput)
  → MessageProcessor 队列（线程安全队列）
    → WsTransport.send() (WebSocket)
      → Server WebSocket accept (server_main.py)
        → convert_to_chat_input_event() (websocket_service.py)
          → ChatStream.feed_event() (ingress_queue)
            → ingress_worker_loop()
              → ingress_message() (预处理: 图片→VLM, 歌曲实体, 日期)
              → agent.add_conversation() (SQLite 落库)
              → topic_planner.feed_unread_message()
                → message_processor() (提取 Topic)
                  → topic_replier.add_topic()
                    → _reply_one_topic()
                      → 并行搜索: 记忆 + 知识 + 唱歌
                      → LLM 调用生成回复
                      → TTS 生成 + WebSocket 发送
```

### 数据流中的安全风险

| 环节 | 风险 | 级别 |
|------|------|------|
| UI 输入 → MessageProcessor | 无长度限制，可发送超大数据 | Medium |
| WebSocket 传输 | 无 TLS 时纯文本传输 | Critical |
| 服务端消息解析 | 类型检查不严格 | Low |
| 会话存储 (SQLite) | 密码明文 | Critical |
| LLM 调用 | 用户输入直达 LLM，无过滤 | Medium |
| 回复落盘 (TTS WAV) | UUID 未校验可路径穿越 | Critical |

---

## 整改建议优先级

### 立即修复 (P0)

| # | 问题 | 模块 | 预估工日 |
|---|------|------|---------|
| 1 | 密码加密存储 (`bcrypt`/`argon2`) | Server | 0.5 |
| 2 | 替换硬编码 JWT 密钥为 env 变量 | Server | 0.3 |
| 3 | 凭据迁移至系统密钥链 | Client | 1 |
| 4 | 令牌移出 URL 参数 | Client + App | 1 |
| 5 | WebView 安全加固 | App | 0.5 |
| 6 | UUID 路径穿越修复 | Client | 0.5 |

### 高优先级 (P1)

| # | 问题 | 模块 | 预估工日 |
|---|------|------|---------|
| 7 | 认证端点添加频率限制 | Server | 1 |
| 8 | `eval()` 调用移除 | Server | 1 |
| 9 | 敏感日志清理 + PII Filter | Server | 1 |
| 10 | OpenGL 线程安全修复 | Client | 1 |
| 11 | 输入长度限制全链路 | All | 0.5 |
| 12 | 凭据存储迁移至 `expo-secure-store` | App | 0.5 |

### 中优先级 (P2)

| # | 问题 | 模块 | 预估工日 |
|---|------|------|---------|
| 13 | 全局单例重构为依赖注入 | Server | 3 |
| 14 | Fire-and-forget 任务加入错误追踪 | Server | 1 |
| 15 | Playwright 异步化 | Server | 1 |
| 16 | MSAF eval 替代 | Server | 2 |
| 17 | LLM 客户端共享 | Server | 1 |
| 18 | 调试面板 `__DEV__` 守卫 | App | 0.3 |
| 19 | CSP 添加 | App | 0.3 |

### 低优先级 (P3)

| # | 问题 | 预估工日 |
|---|------|---------|
| 20 | Debug config from VCS | 0.3 |
| 21 | Orphan files cleanup | 0.3 |
| 22 | CORS middleware | 0.3 |
| 23 | SVG filter fix | 0.2 |
| 24 | N+1 diary query | 0.5 |

**总计预估工日**: ~18 天

---

## 附录: 常见攻击面分析

| 攻击向量 | 是否可行 | 现有防护 | 剩余风险 |
|---------|---------|---------|---------|
| 密码暴力破解 | ✅ 可行 | 无 | 高 |
| JWT 伪造 | ✅ 可行（密钥硬编码） | 无 | 高 |
| SQL 注入 | ❌ (ORM 绑定变量) | SQLAlchemy | 无 |
| XSS (WebView) | ✅ 可行（无 CSP） | 无 | 高 |
| 路径穿越 (客户端) | ✅ 可行 | 无 | 高 |
| MITM (未验证 TLS) | ✅ 可行 | `verify_ssl: false` | 高 |
| CSRF | ✅ 可行（无 token） | 无 | 中 |
| 命令注入 | ❌ (参数为列表) | subprocess 列表传参 | 低 |
| SSRF (amap) | ✅ 可行（无 URL 白名单） | 无 | 中 |
| 反序列化攻击 | ❌ (仅 JSON) | 无 eval | 低 |

---

*审查工具: opencode code review agents | 审查人: AI Assistant | 报告生成日期: 2026-05-25*
