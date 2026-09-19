# VCPedia 候选知识接纳规格（提案，未实现）

- 状态：**设计提案，待评审**。只记录切分与接口，不实现。
- 关联工单：Issue [#81](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/81)（22 迁移 VCPedia 候选知识接纳）
- 相关规范：总 SPEC 第 6.7、8.6 节 `sync_new_song_knowledge` 行；现状 `server/src/world/get_new_songs/task.py`

## 1. 要解决的问题

现状：VCPedia 任务在 world 内抓取、解析并**直接写入 Song 知识**，角色没有「是否接纳」的认知决定，也容易被误当成「已加入学歌」。目标：抓取与规范化留 world，**接纳**由 Agent 决定并写自己的知识。

## 2. 归属切分

| 环节 | 归属 | 说明 |
| --- | --- | --- |
| 每日 04:00、模板歌曲列表拉取 | world / WorldClock | 机械抓取 |
| 反爬、页面解析、字段规范化、去重、成功率统计 | world | 外部技术过程；调用模型做结构化也仍在 world 外 |
| 与已存在知识的比对 | world 提供候选；Agent 判断冲突/接纳 | 「是否可信、是否冲突」属角色认知 |
| 稳定候选 → `SongKnowledgeDiscovered` | world 产出，经 WorldStage 投递 | 稳定边界 |
| 接纳写入知识 + 关键词索引 | Agent 内部 `SongKnowledgeAcceptance` 技能（幂等） | Agent 自有状态变更，不进 ActionPlan |
| 是否加入学歌 | Agent 决定（可选 `RequestSongLearning` Action） | 发现 **不等于** 自动学歌 |

## 3. 建议契约（目标，未实现）

- `SongKnowledgeDiscovered` 承载供应商无关的歌曲资料、来源、外部标识/页面版本、抓取时间；**不得**携带 VCPedia URL/HTML/解析器对象（受控引用）；
- 接纳技能幂等，按外部来源 + 歌曲标识 + 修订版本写入，返回已提交 revision；
- 关键词索引写入与知识写入在同一幂等边界内；
- 与 `dev` 上 #123—#125（VCPedia wikitext 改造）对齐：那批改的是 world 抓取/解析，本规格只定义「候选 → 接纳」边界，二者需在 22 收口时对齐候选规范化产物。

## 4. 影响面与未决问题

- 影响：`get_new_songs/task.py` 改为产出候选刺激；新增 Agent 侧接纳技能与刺激 handler；测试；接口文档。
- 未决：
  1. 候选规范化产物的字段集合（需与 #123—#125 的 wikitext 输出对齐）？
  2. 冲突时「更新既有知识」的版本/修订键是什么？
  3. 是否允许一次投递多个候选（批量）还是逐个投递？

## 5. 明确不包含

- 不实现迁移、不新增 Stimulus/Action、不改抓取与解析逻辑。
- 不改变「发现歌曲不自动学歌」的既有语义（仅明确它）。
