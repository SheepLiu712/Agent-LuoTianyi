# 通话重构 CR-5 实施证据

> 基线：CR-4 checkpoint `68c086d9a4478af0b9f47390aa52870c489b52b8`
>
> 状态：隔离分支候选实现，等待 Oracle Gate C1；不代表人类验收、合入或发布

## 一致性结论

本工单未新增持久化门面。现有三组窄契约已经分别隐藏其技术原子性：

- `call_sessions`：冻结 settlement digest、CAS summary/maintenance状态及最终 progress
- `conversation_service`：稳定 UUID 的 Call Conversation 唯一写入与winner读取
- `call_maintenance_batches`：范围唯一 frozen batch、digest冲突与completed状态

跨存储先后顺序、正常/崩溃恢复策略及 Agent 调用仍属于 `stage/call_settlement`。把上述仓储打包只会原样转发并把恢复策略下沉 infrastructure，没有形成更深操作，因此不封装新门面。

## 真实故障与进程重启证据

新增 `test_process_restart_repairs_partial_summary_and_maintenance_exactly_once` 使用正式 `support.call_network_success_server`、真实 `ServerRuntime.initialize`、`StageManager.initialize`、`StaleCallRecoveryService` 和文件 SQLite。每个 server 都是独立 Python 进程，均正常 stop、exit code 0。测试通过正式仓储接口构造与生产写序等价的 durable 中间状态，再正常退出进程；它不是在 production settlement 写入后强杀进程，也不模拟 OS 断电。

### A. Conversation 已写、ledger summary 未提交

- 进程1写入稳定 call Conversation UUID和正常概要，ledger保持 `summary_status=pending`
- 进程2启动恢复定位同一 winner，验证完整identity/content后只修复ledger状态
- 进程3再次启动不重复Conversation，UUID与计数保持一致

### B. Maintenance projection/batch完成、ledger progress未提交

- 进程1写入 `status=completed` 的空candidate持久batch，并通过SQL预置与batch一致的确定性profile；ledger保持 `maintenance_status=pending`、progress=0
- 进程2由正式projection verifier确认batch结果后修复 `maintenance_status=succeeded`、progress=1
- 进程3再次启动时batch计数、profile和progress不变，不重复应用
- 外部模型、实时语音、TTS、vector backend使用确定性离线端口；SQLite账本、batch、用户profile及恢复路径为正式实现。该e2e单独不证明非空memory/vector/link的实际应用或extract调用次数；非空canonical memory/vector/link由 `test_call_maintenance_projection.py` 的正式projection verifier组件测试分层覆盖

### C. 冲突fail-closed

- 既有独立进程测试持久化同稳定identity但不同终态/summary内容
- 下一进程初始化失败，Conversation不被覆盖，ledger维持pending；等待200ms后再次读取无late write

### D. 二次独立启动唯一性

- 新partial-settlement测试和既有stale-call测试均执行两次独立重启
- Conversation/batch计数、conversation_id、maintenance progress和profile保持稳定

## 发现并修复的最小根因

原 `SqlCallSessionRepository.list_recovery_pending()` 只扫描 `end_reason=system_failure` 的 ENDED connected账本，导致正常 `user_hangup` 在Conversation/batch已经写入但ledger CAS前崩溃后永远不会被启动恢复扫描。新增进程测试首先红灯为 `summary_status=pending`。

修复仅扩展正常终态恢复候选：`ENDED + CONNECTED` 且 `summary_status=PENDING` 或 `maintenance_status=PENDING`。正常结束的稳定 `summary_status=FAILED` / `maintenance_status=FAILED` 不重复扫描；`SYSTEM_FAILURE` 保留基线较宽策略，可重新检查非成功summary或pending maintenance。未改变winner校验、digest冲突、Agent调用或恢复时序。

### Gate C1 attempt 1 remediation

新增真实SQLite候选矩阵覆盖：

| 状态 | summary | maintenance | 候选 |
| --- | --- | --- | --- |
| USER_HANGUP CONNECTED | PENDING | SUCCEEDED | 是 |
| USER_HANGUP CONNECTED | FAILED | SUCCEEDED | 否 |
| USER_HANGUP CONNECTED | SUCCEEDED | PENDING | 是 |
| USER_HANGUP CONNECTED | SUCCEEDED | FAILED | 否 |
| USER_HANGUP CONNECTED | SUCCEEDED | SUCCEEDED | 否 |
| SYSTEM_FAILURE CONNECTED | PENDING/FAILED | SUCCEEDED | 是（旧契约） |
| SYSTEM_FAILURE CONNECTED | SUCCEEDED | PENDING | 是（旧契约） |
| SYSTEM_FAILURE CONNECTED | SUCCEEDED | FAILED | 否 |
| 非CONNECTED ENDED | PENDING | PENDING | 否 |
| ENDING | 任意 | 任意 | 是（原候选） |

新增 `test_normal_failed_summary_is_stable_and_never_reentered`：正常USER_HANGUP、summary FAILED、maintenance SUCCEEDED、normal digest存在且无Conversation winner；连续两次reconcile均 `scanned=0`，ledger完整值（含timestamp）不变、Conversation计数0，且Forbidden batch/verifier端口证明未触发projection或外部backend调用。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m pytest server/tests/e2e/call/test_call_process_restart_recovery.py::test_process_restart_repairs_partial_summary_and_maintenance_exactly_once -q --tb=short
# 1 passed in 42.69s

# 本次恢复后具名重跑：readiness timeout，1 failed in 89.59s；未取得新的进程恢复绿灯

& .\.venv\Scripts\python.exe -m pytest server/tests/e2e/call/test_call_process_restart_recovery.py -q --tb=short
# 3 passed, 0 skipped in 127.51s

