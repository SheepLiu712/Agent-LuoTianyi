# handle 输入契约

本文记录 `src.domain.agent` 已提供的请求、交互快照、取消令牌及构造错误。Stimulus 的结构见 [Stimulus 契约](stimulus.md)。

## 公开入口

以下名称从 `src.domain.agent` 导入：

- `HandleStimulusRequest`。
- `InteractionSnapshot`、`ChatInteractionSnapshot`、`ToyInteractionSnapshot`、`WorldInteractionSnapshot`。
- `InteractionKind`、`ConnectionState`、`AgentOutputKind`。
- `CancellationToken`、`CancellationReason`。
- `InvalidHandleInputError`、`HandleInputErrorCode`。

快照和请求使用仅限关键字的构造器，所有字段均须显式提供，包括值为 `None` 的字段。字段名和参数集合由下文表格完整列出；`kind` 由快照类型固定，是只读属性，不是构造参数。

快照、请求及其集合字段不可变。构造时保留合法输入值，不裁剪字符串、不转换集合类型。字符串身份必须非空白；修订号必须是非负整数，`bool` 不作为整数接受。时间值必须带时区，`timezone` 必须是 `zoneinfo.ZoneInfo`。枚举字段只接受对应枚举的实例。

## InteractionSnapshot

`InteractionSnapshot` 是三种具体快照类型的联合：

```python
InteractionSnapshot = (
    ChatInteractionSnapshot | ToyInteractionSnapshot | WorldInteractionSnapshot
)
```

快照是随请求直接传递的内存值对象。构造新快照保留已有快照的字段和值。

### 公共字段

| 字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `interaction_id` | `str` | 持续交互的身份；非空白 |
| `kind` | `InteractionKind` | 具体快照类型的固定判别值 |
| `interaction_revision` | `int` | 该交互的事实修订号；非负整数 |
| `user_id` | `str \| None` | 相关账户用户；有值时非空白 |
| `pending_stimuli` | `tuple[Stimulus, ...]` | 按输入顺序保存的待处理刺激；允许空元组，刺激 ID 无重复 |
| `now` | `datetime` | 本次输入携带的当前时间事实；带时区 |
| `timezone` | `ZoneInfo` | 解释本地日期的时区；可以与 `now` 的时区不同 |
| `supported_outputs` | `frozenset[AgentOutputKind]` | 声明支持的输出类型；允许空集合 |

`interaction_id` 标识交互，`interaction_revision` 标识该交互的一版事实，`request_id` 标识处理请求。三个字段分别保存调用方提供的值。

`pending_stimuli` 接受已构造的强类型 `Stimulus` 实例。重复的 `stimulus_id` 会被拒绝，包括同一对象重复出现以及不同内容使用同一 ID。集合顺序保留原样。

`UserTyping`、`ImageSelectionOpened`、`ImageSelectionClosed` 和 `InteractionDeadline` 是协调信号，构造快照时拒绝将它们放入 pending；它们可以作为请求的 trigger，与空或非空 pending 一起构造请求。

### ChatInteractionSnapshot

固定 `kind=InteractionKind.CHAT`，在公共字段之外包含：

| 字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `response_deadline` | `datetime \| None` | 聚合或重评截止时间；有值时带时区；允许已经到期 |
| `connection_state` | `ConnectionState` | 输入中记录的输出通道可用状态 |

`ConnectionState` 的成员为 `CONNECTED="connected"`、`DISCONNECTED="disconnected"`。连接状态与支持的输出类型独立：断开状态的快照可以保留非空 `supported_outputs`，构造请求时令牌状态保持原样。

### ToyInteractionSnapshot

固定 `kind=InteractionKind.TOY`，在公共字段之外包含：

| 字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `device_id` | `str` | 设备身份；非空白 |
| `online` | `bool` | 设备在线状态；只接受布尔值 |

### WorldInteractionSnapshot

固定 `kind=InteractionKind.WORLD`，在公共字段之外包含：

| 字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `world_id` | `str` | 箱庭身份；非空白 |
| `world_revision` | `int` | world 事实修订号；非负整数 |
| `activity_id` | `str \| None` | 相关活动身份；有值时非空白 |
| `activity_revision` | `int \| None` | 活动修订号；有值时为非负整数 |
| `planning_cycle_id` | `str \| None` | 规划周期身份；有值时非空白 |
| `schedule_revision` | `int` | 日程修订号；非负整数 |

`activity_id` 和 `activity_revision` 必须同时为空或同时有值。交互、world、活动和日程修订号分别保存各自的输入值。world 事实可以由已有 `WorldObservation`、`ActivityObservation` 等 Stimulus 的内容字段表达。

### 枚举

`InteractionKind` 的成员与协议值为：`CHAT="chat"`、`TOY="toy"`、`WORLD="world"`。

`AgentOutputKind` 的成员与协议值为：

