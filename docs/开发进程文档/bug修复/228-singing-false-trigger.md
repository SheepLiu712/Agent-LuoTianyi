# #228 · 统一话题提取、记忆检索与唱歌意图

## 目标与已确认流程
用户提及歌曲或歌词但未要求唱歌时，不应直接演唱或误写学歌愿望单。
2026-10-03 确认：所有生成式对话回复先调用 topic_extract，在同一次 LLM 请求中取得记忆检索 key 和唱歌 attempt；检索记忆、解析有效歌曲片段后，再交给 replier 生成有序的说话/演唱草稿，转成 Say/Sing ActionPlan。

## 调用链与边界
- 普通批次回复、明确记忆提交后的确认（包括同批普通消息）、主动提醒统一进入 ResponseCompositionSkill。
- TopicExtractionSkill 使用现有 agent.topic_extractor 模型配置和 topic_extraction_prompt，模块名 topic_extract；client_model_type 仍为 topic_extraction。
- 每轮提取一次，普通聊天和无歌名/无唱歌关键词的输入也不跳过。移除独立 SingingIntentSkill 和唱歌关键词短路。
- 同一次 JSON 结果返回 memory_attempts（记忆检索 key 列表）、sing_attempts（歌名或 random_song 列表）。字符串去空白、去空项、按序去重；错误字段类型不强转为歌曲或 key。
- 术语提取仅给模型提供歌曲线索，不能直接生成演唱 attempt；不再把整段输入直接用作记忆查询。
- 保留本轮完整输入与会话历史供 replier 使用。模型不决定 source_message_ids、批次消费或 incomplete；仍按 Stage/Handler 的就绪批次与 ID 结算。
- 明确记忆仍先完成提交，之后的确认回复进入统一链路；不能先承诺写入成功。
- 预制首次欢迎、触摸快速反射、动态/日记写作是既有专用路径，不改成聊天生成。

## 检索、歌曲与计划
- 无记忆 key 时跳过记忆检索；有 key 时调用现有用户/角色隔离的记忆查询。
- 无唱歌 attempt 时不调用选歌。只有提取结果中的 attempt 可以带 confirmed_intent 进入歌曲解析与原有愿望单门控。
- 可用歌名和片段均非空才传入 replier。选不到有效歌曲时继续生成说话回复，不生成不可执行的 Sing。
- replier 接收原回复输入、用户上下文、对话历史、记忆结果和有效歌曲片段；保留说话与演唱的输出顺序、歌词及持久化消息 ID 对齐。
- 单次提取是指上述两个决策共用一次 LLM 请求；replier 仍有独立生成调用，已有重试及图片理解等调用不计入提取次数。

## 失败与取消
- 模型异常、空输出或无效 JSON/字段：日志告警，返回空记忆 key 和空唱歌 attempt；不重试提取、不用原文或术语补造决策，继续说话生成。
- topic_extractor 缺少模型配置时启动告警并采用同样保守降级；生产完整链路需要有效模型配置。
- asyncio 取消不吞掉；处理已取消时不开始提取，提取后取消则不继续检索/选歌/生成，召回后取消则不继续选歌/生成。
- 慢召回继续在同一次处理内等待与结算，不新增刺激或重复回复。

## 验收证据
- 提取单测覆盖普通聊天也调用一次、同一结果同时产出两类列表、歌名只是线索、random_song、非法字段、代码块 JSON、模型失败与取消。
- 离线链路使用真实提取器、回复提示组装/解析、Handler 和 ActionPlan 交付：验证 topic_extract → recall → songs → replier 的顺序，以及 Say → Sing → Say。
- 记忆确认、主动提醒同样经过提取；无演唱意图、歌曲不可用、解析失败均不产生 Sing；验证用户/角色隔离、近期片段排除与愿望单 gate。
- Server 全量测试：1400 passed，17 skipped。跳过项包含真实外部服务/LLM，不代表真实模型意图判断准确率或线上演唱验收。
- 修改 Python 文件 Black、Ruff 检查通过；最终提交前检查 diff 空白。
- 待验证：真实模型对否定、讨论歌曲、引用歌词、明确点歌与模糊指代的行为，以及真实音频交付。
