# `call.v1` 共享通话契约与 deadline 前置验证

## 范围

本短切片只冻结 CL-6 / CL-8 / CL-9 紧接 lane 使用的领域值和 setup deadline 传递，不实现 CallStage、Agent handler、TTS CALL transport 或生产 capability。

## API 与 ownership

- `CallStartClaim.setup_deadline`：CL-5 producer，CL-6 consumer；同 request duplicate 复用首次 monotonic deadline，不写 SQL
- `CallInteractionSnapshot`：`domain.agent` 的正式 `InteractionSnapshot` 联合成员，未来 CallStage producer，现有 `HandleStimulusRequest` 真实校验 consumer
- `CallAnswerRequested` / `AnswerCall`：正式 Stimulus 与 Action，CallStage 请求接听，CL-8 Agent 通过计划返回 ACCEPT/DECLINE
- `CallStarted`：仅 ACTIVE 首次进入后由 CallStage 产生，不等同于接听请求
- `CallTurnCompleted`：携带正整数 `turn_seq` 和已归一化 `CallAudioSemantic`
- `CallSilenceElapsed`：CallStage 五秒资格计时完成后产生
- `CallTerminalFacts` + `CallFinalSnapshot` / `CallEnding`：snapshot 保存全部已完成用户轮次；每轮 `CallReplyStatus` 为 NOT_STARTED / COMPLETED / INTERRUPTED / FAILED，只有 COMPLETED 强制正式 Agent 文本，INTERRUPTED 可有或没有已形成文本，provisional 不进入结构
- `EndCall`：CL-8 Agent action，未来 CallStage 等最后播放结算后执行
- `CallSpeechDelivery`：CL-8 `Say` producer，真实 `Execution -> OutputEmitter -> AgentOutputSink` consumer 链已透传到全部 Text/Audio/End/Expression output。默认 CHAT；CALL 强制 hidden + ephemeral + response ID，可标 provisional

Agent 业务模型不携带 wire `seq` 或 `stream_id`；这些仍由 Adapter transport 分配。PCM 编码/采样率属于 transport stream registration，不进入 Agent 决策值。

## 时间边界

setup deadline 使用 monotonic clock，只存在于当前 runtime claim。ledger 的 `requested_at` 为 aware Beijing；未来 CallStage 调用 CL-2 legacy `create_call` 时必须显式转换为 naive Beijing，不使用宿主时区。

`StageManager.take_call_claim` 是未来 CallStage 的公开接管边界：校验 call/user/character/request/deadline 与当前 CALL lease，产生带 generation 的 `CallStageOwnership`。`current_call_ownership` 支持 duplicate 查询，`release_call` 只释放当前 generation 并清理 runtime deadline；consumer 不读取 manager 私有字典。

## 未实现

- CallStage 状态机与真实 stimulus producer
- Agent 接听/轮次/沉默/结束 handler
- Speaking Skill CALL delivery 与 transport stream registration
- provider、wire endpoint 和 App 完整接线
- 生产 capability 启用

## 当前验证

- domain realization / shared call contracts / plan identity + Say output metadata：132 passed
- CL-5 handoff deadline / take / release ownership：27 passed
- playback/lifecycle/TTS cancellation/provider config compatibility：38 passed
- Black、Ruff、架构边界与 `git diff --check` 以本轮最终命令为准
