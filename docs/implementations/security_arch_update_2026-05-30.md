# 安全与架构整改更新报告 (2026-05-30)

## 范围

- Server: 认证安全、JWT 密钥、Playwright 异步化、SQLite 写入争用、LLM 客户端复用
- Client: TLS 强制校验、凭据加密存储、令牌头部传输、UUID 白名单校验、UI 线程模型更新
- App: SecureStore 令牌存储、令牌头部传输、WebView 资源访问收敛

## 已完成问题

- CR1, CR2, CR3, CR4, CR5, CR6, CR7, CR8, CR9
- H1, H2
- M2, M3, M7

## 变更摘要

### Server

- 密码存储从明文改为 bcrypt 哈希，登录时自动迁移旧密码
- JWT 签名密钥改为环境变量 `JWT_SECRET`，缺失时拒绝启动
- 认证端点加入基础限流（内存级，按 IP+用户名）
- Playwright Cookie 刷新改为异步 API，避免阻塞事件循环
- SQLite 连接开启更长 busy_timeout 与 AUTOCOMMIT 以降低写入争用
- LLM API 客户端按配置缓存复用，减少重复初始化

### Client (PC)

- 强制启用 TLS 校验，移除关闭校验的路径
- 自动登录 token 使用 DPAPI 加密落盘
- 历史记录改用 `Authorization: Bearer` 头传输
- 服务器返回 UUID 进入文件路径前进行白名单校验
- Live2D 表情更新通过 Qt 信号回到 UI 线程执行

### App (Mobile)

- 自动登录 token 改存 `expo-secure-store` 并兼容迁移
- 历史/好感度查询改用 `Authorization: Bearer` 头
- WebView 资源加载收敛到 Live2D 资源路径，保留 file 访问但禁止 file -> http(s)

## 详细说明

### CR1 - 密码哈希

- 注册、重置密码使用 bcrypt 哈希
- 登录验证兼容旧明文，成功后自动升级为 bcrypt

### CR2 - JWT 密钥

- 使用 `JWT_SECRET` 环境变量
- 未配置时抛错阻止启动

### CR3 - 客户端凭据加密

- Windows 平台使用 DPAPI 加密 `login_token`
- 读取时同时兼容旧明文字段

### CR4 - TLS 校验

- 统一强制 `verify_ssl=True`
- 禁止 WebSocket/HTTP 走不验证通道

### CR5 - 令牌不再走 URL

- Client/App 请求历史、好感度改为 `Authorization: Bearer <token>`
- Server `/history` 允许从 Header 读取 token

### CR6 - UUID 路径穿越

- 客户端对服务器返回的 UUID 做 `[A-Za-z0-9_-]` 白名单校验

### CR7 - Live2D UI 线程

- 表情更新从后台线程移至 UI 线程信号处理

### CR8 - WebView 权限收敛

- 仅允许 Live2D 资源路径
- 保留 file 访问以读取本地 JSON/模型资源
- 禁止 file -> http(s)

### CR9 - App 令牌安全存储

- 自动登录 token 改存 `expo-secure-store`
- 启动时迁移旧 AsyncStorage 数据

### H1 - 认证限流

- `/auth/login` `/auth/register` `/auth/auto_login` `/auth/reset_account` 添加内存限流
- 以 IP + username 作为 key

### H2 - 用户枚举

- 注册失败统一返回文案，日志记录具体原因

### M2 - Playwright 异步化

- Cookie 刷新改为 `check_and_refresh_cookie_async()`
- 同步入口在非事件循环环境使用 `asyncio.run()`

### M3 - SQLite 写入争用

- 连接层面加大 busy_timeout 并使用 AUTOCOMMIT

### M7 - LLM 客户端复用

- LLM API 客户端基于配置缓存复用
- 如需禁用缓存，可在配置中设置 `cache_client: false`

## 迁移与兼容性

- 旧明文密码在首次成功登录后自动升级为 bcrypt
- 客户端旧 `temp/user.json` 明文字段仍可读取，后续保存会写入加密字段
- App 旧 AsyncStorage token 在启动时迁移到 SecureStore

## 配置与运行要求

- Server 必须设置环境变量 `JWT_SECRET`
- App 依赖新增 `expo-secure-store`

## 验证建议

- 注册 / 登录 / 自动登录 / 重置密码
- 历史记录和好感度接口是否通过 Authorization 头工作
- WebView Live2D 资源加载是否正常
- Cookie 刷新任务不阻塞事件循环
- 多并发写入场景下 SQLite 不易报 busy
