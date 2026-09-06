# handle 输入契约

> 状态：SPEC 修订版，待评审；本文新增类型尚未实现，不代表 Agent handle 已可调用。
>
> 日期：2026-09-06
>
> 权威范围：`HandleStimulusRequest`、三种 `InteractionSnapshot`、`CancellationToken` 及其必要值类型、构造约束和调用方责任。Stimulus 以 [Stimulus 契约](stimulus.md)为准。

## 1. 目标与边界

stage 用一个明确的请求，把“什么刺激触发判断、当前有哪些待处理内容、判断依据是什么、此次处理是否仍有必要”交给 Agent。Agent 不回查 stage 的队列、连接或可变上下文。

本版只建立输入契约，不实现 Agent 门面、Handler、stage 迁移、计划接收、报告结算或 realization。`ActionPlanSink`、`HandlingReport` 在示例中只表示总体设计已有的输出方向，其完整契约不由本文扩展。当前生产链和旧 `src.domain.stimulus` 保持原有迁移状态。

协议归 `server/src/domain/agent/`，统一从 `src.domain.agent` 导入。建议按 `interaction_snapshot.py` 与 `handle_input.py` 两组职责组织；具体文件不构成公开导入路径。domain 不依赖 Agent、stage、world 的实现，不访问模型、数据库、网络或文件。

目标调用形式：

```python
request = HandleStimulusRequest(
    request_id=request_id,
    stimulus=trigger,
    interaction=snapshot,
    cancellation=token,
)
report = await agent.handle_stimulus(request, plan_sink)
```

## 2. 公开类型与通用规则

本契约登记以下目标公开名称：

- `HandleStimulusRequest`、`InteractionSnapshot`、`ChatInteractionSnapshot`、`ToyInteractionSnapshot`、`WorldInteractionSnapshot`。
- `InteractionKind`、`ConnectionState`、`AgentOutputKind`。
- `CancellationToken`、`CancellationReason`。
- `InvalidHandleInputError`、`HandleInputErrorCode`。

除 `CancellationToken()` 外，数据对象采用仅限关键字的直接构造器。下文所有字段均须显式提供，包括可空字段；固定 `kind` 不作为构造参数。请求、快照和集合不可变，不能通过保留外部可变集合改变已构造快照。集合必须按声明类型传入，不隐式转换 list、set 或 dict。

非空字符串指非空白字符串；合法值保留原样，不 trim、不补默认身份。revision 使用非负整数，`bool` 不视为整数。时间必须带时区；时区字段必须是 `zoneinfo.ZoneInfo`，不依赖进程默认时区。枚举只接受相应枚举实例，不把任意字符串当作合法成员。

`InteractionSnapshot` 是以下三个具体类型的联合，不提供通用构造器或任意上下文扩展口：

```python
InteractionSnapshot = (
    ChatInteractionSnapshot | ToyInteractionSnapshot | WorldInteractionSnapshot
)
```

当前不登记 Call、Realtime 或 CharacterActivity 快照；world 活动由 `WorldInteractionSnapshot` 的活动引用表示。

## 3. InteractionSnapshot

### 3.1 公共字段

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `interaction_id` | `str` | 一段持续交互的稳定身份；非空白，由 stage 分配，不能跨逻辑交互复用 |
| `kind` | `InteractionKind` | 由具体类型固定；`CHAT="chat"`、`TOY="toy"`、`WORLD="world"` |
| `interaction_revision` | `int` | stage 拥有的交互决策修订号；非负；只在同一 interaction 内比较 |
| `user_id` | `str \| None` | 本交互相关账户用户；有值时非空白，无相关用户时显式为 `None` |
| `pending_stimuli` | `tuple[Stimulus, ...]` | 当前尚未结算的内容刺激，按 stage 顺序排列；允许空集合，`stimulus_id` 不重复 |
| `now` | `datetime` | stage 为本次判断提供的时间事实；带时区，Agent 不用机器当前时间覆盖它 |
| `timezone` | `ZoneInfo` | 解释日期和本地时间的时区；不要求 `now` 必须以同一时区表示 |
| `supported_outputs` | `frozenset[AgentOutputKind]` | 当前交互声明支持的输出类型；允许为空，不代表执行必定成功 |

`pending_stimuli` 必须包含实际的已构造强类型 Stimulus，不能只提供 ID、旧 Mapping Stimulus、字典或 Agent 内部 `UnreadMessage`。Agent 本轮待结算的 pending 内容以本快照为准，不能根据 ID 回查 stage 补齐内容；理解这些内容时可以使用 Agent 内部的历史对话与 Recall 上下文。

