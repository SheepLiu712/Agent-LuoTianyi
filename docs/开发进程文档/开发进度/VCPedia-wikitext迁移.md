# VCPedia wikitext 迁移

- 大目标：仅迁移新歌抓取的内部 API/wikitext 实现，外部接口与行为保持不变；直接沿用原有抓取说明，不新增兼容契约。
- PRD：[VCPedia-wikitext迁移](../需求说明（PRD）/VCPedia-wikitext迁移.md)
- 原有抓取说明：[项目架构中的 get_new_songs](../../项目说明/项目架构与接口（spec）/项目架构.md)，以及上述 world 文档的新歌使用示例。
- 总体状态：进行中；兼容迁移基线已完成本地离线验证，由 `refactor/vcpedia-wikitext` 本次基线 commit 收录；未合并，owner 目标尚未交付，尚未证明全站外部行为等价。

## 已完成

### 2026-09-09 兼容迁移基线提交前验证

- 范围：按用户明确授权，将既有两个 fetcher、内部 `wiki_api.py`/`wikitext_parser.py`、requirements、公开入口回归与两个固定语料、真实测试隔离、PRD 和本进度记录作为一个完整 baseline commit 收录。未开始 owner 新功能，未修改产品实现、测试或公开 interface；没有补造过去 SPEC/Red/Green commit。
- SPEC 检查：沿用原项目架构与 world 接口说明，现有入口不扩大；本次仅冻结已有兼容迁移，不新增接口文档、网络 marker 或启用开关。历史条目中的 HEAD 均指各条目执行时迁移前版本，不指本基线提交后的 HEAD；历史 Red/Green 运行记录并非独立提交历史。
- commit 定位：分支 `refactor/vcpedia-wikitext`，本次标题 `refactor(world): 将 VCPedia 抓取迁移至 wikitext`。本条写于提交前，不编造 hash；提交事实以 Git 历史为准，不代表已 push、PR、合并或发布。
- 实际回归：`conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/baseline-commit-regression-20260909-1` → **116 passed, 1 deselected in 5.80s**。
- 实际收集：同四组、同 `-k 'not live'`，使用 `--collect-only -q -p no:cacheprovider --basetemp=data/test_outputs/baseline-commit-collect-20260909-1` → **116/117 tests collected (1 deselected) in 4.62s**。排除的一个测试为真实 live 测试，没有永久跳过。
- 实际静态检查：`conda run -n lty --cwd server python -m compileall -q src/world/get_new_songs tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`git diff --check` 均通过。
- 提交前只读自审：逐项读取当前 diff 与全部 7 个可列出的 untracked 文件，核对内部入口引用、失败语义、临时数据库/关键词/缓存隔离及 curl 超时和无 shell 调用；未发现本次新增的确定安全或兼容阻断。只明确暂存迁移的 11 个文件，缓存、日志、本机配置、生产配置不纳入；根 `.pytest_cache` 权限警告保留，不尝试修改其权限或内容。自审不替代他人审核。
- 当前依赖清单实际仅新增未锁版本的 `mwparserfromhell`，不采用下方历史记录的版本范围；本次未安装或升级依赖，也未执行联网依赖漏洞审计。两个内部文件现合计 495 行，旧“约 300 行”仅是历史阶段体量；整体作为用户授权的完整数据通道基线提交，不拆成仅列表或缺详情的半迁移。
- 未验证：本次未联网；历史真实 requests 挑战后 curl HTTP 403 尚无成功验证。真实 API/详情/入库、curl 通过挑战、未知模板/Lua/动态渲染及全站等价、全 Server/LLM/GPU/生产环境均未验收。既有缓存写入缺失、批次无限制和嵌套事件循环 LLM 问题未改动，不作为 owner 目标已交付的证据。

### 2026-09-09 修复独立审查发现的 tabs 标题作用域泄漏（本地未提交）

- HEAD 旧公开入口核准 4 个人工匹配 HTML/wikitext 样例。`{{tabs|text1=<h2>歌词</h2>}}<poem>外部歌词</poem>` 恢复旧 `lyrics/spaced_lyrics=""`；简介不采外部正文、标题不跨页签，tabs 内有正文和歌词仍正常采集。标题发现不再展平参数到父级；每个参数独立递归，保留参数内 wiki 标题必要重解析。仅改内部解析器及公开入口回归，不改 API/反爬或公开 interface。
- 实际命令统一前缀 `conda run -n lty --cwd server python -m pytest`，选项 `-q --tb=short -p no:cacheprovider`。`tests/world -k tabs_heading_keeps_parameter_sibling_scope`，basetemp `data/test_outputs/tabs-scope-red-1`：**3 failed, 1 passed，5.30s**，均为泄漏输出断言失败；修复后 `tests/world -k 'tabs_heading_keeps_parameter_sibling_scope or compat2_global_headers'`，basetemp `data/test_outputs/tabs-scope-green-1`：**8 passed，3.96s**。
- 原四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，独立 basetemp `data/test_outputs/tabs-scope-regression-1`：**116 passed, 1 deselected，6.01s**。同范围 collect-only，独立 basetemp `data/test_outputs/tabs-scope-collect-1`：**116/117 collected，4.89s**；逐项确认原 112 个选中 ID 全保留，仅新增四例。conda lty compileall（抓取包与上述测试）、`git diff --check` 通过。
- 完成 Red/Green 作者自审：仅恢复标题局部同级边界，未增加通用 DOM 层；自审不替代独立审核。保留已有改动，无 commit/push/PR。未联网或重测性能；真实 API/curl 成功、全站等价、未知模板/Lua/动态渲染及全 Server/生产环境仍未验证。

### 2026-09-09 继续取消前兼容修复与内部优化（本地未提交）

- 接手实测四组离线基线 **89 passed, 1 deselected，5.64s**：取消前已留下四类修复和 14 个测试，全部保留，不回退制造 Red。重新运行仓库外 HEAD 校准脚本，通过旧公开入口核验 **8 个详情、4 个列表 HTML 样例**；人工匹配 wikitext，不是真实站点采样。显式/容器内标题仍返回 Song、正文及完整歌词；noinclude 两条、includeonly 一条、onlyinclude 三条；简介不采额外 div/直接 table；列表甲乙丙、简介甲乙丙丁均与旧输出一致。
- 补发现 tabs 参数标题为 Text 的遗漏：公开入口 focused Red **1 failed, 3 passed，5.39s**，实际为 Person/空简介/空歌词；仅在模板展开边界恢复必要重解析后，四类 focused Green **15 passed，4.15s**。对应命令前缀 `conda run -n lty --cwd server python -m pytest tests/world`，分别使用 `-k compat2_global_headers` / `-k compat2`，`-q --tb=short -p no:cacheprovider`，独立 `--basetemp=data/test_outputs/resume-header-red-1` / `resume-fix-green-1`。原有四类修复本次为补回归，未将临时目录存在当成历史 Red 证据。
- 修复自审后再优化：复用已解析节点，保留模板标题必要重解析；歌词首 p 之后复制局部树再移除 br，不改共享树；首 p/table/poem/infobox 使用惰性标签查找，保留递归顺序与空容器停止；标题清理复用、模板名每阶段共用一次规范化结果、参数/属性消除重复查询，保留 Songbox 后创作者的两阶段覆盖，无全局缓存或通用 DOM 引擎。每份 HTTP 正文仅 JSON 解码一次，403 挑战优先、合法 JSON 中 Anubis 不误判、原 HTTP raise 优先；null/其他非对象仍失败，curl 兜底与列表抛错/详情 None 不变。
- 新增 22 个外部 HTTP/curl fake 回归（403 JSON、500 JSON/非 JSON、null/数组/JSON 字符串等）首次即通过，不记 Red。优化前后同四组、`-k 'not live' -q --tb=short -p no:cacheprovider`，独立 basetemp `data/test_outputs/resume-opt-before-1` / `resume-final-2`，均 **112 passed, 1 deselected**，分别 **6.33s / 6.06s**；完整范围为 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`。同范围 collect-only 前后 **112 个选中 node ID 完全一致**。同 conda 前缀 compileall 上述测试与 `src/world/get_new_songs`、`git diff --check` 通过。
- 仓库外诊断基准（非内部契约测试）：57 对列表/详情语料输出前后一致，曾捕获优化引入的前导冒号显示差异，修正后重新全部核验。两个固定 fixture 各 300 次 × 5 轮中位单次耗时：列表 **1.0328 → 0.8246 ms**，mw.parse **10 → 4**；详情 **3.3941 → 3.4541 ms**，mw.parse **7 → 6**。列表约改善 20%，详情无明显改善，不声称整体性能提升。
- SPEC 已满足，沿用原入口，未新增 interface 文档/网络 marker/汇总歌词/目标标题/创作者摘要。已按 code-review-and-quality 完成修复与优化自审，不替代独立审核。分支仍为 `refactor/vcpedia-wikitext`，无 commit/push/PR，故无 SPEC/Red/Green commit。
- 未验证：未重复联网，已知真实 curl 403 不变；真实 API/curl 成功、全站等价、未知模板/Lua/动态渲染、全 Server/LLM/GPU/生产环境未验证。

