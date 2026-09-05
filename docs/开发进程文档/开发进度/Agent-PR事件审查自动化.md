# Agent PR 事件审查自动化开发进度

关联工单：[#93](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/93)

## 目标

在默认分支部署事件驱动的审查工作流，审查目标为 `refactor/agent`、且显式关联 Agent 深模块重构工单 #60-#89 的同仓库 PR。审查覆盖流程/TDD、黑盒验证、Standards 和 Spec；失败时请求修改，通过时 squash merge 到 `refactor/agent`。

## 已完成

- 建立新建、更新、重新打开、Ready、retarget、review 提交/编辑/撤销、普通评论和行内评论事件入口。
- 在付费调用前限制目标分支、工单范围、同仓库 head 和 write/maintain/admin 触发者。
- 将候选 target base 与 PR head 同时固定，构造并测试对应的候选集成树。
- 将 API Key 所在的只读审查 job 与拥有 GitHub 写权限的发布 job 分离。
- 发布前独立校验完整输出契约、工单集合、base/head SHA、PASS 测试证据、P0/P1 finding 和人工 review 最新状态。
- 将核心合并策略提取到 `.github/codex/scripts/review-policy.js`，并增加 Node 内建测试。
- 将第三方 Actions 固定到已核验的提交 SHA；同一次运行的三个 job 使用同一个 `github.workflow_sha` 读取可信策略。
- 仓库已允许 GitHub Actions 创建 PR review；变量 `AGENT_PR_REVIEW_ENABLED` 已创建并保持为 `false`。

## 已验证

- `node --test .github/codex/tests/review-policy.test.js`：5 项通过。
- `actionlint .github/workflows/agent-refactor-review.yml`：通过。
- Workflow YAML、三个 `actions/github-script` 脚本和 Draft 2020-12 JSON Schema 静态解析：通过。
- `git diff --check`：通过。

上述结果只证明静态配置和本地策略行为，不代表 Secret-enabled 的 GitHub 真实事件链路已经通过。

## 待完成

- 在 GitHub 仓库 Secret 中配置 project-scoped `OPENAI_API_KEY`。
- 将 `AGENT_PR_REVIEW_ENABLED` 切换为 `true`。
- 以一个真实、同仓库、目标为 `refactor/agent` 且关联 #60-#89 的 PR 验证：事件触发、Codex 审查、失败 review 或通过后的 squash merge。
- 真实事件链路验收通过后，删除现有每 10 分钟轮询任务。

在以上待完成项完成前，本功能状态为“已部署但禁用，等待密钥与端到端验收”，不得标记为完成。
