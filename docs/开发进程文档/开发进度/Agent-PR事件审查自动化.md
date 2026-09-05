# Agent PR 事件审查自动化开发进度

关联工单：[#93](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/93)

## 目标

在默认分支部署事件驱动的审查工作流，审查以 `refactor/agent` 为最终集成分支、且显式关联 Agent 深模块重构工单 #60-#89 的同仓库根 PR 与合法堆叠子 PR。审查覆盖流程/TDD、黑盒验证、Standards 和 Spec；失败时请求修改，通过时将子 PR squash merge 到直接父分支，或将根 PR squash merge 到 `refactor/agent`。

## 本 PR

- PR：[#96](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/96)（分支 `codex/stacked-pr-review-workflow`，目标 `master`，Ready，等待复审）
- 目标：让事件审查器识别并安全处理最终终止于 `refactor/agent` 的堆叠 PR 链。
- 范围：事件入口、堆叠链解析与固定、父 PR review 上下文、发布前链路复核、子/根 PR 合并目标、显式 `Issue #NN` 关联语法，以及长耗时外部测试的默认跳过规则。
- 明确不包含：不启用 `AGENT_PR_REVIEW_ENABLED`，不配置或读取 `OPENAI_API_KEY`，不修改 Agent 产品代码或 #90/#94 分支。
- Red：首轮新增策略测试时 5 项失败，其中显式 Issue 关联未识别，且 `resolvePullChain` 尚不存在；复审新增父层批准和 `NOT_RUN` 门禁测试时 2 项失败，分别证明批准门禁尚不存在、合法外部测试跳过会被误拒。
- Green：`node --test .github/codex/tests/review-policy.test.js` 为 12 项通过；两个 JavaScript 文件 `node --check` 通过；Workflow YAML 使用 PyYAML 解析通过；`git diff --check` 通过。当前环境没有 `actionlint`，该项未运行。

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
- 默认跳过真实学歌、B 站/VCPedia 实时抓取和其他长耗时外部测试，并把跳过项记录为未验证。
- 只有父链每一层的当前 head 都具有可信审核者的有效批准、且没有当前修改请求时，子 PR 才能进入审查；发布前会重新检查，旧 SHA、已撤销批准和新增修改请求都会阻止合并。
- 显式关联 #60-#89 但目标分支或堆叠拓扑非法的 PR 会收到可操作的流程修改评论，不再被静默忽略。

## 已验证

- `node --test .github/codex/tests/review-policy.test.js`：共 12 项通过。
- `actionlint .github/workflows/agent-refactor-review.yml`：未运行；当前环境未安装 `actionlint`。
- Workflow YAML、三个 `actions/github-script` 脚本和 Draft 2020-12 JSON Schema 静态解析：通过。
- `git diff --check`：通过。

上述结果只证明静态配置和本地策略行为，不代表 Secret-enabled 的 GitHub 真实事件链路已经通过。

## 待完成

- 在 GitHub 仓库 Secret 中配置 project-scoped `OPENAI_API_KEY`。
- 将 `AGENT_PR_REVIEW_ENABLED` 切换为 `true`。
- 以真实根 PR 和堆叠子 PR 分别验证：事件触发、父链解析、Codex 增量/完整审查、子 PR 合入父分支，以及根 PR 最终 squash merge 到 `refactor/agent`。
- 真实事件链路验收通过后，删除现有每 10 分钟轮询任务。

在以上待完成项完成前，本功能状态为“已部署但禁用，等待密钥与端到端验收”，不得标记为完成。
