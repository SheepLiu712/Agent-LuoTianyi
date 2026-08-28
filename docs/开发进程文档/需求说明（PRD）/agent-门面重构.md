# Agent 门面重构需求（PRD）

- 功能短名：agent-门面重构（进度文档同名）
- 分支定位：`refactor/agent` 分支**只修改 agent 模块**（`server/src/agent/` 与 `server/src/agent_runtime/` 的接口面），目标是把 agent 包装成只暴露少数通用接口的深模块
- 依据文档：`开发守则.md` §2.1"Agent 的有限 interface"、§3"深模块原则"；`接口文档/agent/README.md`"目标接口（尚未实现）"章节；差异文档 #3/#4/#5
- 流程：一片一 PR 交上游 `SheepLiu712/Agent-LuoTianyi` 的 `refactor/agent`，每片完成即停待审查
- 状态：需求评审中
- 最后更新：2026-08-29

## 1. 要解决什么问题

角色心智（agent）是全项目的核心深模块，但当前它不是一个"深模块"——内部结构完全暴露：

1. **没有外壳**：`agent_runtime.py:173` 的 `get_agent()` 直接返回 `LuoTianyiAgent`，其内部的 `mind`（潜意识）、`capabilities`（能力）、`database_manager`、`main_chat`（LLM 模块）全部对外可见；
2. **编排逻辑长在运行时上**：`AgentRuntime` 公开 8 个业务方法（`agent_runtime.py:189-294`：preprocess_chat_event / try_handle_reflex / extract_topic / plan_topic_turn / realize_topic_plan / write_topic_memories / detect_dates_for_topic / update_user_profile_by_context），全部只是转发 `CharacterRuntime` 内部组件，已被 stage 四个组件与 world 共 **14 处**调用（行号清单见进度文档附录 A）；
3. **事实公开接口泛滥**：`LuoTianyiAgent` 的 `*_for_pipeline` / sing / tts_say / citywalk 系列被 stage 直用，`main_chat.py` 的回复类型也被 stage 直接消费。

后果：每接入一种新交互方式（电话、具身、游戏世界），调用方都必须理解并逐步重放"预处理→反射→话题提取→规划→实现→日期检测→记忆写入"整条内部链路，agent 内部任何重构都会波及所有调用方。

**本次明确不解决**：调用方迁移（等门面稳定后由后续分支执行）、agent 之外任何模块的问题。

## 2. 目标：包装成只暴露少数通用接口的深模块

新增 `AgentFacade`（位于 `server/src/agent/facade.py`），对外**只暴露两个通用接口**：

| 接口 | 说明 |
|---|---|
| `await handle_stimulus(stimulus, interaction_context=None) -> AgentTurnResult` | 唯一的刺激处理入口。`stimulus` 为 domain `Stimulus`；`interaction_context` 携带一次交互所需的既有输入（候选字段：user_id、conversation_history、unread_snapshot、external_context、sing_excluded_segments、sing_emotion_context、send_reply_callback、related_memories，最终清单在片 1 定稿） |
| `ensure_dependencies()` | 生命周期检查，语义同 `LuoTianyiAgent.ensure_dependencies()`：依赖缺失时抛 `RuntimeError` |

**第一版纯委托**：`handle_stimulus` 内部按现有管线的既定顺序依次委托既有实现——preprocess → reflex → extract_topic → plan → realize → detect_dates → write_memories——不重写任何内部逻辑、不改变任何一步的行为。反射命中时短路返回，不进入话题管线（与现行为一致）。

**零破坏兼容策略**：

- `get_agent()` 行为不变（仍返回 `LuoTianyiAgent`），现有 14 处调用方一行不改；
- 门面经新增访问器 `AgentRuntime.get_agent_facade(character_id=None)` 获取；
- 旧接口全部保留并标注"过渡接口，禁止新增调用方"（片 4），待调用方迁移分支收窄。

## 3. 其他代码怎样使用它

本分支完成后（调用方尚未迁移，此为目标形态）：

```python
agent = agent_runtime.get_agent_facade("luotianyi")
result = await agent.handle_stimulus(stimulus, interaction_context)
```

调用方只提供刺激与交互上下文，不需要知道 agent 内部经过记忆检索、提示词组装、LLM 调用、解析还是能力执行。接入新交互方式时，只需把外部事件转换成 `Stimulus` 再调用 `handle_stimulus`，不再复制内部链路。

语音（sing / tts_say / tts_say_stream）与 citywalk 查询**暂不入门面**：它们尚无经由门面的真实调用场景，按守则"只有出现第二个真实调用场景时才增加公开方法"原则，等调用方迁移分支按实际需求决定去留。

## 4. 调用后会发生什么？失败时怎么办？

