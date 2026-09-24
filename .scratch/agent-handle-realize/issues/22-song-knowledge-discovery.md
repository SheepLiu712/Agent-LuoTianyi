# 22: 将 VCPedia 新歌同步改为候选知识 Stimulus

**What to build:** 保持 `sync_new_song_knowledge` 的抓取、规范化、去重和结果统计，但不再由 world 直接写 Agent 歌曲知识；每个稳定候选形成 SongKnowledgeDiscovered，经 WorldStage/Agent 判断并由内部 SongKnowledgeAcceptance 幂等接纳。

**Blocked by:** 05: 实现 handle 请求幂等、PlanEmitter 与交互上下文核心；19: 建立长期 WorldStage 与 world 事实投递。

**Status:** ready-for-agent

**GitHub Issue:** [#81](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/81)

## Decision rule

SPEC 第 5.2、6.4、6.7、8.6 的 VCPedia 行优先。模板、safe name、介绍字段、关键词索引和 0.8 秒节流只在 SPEC 留白时参考当前 fetcher/task/tests；不得先写知识再补 Stimulus，也不得自动申请学习所有歌曲。

## Architecture constraints

- 候选抓取/结构化归 world；角色接纳归 `agent/handlers/stimulus/song_knowledge.py`，持久写入归 `agent/skills/mutation` 的 SongKnowledgeAcceptance。
- Handler 不导入 fetcher、数据库或 CapabilityManager；mutation Skill 通过 typed adapter 返回 committed revision，不生成 ActionPlan/文案。
- 候选证据可在 scoped context 中以来源/revision/TTL 引用，歌曲知识真相源仍是长期存储；不得复制完整知识库进 `agent/context`。

## Scope

- 抓取、反爬、页面解析、机械模型结构化、候选规范化、来源 revision、证据封装和来源去重留在 world。
- 每个完整候选投递 SongKnowledgeDiscovered；缺少介绍等不完整项仍计 failed，不投递伪候选。
- SongKnowledgeHandler 核验证据/冲突，通过内部 SongKnowledgeAcceptance 写同等可查询 Song 知识和关键词索引。
- 可选 RequestSongLearning 只能由 Agent 明确决定；本票可产生 Action，但外部执行由 23 号完成。

## Acceptance criteria

- [ ] 已有歌曲按名称/safe name 跳过；来源重复/revision 重投不重复知识和索引。
- [ ] 缺介绍候选失败并进入 added/failed 统计，不写部分知识。
- [ ] world 不直接写 Agent Song Knowledge；Agent 接纳后才有持久知识和 committed revision。
- [ ] 接纳失败或冲突有稳定 report，不能把候选标为成功写入。
- [ ] 各候选间当前 0.8 秒行为和最终统计保持；模型中间结果不成为 Stimulus。
- [ ] 发现歌曲本身不等于学歌请求；无 Agent 决策时不创建 learning job。
- [ ] world 不导入 Agent 内部包，SongKnowledgeHandler 不导入 world/存储实现；知识写入只能经 mutation Skill。

## Verification

- 从 world task 到 WorldStage/Agent 和记忆库最终状态写失败集成测试，Fake 网络/页面/模型。
- 覆盖已有、缺字段、新增、重复 revision、接纳拒绝/失败、索引一致性和可选学习决定。
- 运行 VCPedia、song knowledge、world/Agent integration 回归；真实站点另列人工验证。

## Explicit exclusions

- 不下载、分段、训练或验证唱歌工件。
- 不实现 SongLearned 或学歌任务生命周期；由 23 号工单负责。

## Handoff

一个歌曲知识纵向 PR；PR 记录哪些数据仍属 world 运行数据、哪些成为 Agent 知识。
