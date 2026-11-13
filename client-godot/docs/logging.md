# 客户端日志规范

本文是 Godot 客户端日志的单一说明。实现入口是 `src/storage/log_schema.gd`、`src/storage/client_log.gd`、`src/storage/log_events.gd` 与 `src/storage/engine_log_sink.gd`；旧的历史架构文档不再作为日志契约依据。

## 公共字段

每条落盘与内存中的 JSONL 条目恒带以下公共字段：

`time`、`elapsed_ms`、`run_id`、`seq`、`category`、`level`、`module`、`event`、`message`、`origin`、`code`、`detail`。

- `time`：UTC ISO 字符串，带 `Z`。
- `elapsed_ms`：相对本次启动的单调耗时（毫秒）。
- `run_id`：本次启动标识；同一 run 的 JSONL 与元数据文件名一致。
- `seq`：本次 run 内从 0 单调递增的序号，用于稳定排序。
- `category`：四领域分类之一（`business`、`network`、`storage`、`system`）。
- `level`：严重程度（`DEBUG`、`INFO`、`WARN`、`ERROR`）。
- `module`：所属模块（`app`、`account`、`network`、`message`、`audio`、`cache`、`history`、`settings`、`dynamics`、`engine`）。
- `event`：`<subject>_<action>` 形式的事件名。
- `message`：面向用户的中文说明，来自 `EVENT_REGISTRY`（未注册事件默认为 `"客户端活动"`）。
- `origin`：故障归属（`client`、`network`、`server`、`upstream`、`none`、`unknown`）。
- `code`：规范化状态码或错误码（未传或非字符串时恒为 `""`，非空非法值回退为 `"UNKNOWN"`）。
- `detail`：脱敏后的补充说明或错误原文（未传时恒为 `""`）。

可选字段按领域或调用方传入：

- `duration_ms`：操作耗时（`network` 与 `storage` 必填，其他领域可选）。
- `trace_id`：网络请求/连接追踪 ID，**仅 `network` 分类保留**，其他分类在归一化时自动移除。
- `transaction_id`：SQLite 事务或文件原子写事务 ID（`tx_<16位hex>`），用于 `storage` 领域。
- `stack`：脱敏后的调用栈数组（最多 12 帧）。
- `data`：扁平调试或扩展键值字典（最多 16 键）。
- 指标与业务字段：`phase`、`outcome`、`channel`、`scope`、`operation`、`action`、`method`、`route`、`reason_code`、`subject`、`reply_id`、`status`、`bytes`、`frames`、`count`、`queue_depth`、`uptime_ms`、`pid` 等（白名单见 `LogSchema.METRICS` 与 `LogSchema.STRING_FIELDS`）。

## 分类与级别解耦

分类（`category`）只回答「这条日志属于哪个业务领域」，级别（`level`）只回答「有多严重」，二者正交解耦：

| 分类标识 | 中文名 | 必填字段（公共字段之外） | 触发场景 | 记录内容 | 主要用途 |
|---|---|---|---|---|---|
| `business` | 业务流 | `phase` | 客户端启停、窗口与账号状态、连接与历史同步、动态发布/评论、消息排队/投递/回复、设置与模型执行、在线语音播放与重放 | 阶段（`phase`）、状态码、哈希后的 `reply_id`/`subject`、音频与消息指标 | 追踪用户可感知的业务状态流转 |
| `network` | 网络通信 | `channel`、`route`、`outcome`、`duration_ms` | HTTP 请求与周期汇总、WebSocket 连接/收发、WebSocket 认证、WebSocket 音频分片汇总 | 通道（`http`/`ws`）、方法、脱敏路由、状态码、字节数、耗时、`trace_id` | 网络性能分析与链路排障 |
| `storage` | 存储持久化 | `scope`、`operation`、`outcome`、`duration_ms` | SQLite 读写与事务、数据作用域守卫、文件原子写、凭据读写、语音与图片缓存读写/清理/扫描 | 存储范围（`sqlite`/`file`）、操作名、结果、耗时、队列深度、`transaction_id` | 审计本地数据库与文件操作一致性 |
| `system` | 系统诊断 | 无额外必填 | 运行状态快照、UI 窗口/页面访问、错误弹窗提示、安全组件检查、启动耗时、资源采样、队列深度、引擎错误与警告 | 指标数据、堆栈、采样值、引擎重复抑制计数 | 客户端自检、性能剖析与底层异常定位 |

