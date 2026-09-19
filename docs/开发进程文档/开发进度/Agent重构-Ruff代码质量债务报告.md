# Agent 重构 Ruff 代码质量债务报告

## 1. 基线与结论

- **报告日期**：2026-09-19
- **分支**：`qa/contract_finish`
- **代码基线**：`b7bbbf8210cdcb20a010b873a5a7b3273864dfcf`
- **配置**：`server/pyproject.toml`
- **Ruff**：`0.14.10`（配置要求 `==0.14.10`）
- **Python 目标版本**：3.10
- **行长上限**：120
- **McCabe 圈复杂度上限**：10；复杂度大于 10 触发 `C901`
- **当前扫描范围**：`src/agent`、`src/agent_runtime`、`src/domain/agent`、`src/infrastructure`、`src/stage`、`src/system/system_runtime.py`，共 138 个生产 Python 文件
- **未扫描范围**：测试、其他 `src/system` 模块、`src/world`、客户端及仓库其他语言；本报告不能证明这些范围通过 Ruff

复现命令：

```powershell
# 仓库根目录
D:\Anaconda\envs\lty\python.exe -m ruff check server --statistics

# 或 server 目录
D:\Anaconda\envs\lty\python.exe -m ruff check . --statistics
```

最初 110 文件范围的结果为 **98 errors / 49 个文件**。格式与复杂度逐项清偿后，Skill/基础设施收口又将门禁扩展到当前 138 个文件。当前 Ruff 门禁为 **PASS（0 errors）**。原五项 `C901` 中四项通过职责拆分或去除无效可选分支降至阈值内；扩围后又拆分了歌唱资源加载与音频切片，并逐项审查保留四个必须保持整体可见的语音生命周期状态机。当前共有五处函数级 `# noqa: C901`，均有紧邻的具体理由。没有使用全局 `ignore`、目录级忽略或债务基线文件隐藏问题。

## 2. 初始债务总览

| 规则 | 含义 | 数量 | 涉及文件 | 自动修复 | 处置要求 |
|---|---|---:|---:|---:|---|
| `E501` | 行长超过 120 | 46 | 15 | 0 | 人工换行；不可拆文本才允许局部说明 |
| `I001` | import 未按 Ruff 规则排序 | 44 | 41 | 44 | 可安全修复后复核 import 时副作用 |
| `C901` | 圈复杂度超过 10 | 5 | 5 | 0 | 必须逐函数审查；无充分理由则拆分 |
| `W293` | 空白行包含空格 | 3 | 1 | 3 | 机械修复 |
| **合计** |  | **98** | **49** | **47** |  |

基础正确性规则 `E4/E7/E9/F` 在本次重构范围内没有报告问题。这个结论仅适用于当前限定范围。

### 2.1 按模块分布

| 模块 | 总数 | 组成 |
|---|---:|---|
| `src/agent` | 66 | `C901` 4、`E501` 28、`I001` 31、`W293` 3 |
| `src/agent_runtime` | 6 | `C901` 1、`E501` 2、`I001` 3 |
| `src/domain/agent` | 11 | `E501` 2、`I001` 9 |
| `src/stage` | 15 | `E501` 14、`I001` 1 |

### 2.2 2026-09-19 清偿结果

- Black 26.5.1 按 120 字符口径格式化 87 个文件，23 个文件原样；二次检查 110 个文件全部无需再格式化。
- Black 清除全部 `W293`，并把 `E501` 从 46 项降至 2 项、`I001` 从 44 项降至 40 项。
- Ruff 安全修复清除剩余 40 项 `I001`；未使用 `--unsafe-fixes`。
- 两项 Black 无法处理的长日志模板/长 docstring 已人工换行，`E501` 清零且文本语义不变。
- 五项 `C901` 已逐项审查：四项清零，一项作为顺序事务流保留函数级例外；Ruff 当前报告 0 项。
- `compileall` 通过，`git diff --check` 无错误；生产 Python 修改全部位于既定门禁范围内，另有三处针对性测试修改。
- 本轮结构修改的针对性回归为 **45 passed / 3 skipped**。
- 完整相关回归为 **1019 passed / 3 failed / 2 skipped**。其中两项失败均为日志已输出到 stdout、但 `caplog` 未捕获；在未格式化的 `b7bbbf82` 临时 worktree 中原样复跑同样失败。第三项是 Windows 事件循环计时粒度导致的 `0.04s` 延迟断言波动，当前与基线均可稳定复现约 `0.031s < 0.035s`。三项均不在本次结构修改路径上，记为既有测试夹具/时序局限。

