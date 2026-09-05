# Agent PR 事件审查自动化开发进度

关联工单：[#93](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/93)

## 目标

在默认分支部署事件驱动的审查工作流，审查以 `refactor/agent` 为最终集成分支、且显式关联 Agent 深模块重构工单 #60-#89 的同仓库根 PR 与合法堆叠子 PR。审查覆盖流程/TDD、黑盒验证、Standards 和 Spec；失败时请求修改，通过时将子 PR squash merge 到直接父分支，或将根 PR squash merge 到 `refactor/agent`。

## 本 PR

- PR：[#98](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/98)（分支 `codex/local-agent-pr-review-checkout-fix`，目标 `master`）
- 目标：修复真实 workflow dispatch 在 GitHub-hosted resolver 的 checkout 清理阶段失败。
- 范围：移除三个 job 的 `actions/checkout`；resolver/publisher 通过 GitHub API 读取固定 workflow SHA 的策略文件，本机 review 在 `RUNNER_TEMP` 原生获取固定 base/head/workflow commit；保留 ChatGPT 登录、本地测试和既有审查/合并门禁。
- 明确不包含：不使用或配置 `OPENAI_API_KEY`/`CODEX_API_KEY`，不修改 Agent 产品代码、#90/#94 分支、工单范围或测试通过规则。
- 验证及结果：首次真实 dispatch [run 33961947804](https://github.com/SheepLiu712/Agent-LuoTianyi/actions/runs/33961947804) 在 resolver 的 checkout 认证清理阶段失败，原因是历史 `mineflayer` gitlink 没有 `.gitmodules` URL；review/publish 均未运行，未消耗 Codex 用量或合并 PR。修复后待重新运行静态检查与真实 dispatch；验证期间保持 #90 的人工 `CHANGES_REQUESTED` 合并门禁。

## 已完成

- 建立新建、更新、重新打开、Ready、retarget、review 提交/编辑/撤销、普通评论和行内评论事件入口。
- 在付费调用前限制目标分支、工单范围、同仓库 head 和 write/maintain/admin 触发者。
- 将候选 target base 与 PR head 同时固定，构造并测试对应的候选集成树。
- 将 API Key 所在的只读审查 job 与拥有 GitHub 写权限的发布 job 分离。
- 发布前独立校验完整输出契约、工单集合、base/head SHA、PASS 测试证据、P0/P1 finding 和人工 review 最新状态。
- 将核心合并策略提取到 `.github/codex/scripts/review-policy.js`，并增加 Node 内建测试。
- 将第三方 Actions 固定到已核验的提交 SHA；同一次运行的三个 job 使用同一个 `github.workflow_sha` 读取可信策略。
- 仓库已允许 GitHub Actions 创建 PR review；变量 `AGENT_PR_REVIEW_ENABLED` 已创建并保持为 `false`。
- 支持根 PR 直接指向 `refactor/agent`，以及同仓库开放父 PR 组成、最终终止于该根 PR 的无环堆叠链。
- 子 PR 使用直接父 PR 的固定 head 作为审查基线，只能合入父分支；父 PR 更新后必须触发新的完整候选审查。
- 默认跳过真实学歌、B 站/VCPedia 实时抓取和其他长耗时外部测试；仅非必需检查可用结构化 `skip_reason` 标成 `NOT_RUN`，必需测试不能靠静态检查通过来绕过。
- 只有父链每一层的当前 head 都具有可信审核者的有效批准、且没有当前修改请求时，子 PR 才能进入审查；发布前会重新检查，旧 SHA、已撤销批准和新增修改请求都会阻止合并。
- 显式关联 #60-#89 但目标分支或堆叠拓扑非法的 PR 会收到可操作的流程修改评论，不再被静默忽略。
- 仓库级 Windows runner `desktop-agent-luotianyi-review` 已注册并以当前用户启动，标签为 `self-hosted/Windows/X64/agent-luotianyi-review/codex-chatgpt-auth`；本机 Codex CLI 当前使用 ChatGPT 登录。
- 本地 review job 明确拒绝 API-key 环境变量，并通过 `codex exec --ephemeral --ignore-user-config --sandbox workspace-write --approve-for-me` 使用本地仓库、SPEC、开发规范和测试环境。
- resolver 和 publisher 继续在 GitHub-hosted runner 运行；只有已经通过受信任触发者、同仓库 head、Issue #60-#89 和堆叠链门禁的候选才会派发到本机。
- PR #97 已 squash merge 到 `master`；首次真实 dispatch 暴露 checkout 兼容问题后，仓库变量 `AGENT_PR_REVIEW_ENABLED` 已恢复为 `false`，等待本修复合入后再开启复验。

## 已验证

- `node --test .github/codex/tests/review-policy.test.js`：共 12 项通过。
- `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/agent-refactor-review.yml`：通过。
- Workflow YAML、三个 `actions/github-script` 脚本和 Draft 2020-12 JSON Schema 静态解析：通过。
- `git diff --check`：通过。

上述结果只证明静态配置和本地策略行为，不代表 Secret-enabled 的 GitHub 真实事件链路已经通过。

## 待完成

- 将本 PR 合入默认分支后，把 `AGENT_PR_REVIEW_ENABLED` 切换为 `true`。
- 验证 Windows 重新登录后 runner 能由计划任务自动恢复在线；计划任务已经配置，本轮不为验证而重启用户会话。
- 以真实根 PR 和堆叠子 PR 分别验证：事件触发、父链解析、Codex 增量/完整审查、子 PR 合入父分支，以及根 PR 最终 squash merge 到 `refactor/agent`。
- 真实事件链路验收通过后，删除现有每 10 分钟轮询任务。

在以上待完成项完成前，本功能状态为“runner 已注册、工作流迁移中且仍禁用，等待端到端验收”，不得标记为完成。
