# #228 · v0.4.0：未明确要求唱歌时也会触发唱歌（歌名即触发）

| 项 | 值 |
| --- | --- |
| 分支 | `fix/singing-false-trigger` |
| Issue | [#228](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/228) |
| 来源 | 《AgentLuo bug收集》（腾讯文档） |
| 流程 | 普通修复：dev → fix/ → PR → dev |
| 状态 | 实现完成，待验证（恢复 B：唱歌意图经过决策层判定） |

## 触发条件
用户输入包含歌名（或歌词命中 / 高频触发词命中）但并未表达唱歌意图时，服务端生成 Sing 计划并演唱。

## 被违反的不变量
仅在用户明确表达唱歌意图时，才产生 Sing 计划。

## 根因（详见 #228 调查记录）
- `server/src/agent/handlers/stimulus/chat.py:291` 将预处理检索术语直接作为 `sing_attempts`（无意图判定）；
- 非空即无条件构建 `sing_plan` 并注入强制演唱提示词（`response_composition.py:155-163`、`_prompt_assembly.py:56-64`）；
- 决策层（`SingingAction` / `topic_extraction_prompt`）在 #193 重构中旁路，仅剩残骸；
- 附带：误触发写入「愿望单」触发自动学歌（`singing/backend.py:131-132`）。

## 修复点（已拍板 B）
1. 恢复唱歌意图决策技能，复用 `topic_extraction_prompt` 与 `topic_extractor` 模型配置；
2. 歌名/歌词链接结果仅作为模型判定线索，不再直接成为 `sing_attempts`；
3. 明确点歌返回歌名，仅表达想听歌返回 `random_song`，其余返回空；
4. 模型调用或解析失败时保守返回空，不中断回复链；
5. 愿望单仅在决策层确认唱歌意图后允许写入。

## 改动范围（B）
`chat.py`、`skills/cognitive/singing_intent.py`、共享技能与运行时装配、`skills/expression/singing/backend.py`；
新增用例：含歌名的陈述句、歌词命中、明确点歌、未指定歌曲的听歌请求、模型失败与解析失败。

## 验收标准（已确认）
- 陈述句含歌名、歌词命中和否定请求不触发 Sing；
- 明确点歌正常触发；只表达想听歌时选择 `random_song`；
- 模型或解析失败不阻断回复，并按不唱歌处理；
- 愿望单仅在决策确认的唱歌意图下写入；上述场景均有测试证据。

## 验证计划
- server 相关范围单测 + 端到端对话用例。

## 待定与前置
- 无；范围已确认为恢复 B，后续由 PR 验证与审核。
