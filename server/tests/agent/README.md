# Agent 门面测试

当前测试通过公开的 `handle_stimulus`、`realize_action_plan` 和运行时生命周期观察行为。
每次调用独立处理；失败停止后续交付，保留已完成结果，报告不要求调用者重试。

- `test_facade_contract.py`：入口类型、角色、取消及准入检查。
- `test_handler_registration.py`、`test_handler_dispatch.py`：路由、处理报告、顺序执行、部分效果及错误日志。
- `test_facade_inflight_shutdown.py`：关闭等待、取消传播和处理器清理。
- `test_request_isolation.py`、`test_execution_isolation.py`：不同请求、执行和角色相互隔离。
- `test_plan_emission.py`、`test_plan_delivery_failure.py`、`test_plan_logging.py`：计划交付顺序、失败停止及日志内容隔离。
- `test_output_sequences.py`、`test_output_delivery_failure.py`：输出身份和序号、失败停止、取消、已完成效果及日志。

已移除持久化账本、重复调用合并、历史结果重放、进程重启恢复、数据库故障和旧数据库升级测试。
混合场景保留首次调用中的顺序、失败、取消和效果断言，移除后续重投断言。
原来要求 `retryable=True` 的场景改为 `False`。旧 SQL 样例和持久去重接收器已删除。

运行命令（工作目录 `server`）：

```powershell
& 'D:/Anaconda/envs/lty/python.exe' -X utf8 -m pytest tests/agent tests/agent_runtime -q --tb=short
```
