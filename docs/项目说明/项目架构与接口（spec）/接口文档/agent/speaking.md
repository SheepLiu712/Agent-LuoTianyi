# Speaking 技能与 SAY 音频分支

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

处理器在 `realize` 中按音频来源派发：有 `prepared_audio_ref` 时调用 `_realize_prepared`，否则有 `sound_content` 时调用 `_realize_tts`。纯文字分支在产生输出前返回 `UNSUPPORTED_ACTION`。

呈现方式统一由 `_emit_presentation` 处理：`CONVERSATION` 在显示文字非空时输出 `TextFinalOutput`；`EPHEMERAL_REACTION` 不输出文字，即使 action.content 非空。两者均可输出表情、音频和终止标记，每个输出保留 action.delivery。SAY handler 不写会话数据库，客户端协议映射由下游输出接收器负责。

正常输出顺序：

1. 根据 delivery 和 content 决定是否输出显示文字。
2. 有 `expression` 时输出一次该表情。
3. 使用 `sound_content`、`tone` 调用 skill，逐块交付音频。
4. 输出 `MessageEndOutput(COMPLETED)`。

所有输出绑定同一 action_id，序号由 OutputEmitter 分配。消息终止不表示客户端播放完成。SAY 结束不恢复表情。

空音频发送 FAILED/EMPTY_AUDIO 终止，并返回 AUDIO_EMPTY；生成异常发送 FAILED/GENERATION_FAILED 终止，并返回 AUDIO_GENERATION_FAILED，超时返回 PROVIDER_TIMEOUT。已交付的音频不回滚，后续行动停止。

接收器失败直接向执行流程传播，不再追加终止或表情输出。协作取消停止交付并返回 CANCELLED；任务取消完成流清理后传播 CancelledError。当前 emitter 在令牌取消后拒绝继续交付，因此取消路径不发送补充终止包。

## 预制音频资源

`AgentRuntime` 使用 `agent_runtime.prepared_speech` 配置初始化 `PreparedSpeechResources`，注入各角色的 `SayHandler`。私有配置类只解析 `manifest`；未配置时资源目录为空。

资源目录初始化只读取 manifest 元数据并检查路径，不读取音频内容。`get(name)` 返回资源描述；描述的空表情已解释为 normal。计划创建方将文字、表情写入 Say，执行方使用已经确定的 action.content 和 action.expression，不用当前资源描述覆盖计划。

`Say.prepared_audio_ref.media_id` 对应 manifest 中的 `name`，不是任意文件路径或网络 URI。执行时调用 `read_audio(name)` 在工作线程中读取文件，重新验证路径仍在资源根目录内，并验证 WAV 包含完整的非空音频帧。第一版支持完整 WAV 文件，以 `COMPLETE_FILE` 输出，不缓存音频内容。

预制音频在投递任何消息内容前完成读取：资源不存在、文件损坏或不可读返回 AUDIO_GENERATION_FAILED；空文件或零音频帧返回 AUDIO_EMPTY。由于尚未开始消息，不发送终止包。成功读取后按 delivery 输出文字和表情，然后交付一个完整音频文件及 COMPLETED 终止标记。

读取期间取消时等待本次文件操作收尾，并在投递前再次检查取消状态。交付失败后不追加音频、终止或表情恢复。
