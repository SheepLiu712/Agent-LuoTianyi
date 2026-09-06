# HandlingReport 类型契约

`src.domain.agent` 提供不可变的 `HandlingReport`，保存调用方传入的请求结束状态、pending 处理结果、计划身份和重评时间，并校验报告内部的字段关系。

## 公开入口

以下名称从 `src.domain.agent` 导入：

- `HandlingReport`。
- `HandlingRequestStatus`。
- `HandlingErrorCode`。
- `InvalidHandlingReportError`。
- `HandlingReportErrorCode`。

`HandlingReport` 使用不可变值对象和仅限关键字的直接构造器。下表是完整构造参数，所有字段均须显式传入，包括空元组、`None` 和 `False`。合法值原样保存，字符串不裁剪，集合不转换、排序或去重。两个报告在全部字段相等时值相等。

## 字段

| 字段 | 类型 | 含义与构造约束 |
| --- | --- | --- |
| `request_id` | `str` | 被报告的请求身份；非空白 |
| `request_status` | `HandlingRequestStatus` | 请求的结束状态；对应枚举实例 |
| `trigger_stimulus_id` | `str` | 触发请求的刺激身份；非空白 |
| `basis_interaction_revision` | `int` | 判断依据的交互修订号；非负整数，拒绝 `bool` |
| `considered_pending_stimulus_ids` | `tuple[str, ...]` | 本轮考察的 pending 身份序列；构造保留传入顺序 |
| `consumed_pending_stimulus_ids` | `tuple[str, ...]` | considered 中已完成语义处理的身份，按 considered 中的相对顺序记录 |
| `retained_pending_stimulus_ids` | `tuple[str, ...]` | considered 中仍需重新判断的身份，按 considered 中的相对顺序记录 |
| `emitted_plan_ids` | `tuple[str, ...]` | 本次请求已被接受的计划身份，按首次接受顺序记录 |
| `reconsider_at` | `datetime \| None` | retained 内容的定时重评时间；有值时带时区，`None` 表示没有定时重评时间 |
| `error_code` | `HandlingErrorCode \| None` | 请求失败的稳定原因；`FAILED` 时必填，其他状态必须为 `None` |
| `retryable` | `bool` | 只接受布尔值；当前 Agent 返回 False，不要求调用者重投 |

四个身份元组均允许为空，元素必须为非空白字符串，同一元组内不得重复。不同身份域独立，例如计划 ID 与刺激 ID 使用相同字符串不影响构造。

`request_id`、trigger 和 revision 的含义分别对应[输入请求](handle-input.md)的身份、`stimulus.stimulus_id` 和 `interaction.interaction_revision`。构造器只接收上表字段，校验报告自身的类型、数值和内部关系；considered 的来源及计划接受情况由传入值表达。

## 请求状态与 pending 划分

`HandlingRequestStatus` 是字符串枚举，成员及协议值固定为：

| 成员 | 协议值 | 含义 |
| --- | --- | --- |
| `COMPLETED` | `completed` | 本次请求正常结束 |
| `CANCELLED` | `cancelled` | 本次请求因取消结束 |
| `FAILED` | `failed` | 本次请求因错误结束 |

设 considered、consumed 和 retained 的身份集合分别为 C、D、R，构造必须满足：

```text
C = D ∪ R
D ∩ R = ∅
```

consumed 和 retained 各自必须是 considered 的有序子序列。遗漏 considered 身份、加入未考察身份、交叉重复或颠倒子序列顺序均属于非法报告。considered 为空时，consumed 和 retained 也必须为空。

状态与划分独立：三个状态都允许全部消费、全部保留、部分消费或空 considered。trigger 可以是独立协调信号，因此它与 considered 的成员关系不参与构造校验。

`emitted_plan_ids` 与状态、消费比例独立；正常结束、取消和失败都能记录零个或多个已经接受的计划。计划 ID 的存在不等于计划已执行成功。