`UserTyping`、`ImageSelectionOpened`、`ImageSelectionClosed` 和 `InteractionDeadline` 是协调信号，不进入 pending。它们作为请求的 `stimulus`，可以在 pending 为空时触发 handle。其他调度/观察刺激是否需要持续保留，由对应 stage 的业务契约决定，不在这里建立全种类的处理策略表。

### 3.2 身份与修订号

`interaction_id` 回答“属于哪段交互”，`interaction_revision` 回答“依据这段交互的哪一版事实”。两者不能互相替代，也不能用 `request_id` 代替。

stage 必须在 pending 内容、有效等待控制、通道可用状态、输出支持集合或其他使旧判断失效的交互事实改变时递增 revision。安全重投相同事实、重复取消或仅再次采样 `now` 不要求递增。revision 可以跳号，但不得倒退或在同一 interaction 生命周期内重置。

构造器只能校验 revision 自身合法，无法证明它相对 stage 上一次值单调；该责任属于 stage。revision 不是 Agent 状态版本，也不能替代 world、activity、schedule 各自的权威修订号。

重连是否沿用原 interaction 由 stage 生命周期规则决定。保留同一逻辑交互时沿用 ID 并更新 revision；旧交互已经终结而新建交互时使用新 ID。不能仅因用户相同就接受旧交互结果。

### 3.3 ChatInteractionSnapshot

固定 `kind=InteractionKind.CHAT`，增加以下字段：

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `response_deadline` | `datetime \| None` | 当前聚合/重评截止时间；有值时带时区；允许已经到期，`None` 表示未设期限 |
| `connection_state` | `ConnectionState` | 本次采样时输出通道是否可用 |

`ConnectionState` 当前只有 `CONNECTED="connected"` 与 `DISCONNECTED="disconnected"`。它不携带 WebSocket、重连次数或供应商会话，也不表示 interaction 已经销毁。重连中但尚不可输出时仍为 `DISCONNECTED`。

删除 `typing_state: TypingState` 和 `image_selection_state: ImageSelectionState`，不以其他名字恢复它们。stage 维护等待流程；当前协调信号通过已有 Stimulus 交给 Agent，生效后的期限通过 `response_deadline` 表达。图片内容只能由 `ImageMessage` 提供，关闭选图不等于收到图片。

### 3.4 ToyInteractionSnapshot

固定 `kind=InteractionKind.TOY`，增加以下字段：

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `device_id` | `str` | 当前设备身份；非空白 |
| `online` | `bool` | 本次采样时设备是否在线 |

暂不建立 `ContactState` 或 `continuous_contact`。删除 `DeviceOutputLimits` 和 `device_output_limits`。设备可呈现的输出种类使用公共 `supported_outputs`；采样率、音量、动作幅度等设备限制不在本版 handle 输入中建立通用限制对象。

本版沿用 Toy 的 `online` 字段，保留 Chat 的 `ConnectionState`，不增加两套并列连接字段。Toy 快照可构造不表示占位的设备 Stimulus 已开放构造，也不表示玩偶生产链已实现。

### 3.5 WorldInteractionSnapshot

固定 `kind=InteractionKind.WORLD`，增加以下字段：

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `world_id` | `str` | 箱庭身份；非空白 |
| `world_revision` | `int` | 所读权威 world 快照修订；非负 |
| `activity_id` | `str \| None` | 当前关联活动；有值时非空白 |
| `activity_revision` | `int \| None` | 所读活动状态修订；有值时非负 |
| `planning_cycle_id` | `str \| None` | 相关规划周期；有值时非空白 |
| `schedule_revision` | `int` | 所读日程修订；非负 |

`activity_id` 与 `activity_revision` 必须同时为空或同时有值；无活动时不构造伪活动 ID。world、活动和日程修订是否仍有效，由各自状态所有者在使用时校验，不能仅比较 `interaction_revision` 得出结论。

删除 `visible_world_ref`。本版所需 world 事实由已有 `WorldObservation`、`ActivityObservation` 等强类型 Stimulus 的专有内容传入，通过 trigger 或 pending 参与判断；快照中的身份和 revision 不提供按 ID 获取任意 world 内容的能力。尚未定义所需事实的规划场景，不因存在 world ID 或 revision 就被视为已支持。

