# World 单元测试

本目录验证World时钟、Runtime配置和任务局部行为；公网、生产凭据和真实模型不属于单元测试。数据库、Stage、Agent或结算路由场景在`tests/integration/world`，真实站点探测在`tests/e2e/external`。分层与执行说明见[`tests/README.md`](../../README.md)，不变量见[`tests/INVARIANTS.md`](../../INVARIANTS.md)。

## VCPedia

- [进行中spec](../../../../docs/开发进程文档/vcpedia-wikitext-migration.md)：唯一业务契约。
- [审查记录](../../support/vcpedia_review/README.md)：未完成项与历史报告，不维护审核框架。
- [样本与比较说明](../../support/vcpedia_corpus/README.md)：manifest、独立oracle、权利及内容/性能命令。

### 离线测试与Ruff

从`server`目录使用项目依赖环境执行。

```text
python -m pytest tests/unit/world -q
python -m pytest tests/integration/world tests/integration/packaging -q
```

Ruff锁定**0.14.10**，使用项目规则，包括C901，不使用`--isolated`。根据PR的base…HEAD及本次未提交变更，手工列出仍存在的全部变更`.py`文件（源码、工具、测试及新增文件），执行`python -m ruff check <逐个列出的PR变更.py路径>`。占位符须替换为实际文件列表；**列表为空就不执行，不能退回检查整个目录。** 目录发现受项目`include`影响，不能用单个目录退出0替代完整PR文件检查。不再使用自制提交认证脚本。

需验证Windows默认编码时分别使用`python -X utf8=0 -m pytest ...`与`python -X utf8=1 -m pytest ...`，记录`sys.flags.utf8_mode`及`locale.getpreferredencoding(False)`；只有实际为cp936/GBK才称GBK证据。

歌词恢复测试只验证已有源码的当前歌词与关键词，不单独证明旧HTML为空。内容测试验证已实现的真实正例和评分器行为，不要求已知错误保持不变；内容报告的`--check`当前因未满足独立预期应退出1。非空、字数或`needed`均不是完整性证明。原24首比较与刹那芳华64→723仍待原同批证据。

### 提示词实验

默认离线，标题映射使用manifest；输出使用新的`data/test_outputs`子目录，不提交凭据。

```text
python scripts/vcpedia_prompt_lab.py --material title:Foxy --out data/test_outputs/prompt-lab-local
```

`--dry-run`明确离线；`--live`才发出真实、可能计费的模型请求，需配置`extraction_llm_module`及provider/凭据。live仅支持配置中的OpenAI-compatible接口；`--provider`只覆盖显式live的补提provider，不回退总结模型。A/B使用`--prompt`与`--prompt-b`。工具复用生产材料与回答/合并校验，不发送片段POST，不代表完整在线采集验收。

性能与内容比较复用小fixture读取模块。普通测试不联网重验活跃页，不自动选材或断言历史文档；真实性能单列受控运行，不把本机毫秒数作为CI保证。