### 2026-09-09 同包内部命名与类型整理（本地未提交）

- SPEC 已满足；仅机械改名与注解，Red 不适用。两个内部文件现为 `server/src/world/get_new_songs/wiki_api.py`、`server/src/world/get_new_songs/wikitext_parser.py`；两个 fetcher 同步调用 `fetch_wikitext`、`parse_song_titles`、`parse_details`，文件内部 helper 保持原名。不新增公开 interface 或接口文档。
- 类型沿用 typing 风格：请求入口接收字符串 base_url/title、`Callable[..., Response]` 和数值秒数 `float`（兼容现有 int），返回 str；列表接收 str，返回 `List[str]`；详情接收 source/title 两个 str，返回 `Dict[str, Union[str, Dict[str, str], List[str]]]`。不引入 Protocol、TypedDict 或新数据模型；Callable 的省略号保留 requests.get/Session.get 的关键字调用方式，不声称静态检查其关键字签名。
- 本次真实前后命令均为 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/naming-{before,after}-run-20260909`（分别展开 before/after 执行）：改前 **75 passed, 1 deselected in 8.09s**，改后 **75 passed, 1 deselected in 4.71s**。
- 同一范围、相同 `-k 'not live'`，将运行选项改为 `--collect-only -q -p no:cacheprovider`，独立 basetemp 为 `data/test_outputs/naming-{before,after}-collect-20260909`：前后均 **75/76 tests collected (1 deselected)**，分别 4.80s/4.68s；逐项比较 75 个选中 node ID 完全一致。仅本次离线选择，未添加网络门禁。
- `conda run -n lty --cwd server python -m compileall -q src/world/get_new_songs tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py` 与 `git diff --check` 通过。一次批量编辑命令因 shell 转义导致脚本语法错误，在写入前失败，随后完成精确替换；不计为 Red 或产品测试失败。
- 作者自审：按 code-review-and-quality 五轴核对改前源码副本与改后独立 diff，仅文件名、函数名、导入和注解变化，函数体逻辑无变动；旧源码路径/名称引用无残留，新入口无同名定义冲突。未改输出、异常处理、反爬、API 请求、解析、依赖或测试；历史文件引用仅更新当前定位，不生成历史新运行。自审不替代独立审核。
- 分支仍为 `refactor/vcpedia-wikitext`，原有未提交改动保留，无 commit/push/PR/合并，无 SPEC/Red/Green commit。未重复联网；已知真实 curl HTTP 403 不变，真实 API/curl 成功、全站等价、未知模板/Lua/动态渲染、全 Server/LLM/GPU/生产环境及静态类型检查器均未验证。

### 2026-09-09 修复独立审查的四项确定兼容差异（本地未提交）

- SPEC 已满足：已读取 AGENTS、开发守则、spec-tdd-pr-guard、迁移 PRD、原抓取说明与 world 接口。沿用 `VCPediaFetcher.fetch_entity_description` 和 `do_one_song`，不新增接口文档、不改变旧外部语义。全部已有未提交改动保留；分支仍为 `refactor/vcpedia-wikitext`，无 commit/push/PR/合并，也无 SPEC/Red/Green commit。
- 交付：恢复显式 `Tabs`/`tabLabelTop` 容器首个 div.poem、首 p 与停止查找规则（空 Tabs 也停止，不任意递归汇总）；保留普通命名空间及前导冒号可见链接的文案，区分文件嵌入/分类声明；使用 mwparserfromhell 本地源码节点恢复显式 infobox、简介 div 首 table、歌词首 table 的旧选择和双列/单列行提取，保留 br、隐藏行、图片行和 navbox 停止语义；span 内 br 无分隔，不同 span 间仍为空格。
- HEAD 对照：仓库外临时脚本 `check_head.py` 使用 `git show HEAD:server/src/world/get_new_songs/vcpedia_fetcher.py` 加载旧实现，只替换 requests 外部响应，调用旧公开入口核对完整返回值。最终 **6 个歌词、2 个链接、7 个表格样例全部匹配**。测试中的 HTML/wikitext 是人工对应 fixture，不是真实站点采样；期望不来自新解析器。
- 下游补回归：通过真实 `do_one_song → fetch_entity_description` 连接，临时 SQLite 验证 singers=洛天依、命名空间作者简介与歌词；临时关键词文件验证 Tabs 完整句，以及 span/br 合并后的六字“第一句第二句”未丢失。仅 fake 外部网络/进程，不 mock 内部解析、入库或关键词步骤，Session 关闭、engine dispose。此两例及追加的 3 个表格边界首次运行即通过，记为补回归，不伪造 Red。
- 以下命令统一展示为从仓库根目录运行的相对路径形式，Python 命令使用前缀 `conda run -n lty --cwd 'server'`，pytest 禁用 cacheprovider，独立 basetemp。按紧密行为组依次 Red→Green，每组确认输出断言失败后才改最小 helper。

| 阶段 | 实际命令（接上述前缀） | 结果 |
| --- | --- | --- |
| HEAD 最终核对 | 仓库外临时脚本核对（见上文） | 6/2/7 matched |
| 歌词 Red（问题 1、4） | `python -m pytest tests/world -k head_repair_lyrics -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-lyrics-red-1` | 5 failed, 1 passed, 45 deselected，4.96s；容器漏采/错误继续查找及 span/br 多空格 |
| 歌词 Green | `python -m pytest tests/world -k head_repair_lyrics -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-lyrics-green-1` | 6 passed, 45 deselected，3.58s |
| 链接 Red（问题 2） | `python -m pytest tests/world -k head_repair_links -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-links-red-1` | 2 failed, 51 deselected，4.86s；简介/infobox/歌词可见文案丢失 |
| 链接 Green | `python -m pytest tests/world -k head_repair_links -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-links-green-1` | 2 passed, 51 deselected，3.64s |
| 表格 Red（问题 3） | `python -m pytest tests/world -k head_repair_tables -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-tables-red-1` | 4 failed, 53 deselected，4.86s；infobox 空及简介误含表格文本 |
| 表格 Green | `python -m pytest tests/world -k head_repair_tables -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-tables-green-1` | 4 passed, 53 deselected，3.59s |
| 四组回归 | `python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/fix-regression-1` | **75 passed, 1 deselected，5.97s** |
| 完整收集 | `python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py --collect-only -q -p no:cacheprovider --basetemp=data/test_outputs/fix-collect-1` | **76 tests collected，19.20s**，包含 live |
| 编译 | `python -m compileall -q src/world/get_new_songs tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py` | 通过 |

- 作者自审：已加载 code-review-and-quality，核对 HEAD 选择/停止规则、测试外部边界和资源隔离；产品修正仅在 `server/src/world/get_new_songs/wikitext_parser.py`（按当前文件定位，历史验证未重跑），没有新增依赖、网络 HTML fallback、远程模板展开或通用 DOM 层。API+wikitext 与全站反爬 curl 保留不动。`git diff --check` 通过；原已有 tracked diff 文件及未跟踪文件保留。自审不替代更新后独立审核。
- 未验证：本次不重复联网，最新真实结果仍为 requests 挑战后 curl HTTP 403（见下条记录）；真实 API 成功、真实详情/入库、curl 成功通过挑战、全站等价、未知模板/Lua/动态渲染、全 Server/LLM/GPU/生产环境均未验证。`-k 'not live'` 仅本次测试选择，没有新增 real_network marker、开关或永久跳过规则。

### 2026-09-09 删除迁移网络门禁并直接联网验证（本地未提交）

- 按用户明确要求覆盖本次外网默认标记规则：删除迁移新增的外网 marker、启用选项和跳过逻辑，conftest 恢复 HEAD 的真实 LLM 配置（含环境变量启用及原跳过说明）。真实测试本体保留，没有增加替代网络限制。PRD 同步直接运行方式；下文 skipped/未联网为各历史阶段事实，不代表当前配置或本次结果。
- SPEC 已满足：沿用 world 任务入口，不改变产品代码、公开接口、批次、缓存策略、调度或反爬行为。配置清理的运行时 Red 不适用；缓存隔离属于旧测试最小修正，不伪造产品 Red。
- 隔离修正：旧测试设置的 crawler.output_dir 并非实际缓存配置，已改为 tmp_path 下的 crawler.data_dir 与 crawler.vcpedia.output_dir；SQLite 和关键词目录仍使用 tmp_path。测试恢复真实 0.8 秒节流，不再 monkeypatch sleep；数据库全局绑定由 monkeypatch 恢复，临时 engine 在 finally dispose。关闭 LLM，没有调用模型或修改生产数据。
- 以下命令展示为从仓库根目录运行的相对路径形式，使用前缀 `conda run -n lty --cwd 'server'`；elapsed 为 Git Bash time 的整条命令墙钟时间，pytest 时间另列。
- 真实联网命令：`python -m pytest tests/test_world_task_vcpedia_new_songs.py::test_vcpedia_run_once_fetches_live_songs_and_writes_result -vv -s --tb=short -p no:cacheprovider --basetemp=data/test_outputs/live-direct-20260909-1`。工具超时 600000 ms，实际 **1 failed in 5.64s，elapsed 13.648s，exit 1**。requests 被既有逻辑识别为挑战，自动 curl 兜底返回 **HTTP 403**，原始错误为 `curl fallback failed: curl: (22) The requested URL returned error: 403`。未额外重试、批量抓取或绕过反爬；运行机日志时间为 2026-09-10 01:11:15。
- 实际副作用：写入 `server/data/test_outputs/vcpedia_new_songs_latest.json`，记录 ok=false、added/failed 均为空；创建 `server/data/test_outputs/live-direct-20260909-1/test_vcpedia_run_once_fetches_0/knowledge/knowledge_db.db`，只读核验 songs 为 **0 行**，该 live 临时目录只有此数据库文件，无关键词或缓存文件。失败发生在列表获取，尚未进入歌曲详情抓取。配置加载提示若干环境密钥未设置，但本次失败原因是 HTTP 403，不是密钥问题。
- 离线命令：`python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/offline-direct-20260909-1` → **58 passed, 1 deselected in 4.84s，elapsed 12.788s**。
- 收集命令：`python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py --collect-only -q -p no:cacheprovider` → **59 tests collected in 4.50s，elapsed 12.415s**，包括 live 测试。过时外网 marker/选项引用搜索无匹配；`git diff --check` 通过。
- 作者自审：已加载 code-review-and-quality，核对本次配置删除、缓存/数据库/关键词隔离、错误真实性及最小差异；未修改其余既有未提交产品实现。分支仍为 refactor/vcpedia-wikitext，无 commit/push/PR/合并，无本次 SPEC/Red/Green commit；自审不替代他人审核。
- 未验证范围：真实 API 成功响应、真实详情解析与入库、curl 成功通过挑战、全站与旧实现行为等价均未验证；全 Server、真实 LLM/GPU 和生产环境未运行。此次联网失败不得表述为迁移验收通过；既有产品批次无上限等问题未修改。

### 2026-09-09 恢复可确定的旧抓取输出（本地未提交）

- 依据：读取 AGENTS、开发守则、spec-tdd-pr-guard、原抓取说明、world 接口及 HEAD 两个旧抓取实现。沿用现有入口，不创建接口契约文档；PRD 补充恢复原行为验收。此记录取代下文历史迁移测试对“目标标题、汇总歌词、追加创作者简介”等行为的认可，不抹去历史实现事实。
- 可信对照：测试文件内 LIST_SOURCE/LIST_HTML 和 HEAD_DETAIL_CASES 为人工匹配的源码/渲染 HTML，不是真实站点采样。在 conda lty/server cwd 下用 `git show HEAD:server/src/world/get_new_songs/{daily_new_song_fetcher,vcpedia_fetcher}.py` 加载旧实现，只替换 requests 外部网络响应，实际调用两个旧公开入口。核验结果为 `HEAD detail: 5 matched`、`HEAD list: matched`；包括旧无简介时的 `[""]` 输出，不把新实现当期望。
- 交付：列表恢复显示名、去星号、显示名去重及旧文本/链接过滤；不增加全局目标映射，旧显示名抓错问题保持原状。详情恢复 h2 歌词分类、Person 不额外返回 short_summary、创作者不追加 summary、简介 h3 截断及“截至…收藏”删除、不汇总多版本/标题外歌词、最后歌词 h2 后首个 poem/p 的 span 优先与 br 无分隔格式。过滤明确的 image/width/style 等展示控制参数。API 共享反爬/curl 实现未修改，两个入口挑战及失败回归保留。
- 下游验证：通过 fetch_song_list_from_template → do_one_song → VCPediaFetcher 的真实连接，临时 SQLite 验证显示歌名的请求身份、name/safe_name、查重、简介、歌词与关键词文件；没有改动数据库、调度或 LLM 策略。
- 有效 Red（以下以仓库根目录下的相对路径形式展示，命令前缀为 `conda run -n lty --cwd 'server'` 执行）：`python -m pytest tests/world -k 'head_detail or head_display' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/compat-red-1` → **6 failed, 41 deselected in 4.84s**，均为目标输出断言失败，无导入/语法错误。Windows conda 不支持多行 -c 的启动失败、一次旧期望校准失败均不计入 Red。
- Green：同前缀执行 `python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/compat-regression-2` → **58 passed, 1 skipped in 5.66s**。中间模块验证曾为 38 passed/9 failed，失败项为固化新行为的迁移预期，已按旧选择/格式规则修正或以可信对照替换。
- 收集：同前缀执行 `python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py --collect-only -q -p no:cacheprovider --basetemp=data/test_outputs/compat-collect-2` → **59 tests collected in 4.57s**；跳过项为真实网络测试。
- 静态验证：同前缀执行 `python -m compileall -q src/world/get_new_songs tests/world tests/conftest.py tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py` 通过；仓库 `git diff --check` 通过。
- 作者自审：已加载 code-review-and-quality，核对公开入口测试、旧输出依据、最小内部修正、无新增网络请求/全局状态/依赖/HTML fallback。分支 refactor/vcpedia-wikitext，未 commit/push/PR/合并，无 SPEC/Red/Green commit；作者自审不替代独立审核。
- 未保证范围：源码离线解析不能还原远程模板/Lua/动态计数；未删除整句不代表未知计数已还原。模板生成的 span/ruby/ref、Tabs/div 嵌套后的真实 DOM 同级关系、段落/列表空白、无简介首个 h2 含复杂子节点、infobox 动态标签/条件行及未列举展示参数仍可能与 HEAD 不同；列表未知模板展开、功能链接生成与命名空间渲染也未证明全覆盖。已移除无依据的“全部歌词/嵌套简介无损”预期，不声称任意 Lyrics/Songbox 模板等价。没有访问真实 API、验证真实 curl 突破反爬、运行全 Server/真实 LLM/GPU 或生产数据库。

### 2026-09-09 模板与完整详情 API/wikitext 迁移

- 本地实现：保留 fetch_song_list_from_template/VCPediaFetcher 调用形状，内部改用 API/wikitext 与共享挑战识别、curl 兜底，替换 HTML 解析。节点提取属于实现细节，不构成新的公开契约；调用形状和下游代码未变不能证明发现结果、详情内容及入库效果不变。
- 离线 fixture 为人工合成的固定源码，不声称是实时站点采样。覆盖管道身份、命名空间/锚点/占位符、lj、Songbox、创作者名单、标题内外两种 tabs、poem/标签/歌词模板、两个入口的挑战/错误，以及真实临时 SQLite 和关键词文件。
- 历史验证范围：该阶段没有运行真实联网测试；本次迁移新增的网络门禁现已移除，真实测试直接执行，LLM 测试规则不变。实际联网结果见后续独立记录。
- 分支：refactor/vcpedia-wikitext。未执行 commit/push/PR/合并，因此没有 SPEC/Red/Green commit。作者自审不代替他人审核。
- 依赖清单新增 mwparserfromhell >=0.7.2,<0.8（MIT，无传递依赖）。

### 2026-09-09 混合歌词与嵌套章节修复

- 范围说明：以下为本地解析修正及其样例覆盖，不将“完整歌词、嵌套简介、仅剔除动态统计句”等解析规则追认为历史契约；既有说明未规定这些细则。回归测试从 VCPediaFetcher.fetch_entity_description 观察结果，但仍需与迁移前输出核对，不能据此宣称行为等价。
- 混合歌词：删除互斥回退，统一按源码顺序输出章节/独立歌词容器；外层容器消费其内容后不再重复采集子容器。覆盖 Lyrics+poem、章节内外混合及嵌套不重复三例。
- 统计句：保留 tabs 正文的原节点与句界，仅剔除含动态统计的句子，不再因子模板统计节点删除整个 tabs 正文。
- 活动章节：tabs/div/section 内部边界在自己的作用域处理，无内部标题继承外层；退出容器恢复外层，歌词及参考段不再混入简介。

### conda lty 验证

- 环境：conda `lty`，Python **3.10.20**（Anaconda，64 bit）。所有 Python/pytest/compileall 命令显式通过 `conda run -n lty` 执行。
- 依赖检查：pytest 9.1.1、pytest-asyncio 1.4.0、mwparserfromhell 0.7.2、requests 2.34.2、SQLAlchemy 2.0.51、chromadb 1.5.9、pydantic 2.13.4、loguru 0.7.3 均已安装；没有安装、升级或卸载依赖，没有全量安装 GPU requirements。
- 下列命令为相对路径写法，从仓库根目录运行，`--cwd server` 指定测试工作目录；结果保留对应阶段记录：

```bash
conda run -n lty python -c "import sys; print(sys.version); print(sys.executable)"
conda run -n lty --cwd 'server' python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -q --tb=short -p no:cacheprovider --basetemp='data/test_outputs/lty-env-regression-20260909-1'
conda run -n lty --cwd 'server' python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py --collect-only -q -p no:cacheprovider --basetemp='data/test_outputs/lty-env-collect-20260909-1'
conda run -n lty --cwd 'server' python -m compileall -q src/world/get_new_songs tests/world tests/conftest.py tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py
git diff --check
```

- 结果：受影响回归 **55 passed, 1 skipped in 12.62s**；同范围 **56 tests collected in 4.62s**；compileall 与 `git diff --check` 通过。跳过项为真实 VCPedia 网络测试。

#### 自审与验证边界

- 文档边界：沿用原有项目架构的新歌说明及 world 任务接口；API 不承诺免反爬，不新增跨模块接口或解析契约。历史离线记录不是本次文档修正重新执行的结果，也不证明旧新行为完全一致。
- 测试自审：从原入口观察业务结果，仅 fake 外部 HTTP/curl，使用临时数据库/文件。
- 实现自审：按正确性、可读性、架构、安全、性能核对；检查源码顺序、容器唯一消费、内部章节隔离和无标题继承；curl 无 shell、带超时和 HTTP 校验，JSON 正文中的 Anubis 不误触发挑战。
- 体量：两个内部 helper 约 300 行实现，替换约 300 行 HTML/不可达路径；加上契约测试和文档超出 500 行总 diff，但属于同一数据通道的完整兼容迁移，未拆成缺歌词或仅列表的半迁移。
- 未验证：没有请求真实站点/API，没有验证真实 curl 能突破当前反爬，没有执行全 Server 测试、真实 LLM/GPU 或生产数据库验收。任意未知模板/远程 Lua 展开不在离线解析能力内，未宣称全站页面无损；旧缓存写入缺失、批次无限制及嵌套事件循环 LLM 等既有问题未纳入本次改造。