& .\.venv\Scripts\python.exe -m pytest server/tests/integration/persistence/test_call_recovery_candidates.py server/tests/integration/persistence/test_call_settlement_digest.py server/tests/integration/persistence/test_call_maintenance_batches.py server/tests/integration/persistence/test_call_maintenance_projection.py server/tests/integration/stage/test_stale_call_recovery.py server/tests/integration/stage/test_call_settlement_consumer.py -q --tb=short
# 34 passed, 0 skipped in 12.50s
```

以上命令分别报告，不累加为单一总数。候选矩阵与稳定失败测试的红灯是在实现修复前由对应新增断言触发，随后同一测试分别以 `11 passed` 与 `20 passed` 绿灯收敛；本轮保留绿灯命令和结果，不虚构一次命令同时包含红绿两次运行。恢复后的具名进程测试重跑因 readiness timeout 失败，不能冒用此前绿灯；日志显示前两次独立启动已正常处理并退出，第三次启动日志为空，属于测试环境启动不稳定，未形成新的恢复证据。进程测试日志只包含阶段、状态和普通测试路径，不记录token、逐轮转写或PCM；认证token不写日志。已知同timestamp CAS风险通过生产恢复的 `_next_timestamp` 至少递增1微秒规避。

## 未验证边界

- 未使用真实付费模型、实时语音供应商、生产vector服务或Android真机
- 未模拟OS在SQLite单条事务提交中的断电；SQLite事务原子性由数据库承担
- 未实现CR-6兼容清理或#324–335专项需求
- Issue #322及相关Spec仍需非作者/人类审查，不自动关闭或标记ADR Accepted
- 本轮未重复完整进程套件；具名 pending-winner 恢复测试的历史绿灯保留为既有证据，本轮重跑失败不改变源码结论，但仍需在稳定环境重新验证

## Gate C1 attempt 1 remediation 状态

本轮仅完成 Gate C1 attempt 1 的唯一阻断修复及证据校准；没有提交、推送、合并、GitHub操作或推进CR6。当前等待 Gate C1 attempt 2 独立复审，不宣称 Gate PASS。

## Gate C1 process startup 证据收口

此前当前候选具名运行曾出现两种 readiness 红灯：一次前两进程正常恢复/退出后第三进程日志为空；一次首进程日志为空且尚未生成 config/SQLite。批准 Temp 的同模块 `-X importtime` 诊断在 `19.391s` ready、stop 后 exit 0，只能说明可成功启动及 heavy import 存在明显耗时，不能证明恢复 query 缺陷或把问题笼统归为环境。

解释器来源已直接核验：

```text
sys.executable = C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\Scripts\python.exe
sys.prefix = C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv
sys.base_prefix = C:\Users\Administrator\.conda\envs\agent
pytest.__file__ = C:\Agent-LuoTianyi\.slim\worktrees\call-refactor-cr\.venv\lib\site-packages\pytest\__init__.py
pytest.__version__ = 9.0.3
```

Windows 进程镜像显示基础解释器属于正常 venv 行为；实际 `sys.executable`、prefix 与 pytest 包均来自当前 lane，不重建或安装共享环境。

为让原始失败日志在 heavy import 前即可定位，测试 harness 使用当前 `sys.executable -u -c <bootstrap>` 启动相同 `support.call_network_success_server` 模块，并设置 `PYTHONUNBUFFERED=1`。新增的持久 test-only 阶段只输出固定标签、单调耗时、PID、解释器/prefix与模块源码路径：

```text
python-entered
module-entered
imports-complete
config-built
runtime-initialized
address-published
```

阶段观测不新增诊断 endpoint，不读取环境变量值、token、summary、transcript、PCM或local variables；正式组件、30秒readiness、15秒stop及恢复时限均未改变。

当前候选具名复跑：

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  server/tests/e2e/call/test_call_process_restart_recovery.py::test_process_restart_repairs_partial_summary_and_maintenance_exactly_once `
  -q --tb=short
# 1 passed, 0 skipped in 79.07s
```

三次独立进程均使用当前 lane `sys.executable` 与当前 `server/tests/support/call_network_success_server.py`，并正常 stop、exit code 0：

| 进程 | python-entered | module-entered | imports-complete | config-built | runtime-initialized | address-published | 业务阶段 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 初始 durable fixture | 0.000s | 0.437s | 26.016s | 26.234s | 28.500s | 28.547s | seed 200，stop 200，exit 0 |
| 首次恢复 | 0.000s | 0.390s | 22.297s | 22.312s | 22.969s | 22.969s | recovery_counts 200，stop 200，exit 0 |
| 二次幂等恢复 | 0.000s | 0.297s | 16.656s | 16.672s | 17.141s | 17.156s | recovery_counts 200，stop 200，exit 0 |

初始进程 `imports-complete=26.016s`、`address-published=28.547s` 距30秒readiness仅约1.45秒，支持此前日志为空是发生在module heavy imports之前或期间的启动时延风险；本次三进程通过同时证明当前候选恢复 query、winner修复和第二次幂等恢复可完成。此前两次readiness失败历史继续保留，本次绿色不宣称启动不稳定已被环境排除。

受影响 harness smoke：

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests/e2e/call/test_call_network_success.py -q --tb=short
# 1 passed, 0 skipped in 18.49s
```

未重复完整三case进程套件或长网络。完成后没有本任务创建的 server/pytest 子进程残留。本节只闭合当前候选的具名process证据并提供失败阶段可观测性，仍等待 parent 与 Oracle 对测试改动的小审；不单独宣称 Gate PASS、合入、发布或进入CR6。
