# 工作记录归档

本目录保存 2026-09 ~ 2026-11 期间的原始工作记录。**2026-11 起，这些记录的结论已合并为单一文档**：

- 现行汇总 → [`client-godot/docs/WORKLOG.md`](../../client-godot/docs/WORKLOG.md)
- 本目录只承载**逐条原文与逐轮证据**，不再单独维护；冲突时以 `WORKLOG.md` 的裁决为准。

## 索引

| 归档路径 | 原路径 | 日期 | 去向 | 归档理由 |
|---|---|---|---|---|
| `pr-186/review-5267320830-round1.md` | `tmp/review_5267320830.md` | 2026-11-08 | WORKLOG §4、§5 | 第 1 轮审查原文（head `92a46bd`，N1–N21）；结论已表格化 |
| `pr-186/review-5274311665-round2.md` | `tmp/review_5274311665.md` | 2026-11-08 | WORKLOG §4、§5 | 第 2 轮复审（head `a5e5ed6`），逐项复核 N1–N21 |
| `pr-186/review-5280367770-round3.md` | `tmp/review_5280367770.md` | 2026-11-08 | WORKLOG §4、§5 | 第 3 轮复审（head `1bb36b0`），冷导入竞态修复 |
| `pr-186/review-5379250373-round4.md` | `tmp/review_5379250373.md` | 2026-11-08 | WORKLOG §4、§5 | 第 4 轮审查（head `f1cb9e27`），N22–N30 起因 |
| `pr-186/review-5381572229-round5.md` | `tmp/review_5381572229.md` | 2026-11-08 | WORKLOG §4、§5 | 第 5 轮复审（head `2ea9870b`），解除阻断 |
| `pr-186/comment-5931768270-complexity.md` | `tmp/comment_5931768270.md` | 2026-11-08 | WORKLOG §5 | 圈复杂度三树对比补充证据 |
| `pr-186/review-186-4th-round.md` | `client-godot/docs/review-186.md` | 2026-10-01 | WORKLOG §5、§7 | 作者侧第 4 轮整改自述与验证状态 |
| `pr-186/pr-186-response-draft.md` | `client-godot/docs/pr-186-response.md` | 2026-10-01 | WORKLOG §5、§14 | PR 描述草稿与逐项回复，已过期（原文自述未推送） |
| `diagnostics/display-stutter-20261028-090718-findings.md` | `diagnostics/display-stutter-20261028-090718/findings.md` | 2026-10-28 | WORKLOG §12 | 桌面卡顿诊断，ETW 数值与事件表细节只在原文 |
| `design/ui-motion-plan.md` | `docs/ui-motion-plan.md`（工作区根） | 2026-10-02 | WORKLOG §9 | 动效交接方案；`ui_motion.gd` 从未落地，方案已失效 |

## 就地保留（未复制，避免双份漂移）

| 路径 | 说明 |
|---|---|
| `.workbuddy/memory/2026-11-08.md`、`2026-11-09.md` | 唯一的连续开发日志。Agent 系统按日期读取，**不得移动**；两份文件末尾已加指向 WORKLOG 的指针。 |
| `Agent-LuoTianyi/docs/TODO.md` | 路线图，仍有活跃入链，属活文档而非记录。 |
| `Agent-LuoTianyi/client/changelog.md` | 旧 Python 客户端的 V0.0.2 发布记录，内容已由 WORKLOG §2 吸收，原文件留在 `client/` 语境中。 |

## 使用提示

- 本目录是**未跟踪目录**，不纳入 `git add`（PR 口径只收本轮客户端文件）。
- 归档文件内容保持原貌，仅做两类改动：修正因移动而失效的相对链接；`design/ui-motion-plan.md` 顶部加入失效声明。
- 需要新增证据时，写入 `WORKLOG.md` 对应小节并在此表追加一行，不要修改已归档原文。