- **副作用**：完全沿用各既有步骤（LLM 请求、记忆写入、数据库读写、音频生成），门面不新增任何副作用；
- **返回**：`AgentTurnResult`（门面模块内 dataclass），字段含 `reflex_handled`（反射是否短路）、`response_lines`（`list[OneResponseLine]`）、`dates_result`、`memory_result`，最终字段清单在片 1 定稿；
- **依赖未注入**：抛 `RuntimeError`（与现状一致，不新增兜底）；
- **模型返回无法解析 / 能力执行失败**：异常向上传播，由调用方在 stage/Adapter 边界转换为可观察的失败结果（与现状一致）；
- **重复调用 / 并发**：门面无状态、不加锁（与现状一致，状态管理仍属 stage 职责）；
- **流式语音**：本分支不涉及（未入门面）。

## 5. 怎样证明它做对了

全部从门面公开 interface 观察，Fake 只走外部 seam（LLM、数据库、音频），不 mock 项目内部实现：

1. 反射命中：`handle_stimulus` 短路返回 `reflex_handled=True`，不调用 mind 的任何话题方法；
2. 正常输入：按序走完全链，`AgentTurnResult` 各字段与既有各步骤的返回一致；
3. 依赖未注入：`ensure_dependencies()` 与 `handle_stimulus` 明确失败；
4. **零破坏**：`get_agent()` 返回类型不变；全量 pytest 基线前后一致（收集数/通过/失败/跳过）；`grep` 证明 14 处调用方未修改；
5. **门面最小面**：`grep` 证明 `AgentFacade` 公开方法仅 `handle_stimulus` 与 `ensure_dependencies`；
6. **过渡标注**：旧接口标注完成，agent/README 与源码一致；
7. 流程：每片 ≤500 行手写改动、一片一 PR、进度文档同步更新。

## 6. 改造计划（4 片，一片一 PR）

| 片 | 内容 | 类型 |
|---|---|---|
| 1 | `agent/README.md` 目标接口定稿：`handle_stimulus` 签名、`interaction_context` 与 `AgentTurnResult` 字段、副作用、正常/异常行为、契约测试场景清单 | 文档 |
| 2 | `agent/__init__.py` 补导出 `LuoTianyiAgent`（独立小片，零行为变化） | 代码 |
| 3 | 红测试先行（Fake preprocessor/reflex/mind/conscious 走既有 seam）→ 实现 `AgentFacade`（`handle_stimulus` 纯委托 + `AgentTurnResult`）与 `AgentRuntime.get_agent_facade()`；`get_agent()` 行为不变 | 代码 |
| 4 | 过渡接口标注：AgentRuntime 8 方法（:189-294）、`LuoTianyiAgent` 对外系列、`get_default_agent()`；agent/README"当前对外接口"章节加过渡标记 | 代码注释+文档 |

**前置条件**：片 2 开始前建立测试基线——Python 环境（conda `lty` 或 venv + `server/docs/requirements.txt`）、redis 可用性检查、`pytest --collect-only` 与全量结果记入进度文档。

**每片固定流程**：SKILL 门禁审计 → 更新进度文档 → 测试（新接口片红先行）→ 最小实现 → 受影响模块 + 全量回归 → 推送 fork → PR 交上游 `refactor/agent` → **停，等审查**。

## 7. 非目标（移出本分支，后续独立分支处理）

- 调用方迁移（stage 四组件、world 改走门面）与 `get_agent()` 翻转；
- stage↔adapter 窄接口、world 注入收窄、utils 反向依赖清理、全局服务定位器收缩；
- 测试目录按守则归位（59 个平铺测试文件的归位映射已记录在 git 历史，供后续分支取用）；
- system / capabilities / subconscious 等其他模块的包导出修复；
- 物理目录搬移（chat_session→stage 改名、adapter 顶层归位）、`server_main.py` REST 下沉、>500 行文件拆分；
- CI 搭建、fork dev 独有 9 提交（server hardening）移植、harmony 分支 89cb7a0 回移。

## 8. 风险与依赖

- **签名前瞻性**：`handle_stimulus` 按现管线顺序定稿，调用方迁移分支落地时可能需微调参数——届时先改 agent/README spec（独立文档 PR）再改实现，不让实现先行；
- **测试脚手架**：Fake `CharacterSubconscious`/`ChatPreprocessor`/`CharacterReflex` 的工作量主要在测试侧，参考现有 `test_agent_reflex.py` 与 pipeline 测试的 Fake 模式；
- **环境**：torch/gsv-tts/chromadb/redis 重依赖可能限制基线可跑范围，环境性跳过逐条记录，不伪造结果。

## 9. 页面行为与埋点

不适用：无 UI 变化；观测服务（ObservabilityService）的写入接口与数据格式保持不变。

## 10. 新增公开 interface 确认记录

本 PRD 列出的新增公开 interface（`AgentFacade.handle_stimulus`、`AgentFacade.ensure_dependencies`、`AgentTurnResult`、`AgentRuntime.get_agent_facade`）已经需求方 2026-08-29 确认。实现中如需超出此清单新增或扩大任何公开 interface，立即停止并另行确认。
