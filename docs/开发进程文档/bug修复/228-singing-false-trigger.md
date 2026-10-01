# #228 · v0.4.0：未明确要求唱歌时也会触发唱歌（歌名即触发）

| 项 | 值 |
| --- | --- |
| 分支 | `fix/singing-false-trigger` |
| Issue | [#228](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/228) |
| 来源 | 《AgentLuo bug收集》（腾讯文档） |
| 流程 | 普通修复：dev → fix/ → PR → dev |
| 状态 | 计划（首提交占位），范围待拍板（A/B） |

## 触发条件
用户输入包含歌名（或歌词命中 / 高频触发词命中）但并未表达唱歌意图时，服务端生成 Sing 计划并演唱。

## 被违反的不变量
仅在用户明确表达唱歌意图时，才产生 Sing 计划。

## 根因（详见 #228 调查记录）
- `server/src/agent/handlers/stimulus/chat.py:291` 将预处理检索术语直接作为 `sing_attempts`（无意图判定）；
- 非空即无条件构建 `sing_plan` 并注入强制演唱提示词（`response_composition.py:155-163`、`_prompt_assembly.py:56-64`）；
- 决策层（`SingingAction` / `topic_extraction_prompt`）在 #193 重构中旁路，仅剩残骸；
- 附带：误触发写入「愿望单」触发自动学歌（`singing/backend.py:131-132`）。

## 修复点（建议拆两步，需拍板）
**A. 行为收口（本单建议范围）**
1. `sing_attempts` 改为意图门控：仅明确点歌语境才生成；
2. `song_entity_linker` 收紧：歌词命中不再直接成 attempt；
3. 愿望单仅在真实点歌时写入。

**B. 决策层恢复（建议另立工单）**
让 `SingingAction` / 决策提示词真正回到链路参与判定。

## 改动范围（A）
`chat.py`、`skills/cognitive/song_entity_linker.py`、`skills/expression/singing/backend.py`；
新增用例：含歌名的陈述句、歌词命中、明确点歌（正反用例）。

## 验收标准（拟 · 待人审）
- 陈述句含歌名不触发 Sing；明确点歌正常触发；
- 愿望单不被误写；三类场景均有测试证据。

## 验证计划
- server 相关范围单测 + 端到端对话用例。

## 待定与前置
- 「明确点歌」的句式边界（验收标准待确认）；
- A/B 范围取舍确认。
