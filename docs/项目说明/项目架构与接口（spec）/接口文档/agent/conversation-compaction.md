# 对话压缩技能

`server/src/agent/skills/conversation/compaction.py` 提供 `ConversationCompactionSkill`。

## 初始化与共享

`ConversationCompactionSkill(config: dict[str, Any], llm_service: LLMService)` 读取配置并注册名为 `conversation_context_summary` 的模型。`AgentRuntime` 创建 `Skills` 门面，由门面创建一个技能实例，所有角色共用；实例不持有用户、交互或对话快照。

配置来自 `agent_runtime.skills.conversation_compaction`。系统装配时，该项不存在则使用现有 `chat_session_manager.conversation_service` 配置。

| 配置键 | 含义 | 默认值 |
| --- | --- | --- |
| `raw_conversation_context_limit` | 近期记录超过此条数时生成总结 | 60 |
| `not_zip_conversation_count` | 保留在近期窗口中的记录条数 | 30 |
| `forget_conversation_days` | 传给总结提示词的遗忘天数 | 10 |
| `llm_module` | 注册总结模型的配置 | 无 |

压缩模块通过私有 `_CompactionConfig.from_dict` 提取并校验自身字段。阈值、保留条数和遗忘天数须为非负整数，拒绝布尔值、数字字符串、浮点数及显式 `None`；同时满足 `保留条数 <= 阈值`。字段缺失时使用默认值，本层配置错误发生在模型注册之前。

`llm_module` 不进入 `_CompactionConfig`，原样下传至 LLM 注册接口，由下一级解释。缺失或为 `None` 时不注册；空字典仍传给下一级，注册异常向初始化调用方传播。其它非本层字段不由压缩配置类校验。

## 压缩接口

```python
async def compact(
    conversation_context: ConversationContext,
) -> ConversationCompaction | None:
    ...
```

一次调用读取一次快照。未超过阈值返回 `None`；超过阈值则选择较早记录，将旧总结与这些记录传给模型，返回 `ConversationCompaction`。返回结果的覆盖 ID 与模型输入记录一致，最近保留的记录不进入本次总结输入。

技能不更新 context，不写数据库。调用方拿到非空结果后调用 `conversation_context.compact(result)`，由 context 验证并应用。模型未配置、调用失败、返回空白或非文字结果时抛出异常。任务取消向调用方传播。

## 现有聊天链路

`SystemRuntime` 将 `AgentRuntime.skills` 注入 `ChatSessionManager`，后者通过 `skills.get(ConversationCompactionSkill)` 取得共享实例，交给旧 `ConversationService`。旧会话服务不再注册总结模型。

旧 `compress_context_if_needed` 从数据库构造临时 `ConversationContext`，调用共享技能并应用结果，然后返回旧格式快照；无需压缩返回 `None`。原 `snapshot` 参数保留兼容，生成压缩的依据重新从数据库读取。

`ReflectionWorker` 保持原调用位置：压缩成功后继续更新画像；异常进入其现有日志处理。完整历史保留，结果生成期间新增的记录由 context 在应用时保留。

## 共享技能门面

`server/src/agent/skills/facade.py` 提供 `Skills(config, llm_service, *, tts_engine)`，由 `AgentRuntime` 初始化一次。`config` 为 `agent_runtime.skills` 配置，门面按技能名称派发配置，并显式注入每个技能所需的依赖。

`get(skill_type: type[SkillT]) -> SkillT` 按类型精确查询已初始化的技能，返回共享原实例，不执行技能。非类型参数抛 `TypeError`，未注册类型抛 `KeyError`。调用方可以通过返回类型获得对应技能的接口提示。

```python
compactor = agent_runtime.skills.get(ConversationCompactionSkill)
result = await compactor.compact(conversation_context)
```
