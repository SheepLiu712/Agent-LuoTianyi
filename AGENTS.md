工作前请牢记[《开发守则》](docs/开发守则.md)

使用以下模板撰写文档以保证人类可读性：
- 创建SPEC文档时，使用[spec文档模板](docs/模板/spec文档模板.md)撰写。
- 提交PR时，使用[pr描述模板](docs\模板\pr描述模板.md)撰写PR描述，确保PR的目的、改动内容、改动范围、关键调用链和验证方法清晰可读。
- AI 审查或复审 PR 时，必须读取并执行仓库内的 [PR 审查技能](docs/模板/skills/pr-review-report/SKILL.md)。它是 AI 执行项目 PR 审查的唯一流程标准，并要求按 [PR 审查结论模板](docs/模板/pr审查结论模板.md)撰写报告。

## 仓库架构

本仓库是 AgentLuo（洛天依对话 Agent）项目：一个服务端 + 多个客户端（桌面 / CLI / 移动端），客户端通过 HTTP / WebSocket 使用服务端；角色认知、对话与记忆、世界任务运行在服务端。

| 子项目 | 职责与技术 | 入口 |
| --- | --- | --- |
| `server/` | Python / FastAPI 服务端：角色运行时、对话、技能、持久化、世界任务、管理接口 | `server/server_main.py`、`server/src/server_runtime.py` |
| `client/` | Python / PySide6 桌面客户端：窗口、Live2D、消息收发、音频播放 | `client/main.py` |
| `cli-client/` | 无 GUI 命令行客户端：注册、登录、历史、聊天、回复与场景判定 | `cli-client/cli.py` |
| `app/` | Expo / React Native 移动客户端（当前重点 Android），Live2D 通过 WebView | `app/app/_layout.tsx`、`app/app/index.tsx` |
| 管理控制台 | 服务端附带的 Web 前端（配置、账号、运行时管理），不是角色聊天客户端 | `server/res/admin_ui/` |

`server/src/` 主要模块：`domain`（共享契约）、`web`（HTTP / WS 入口）、`application`（应用用例）、`adapter`（信道语义转换）、`stage`（交互生命周期与时序）、`agent`（认知与技能）、`agent_runtime`（角色装配）、`infrastructure`（模型 / 存储 / 媒体 / 配置）、`world`（世界任务与采集）；组合根为 `server_runtime.py`。

运行时消息链：客户端 → `web.websocket` → `adapter.websocket` → `ChatStage` → `Agent.handle_stimulus` → 计划队列 → `Agent.realize_action_plan` → 输出 sink → `adapter.websocket` → 客户端。

改动代码前先读 [《代码地图》](docs/代码地图.md)（模块职责、边界、关键设计理由与测试入口）；领域术语见 [CONTEXT.md](CONTEXT.md)；路线图见 [docs/TODO.md](docs/TODO.md)；当前实现类文档见 [server/docs/dev/](server/docs/dev/)。

## 仓库现状

> 2026-11-06 快照；易过期的细节以分支、Issue、PR 为准，引用前先复核，不要当作长期事实。

- **分支位置**：`dev` 为 `54236431`，与 `upstream/dev` 一致；`master` 为 `3368f3e5`（2026-10-07 合并 `v0.5.0`）。`dev` 领先 `master` 52 个提交，`master` 另有 10 个提交未回流 `dev`。进入 `dev` 不等于进入 `master` 或发布。
- **F1 用户语音消息：已完成并发布**。该功能经 [PR #244](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/244) 集成至 `dev`，随后合入 `master` 并打 `v0.5.0` 标签；[Release v0.5.0](https://github.com/SheepLiu712/Agent-LuoTianyi/releases/tag/v0.5.0) 已于 2026-10-16 发布。历史验收证据见 [用户语音消息验收](server/docs/dev/用户语音消息验收.md)，其中的测试数字与用户确认均为当时证据，不代表当前 `dev` 的全量回归。
- **F2 实时语音通话：主体已集成 `dev`，未进入 `master`、未发布**。[PR #361](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/361) 于 2026-10-21 从其特性分支 squash 合入（`7d19a9aa`），原特性提交不是 `dev` 的祖先属正常现象。[Issue #362](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/362) 已于 2026-11-05 按 completed 关闭，关闭说明为「语音通话功能基本可以验收」，同时明确三项不在验收范围：延时以客户端 ACK 近似客户端播放、异常场景待生产事故再处理、客户端回声抑制与降噪不验收。引用时须保留这些边界，不得简写为「全部验收通过」。
- **文档布局**：`docs/开发进程文档/` 已在本仓库主线退休（整目录删除），其中已完成的 spec 与实现计划只能从历史提交或旧分支取阅，不要在新工作中继续引用该路径。现行实现类文档位于 `server/docs/dev/`，如 `用户语音消息验收.md`、`call-capability-api.md`、`aliyun-realtime-speech.md`、`认知维护迁移与验收.md`。
- **开放问题分布**：[#391](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/391) 为 CI 基线（时区依赖用例与 flaky 用例）；[#370](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/370)–[#377](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/377) 为桌面端与通话的 P1/P2 审查项；[#364](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/364) 登录窗口 Esc 退出；[#360](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/360) 统一聊天与通话嘴型驱动；[#386](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/386)/[#387](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/387) 为响铃与头像增强；[#315](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/315)/[#316](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/316) 为 App 录音生命周期与权限判断。
