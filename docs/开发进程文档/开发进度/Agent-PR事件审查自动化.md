# Agent PR 事件审查自动化开发进度

关联工单：[#93](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/93)

## 目标

在 GitHub 默认分支 `dev` 部署事件驱动的审查工作流，审查以 `refactor/agent` 为最终集成分支、且显式关联 Agent 深模块重构工单 #60-#89 的同仓库根 PR 与合法堆叠子 PR。审查覆盖流程/TDD、黑盒验证、Standards 和 Spec；失败时请求修改，通过时将子 PR squash merge 到直接父分支，或将根 PR squash merge 到 `refactor/agent`。`master` 仅用于已经验收的生产发布和必要热修复，不承载该开发自动化。

## 本 PR

- PR：[#104](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/104)（分支 `codex/record-pr-review-branch-migration`，目标 `dev`）
- 目标：记录默认分支迁移和发布分支清理的最终结果。
- 范围：只更新本进度文档，关联迁移 PR #102 和清理 PR #103 的验证事实。
- 明确不包含：不修改工作流、审查策略、Agent 产品代码、#90/#94 分支或本机 Runner 配置。
- 验证及结果：GitHub 默认分支为 `dev`；`dev` 上的 `Agent refactor PR review` 工作流为 active；`master` 当前文件树与自动化引入前的发布提交 `450c1a53` 无差异。

## 已完成

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

## 待完成

- 验证 Windows 重新登录后 runner 能由计划任务自动恢复在线；计划任务已经配置，本轮不为验证而重启用户会话。
- 下一次受信任开发者对相关 PR 提交 commit、Ready/Reopen、review 或评论回复时，确认对应事件会自动产生新运行；本轮已通过同一入口的 `workflow_dispatch` 验证完整执行链。
- 仍需以真实堆叠子 PR 验证父链增量审查和“子 PR squash 到直接父分支”路径；当前只完成根 PR 的审查与拒绝合并路径。
- 首个无阻塞根 PR 或堆叠子 PR 出现后，验证 PASS 会在发布前重新检查 head/base/父批准，并只合并到规则允许的目标。

当前功能状态为“已启用并通过根 PR 审查/拒绝合并链路验收”；上列自动重启、真实事件和 PASS/堆叠合并路径仍需随下一批实际 PR 验证，不能提前写成通过。
