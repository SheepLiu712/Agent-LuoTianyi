# AI 决策记录

## 2026-11-17 #411：将聊天停止安全事实与结束维护结果分离（设计 gate 已通过，实施 gate 待定）

**待定问题**：维护失败不应独自阻断通话，但现有 `finalization_error` 混合停止任务与维护失败，`resources_released` 又只依据关闭上下文，不能只删除 Manager 的拒绝条件。

**背景约束**：
- 固定工作树 `.slim/worktrees/issue-411`，分支 `bugfix/call-handoff-maintenance`，基线 `ee718b21536e410ce5e4073b068f03b9bfcd68dc`。初始仅授权写 `server/src/stage`、相关 `server/tests` 和本文；后续精确扩域见下文；未获实现 gate 前不提交，当前不推送或写 GitHub。
- 验收依据：[维护者锁定评论](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/411#issuecomment-6910255769)。任务已停止、上下文已关闭、资源释放安全确定后，纯维护失败继续切换；清理失败或安全未确认仍拒绝。
- 不调整 90 秒结束维护、通话建立预算、建立步骤或供应商审核语义；不把结束维护后台化；保留 #427 embedding 准备/跳过和并行生成、阈值维护后台队列。
- 非作者设计 gate 通过前只写测试/本文，不改生产代码。

**调研参考**：
- Python/CPython asyncio [任务文档](https://docs.python.org/3.10/library/asyncio-task.html)：`wait_for` 等待取消完成；`shield` 保留被拥有任务，不把等待者取消当作终止已完成；`gather(return_exceptions=True)` 等待所有任务，但异常仅成为结果，不能据正常返回推断清理成功。通过 Context7 复核，实际解释器为 Python 3.10.21。
- 本项目 `StageLifetime.start/terminate` 与 Manager 已持有初始化/终止任务，复用现有所有权，不建立另一个生命周期框架。

**候选方案**
1. **仅删除 Manager 的 finalization_error 条件**：改动最少，但停止阶段异常也被放行，现有 context.close 成功不足以证明安全，否决。
2. **复用现有结果、分三段记录事实**：在 ChatStage 内分离停止、维护、关闭。将停止/关闭错误归 `cleanup_error`，只将维护错误归 `finalization_error`；`resources_released` 成为完整安全释放事实。Manager 对纯维护失败放行。选择此方案。
3. **扩展 domain 结果枚举/每阶段字段**：可表达更多细节，但超出授权写域并涉及 CallStage、其他 ManagedStage；现有字段已能表达本工单最小需求，暂不采用。

**选择**：候选 2。Oracle D1 非作者设计 gate attempt 1/3 通过，lead 已放行实施；尚未实现 gate，不提交或推送。初始化只允许 `StageStartAborted` 直接 `__cause__` 为 `CancelledError` 的明确包装；`StageStartAborted → OSError → CancelledError` 不放行。

**三段安全事实与最小改动**：
1. **停止段**：初始 `tasks_stopped=False`；取消并等待初始化及受管前台、阈值后台、提醒任务，成功完成后才置 True。停止阶段异常归 `cleanup_error`，不运行结束维护。对本次 join 的非取消异常应在等待所有兄弟退出后判为不安全，不能因 `return_exceptions=True` 遗失；正常取消不是清理错误。现有初始化包装会以 `StageStartAborted` 包裹取消，需要核对 cause，不能白名单放行全部初始化失败。优先局限在 ChatStage，不改变 CallStage 的取消规则。
2. **维护段**：仅停止安全后进入，继续原 `InteractionEnding`→Agent→唯一 `CognitiveMaintenance` 和原 `wait_for`；维护失败/超时保留 `finalization_error`、失败日志和 error span。超时必须实际取消并等待维护退出，不当作成功、不推进未提交进度。
3. **关闭段**：仅停止安全时关闭 context，防止仍在运行的任务使用已关闭上下文；关闭失败归 `cleanup_error`。只有停止事实成立且 context 关闭成功（或无 context）且无清理错误，才 `resources_released=True`，ChatStage/StageLifetime 才为 TERMINATED。
4. **Manager**：`_finish_source_interaction` 只在 `cleanup_error` 或 `not resources_released` 时拒绝。`_finish_stage` 原失败日志保留，安全释放后可移除 source 注册；纯维护失败不是维护成功。`_finish_call_ownership` 原资源守卫不变。

**所有权与取消**：
- `ChatStage.terminate` 使用同一个 `_lifetime.termination`，重复调用返回同一结果，不重新运行停止/close，也不能从“后续任务退出”推测先前失败结果可升级为安全。
- 停止失败时保留 TERMINATING、Manager `_managed`/`_termination_results`，call transition 不转为 CALL。`_finish_call_ownership` 再次读取同一不安全结果并拒绝释放；后续聊天/直接通话/用户数据 reset 不应取得有效所有权。
- 现有 `StageManager.close` 对不安全结果/遗留 managed/释放异常抛 `StageShutdownFailed`；不是必须自愈重试，重复 close 也不能虚假成功。明确保留此失败模式。
- 不捕获并转成功 `CancelledError`，不改变 shield、owned termination、CallStage 的 setup timeout、挂断先发送终态与后续 scope release。
- 私有 `_stop_work(require_safe_cleanup=False)` 默认保留断线既有策略；仅 `_stop_termination_work` 传 True 启用本次取消/join 收尾异常安全门，避免把 #411 扩成断线策略修改。对比回归覆盖同一 CancelDelivery OSError 在断线保留旧 CHAT 可重连、在终止保留不安全 CALL_TRANSITION。

**选择理由**：复用窄结果接口和既有拥有任务，安全判断集中于真正知道受管任务/上下文的 ChatStage；Manager 不解析错误字符串或供应商类型。

**未选原因**：
- 候选 1：会把停止失败误分成可忽略的维护故障，存在双交互和后台任务遗留风险。
- 候选 3：为本次单一行为扩散 domain/CallStage 的接口改动，没有必要且不在本 lane 写域。

**验证方式与证据路径**：
- 外部确认来源为维护者锁定评论，不以旧测试或 mock 返回值确认正确预期。
- 公开接缝为 `WebSocketAdapter` 打开真实 ChatStage→`StageManager.prepare_call_transition/try_to_get_stage`→真实 CallStage→显式 `call.start()`；新用例不 fake `StageTerminationResult`。
- 修改前现有旧维护必败用例和正常关闭用例：`2 passed, 2 warnings in 0.98s`（2026-11-17），仅生命周期基线，不是新需求通过。
- 首次只导入 stage 触发已有 SqlCallSessionRepository 循环 import；按 conftest 顺序先加载 `support.agent_runtime_support` 后正常。未改依赖/用户配置。每次运行将 `src.__path__` 限为本 lane/server/src，打印 `inspect.getfile(ChatStage/StageManager/CallStage)` 并 assert 路径在本 lane，避免 editable 回退主树。
- 红灯：将旧“维护失败必然通话失败”用例改为 `test_termination_maintenance_failure_does_not_fail_safely_released_call`，显式等待 call.start，要求 RINGING、账本不为 FAILED/SYSTEM_FAILURE、维护错误仍存在：`1 failed, 2 warnings in 0.93s`，实际失败链 `Manager._finish_source_interaction → StageHandoffFailed → StageInitializationFailed`。再运行 foreground/threshold 等待退出与 CancelDelivery 清理端口 OSError 三例：`3 failed, 43 deselected, 2 warnings in 1.47s`；旧实现丢弃清理异常后仍 `resources_released=True`，与安全验收相反。
- 安全网：真实前台/阈值任务取消 finally 用 Event 卡住，退出前不可 RINGING/不可释放 transition；停止阶段抛异常与 context.close 失败必须拒绝，重复 terminate/close 保持失败 owner；用户取消、服务关闭、setup timeout 和 provider 故障不放宽。
- 维护证据：`test_handoff_maintenance_safety.py` 使用真实 Agent、InteractionEndingHandler、CognitiveMaintenanceActionHandler、CognitiveMaintenanceSkill、AgentMemory/MemoryWriter、InteractionContext、SQLite ConversationService；仅外部模型/音频端口受控。分别注入 RuntimeError 与现有 LLMContentInspectionError，断言维护失败日志/error spans、未提交进度仍为 None、真实 context 已关，call RINGING/账本无失败，并通过真实 CallAnswerRequestedHandler/AnswerCallHandler 达到 ACTIVE 和持久账本 ACTIVE。单独 RecordingAgent 测试不充当清理或进度安全证明。
- 定向回归最小集合：`test_call_handoff.py`、`test_chat_stage.py`、`test_manager_lifecycle.py`；补现有认知维护/embedding 跳过、并行生成用例。全量离线门禁由 ci-verifier 统一调度，未执行前不声称通过。
- 运行命令（工作目录为本 lane 的 server）：
  ```powershell
  & 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c "import sys,pathlib,inspect; root=pathlib.Path.cwd(); sys.path.insert(0,str(root)); sys.path.insert(0,str(root/'tests')); import src; src.__path__=[str(root/'src')]; import support.agent_runtime_support; from src.stage.chat.chat_stage import ChatStage; from src.stage.stage_manager import StageManager; from src.stage.call.call_stage import CallStage; classes=(ChatStage,StageManager,CallStage); [(print(cls.__name__+'='+inspect.getfile(cls),flush=True)) for cls in classes]; assert all(pathlib.Path(inspect.getfile(cls)).is_relative_to(root/'src') for cls in classes); import pytest; raise SystemExit(pytest.main(['tests/integration/stage/test_call_handoff.py::test_termination_maintenance_failure_does_not_fail_safely_released_call','-q','--tb=short']))"
  ```

**真实 Agent 可观察性缺口与精确扩域（已授权修复，待实现 gate）**：`agent/processing/invocation.py:57–72` 在取消时等待 worker，但若 worker 的取消清理抛异常，只记录异常后重抛原 CancelledError；Stage 的 gather 无法从 `task.cancelled()` 识别此内部清理失败。当时本 lane 授权写域不含 Agent，故先暂停且未擅自扩改。真实 Agent + 真实 ChatStage/Manager/CallStage 的取消 finally OSError 探针 `test_real_agent_cancel_cleanup_failure_does_not_release_handoff` 已实跑：`1 failed, 2 warnings in 1.00s`，OSError 原因仍在日志，但 Stage 返回 `finalization_error=None, cleanup_error=None, resources_released=True`。lead/Oracle 已收到，Oracle 确认必须补窄可观察信号，当时暂停 runtime 继续改动/不提交，等待明确最小载体与精确授权；随后按下述授权完成局部实现。之前最终收窄版 160 passed/12.91s、四文件 ruff/black/diff-check 通过不含当时新增的红例，不代表最终候选验证；最终结果见下文。独立 Python 3.10 探针确认 `gather(return_exceptions=True)` 与之后 `task.result()` 均丢失 CancelledError 的 cause，不能靠异常临时属性/因果链或日志解析补安全判据。当时提出复用单次 CancellationToken 只读清理错误类型信号与独立清理结果载体两候选；lead/Oracle 选择前者并由 task-6 revision 3 精确授权 `domain/agent/handle_input.py` + `agent/processing/invocation.py`。只记录首个异常类型名，校验为标识符、不保存异常对象/自由文本或 traceback，不改取消 reason/首次原因/只读属性；正常取消、取消到达前已 done 的业务失败不标。Stage 停止前捕获本次 active request/foreground/threshold 执行对应的 token，所有任务 join 后检查，已被 finally 清掉的引用不影响检查；结束维护局部 request/execution token 在维护超时后也检查，清理失败不关 context、不释放 owner。

随后真实结束维护 execution 超时用例又取得 `1 failed, 125 passed in 2.40s`：`cognitive_maintenance/_parallel.py` 的 sibling drain 同样吞了外部模型取消 finally OSError，且遗留 `_GatheringFuture exception was never retrieved`。lead 在 task-6 revision 5 精确授权 `_parallel.py` 和 `skill.py`/`_call.py` 两个现有调用点传入同一 `invocation.cancellation`。保留原并行、shield、complete_owned、全部 siblings join；只对本次 active 且实际 cancel 成功的 child 的非取消收尾异常，在完整 join 后写已有 token，原 gather 通过 done callback 检索异常。此载体也覆盖一个分支先业务失败→取消兄弟→兄弟清理失败（无需外层取消）的近邻，普通业务失败仍不是清理错误。不改 shared complete_owned，不建立新框架/全局 registry。两条真实红均保留为长期测试，不换浅 mock 取绿。

**最终候选验证（2026-11-17，未提交/待实现 gate）**：
- 使用上文同一受控 import/inspect runner，最终 13 个 pytest 入口：`297 passed, 2 warnings in 17.39s`，exit 0。目标依次为 `integration/stage/test_call_handoff.py`、`test_chat_stage.py`、`test_manager_lifecycle.py`、`test_handoff_maintenance_safety.py`、`test_call_stage.py`、`test_stage_finalization.py`、`test_call_omni.py::test_provider_failure_ends_call_and_releases_session`、`unit/agent/test_cognitive_maintenance.py`、`integration/agent/test_call_threshold_maintenance.py`、`unit/utils/test_embedding_timeouts.py`、`unit/domain/test_handle_input_contract.py`、`unit/agent/test_cancellation_cleanup.py`、`unit/agent/test_interruptibility.py`；均以 `server/tests/` 为前缀。
- 真实 Agent 取消 finally 红例 + 全部 token 契约先局部 `109 passed, 2 warnings in 0.51s`。新 token 契约实现前为 `5 failed, 103 deselected in 0.89s`（字段/方法不存在）。
- 维护纯失败、LLMContentInspectionError 不假成功；真实 SQLite 进度不推进，error 日志/span 与终止总 span error 保留；RINGING 后真实接听处理器使持久账本 ACTIVE。停止清理异常、初始化清理异常、关闭失败、结束维护 handler/execution timeout 清理异常与生成分支失败导致 sibling 清理异常都拒绝；正常取消和业务先 done 的异常不误标。
- ruff 0.14.10 对 7 个改动生产文件 + 4 个改动/新增测试文件通过；black 26.5.1 对 7 个改动生产文件 + 新安全/Agent 测试/原 handoff 测试 10 文件检查通过；`git diff --check` exit 0。未重排未改动的 domain 契约测试全文格式。
- Python 3.10.21；`inspect.getfile` 打印并 assert ChatStage、StageManager、CallStage、invocation、CancellationToken 均来自本 issue-411/server/src。启动前仅 runner 内调整 sys.path/src.__path__，未安装 editable/改全局环境。
- 2 个 pytest 提示是预加载 support 后 anyio/pytest_asyncio 已导入，无法重写断言；另 pydub 提示未在当前 PATH 找到 ffmpeg。上述定向用例没有实际音频编解码，无真实供应商/设备验收。全量离线 CI 仍由 ci-verifier 统一调度，尚未运行，不等同已过 CI。
- 清理失败 owner 仍为 CALL_TRANSITION 或原 CHAT，重复 terminate 返回同一不安全结果，重复 close 拒绝；不迁移持久数据、不撤销 #427。不承诺慢拨号已经解决。

**风险与回滚**：停止结果的错误分类、取消任务 finally 失败、初始化被取消的 cause、Manager 的失败 scope release 都需独立 gate 核查。`resources_released=False` 将继续阻止新交互与关闭依赖，不能自作主张清理或放弃 owner。最终运行修改为已授权的 Stage 与单次清理事实传递链，后续可单独 revert 本单元，恢复旧准入策略；不迁移持久数据、不改模型配置，不撤销 #427。仅放行纯维护错误仍可能耗尽既有 10 秒通话预算，不承诺解决慢拨号。无真实供应商、生产配置、实体设备验证。
