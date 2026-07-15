# 唱歌能力优化实现说明

## 范围

本次实现分三阶段完成：唱歌段落去重与最终可唱性校验、歌曲及对话情绪标签、学歌阶段的歌手安全校验。

## 行为摘要

### 1. 段落去重与最终校验

- `ChatStream` 持有 `deque(maxlen=10)`，记录最近实际生成音频的 `(歌名, 段落名)`。
- 队列和 `ChatStream` 同生命周期，因此 WebSocket 在 600 秒保留期内重连时会继续复用队列；销毁后自然清空。
- 规划歌曲时优先排除队列中的段落；明确指定歌曲时，如果所有段落都在队列中，则允许突破去重。
- 队列只在 `GlobalSpeakingWorker` 确认生成出非空歌曲音频后更新，规划失败或音频失败不会污染队列。
- Agent 最终回复要求唱歌时重新调用 `resolve_sing_plan` 校验歌曲和段落；不可唱时只删除唱歌动作，文字和其他动作仍正常执行。

### 2. 歌曲情绪与随机选歌

- 情绪标签固定为：`甜美`、`温柔`、`积极`、`帅气`、`搞怪`、`伤感`、`愤怒`，允许多标签。
- 学完歌曲后，使用完整歌词调用 `song_emotion_tagger`，结果写回歌曲 JSON 的 `emotion_tags` 字段。
- 随机唱歌时，以未压缩的最近对话、当前 topic 为上下文，由同一模块生成目标情绪标签，再优先从有交集的歌曲中随机选择。
- 低气压语境的提示词偏向 `温柔`、`积极`、`甜美`，避免继续选择压低情绪的歌曲；如果模块不可用或没有匹配标签，则回退到普通随机选择。
- 旧歌曲可使用批处理脚本重新标注：

```powershell
conda run -n lty python server/scripts/music/tag_song_emotions.py --config server/config/config.json
```

### 3. 学歌歌手安全校验

- 学歌下载入口检查 QQ 音乐返回的完整结构化歌手列表，而不是只使用第一位歌手。
- 仅当歌手列表非空且只包含目标歌手“洛天依”时才允许下载和进入后续学习流水线。
- 合唱歌曲、包含其他已知虚拟歌手（`洛天依`、`乐正绫`、`言和`、`星尘`、`诗岸`中除目标外的歌手）或未知歌手的歌曲都会被直接拒绝。
- 校验发生在创建输出目录和下载音频之前，确保不会把其他歌手的声音带入歌曲库。

## 主要修改位置

| 文件 | 作用 |
|---|---|
| `server/src/chat_session/chat_pipeline/chat_stream.py` | 保存最近唱过的段落 |
| `server/src/chat_session/chat_pipeline/topic_replier.py` | 传递去重/情绪上下文，最终校验唱歌动作，接收音频生成回调 |
| `server/src/chat_session/dependency/global_speaking_worker.py` | 在实际歌曲音频生成后触发记录 |
| `server/src/capabilities/singing/singing.py` | 唱歌计划、歌曲解析和情绪标注能力 |
| `server/src/capabilities/singing/singing_manager.py` | 段落排除、情绪标签存取和匹配选歌 |
| `server/src/capabilities/singing/song_emotion_tagger.py` | 歌曲情绪和目标情绪的 LLM 模块 |
| `server/src/world/learn_sing_songs/task.py` | 新学歌曲自动标注情绪 |
| `server/scripts/music/tag_song_emotions.py` | 旧歌曲批量标注 |
| `server/src/world/learn_sing_songs/song_learner/src/pipeline/download_qq_song.py` | 下载前的完整歌手校验 |
| `server/res/agent/prompts/song_emotion_prompt.json` | 情绪标注与目标情绪提示词 |

## 配置结构

`capabilities.sing` 只在模块层直接放置 `song_emotion_tagger`，角色歌曲资源统一放在 `characters` 层：

```json
{
  "capabilities": {
    "sing": {
      "song_emotion_tagger": { "llm": { "name": "..." } },
      "characters": {
        "luotianyi": {
          "resource_path": "res/sing_song/luotianyi"
        }
      }
    }
  }
}
```

旧的 `capabilities.sing.luotianyi` 扁平结构不再支持。

## 验证

- 唱歌能力、响应解析、情绪标签和学歌流水线相关测试通过。
- 学歌流水线测试：`25 passed`。
- 受影响测试合计：`41 passed, 1 warning`；warning 来自环境依赖 `pkg_resources` 弃用提示。
- 服务端全量测试：`173 passed, 2 skipped, 2 failed`；失败项是既有动态任务依赖测试和 VCPedia 外部 curl 超时，均不涉及本次唱歌改动。
- `server/src`、`server/scripts`、`server/tests` 编译检查通过。
