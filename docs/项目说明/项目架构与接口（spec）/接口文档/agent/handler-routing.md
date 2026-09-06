# Handler 路由契约

状态：已实现；内部 plans 使用 [PlanEmitter](plan-emitter.md) 协议。本文记录 Agent 内部的处理器注册、查找和调用；业务入口继续使用 [Agent 门面](facade.md) 的两个方法。

## 文件与所有权

```text
server/src/
├── agent_runtime/
│   └── agent_runtime.py           # 初始化时装配每角色 Agent 及其路由器
└── agent/
    ├── __init__.py                # 只公开导出 Agent
    ├── facade.py                 # 业务入口校验及路由结果处理
    └── handlers/
        ├── __init__.py
        ├── stimulus/
        │   ├── __init__.py
        │   └── router.py         # StimulusRouter
        └── action/
            ├── __init__.py
            └── router.py         # ActionRouter
```

两个 router 模块及各级包位于以上路径。各 handlers 包的 `__init__.py` 不重导出内部类型。生产注册集合为空，装配由 AgentRuntime 初始化完成。

该文件树采用 #63 的两个路由模块位置；装配遵循已确定的 AgentRuntime 初始化约定。文件树列出路由涉及的文件。

Router 是 Agent 内部模块。AgentRuntime 仅在显式装配位置直接导入两个 router 类型；stage、world、Adapter 及其他业务调用方不导入它们。Agent 对外不增加注册、查询处理器或第三个业务方法。

## 内部接口

两个 router 分别在各自模块定义，使用泛型保存处理器引用。`HandlerT` 是调用处确定的处理器类型，只表示绑定的对象类型。路由器保存并返回原对象，调用协议见下文。

```python
class StimulusRouter(Generic[HandlerT]):
    def __init__(
        self, registrations: Iterable[tuple[StimulusKind, HandlerT]],
    ) -> None: ...

    def resolve(self, kind: StimulusKind) -> HandlerT: ...

class ActionRouter(Generic[HandlerT]):
    def __init__(
        self, registrations: Iterable[tuple[ActionKind, HandlerT]],
    ) -> None: ...

    def resolve(self, kind: ActionKind) -> HandlerT: ...
```

构造和 resolve 都是同步操作。类及方法提供中文 docstring，说明参数、返回对象和异常。注册项中的处理器必须为非 None 对象；路由器不创建、复制、调用或关闭该对象。

### 注册

- 构造器立即消费注册序列并保存独立的键到对象映射。调用方之后修改原序列不改变路由结果；处理器对象仍保留原引用，不做深复制。
- 注册输入使用有序的二元组序列，不能先合并成字典而掩盖重复键。空序列合法。
- 刺激键必须是 `StimulusKind` 实例，行动键必须是 `ActionKind` 实例。字符串值即使与枚举 value 相同也不接受；两种枚举不能混用。
- 相同 kind 出现两次即抛出 `ValueError`，包括重复绑定同一个对象。不会静默覆盖，也没有首项优先、优先级或 fallback。
- 非可迭代输入、非二元组注册项、错误键类型或 None 处理器抛出 `TypeError`。构造失败不返回部分可用的 router。
- 一个对象可以通过多个不同 kind 注册；一个 kind 至多对应一个对象。
- 构造完成后没有增删、替换或重载注册的方法。注册集合的生命周期与所属 Agent 一致，不使用进程级注册表。

### 查找

- `resolve(kind)` 只查询精确枚举键。已注册时返回构造时绑定的同一对象；重复查找不创建新对象，不改变注册状态。
- 类型正确但未注册时抛出 `KeyError(kind)`；错误键类型抛出 `TypeError`，不会转成未注册或默认路由。
- 查找不读取刺激正文、InteractionSnapshot、用户、角色配置或模型结果，不调用处理器，不产生网络、数据库、输出或后台任务。
- 每个角色单独装配 router；某角色的注册不会影响另一个角色。

## 路由键

刺激路由使用 `request.stimulus.kind`，快照保留交互事实；是否支持该交互由获得请求的处理器判断。

行动路由使用每项 `action.kind`。`START_THINKING` 由 stage 消费，ActionRouter 构造时注册该键抛出 `ValueError`；以该键查找仍属于未注册，抛出 `KeyError`。

枚举中已有成员不表示已注册，更不表示已有真实业务实现。本版生产两个注册集合均为空。

### 选择范围与调用流程

