# agent-门面重构

- PRD：`docs/开发进程文档/需求说明（PRD）/agent-门面重构.md`
- interface spec：`docs/项目说明/项目架构与接口（spec）/接口文档/agent/README.md`（目标接口章节；具体签名在片 1 定稿）
- 当前阶段：需求
- 总体状态：进行中
- 最后更新：2026-08-29

## 本 PR（纯文档）

- 目标：重写 PRD 与开发计划——按需求方 2026-08-29 指示，`refactor/agent` 分支只修改 agent 模块，把 agent 包装成只暴露少数通用接口的深模块；文档从"server-模块化重构"全 server 33 切片重写为聚焦 agent 门面的 4 片计划，文件同步更名为 `agent-门面重构`
- 范围：新增 PRD 与进度文档两份、删除旧名两份；不修改任何产品代码与测试
- 明确不包含：全部代码/测试切片；调用方迁移；测试目录归位（映射表已随旧版文档留在 git 历史，供后续分支取用）
- 验证及结果：PRD 引用的 file:line 证据已逐条复核（附录 A）；8 个过渡方法的 14 处调用方已定位（附录 A 末行）

## 切片清单

| 片 | 内容 | 状态 |
|---|---|---|
| 0 | PRD + 进度文档（本 PR） | 待审查 |
| 1 | `agent/README.md` 目标接口定稿（签名/字段/行为/契约场景） | 未开始 |
| 2 | `agent/__init__.py` 补导出 `LuoTianyiAgent` | 未开始（前置：测试基线） |
| 3 | 红测试 + `AgentFacade` 实现 + `get_agent_facade()` | 未开始 |
| 4 | 过渡接口标注（AgentRuntime 8 方法 / LuoTianyiAgent 对外系列 / get_default_agent / README） | 未开始 |

## 已完成

- 现状盘点：agent 模块（9 文件 1,225 行）、`AgentRuntime`（403 行，8 个编排方法 :189-294）、`CharacterRuntime` 结构（conscious/mind/reflex/capability_manager）
- agent 相关证据复核（附录 A）
- 调用方清单：8 个过渡方法 14 处调用、`get_agent()` 2 处调用——门面第一版必须与旧接口共存、零破坏

## 阻塞和未验证项

- 测试基线未建立：需 Python 环境（conda `lty` 或 venv + `server/docs/requirements.txt`）与 redis 可用性检查，片 2 前执行
- `interaction_context` 与 `AgentTurnResult` 字段清单在片 1 定稿，片 3 实现前不得先写代码

## 下一 PR

- 片 1：`agent/README.md` 目标接口定稿（纯文档）

## 附录 A：agent 门面证据复核（基于 4177799）

| 断言 | 复核结果 |
|---|---|
| `get_agent()` 直接返回 `LuoTianyiAgent` | ✓ `agent_runtime.py:173-175` |
| AgentRuntime 8 个业务编排方法 | ✓ :189 preprocess_chat_event / :193 try_handle_reflex / :204 extract_topic / :222 plan_topic_turn / :244 realize_topic_plan / :249 write_topic_memories / :267 detect_dates_for_topic / :285 update_user_profile_by_context；全部转发 CharacterRuntime 内部组件（preprocessor/reflex/mind/conscious） |
| agent/README 无外壳、`handle_stimulus` 不存在 | ✓ "当前实现还没有独立的'薄外壳'类" + "目标接口（尚未实现）"章节 |
| `LuoTianyiAgent` 对外暴露内部组件 | ✓ `luotianyi_agent.py:48-58`：database_manager/capabilities/mind/main_chat 均为公开属性 |
| `agent/__init__.py` 未导出 `LuoTianyiAgent` | ✓ 文件仅有 docstring |
| 8 个编排方法的调用方共 14 处 | ✓ ingress_helper.py:91,124（reflex/preprocess）；topic_planner.py:235,243（extract_topic）；topic_replier.py:172,182,188,198（plan/realize）；reflection_worker.py:103,141,176（dates/write_memories/profile）；world/dynamic_interaction/task.py:151,182（write_topic_memories） |
| `get_agent()` 调用方 2 处 | ✓ system_runtime.py:316、topic_replier.py:280 |
| `handle_stimulus` 全仓无实现 | ✓ grep 无命中（仅 agent/README 目标章节文字提及） |