### 2.3 Skill/基础设施收口后的扩围结果

- 门禁新增 `src/infrastructure` 与 `src/system/system_runtime.py`；Black 与 Ruff 对当前 138 个文件均通过。
- `SingingManager.get_music_data` 拆出单曲加载，`get_song_segment` 拆出唱段查找与音频渲染；两者均降到复杂度阈值内。
- `SpeechBackend.stop`、`AsyncTTS.stream`、`_run_gsv_worker`、`TTSServer._stop` 保留函数级例外：它们分别拥有完整的停止重试、可取消生成器、子进程协议、进程与队列释放状态机，拆开会分散资源所有权和清理顺序。
- 全量回归更新为 **1289 passed / 17 skipped**；唯一警告来自 Starlette 对 AnyIO 类型别名的上游弃用提示。
- 单元测试覆盖门禁为 **873 passed，59.13%**，高于 `fail_under = 40`。

## 3. 圈复杂度审查结论

复杂度不超过 10 时门禁通过；复杂度 11 及以上必须先审查。初始五项和基础设施扩围项均已完成审查。

| 文件与函数 | 初始复杂度 | 审查与处置结论 |
|---|---:|---|
| `src/agent/handlers/stimulus/chat.py` `ChatReplyHandler.handle` | 13 | 拆为输入分类、记忆确认、普通对话回复三个命名明确的私有步骤；公开处理接口不变 |
| `src/agent/processing/execution.py` `Execution.run` | 12 | 保留；它是保持行动顺序、失败短路和输出收尾不变量的单条事务流。补齐 `Agent` 类型并使用函数级 `# noqa: C901` |
| `src/agent/response_parser.py` `StructuredResponseParser.parse` | 11 | 解析器自行创建具名 logger，移除没有真实替换需求的可选 logger 分支和构造参数，复杂度降至阈值内 |
| `src/agent/skills/expression/song_learning.py` `material` | 11 | 增加唱歌管理器 `Protocol`，装配时一次校验四个 callable；运行时仍保留素材读取异常降级，复杂度降至阈值内 |
| `src/agent_runtime/agent_runtime.py` `shutdown` | 11 | 拆为停止接收、等待在途调用、拥有式关闭向量库、最终清理四个生命周期步骤，复杂度降至阈值内 |
| `src/infrastructure/singing/singing_manager.py` `get_music_data` | >10 | 拆出 `_load_song`，主流程只负责扫描、登记和错误隔离，复杂度降至阈值内 |
| `src/infrastructure/singing/singing_manager.py` `get_song_segment` | 11 | 拆出 `_find_segment` 与 `_render_segment_audio`，复杂度降至阈值内 |
| `src/infrastructure/speech/speech.py` `SpeechBackend.stop` | 15 | 保留；一次原子关闭要同时处理重试、取消、超时、错误聚合和幂等状态，函数级例外已说明 |
| `src/infrastructure/speech/streaming.py` `AsyncTTS.stream` | 13 | 保留；同步生成器的待决读取、取消和关闭必须由同一异步生成器生命周期拥有，函数级例外已说明 |
| `src/infrastructure/speech/tts_server.py` `_run_gsv_worker` | 21 | 保留；它是子进程启动、请求协议与退出的完整状态机，函数级例外已说明 |
| `src/infrastructure/speech/tts_server.py` `TTSServer._stop` | 18 | 保留；进程终止升级与队列释放具有严格顺序和幂等要求，函数级例外已说明 |

此外，虽未被 McCabe 报告，`AgentRuntime.__init__` 的巨大门面组装被确认为更重要的可维护性债务。本轮已提取 `_build_agents`、`_build_agent`、`_build_stimulus_router`、`_build_action_router` 四个内部装配步骤；所有角色完整构造后才一次性赋给 `self._agents`，并在单角色内复用无状态预处理处理器及同一个学歌派发技能。

审查规则：

1. 不得仅为降低数字而把无意义代码段搬到辅助函数；拆分后应形成可命名、可单独理解的职责。
2. 若函数是显式状态机、协议决策表或必须保持整体可见的生命周期编排，可保留高复杂度。
3. 例外必须精确到函数，并在函数前记录具体理由；仅允许函数定义行使用 `# noqa: C901`。
4. 禁止对整个文件或目录忽略 `C901`。