| 成员 | 协议值 | 含义 |
| --- | --- | --- |
| `TEXT_DELTA` | `text_delta` | 增量文字 |
| `TEXT_FINAL` | `text_final` | 最终文字 |
| `AUDIO_CHUNK` | `audio_chunk` | 音频块 |
| `MESSAGE_END` | `message_end` | 消息结束标记，纯文字和音频消息均适用 |
| `EXPRESSION` | `expression` | 表情 |
| `MOTION` | `motion` | 动作 |

## HandleStimulusRequest

| 构造字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `request_id` | `str` | 处理请求身份；非空白 |
| `stimulus` | `Stimulus` | 触发本次判断的刺激，即 trigger |
| `interaction` | `InteractionSnapshot` | 三种具体交互快照之一 |
| `cancellation` | `CancellationToken` | 与调用方共享的取消令牌；保留同一对象引用 |

`TextMessage`、`ImageMessage`、`VoiceMessage` 作为 trigger 时，必须在 pending 中按 `stimulus_id` 恰好匹配一项，且完整字段相等。其他 trigger 若与 pending 中某项使用同一 ID，也必须完整相等。内容相等的不同对象实例可以匹配。

字段自身合法的刺激种类、交互种类、用户身份和输出集合组合均可构造。构造请求保留来源与用户字段，不检查业务组合白名单。

### 构造示例

给定一个已构造的 `TextMessage` 实例 `message`：

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.domain.agent import (
    AgentOutputKind, CancellationToken, ChatInteractionSnapshot,
    ConnectionState, HandleStimulusRequest,
)

token = CancellationToken()
snapshot = ChatInteractionSnapshot(
    interaction_id="chat-1",
    interaction_revision=0,
    user_id=message.user_id,
    pending_stimuli=(message,),
    now=datetime.now(timezone.utc),
    timezone=ZoneInfo("Asia/Shanghai"),
    supported_outputs=frozenset({AgentOutputKind.TEXT_FINAL}),
    response_deadline=None,
    connection_state=ConnectionState.CONNECTED,
)
request = HandleStimulusRequest(
    request_id="request-1", stimulus=message,
    interaction=snapshot, cancellation=token,
)
```

## CancellationToken

令牌通过同一对象在调用方与请求观察者之间共享取消状态。使用范围为同一事件循环。

| 入口 | 返回值或状态 | 行为 |
| --- | --- | --- |
| `CancellationToken()` | 新令牌 | 初始 `is_cancelled=False`、`reason=None` |
| `token.is_cancelled` | `bool`，只读 | 是否已经取消 |
| `token.reason` | `CancellationReason \| None`，只读 | 首次取消原因；未取消时为 `None` |
| `token.cancel(reason: CancellationReason) -> bool` | 是否首次改变状态 | 首次合法调用返回 `True`；之后合法调用返回 `False`，首次原因保持不变 |

`CancellationReason` 的成员与协议值为：

| 成员 | 协议值 | 含义 |
| --- | --- | --- |
| `SUPERSEDED` | `superseded` | 原处理依据已过时 |
| `NO_LONGER_NEEDED` | `no_longer_needed` | 原请求已无需处理 |

取消状态单向变化：未取消时没有原因，取消时保存首次原因，`is_cancelled` 从是否存在原因推导。连续读取两个属性可观察同一事件循环中已发布的状态；跨异步等待的两次读取可能对应不同时间点。

已取消令牌可以构造请求。请求引用原令牌，之后对令牌的取消会在请求中可见。不同新令牌的状态相互独立。取消前后都校验原因类型，非法原因报错且保持已有状态。

## 错误与副作用

快照、请求、令牌的构造器和 `cancel()` 在缺参、多余参数、非法字段或结构错误时，抛出 `InvalidHandleInputError`。它是 `ValueError` 的子类，提供只读的 `code: HandleInputErrorCode`。

| 错误成员及协议值 | 对应输入错误 |
| --- | --- |
| `CONTRACT_INVALID_INTERACTION` | 快照字段或参数非法、pending 重复 ID 或混入协调信号、活动字段不配对 |
| `CONTRACT_INVALID_HANDLE_REQUEST` | 请求字段或参数非法、必要 trigger 不在 pending、同 ID 内容不一致 |
| `CONTRACT_INVALID_CANCELLATION` | 令牌构造参数非法，或 `cancel()` 缺少/传入非法原因 |

上述错误枚举的协议值与成员名相同。多项错误并存时，调用方按错误码识别失败类别；异常文案和校验先后不构成稳定协议。Stimulus 自身的构造错误见 [Stimulus 契约](stimulus.md)。

构造和读取这些对象没有数据库、网络、模型或文件副作用。`cancel()` 的副作用仅为更新当前令牌状态，请求中的快照和 pending 保持不变。

## 验证

公开契约测试位于 `server/tests/domain/test_handle_input_contract.py`，覆盖快照字段与不可变性、请求和 pending 一致性、稳定错误、共享取消状态与重复取消行为。

在 `server` 目录运行：

```text
python -m pytest tests/domain/test_handle_input_contract.py -q
python -m pytest tests/domain -q
```

已完成验证记录见 [开发进度](../../../../开发进程文档/开发进度/Agent-handle-realize-深模块重构.md)。