### 3.6 工作上下文与快照生命周期

删除 `conversation_ref`，不以其他字段或通用上下文字典替代。Agent 按 `(character_id, interaction_id)` 隔离工作上下文，在内部选取和组织历史对话、摘要、Recall 结果与本轮输入。stage 不负责选择历史窗口、唤起记忆或组装模型上下文，也不通过传入引用指挥 Agent 的上下文生命周期。

Agent 可以统一管理对话片段及相关记忆检索结果的相关性、保留期限、压缩和清理。清理的是认知使用中的临时内容，不等于删除会话记录或长期记忆正本；读取与持久化策略仍由 Agent 内部负责。stage 的 pending、deadline、连接状态及其结算权不因此转移给 Agent。

取消一次 handle 不等于结束整个 interaction，不能仅因 token 取消就清空共享工作上下文。interaction 结束或临时上下文过期时，由 Agent 内部按生命周期策略清理；本输入契约不新增上下文查询、清理方法或结束通知接口，也不宣称该生命周期链路已实现。

`InteractionSnapshot` 是随请求直接传递的不可变内存值。交互事实变化时创建新快照，旧快照不变；请求、重试及仍在运行的处理不再需要它后，可以释放。不为这些快照建立持久化、全局注册表、独立快照 ID 或按 ID 解析机制。`interaction_id` 与 `interaction_revision` 只标识交互及判断依据，不是快照存储地址。

本版删除通用 `SnapshotRef`，不从 `src.domain.agent` 导出。Stimulus 已有的 `MediaRef`、`EvidenceRef` 等资源引用仍由其自身契约负责，不能用这些类型包装已删除的上下文快照引用。

快照字段必须具有明确消费者和决策用途：应能说明谁读取、影响什么决定、删除后哪项行为无法成立。没有这些用途的信息不进入快照；未来确需额外 world 事实时，先为具体场景定义必要的强类型事实或明确查询契约，不预建通用引用。

### 3.7 supported_outputs

`AgentOutputKind` 在此只定义用于能力声明的枚举，不定义完整输出对象、动作或 sink：

| 成员 | 序列化值 | 含义 |
| --- | --- | --- |
| `TEXT_DELTA` | `text_delta` | 增量文字 |
| `TEXT_FINAL` | `text_final` | 最终文字 |
| `AUDIO_CHUNK` | `audio_chunk` | 音频块 |
| `AUDIO_END` | `audio_end` | 音频结束标记 |
| `EXPRESSION` | `expression` | 表情 |
| `MOTION` | `motion` | 动作 |
| `SONG_STATE` | `song_state` | 演唱状态 |

连接状态与支持类型职责不同：前者表示当前可达性，后者表示通道能呈现什么。断开时不要求强制清空支持集合；构造器不建立 `kind + connection + supported_outputs` 组合白名单。空支持集合也不禁止 Agent 认知或生成不经输出通道执行的计划。实际输出仍需由执行边界校验，快照不能保证后续连接仍然可用。

## 4. HandleStimulusRequest

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `request_id` | `str` | 一次逻辑 handle 请求的稳定身份；非空白 |
| `stimulus` | `Stimulus` | 触发此次路由与判断的 anchor stimulus；必须是目标协议的合法实例 |
| `interaction` | `InteractionSnapshot` | 调用时冻结的交互事实；必须是本文三种变体之一 |
| `cancellation` | `CancellationToken` | 此次 handle 的共享取消令牌；保留同一对象引用，不能复制当前状态代替它 |

请求不重复携带 `character_id`，Agent 实例由 `get_agent(character_id)` 取得。调用方必须确保目标 Agent 属于 trigger 和待处理刺激的 `target_character_ids`；domain 请求构造器没有绑定 Agent，不查询角色注册表。

`TextMessage`、`ImageMessage`、`VoiceMessage` 作为 trigger 时，必须在 pending 中按 `stimulus_id` 恰好出现一次，且完整字段一致。其他 trigger 如果同时出现在 pending 中，也必须与其中同 ID 对象完整相等。对象实例身份可以不同，不能只因 ID 相同就接受不同内容。

不在构造阶段校验 `StimulusKind + InteractionKind` 的处理能力组合，也不因 `user_id` 不同自动改写字段。调用方负责正确交互归属及授权；Handler 是否支持某种合法组合属于运行时行为。

