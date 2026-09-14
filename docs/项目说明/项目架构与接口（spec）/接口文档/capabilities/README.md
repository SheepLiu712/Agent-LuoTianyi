# capabilities 对外接口

## 模块职责

`server/src/capabilities` 封装角色能执行的具体能力，例如语音、唱歌、图片理解、动态发布和日记生成。它回答“怎么做”，Agent 决定“何时做、为什么做”。目标架构中业务调用应由 Agent 转发。

## 当前对外接口

### `CapabilityManager`

- `wire_dependencies(...)`：注入数据库、模型和世界服务等依赖。
- `ensure_dependencies()`：检查各能力是否可用。
- `async stop()`：停止仍在运行的能力和后台资源。
- 属性 `speech`、`singing`、`image_understanding`、`media_resolver`、`dynamics`、`diary`：取得具体能力对象。它们是当前事实接口，但会扩大耦合面，新增代码应优先通过 Agent 使用。

### `MediaResolver`

- 端口位于 `server/src/capabilities/media_resolution/`；`resolve(media_ref: MediaRef) -> ResolvedMedia` 只接受名义 `media_id`，返回 `ResolvedMedia(data: bytes, mime_type: str)`，不把本地路径、URL、凭据或供应商对象送入 Agent。
- `ResolvedMedia` 是不可变值；解析是只读、可重复的操作。AgentRuntime 只把该窄端口注入图片认知技能，Handler 不直接访问 CapabilityManager、SystemRuntime 或存储。
- `FilesystemMediaResolver` 从配置的永久媒体根目录读取 `<media_id>/content.bin` 和 `metadata.json`；只接受 UUID 形式的 media_id，拒绝未知、空内容、非图片 MIME、损坏元数据和路径穿越。媒体引用永久有效，没有 TTL、过期或清理状态。
- `UnconfiguredMediaResolver` 仍是缺省实现：`ensure_dependencies()` 是无操作，`resolve()` 稳定抛出 `MEDIA_RESOLVER_NOT_CONFIGURED`，不会把缺少存储配置伪装成空内容成功。
- 当前错误分类为 `MEDIA_UNKNOWN`、`MEDIA_UNAUTHORIZED`、`MEDIA_EMPTY` 与 `MEDIA_UNSUPPORTED_TYPE`；图片技能在调用 VLM 前拒绝空内容和非 `image/*` MIME。

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
- MediaResolver 未配置、引用未知/未授权、内容为空或 MIME 非图片时明确失败；失败不进入图片理解能力。
- 停机时应调用 `CapabilityManager.stop()`，避免遗留后台任务和模型资源。

## 使用示例

假设 Agent 决定回复一句话并朗读：Agent 生成文字和语气后调用 `speech.say(...)`；stage 只接收可发送的结果。stage 不应自行选择 tone 或直接操作 TTS 模块，否则角色决策会散落到流水线中。

## 应覆盖的契约场景

- 语音成功、初始化失败、流式生成中断分别产生明确结果。
- 不可演唱歌曲返回 `None`，可演唱歌曲返回非空音频且歌词查询与片段一致。
- 同一日记来源重复调用不会重复发布；生成成功但发布失败时返回失败和原因。
- MediaResolver 的未配置、未知、未授权、空内容和非图片 MIME 均为稳定失败，且 VLM 不应在解析/校验失败后执行。

## 尚未解决的媒体存储策略

- 授权主体尚未选择：按用户、角色、二者组合或全局校验仍待书面决策。
- 大文件分块、大小限制和解析/理解超时上限尚未确定。
- 图片与语音是否长期复用同一解析端口尚未确定；当前没有接入 ASR。
- 已决定媒体永久保存且引用不失效；不执行 TTL、过期或自动清理。生产配置缺少媒体根目录时图片输入会明确失败，不产生不可解析的引用。

## 当前导出注意事项

`server/src/capabilities/__init__.py` 当前的导入与 `__all__` 不一致：实际导入了 `CapabilityManager`，但 `__all__` 中含未定义的 `CapabilityRegistry` 且漏掉 `CapabilityManager`。修复前不要把星号导入结果当成稳定协议。

## 目标接口（草案，待评审，未实现）

以下为 Issue #68（09 图片预处理落库）所需的**媒体引用解析**端口草案。**当前源码未实现**，不得按“当前接口”调用；确认后需同步本页、`system` 装配说明与总 SPEC 4.2。

### `MediaResolver`（对应 Issue #68）

```python
@dataclass(frozen=True)
class ResolvedMedia:
    data: bytes
    mime_type: str

class MediaResolver(Protocol):
    def resolve(self, media_ref: MediaRef) -> ResolvedMedia: ...
```

- **调用者**：Agent 的图片/语音理解技能（构造时注入）；Adapter 仍只把外部消息转成携带 `MediaRef` 的 Stimulus。
- **输入/输出**：名义 `media_id` → 编码字节与 MIME；**不返回**本地路径、URL 凭据或供应商对象。
- **副作用**：只读，无持久化、无网络写。
- **正常行为**：按 `media_id` 返回内容与 MIME。
- **异常行为**：未知 / 过期 / 未授权 → 稳定、可分类的错误；内容为空 → 明确失败，不静默返回空。
- **归属备选**：A. capabilities 提供并由 `SystemRuntime` 装配（倾向）；B. Adapter 解析后写受控缓存，Agent 只读引用；C. 预处理阶段外部解析落库。
- **未决问题**：授权主体（用户/角色）；TTL 与清理；大小/超时上限；图片与语音是否复用同一端口；解析失败时 09 的行为（按现行「不自动重试」应为 `FAILED/INTERNAL_ERROR` 并丢弃该输入）。

> 与 capabilities 现有 `image_understanding.describe_image(image_base64)` 的关系：`MediaResolver` 只负责“取到内容”，理解仍由 `image_understanding` 完成，二者不是同一职责。
