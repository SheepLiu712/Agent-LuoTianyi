# Speaking 技能与 SAY 的 TTS 分支

## 装配

`agent/skills/expression/speaking.py` 提供 `SpeakingSkill(config, tts_engine)`。`Skills` 派发 `skills.speaking` 配置并注入 `AsyncTTS`；一个 AgentRuntime 的所有角色共享同一技能。私有 `_SpeakingConfig` 校验配置是字典，当前没有额外行为字段。

`AsyncTTS` 位于 `capabilities/speech/streaming.py`，复用 `SpeechCapability` 已初始化的角色 TTS 模块。它不创建、关闭共享模型或工作进程。角色声音、语调映射和参考音频沿用引擎配置。

AgentRuntime 为每个角色创建 `SayHandler`，注册到 `ActionKind.SAY`。刺激路由仍为空。

## 技能接口

```python
async def speak(
    self, *, character_id: str, text: str, tone: Tone,
    cancellation: CancellationToken,
) -> AsyncIterator[SpeakingAudioChunk]:
    ...
```

文本是朗读文本，角色 ID 决定使用哪个 TTS 模块。skill 不接收表情。每次调用只持有自己的流和取消信号。

`SpeakingAudioChunk` 包含 `data: bytes` 和 `framing: AudioFraming`。现有引擎输出可顺序拼接的 WAV 字节片段，标记为 `FILE_FRAGMENT`，不经过 Base64。零长度片段不交付；整个流没有有效音频时抛 `EmptySpeechError`。

调用方提前停止时使用 `contextlib.aclosing` 关闭流。技能内部同样显式关闭引擎流。

## 异步适配

同步生成器在工作线程创建、推进和关闭；每次只请求下一个片段，不提前合成并缓存后续片段。等待期间不会阻塞事件循环。

协作取消、任务取消和提前关闭都会设置本次请求的取消事件，等待正在执行的读取收尾后关闭生成器。等待引擎锁和工作进程响应支持该事件；响应队列读取最多等待一秒后重新检查。请求计数和合成锁在结束时释放。

单请求取消不关闭共享工作进程，也不保证立即终止已开始的模型计算。后续请求只消费自身请求 ID 的结果。

## SAY 处理

处理器只支持 `sound_content` 非空且无 `prepared_audio_ref` 的 TTS 分支。纯文字和预制音频分支在产生输出前返回 `UNSUPPORTED_ACTION`。

正常输出顺序：

1. 使用 `content` 生成显示文字。
2. 有 `expression` 时输出一次该表情。
3. 使用 `sound_content`、`tone` 调用 skill，逐块交付音频。
4. 输出 `MessageEndOutput(COMPLETED)`。

所有输出绑定同一 action_id，序号由 OutputEmitter 分配。消息终止不表示客户端播放完成。SAY 结束不恢复表情。

空音频发送 FAILED/EMPTY_AUDIO 终止，并返回 AUDIO_EMPTY；生成异常发送 FAILED/GENERATION_FAILED 终止，并返回 AUDIO_GENERATION_FAILED，超时返回 PROVIDER_TIMEOUT。已交付的音频不回滚，后续行动停止。

接收器失败直接向执行流程传播，不再追加终止或表情输出。协作取消停止交付并返回 CANCELLED；任务取消完成流清理后传播 CancelledError。当前 emitter 在令牌取消后拒绝继续交付，因此取消路径不发送补充终止包。
