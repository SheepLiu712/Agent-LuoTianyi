# system.observability 对外接口

## 模块职责

`server/src/system/observability` 记录模型调用、流水线耗时、日志和记忆追踪，并提供管理后台查询所需的汇总数据。它只观察运行，不改变业务结果。

## 写入接口

### `ObservabilityService`

- `span(...) -> SpanTimer`：创建一个可计时的范围；正常结束调用 `finish(...)`，异常时调用 `fail(exc)`。
- `record_llm_call(...)`：记录模型、模块、耗时、token、结果和元数据。
- `record_pipeline_span(...)`：记录流水线阶段耗时及 trace 关联。
- `record_log_event(...)`：保存结构化日志事件。
- `record_memory_trace_event(...)`：记录一次记忆检索、使用、写入或更新事件。
- `close()`：关闭本地观测数据库连接。

辅助接口：

- `new_trace_id(prefix="trace") -> str`：创建 trace ID。
- `get_trace_context() -> dict`：读取当前异步上下文中的 trace 信息。
- `record_exception_log(...)`：将日志异常桥接到观测服务。

## 查询接口

- `get_dashboard_summary(days=1)`：管理首页汇总。
- `get_llm_summary(...)`、`get_recent_llm_calls(...)`：模型调用统计和明细。
- `get_pipeline_latency_summary(days=7)`、`get_recent_pipeline_spans(...)`：流水线耗时统计和明细。
- `get_trace_summaries(days=7, limit=100)`、`get_trace_detail(trace_id)`：按一次请求查看完整链路。
- `get_memory_trace_events(...)`、`get_memory_trace_summary(days=7)`：记忆事件和统计。
- `annotate_memory_trace_event(...)`：为记忆追踪记录人工评价。
- `get_recent_logs(...)`：查询近期日志。
- `cleanup_old_records()`：按配置清理过期观测数据。

进程级兼容入口：`set_observability_service(...)`、`get_observability_service()`。

## 正常与异常行为

- 观测失败原则上不应改变聊天、数据库写入或世界任务的业务判断。
- 记录中不得保存 API 密钥、密码、完整认证 token 等秘密；用户内容应遵守项目隐私策略。
- `SpanTimer.finish()` 应只代表被测阶段真正结束；不能在异步生成器尚未消费完时提前结束。
- 查询接口读取本地 SQLite 观测数据；时间范围或 trace 不存在时返回空统计/空结果。

## 使用示例

一次 Agent 回复开始时生成 trace ID；stage、Agent、模型和记忆服务在同一 trace 下分别记录 span。管理后台随后可以看到总耗时及每个阶段，而无需让 stage 了解观测数据怎样存储。

## 应覆盖的契约场景

- 同一 trace 的流水线、模型和记忆记录能在详情接口中关联起来。
- 无数据时间范围返回空统计；观测写入失败不改变原业务返回值。
- 清理只删除保留期之外的数据，且记录中不出现配置密钥和认证 token。
