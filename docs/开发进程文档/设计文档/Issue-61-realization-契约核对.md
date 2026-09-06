# Issue #61 类型与接口核对

日期：2026-09-06。代码基线：`c523b2a6`，分支起点为 `refactor/agent`。

本文记录当前代码证据与待确认的设计建议；配套 [realization SPEC 草案](../../项目说明/项目架构与接口（spec）/接口文档/domain/realization.md) 尚未实现。
检查目标为当前版本用途、信息是否重复，以及当前用户行为是否被覆盖。未运行真实模型、媒体、设备或生产链路，以下代码证据均为静态核对。

## 1. 逐接口用途与重复检查

| 总 SPEC 中的类型/接口 | 当前用途依据 | 信息覆盖检查与本轮建议 |
| --- | --- | --- |
| Action / ActionKind | 当前说话、唱歌、日记、动态、评论和学歌有真实执行链 | 保留具体强类型和固定 kind；旧 Mapping Action 不作为字段模板 |
| Say | OneSentenceChat、触摸与预制欢迎 | content 与 sound_content 分别展示/朗读，不重复；预制媒体与 TTS 互斥 |
| Sing | GlobalSpeakingWorker 的歌曲分支 | song/segment 有用；bridge_text 被前后 Say 覆盖且没有位置定义，建议删 |
| ChangeExpression | 当前普通回复、唱歌、触摸带表情代码 | 保留内嵌语义；intensity/duration_ms 未找到消费证据，建议先只留 expression_id |
| Tone | MainChat 的语气到 TTS 配置映射 | 有用，与表情代码不同；使用非空白语义值，不猜测固定全集 |
| PerformMotion / MotionParameters | 只有旧动作枚举；未找到匹配的生产执行或参数协议 | 暂缓具体类型，不能根据名称推测参数 |
| TransitionActivity / ActivityState / ActivityTransitionReason | 本轮未找到活动修订 CAS 执行边界 | 暂缓；expected_activity_revision 与 StateDependency 可能表达相同前置条件 |
| CreateSchedule / CancelSchedule 及原因值 | 当前 WorldClock 周期任务和事件提醒不等于可由 Agent 创建/取消的持久日程 | 暂缓；不得把现有提醒强行替换为历史 SPEC 排除提醒的 future_stimulus |
| StateDependency / ExternalStateKind | 没有查到上述目标聚合修订的实际提交 owner | 建议本轮不建立；若活动/日程被确认属于本版本，先确定每项 Action 的唯一依赖表示 |
| WriteDiary | DiaryCapability 发布 private、不可评论、按来源去重的动态 | 与 PublishDynamic 共用存储，但日期/用户唯一性和固定策略有独立意义；不需要独立 title、visibility、任意 dedup_key |
| PublishDynamic / Visibility | citywalk、学歌发布，以及 DynamicStore 可见性 | 需要明确用户、来源和是否可评论；source identity 与任意 dedup_key 不并列 |
| ReplyDynamic / DynamicReplyTarget | publish_agent_comment 支持原帖与评论回复 | 明确 dynamic_id、parent_comment_id 和用户归属；不复制整个 DynamicObserved 线程 |
| RequestSongLearning / LearningPriority | 有持久候选与外部子进程学歌链；没有目标提交 port 或优先级消费证据 | 保留拟议的指定歌曲提交语义，暂删 priority；实际 job identity 通过效果结果返回，适配范围待确认 |
| ActionPlan | 目标架构需要排队后独立执行、慢 Recall 多计划 | 计划不是 HandlingReport 的副本；来源 IDs 是决定依据，report IDs 是消费结算 |
| ActionPlanSink / PlanReceipt | 新架构真实队列边界；当前 response/speaking 队列证明异步排队需求 | 接收与执行完成不同；保留关联身份/status，queue_position、accepted_at 没有业务消费者，建议去除 |
| ExecutionContext | 接收后排队期间可能变更或取消 | 当前 revision 与计划 basis revision 是两个时点；两种取消令牌生命周期独立 |
| AgentOutput / AgentOutputKind | 当前文字、音频、表情送往客户端 | 保留共享公共头与具体输出；kind 固定，避免任意 kind/content 配对 |
| OutputDelivery | 当前 display_in_chat/is_ephemeral 在欢迎和触摸时不同 | 两个外部布尔值合成同一语义，不与输入 Stimulus.ephemeral 混同 |
| TEXT_FINAL / TEXT_DELTA / TextPurpose | 当前先发完整显示文本，随后音频块不重复文字 | TEXT_FINAL 有用途；本轮未见增量文字生产者；purpose 的桥接语义由有序 Action 覆盖，建议暂不增加 |
| AUDIO_CHUNK / AudioFormat | 当前 TTS 为独立 WAV 块、唱歌切分整体音频 | sequence 足够排序；编码文件头已有格式、声道和采样率；真正缺失的是块的封装方式 |
| AUDIO_END | 当前成功、空音频、流异常均有终包 | 必须补失败/取消表达；total_chunks、summary、duration 暂无本次调用者依据 |
| EXPRESSION | 现行回复表情及触摸恢复 normal | 复用 ChangeExpression，不重复定义三套表情字段 |
| MOTION / SONG_STATE | 未找到运动输出执行链；SONG_STATE 已按用户决定移除 | 暂缓 MOTION 具体输出；不得恢复 SONG_STATE |
| AgentOutputSink / OutputReceipt | 当前通道排队/关闭/发送失败 | 接收不是播放完成；回执保留执行/序号/status，accepted_at 建议作为内部日志 |
| ExecutionReport / ActionResult | 当前流失败和持久发布可能部分完成 | 整体已提交效果布尔值可由逐项结果推导；output_started 不能从完成状态推导，仍有独立意义 |
| EffectRef | 发布得到动态/评论对象、学歌提交得到任务身份 | 只返回稳定 ID 和类别；日记共用动态效果类别 |
| 稳定错误/状态 | 需要区分构造错误、sink 拒绝和执行结果 | 使用不同错误边界；单项和整体执行错误语义相同，不必复制 ActionErrorCode 枚举 |

