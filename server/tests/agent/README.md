# Agent 门面 RED

对应 SPEC：`docs/项目说明/项目架构与接口（spec）/接口文档/agent/facade.md`，SPEC commit `d5303223`。

## 测试目的

| 文件 | 展开用例 | 目的 |
| --- | ---: | --- |
| `test_facade_contract.py` | 21 | 两个异步业务方法、中文方法说明、包导出与内部对象隐藏；空注册失败；角色/交互/修订校验；两类预取消；拒绝时保留 pending、行动全部 NOT_STARTED、无 sink 输出；关闭后拒绝；顶层参数类型错误 |
| `../agent_runtime/test_agent_lookup.py` | 12 | 每角色缓存、新旧对象隔离、严格角色查找；保留旧注册表和可调用旧方法；关闭幂等及初始化失败回滚 |
| `../agent_runtime/test_legacy_agent_access.py` | 5 | get_agent 语义改变后，SystemRuntime.agent、get_default_agent 和旧 TopicReplier 仍使用 get_character_runtime；话题队列仍完成回复持久化、发送和反思交付 |

## 旧调用链检查

对 `server` Python 源码的 get_agent 调用搜索发现三个生产调用点：

- `src/agent_runtime/agent_runtime.py` 的 `get_default_agent()`；
- `src/system/system_runtime.py` 的 `SystemRuntime.agent`；
- `src/chat_session/chat_pipeline/topic_replier.py` 的话题 Agent 选择。

GREEN 必须统一改成从 `get_character_runtime(...).conscious` 取得旧对象。测试中的 SplitRuntime 在公开边界明确分开新门面与旧对象，避免因旧运行时暂时仍返回旧 Agent 而误判兼容通过。TopicReplier 当前只把选择的 Agent 用于非空检查，实际规划/实现仍走 runtime 代理；因此同时断言旧队列效果和不访问新 get_agent，两者缺一都会漏掉该迁移问题。覆盖默认角色、第二角色、原有未知角色回退路径；回退用例只验证取对象路径及原队列编排，不证明真实未知角色业务可以完成。

## RED 证据

工作目录 `server`：

```powershell
D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime --collect-only -q
D:/Anaconda/envs/lty/python.exe -X utf8 -m pytest tests/agent tests/agent_runtime tests/domain tests/world -q --tb=no -rN
D:/Anaconda/envs/lty/python.exe -m ruff check tests/agent tests/agent_runtime tests/agent_runtime_support.py tests/conftest.py
```

2026-09-06 收集 38 项新增测试，无跳过。合并回归为 32 failed、550 passed、2 skipped；其中新增测试 32 failed、6 passed，既有 domain/world 为 544 passed、2 skipped。Ruff 通过。

失败原因：新门面及导出未实现、运行时仍返回旧 Agent、空字符串及 falsy 非字符串角色参数回退默认角色、三个旧入口仍调用 get_agent。门面行为用例目前首先在真实运行时返回对象缺少两个方法的明确断言处失败，尚未到达报告断言；没有导入错误、语法错误或环境错误。既有通过项是回归基线，不伪造 RED。

离线装配保留真实 AgentRuntime、CharacterRegistry、AgentRegistry、CharacterRuntime、LuoTianyiAgent 和 MainChat；向量存储、LLM 服务和旧潜意识等协作者使用受控替身，角色资源写入 pytest 临时目录。不会调用真实模型、capability 或生产数据库。

本轮证明空生产注册版本的入口与兼容契约。已注册处理器的成功路由、重复注册、处理中取消、sink 拒绝后的部分结算、在途处理器关闭超时尚无测试证据；这些场景需要内部测试装配支持，不能把当前空注册拒绝测试算作覆盖。版本构造约束由现有 domain 测试覆盖。
