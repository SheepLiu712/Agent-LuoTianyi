# AI 决策记录

## 2026-11-17 #410 U1 总预算配置与控制台

**待定问题**：核心预算链已提交 `f3e2cb8d27dd5b236138aa8bd805060b050a4d0e`，控制台仍只显示旧内层值，且共享解析会用旧非法键阻止生产配置校验。需要一次可回滚的配置/UI单元，保留独立诊断严格限时。

**背景约束**：lead放行task8 U1 rev8，仅现有配置编辑/校验、Qwen生产解析、控制台及其真实构建产物、公开模板/README和必要测试。不改Manager、Stage owner、用户config/secret；不混Fun-ASR脚本或结构化日志单元，gate前不commit/push。

**调研参考**：[React官方input](https://react.dev/reference/react-dom/components/input) 经Context7核对受控number输入保留原始string、onChange同步更新，避免输入中途转NaN/JSON null；UI skill精准表单查询只采用number类型与明确错误提示，不换样式系统。既有#435面板局部select/草稿/串行apply作为稳定行为保留。

**候选方案**
1. **有效值视图+单叶子patch**：视图显示stage_manager.call_setup_timeout缺省10，提交只合这一键；validator按正有限数/bool排除；Qwen生产显式忽略legacy限时，独立adapter from_mapping默认严格。
2. **把整个stage_manager暴露并覆盖保存**：便于编辑但可能覆盖termination/offline兄弟设置，违背最小范围。
3. **独立新解析模块同时修改Manager**：可共享默认值，但新增跨层依赖/改既过gate核心，无必要。

**选择**：候选1。只抽model_editor本次leaf写入小helper避免既有apply复杂度10→11，不建跨层模块。UI保存raw string，提交验证非空/正有限后转number；旧connect/session编辑字段撤下，原值不启动改写/删除。管理apply原校验→写→按需重启链路复用。

**未选原因**：候选2会扩大写入面并破坏#435；候选3扩大邻域改动与回归成本。模板显式10但缺省行为不变；独立诊断仍严格旧参数，避免本单元把它变无界。

**验证方式**：首个view/apply公开接缝red job `pwsh-d8c30569f1ca4985` 为2 failed/7 deselected/.47s，均因有效预算字段缺失；最终job `pwsh-54673a2cace24a72` 为77 passed/3.47s，含默认/30/leaf兄弟保持、非法总时限apply不写不重启、5类旧Qwen非法键不阻完整validator而独立adapter拒绝；4生产Ruff/Black通过。首次回归旧session_timeout=-1管理校验预期失败，按维护者明确兼容要求更换为生产/诊断对照；独立adapter原严格测试保留。独占窗口内本tree锁文件SHA256 12109e9efe5a0c039c482db7cdb91d0e20632d0436cf019901a2318fdbacb7e4未变，显式Node22.23.5 npmci69packages7s与tsc/vite构建成功（job `pwsh-2673bb6d91ba4416`）；新构建产物真实Chromium `python -m scripts.check_admin_model_panels` exit0（job `pwsh-38525d4753d6490f`），空输入不发请求/总预算30.5保存刷新/局部放弃/其他面板草稿保留。未改用户配置、不把UI模拟API说成真实业务runtime重启。资源清单按新JS及HTML实际字节/哈希同步；初次资源校验通过与3项发布资源测试通过，但diff-check随后发现HTML混合CRLF，组合shell末status掩盖其非零，已明确排除该次diff绿声明。仅生成HTML规范为LF（无DOM/JS语义变化，423字节、SHA256 282cec880bde7c0767ba3e84257296d457031a48fd7e733bc5b6ee2d2dbbc185），重算清单后资源验证和逐项diff-check均通过，未重复浏览器。

**风险与回滚**：UI与有效默认漂移、整树覆盖、旧键解析模式误伤诊断。用单叶子与生产显式flag、公开Manager契约对照和局部草稿浏览器证据控制；回退本单元代码/资源/模板，不删除旧键、不迁移用户数据。部署资源清单须同步实际构建文件路径/size/hash，不能只改TSX。

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
