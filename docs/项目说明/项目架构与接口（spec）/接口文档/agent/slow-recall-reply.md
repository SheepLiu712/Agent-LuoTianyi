# 慢召回的两段式回复契约

状态：当前工作区已实现（#70）。代码位于 `agent/skills/cognitive/response_composition.py` 与 `agent/handlers/stimulus/chat.py`。

召回慢时，角色先给出一条完整的临时回复，等正式结果就绪后再给出完整的正式回复。两者是两份彼此独立、各自可实现的计划，不是同一条消息的增量修补。

## 内部两段式生成结果

```python
@dataclass(frozen=True)
class ComposedReply:
    drafts: tuple[ReplyDraft, ...] = ()
    memory_hits: tuple[MemoryHit, ...] = ()

@dataclass
class ComposedResponse:
    provisional: tuple[ReplyDraft, ...] | None = None
    pending: Callable[[], Awaitable[ComposedReply]] | None = None

    @property
    def awaits_formal(self) -> bool: ...
    async def formal(self) -> ComposedReply: ...

class ResponseCompositionSkill:
    async def compose_staged(self, *, character_id, user_id, reply_topic,
                             conversation_history, memory_queries=(),
                             sing_attempts=(), excluded_segments=None) -> ComposedResponse: ...
```

`compose_staged` 是处理器内部使用的分阶段入口，不新增任何公开 Stimulus 或 Action，也不改变既有 `compose` 的语义（`compose` 仍一次性返回正式草稿）。

`provisional` 为 `None` 表示本次无需先行回复：召回在阈值内返回，或未配置临时文案。`awaits_formal` 为 True 时调用方必须再 `await formal()` 取得正式结果；`formal()` 可重复调用并返回同一结果，不重复生成。召回 future 全程留在本次 handle 内，不经由公开接口回流，因此没有 `RecallCompleted` 刺激，也不会递归进入处理器。

## ChatReplyHandler 的交付顺序

1. 交付序号 0 的 `StartThinking` 独立计划。
2. 调用 `compose_staged`；若返回临时草稿，立即把它作为一份完整计划交付（序号 1），其行动为可直接播放的 `Say`。
3. `await formal()` 等待正式结果。
4. 重新检查 `request.cancellation` 与交互依据修订：已取消或修订已推进则不交付正式计划，迟到的召回结果被丢弃。
5. 否则把召回命中按触发刺激写入 `plans.context.recalled_memory`，再交付正式计划（序号 2）。

两份计划的 `basis_interaction_revision` 相同，`source_stimulus_ids` 相同，`plan_id` 与行动标识彼此独立（临时用 `-t{n}`、正式用 `-r{n}` 后缀），正式计划不修改也不引用临时计划。计划序号连续，由 PlanEmitter 分配。

临时计划交付失败时按既有失败停止语义处理：不再调用 sink，不生成正式结果，报告为 `FAILED` 且 `retryable=False`，没有任何重试或补偿。

召回结果只写入本次交互借用的 `InteractionContext`，按触发刺激归属，由 Stage 在结算时清理；不存在 Agent 全局召回注册表，结果不会跨用户或跨角色。

## 配置

`agent_runtime.reply_composition.slow_recall`（`server/config/config.json`）：

| 字段 | 含义 |
| --- | --- |
| `provisional_after_seconds` | 等待召回多久后给出临时回复；`0` 或缺省表示不启用两段式 |
| `provisional_text` | 临时回复的显示文本；为空表示不启用两段式 |
| `provisional_sound_content` | 临时回复的朗读文本 |
| `provisional_tone` | 临时回复的 TTS 语气代码（已映射值，如 `tender`） |
| `provisional_expression` | 临时回复的 L2D 表情代码（已映射值，如 `温柔脸`） |

临时文案属于用户可见内容，只来自该配置，处理器与技能内不含任何字面文案。配置经 `AgentRuntime` 读取后由 `Skills.reply_composition_config` 交给 `ResponseCompositionSkill`。临时回复不经过 LLM 语气映射，因此 `provisional_tone` 与 `provisional_expression` 需直接填写已映射的代码。
