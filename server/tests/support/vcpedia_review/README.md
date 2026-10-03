# VCPedia PR #195 审查记录

关联 [PR #195](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/195) / [Issue #196](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/196)。产品约束只维护[进行中 spec](../../../../docs/开发进程文档/vcpedia-wikitext-migration.md)；操作见[World 测试说明](../../unit/world/README.md)和[语料说明](../vcpedia_corpus/README.md)。

## 本次减法

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
