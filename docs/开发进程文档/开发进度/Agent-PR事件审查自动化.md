# Agent PR 事件审查自动化开发进度

关联工单：[#93](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/93)

> 当前阶段：GREEN
>
> 当前状态：退役候选完成，等待 PR 审核

## 当前行为切片

- PR：[#108](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/108)（分支 `codex/revise-development-pr-flow`，目标 `dev`，Ready，等待其他开发者审核）。
- 目标：把 SPEC、Red、Green 改为同一行为切片分支内的 commit 与作者自审门禁；完整 Green 候选才提交 PR，由其他开发者审核。管理员在评审时自行决定是否手动使用 AI，不再由 PR 事件自动审查或合并。
- 范围：修订开发守则及 `spec-tdd-pr-guard`；删除 `agent-refactor-review.yml`、专用 `.github/codex` 审查 bundle 和只服务该流程的 actionlint runner 标签配置；停用并注销本机专用 runner、计划任务和仓库开关变量。
- 明确不包含：不修改 Agent 产品代码、#107 的测试或实现、仓库通用 Actions 权限、其他 runner 和其他 Codex 配置。
- Red：不适用。本切片删除废弃流程，不为“文件应不存在”制造测试；使用仓库文件清单、GitHub runner/变量状态和本机计划任务/进程状态验证。
- Green：当前分支已删除仓库内自动触发 workflow、专用审查 bundle 和只服务该 runner 的 actionlint 配置；仓库变量、本机计划任务、runner 进程和 GitHub runner 注册均已删除。
- 作者自审与验证：仓库工作树已无 `.github` 审查文件，排除本历史进度文档后定向扫描未发现 `pull_request_target`、`AGENT_PR_REVIEW_ENABLED`、专用 runner 或 workflow 引用；更新后的 `spec-tdd-pr-guard` 通过 Skill validator，三份中文文档通过严格 UTF-8 解码，`git diff --check` 通过。本机 runner 缓存目录已失去启动入口和远端注册，但当前命令策略阻止递归删除，作为不影响运行的残留明确记录。

## 退役后的目标

PR 创建、push、编辑、评论、Ready 或 review 事件不再触发 AI 审查，也不再由自动流程批准或合并。管理员在其他开发者审核完整 Green 行为切片时，可按当前风险和需要手动调用 AI 辅助；AI 结果只作为审核证据，不替代管理员的最终判断。

## 历史最后一次上线 PR

- PR：[#104](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/104)（分支 `codex/record-pr-review-branch-migration`，目标 `dev`）
- 目标：记录默认分支迁移和发布分支清理的最终结果。
- 范围：只更新本进度文档，关联迁移 PR #102 和清理 PR #103 的验证事实。
- 明确不包含：不修改工作流、审查策略、Agent 产品代码、#90/#94 分支或本机 Runner 配置。
- 验证及结果：GitHub 默认分支为 `dev`；`dev` 上的 `Agent refactor PR review` 工作流为 active；`master` 当前文件树与自动化引入前的发布提交 `450c1a53` 无差异。

## 历史已完成（退役前）

- 建立新建、更新、重新打开、Ready、retarget、review 提交/编辑/撤销、普通评论和行内评论事件入口。
- 在付费调用前限制目标分支、工单范围、同仓库 head 和 write/maintain/admin 触发者。
- 将候选 target base 与 PR head 同时固定，构造并测试对应的候选集成树。
- 将使用本机 Codex 的只读审查 job 与拥有 GitHub 写权限的发布 job 分离。
- 发布前独立校验完整输出契约、工单集合、base/head SHA、PASS 测试证据、P0/P1 finding 和人工 review 最新状态。
- 将核心合并策略提取到 `.github/codex/scripts/review-policy.js`，并增加 Node 内建测试。
- 将第三方 Actions 固定到已核验的提交 SHA；同一次运行的三个 job 使用同一个 `github.workflow_sha` 读取可信策略。
- 仓库已允许 GitHub Actions 创建 PR review；变量 `AGENT_PR_REVIEW_ENABLED` 已创建并设置为 `true`。
- 支持根 PR 直接指向 `refactor/agent`，以及同仓库开放父 PR 组成、最终终止于该根 PR 的无环堆叠链。
- 子 PR 使用直接父 PR 的固定 head 作为审查基线，只能合入父分支；父 PR 更新后必须触发新的完整候选审查。
- 默认跳过真实学歌、B 站/VCPedia 实时抓取和其他长耗时外部测试；仅非必需检查可用结构化 `skip_reason` 标成 `NOT_RUN`，必需测试不能靠静态检查通过来绕过。
- 只有父链每一层的当前 head 都具有可信审核者的有效批准、且没有当前修改请求时，子 PR 才能进入审查；发布前会重新检查，旧 SHA、已撤销批准和新增修改请求都会阻止合并。
- 显式关联 #60-#89 但目标分支或堆叠拓扑非法的 PR 会收到可操作的流程修改评论，不再被静默忽略。
- 仓库级 Windows runner `desktop-agent-luotianyi-review` 已注册并以当前用户启动，标签为 `self-hosted/Windows/X64/agent-luotianyi-review/codex-chatgpt-auth`；本机 Codex CLI 当前使用 ChatGPT 登录。
- 本地 review job 明确拒绝 API-key 环境变量，并通过 `codex exec --ephemeral --ignore-user-config --approve-for-me` 使用本地仓库、SPEC、开发规范和 workspace-write 测试环境。
- resolver 和 publisher 继续在 GitHub-hosted runner 运行；只有已经通过受信任触发者、同仓库 head、Issue #60-#89 和堆叠链门禁的候选才会派发到本机。
- PR #97—#99 已 squash merge 到 `master`；第三次真实 dispatch 暴露结构化输出 Schema 不兼容后，仓库变量 `AGENT_PR_REVIEW_ENABLED` 已恢复为 `false`，等待本修复合入后再开启复验。
- PR #100 已 squash merge 到 `master`；仓库变量 `AGENT_PR_REVIEW_ENABLED` 已重新设为 `true`。
- PR #102 已 squash merge 到 `dev`，工作流内部重新派发使用的可信 ref 已从 `master` 改为 `dev`；GitHub 默认分支随后切换为 `dev`。
- PR #103 已以普通 revert 提交 squash merge 到 `master`，撤销 #92、#96—#101 的自动审查文件，不改写历史；清理后 `master` 文件树与发布提交 `450c1a53` 无差异。
- 真实审查已读取固定 PR/Issue/SPEC 上下文，执行 focused/domain pytest、Ruff、`PersistPolicy` 公开身份检查和 `git diff --check`；所有记录的检查均通过，真实学歌、B 站/VCPedia、真实模型/TTS/GPU/设备测试未运行。
- publisher 已把 Standards finding 发布到 PR #90：新增公开 `src.domain.agent` interface 尚未同步到当前 domain interface 文档。PR 保持开放和 `CHANGES_REQUESTED`，证明失败结论不会触发合并。
- 原 Codex 桌面心跳轮询任务 `agent-pr` 已删除；后续由 GitHub PR 事件直接派发，不再定时轮询。

## 已验证

- `node --test .github/codex/tests/review-policy.test.js`：共 16 项通过，包括重新派发必须固定到 `dev` 的契约测试。
- `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/agent-refactor-review.yml`：通过。
- Workflow YAML、三个 `actions/github-script` 脚本和 Draft 2020-12 JSON Schema 静态解析：通过。
- `git diff --check`：通过。

静态配置、本地策略以及根 PR 的真实审查/拒绝合并链路已经通过；尚未验证的真实事件、PASS 合并和堆叠 PR 场景继续列在下节。

## 退役验证与残留

- GitHub 仓库变量 `AGENT_PR_REVIEW_ENABLED`：已删除。
- GitHub self-hosted runner `desktop-agent-luotianyi-review`：已从仓库注销，注销前确认空闲并在停止进程后变为 offline。
- 本机计划任务 `Codex Agent-LuoTianyi Review Runner`：已停止并注销。
- 本机专用 `Runner.Listener.exe`：已停止，未发现同目录下仍运行的 listener/worker。
- 仓库触发文件与专用 bundle：已在本分支删除，合入 `dev` 后不再存在 GitHub 事件入口。
- 本机目录 `C:\Users\A\.codex\github-runners\Agent-LuoTianyi-review`：仍保留不可运行的缓存、日志和已注销凭据文件；递归删除被当前命令策略拒绝。它没有计划任务、运行进程、GitHub 注册或仓库开关，不会继续触发审查。后续可由管理员手工删除该精确目录。
- 未修改仓库通用 Actions 权限、其他 runner、Agent 产品代码或 #107。
