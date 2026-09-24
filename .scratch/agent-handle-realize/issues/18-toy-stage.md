# 18: 实现 ToyStage 设备事实、振动与动作输出

**What to build:** 建立 ToyStage 持续交互，使去抖后的 ToyVibration、DeviceConnected/Disconnected 和可选文字/语音/触摸能通过 Agent 两接口处理，并让 PerformMotion 经设备 output Adapter 实现。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；06: 实现 realization、Execution Ledger 与 Say 输出核心。

**Status:** ready-for-agent

**GitHub Issue:** [#77](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/77)

## Decision rule

SPEC 第 3、4.1—4.2、5.2/5.3、6.3—6.5 节优先。当前没有设备实现的行为不得凭空猜测；只在已有玩偶/设备 Adapter、协议或测试能证明时补充。若需要新外部协议或 AgentOutput kind，先修订 SPEC。

## Architecture constraints

- `ToyVibration`、`DeviceConnected/Disconnected` 归 `agent/handlers/stimulus/device.py` 行为族；TouchInteraction 仍走独立 touch Handler。原始采样、去抖和供应商协议留在 Adapter。
- 设备相关角色理解复用 cognitive Skill；PerformMotion 由 `agent/handlers/action/motion.py` 与 typed execution Skill 实现，Agent 不接触硬件 SDK。
- ToyStage 只依赖 domain 协议和 façade，拥有 pending/revision/cancellation/output sink；不得导入 Agent context、Handler 或 Skill。

## Scope

- ToyStage 按 interaction/device 维护 pending、revision、取消、输出能力和持续接触快照，不建立通用 BaseStage。
- Adapter 在 Agent 前完成采样去抖/聚合，形成 ToyVibration、DeviceConnected、DeviceDisconnected 或 TouchInteraction。
- Device/Touch Handler 使用共享注意力 Skill；需要独立动作时产生 PerformMotion，由 realization 输出 MOTION。
- device output sink 校验 supported outputs、顺序、背压和断开；Agent 不接触硬件 SDK。

## Acceptance criteria

- [ ] 高频原始传感器采样不会一对一进入 Agent，100 次采样按设备规则聚合为有限 Stimulus。
- [ ] connect/disconnect/vibration 字段与 ToyInteractionSnapshot 完整且不含供应商对象。
- [ ] 设备不支持某输出时 sink 明确拒绝，Agent 不自行降级为未知硬件命令。
- [ ] PerformMotion 是独立 Action；表情仍只能嵌入 Say/Sing；没有 HAPTIC 输出。
- [ ] 断开先由 ToyStage/Adapter 停止即时输出并递增 revision，再取消过期 handle/realization。
- [ ] 同一角色的不同设备/interaction 上下文不串用。
- [ ] device 与 touch 行为族边界清晰；Handler 不接触原始采样/SDK，motion execution Skill 不反向依赖 ToyStage。

## Verification

- 从 ToyStage/设备 Adapter seam 先写失败测试，使用 Fake 设备 SDK 和可控采样流。
- 覆盖去抖、能力协商、断开竞态、输出拒绝、motion 成功/失败和多设备隔离。
- 运行 Agent、stage、Adapter 和设备相关回归；真实硬件另列人工验收。

## Explicit exclusions

- 不实现 Call/Realtime，不新增 haptic。
- 无当前设备协议证据的能力保持未实现，不用通用 payload 预留。

## Handoff

一个 Toy 纵向 PR；PR 明确自动化覆盖与真机未验证边界。