严重程度共四级：`DEBUG`、`INFO`、`WARN`、`ERROR`。

- **显式优先**：调用方在 `fields` 中传入合法 `level` 时直接采用。
- **默认推导**（`LogSchema.default_level`）：未显式指定或值非法时，`outcome == "failure"` 或 `phase == "error"` 为 `ERROR`；`outcome` 为 `"cancelled"` / `"denied"` 或 `phase == "warning"` 为 `WARN`；其余默认为 `INFO`。

## 事件命名与注册表

事件名统一采用 `<subject>_<action>` 命名，直接映射所属领域与默认模块，不再保留任何旧事件别名或兼容映射。`LogSchema.EVENT_REGISTRY` 当前共定义 **71 个事件**，完整列表如下：

### 业务流（`business`）

- `app_started`（`app`）：客户端启动
- `app_stopped`（`app`）：客户端正常退出
- `window_state_changed`（`app`）：窗口状态变化
- `previous_run_incomplete`（`app`）：上次运行未正常结束
- `account_lifecycle`（`account`）：账号生命周期
- `account_state`（`account`）：账户操作状态
- `connection_state`（`network`）：聊天连接状态变化
- `history_state`（`history`）：历史同步状态
- `dynamics_state`（`dynamics`）：动态读取与写入状态
- `message_queued`（`message`）：消息已进入发送队列
- `message_delivery`（`message`）：消息投递状态
- `message_reply_received`（`message`）：收到回复（`ChatSession` 按回复 UUID 去重，每条回复在收到终包或发生音频错误时只记一条；带音频错误时 `level` 为 `WARN`）
- `message_error`（`message`）：消息处理失败
- `history_reconcile`（`history`）：送达不确定后的历史对账
- `settings_models`（`settings`）：模型配置状态
- `settings_preference`（`settings`）：相处偏好操作
- `settings_save_failed`（`settings`）：设置保存失败
- `avatar_applied`（`app`）：头像应用
- `model_execution`（`settings`）：模型请求执行
- `account_auth`（`account`）：账号认证事件
- `dynamics_post_publish`（`dynamics`）：发布动态
- `dynamics_comment_created`（`dynamics`）：发表评论
- `dynamics_comment_rejected`（`dynamics`）：评论被拒绝
- `account_capability_degraded`（`account`）：扩展能力降级
- `account_capability_failed`（`account`）：扩展能力启动失败
- `audio_receive_finished`（`audio`）：音频接收结束
- `audio_playback_started`（`audio`）：开始播放在线语音
- `audio_playback_finished`（`audio`）：在线语音播放结束
- `audio_replay_started`（`audio`）：开始重放
- `audio_replay_paused`（`audio`）：重放已暂停
- `audio_replay_resumed`（`audio`）：继续重放
- `audio_replay_stopped`（`audio`）：重放已停止
- `audio_replay_finished`（`audio`）：重放结束
- `audio_replay_preempted`（`audio`）：在线语音打断本地重放
- `audio_underrun`（`audio`）：音频缓冲暂时不足
- `audio_error`（`audio`）：音频处理失败
- `audio_frames_received`（`audio`）：收到音频数据
- `audio_format_detected`（`audio`）：已识别音频格式
- `audio_decoded`（`audio`）：音频解码完成

### 网络通信（`network`）

- `network_http`（`network`）：HTTP 请求
- `network_http_summary`（`network`）：HTTP 请求汇总
- `network_ws`（`network`）：WebSocket 访问
- `network_ws_auth`（`network`）：WebSocket 认证
- `network_ws_audio_summary`（`network`）：WebSocket 音频汇总

### 存储持久化（`storage`）

- `storage_sqlite_operation`（`history`）：SQLite 操作（`SqliteWorker` 将每次作业与事务信息合并为单条记录，成功且耗时 `< 10ms` 的 `read_*` 操作自动过滤不落盘；`SqliteAccess` 在 SQL 失败时在 `detail` 中附带错误说明与前 120 字符 SQL）
- `storage_scope_guard`（`history`）：数据作用域检查
- `storage_file_write`（`app`）：文件写入
- `storage_credential`（`account`）：凭据读写
- `storage_cache_cleared`（`cache`）：已执行语音缓存清理
- `storage_cache_write_failed`（`cache`）：缓存写入失败
- `storage_media_scan`（`cache`）：扫描媒体缓存
- `storage_media_scan_failed`（`cache`）：媒体缓存目录不可用
- `storage_avatar_clear_failed`（`app`）：头像清理失败
- `storage_avatar_save_failed`（`app`）：头像保存失败
- `storage_history_image_ready`（`history`）：历史图片就绪
- `storage_history_image_failed`（`history`）：历史图片处理失败
- `storage_image_operation`（`history`）：图片处理
- `history_storage_unavailable`（`history`）：本地历史库不可用