同一逻辑请求安全重投时保留 `request_id`、trigger、完整 snapshot 和原令牌；不得改变 pending、时间、revision 或替换一个取消后重新可用的令牌，仍声称是同一请求。更新判断依据或取消后重新发起处理时使用新 `request_id` 和新令牌；保留内容的 `stimulus_id` 不变。

构造器不维护全局请求历史，不能独立检测跨调用的 ID 冲突。运行时去重和冲突报告属于后续 Agent 请求账本契约；本版只固定调用者应遵守的身份语义。

## 5. CancellationToken

### 5.1 公开操作与状态

`CancellationToken` 是请求中唯一有意可变的控制对象。stage 创建并持有它，将同一对象传入 Agent；stage 是取消决策者，Agent 与内部工作只观察它。

| 入口 | 返回值/状态 | 契约 |
| --- | --- | --- |
| `CancellationToken()` | 新令牌 | 初始 `is_cancelled=False`、`reason=None` |
| `token.is_cancelled` | `bool`，只读 | 是否已收到取消要求 |
| `token.reason` | `CancellationReason \| None`，只读 | 首次取消原因；未取消时为 `None` |
| `token.cancel(reason: CancellationReason) -> bool` | 是否首次改变状态 | 首次有效调用返回 `True`；重复有效调用返回 `False` 并保留首次原因 |

`CancellationReason` 当前严格限定为两类：

| 成员 | 序列化值 | 含义与例子 |
| --- | --- | --- |
| `SUPERSEDED` | `superseded` | 消息/请求已过时：新的刺激或交互事实要求更新 handle 的处理方式，旧判断不再适用 |
| `NO_LONGER_NEEDED` | `no_longer_needed` | 消息/请求已无需处理：例如连接断开后 stage 决定停止本次 handle，或 interaction 结束 |

新刺激到来不等于无条件取消，断线也不由领域对象自行触发取消；是否取消由 stage 按其交互策略决定。系统停机若需停止 handle，使用 `NO_LONGER_NEEDED`，不另加第三类原因。

取消状态只能从未取消进入已取消，不能重置或复活。`is_cancelled` 与 `reason` 的更新必须作为同一状态变化发布：已取消时原因一定存在。两个属性应连续读取，调用者不应跨异步等待把旧布尔值与新原因拼成一次状态采样。同一 stage 事件循环内的取消与读取必须一致；本版不承诺跨线程直接修改，其他线程应先交给拥有该 interaction 的事件循环。

首次原因保留，例如先因新刺激取消、随后连接断开，旧令牌仍记录 `SUPERSEDED`；stage 按最新交互状态决定是否重发，不能仅靠旧取消原因自动重试。对已取消令牌传入非法原因仍报构造/输入错误，不静默接受。

### 5.2 对 Agent 与 stage 的约束

1. 请求允许携带已取消令牌；请求构造本身不报错。未来 Agent handle 入口必须识别它，结束为取消，不启动新的认知工作或提交新计划。
2. 处理期间 stage 取消后，Agent 必须在启动下一项工作、异步工作返回后以及每次提交计划前检查令牌，并向内部可取消工作传播取消。
3. 外部 Recall/模型调用若无法立即终止，Agent 仍须丢弃取消后的迟到结果；`cancel()` 返回不表示模型请求已退出，也不承诺硬实时中断或完成确认。
4. stage 先更新自己的交互事实并递增 revision，再取消旧 token。快照本身不原地改变；需要再次 handle 时创建新请求和新快照。
5. 取消检查与计划接收之间仍可能发生竞态。stage 绑定的 plan sink 需要校验当前 interaction/revision；token 不能替代这项最终校验。具体接收与拒绝结果由 plan sink 契约定义。
6. 已经被可靠接收的计划、已经提交的记录或外部效果，不因 token 改变而自动回滚。取消也不等于 pending 已被消费或应被删除；后续由 stage 按有效报告与实际执行事实结算。

令牌不含 stage/Agent 引用、连接对象、回调列表、异常对象或任意原因字符串。本文不新增订阅、等待、reset、子令牌或取消源包装层。

## 6. 构造错误与副作用

本版直接构造入口发生缺参、多余参数、非法字段或结构错误时，统一抛出 `InvalidHandleInputError`（`ValueError` 子类），其只读 `code: HandleInputErrorCode` 为以下稳定值之一：

