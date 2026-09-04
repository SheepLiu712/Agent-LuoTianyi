# 30: 完成两接口架构与全部现有链路的集成验收

**What to build:** 从外部入口和可控 WorldClock 对最终架构做一次独立验收，证明聊天、触摸、登录主动发言、九类 world action、幂等/取消/Reflection 和架构收束同时满足 SPEC，并把文档与验证事实更新到可合并状态。

**Blocked by:** 26: QQ 音乐凭据刷新；27: B 站事件同步；28: 过期事件清理；29: Contract 阶段删除旧 Agent 业务入口与所有旁路。

**Status:** ready-for-agent

**GitHub Issue:** [#89](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/89)

## Decision rule

SPEC 第 8 节全部条款是验收清单，不能以各子工单已完成替代端到端证据。差异优先按 SPEC 判断；SPEC 留白时才查最终分支当前行为和开发规范。发现行为冲突时创建/重开对应缺陷切片，不在验收 PR 中塞入大修复。

## Scope

- 运行/补齐从公开两接口、聊天入口、触摸入口、登录流程、WorldStage 和可控 WorldClock 观察的集成/少量 e2e 证据。
- 逐项核对 A1—A8、聊天全部信号、超时、重新思考、部分消费、触摸、首次/当日登录和提醒 claim。
- 逐项触发九类 clock action，区分纯机械任务和需要角色认知的目标链，并核对所有外部效果。
- 汇总真实网络、LLM、TTS、唱歌模型、GPU、设备和生产环境尚未完成的人工验收，不用 Fake 宣称通过。
- 更新项目架构、模块 interface、SPEC 状态和开发进度；准备但不代替功能分支最终评审。

## Acceptance criteria

- [ ] 公开 façade、依赖扫描和运行时对象图证明只有两个 Agent 业务 interface 且无内部泄漏。
- [ ] 聊天文本/图片/语音/协调信号、deadline、旧 revision、慢 Recall、多计划、显式记忆和 Reflection 证据全部通过。
- [ ] 触摸快速/回退、登录首次/当日/重复、周期提醒 claim 和持久化语义全部通过。
- [ ] 九类 WorldClock action 的调度、skip/failure、去重、持久效果和 Agent 边界逐项有结果；`ensure_holidays()` 不误计。
- [ ] request/execution/reflection 重投不产生重复回复、记忆、动态、日记、日程、事件或学歌任务。
- [ ] 默认 Server 回归通过；真实依赖未验证项明确列出，不使用“全部通过”模糊表述。
- [ ] SPEC、架构/interface 文档和进度只陈述已实现/已验证事实。

## Verification

- 先以缺失的 SPEC 第 8 节证据写失败验收测试；已有测试可复用但不得只测私有实现。
- 运行 focused → integration → 默认 Server 回归；记录命令、收集数、通过/跳过/失败和环境。
- 对真实依赖建立逐项人工清单，保留可复核输出且不记录密钥/隐私数据。

## Explicit exclusions

- 不在验收 PR 中增加新 Stimulus/Action/interface 或顺便实现 Call/Realtime。
- 不直接发布版本、不推送 GitHub Issue 状态，除非用户另行授权。

## Handoff

这是最终验收 PR；只有所有自动化与明确列出的人工门槛满足后，进度才能标为已完成。
