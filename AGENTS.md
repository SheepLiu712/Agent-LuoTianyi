工作前请牢记[《开发守则》](docs/开发守则.md)

产出或提交 PR 审查报告时，加载并遵守 `docs/开发进程文档/skills/pr-review-report/SKILL.md`。

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

改动代码前先读 [《代码地图》](docs/代码地图.md)（模块职责、边界、关键设计理由与测试入口）；领域术语见 [CONTEXT.md](CONTEXT.md)；路线图见 [docs/TODO.md](docs/TODO.md)；当前功能文档见 [docs/开发进程文档/](docs/开发进程文档/)。

## 仓库现状

> 2026-10 快照；易过期的细节以分支、Issue、PR 与 `docs/开发进程文档/` 为准。

- **正在开发**：用户语音消息（F1）——spec、App 界面蓝图与实现计划在 `docs/开发进程文档/`；工单 VM-1…VM-9 已实现，并以堆叠 PR 合入 `feat/voice`（#214–#222，squash）；下一步为集成（`feat/voice` → `dev`）。
- **后续计划**：用户实时语音通话（F2）——spec 与实现计划已就绪，尚未启动。
- **分支与 PR**：集成分支 `feat/voice`（主仓库）；F1 工单分支已随合并从主仓库删除，同名备份保留在 fork（`origin`）；当前工作分支 `feat/voice-message`。早期工单分支暂留主仓库、后续统一迁移到 fork（fork 上已有同名副本）。
- **工单跟踪**：Issue #205–#213（VM-1…VM-9）已随合入关闭。
- **测试基线（最近一次）**：server 单测 976 passed（另有 1 个本机 `QWEN_API_KEY` 401 环境性失败，与代码无关）；cli-client 153 passed；app 21 套件 / 122 用例（tsc 干净）。

## 仓库与远端约定

- `origin` = 个人 fork（`jinyiwei2012/Agent-LuoTianyi`）；`upstream` = 主仓库（`SheepLiu712/Agent-LuoTianyi`）。
- 开发分支一律在 fork 中创建并推送到 `origin`；不向主仓库推送开发分支，保持主仓库分支干净。
- 变更通过跨仓库 PR 从 fork 合入主仓库：head 为 `jinyiwei2012:<branch>`，base 为主仓库的目标分支。
- 同步主线从 `upstream` 拉取（如 `git fetch upstream`）。