| 成员及值 | 使用场景 |
| --- | --- |
| `CONTRACT_INVALID_INTERACTION` | snapshot 自身非法，例如负 revision、无时区时间、重复 pending ID、协调信号混入 pending、活动 ID/revision 不配对 |
| `CONTRACT_INVALID_HANDLE_REQUEST` | 请求字段非法、类型不符、必要内容 trigger 缺失或同 ID 内容不一致 |
| `CONTRACT_INVALID_CANCELLATION` | token 构造传入未定义参数，或 `cancel` 未提供合法原因 |

以上枚举成员的字符串值与成员名相同。已构造 Stimulus 的错误类型仍由 [Stimulus 契约](stimulus.md)负责，不重新定义或吞并 `InvalidStimulusError`。同时存在多项错误时不承诺校验先后；不依赖完整异常文案作业务判断。

数据构造、读取 token 和调用 `cancel` 均不访问外部服务、不修改 stage pending、不产生用户输出、不写持久化。`cancel` 唯一副作用是修改本令牌状态。构造成功不证明引用存在、请求获得授权、Handler 支持该场景或 handle 实现已经就绪。

## 7. 验收场景与测试入口

领域契约测试以 `src.domain.agent` 的公开构造器、字段和 `cancel` 为入口，预期放入 `server/tests/domain/test_handle_input_contract.py`。不测试私有 helper，也不需要模型、数据库或真实连接。

| 场景 | 可观察结果 |
| --- | --- |
| 分别构造 Chat、Toy、World | 固定 kind，公共字段与专有字段完整保留；World 允许无 user/activity |
| 构造空 pending 与空 supported_outputs | 合法；不因没有用户可见输出而拒绝 |
| 同一 interaction 的 r1、r2 快照 | ID 相同、revision 不同；构造 r2 不改变 r1 |
| 请求与快照尝试赋值，或集合尝试原地变更 | 拒绝变更；token 保留可变控制能力 |
| 负 revision、bool revision、无时区时间、错误枚举类型 | 对应稳定错误；合法的过去 deadline 可保留 |
| 内容 trigger 在 pending 中缺失/重复/同 ID 异内容 | 拒绝；相同内容的不同实例可接受 |
| 打字、选图或 deadline trigger，pending 含实际消息 | trigger 无需进入 pending；Agent 输入仍包含完整消息 |
| 把协调信号放入 pending，或传入旧 Mapping Stimulus | 拒绝，不进行隐式转换 |
| 传入被删除的四组字段/类型 | 快照拒绝多余字段；公开包不导出 TypingState、ImageSelectionState、ContactState、DeviceOutputLimits |
| 构造 Chat/World 快照，不提供任何上下文引用 | 合法；不查询快照存储或 Agent 上下文 |
| 传入 `conversation_ref` 或 `visible_world_ref` | 拒绝多余字段；公开包不导出 `SnapshotRef` |
| 字段合法但少见的 stimulus/interaction/output 组合 | 不设生产场景白名单；接受构造 |
| 请求构造后，stage 调用同一 token.cancel | 请求内立即观察到 `True` 与对应原因，原 snapshot 不变 |
| 同一 token 重复取消或用另一合法原因取消 | 首次返回 True，后续 False，首次原因保留 |
| 新建 token、两个并存请求、取消其中一个 | 初值一致；独立令牌互不影响，不复活旧令牌 |
| 已取消 token 构造请求；非法原因取消 | 前者合法；后者返回稳定错误且不改变已有状态 |

以下场景需要未来真实 Agent/stage 公开入口验证，不能用领域对象测试宣称通过：预取消不启动工作；Recall/模型迟到结果不提交；新 revision 拒绝旧计划；同 request ID 的输入冲突；断线和重连期间的 pending 结算；Agent 工作上下文的 interaction 隔离、历史与 Recall 统一保留/清理、取消不误删上下文以及清理不删除持久化正本；Stimulus 资源引用的授权读取。

本次为文档交付，运行时 Red/Green 不适用。评审验证采用字段逐项核对、Markdown 相对链接检查及 `git diff --check`；未建立新类型或运行时行为测试。

## 8. 阅读验收

评审者应能仅根据本文说明：新消息到来与连接断开时分别由谁取消、使用哪个原因；旧 snapshot 是否变化；重新处理时三个 ID/revision 如何变化；取消前已接收的计划是否会自动回滚；对话工作上下文由谁管理，清理它是否删除长期记录，以及快照为何无需按 ID 保存和读取。不能从本文直接确定的 Agent 输出及结算细节，应从对应输出契约评审，不从内部代码推断输入语义。
