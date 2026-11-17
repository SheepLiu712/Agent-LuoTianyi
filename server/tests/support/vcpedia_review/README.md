# VCPedia PR #195 审查记录

关联 [PR #195](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/195) / [Issue #196](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/196)。产品约束只维护[进行中 spec](../../../../docs/开发进程文档/vcpedia-wikitext-migration.md)；操作见[World 测试说明](../../unit/world/README.md)和[语料说明](../vcpedia_corpus/README.md)。

## 2026-10-07 单版本歌词修复

按[维护者最新评论](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/195#issuecomment-6029627171)隔离歌词候选及缺口：先完成所有规则候选，再在需要时分别渲染，仍无完整结果才选一个候选最多补提一次。模型材料不含其他版本或译文；最终关键词从采用的歌词派生。简介总结保持独立，不增加完整性认证或多版本入库。

旧歌曲缓存无法证明单版本来源，重新抓取且不删除、不写回；最终仍缺歌词的 Song 不进入 Agent。歌曲入口也拒绝空歌词的 Person 结果，沿原 `fetch_failed` 处理，不改变 Agent 接纳/持久化接口。原版“添加第二个有缺口 poem 使首版 `needed.lyrics` 由 false 变 true”的复现已由候选隔离回归覆盖。

本轮工作区验证（非提交或合并证明）：

- Python 3.10.20、pytest **9.0.3**、Ruff **0.14.10**。pytest 使用独立临时目录的锁定版本，未修改共享环境。
- `tests/unit/world`、`tests/integration/world`、`tests/integration/packaging`、`tests/integration/agent/test_song_knowledge_acceptance.py` 在 `-X utf8=0`（实际 cp936/GBK）与 `-X utf8=1`（UTF-8）下均 **644 passed**。两次仅有既有 zhconv `pkg_resources` 弃用警告。
- Ruff 在 `server` 工作目录、使用项目配置，对完整 PR 与本次改动的 **30 个现存 Python 文件**逐个显式检查通过；不以目录发现代替变更文件集合。
- 保留的真实性能比较 `--check` 三组通过；默认提示词实验离线成功，无站点 POST 或真实模型调用。
- 内容 `--check` **仍返回 1**：新侧 78 个检查槽中 67 个满足、11 个未满足，歌词全文为 9/12。未改写语料或 oracle，不把已知缺口改成通过。
- 独立代码审查发现的渲染标点/关键词边界、制作信息过滤、明确多版渲染及无歌词 Person 入口问题均修复并补回归；这不代替维护者审核。

复跑相关测试可从 `server` 使用 `python -X utf8=0 -m pytest tests/unit/world tests/integration/world tests/integration/packaging tests/integration/agent/test_song_knowledge_acceptance.py -q -p no:cacheprovider --basetemp=<新的临时目录>`，再以 `-X utf8=1` 和另一临时目录重跑。性能、内容及提示词命令沿用[样本说明](../vcpedia_corpus/README.md)与[World 测试说明](../../unit/world/README.md)，输出到新目录，不覆盖历史报告。

未运行全量 unit、真实站点、真实模型或生产数据重验；下列历史内容验收和材料权利事项仍开放。本轮未提交、推送或关闭 #196。

## 2026-10-02 减法

- 保留单一输入 manifest、独立内容 oracle、已有真实原件、旧 HTML 对照、提示词实验、性能与内容报告。fixture 读取只用小模块，不另设 CLI 或认证框架；不扩大第三方素材、不重新生成预期。
- 删除重复元数据、选材/历史文档台账及专属脚本、测试；一次选材调查留作静态记录。官方活跃页记录仅为 manifest 的背景信息，不是普通测试前置条件；不再自动选材、审计提交数量或测试历史文档条款。
- **N8：撤回自制 commit proof / 提交认证机制，不撤回 Ruff。** 使用锁定 Ruff 0.14.10 和项目规则，对 PR 变更 Python 文件显式运行标准检查；不引入新的 CI 流程。
- 内容 `--check` 改为本次声明范围内当前解析器满足全部独立预期才返回 0。已知缺口仍报告，不要求旧/新实现保持错误，也不靠固定失败快照把测试刷绿。性能比较不设固定页数或第二份锁文件，每次报告实际样本身份。

## 仍未完成

- 原当日列表 **24 首**同批新旧比较，以及“刹那芳华 **64→723**”仍缺原同批输入/版本证据；不能由精选语料替代。
- 当前内容仍有缺口：Foxy、Sharing、社畜的歌词与部分简介事实尚未满足独立预期。因此内容 `--check` 当前应退出 1；默认仅生成报告成功可退出 0，不代表效果达标。槽位有重叠，不称独立缺陷数或准确率。
- 本轮未取得真实补提模型端到端质量、生产库存量重验或全站等价证据；第三方歌词等再分发权利仍需维护者核验。
- #196 的未完成验收不因工具精简关闭。进行中 spec 保留；完成后按[开发守则](../../../../docs/开发守则.md)另开清理工单处理。

## 历史报告

[results/](results/)保留原报告，不覆写为本轮结果。下列链接固定在清理前提交；测试数量、样本集合、运行环境、失败与旧成功码仅属于当时运行，不能沿用作本轮通过结论。尤其旧内容报告的 `--check=0` 只是当时“与已审状态一致”，不是全部正确。

| 历史批次 | 验证 | 内容 | 性能 |
| --- | --- | --- | --- |
| 5b7b932 批次 | [validation](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/validation.json) | [effect](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/effect.json) | [performance](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/performance.json) |
| N6 / N8–N15 批次 | [validation](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/validation-n6-n15.json) | [effect](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/effect-n6-n15.json) | [performance](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/results/performance-n6-n15.json) |

旧规范去向、早期调查和声明纠正见[清理前记录](https://github.com/SheepLiu712/Agent-LuoTianyi/blob/c3521126a8a8907cce5762183d4b9d2647824a8f/server/tests/support/vcpedia_review/README.md)。不继续维护历史清单或双向条款核验框架。

本次减法验证：标准Ruff0.14.10显式检查27个剩余PR变更Python文件通过；world单元、world集成及packaging在cp936/GBK和UTF-8两种模式下各546 passed。提示词默认离线成功；性能三组检查通过；内容报告生成成功，但`--check`因当前未满足槽位返回1，不能宣称产品效果全部通过。全量单测、真实站点及真实模型本次未重跑，原有内容缺口和权利问题未因此消失。