例外格式：

```python
# Complexity exception: 分支与协议状态转换一一对应，拆分会隐藏状态完整性。
async def advance_state(...):  # noqa: C901
    ...
```

## 4. 初始行长债务

46 项 `E501` 分布如下：

| 实际长度 | 数量 |
|---|---:|
| 121–130 | 31 |
| 131–150 | 10 |
| 151–200 | 4 |
| 大于 200 | 1 |

### 4.1 按文件与行号

| 文件 | 数量 | 行号 |
|---|---:|---|
| `src/agent/facade.py` | 10 | 24、44、55、72、78、109、138、157、180、193 |
| `src/stage/chat_stage.py` | 9 | 231、312、352、354、366、452、496、505、513 |
| `src/agent/processing/handling.py` | 8 | 20、58、60、64、67、73、81、84 |
| `src/agent/processing/plan_emitter.py` | 3 | 26、40、131 |
| `src/agent_runtime/agent_runtime.py` | 2 | 117、494 |
| `src/agent/ledgers/_request_codec.py` | 2 | 42、56 |
| `src/agent/skills/conversation/compaction.py` | 2 | 42、66 |
| `src/stage/_config.py` | 2 | 23、27 |
| `src/stage/stage_manager.py` | 2 | 51、201 |
| `src/agent/context/models.py` | 1 | 156 |
| `src/agent/handlers/stimulus/router.py` | 1 | 22 |
| `src/agent/processing/interruptibility.py` | 1 | 25 |
| `src/domain/agent/action_plan.py` | 1 | 116 |
| `src/domain/agent/handling_report.py` | 1 | 114 |
| `src/stage/_sinks.py` | 1 | 62 |

### 4.2 优先检查的极长行

| 文件与行号 | 长度 |
|---|---:|
| `src/stage/_config.py:23` | 261 |
| `src/agent/facade.py:138` | 197 |
| `src/agent/ledgers/_request_codec.py:42` | 172 |
| `src/stage/_config.py:27` | 168 |
| `src/agent/facade.py:44` | 165 |

处置原则：优先使用括号换行、每行一个参数/字段和具名局部变量；不得通过缩短清晰的领域名规避限制。不可拆分的 URL、外部协议字面量或测试快照不在当前生产范围内，后续遇到时应使用最窄的局部例外并说明原因。

## 5. 初始可机械修复债务

### 5.1 import 排序

`I001` 共 44 项，涉及 41 个文件。其中 `src/agent/luotianyi_agent.py` 有 4 个独立 import 块，其余文件各 1 项。

建议单独提交机械修复：

```powershell
D:\Anaconda\envs\lty\python.exe -m ruff check server --select I --fix
```

修复后必须审查 diff，特别确认延迟 import、注册顺序和有导入副作用的兼容模块没有改变语义。不得使用 `--unsafe-fixes`。

### 5.2 空白行

`W293` 全部位于：

- `src/agent/luotianyi_agent.py:244`
- `src/agent/luotianyi_agent.py:248`
- `src/agent/luotianyi_agent.py:251`

可与 import 排序一起机械修复，但应保持为独立于行为修改的提交。

## 6. 初始完整文件级债务清单

