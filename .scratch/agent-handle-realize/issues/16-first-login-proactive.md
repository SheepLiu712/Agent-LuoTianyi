# 16: 迁移首次登录主动欢迎

**What to build:** 在登录认证和 ChatStage 建立完成后，把首次登录事实交给 Agent，通过两个公开接口按当前顺序发送并持久化两条带预制音频的欢迎消息，而不是由 ProactiveTopicMaker/stage 直接读取资源并构造回复。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心；07: 让 ChatStage 通过新 façade 处理输入协调信号。

**Status:** ready-for-agent

**GitHub Issue:** [#75](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/75)

## Decision rule

SPEC 第 5.2/5.3、8.5 节优先。欢迎文案、音频资源和历史同步延时只在 SPEC 留白时参考当前 ProactiveTopicMaker、登录调用链和配置；不得恢复 RETURN_LOGIN 或让 stage 生成角色内容。

## Architecture constraints

- 登录/提醒等主动刺激归 `agent/handlers/stimulus/proactive.py`；欢迎内容选择可调用 cognitive Skill，预制音频/表情输出仍由 communication Action Handler + execution Skill 实现。
- ChatStage 只拥有历史同步窗口、pending、claim 与输出路由，不读取角色资源、不导入 proactive Handler/Skill。
- 现有 ProactiveTopicMaker 只作为迁移源；角色内容逻辑迁走后不得作为 façade 外第二入口保留。

## Scope

- 登录认证记录 elapsed_from_last_login，等对应 user/character ChatStage ready 后构造首次登录 ProactivePromptDue。
- ProactiveContentHandler 选择配置中的两条欢迎内容和预制音频，产生两个有序 CONVERSATION Say 计划/Action。
- realization 持久化文字并发送 normal 表情、预制音频和 final package；约 1 秒同步窗口由 ChatStage 管理。
- request/execution 重投不得重复欢迎消息或持久记录。

## Acceptance criteria

- [ ] 仅 `elapsed_from_last_login is None` 触发首次欢迎；在 ChatStage ready 前不发送。
- [ ] 等待约 1 秒后按配置顺序发送两条，各自文字持久化一次、使用预制音频、表情 normal、final package 完整。
- [ ] delivery 为 CONVERSATION，不按触摸瞬时反应隐藏气泡或跳过记录。
- [ ] stage 不读取音频、不拼角色回复；内容决定和 realization 均在 Agent 内。
- [ ] 距上次登录大于等于 5 天仍不派发 RETURN_LOGIN。
- [ ] 重连/重投/并发首连接不重复创建 worker 或重复欢迎。
- [ ] 新生产链只依赖 domain 协议和 façade；主动 Handler 不依赖登录 session、WebSocket 或 ChatStage 实例。

## Verification

- 从认证后创建 ChatStage 的公开流程先写失败测试，使用可控时钟和 Fake output Adapter。
- 覆盖首次、非首次、五天以上、并发连接、历史同步时点、输出顺序和重投去重。
- 运行 proactive、chat lifecycle、Agent realization 和账户集成回归。

## Explicit exclusions

- 不处理当天首次登录的到期 event；由 17 号工单负责。
- 不改变客户端登录协议或欢迎资源内容。

## Handoff

一个首次登录纵向 PR；进度记录真实持久化/输出证据和未验证音频环境。