目标协议尚无生产调用者本身不构成删除依据：计划、sink、receipt 是已确认的两个 Agent 方法所需的真实协作边界。暂缓建议针对缺少行为/参数依据的功能，而非所有新类型。

## 2. 会话中需确认的风险

### R1：思考提示没有归属和精确时序

证据：`server/src/chat_session/chat_pipeline/topic_replier.py:137` 在处理队列清空后发送结束思考，`:150` 在处理话题前发送开始思考；`chat_stream.py:239` 将它转为状态，`:302` 使用 AGENT_STATE_CHANGED 发送。桌面 `client/src/gui/binder.py:114` 根据 thinking 显示气泡，App 的 `app/hooks/useChatLogic.ts` 同样消费状态。

建议由 ChatStage 依据实际内容处理生命周期发送既有 thinking/waiting，避免零计划、失败和取消时没有收尾。不能对每次 typing/deadline handle 都无条件显示气泡，也不能让旧请求 finally 关闭新请求的提示。
风险：现行 topic 处理跨度与新 handle 生命周期不完全同构。若必须精确保留 Agent 内部某阶段的起止，而 stage 无法观察，则两个现有 sink 均不足，需要单独讨论进度通知；不能把“开始思考”排在计划中，在思考结束后才执行。

### R2：缺少私密内容的用户身份及发布元数据

证据：`server/src/capabilities/diary/diary.py` 以角色、用户、日期产生 source_id，发布时固定 private、owner_user_id、allow_comment=False；`dynamic/dynamic.py:80` 接收来源、可见性、用户和评论策略；`:110` 的评论提交也需要 owner_user_id。

总 SPEC 的 ActionPlan 和 ExecutionContext 都没有 user_id，仅凭 interaction_id 无法在独立执行时获得这些事实。建议将用户写在需要该事实的日记/动态/评论 Action；补充来源和评论策略。不能默认读全局当前用户或解析 interaction_id。

### R3：音频失败、封装与消息收尾缺失

证据：`server/src/system/user_interface/types.py:20` 的 ChatResponse 有 uuid、is_final_package、audio_error、error_code。`global_speaking_worker.py:144` 建立终包，`:203`、`:212` 处理流异常和空音频；`server/tests/test_pipeline_reliability.py` 已有相应断言。桌面 `message_processor.py:275` 在音频失败时拒绝保存残缺音频。

