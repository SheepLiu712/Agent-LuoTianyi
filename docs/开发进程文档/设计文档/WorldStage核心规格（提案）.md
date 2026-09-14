# WorldStage 核心规格（提案，未实现）

- 状态：**设计提案，待评审**。只记录归属与接口，不实现。
- 关联工单：Issue [#78](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/78)（19 实现长期 WorldStage 及世界事实投递）
- 相关规范：总 SPEC 第 4.9、6.1、7.7 节；现状 `server/src/stage/`（只有 `chat_stage.py`）、`server/src/world/world_runtime.py`、`domain/agent/interaction_snapshot.py`（`WorldInteractionSnapshot` 已存在）

## 1. 要解决的问题

- 目前没有 `WorldStage`：`server/src/stage/` 只有 `ChatStage`；`WorldInteractionSnapshot`、`WorldObservationKind` 等类型已存在但**没有生产者**。
- 4 个 world 任务（`citywalk`、`diary`、`dynamic_interaction`、`learn_sing_songs`）仍 `import CharacterRuntime` 直连旧链路，绕过两个 Agent 接口。
- 需要一条**持续、按角色/世界隔离**的交互通道，让 world 只提交稳定事实，由 stage 处理 pending/修订/取消并调用 Agent。

## 2. 归属

| 内容 | 归属 | 理由 |
| --- | --- | --- |
| 世界/活动/日程的权威事实与 revision | `world`（owner） | 事实来源在 world，stage 只协调交互 |
| 长期人格—世界交互、pending、取消、计划队列、输出路由 | `WorldStage`（`stage/`） | 与 ChatStage 同级；不属 world、不属 Agent |
| 时间唤醒 | `WorldClock` | 只唤醒，不构造角色决策 |
| 认知与表达 | Agent 两个接口 | stage 不解释抓取/供应商数据 |

## 3. 建议接口（目标，未实现）

```python
class WorldStage:
    @classmethod
    async def create(cls, *, character_id: str, world_id: str, agent, fact_sink_config) -> "WorldStage": ...

class WorldFactSink(Protocol):
    """world 任务向 WorldStage 投递稳定事实的窄端口。"""
    async def submit(self, fact: d.Stimulus) -> bool: ...   # 例如 WorldObservation
```

- **实例作用域**：`(character_id, world_id)`；单世界部署可退化为每角色一个长期实例。
- **Stage 职责**：维护 `interaction_id`/`interaction_revision`、pending、`WorldInteractionSnapshot`、handle 取消、plan sink、串行 execution worker、受限 world output sink（无即时通道时明确拒绝或 `NoChannelOutputSink`）。
- **事实投递**：world 任务只通过 `WorldFactSink.submit(WorldObservation(...))` 提交规范化事实；stage 不解释原始抓取/供应商数据。
- **revision**：新事实递增 `interaction_revision`，旧 handle 结果按 ID 结算；world/activity/schedule 的权威 revision 仍由各自 owner 校验。
- **装配**：`SystemRuntime` 显式装配 WorldStage registry 与 `get_agent`；不使用 service locator。
- **边界**：`world`/`world_clock` 不 import façade 或 Agent 内部；`agent/context` 只存带来源/版本/TTL 的受控证据，不成为 world 镜像。

## 4. 备选方案

| 方案 | 说明 | 评价 |
| --- | --- | --- |
| A. WorldStage + `WorldFactSink` 窄端口（倾向） | 长期交互、按 ID 结算 | 与 SPEC 4.9 一致；需新增 stage 模块与装配 |
| B. 每个事实一个 one-shot runner | 无长期状态 | 违反「不使用 one-shot runner 丢失连续上下文」 |
| C. world 直接调用 Agent | 省略 stage | 违反 A3/A5，world 不得直接调用 façade |

## 5. 影响面与未决问题

- 影响：新增 `stage/world_stage.py` 与 `agent/handlers/stimulus/world_activity.py`；`world_runtime` 的任务改为投递事实；`SystemRuntime` 装配；接口文档与测试。
- 未决：
  1. `world_id` 从哪来（配置/常量/多世界）？
  2. 无即时通道时 world 输出的支持/拒绝策略与 `output_started` 语义？
  3. 计划执行是串行复用同一 worker，还是每次 plan 一个 execution？
  4. 日程/活动（20）持久 scheduler 的归属与端口。

## 6. 明确不包含

- 本提案不实现 WorldStage、不迁移任何 world 任务、不新增端口代码。
- 不改变现有 `ChatStage`、`WorldClock`、world 任务行为。