### 系统诊断（`system`）

- `state_snapshot`（`app`）：运行状态快照
- `ui_access`（`app`）：界面访问
- `ui_error_shown`（`app`）：已通过弹窗提示用户错误
- `system_security_component`（`account`）：安全组件检查
- `system_startup`（`app`）：启动阶段耗时
- `system_resource_sample`（`app`）：资源占用采样
- `system_queue_depth`（`app`）：队列深度
- `engine_error`（`engine`）：引擎报告错误
- `engine_warning`（`engine`）：引擎报告警告
- `engine_error_repeated`（`engine`）：引擎重复错误
- `engine_warning_repeated`（`engine`）：引擎重复警告
- `log_pending_dropped`（`app`）：日志后台队列溢出丢弃（`WARN`，每次运行最多一条汇总）
- `log_limit_reached`（`app`）：日志容量达到上限（`ERROR`，每次运行最多一条诊断）

## API

`ClientLog` 只提供主线程写入、工作线程入队与批量排空三个核心写入接口；旧版单参数入口与按分类命名的快捷方法均已删除：

```gdscript
# 主线程记录
logger.record_as("business", "message_queued", {"reply_id": id, "phase": "queued", "code": "OK"})
logger.record_as("system", "state_snapshot", {"level": "DEBUG", "data": {"state": "ready"}})

# 工作线程安全入队（队列上限 MAX_PENDING = 4096；满时丢弃最旧条目并累加 dropped_pending，
# 随后 drain() 时每次运行最多写入一条 log_pending_dropped 汇总）
logger.record_threadsafe("storage", "storage_image_operation", {"scope": "file", "operation": "decode", "outcome": "success", "duration_ms": 4})

# 主线程排空后台队列（Application._process 每帧、read_entries() 读取当前启动前、finish() 关闭前调用）
logger.drain()
```

`src/storage/log_events.gd` 封装了高频场景的标准字段拼装：`LogEvents.http`（记录 `network_http`）、`LogEvents.ws`（记录 `network_ws`，支持 `detail`）、`LogEvents.ws_audio`（记录 `network_ws_audio_summary`）、`LogEvents.ui`（记录 `ui_access`）、`LogEvents.security_auth`（记录 `account_auth`，支持 `detail`）、`LogEvents.security_token`（记录 `storage_credential`）、`LogEvents.file_transaction`（记录 `storage_file_write`）。错误详情辅助函数包括：`LogEvents.http_result_name`（保留 `HTTPRequest.RESULT_*` 枚举名）、`LogEvents.request_error_detail`（保留 `error_string(error)` 与错误码）以及 `LogEvents.http_failure_detail(body, status)`（只提取服务端 JSON 中的字符串 `detail`/`message`/`error`，无可用文本时回退为 `HTTP status <n>`；结构化校验回显不会被序列化）。

当某分类的必填字段（`CATEGORY_REQUIRED`）缺失时，`LogSchema.apply_defaults` 会自动补齐默认值（`channel="app"`、`route="/unknown"`、`duration_ms=0`、`outcome="unknown"`、`scope="unknown"`、`operation="unknown"`、`phase="unknown"`），并在条目中写入以逗号分隔的 `schema_missing` 字段，同时累加 `get_stats().schema_warnings`。

## 关联 ID 与故障归属（origin）