仅在最终 ExecutionReport 写 FAILED 不能替代及时发往客户端的音频失败终包。建议 AudioEndOutput 加状态/错误，同时规定 TEXT_FINAL 不提前终结仍有音频的消息，以及跨输出/数据库共用的稳定消息身份。
`speech/tts_server.py:46` 每块编码 WAV，speaking worker 的演唱分支对完整音频按 48 KiB 切片。建议明确 COMPLETE_FILE/FILE_FRAGMENT；媒体解析器与客户端的兼容性必须验证，不能把每个文件片段当成可独立播放文件。

### R4：一组字段在重复表达相同决定

- Sing.bridge_text 与前后 Say 重复，且不确定衔接发生在哪一侧。
- StateDependency 与活动/日程 Action 的 expected_revision 重复，可能相互矛盾；计划级依赖也可能使第二个 Action 被第一个 Action 刚改变的修订误判失效。
- ExecutionReport.irreversible_effect_committed 与各 ActionResult 的 any 重复，建议只提供派生属性。
- PublishDynamic 的来源业务身份和任意 dedup_key 可能重复；WriteDiary 的唯一性已由角色/用户/日期确定。
- queue_position、accepted_at、TextPurpose、AudioEnd.summary 只有观测或未证明用途，建议留在内部日志或暂不引入。

plan/execution/action 身份、交互身份、不同时间的 revision 和跨 execution 的业务去重并不天然重复，不能为了减少字段全部合并。

### R5：活动、日程和 motion 的“当前版本”范围未明确

本轮检索 `server/src`（排除第三方学歌代码）未找到 PerformMotion、MotionParameters、TransitionActivity、CreateSchedule、CancelSchedule 或目标 expected revision 执行实现。当前存在 WorldClock、EventStore 和旧 LIVE2D_MOTION 枚举，不证明这些目标语义已存在。

建议本轮暂缓这四类 Action 及依赖值对象，而不是创建没有依据的可构造空壳。若本版本明确要交付它们，则需要先给出动作参数、活动状态、持久日程允许刺激及 revision owner。草案已经明确这是待确认范围，不擅自删除工单目标。

### R6：表情恢复不能以“已接收音频”替代“已播放完”

`server/src/agent/reflex/touch.py:64` 当前会在非 normal 快速反应后追加 normal 包。旧总 SPEC 写“音频结束或 duration 到期”，但没有明确结束是生成、投递还是播放结束。

建议保留表情输出与 normal 恢复行为，暂不承诺 duration/intensity 等客户端未消费参数。OutputReceipt 只证明接收；若要求严格播放后恢复，必须以实际客户端队列/播放事件核验。取消后还需避免表情恢复覆盖后续 Action。

### R7：日记是否合并、学歌是否已具备提交语义

WriteDiary 的存储是动态，但其按日唯一、私密、不允许评论的业务契约与通用发布不同，建议保留独立 Action，而不是同时执行 WriteDiary 与 PublishDynamic 导致双写。
现有学歌是候选池轮询及外部任务流程，并非按 learning_job_id/priority 提交的公开队列。建议保留“请求学习指定歌曲”的业务 Action，删除无证据的 priority，由效果回执给出任务 ID；这一适配范围需确认。

### R8：工单和历史文档滞后

issue #61 仍列 SONG_STATE，已有输入输出枚举没有该值；issue 还引用已标为历史背景的总体设计及 `.scratch` 底稿。
PRD 有旧的 `ActionPlanSink.emit -> None`，历史设计使用 PlanReceipt。确认草案后，应将本轮接口页作为对应权威来源并同步工单口径；本轮没有修改远程工单。

## 3. 本轮完成边界

完成静态用途/重复/行为遗漏核对及一份可评审 SPEC 草案。新增或收窄契约均已标为建议，尚未写产品实现或 RED。
没有把构造测试当成跨调用顺序、恰好一次提交、背压或生产兼容的证明。
待确认项保留在本核对文档和会话中，不写成接口已经实现的事实。