一次 handle 只根据触发刺激选择一个处理器。`pending_stimuli` 是交给该处理器理解和结算的输入，不逐项再次路由，也不因 pending 含有其他 kind 而调用其他处理器。`InteractionKind` 不参与路由键；处理器接收完整请求，并以 `UNSUPPORTED_INTERACTION` 表达不支持的交互。

一次 realize 先解析计划中全部行动，再按原顺序逐项调用处理器。因此，计划的后续行动未注册时，前面的行动也不会开始；同一个处理器被多个行动匹配时，仍然按每项行动分别调用，不合并行动。

```text
handle_stimulus(request, plan_sink)
  -> 门面入口检查
  -> StimulusRouter.resolve(request.stimulus.kind)
  -> handler.handle(request, 本次受限 plans)
  -> 门面核对并返回 HandlingReport

realize_action_plan(plan, execution_context, output_sink)
  -> 门面入口检查
  -> 为 plan.actions 全部解析 ActionRouter
  -> 按行动顺序 await handler.realize(action, execution_context, 本项受限 outputs)
  -> 门面核对并返回 ExecutionReport
```

上述流程说明进入路由后的选择和调用关系。门面各项入口检查及提前返回的完整顺序以 [门面契约](facade.md) 为准。

| 协作者 | 负责的事实 |
| --- | --- |
| AgentRuntime | 为每个角色构造注册集合、路由器和 Agent，注入依赖并管理生命周期 |
| Router | 校验注册键的唯一性，按精确枚举键返回处理器引用 |
| Agent 门面 | 校验调用身份，调用已解析处理器，管理取消、交付回执与报告结算 |
| StimulusHandler | 理解触发刺激及 pending，判断交互适用性，交付计划并报告消费结果 |
| ActionHandler | 实现单项行动，交付输出并报告实际效果 |

## 与门面和运行时的衔接

AgentRuntime 创建每角色 router，并通过 Agent 的装配参数传入；装配参数只供运行时和模块内测试使用，不从门面暴露 router。默认生产装配显式使用空注册序列。任一 router 构造失败时，AgentRuntime 初始化失败，沿用已有初始化清理规则，不发布半成品运行时。

门面完成其契约规定的入口检查后才查询 router；路由器不自行重复这些检查：

| 入口 | 查询方式 | 未注册的公开结果 |
| --- | --- | --- |
| handle_stimulus | 用触发刺激 kind 查询 StimulusRouter | FAILED / UNSUPPORTED_STIMULUS，pending 全部 retained，consumed 和 emitted_plan_ids 为空 |
| realize_action_plan | 按计划行动顺序逐项查询 ActionRouter | 任一项未注册则整份计划 FAILED / UNSUPPORTED_ACTION，所有行动 NOT_STARTED，不产生输出或效果 |

门面只将 resolve 的“合法枚举未注册”KeyError 转成上述结果；不能用包住整个处理流程的 KeyError 捕获来误吞业务错误。路由器的构造异常属于启动错误，不包装为 HandlingReport 或 ExecutionReport。

路由器只解析；门面负责调用解析结果并结算。Agent 构造接受仅供装配使用的关键字参数 `stimulus_router`、`action_router`；省略时为空表。AgentRuntime 显式传入每角色独立的空路由器。

## 内部处理器调用与单次调用事实

内部处理器采用以下异步结构协议；协议分别放在两个 router 模块，不从包根导出：

```python
class StimulusHandler(Protocol):
    async def handle(self, request: HandleStimulusRequest,
                     plans: PlanEmitter) -> HandlingReport: ...

class ActionHandler(Protocol):
    async def realize(self, action: Action, execution_context: ExecutionContext,
                      outputs: AgentOutputSink) -> ActionResult: ...
```

`plans` 是接收 ActionPlanDraft 的内部 PlanEmitter，按 [计划投递契约](plan-emitter.md) 分配身份并保存投递事实；`outputs` 保留 AgentOutputSink 协议。二者都是门面为本次调用创建的受限交付对象。它们不能取得其他调用的 sink，不把外部 sink 原对象传给处理器。处理器正常返回后，交付对象失效；保留它再调用不会产生输出。处理器不能启动脱离调用生命周期的工作；拥有的异步任务或同步线程在返回或传播任务取消前必须完成清理。

