# AI 决策记录

## 2026-11-17 #410 单一建立 deadline 的最小传递候选

**待定问题**：Manager 已有唯一通话建立截止时间，但 Qwen 的 connect/session 独立限时与 websockets 缺省 10 秒仍可能提前终止管理员给定的较长总窗口。需要在不重写生命周期所有权、不混入 #411 的前提下传递剩余时间。

**背景约束**：需求已由 [维护者评论](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/410#issuecomment-6910783940) 锁定：仅 `stage_manager.call_setup_timeout` 可配置；登记时固定唯一 deadline，连接/ready/ringing 共用；明确错误立即失败；Fun-ASR 诊断脚本独立限时。基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`，Python 3.10.21、websockets 16.1.1。D2通过后lead已放行provider预算核心与显式caller；不改Manager/用户配置/密钥，不提交/推送/GitHub。

**调研参考**：通过 Context7 核对 [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) 与 [16.0 官方文档](https://github.com/python-websockets/websockets/blob/16.0/docs/reference/asyncio/client.md)：单次 await、显式 `open_timeout`、None 可禁限时、iterator 才自动重连；[Python3.10 asyncio.wait_for](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait_for) 超时取消并等待清理，总返回可超过 timeout；[asyncio.wait](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait) 不自动取消 pending。借鉴既有 absolute deadline+阶段 remaining，不引入3.11才有的timeout上下文。

**候选方案**
1. **余额回调沿现有open接缝传递**：CallStage 由现有原 deadline 与 monotonic 计算 `remaining_setup_time()`，Agent/Factory 转交；provider 每阶段重算，仅初始化期间使用。不加配置/测试专属clock。
2. **原deadline + clock双参数**：三层均传 deadline 与 clock，类型更显式，但接缝需共同理解时钟域，参数更多且容易与已有注入不同步。
3. **删除全部内层限时，仅外层取消**：改动少，但不能表达明确的阶段余额，standalone 调用易变无界，诊断所有权容易遗漏。

**选择**：D2设计gate attempt1/3已通过，lead已放行候选1的provider核心实施，不commit/push；UI/旧键/诊断为后续单元。窄核补充明确选择同步 `on_session_created` 早交Stage owner，不采用失败异常携活handle候选。完整方案及单owner表见 [设计稿](<docs/specs/call-setup-deadline-plan.md>)。

**选择理由**：复用唯一权威 clock，三个接缝只学习一个小 Interface；provider 不查 Stage、不存当前会话状态，外层 `_await_setup / _dispose_late_setup` 仍拥有任务/迟到资源。显式 `open_timeout=remaining` 不受库缺省10秒影响；ready重新取余额而非续期。

**未选原因**
- 候选2：重复时钟约定与参数传递，不比现有 Stage 的权威余额提供更多实际能力。
- 候选3：虽能依赖外层约束，但独立 Factory/诊断的无界风险和阶段语义不够清楚。

**其他具体取舍**：旧connect/session JSON键暂兼容但生产不消费、不让旧非法值阻断，不启动时改写用户配置；UI仅新总预算叶子并保留#435面板局部草稿；Fun-ASR脚本分别持有connect/ready参数，不借用生产Manager。#411既有安全释放结果由另一lane负责，设计中只衔接不修改。

**验证方式**：lead已确认 Manager公开接入→真实Agent/providerfactory 接缝，仅connector/socket、空存储端口与时间受控。已运行 [首个参数化10/30行为测试](<server/tests/integration/stage/test_call_setup_deadline.py>)，job `pwsh-7b6420a064f44074` 已收集：1 failed, 1 passed, 1 warning in0.61s。10秒真实终态/账本SETUP_TIMEOUT对照通过；30秒在10.25虚拟秒因旧ready限时已经进入终止，精确业务断言失败，不是新参数TypeError。首跑清理夹具曾误调用Agent.stop，已修正，仅干净复跑计证据。Ruff/Black通过；pydub缺ffmpeg为环境warning，本测试不做音频。尚未覆盖库真实connect默认、4秒鉴权、控制台/诊断；后续各取最少必要证据。生产零改动，设计gate前不进入绿灯，完整CI由ci-verifier统一调度。

**风险与回滚**：接缝参数遗漏、共享配置迁移遗漏独立诊断、取消清理覆盖原错误是主要风险。回退本单元代码与测试，不删配置/密钥/数据库；保持Manager既有键与默认兼容、旧键不删除。不得为准时返回先释放仍被旧任务使用的资源，也不为凑满预算重试明确失败。

**D2单owner落实**：remaining先检查再创建；Factory首await前同步on_session_created交Stage PREPARING slot，callback拒绝必须在赋slot前完成校验，赋值后不抛；重复发布同handle为幂等，异handle拒绝。交后Factory成功/失败/cancel均不close；Stage原provider late-cleanup lambda移除但cancel/join保持，return必须is已持handle。Stage唯一close task成功清slot、失败保留slot/失败task并_resource_error；多次清理不再close，资源不安全时Manager仍拒绝释放。取消日志读remaining独立小try捕TimeoutError/CancelledError，不改原异常。普通auth即时传播Stage锁SYSTEM_FAILURE，不因慢close跨deadline改SETUP_TIMEOUT。未加窄失败异常handle、通用owner/clock或#411字段。

**实施阶段证据**：核心首红转2 passed/.22s；既有四文件73 passed/5.88s（会话/prompt/handoff/公开Manager）；六场景门控6 passed/.73s，含auth+慢关/关失败、connect15+blocked update send、取消抑制late关闭一次。测试初稿cause层数/close计数时机错误已收敛，不把夹具失败算产品红灯。4生产文件Ruff/Black、diff-check通过；未改的既有test_call_omni全文件仍有基线格式差异，新增helper按Black，不夹带格式清理。最终冻结检查与原输出归档单独提供，未运行真实供应商/全CI。UI、旧键验证兼容、诊断在下单元；当前不commit/push。
