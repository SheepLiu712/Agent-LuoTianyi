# 26: 保持 QQ 音乐凭据刷新为纯机械 world 任务

**What to build:** 在 Agent/WorldStage 重构期间保护 `qq_music_credential_refresh` 的当前调度、凭据路径去重、skipped/failure/success 语义，并证明该任务不产生 Stimulus、不调用 Agent。

**Blocked by:** 03: 冻结 WorldClock 调度与九类注册基线。

**Status:** ready-for-agent

**GitHub Issue:** [#85](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/85)

## Decision rule

SPEC 第 4.1、6.7、8.6 的 QQ 凭据行优先。凭据文件、提前刷新阈值和返回数据不清时参考当前 credential refresh task、learner 配置和测试；凭据内容/路径不得进入日志、Stimulus 或 Agent context。

## Scope

- 保持仅在存在学歌任务且配置启用时注册，每 21600 秒执行并在启动时立即运行。
- 对实际被学歌任务使用的凭据文件按规范化路径去重，检查/刷新一次。
- 没有初始化凭据时 skipped；任一角色失败时 failure 并列出受影响角色；全部可用时报告成功计数。
- 移除重构中误加的 Agent/WorldStage 依赖，保持纯基础设施边界。

## Acceptance criteria

- [ ] 相同规范化凭据路径只刷新一次，不因多个角色重复访问供应商。
- [ ] 无学歌任务时不注册；无已初始化凭据时 skipped 而非伪成功。
- [ ] 部分失败结果准确包含角色列表且不泄漏凭据或签名 URL。
- [ ] 调度 6 小时、run_immediately=true 和后续周期保持。
- [ ] 任务没有 Stimulus、ActionPlan、AgentRuntime/CharacterRuntime 调用。
- [ ] 一次失败不停止后续周期或其它 clock action。

## Verification

- 优先补/迁移 world task 回归测试，Fake 凭据 provider 和多角色共享路径。
- 覆盖未注册、skipped、共享路径、成功、部分失败、异常隔离和日志脱敏。
- 运行 credential、learn-song、WorldClock/WorldRuntime 回归；不访问真实账户。

## Explicit exclusions

- 不改变凭据格式、购买/登录流程或学歌任务行为。
- 不把刷新结果转成角色可感知事件。

## Handoff

一个纯机械任务保护 PR；若现有实现已满足，记录“回归测试首次 Green，无 Red”。
