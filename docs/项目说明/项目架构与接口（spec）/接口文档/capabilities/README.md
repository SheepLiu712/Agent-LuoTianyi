# capabilities 对外接口

## 模块职责

`server/src/capabilities` 封装角色能执行的具体能力，例如语音、唱歌、图片理解、动态发布和日记生成。它回答“怎么做”，Agent 决定“何时做、为什么做”。目标架构中业务调用应由 Agent 转发。

## 当前对外接口

### `CapabilityManager`

- `wire_dependencies(...)`：注入数据库、模型和世界服务等依赖。
- `ensure_dependencies()`：检查各能力是否可用。
- `async stop()`：停止仍在运行的能力和后台资源。
- 属性 `speech`、`singing`、`image_understanding`、`dynamics`、`diary`：取得具体能力对象。它们是当前事实接口，但会扩大耦合面，新增代码应优先通过 Agent 使用。

### `SpeechCapability`

- `await say(character, text, tone) -> str`：生成 Base64 编码的完整语音。
- `say_stream(character, text, tone) -> Generator[str]`：生成 Base64 编码的语音块。
- `request_stop()`：请求停止当前生成。
- `stop()`：释放语音相关资源。

兼容接口还包括 `TTSModule`、`TTSServer` 和 `init_tts_module(...)`。

### `SingingCapability`

- `await build_sing_plan(...)`、`resolve_sing_plan(...)`：建立并解析演唱计划。
- `can_i_sing_song(song_name)`、`get_songs_can_sing()`：查询歌曲可用性。
- `sing(song_name, segment) -> bytes | None`：取得演唱音频。
- `get_segment_lyrics(...)`、`get_full_lyrics(...)`：取得歌词。
- 歌曲重载、标签和模型辅助选择方法：维护当前曲库和选择结果。

### `ImageUnderstanding`

- `await describe_image(image_base64, **kwargs) -> str`：调用视觉模型生成图片描述。

### `DynamicCapability`

- `publish_agent_dynamic(...)`、`await publish_citywalk_dynamic(...)`、`await publish_learned_song_dynamic(...)`：发布不同来源的动态。
- `publish_agent_comment(...)` 以及世界内容生成相关方法：生成内容并写入动态存储。

### `DiaryCapability`

- `await generate_and_post_diary(...) -> tuple[bool, str, data | None]`：生成日记并尝试发布，返回是否成功、说明和结果数据。

## 正常与异常行为

- 语音、唱歌和图片理解可能进行网络请求、GPU 推理、文件读写并消耗较长时间。
- 动态和日记能力会写数据库或调用外部平台，调用方必须把“生成成功”和“发布成功”区分开。
- `sing` 返回 `None` 表示没有可用音频；模型、网络、配置或资源错误可能抛出异常。
- `say_stream` 的错误可能在迭代期间发生。
- 停机时应调用 `CapabilityManager.stop()`，避免遗留后台任务和模型资源。

## 使用示例

假设 Agent 决定回复一句话并朗读：Agent 生成文字和语气后调用 `speech.say(...)`；stage 只接收可发送的结果。stage 不应自行选择 tone 或直接操作 TTS 模块，否则角色决策会散落到流水线中。

## 应覆盖的契约场景

- 语音成功、初始化失败、流式生成中断分别产生明确结果。
- 不可演唱歌曲返回 `None`，可演唱歌曲返回非空音频且歌词查询与片段一致。
- 同一日记来源重复调用不会重复发布；生成成功但发布失败时返回失败和原因。

## 当前导出注意事项

`server/src/capabilities/__init__.py` 当前的导入与 `__all__` 不一致：实际导入了 `CapabilityManager`，但 `__all__` 中含未定义的 `CapabilityRegistry` 且漏掉 `CapabilityManager`。修复前不要把星号导入结果当成稳定协议。
