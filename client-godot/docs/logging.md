# 客户端日志规范

本文是 Godot 客户端日志的单一说明。实现入口是 `src/storage/log_schema.gd` 与 `src/storage/client_log.gd`；旧的历史架构文档不再作为日志契约依据。

## 公共字段

每条 JSONL 条目都带以下字段：

`time`、`elapsed_ms`、`run_id`、`seq`、`category`、`level`、`module`、`event`、`message`、`origin`。

- `time`：UTC ISO 字符串，带 `Z`。
- `elapsed_ms`：相对本次启动的单调耗时。
- `run_id`：本次启动标识；同一 run 的 JSONL 与元数据文件名一致。
- `seq`：本次 run 内单调递增序号，用于稳定排序。
- `category`：九类日志之一。
- `level`：`DEBUG`、`INFO`、`WARN`、`ERROR`。
- `module`：`app/account/network/message/audio/cache/history/settings/dynamics/engine`。
- `event`：`<category>_<domain>_<action>` 形式的事件名。
- `message`：面向用户的中文说明；原始错误文本放在 `detail`。
- `origin`：故障归属，`client`（客户端/本机）、`network`（DNS/TCP/TLS/超时/断线）、`server`（服务端 HTTP/WS）、`upstream`（TTS/LLM 等上游服务）、`none`（成功或无故障）、`unknown`。调用方未显式给出时按事件、错误码和 HTTP 状态推断。

## 九类日志

| 分类标识 | 中文名 | 必填字段（公共字段之外） | 触发场景 | 记录内容 | 主要用途 |
|---|---|---|---|---|---|
| `error` | 错误 | `code`、`detail`、`stack`、`origin` | 引擎/脚本/着色器错误、本地异常、解码/存储/缓存/头像失败 | 错误码、脱敏原文、最多 12 帧堆栈、阶段、故障归属、`trace_id` | 定位与修复、崩溃分诊 |
| `warning` | 警告 | `code`、`detail`、`origin` | 设置保存失败、音频欠载、重放被打断、引擎警告、字段缺失 | 警告码、原文、阶段、故障归属、`trace_id` | 提前发现潜在问题 |
| `info` | 信息 | `phase` 或 `code`，加业务指标 | 消息入队/投递/回复、音频接收/播放、缓存提交/清理、Python 媒体扫描/导入、历史对账、头像应用、设置模型/偏好 | 关键节点、计数、耗时、`reply_id` | 掌握运行与业务流 |
| `debug` | 调试 | `data` | `--debug-log` 下的函数参数/变量、音频分片格式/解码、WS/状态机细节 | 扁平键值（≤16 键，值≤256 字符，敏感键丢弃） | 复现、调试、优化 |
| `access` | 访问 | `channel`、`action`、`route`、`outcome`、`duration_ms`、`trace_id` | HTTP 请求、WS 连接/认证/控制消息、音频分片 30 秒聚合、UI 窗口/页面打开关闭 | 方法/动作、归一化路由、状态码/关闭码、耗时、字节数、结果、故障归属 | 用户行为分析、请求性能 |
| `security` | 安全 | `action`、`outcome`、`reason_code`、`subject`、`trace_id` | 登录/自动登录/注册/重置/登出、token 读写/遗忘、DPAPI/加密组件检查、WS 认证拒绝、DB scope 守卫 | 动作、结果、原因码、账号+服务器哈希、通道 | 安全审计与追踪 |
| `performance` | 性能 | `operation`、`outcome`、`duration_ms`、`trace_id` | 启动阶段、SQLite 作业、图片/音频解码、HTTP/WS 汇总、30 秒资源采样 | 耗时、字节/帧/条数、队列深度、内存/对象/绘制调用/FPS | 瓶颈分析与优化 |
| `transaction` | 事务 | `transaction_id`、`scope`、`operation`、`phase`、`outcome`、`duration_ms`、`trace_id` | SQLite BEGIN/COMMIT/ROLLBACK、文件原子写（音频/图片导入、缓存、凭证） | 事务 ID、范围、操作、阶段、耗时、可选影响行数 | 一致性与完整性 |
| `runtime` | 运行 | `phase`、`reason`、`uptime_ms`、`pid` | 启动/关闭、启动阶段、窗口打开/关闭、账号/连接/历史/动态状态变化、上次未正常结束 | 生命周期阶段、原因、运行时长、进程号、`trace_id` | 生命周期追踪 |