`reconsider_at` 有值时 retained 必须非空，时间满足 `tzinfo is not None` 且 `utcoffset() is not None`。允许已经到期的时间；时间校验只依赖字段本身。retained 非空时，时间可以为 `None`。三种状态均适用该规则。

`retryable` 是显式事实，构造器保留其布尔值；它与状态、计划数量和 retained 数量没有推导关系。

## 请求失败码

`HandlingErrorCode` 是字符串枚举。下列成员的协议值与成员名相同：

| 成员 / 协议值 | 含义 |
| --- | --- |
| `CONTRACT_INVALID_STIMULUS` | 刺激字段或变体结构不符合契约 |
| `CONTRACT_UNSUPPORTED_SCHEMA` | 刺激 schema 版本不受支持 |
| `CONTRACT_SNAPSHOT_MISMATCH` | 输入快照的结构或修订契约不成立 |
| `UNSUPPORTED_STIMULUS` | 当前处理能力不支持该刺激 |
| `UNSUPPORTED_INTERACTION` | 当前处理能力不支持该交互场景 |
| `STALE_INTERACTION` | 处理依据的交互修订已过时 |
| `SINK_CLOSED` | 计划接收端已关闭 |
| `BACKPRESSURE_TIMEOUT` | 等待计划接收超时 |
| `DEPENDENCY_UNAVAILABLE` | 处理所需依赖不可用 |
| `PROVIDER_TIMEOUT` | 外部提供方调用超时 |
| `INTERNAL_ERROR` | 处理过程中发生内部错误 |

枚举字段只接受对应枚举实例。原始字符串、未知成员或其他枚举实例均被拒绝。

前三个 `CONTRACT_*` 失败码表示输入契约错误，此时 consumed 必须为空；considered 全部进入 retained。其他失败码允许记录失败前已经完成的部分。报告构造器验证这些组合，不读取外部状态推断错误原因。

## 构造错误与副作用

非法报告抛出 `InvalidHandlingReportError`，它继承 `ValueError`，公开只读属性 `code: HandlingReportErrorCode`。`HandlingReportErrorCode` 是字符串枚举，只有 `CONTRACT_INVALID_HANDLING_REPORT="CONTRACT_INVALID_HANDLING_REPORT"`。

缺少参数、额外参数、使用位置参数、字段类型或数值非法、身份集合关系非法，以及状态/错误码/时间组合非法，均使用该构造错误。失败时不返回报告实例。异常文本供人工诊断，文案和多项错误的检查顺序不属于稳定协议。

`HandlingErrorCode` 是合法报告承载的处理失败原因；`HandlingReportErrorCode` 标识报告自身构造失败。二者具有独立类型和用途。

构造和读取报告只涉及内存值，不访问数据库、网络、模型或文件，不修改输入请求、取消令牌或已有集合。

## 构造示例

以下示例展示公开构造形式：请求正常结束，M1 已处理，M2 保留到指定时间。

```python
from datetime import datetime, timezone
from src.domain.agent import HandlingReport, HandlingRequestStatus

report = HandlingReport(
    request_id="request-1",
    request_status=HandlingRequestStatus.COMPLETED,
    trigger_stimulus_id="deadline-1",
    basis_interaction_revision=7,
    considered_pending_stimulus_ids=("M1", "M2"),
    consumed_pending_stimulus_ids=("M1",),
    retained_pending_stimulus_ids=("M2",),
    emitted_plan_ids=("plan-1",),
    reconsider_at=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
    error_code=None,
    retryable=False,
)
```

## 验证

测试从 `src.domain.agent` 的上述五个公开名称观察行为，测试文件归属 `server/tests/domain/test_handling_report_contract.py`。

在 `server` 目录运行：

```text
python -m pytest tests/domain/test_handling_report_contract.py -q
python -m pytest tests/domain -q
```

已完成验证记录见 [开发进度](../../../../开发进程文档/开发进度/Agent-handle-realize-深模块重构.md)。