| 文件 | 总数 | 构成 |
|---|---:|---|
| `src/agent/facade.py` | 11 | `E501` 10、`I001` 1 |
| `src/agent/processing/handling.py` | 9 | `E501` 8、`I001` 1 |
| `src/stage/chat_stage.py` | 9 | `E501` 9 |
| `src/agent/luotianyi_agent.py` | 7 | `I001` 4、`W293` 3 |
| `src/agent/processing/plan_emitter.py` | 4 | `E501` 3、`I001` 1 |
| `src/agent_runtime/agent_runtime.py` | 3 | `C901` 1、`E501` 2 |
| `src/agent/ledgers/_request_codec.py` | 3 | `E501` 2、`I001` 1 |
| `src/agent/skills/conversation/compaction.py` | 3 | `E501` 2、`I001` 1 |
| `src/agent/processing/execution.py` | 2 | `C901` 1、`I001` 1 |
| `src/agent/processing/interruptibility.py` | 2 | `E501` 1、`I001` 1 |
| `src/agent/response_parser.py` | 2 | `C901` 1、`I001` 1 |
| `src/domain/agent/action_plan.py` | 2 | `E501` 1、`I001` 1 |
| `src/domain/agent/handling_report.py` | 2 | `E501` 1、`I001` 1 |
| `src/stage/_config.py` | 2 | `E501` 2 |
| `src/stage/_sinks.py` | 2 | `E501` 1、`I001` 1 |
| `src/stage/stage_manager.py` | 2 | `E501` 2 |
| `src/agent_runtime/__init__.py` | 1 | `I001` 1 |
| `src/agent_runtime/agent_registry.py` | 1 | `I001` 1 |
| `src/agent_runtime/character_runtime.py` | 1 | `I001` 1 |
| `src/agent/context/__init__.py` | 1 | `I001` 1 |
| `src/agent/context/_storage.py` | 1 | `I001` 1 |
| `src/agent/context/context_factory.py` | 1 | `I001` 1 |
| `src/agent/context/conversation_context.py` | 1 | `I001` 1 |
| `src/agent/context/interaction_context.py` | 1 | `I001` 1 |
| `src/agent/context/models.py` | 1 | `E501` 1 |
| `src/agent/context/user_context.py` | 1 | `I001` 1 |
| `src/agent/handlers/action/router.py` | 1 | `I001` 1 |
| `src/agent/handlers/action/say.py` | 1 | `I001` 1 |
| `src/agent/handlers/stimulus/chat.py` | 1 | `C901` 1 |
| `src/agent/handlers/stimulus/router.py` | 1 | `E501` 1 |
| `src/agent/ledgers/_execution_codec.py` | 1 | `I001` 1 |
| `src/agent/ledgers/_output_codec.py` | 1 | `I001` 1 |
| `src/agent/ledgers/output_outbox.py` | 1 | `I001` 1 |
| `src/agent/main_chat.py` | 1 | `I001` 1 |
| `src/agent/processing/invocation.py` | 1 | `I001` 1 |
| `src/agent/processing/output_emitter.py` | 1 | `I001` 1 |
| `src/agent/processing/plan_identity.py` | 1 | `I001` 1 |
| `src/agent/reflex/character_reflex.py` | 1 | `I001` 1 |
| `src/agent/reflex/touch.py` | 1 | `I001` 1 |
| `src/agent/skills/expression/song_learning.py` | 1 | `C901` 1 |
| `src/agent/skills/expression/speaking.py` | 1 | `I001` 1 |
| `src/agent/text_cleaning.py` | 1 | `I001` 1 |
| `src/domain/agent/__init__.py` | 1 | `I001` 1 |
| `src/domain/agent/_stimulus_contract.py` | 1 | `I001` 1 |
| `src/domain/agent/execution_output.py` | 1 | `I001` 1 |
| `src/domain/agent/execution_report.py` | 1 | `I001` 1 |
| `src/domain/agent/interaction_snapshot.py` | 1 | `I001` 1 |
| `src/domain/agent/realization_sinks.py` | 1 | `I001` 1 |
| `src/domain/agent/stimulus.py` | 1 | `I001` 1 |

## 7. 清偿执行顺序

1. **机械批次**：修复 `I001`、`W293`，只做安全自动修复并人工审查 diff。
2. **可读性批次**：处理 `E501`，优先五处长度超过 150 的行；不顺带改变行为。
3. **结构批次（已完成）**：逐个审查五项 `C901`；四项拆分或消除无效分支，一项有理由保留。
4. **复验（已完成）**：Ruff、Black 幂等检查、`compileall`、`git diff --check` 和针对性回归均已执行；完整回归中的三项既有夹具/时序问题已单列。
5. **扩围（已完成本阶段）**：Skill 收口涉及的 `src/infrastructure` 与 `src/system/system_runtime.py` 已纳入；其他 Server 生产模块仍须单独测量，不得把本报告的零债务结论外推到未扫描范围。

## 8. 本阶段完成标准

- [x] `D:\Anaconda\envs\lty\python.exe -m ruff check server` 退出码为 0。
- [x] 47 项可机械修复问题全部清零，且没有使用 unsafe fix。
- [x] 46 项行长问题清零。
- [x] 原五个复杂函数及基础设施扩围项均有逐项结论；拆分后的职责清晰，五个保留项具有函数级 `C901` 例外和理由。
- [x] 未新增全局 ignore、目录级 C901/E501 ignore 或掩盖历史债务的宽泛 per-file ignore。
- [x] 报告已更新为实际清偿后的计数和验收结果。
