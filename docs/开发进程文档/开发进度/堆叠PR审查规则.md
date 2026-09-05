# 堆叠 PR 审查规则

- 相关规范：[`开发守则`](../开发守则.md)、[`Spec、TDD 与小 PR 门禁`](../skills/spec-tdd-pr-guard/SKILL.md)、[`Agent 深模块 SPEC`](../设计文档/Agent-handle-realize-深模块重构.md)
- 当前阶段：流程规范
- 总体状态：进行中
- 最后更新：2026-09-05

## 本 PR

- PR：待创建（分支 `codex/stacked-pr-review-policy`，目标 `refactor/agent`）
- 目标：允许可追溯的父子堆叠 PR，同时保证完整候选最终只由根 PR 合入规定功能分支。
- 范围：定义根/子 PR、fixed point、合并顺序、旧批准失效、Draft/Ready 所有权，以及审查时跳过长耗时真实外部测试的规则；同步 Agent 深模块 SPEC。
- 明确不包含：不修改 Agent 产品 interface、实现、测试或 #90/#94 分支；不把 `dev`、`main`、`master` 变成 Agent 重构交付目标；不宣称真实学歌、B 站、LLM、TTS、GPU 或设备链路已验证。
- 验证及结果：三个相对 Markdown 链接均解析到现有文件；四个文档均无 Unicode replacement character，三个既有文档的 Markdown fence 数量均为偶数；`git diff --check` 通过；关键词静态检查确认根/子 PR、fixed point、重新审核、Draft/Ready 和长测试跳过规则均已同时写入通用门禁与 Agent SPEC。本 PR 为流程文档修改，未运行产品 pytest、真实学歌、B 站抓取或其他外部环境测试。

## 已完成

- [x] 确认“所有 PR 直接指向功能分支”会误拒合法的 Red→Green 堆叠审查。
- [x] 确认根 PR 仍需以规定功能分支为 base，子 PR 只能合入同一链的父 PR 分支。
- [x] 明确父 PR 接收子 PR 后必须以新 head 重新审核，旧批准不能沿用。
- [x] 明确 Draft/Ready 由作者维护，审核结论和合并由审核者负责。
- [x] 明确默认跳过真实学歌、B 站抓取和其他长耗时外部测试，并记录未验证项。

## 阻塞和未验证项

- GitHub 事件驱动审查工作流当前仍需同步支持堆叠 PR；该工作流位于默认分支，不能在本 PR 中跨目标分支混合提交。
- 本轮未运行真实外部服务或产品测试。

## 下一 PR

在默认分支单独更新 Agent PR 自动审查工作流，使其识别终止于 `refactor/agent` 的可信堆叠链，并以直接父 PR 为增量审查 fixed point。
