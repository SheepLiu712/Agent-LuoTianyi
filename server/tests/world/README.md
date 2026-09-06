# World 调度与注册回归

本目录集中保存 world 的调度注册测试及已有任务行为测试。默认执行清单位于上级 `conftest.py`。

- `test_world_clock.py`：可控超时、服务器本地每日时间、立即运行、失败隔离、同名替换、异步清理、同步任务关闭重试。
- `test_world_runtime.py`：九类真实任务构造及注册元数据、配置传递、角色展开和开关、启动节日初始化、关闭异常传播。替换任务业务初始化与时钟，不连接网络、数据库或模型。

- `test_world_task_*.py`：迁入的 citywalk、VCPedia、学歌及 QQ 凭据、B 站事件、主动提醒、过期事件清理测试，以及从混合文件提取的日记、动态测试。部分历史测试直接验证内部方法，属于现有回归资产，不表示完整业务契约已经审核。数据库测试使用内存或临时目录。
- `test_world_live.py`：保留两项真实 VCPedia/B 站探测，不加入默认执行清单。

调度测试复用并替代原 `test_world_runtime_config.py` 的两项 world 配置测试、旧事件清理文件的注册测试、`test_admin_runtime.py` 的禁用任务测试及 `test_runtime_shutdown.py` 的 WorldClock 关闭测试。混合文件中的其他模块场景仍保留。调度测试不再直接调用 `_register_clock_actions()` 或检查 `_tasks`。

从 `server` 目录运行：

```powershell
D:/Anaconda/envs/lty/python.exe -m pytest tests/world tests/domain -q
```

2026-09-06 GREEN：world 115 项通过、2 项真实探测跳过；domain 429 项通过。恢复的 89 项离线测试全部通过。日记 Fake 更新为当前 `ensure_dependencies()`，随机抽样改为受控结果；动态数据库 fixture 恢复环境变量并关闭数据库。迁移前后测试函数清单一致，无遗漏或重复副本。除关闭重试修复外，通过的场景是既有实现的回归证据，无人为制造的 RED。

关闭重试的 RED 证据为 `test_stop_reports_live_sync_work_and_can_retry`：同步 action 被阻塞，第一次关闭超时并报错；保持 action 阻塞，再次关闭却返回成功。GREEN 修复使同一任务只收到一次关闭取消请求，后续关闭继续等待；工作未结束时仍报错，释放并结束后关闭成功。该测试未改动，始终激活。

#62 的验收覆盖调度、注册、启用条件、失败隔离和关闭语义；各任务完整业务基线在对应迁移工单中核对。归档旧测试本身不代表九类任务业务已完成验收。
