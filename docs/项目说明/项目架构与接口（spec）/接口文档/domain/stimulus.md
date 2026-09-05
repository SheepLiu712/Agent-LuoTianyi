# Stimulus 领域契约

> 状态：工单 1 首个行为切片的目标 interface。
>
> 权威范围：本文件只定义抽象 `Stimulus`、首个具体变体 `TextMessage`，以及构造它们所必需的枚举和错误。其他 Stimulus、InteractionSnapshot、request 和 report 不属于本切片。

## 模块和调用者

这些类型归 `server/src/domain/agent/` 所有，并从 `src.domain.agent` 公开导出。Adapter、stage 和 world 使用具体 Stimulus 表达已经规范化的领域事实；Agent 只接收这些类型，不接收 WebSocket 事件、供应商对象或任意 `dict` payload。

`domain` 只负责不可变数据及其自身结构校验。构造这些对象不会访问数据库、网络、模型或文件，也不会决定会话记录或长期记忆持久化。

## 公开导出

本切片完成后，`src.domain.agent` 必须公开：

```python
from src.domain.agent import (
    InvalidStimulusError,
    Stimulus,
    StimulusErrorCode,
    StimulusKind,
    StimulusSource,
    TextMessage,
)
```

目标公开包不导出 `PersistPolicy`。迁移期旧协议仍从旧路径使用自己的 `PersistPolicy`；本切片不删除旧 `server/src/domain/stimulus.py` 或迁移其生产调用方。

## `Stimulus`

`Stimulus` 是所有目标强类型刺激的抽象基类，不能直接构造。它只集中定义每种刺激共有的身份、版本、时间、来源、目标和 interaction 生命周期字段；具体内容和固定 `kind` 由子类型提供。

所有实例都不可变，不提供任意 `payload` 扩展口，也不携带持久化策略。

| 字段 | 类型 | 含义 | 构造约束 |
| --- | --- | --- | --- |
| `stimulus_id` | `str` | 一项外部事实或协调信号的稳定身份 | 非空白；同一事实安全重投时保持不变 |
| `kind` | `StimulusKind` | 具体 Stimulus 的稳定判别值 | 由具体子类型固定，不是构造参数，也不能被调用方改写 |
| `schema_version` | `int` | 当前具体变体的结构版本 | 本切片只支持整数 `1`；`bool` 不视为整数版本 |
| `occurred_at` | `datetime` | 事实在来源处发生的时间 | 必须带时区；保留调用方提供的值，不以接收或处理时间替代 |
| `source` | `StimulusSource` | 供应商无关的语义来源 | 必须是已定义枚举值；Agent 不根据 `kind` 推断或改写 |
| `target_character_ids` | `tuple[str, ...]` | 应感知该事实的角色 | 至少一个成员；每个成员都是非空白字符串；保留调用方给出的顺序和值 |
| `user_id` | `str \| None` | 与事实有关的账户用户 | 没有相关用户时为 `None`；字符串时必须非空白，不回退默认用户 |
| `ephemeral` | `bool` | 该事实是否只在当前 interaction 窗口内有意义 | 只描述 interaction 生命周期，不直接命令是否写入会话或长期记忆 |

## `StimulusKind` 与 `StimulusSource`

本契约只登记 `TextMessage`；后续变体在各自行为切片中增量增加 `StimulusKind` 成员。

| `StimulusKind` 成员 | 序列化值 | 对应类型 |
| --- | --- | --- |
| `TEXT_MESSAGE` | `text_message` | `TextMessage` |

`StimulusSource` 表达领域事实由谁产生，不表达 WebSocket、HTTP、蓝牙、供应商或 scheduler 等传输和投递机制。

| `StimulusSource` 成员 | 序列化值 | 语义 |
| --- | --- | --- |
| `USER` | `user` | 用户行为产生的事实 |
| `DEVICE` | `device` | 设备自身状态或行为产生的事实 |
| `WORLD` | `world` | world 规范化的外部或活动事实 |
| `STAGE` | `stage` | stage 为其 interaction 产生的协调或期限事实 |

构造器不维护 `kind / source / ephemeral` 或其他字段的组合白名单。字段各自合法时，即使组合当前没有生产者，也必须允许构造；某个 Handler 暂不支持该输入时，由后续 handle 运行时契约表达。

## `TextMessage`

`TextMessage` 是用户或其他语义来源已经提交、可参与 Agent 语义处理的一条完整文字消息。它是 `Stimulus` 的具体不可变子类型，使用公共字段并增加：

| 字段 | 类型 | 含义 | 构造约束 |
| --- | --- | --- | --- |
| `text` | `str` | 消息正文 | 必须包含至少一个非空白字符；实例保留原始字符串，不自动 trim 或改写 |
| `client_msg_id` | `str` | 调用方重试同一客户端消息时使用的稳定身份 | 非空白；domain 不访问数据库执行去重 |

公开构造 interface 为：

```python
TextMessage(
    *,
    stimulus_id: str,
    schema_version: int,
    occurred_at: datetime,
    source: StimulusSource,
    target_character_ids: tuple[str, ...],
    user_id: str | None,
    ephemeral: bool,
    text: str,
    client_msg_id: str,
)
```

调用方必须按字段名直接构造 `TextMessage`，且显式提供上面的全部字段；`user_id` 没有关联用户时显式传入 `None`。不能传入 `kind`、`payload` 或 `persist_policy`。实例的 `kind` 始终为 `StimulusKind.TEXT_MESSAGE`。

`TextMessage` 不限定 `source` 或 `ephemeral` 的组合。例如字段自身都合法时，`source=StimulusSource.WORLD` 与 `ephemeral=True` 也能构造；这不代表当前一定存在该生产者，只证明 domain 不替 Agent 或 Handler 猜测业务合法性。

## 构造错误

```python
StimulusErrorCode = Literal[
    "CONTRACT_INVALID_STIMULUS",
    "CONTRACT_UNSUPPORTED_SCHEMA",
]
```

`InvalidStimulusError(ValueError)` 是公开构造异常，并稳定提供：

- `code: StimulusErrorCode`；
- `retryable: Literal[False]`，始终为 `False`。

字段缺失、类型不符、ID 或正文为空白、目标为空、目标成员非法、时间不带时区等字段或结构错误，抛出 `InvalidStimulusError(code="CONTRACT_INVALID_STIMULUS")`。`schema_version` 是整数但不是当前支持的 `1` 时，抛出 `InvalidStimulusError(code="CONTRACT_UNSUPPORTED_SCHEMA")`；非整数版本属于 `CONTRACT_INVALID_STIMULUS`。

`str(error)` 只供人工诊断，具体措辞不是公开契约。调用方不能解析错误字符串，也不能依赖内部字段名、规则 ID、非法值映射或 cause。构造失败不产生部分实例，也不会进入 Agent handle 流程。

## 契约验证 seam

契约测试只能从 `src.domain.agent` 的公开导出观察：

1. `Stimulus` 是不可直接构造的抽象类型，`TextMessage` 是其具体子类型；
2. 合法 `TextMessage` 固定为 `TEXT_MESSAGE`，逐项保留字段、不可修改，且不存在 `payload` 和 `persist_policy`；
3. 字段合法但少见的 `source / ephemeral` 组合仍能构造；
4. 公共字段、文字专有字段和 schema 的最小代表错误返回稳定 `code` 与 `retryable=False`；
5. `src.domain.agent` 不公开 `PersistPolicy`，旧 Stimulus 路径仍可使用迁移期协议。

测试不导入私有构造 helper，不枚举 `kind / source / ephemeral` 笛卡尔积，也不测试尚未进入本切片的其他 Stimulus。
