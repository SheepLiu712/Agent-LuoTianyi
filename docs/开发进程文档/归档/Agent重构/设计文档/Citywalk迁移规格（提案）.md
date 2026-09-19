# Citywalk 迁移规格（提案，未实现）

- 状态：**设计提案，待评审**。只记录切分与接口，不实现。
- 关联工单：Issue [#80](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/80)（21 迁移 citywalk 的角色决策与动态发布）
- 相关规范：总 SPEC 第 8.6 节 `try_citywalk:{character_id}` 行；现状 `server/src/world/citywalk/task.py`（`import CharacterRuntime`）

## 1. 要解决的问题

当前 citywalk 任务在 world 内直接取得角色能力完成「路线选择/表达/发布」。目标是把**机械外部过程**留在 world，把**角色决策**经 `WorldStage → handle`，发布经 `PublishDynamic` Action + realize。

## 2. 归属切分

| 环节 | 归属 | 说明 |
| --- | --- | --- |
| 每日 04:00、按角色、`daily_run_probability` 抽样 | world / WorldClock | 概率与环境推进是机械过程 |
| 地图请求、路径与环境推进、报告生成 | world | 外部事实与机械模拟 |
| 写 `travel` event、动态正文/ID 回写报告 | world（EventStore） | 权威事实与业务状态 |
| 角色路线选择/表达/是否发布 | Agent（经 WorldStage → `WorldObservation`） | 角色认知 |
| 动态发布 | `PublishDynamic` Action + realize | 外部效果，不直连 capability |
| 动态发布失败 | 不抹掉已完成 citywalk | 保留已完成外部事实 |

## 3. 建议刺激与调用（目标，未实现）

- world 成功完成环境流程后，产出 `WorldObservation`（含路线/环境结果等事实引用），经 `WorldFactSink`（见 19）投递 `WorldStage`；
- `WorldObservation` 的字段/取值需在 `domain/agent/stimulus.py` 的既有类型内确定（当前类型已存在，字段是否足够需评审）；
- Agent 决定表达与发布 → 计划交给 `realize`；world 不直接调用 `TtsHandler`/`capability.dynamics`。

## 4. 影响面与未决问题

- 影响：`citywalk/task.py` 去掉 `CharacterRuntime` 依赖；新增 world→WorldStage 投递；`PublishDynamic` action handler（当前 `ActionKind.PUBLISH_DYNAMIC` 已定义、无 handler）；测试。
- 未决：
  1. 路线/环境结果如何压缩进 `WorldObservation`（避免把机械细节带进 Agent）？
  2. 发布动态的正文由 Agent 生成，world 只回写 ID——确认无异议？
  3. 概率为 0（未命中）时是否完全不产生刺激（应为是）？

## 5. 明确不包含

- 不实现 citywalk 迁移、不新增刺激类型或 Action。
- 不改变概率、调度时间与 `travel` event 规则。