默认级别：`error→ERROR`、`warning→WARN`、`info→INFO`、`debug→DEBUG`；`access/security/performance/transaction/runtime` 默认 `INFO`，`outcome=failure` 升为 `ERROR`，`denied/cancelled` 升为 `WARN`，事务失败阶段升为 `ERROR`，异常退出升为 `WARN`。调用方仍可显式覆盖 `level`。

## API

保留旧入口：

```gdscript
logger.record("runtime_app_started", {"phase":"starting"})
```

新增统一入口与九类快捷方法：

```gdscript
logger.record_as("access", "access_http", {...})
logger.log_error("error_system", {...})
logger.log_warning("warning_settings_save", {...})
logger.log_info("info_message_queued", {...})
logger.log_debug("debug_state", {"data":{"state":"ready"}})
logger.log_access("access_http", {...})
logger.log_security("security_auth", {...})
logger.log_performance("performance_sample", {...})
logger.log_transaction("transaction_file", {...})
logger.log_runtime("runtime_app_started", {...})
```

工作线程使用 `record_threadsafe(category, event, fields)` 入队；主线程在 `Application._process`、`read_entries()` 前和 `finish()` 前调用 `drain()`。

必填字段缺失时会补安全默认值，并在条目中写 `schema_missing`；`get_stats()` 可读取 `schema_warnings`、`dropped_debug`、`write_failures` 与 `by_origin` 等计数。

故障归属判定：HTTP `status=0` 为 `network`，4xx/5xx 为 `server`，成功为 `none`；本地缓存/存储/图片/头像/配置/解码错误为 `client`；`TIMEOUT/NETWORK_ERROR/断线/TLS` 为 `network`；`AUTH_REJECTED/HTTP_ERROR/SERVER_ERROR/INVALID_RESPONSE/历史失败` 为 `server`；`REMOTE_AUDIO_ERROR/TTS_*/MODEL_ERROR` 为 `upstream`。
旧归档没有 `origin` 时，读取与导出会按同样规则临时推断，不修改原 JSONL。

## 事件与旧归档

新代码使用 `<category>_<domain>_<action>` 事件名。旧归档中的事件名通过 `LEGACY_ALIASES` 解析出分类与中文说明，例如 `client_started → runtime_app_started`、`reply_received → info_reply_received`、`system_error → error_system`。旧 JSONL 不需要迁移。

## 隐私与脱敏

- 允许保留错误原文、异常栈和失败响应摘要。
- 永不写入 token、密码、Authorization、Cookie、密钥、聊天/动态正文、音频 Base64、请求头。
- `detail` 最多 1024 字符；`stack` 最多 12 帧，路径归一化为 `res://`、`user://` 或 `<abs>/文件名`。
- `data` 只接受扁平标量，最多 16 键、字符串最多 256 字符；敏感键直接丢弃。
- `subject` 与 `reply_id` 只存 SHA-256 截断值；`route` 只保留归一化 path，不带 host/query。

## 保留与导出

- 单次运行默认上限：8 MiB、5 万条；保留最近 50 次 run，保护仍在运行的实例。
- 每次启动一个 `<run_id>.jsonl` 与 `<run_id>.json`。
- 导出 ZIP 固定包含 `events.jsonl`、`readable.txt`、`environment.json`；`environment.json` 增加 `schema_version`、`counts_by_category`、`counts_by_origin`、`debug_enabled` 与 `retention`。
- 导出不覆盖已存在文件；失败删除半成品 ZIP。

## 检索示例

```bash
# 只看错误
jq -c 'select(.category=="error")' events.jsonl
# 按 trace_id 串起一次请求
jq -c 'select(.trace_id=="req_ab12cd34ef56")' events.jsonl
# 只看服务端问题
jq -c 'select(.origin=="server")' events.jsonl
# 区分客户端与网络链路问题
jq -c 'select(.origin=="client" or .origin=="network")' events.jsonl
# 看事务失败
jq -c 'select(.category=="transaction" and .outcome=="failure")' events.jsonl
# 看最近一次启动的性能采样
jq -c 'select(.event=="performance_sample")' events.jsonl | tail -5
```

## 调试开关

调试日志默认关闭。启动参数加 `--debug-log`，或在测试中调用 `logger.set_debug_enabled(true)` 后，`debug_*` 事件才会落盘。桌面端每 30 秒采样一次资源指标；headless 测试不启动定时器。
