# Handler 路由契约

状态：#63 SPEC 草案，尚未实现。本文定义 Agent 内部的处理器注册与查找；业务入口继续使用 [Agent 门面](facade.md) 的两个方法。

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

本切片建立以上两个 router 模块及必要包文件。各 handlers 包的 `__init__.py` 不重导出内部类型。生产注册集合为空，不建立 ConversationTurnHandler 等真实或占位 Handler 文件。装配由 AgentRuntime 初始化完成，不建立 factory.py。

Router 是 Agent 内部模块。AgentRuntime 仅在显式装配位置直接导入两个 router 类型；stage、world、Adapter 及其他业务调用方不导入它们。Agent 对外不增加注册、查询处理器或第三个业务方法。

## 内部接口

两个 router 分别在各自模块定义，使用泛型保存处理器引用。`HandlerT` 是调用处确定的处理器类型，不是新增共享领域类型；路由器不规定处理器业务方法，也不把它转换为通用 payload。

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

刺激路由使用 `request.stimulus.kind`，不使用 `StimulusKind + InteractionKind` 组合键。快照照常保留交互事实；是否支持该交互由获得请求的处理器判断。路由器不能因为 Chat、Toy、World 不同而自行换到另一个处理器。

行动路由使用每项 `action.kind`。`START_THINKING` 由 stage 消费，ActionRouter 构造时注册该键抛出 `ValueError`；以该键查找仍属于未注册，抛出 `KeyError`。

枚举中已有成员不表示已注册，更不表示已有真实业务实现。本版生产两个注册集合均为空。

## 与门面和运行时的衔接

AgentRuntime 创建每角色 router，并通过 Agent 的装配参数传入；装配参数只供运行时和模块内测试使用，不从门面暴露 router。默认生产装配显式使用空注册序列。任一 router 构造失败时，AgentRuntime 初始化失败，沿用已有初始化清理规则，不发布半成品运行时。

门面保持既有参数、角色、交互、修订、接受状态及预取消检查顺序。入口检查通过后才查询 router：

| 入口 | 查询方式 | 未注册的公开结果 |
| --- | --- | --- |
| handle_stimulus | 用触发刺激 kind 查询 StimulusRouter | FAILED / UNSUPPORTED_STIMULUS，pending 全部 retained，consumed 和 emitted_plan_ids 为空 |
| realize_action_plan | 按计划行动顺序逐项查询 ActionRouter | 任一项未注册则整份计划 FAILED / UNSUPPORTED_ACTION，所有行动 NOT_STARTED，不产生输出或效果 |

门面只将 resolve 的“合法枚举未注册”KeyError 转成上述结果；不能用包住整个处理流程的 KeyError 捕获来误吞业务错误。路由器的构造异常属于启动错误，不包装为 HandlingReport 或 ExecutionReport。

本切片交付注册和解析能力，以及空生产注册表的门面拒绝路径。成功解析只证明找到已绑定对象；路由器不执行对象，也不把解析成功记作行动完成、内容消费或计划被接收。Handler 调用协议、处理中取消和部分结算仍以门面草案的对应部分为准，本切片不宣称其已实现。

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

本次只交付 SPEC。后续 RED 中既有空表拒绝回归如果首次就通过，记录为回归测试，不制造失败。
