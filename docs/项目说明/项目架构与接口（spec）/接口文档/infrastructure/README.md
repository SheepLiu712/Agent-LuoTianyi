# infrastructure 对外接口

## 模块职责

`server/src/infrastructure` 封装共享的外部模型、协议、文件与资源生命周期。它不决定角色为何或何时使用资源，也不保存当前角色/用户业务上下文。

## `InfrastructureRuntime`

由 `SystemRuntime` 创建一次，配置根为 `infrastructure`。它拥有：

- `speech: SpeechBackend`：角色语音后端和 TTS worker 生命周期；
- `singing: SingingBackend`：按角色 ID 选择歌曲资源、歌词和音频；
- `image_understanding: ImageUnderstanding`：VLM 图片描述适配器；
- `media_resolver: MediaResolver`：按认证用户解析并校验持久媒体；
- `async stop()`：幂等关闭拥有的语音资源。

`AgentRuntime` 只把所需窄对象注入 `SharedSkills`。Handler、Stage 与 World 不得通过 `InfrastructureRuntime` 取得任意服务。

## 关键端口

### `MediaResolver`

`resolve(media_ref, *, owner_user_id) -> ResolvedMedia` 接受名义媒体引用和认证用户，返回不可变的字节/MIME 值。文件系统实现校验所有权、大小、路径、元数据、真实图片格式与声明 MIME；失败时不调用 VLM。

### `SpeechBackend` / `AsyncTTS`

语音后端管理按角色配置的 TTS 模块和共享 worker。`AsyncTTS.stream(...)` 把同步生成器适配为请求可取消的异步字节流；取消本次流不关闭共享后端。

### `SingingBackend`

按显式 `character_id` 查询曲库、选择唱段、读取歌词和音频，并提供歌曲重载与情绪标签能力。角色要不要唱、唱什么以及缺歌后的行动属于 Agent Skill。

## 生命周期与失败

- 配置或模型初始化失败必须回滚已创建的拥有资源。
- `stop()` 成功后幂等；失败保留可重试状态，不假装已经关闭。
- 基础设施错误可以向 Skill 抛出明确异常，但不得自行生成角色话术或修改角色记忆。
