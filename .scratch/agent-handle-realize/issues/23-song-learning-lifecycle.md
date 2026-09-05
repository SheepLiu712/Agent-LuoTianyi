# 23: 迁移学歌任务派发、完成事实与学会后的动作

**What to build:** 让 Agent 通过 RequestSongLearning Action 幂等启动可恢复长任务；机械下载/清理/分段/模型/校验完成后仅以 SongLearned 通知 WorldStage，Agent 内部记录学会经验并可发布动态或表达，同时保持现有 wishlist、通知、事件、库刷新和标签语义。

**Blocked by:** 06: 实现 realization、Execution Ledger 与 Say 输出核心；19: 建立长期 WorldStage 与 world 事实投递；21: 迁移 citywalk 报告、旅行事件与动态发布链；22: 将 VCPedia 新歌同步改为候选知识 Stimulus。

**Status:** ready-for-agent

**GitHub Issue:** [#82](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/82)

## Decision rule

SPEC 第 5.2/5.3、6.7、8.6 的 learn_sing_songs 行优先。wishlist 状态、凭据检查、工件有效性、通知文件、new_song event、库刷新和情绪标签细节不清时参考当前 learner/task/tests；中间进度不是 Stimulus，失败不得伪装成 SongLearned。

## Architecture constraints

- RequestSongLearning 归 `agent/handlers/action/song_learning.py` 与 typed execution Skill/持久 dispatch Adapter；机械 learner 保持在 world/capability，不进入 Agent。
- SongLearned 由 `agent/handlers/stimulus/song_knowledge.py` 处理，LearnedSongExperienceCommit 归 `agent/skills/mutation`；发布/表达分别复用 publishing/communication Action Handler。
- execution Skill/Adapter 只按已决定语义创建/恢复任务，不重新决定学什么；world learner 只通过稳定完成事实回到 WorldStage，不取得 Agent façade 或内部对象。

## Scope

- 实现 RequestSongLearning Action Handler/dispatch Adapter，以 learning_job_id/dedup key 持久化任务并由 Execution Ledger 结算。
- 保留 QQ 凭据前置、wishlist pending、learned/already learned/abandoned/awaiting 状态和机械工作流。
- 只在工件验证、媒体库刷新和必要标签结果达到现有完成条件后产生 SongLearned。
- SongKnowledgeHandler 通过 LearnedSongExperienceCommit 幂等记录 Agent 经验，并可产生 PublishDynamic/Say/Sing。
- 保持新 learned 的通知文件和 new_song event；already learned 不重复通知/发布。

## Acceptance criteria

- [ ] 相同 RequestSongLearning execution 重投只创建一个持久 job，进程恢复继续而不重复下载/发布。
- [ ] 凭据失败时本轮不启动；已有有效工件进入 already learned 且不产生新通知、event 或动态。
- [ ] 下载、清理、分段、模型处理和校验留在 world/capability，Agent 看不到中间对象。
- [ ] 只有验证完成产生一次 SongLearned；失败/awaiting/abandoned 只更新 task 状态。
- [ ] 新 learned 保持通知文件、new_song event、库刷新、情绪标签和每歌动态尝试；各效果独立、幂等、可报告部分失败。
- [ ] 角色经验写入在 Agent 内，不存在 RecordLearnedSong Action；动态仍经 PublishDynamic realization。
- [ ] action Handler、mutation Skill、机械 learner 三段依赖单向且可扫描；中间任务对象、凭据和工件路径不进入 Agent context/domain report。

## Verification

- 从 Agent Action dispatch 到 Fake worker 完成再回到 WorldStage 写失败跨模块测试；机械 provider 使用 Fake，状态/ledger 使用隔离存储。
- 覆盖凭据失败、already learned、awaiting、abandoned、完成、重复 completion、部分副作用失败和进程恢复。
- 运行 learn-song、dynamics、event、library/tagging 与 Agent/world integration 回归；真实模型/GPU 另列人工验证。

## Explicit exclusions

- 不改变歌曲处理算法、模型或凭据格式。
- 不新增“学歌失败”Stimulus；需要时先改 SPEC。

## Handoff

一个学歌生命周期纵向 PR；必须列出每个持久效果的幂等键和事务/补偿边界。
