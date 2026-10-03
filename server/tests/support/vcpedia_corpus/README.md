# VCPedia 离线样本与比较

只使用已有本地原件，不抓取或扩充第三方正文。[进行中 spec](../../../../docs/开发进程文档/vcpedia-wikitext-migration.md)规定业务行为，[审查记录](../vcpedia_review/README.md)列历史报告与未完成项。

## 输入与权利

- `manifest.json` 是唯一输入清单：相对路径、来源、必要hash、已知版本/配对依据、权利信息及各工具使用列表。内容与性能样本不要求相同，也不固定页数；报告必须写明本次实际样本身份。提示词实验的标题映射也取自manifest。
- `../vcpedia_samples.py` 只提供 `load_samples`、文本/原响应读取及必要hash检查；内容与性能工具复用它。不是CLI、自动选材或提交认证框架，也不维护第二份锁文件。
- HTML是MediaWiki `parse.text`片段，不是完整网页；源码/HTML须来自可证明的同一捕获，不能按同名页面混配。未知捕获时间或revision不推测，最后编辑者不等于结构作者。
- 官方活跃用户页只用于当时选材调查，结果作为manifest背景信息；不重新联网核验，不要求每次测试证明名单完整，操作数不称编辑数。删除的台账与行为快照仅由Git历史保留。
- 许可见[浏览前必读](https://vcpedia.cn/VCPedia:%E6%B5%8F%E8%A7%88%E5%89%8D%E5%BF%85%E8%AF%BB)（取证oldid 585010，已有原页`evidence/site-terms.html`）。2026-09-16后站点授权编辑文本适用CC BY-NC-SA 4.0，更早部分可能适用3.0 CN；**歌词、引文、媒体不因此获得整体CC授权，更不变成项目MIT素材。** 保留原件版权提示，不扩大材料；再分发权利仍需维护者核验。

## 独立内容预期

`oracle.json`来自对应源码/HTML的独立人工核对，不用当前解析器生成或自动更新。按记录的首候选/章节选块，不拼接所有poem，也不将不同版本、译文或旁注合成一个分母。

`lyrics_exact`是zh-cn字形归一、去Unicode空白后精确一致，不证明原字形和段落保真；保护字形、Ruby和括号和声另用字面断言。歌词全文、代表行顺序、信息框值、简介事实分列，其中全文与派生代表行检查重叠，不能当准确率或独立缺陷数。来源存在性测试不等于自动验证章节归属或容器完整性。

内容报告保留旧/新逐字段结果及known gaps。**`--check`仅在当前解析器满足本次声明范围全部独立预期时退出0；当前仍有内容缺口，应退出1。** 默认仅生成报告，成功可退出0，不代表效果达标。Foxy、Sharing、社畜及部分简介事实的问题不能用“与历史失败一致”判为通过；pytest保留已实现内容正例及fake scorer的正确/错误行为，不要求任何已知错误永久存在。原24首比较与刹那芳华64→723仍未补齐证据。

## 命令

从`server`目录使用项目依赖环境；输出与pytest临时目录放在语料目录外，使用新的名字，勿覆写历史报告或oracle。

```text
python tests/support/vcpedia_corpus/oracle_support.py --manifest tests/support/vcpedia_corpus/manifest.json --output data/test_outputs/effect-UNIQUE.json
python scripts/vcpedia_perf_baseline.py --manifest tests/support/vcpedia_corpus/manifest.json --output data/test_outputs/performance-UNIQUE.json --check
python -m pytest tests/unit/world/test_vcpedia_corpus_baseline.py tests/unit/world/test_vcpedia_perf_baseline.py -q -p no:cacheprovider --basetemp=data/test_outputs/pytest-corpus-UNIQUE
```

内容命令可追加`--check`检查完整满足情况；不要将它当前的非0退出码改写为普通pytest失败或全绿。两比较工具均保留`--manifest --output [--check]`，缺输入、读取或解析错误不能算成功。

## 性能范围

旧侧为commit `910af449680091e339e0e6fd517d08c1f5222923`的真实HTML抽取算法，原文保存在`reference/vcpedia_fetcher.py.txt`，适配在`../vcpedia_legacy_html.py`；不是简化poem模拟。新侧使用生产解析器，二者均抽取完整字段。读取、hash检查、导入、初始化、网络和LLM在计时外。

每页2次预热、9轮正式测量，交替先后，共3组。报告原始测量、每页中位数、配对比中位数、整组中位耗时总和之比、实际输入身份和运行版本；输入文件字节比不是网络传输比。`--check`要求3组新侧中位耗时总和均小于旧侧，**无最低改善裕量或统计显著性承诺**。更换输入或环境需新测，旧报告不自动升级；普通单测只验证统计、顺序和失败语义，不以本机计时约束所有CI机器。