- `trace_id`：格式为 `^[a-z]{2,12}_[a-f0-9]{8,40}$`。仅 `network` 分类保留该字段；若 `network` 条目未传或格式不合法，自动生成 `net_<16位hex>`（WebSocket 辅助方法缺省生成 `ws_<16位hex>`）。非 `network` 分类传入的 `trace_id` 会被清除。
- `transaction_id`：由 `LogSchema.new_transaction_id()` 生成 `tx_<16位hex>`，用于关联 SQLite 事务（`SqliteAccess.transaction`）与本地文件原子写入（`LogEvents.file_transaction`）。
- `origin`（故障归属）：若调用方显式传入合法 `origin` 则直接采用，否则按 `LogSchema.infer_origin` 顺序推导：
  1. `network_http*`：非 `failure` 为 `none`；`failure` 时 `status <= 0` 为 `network`，`status > 0` 为 `server`。
  2. `network_ws*`：非 `failure` / `denied` 为 `none`；失败或拒绝时错误码属于 `SERVER_CODES` 为 `server`，属于 `CLIENT_CODES` 为 `client`，其余为 `network`。
  3. `engine_*`：`detail`（转小写）含 `tls`、`ssl`、`cert`、`handshake` 时为 `network`，其余为 `client`。
  4. 错误码映射：匹配 `CLIENT_CODES` 为 `client`，匹配 `NETWORK_CODES` 为 `network`，匹配 `SERVER_CODES` 为 `server`，匹配 `UPSTREAM_CODES`（`REMOTE_AUDIO_ERROR`、`TTS_EMPTY`、`TTS_STREAM_ERROR`、`TTS_CANCELLED`、`AUDIO_TIMEOUT`、`MODEL_ERROR`）为 `upstream`。
  5. 兜底：`outcome == "failure"` 时，`network` 分类归为 `network`，其他分类归为 `client`；非失败条目归为 `none`。

## 归档与保留

- **Schema 版本**：当前 `SCHEMA_VERSION = 3`。`list_runs()` 只返回 `schema_version >= 3` 的运行记录；旧版 v2 及更早归档从运行列表中隐藏，不再读取或逐行解析，随最近 50 次保留策略自然淘汰。
- **单次容量上限**：默认单次运行最多 **8 MiB**（`DEFAULT_MAX_BYTES`）或 **50,000 条**（`DEFAULT_MAX_ENTRIES`）。首次超出任一上限时，额外写入一条 `log_limit_reached` 软诊断（`system` / `ERROR`），将元数据 `complete` 置为 `false`、保存元数据并触发一次 `write_failed(ERR_OUT_OF_MEMORY)` 信号；之后的新条目直接丢弃并累加 `dropped_limit`，不再重复同步写盘或重复告警。运行元数据与导出摘要均记录 `dropped_limit`、`dropped_pending`、`dropped_debug`。
- **运行文件与淘汰**：每次启动在 `user://logs` 下生成独立的 `<run_id>.jsonl` 与 `<run_id>.json`（元数据通过 `.json.tmp` 原子替换写入）。目录最多保留最近 **50 次**（`MAX_RUNS = 50`）运行，超出时从最旧的非活动运行开始清理，正在运行的实例受保护不删除。
- **诊断包导出**：`export_run(run_id, destination_zip)` 导出 ZIP 固定包含 `events.jsonl`、`readable.txt`、`environment.json` 三个文件。`environment.json` 仅包含白名单摘要（`release`、`engine`、`os`、`architecture`、`schema_version`、`closed`、`complete`、`debug_enabled`、`count`、`counts_by_category`、`counts_by_origin`、`dropped_limit`、`dropped_pending`、`dropped_debug`、`retention`）。目标路径已存在时返回 `ERR_ALREADY_EXISTS`，写入失败自动清理半成品文件。

## 日志窗口

日志窗口（`src/ui/log_window.gd`）提供运行选择与多维过滤：

- **下拉筛选**：支持按启动运行（Runs）、四领域分类（全部类别 / 业务流 `business` / 网络通信 `network` / 存储持久化 `storage` / 系统诊断 `system`）、级别（`DEBUG` / `INFO` / `WARN` / `ERROR`）、模块（10 个模块）和故障归属（`origin`）筛选。
- **关键词搜索**：输入框带 200ms 防抖，匹配 `event`、`message`、`detail`、`code`、`module`、`category` 及序列化后的 `data`。
- **渲染上限**：单次刷新或追加最多渲染 **1000 条**（`MAX_RENDER_ENTRIES = 1000`）匹配记录。超出后停止向 `RichTextLabel` 追加，并在底部状态栏提示 `"当前仅显示前 1000 条匹配记录。"`；界面筛选与渲染截断只影响显示，导出始终包含所选启动的全部记录。
- **丢弃可见性**：底部状态栏同时显示本次启动（或所选历史运行）的 `dropped_limit`、`dropped_pending`、`dropped_debug` 计数；容量与后台队列丢弃还会各自留下一次诊断事件，避免日志缺失被静默忽略。

