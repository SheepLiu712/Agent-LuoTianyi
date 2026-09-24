# 03: 冻结 WorldClock 调度与九类注册基线

**What to build:** 用公开 WorldClock/WorldRuntime 行为测试冻结当前调度、注册、失败隔离和关闭语义，为后续多人迁移九类 world task 提供不会漂移的共同基线；如果现有行为已满足，形成回归证据而不是制造伪 Red。

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**GitHub Issue:** [#62](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/62)

## Decision rule

SPEC 第 4.4、8.6、8.7 节的任务清单与语义优先。调度默认值不清时读取当前生效配置、WorldRuntime 组装和各 WorldTask 的 `clock_config`；开发守则要求既有实现测试首次即通过时明确记录“补回归，无 Red 证据”。不得把 `ensure_holidays()` 误列为 clock action。

## Scope

- 从实际 WorldRuntime 任务集合证明九类 action 名称、角色展开规则和启用条件与 SPEC 一致。
- 冻结 daily 使用服务器本地时间、interval 的 `run_immediately`、同名替换、单次错误隔离和后续周期继续。
- 冻结 shutdown 对已拥有任务的取消/等待及同步任务仍在运行时的明确失败。
- 为后续任务迁移提供可控时钟/Fake task seam，但不改变 world task 业务。

## Acceptance criteria

- [ ] 注册清单逐项包含 citywalk、VCPedia、新歌学习、QQ 凭据、B 站事件、主动提醒、动态互动、日记和过期事件清理，并正确处理 per-character/global 差异。
- [ ] 当前 04:00、00:00、300/600/21600 秒及立即运行配置由生效配置驱动，测试不把产品值复制为另一套实现常量。
- [ ] 一个 action 抛错不会停止其他 action 或自己的下一周期；同名重新注册不产生双循环。
- [ ] shutdown 成功与仍有同步工作未停止可以被区分。
- [ ] `ensure_holidays()` 只作为启动初始化被记录，不出现在 WorldClock 注册断言中。

## Verification

- 优先补现有 world/system 公共 seam 的回归测试；使用可控时钟和 Fake action，默认测试不访问网络、真实数据库或模型。
- 记录测试第一次是 Red 还是既有行为下 Green，并运行 WorldClock/WorldRuntime 相关回归。

## Explicit exclusions

- 不迁移任何任务到 Agent/WorldStage，不修改任务输出和当前配置。
- 不创建 GitHub Issue 或开始 20—28 号任务的实现。

## Handoff

提交测试、必要的最小可测试性 prefactor 和进度更新；任何行为改动都必须先回到 SPEC 评审。