- plans 接收完整 draft，由门面固定角色、请求、交互与修订，校验 source_stimulus_ids 只能来自触发刺激及 pending；根据 ordinal 保存计划，再进行投递。报告只记录已确认接收的计划 ID，恢复及失败事实以 PlanEmitter 契约为准。
- outputs 校验输出的 execution_id、interaction_id、action_id 与当前行动一致；成功回执必须是 OutputReceipt 且 execution_id、sequence_no 匹配。首次有效回执后 output_started=True。回执不匹配属于 INTERNAL_ERROR；输入输出身份不匹配属于 CONTRACT_MISMATCH。
- 两个交付对象在调用外部 sink 前检查取消，sink 等待返回后先保存已确认接收事实，再检查取消。取消后不开始下一次交付。每次调用结束后释放 sink 引用。
- handle 正常返回的 HandlingReport 必须匹配请求、触发刺激、修订，considered 必须是 pending 的有序子集，emitted_plan_ids 必须等于真实回执记录。不合法的处理器结果转 INTERNAL_ERROR，pending 全部 retained，保留真实 emitted_plan_ids，不接受伪造消费。合法报告的消费和保留事实原样结算；令牌已取消时改为 CANCELLED/error_code=None，保留合法结算事实。
- 处理器抛异常时，尚无已返回的消费事实，pending 全部 retained；已确认接收的计划仍写入报告。失败处理器也可正常返回合法的 FAILED 报告来表达已确认的部分结算。
- ActionResult 必须匹配当前 action_id，且不能用 NOT_STARTED 冒充已调用的结果；无效返回转 INTERNAL_ERROR。已完成行动按原顺序保留，失败或取消停止后续行动。返回的 effect_ref 与 irreversible_effect_committed 是内部处理器已确认的事实，失败或取消不能清除它们。
- 行动等待返回时令牌取消：已返回 COMPLETED/ALREADY_COMPLETED 的效果仍为完成；整体报告为 CANCELLED，后续行动 NOT_STARTED。行动返回 FAILED 优先保留实际失败，不能用晚到取消掩盖。处理器返回 CANCELLED 时整体同样取消。
- 处理器内部 KeyError 是 INTERNAL_ERROR，不能误判为路由缺失。TimeoutError 和 SinkRejectedError 按门面错误表转换；通过 utils/logger.py 记录调用身份、稳定错误码、异常类型及无局部变量的栈位置，省略协作者异常原文。

## 在途调用与关闭

Agent 在通过入口检查、开始调用处理器前登记该调用，直到处理器及其清理退出才解除登记。AgentRuntime.shutdown 首先禁止所有角色接受工作，然后以 shutdown_timeout_seconds 为整轮在途等待的上限等待已登记调用；不主动取消调用方令牌或任务。超时抛 RuntimeError，不关闭向量库、不清除运行时引用；后续 shutdown 继续等待。全部调用退出后才能进入既有资源关闭流程。关闭调用本身取消也不清除仍运行的业务工作。门面拥有处理器任务，调用方任务取消仅向处理器转发一次；调用方重复取消时继续等待处理器清理退出，然后传播原取消。处理器任务实际开始时再次检查令牌；调度期间已取消则不调用业务处理器，handle 保留全部 pending，realize 当前及后续行动均为 NOT_STARTED。不同 interaction 的处理可同时进行，计划回执、输出、取消和报告不能互相污染。

## 测试入口与验收

路由模块自己的测试放在 `server/tests/agent`，可直接通过这两个内部模块接口构造和 resolve；不得读取私有映射或断言存储结构。测试对象只需是有区别的哨兵对象，无需创建真实 Handler 类或调用模型。业务边界回归仍通过 AgentRuntime.get_agent 和两个门面方法，不向外部测试提供生产 Handler 对象。

| 场景 | 应观察到的结果 |
| --- | --- |
| 空表、未注册合法枚举 | KeyError，门面保持既有 UNSUPPORTED 报告 |
| 单项和多项注册 | 每个 kind 返回准确的同一对象 |
| 多个 kind 绑定同一对象 | 允许共享，身份不改变 |
| 重复键绑定相同或不同对象 | 构造 ValueError，无覆盖 |
| 字符串键、另一种枚举、非法注册项、None 对象 | TypeError |
| START_THINKING 注册及查找 | 注册 ValueError，查找 KeyError |
| 修改构造所用列表 | 原 router 解析结果不变 |
| 两个不同 router 注册相同 kind | 各自返回自己的对象，无全局串扰 |
| 调用 resolve | 无处理器调用、副作用或异步任务 |
| 无真实 Handler 的生产装配 | 保持既有门面 38 项测试及旧链 get_character_runtime 兼容行为 |

契约测试覆盖成功处理器调用、错误与回执校验、等待中取消、并发交互隔离、在途关闭超时重试。测试证据见 `server/tests/agent/README.md`。