## 引擎日志频控

`EngineLogSink`（`src/storage/engine_log_sink.gd`）挂载到 Godot 引擎 `Logger`，对高频引擎报错与警告执行 **1 秒窗口频控**（`WINDOW_MS = 1000`）：

- 按 `file:line:code:error_type` 组成聚合键。
- 同一键在 1000ms 窗口内首次出现时，立即记录 `engine_error`（`ERROR`）或 `engine_warning`（`WARN`），`count = 1`。
- 同一窗口内后续到达的相同键不再逐条落盘，仅累加窗口内的 `suppressed` 计数。
- 窗口到期后（主线程每帧调用 `flush()`，或下一次任意引擎日志写入时），若 `suppressed > 0`，输出一条汇总事件 `engine_error_repeated` 或 `engine_warning_repeated`，其中 `count` 为被抑制的重复次数，`detail` 为 `"1 秒内重复 <count> 次；首条：<detail>"`，`data` 为 `{"window_ms": 1000}`。

## 隐私与脱敏

- 允许保留脱敏后的错误原文、脚本调用栈和服务端纯文本错误说明（`LogEvents.http_failure_detail` 只提取 JSON 中的字符串 `detail`/`message`/`error`，拒绝序列化结构化校验回显）。
- **错误详情透传**：HTTP 4xx/5xx 优先保留服务端文本说明；HTTP 传输失败保留 `RESULT_*` 枚举名与 `error_string`；WebSocket 断开保留 close code 与 close reason；SQLite 回滚失败保留原始错误码/详情并追加回滚失败原因；音频解码、播放、超时与远端 TTS 失败保留具体 `detail`。头像保存失败只由 `AvatarStore` 记录一次，`AvatarProfile` 仅在成功应用或本地图片读取失败时记录。
- 永不写入 token、密码、Authorization、Cookie、密钥、聊天/动态正文、音频 Base64 或请求头；文本中的 `Bearer <token>`、敏感键值对、80 字符以上的 Base64 串与 Windows 盘符绝对路径会被正则替换为掩码（`***`、`[redacted-base64]`、`<abs>`）。
- `detail` 最多 **1024** 字符（普通字符串字段最多 128 字符）；`stack` 最多 **12** 帧，单帧最多 240 字符，源码路径归一化为 `res://`、`user://` 或 `<abs>/文件名`。
- `data` 只接受扁平标量（`bool`、`int`、有限 `float`、`String`），最多 **16** 键、字符串值最多 **256** 字符；键名含 `SUBJECT_SECRET_KEYS`（如 `token`、`password`、`secret`、`key`、`body`、`text`、`audio`、`message` 等）直接丢弃。
- `subject`（`[server, username]` JSON）与 `reply_id` 只存 SHA-256 前 **12** 位十六进制截断值；`route` 剥离 scheme、host 与 query，只保留归一化路径（如 `/dynamics/*`、`/auth/login`）。

## 检索示例

```bash
# 按领域查看网络通信或存储持久化日志
jq -c 'select(.category=="network")' events.jsonl
jq -c 'select(.category=="storage" and .outcome=="failure")' events.jsonl
# 按级别只看错误或警告
jq -c 'select(.level=="ERROR" or .level=="WARN")' events.jsonl
# 按事件名查看收到的回复或 SQLite 操作
jq -c 'select(.event=="message_reply_received")' events.jsonl
jq -c 'select(.event=="storage_sqlite_operation")' events.jsonl
# 按 trace_id 串起一次网络请求
jq -c 'select(.trace_id=="net_ab12cd34ef567890")' events.jsonl
# 按故障归属区分服务端、上游与网络链路问题
jq -c 'select(.origin=="server")' events.jsonl
jq -c 'select(.origin=="upstream" or .origin=="network")' events.jsonl
```

## 调试开关

调试日志默认关闭。启动参数传入 `--debug-log`，或在代码中调用 `logger.set_debug_enabled(true)` 后，显式指定 `level="DEBUG"` 的条目才会落盘并进入内存列表；未开启时仅屏蔽 `level=="DEBUG"` 的条目（计入 `dropped_debug`），不影响四个领域下 `INFO`、`WARN`、`ERROR` 级别的正常记录。桌面端每 30 秒采样一次 `system_resource_sample`；headless 测试不启动定时器。
