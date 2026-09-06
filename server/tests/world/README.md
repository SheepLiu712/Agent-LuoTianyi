# World 调度与注册回归

本目录通过 WorldClock 的注册、启停与 action 结果，以及 WorldRuntime 的公开生命周期入口验证调度基线。默认执行清单位于上级 `conftest.py`。

- `test_world_clock.py`：可控超时、服务器本地每日时间、立即运行、失败隔离、同名替换、异步清理、同步任务关闭重试。
- `test_world_runtime.py`：九类真实任务构造及注册元数据、配置传递、角色展开和开关、启动节日初始化、关闭异常传播。替换任务业务初始化与时钟，不连接网络、数据库或模型。

复用并替代原 `test_world_runtime_config.py` 的两项 world 配置测试、`test_world_task_event_cleanup.py` 的注册测试、`test_admin_runtime.py` 的禁用任务测试及 `test_runtime_shutdown.py` 的 WorldClock 关闭测试。原文件其他场景保留。迁入后不再直接调用 `_register_clock_actions()` 或检查 `_tasks`。

从 `server` 目录运行：

```powershell
D:/Anaconda/envs/lty/python.exe -m pytest tests/world tests/domain -q
```

2026-09-06：world 25 项通过、1 项失败；domain 429 项通过。通过的场景是既有实现的回归证据，无人为制造的 RED。

失败场景 `test_stop_reports_live_sync_work_and_can_retry`：同步 action 被阻塞，第一次关闭超时并报错；保持 action 阻塞，再次关闭却返回成功。测试要求再次报告仍有工作未停止。测试最终释放并等待线程结束，避免留下后台工作。此测试保持激活，不使用 skip 或 xfail 隐藏失败；本轮未修改产品实现。
