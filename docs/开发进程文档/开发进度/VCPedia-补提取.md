# VCPedia 补提取

- 大目标：改善陌生格式的歌手、UP主、歌词、简介提取，保留原入口与持久化/调度。
- PRD：[补提取](../需求说明（PRD）/VCPedia-补提取.md)
- 设计与 interface：[world 补提取](../../项目说明/项目架构与接口（spec）/接口文档/world/vcpedia-extraction.md)
- 总体状态：已按最新授权收缩为独立提取，本地验证完成，未提交或合并。以下旧 scope/缓存/批次/补偿及来源判卷记录仅为历史事实；扩大方案已退役，不是现行契约。与兼容迁移进度分开记录。

## 已完成

### 2026-09-09 Ruby 缺口跟随选用分支（本地未提交）

- 修复上条引入的回归：五组缺口记录使 Ruby 表层与注音共用缺口集合，表层非空时未采用的注音内容仍被标记，完整歌词被误判待补。现只提交实际采用分支的缺口——表层非空以表层取文为准，表层为空回退取注音时按注音结果标记；不改变单值选择、不新增版本标签或模板专用规则。
- 用例 `test_ruby_gaps_follow_selected_text` 参数化 3 种标注形式（模板/显式 rb/隐式 rb）× 4 组表层与注音，共 12 例。Red 证据两路：以 `approved-five-20260909-a/before` 旧解析器运行同组用例 → **6 failed / 6 passed**（selected-* 未记录缺口，即本切片新增要求）；另一方向由独立审查以公开入口复现——完整表层＋未知注音得到 `needed.lyrics=true` 且 2 次调用，修复后同例仅 1 次摘要。
- 验证：当前解析器同组用例 12 passed；四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`、禁 cacheprovider、独立 `data/test_outputs/ruby-gap-final` → **321 passed / 1 deselected，49.48s**；同范围 collect **322 collected**，`compileall -q src/world/get_new_songs tests/world` 与 `git diff --check` 退出 0。
- 契约：`vcpedia-extraction.md` 缺失补提段补一句“含表层的结构只提交实际采用分支的缺口”。
- 未验证：真实站点/模型、全 Server、生产。保留 HEAD `96c8726` 与全部其他未提交工作，无 commit/push/PR，零网络/模型。

### 2026-09-09 五组目标缺口与局部传输修复（本地未提交）

- 按已批准边界完成：明确正文取文缺口不被其他非空候选清除；Embed 仅继承章节/已知正文槽，不以 page 文字授权；staff 视频保留原键、非空角色空值进入 needed；普通嵌套 div/隐藏内容聚合同一简介；局部 parse POST 表单 body、curl stdin，标题 GET 与原状态/challenge 校验不变。未增加模板适配家族、版本标签、语义判卷、公开接口或选择策略，原摘要 prompt 内容与 HEAD 相等（checkout 换行字节不同）。
- SPEC/Red/Green 逐组自审：五组新增公开 fetcher 回归首次分别 4 failed/4 passed、5 failed、2 failed、2 failed、5 failed，均目标行为失败。历史回放发现章节尾资料误报，补1例有效 Red 后收窄到正文路径；补提 prompt 原“按源码顺序采用第一候选”另1例 Red 后删除，明确未请求字段不覆盖，源码顺序不表示主次。中途比较命令语法错误不计 Red。
- 最终四组 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider`：独立 `data/test_outputs/approved-five-20260909-a/final2`，**309 passed / 1 deselected，55.54s**；独立 collect **309/310**，compileall 和 git diff --check 通过。保留既有 zhconv 弃用及根 cache 权限提示，不修改权限。
- 同目录冻结本轮 before，既有21缓存样本及冻结随机10页（7歌曲）通过公开 fetcher、HTTP 回放、独立摘要 stub/null 补提 stub 对照，禁外部网络/进程。21/21规则业务结果完全相同；随机仅神孽“视频=梦游睡大觉”、我生于死去之日。“视频=辻延soul”恢复，7/7歌词及简介选择不变。Sharing 仍617字符日文歌词但 needed.lyrics=true；Foxy/社畜仍空且待补；唱给雅音宫羽 jk“压线”漏提标 summary=true，不称 font 修复。
- 最终自然补提触发：缓存3/21、随机歌曲3/7，均非恢复准确率。另两缓存触发为山塘恋雨 poem 内未知 refn（可能注释误报）、I LOVE YOU(Adaa) 未支持 Photrans/font；未擅加规则。早期18/21缓存误报结果保留于 cache-after，最终收窄结果为 cache-final，before 不覆盖；null stub 不恢复内容，真实模型质量未验。
- 作者五轴自审完成，不能替代独立审核；无 Agent 工具，未声称独立复审完成。保留用户原工作、fixture 删除和 A–F 命名；task/daily/模板资源/转换模块未改。无 stage、SPEC/Red/Green commit、commit/push/PR、依赖安装、真实站点/模型或生产访问；全 Server、线上 POST/反爬与真实补提质量未验证。

### 2026-09-09 模板规则配置目录机械迁移（本地未提交）

- 当前定位为 `server/config/vcpedia_templates.json`，属于规则配置而非知识库；迁移前 config 无同名文件，仅移动原内容，2765字节及 SHA-256 `2573c674165745e0def65e9e444814fadb96630218e2f8c06461d772ddcc7121` 前后一致，旧文件不存在。下方旧路径仅描述当时新增位置，不改写历史或冻结证据。
- template_rules 仅更新源码 resolved 加载路径，仍独立于 cwd、初始化加载一次并冻结；公开 fetcher interface、规则及 JSON 正文不变。现行 PRD/spec/架构同步定位，既有公开配置测试加强为精确新路径断言；README 无旧定位，不扩写。
- 机械迁移 Red 不适用，SPEC 已满足。`conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_source_extraction.py -k template_resource -q --tb=short -p no:cacheprovider`，独立 basetemp `data/test_outputs/template-move-20260909-8c241-pre` / `template-move-20260909-8c241-post`：改前 **11 passed / 71 deselected，49.42s**，改后 **11 passed / 71 deselected，42.65s**；仅既有 zhconv 弃用警告。loader 与该测试 compileall、git diff --check 通过；全 repo rg 含非忽略 untracked 文档/测试，旧路径仅剩本文件历史条目，未扫描 ignored 历史输出。
- 限定范围检查完成，保留全部其他未提交工作与 HEAD96c8726；无 SPEC/Red/Green commit、commit/push/PR。未搬其他 knowledge/prompt 文件，未修改生产配置或配置模板正文，无依赖安装、网络、真实模型或生产访问；未运行全 Server 回归，不将 focused 结果作为全站验收。

### 2026-09-09 摘要与可选补提两个独立流程（本地未提交）

- 最新确认替代下方旧单次/参数继承历史方案：原 Song 摘要与可选 JSON 补提分离。完整页1次摘要；缺项且显式配置补提时先补提合并再1次摘要，共2次；补提坏 JSON/null/超时或注册失败不妨摘要。摘要失败取合并后简介前100字符，关闭/缓存0次，Person不新增摘要。
- 依据真实 LLMService.register_llm_module 与 LLMModule.generate_response：前者绑定固定 prompt，后者仅接受模板变量，无 per-call prompt API。因此两个显式完整配置直接注册，无继承、参数覆盖或新factory/shared API。task仅新增可选注册、局部异常日志及 keyword-only wiring；daily仅补传依赖。原摘要prompt与96c8726字节相等，旧可选拼接片段备份后退役，独立补提prompt仅字段JSON/正向null示例。配置模板仅增加独立extraction_llm_module，原摘要配置不变，use_llm统一控制；仅原配置不自动补提。生产配置未编辑。
- SPEC/Red自审后，公开task初始化→真实LLMService→Fake SDK契约8项Red（缺少已约定补提模块入口，无导入/环境错误）；补齐实现并扩展两provider/client委托成功及fallback、参数不变、merged摘要输入、缺失/损坏prompt、纯文本摘要及失败边界。原单次测试按新契约调整相关预期，保留字段/转换/人物/缓存与入库断言。中间日志sink与空字段样例期望纠正，不记为产品Red；一次conda多行参数不支持未执行文档修改，不计Red。
- 最终四组 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider`，独立 basetemp `data/test_outputs/two-independent-c74d2350bd344814ae4dc48499483ac3/final`：**288 passed / 1 deselected，49.82s**。同范围独立collect **288/289，1 deselected**；compileall及git diff --check通过，仅既有zhconv弃用警告。
- 同一ignored唯一目录保存改前任务/测试/配置模板/文档备份与本轮21份冻结源码before/after完整输出、请求和SHA对照：**21/21完全一致**，name/source材料不变，禁真实socket/子进程、模型关闭、空隔离缓存。source_extraction、template_rules、text_conversion、wikitext_parser、wiki_api本轮字节不变；原zhconv/nowiki/TextHover等修复保留。LLMService/LLMModule/PromptManager/shared runtime及provider/client/timeout路径未修改，无缓存metadata/SQL/budget新范围。
- 五轴作者自审完成，不替代他人审核。无SPEC/Red/Green commit、commit/push/PR，HEAD保持96c8726。无真实网络/模型/生产访问；未验全站、真实模型质量、真实客户端、全Server或性能，不以离线Green声称生产验收。

### 2026-09-09 结构转换复用 zhconv（本地未提交）

- 仅 template_rules 的 import / `_structure` 改为普通 `convert(str(text), 'zh-hans')`，删除1个独立结构转换实例；不叠加 zh-cn 地区词表，不新增补偿规则或公开 interface。PRD/提取契约当前职责同步，历史记录保留。HEAD requirements 对照确认固定版本行是未提交新增后，仅删除该1行；GSV 独立 requirements 的2处 opencc 配置保留，环境包未卸载，产品源码 active OpenCC 引用归零。
- 本轮当前配置全部字符串键/值（含 name/key/alias/content 参数）、21份冻结真实材料模板/参数/章节/tag/角色及 parser 字面量共6187项比较，仅 cached-14/15 同一个未知周刊模板名称的「」→“”不同；两边均不匹配描述，不影响分类。普通简介/歌词/角色及配置无差异；不宣称全字库等价。已核对 lty zhconv 的 zh-hans 仅用 zh2Hans、不叠加 zh2CN；仓库无 choosevariant 实现，不声称验证该函数。
- 同四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`，统一 `conda run -n lty --cwd server python -m pytest`、`-k 'not live' -q --tb=short -p no:cacheprovider`，独立 basetemp `data/test_outputs/structure-dedup-20260909-a/pre2` 与 `green`：改前 **275 passed / 1 deselected，49.91s**，改后 **275 passed / 1 deselected，46.37s**。测试文件字节未改、复用既有公开结构回归，无新增行为，Red 不适用。首次 pre 因 basetemp 父目录不存在产生环境 setup 错误，建立隔离父目录后重跑，不计产品 Red。同范围独立 collect **275/276（1 deselected）**、compileall、git diff --check 通过；保留既有 zhconv 弃用警告。
- `server/data/test_outputs/structure-dedup-20260909-a/` 保存本轮 before/after 全输出、请求记录、结构对照与改前文件哈希；**21/21 完整结果及请求一致**，不是沿用历史输出。回放在 requests 边界提供冻结真实 wikitext，禁真实 socket/子进程且模型关闭；无新网络/模型调用。text_conversion、parser、source、fetcher、task、资源和测试及所有其他原工作均保持本轮改前字节，仅额外同步本记录。
- SPEC 与 Green 五轴作者自审完成，不替代独立审核；没有 SPEC/Red/Green commit、commit/push/PR，HEAD 保持96c8726。无安装/卸载、生产访问；未验证全站、全字库、真实模型、全 Server 或性能，不以墙钟差异宣称提速。

### 2026-09-09 原单模块同次摘要与补提（本地未提交）

- 最新授权替代下列历史专用模块方案：新抓取 Song 保持原摘要时机，完整页一次 short_summary，缺项页同次补缺项和 short_summary；缓存、关闭、缺模块零调用。Person 分类及已有缺项补提保持，不加人物摘要或新人物需求。task 文件与 HEAD96c8726 字节一致，单注册 song_knowledge_crawler；source 仅材料/合并，额外注入和专用 prompt 已备份后移除。原 prompt 保留 song_data，可选材料仅缺项渲染；配置模板仅增加 use_json=true，生产配置及共享服务/委托未改。
- 初始公开行为 Red：14 failed / 1 passed（未补字段、JSON 被当摘要、额外注册等）。自审补真实注册完整页，2 failed / 4 passed，发现可选模板变量被要求必填；仅 prompt 添加 default 后通过。中途两次脚本换行转义造成 SyntaxError，已修复，不计行为 Red；Person 无缺项样例移除本来产生歌词缺口的 Songbox，未改分类规则。
- 最终 conda lty 四组 tests/world、test_world_task_vcpedia_new_songs.py、test_world_runtime_config.py、test_world_task_event_cleanup.py，-k 'not live'、禁 cacheprovider、独立 single-call-20260909-c/final-reviewed：275 passed / 1 deselected，46.58s；同范围 collect 275/276、compileall 和 git diff --check 通过。覆盖真实 LLMService→Fake SDK 的完整/缺项×JSON开关、原委托成功/fallback与参数不变、单次入库摘要、类型/空值/异常、缓存与保护字形。
- ignored single-call-20260909-c 保存逐文件改前备份、21份冻结输入和本轮 before/after 全输出及请求；21/21 完全相同，规则/模板加载/转换/API 源文件本轮未改。作者五轴自审完成，不替代独立审核；无新 scope/预算/语义判卷，无安装、真实网络/模型或生产访问，无 commit/push/PR，未创建 SPEC/Red/Green commit。全站、真实模型质量、真实客户端及全 Server 未验证。以下专用模块参数覆盖与双调用记录仅为已退役历史。

### 2026-09-09 补提取保留 client 委托路由（本地未提交）

- 契约短同步：沿供应商原路由，不强制禁 delegate。task 仅撤销 `client_model_type=''`，保留专用 prompt、JSON、thinking=false、无工具及深拷贝隔离；LLMService、LLMModule、客户端和 provider/model/API/key/timeout 路由实现未改。限定参数块自审未发现其他有确定依据应撤的无关覆盖。
- 新增公开 task.initialize → 真实 LLMService/模块 generate_response → 外部 Fake executor/provider 的4例，覆盖继承/显式配置优先与委托成功/None fallback，并验证源配置不变、旧摘要参数及 prompt 不变。Red **4 failed**，均因 client_model_type 被清空、实际委托入口未到达；撤一行后4例通过。首次合并 focused 中旧 SDK 例因 basetemp 父目录不存在而 setup error，创建隔离父目录后四组全部通过；该环境错误不计产品 Red。
- 统一 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q -p no:cacheprovider`，独立 `--basetemp=data/test_outputs/client-route-20260909-b/regression`：**259 passed / 1 deselected，70.53s**。同四组 collect-only 使用独立 collect 目录：**259/260 collected，1 deselected**；抓取包、LLM adapter 和四组 compileall、git diff --check 通过。旧合法 JSON/thinking/no-tools SDK 回归保留通过。
- 精确删除 requirements 自写许可注释、PRD 分发提醒及本进度重复许可短句，依赖版本、第三方 LICENSE 与其他历史许可事实未动。SPEC/Red/Green 与五轴作者自审完成，不替代独立审核；全部其他未提交工作保留，无 reset/commit/push/PR，没有 SPEC/Red/Green commit。无新依赖、联网、真实模型或生产访问，不做外范围审计；未验证真实客户端/供应商及全 Server。

### 2026-09-09 TextHover 可见正文与图片排除（本地未提交）

- PRD/interface 先明确参数1可见文案、参数2不拼入、参数3及 tag/htmltag 不参与选择、参数4 pic 整体排除。JSON 新增一条 inline 描述；loader 增加可选非空 `skip_if` 参数值列表，任一 strip/casefold 相等即跳过，仅值比较，不解析表达式。通用 inline 结构边界防止图片文件名及展示结构下探泄漏；没有 TextHover 专用 Python 分支、新包、依赖、font/Heimu 或其他 hover 能力。nowiki、LC、最终一次 zhconv、请求身份保持。
- 公开 fetcher 6例，SPEC/Red 自审后 `tests/world/test_vcpedia_content_quality.py -k texthover` 首次 **5 failed / 1 passed**：参数1缺失、展示伪简介及裸文件名/内链文件名泄漏；nowiki 首次通过，属于补回归，不伪造 Red。实现后四组 **255 passed / 1 deselected，58.31s**；collect **255/256，1 deselected**；compileall 与 git diff --check 通过。所有 Python 使用 conda lty，无安装；pytest 禁 cacheprovider，独立 basetemp。
- 四组命令：`conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/texthover-cache-20260909-a/green`。Red、collect、日志及 sourcehash/full before/after-final/report 位于同一 ignored 唯一目录 `server/data/test_outputs/texthover-cache-20260909-a/`，未覆盖任何旧 evidence/before。
- 当前工作区改前冻结 six-real 六份与 cached15，按 title+source 去重仍 **21份**；samecount=**20** 表示完整公开结果及请求相等的输入数，不是歌词行数。唯一变化 six-5 I LOVE YOU(Adaa) 的 lyrics/spaced_lyrics；该页首信息框、简介及其他字段均相等。原源码52/53行对应首普通 poem 第11/12个非空行，恢复 **2行** `../.-../---/...-/./-.--/---/..-`，18→20行，无新增解码文案。
- 同原 HTML 第一 `.poem` 对照：去 `.template-ruby-hidden`、rp/rt、脚注 reference，以及 CSS 默认 opacity:0 的 `.hover-change-after`（保留 before 普通表层），br 转换行后比较非空行，**20行全文逐行相等**。初稿直接 get_text 混入隐藏 I LOVE YOU 导致对照失败，修正证据选择而非产品；没有全局删除同名歌词句。第一块通过不表示第二 PV/font 已修复。
- 隔离旧 append 实际生成 keywords 并调用真实 SongEntityLinker：31字符电码查询和两侧空格查询均命中 `--/---/是《I LOVE YOU(Adaa)》的歌词`。旧 spaced_lyrics 以句点拆分，只保留6–50字符片段，故不是完整电码匹配；不改 SQL/模型/关键词策略。目标测试当前失败0；font 原漏及第二 PV 未纳入验收。
- 五轴作者自审完成，不替代独立审核；HEAD 仍96c8726、所有其他未提交修改保留，无 SPEC/Red/Green commit、commit/push/PR/合并。零真实网络/模型、无生产读写，全站与真实服务未验证。

### 2026-09-09 既有模板描述配置化（本地未提交）

- 新增 `server/res/knowledge/vcpedia_templates.json`：13组描述、43个名称、11种固定 kind、16项字段别名；迁移 inline、tabs/wrapper、lyrics/multiline/Utawari、Songbox/Infobox、staff 与 embed 的既有数据规则。Ruby/Utawari 算法、整体排除、标题识别和未知参数结构发现仍在代码，不新增 TextHover/font 或高级 LC。source 继续复用 parser 分类，无第二份嵌入白名单。
- 加载器按源码 resolved 路径一次加载并递归冻结；校验字段、固定 kind、字符串参数和跨描述别名冲突，同描述内繁简/大小写等价名合并。无新依赖/环境路径/公开配置键。`.gitignore` 仅放行该 JSON，knowledge 的数据库与其他数据仍忽略。参数修改例及无需改代码的范围见 interface“模板资源配置”，world 索引已短链到该说明。
- 先四组离线基线238 passed/1 deselected，collect238/239；SPEC自审后7项配置 Red 全因未实现而失败，无 importerror。临时文件替换外部读取，公开 fetcher 证明参数2、payload、原译/字段/staff、共享 embed、校验错误、cwd独立和一次加载；另4项参数/页签补回归。最终 conda lty 四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，禁 cacheprovider、独立 `template-config-final-1`：249 passed/1 deselected；独立 collect-final249/250、compileall、git diff --check通过。补回归初稿将空 lj 放在中间触发既有候选分段，调整样例位置而未改实现，不算产品 Red。
- `server/data/test_outputs/template-config-evidence/` 保存本轮迁移前源码、21份同输入快照、before/after-final完整输出与请求对照：真实六份及历史cached15全部逐字段相等，不使用历史输出冒充当前基线。离线HTTP重放且封锁真实网络，缓存分别隔离；不读取私有资料或生产DB。
- 相对本轮工作区快照，parser585→555行、AST If115→108；新loader105行/16个If，合计净增75行/9个If。删除的是代码中的描述数据与两段重复inline分支、五段名字分类分支，不宣称业务规则消失或整体复杂度下降。source/text_conversion/task/fetcher字节不变，prompt/requirements未动。作者五轴自审完成，不替代独立审核；保留HEAD96c8726和所有既有修改，无SPEC/Red/Green commit、push或PR，无真实模型/站点、全Server或生产验收。

### 2026-09-09 修复局部简介抢占外层候选（本地未提交）

- 独立审查阻断复现：普通 div 的结构发现先发布局部简介，使尚未 flush 的外层完整简介失去首候选。保留发现调用，仅暂存其简介候选，在外层简介（含结尾）完成后发布；无外层时局部简介仍可读。现有首完整简介契约已满足，无 scope 框架或公开接口变化。
- 公开 fetcher 直接/嵌套容器及无外层3例，`local-intro-red-1` 为2 failed / 1 passed，`local-intro-green-1` 为3 passed。统一 conda lty、禁 cacheprovider、独立 basetemp；四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，`local-intro-final-1`：238 passed / 1 deselected；`local-intro-collect-1` 收集238项，compileall 与 git diff --check 通过。
- 仅 parser、公开回归及本记录，作者自审完成；保留原未提交工作，不联网、不安装依赖、不 commit/push，不触及生产。未将本轮回归称为真实服务或独立复审通过。

### 2026-09-09 模板参数通用结构遍历（本地未提交）

- 仅扩展内部 details walk：模板参数按源码顺序寻找结构，保留已知内容槽/原译优先与首框相邻 staff 语义；未知纯文本不当正文，局部标题不跨参数，poem 仍受原歌词章节/槽边界约束，nowiki/comments 不发现伪结构。无新增模板名称、歌名或切换显示特例；列表及外部嵌入名单未改。parser 547→579行（净增32），删除仅 tabs/wrapper 才下探的门禁，增加已知歌词消费及通用参数路径；没有把名单移入新模块。
- 公开 fetcher 初始结构 Red 7 failed；首轮回归暴露无章节 poem 被误当歌词，恢复原章节边界并校正新增样例的章节前提，旧断言未改。自审补普通简介 div 内局部标题，独立 `structure-div-red` 1 failed，修复后通过；另补未知包装填满歌词后模型/局部渲染零请求。合计新增9例，原9项文本转换/nowiki 测试保留。
- 最终 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/structure-final-2`：235 passed / 1 deselected；同四组独立 `structure-collect-2` 收集235项，compileall 与 git diff --check 通过。仅既有 zhconv pkg_resources 弃用警告。
- ignored `six-real/evaluate.py` 最终重放六原材料：24/15/24/44/18/46非空歌词行；除山塘外五份完整业务结果与修改前完全相同，原材料字节不变。山塘首繁体候选44行与同响应 HTML 第一 poem 逐行去空白全文相等，第二简体块同为44行但未合入；LC 保护后的字形仍区别于普通 zh-cn 转换。完整对照保存于 `server/data/test_outputs/six-real/structure-comparison.json`。I LOVE YOU 既有 font 漏提不属于本切片，未声称修复。
- SPEC/Red/Green 作者自审及五轴质量检查完成，不替代独立审核。HEAD96c8726及既有未提交工作保留，无 commit/push/PR；不恢复 scope/cacheTTL/metadata，不改 SQL/关键词/配置。零网络、零真实模型、无依赖安装、无生产读写；全站、真实服务与全 Server 未验收。

### 2026-09-09 zh-cn 正文转换与 nowiki 保留（本地未提交）

- 按本轮授权更新 PRD/提取契约：规则最终输出、模型新补字段和模型新摘要各转换一次；fallback 不重转，局部已渲染 HTML 保持站点文本。nowiki 在解析前暂存、转换后还原全部内部文字/标记/换行；普通 noFlag LC 在提取内联 markup 后保护字形并解包。source、name、请求/链接身份及未知字段键保持，不恢复缓存/版本/scope/预算设计。
- lty 原未安装 zhconv，本轮仅向 lty 安装 1.4.3，requirements 显式固定版本。运行存在上游 pkg_resources 弃用警告，未改其他依赖。
- 公开 fetcher 8例：`zhconv-red-1` 7 failed / 1 passed（HTML 已有回归）；真实材料自审补 LC 内联 markup，`zhconv-markup-red` 1 failed，修复后通过。12项旧繁体正文预期按新契约精确更新，原始材料、身份、全文与结构断言未删除。
- 最终 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/zhconv-final-2`：226 passed / 1 deselected；同范围独立 `zhconv-collect-1` 收集226/227，抓取包、LLM adapter、四组 compileall 与 git diff --check 通过。
- ignored `six-real/evaluate.py` 已按当前公开 fetcher 离线重放六原材料，`conversion-replay.json` 保存完整结果；原材料字节和请求身份不变，输出均无 LC 定界符。唱给雅音宫羽/青麟雪/横竖撇点折/山塘恋雨/I LOVE YOU(Adaa)/长平传非空歌词行分别24/15/24/0/18/46；前3首及长平传仍保留区别于普通转换的保护字形。山塘歌词空、I LOVE YOU font 漏提未修，不把本轮文本验证写成站点完整性验收。
- SPEC/Red/Green 作者自审及质量检查完成，不替代独立审核；无 commit/push/PR。除依赖下载外无网络、无真实模型，全站、真实模型、全 Server 与生产未验收。

### 2026-09-09 修复普通简介容器截断（本地未提交）

- 独立审查发现普通 div 内黑幕模板触发 flush，使同一简介被截为多个候选。仅将普通正文模板保留在当前简介聚合；结构内容和实际标题仍走原遍历边界，不恢复 scope/版本框架。现行“首个完整简介”契约已满足，无接口变更。
- 公开 fetcher 新增直接/嵌套 div、源码及 HTML 第二简介边界共4例：`intro-container-red-1` **4 failed** → `intro-container-green-1` **4 passed**。四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，统一 `conda run -n lty --cwd server python -m pytest`、禁 cacheprovider、独立 `intro-container-regression-1`：**217 passed, 1 deselected，9.84s**；独立 collect、compileall、git diff --check 通过。
- 作者自审核对正文完整性及第二简介不混入；仅本修复代码、回归测试与此记录，无联网、真实模型或 commit/push。未替代独立复审。

### 2026-09-09 按授权缩回独立提取（本地未提交）

- 以 `96c8726` 为恢复基线：保留首信息框、首完整简介、首歌词的独立提取、结构比较 OpenCC、markup/ruby/和声、一次缺失业务 JSON、必要嵌入及 target/display。移除 scope/versions/来源缓存元数据和写回、TTL、失败文件、批次期限、SQL upsert、关键词补偿/原子替换/长窗口；共享 SDK timeout 与说明恢复基线。Person fallback 与原入库返回边界恢复，不宣称人物识别准确。
- 修改前逐文件备份28个相关 tracked/untracked 原文件及 tracked.patch，位置 `../vcpedia-shrink-backup-20260912-013318`；manifest.json 记录相对路径、大小及 SHA-256，复核全部匹配。无配置/密钥/data/test_outputs 复制。仅读取并确认纯新增缓存重设计测试后删除该独立文件；混合测试仅退役超范围断言，真实 fixtures 与原基线回归保留。三个原测试名称中缓存名称已恢复，另两个为按新正文契约改名而非删除保护。
- Red：三种首信息框与公共正文布局 `shrink-red-1` 为3 failed，Green 3 passed；自审补首简介页签前后正文，`shrink-intro-red` 为1 failed，最终全部通过。无伪造 SPEC/Red/Green commit，未 commit/push；PRD/spec 已同步收缩，历史条目未删除。
- 实际最终命令：`conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/shrink-final-reviewed` → **213 passed, 1 deselected，9.91s**；同范围 collect-only 使用独立 `shrink-collect-reviewed`，213/214；抓取包及四组 compileall、git diff --check 通过。
- 已知真实材料离线回放包含疑神疑鬼（原版繁体完整简介、公共30行歌词及和声）、Estrus（原文与HTML逐行、原译不混）、煌/普通DISCO/达拉崩吧及原固定三源。未重新随机、未联网或真实模型。六个产品文件相对本轮备份从1479行缩至1130行；未把删除的缓存/版本逻辑搬到新 helper，产品热路径禁用概念扫描无命中。作者自审不替代他人审核；全站、真实服务、全 Server 和生产未验证。

### 2026-09-09 结构判断字段繁简归一（本地未提交）

- 仅章节、模板/语义参数名和角色标签的比较副本使用 OpenCC t2s；已知 infobox 键规范化，未知原键保留，source 补提按同一键规约合并。正文、姓名、歌名、链接目标与缓存身份不转换；不改 scope/root/main、Person 或统计正文规则。复用 lty 已安装的 OpenCC 1.4.1（Apache-2.0），在 `server/docs/requirements.txt` 显式声明，无新增安装。
- 公开 fetcher/source/daily 新增8例，`conda run -n lty --cwd server python -m pytest tests/world -k structural_normalization -q --tb=short -p no:cacheprovider`，独立 `structnorm-red-1`：**8 failed**；首次 Green **7 passed / 1 failed**，剩余为样例期望误加黑幕前换行，按既有文本拼接约定纠正，未改正文实现。最终四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，同前缀/禁缓存、独立 `structnorm-regression-1`：**259 passed / 1 deselected，13.61s**（含新增8例）；独立 collect **259/260，1 deselected**。抓取包、LLM adapter、四组 compileall 与 git diff --check 通过。
- 真实《疑神疑鬼》历史 raw 原字节固化为 `server/tests/world/fixtures/vcpedia_recorded_yishen.wikitext`，SHA-256 `f2c416e1bb3c81b2608a6446fb73416ed2fe428de96f429794f15ee2f203aa2d`；原版简介全文恢复并保留繁体，主歌词仍空、requested.lyrics=true，独立 root/main 问题未修。测试同时证明繁体正文/人名、未知 key、原始补提材料、链接请求身份和 SQLite 值未转换。
- SPEC/Red/Green 作者边界自审完成，无本轮 commit/push/PR、联网、真实模型或随机验收；保留原未提交工作。此记录仅为结构修复回归，不表示整体歌曲质量验收完成。

### 2026-09-09 独立审查阻断：普通容器歌曲框与 staff（本地未提交）

- 现行顺序 scope 契约已满足，无新增公开接口。普通 div/section 内容走原顺序 walk，返回末尾 scope，使嵌套后框及容器外相邻 staff 保持 version 归属；没有全局第二扫描或名称启发式。div 复用原节点；section 在 mwparserfromhell 中为不透明扩展标签，仅其入口解析内容。原标题局部范围、显式 table/poem 路径保留。
- 公开 fetcher 新增直接 div 首框与嵌套容器 staff/version 两例，`conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_content_quality.py -k 'plain_container or nested_containers' -q --tb=short -p no:cacheprovider`：独立 `data/test_outputs/container-red-1` **2 failed**；`container-green-2` **2 passed**。完整断言首后框字段、简介、歌词与 version，不测试私调用次数。
- 最终四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`，同 conda 前缀及禁 cacheprovider、独立 `container-final-1`：**251 passed / 1 deselected，13.11s**；`container-collect-1` 收集 **251/252（1 deselected）**。抓取包、LLM adapter、四组 compileall 与 `git diff --check` 通过。
- 更新同口径真实结构：parser **690/33/135 → 554/30/110**（行/函数/AST If），daily **331/16/35 → 296/15/28**、source **226/13/26 → 226/13/26**；三者合计 **1247/62/196 → 1076/58/164**，净减171行、4函数、32个 AST If。此次增8行、1个 If，无移动实现掩盖下降，仍不把 If 当业务规则或宣称性能提升。作者自审完成；未网络、模型、commit/push、生产修改。

### 2026-09-09 源码顺序提取与列表单遍候选（本地未提交）

- 按本轮明确授权修正 PRD/interface：首个歌曲框为主，后框为独立 version，名称/消歧/about/链接不决定主范围；Introduction 补当前 staff，正文槽页签按首项顺序投影，不逐字段竞争版本。保留全部已有工作，无 commit/push/PR；HEAD 仍为 `96c8726`。作者自审完成，不替代独立审核。
- 删除 `_parse_scope`、`_headings`、`_sections`、`_tab_contents`、`_content_nodes`、`_first_poem`、`_songbox` 及 daily 的第二套 `visible_links`；删除逐框再 parse、局部序列化归一化、重复歌词覆盖、冲突字段删除、名称/后缀匹配。直接读取开放业务字段、staff、Small 简介/歌词、Lyrics 原译槽和 tabs/wrapper；显式 HTML table/poem、标准文本及 ruby 保留。列表 target/display 共用一次候选遍历，名称公开形状只投影；嵌入小名单复用 parser 局部分类，不增加通用解释器。
- 非歌曲返回 Unknown，do_one_song 拒绝非 Song；SQL/关键词预算与补偿未重写。extractor 升至 `knowledge-2026-09-v3-source-order`，schema 2 不变；完整缓存对 partial/失败刷新保护、unknown 不触发模型、业务 JSON 类型合并及必要嵌入预算回归通过。
- 优化前已在仓库外临时目录冻结抓取包源码及 AST 统计，不以 HEAD 或移动代码比较。实现同口径（物理行/函数含嵌套函数/AST If）：parser **690/33/135 → 546/30/109**；daily **331/16/35 → 296/15/28**；source **226/13/26 → 226/13/26**。三者合计 **1247/62/196 → 1068/58/163**；其余抓取文件结构计数不变，无新实现文件。If 是复杂度代理，不是每项业务规则。局部具名集合为4个歌词名、6个 staff 名、2个 tabs 名、4个外部嵌入名、3个 wrapper 名，另16个角色别名；仍有标准 markup、展示键和列表过滤兼容，不宣称零模板维护或全面泛化。
- Red：公开 fetcher `-k ordered_first` 为 **3 failed**（首框丢字段、后 staff 覆盖）；公开列表/入库 `-k 'content_slots or non_song'` 为 **4 failed**；自审发现 Small 直接文本歌词槽，`-k small_direct` 为 **1 failed**，修复后均由最终回归覆盖。对应独立 basetemp 为 `order-red-20260909`、`list-red-1`、`slot-red-1`。没有伪造独立 SPEC/Red/Green commit。
- 旧测试精确更新：异名首框为 main、同名后框 version 不删首歌手、后框之后正文不倒填首框、任意标签首页签按顺序；无歌曲证据 Person 改 Unknown，明确歌曲框即 Song；同一 scope 的 h3 简介归为一个全文条目，正文及短摘要文字不变。其余完整业务字段/HTML断言保留。冻结 Estrus 的 HTML 为逐行 Lyrics-original 而非 poem，修正测试对照选择，不算产品 Red。
- 冻结连续三样本 `browser-fixed-20260911-113745-20e80d` 的原始3份响应固化为 `server/tests/world/fixtures/vcpedia_frozen_consecutive.json`，含指定 `2.source.json`，不修改原冻结材料；这是既有材料重放，不是新 random。《此刻说再见》、Estrus 原文逐行全文对照及可达六字关键词实际消费者通过；Estrus 47个非空原文行，心华/野良犬P、完整五项信息框和简介、译文独立保存，无心形/标题例外。周刊449为 Unknown，临时 SQL/关键词均拒写。原秦宣/刀马旦/纸飞机三源及历史煌/普通DISCO/达拉崩吧三源全文与缓存/SQL/关键词回归保留通过。
- 最终命令统一 `conda run -n lty --cwd server python -m pytest`：`tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/order-final-reviewed` → **249 passed / 1 deselected，13.29s**。同范围 collect-only、独立 `order-reviewed-collect` 为 **249/250 collected（1 deselected）**；抓取包、LLM adapter、四组测试 compileall 与 `git diff --check` 退出0。无真实网络/模型、生产配置/DB修改；未测性能、全站及生产，不用测试墙钟声称提速。

### 2026-09-11 独立审查阻断修复：HTML Ruby 隐式正文（本地未提交）

- 现行 Ruby 表层契约已满足，无新增接口。无显式 rb 时，排除 rt/rp 后按原正文解析路径保留文本、span/br；确实空白才回退实际唱词。显式空 rb 的历史“啦啦”保持，未改冻结材料或缓存协议。
- 公开 fetcher 新增5例，统一 `conda run -n lty --cwd server python -m pytest`、`-q --tb=short -p no:cacheprovider`：`tests/world/test_vcpedia_content_quality.py -k implicit_base`，独立 basetemp `data/test_outputs/ruby-implicit-red` 为 **3 failed / 2 passed**（字被替换成zi、span/br正文丢失）；`ruby-implicit-green` 为 **5 passed**。两项空正文回退首次即通过，属于补回归。
- 原四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`、独立 `ruby-implicit-regression`：**238 passed / 1 deselected，15.07s**；同范围 collect-only（`ruby-implicit-collect`）、抓取包/LLM adapter/四组测试 compileall、`git diff --check` 均退出0。作者自审完成；无网络、模型、commit/push，所有其他修改保留。独立审查79项通过为审查方前轮结果，不冒充本轮执行。

### 2026-09-11 固定三源六问题修复回归（本地未提交）

- 保留 HEAD `96c8726` 及原全部未提交工作，无 commit/push/PR。公开 fetcher/do_one_song/daily sync/SongEntityLinker 验证：消歧标题首主框恢复且同名二创隔离；Ruby 非空表层取 rb/参数1，空白 rb 实唱保留 rt；Dead 姓名及粗斜体正文保留；其他资料局部统计分句移除并保留投稿/重制/专辑；完整歌词行及原空白优先生成关键词，兼容片段和同句窗口，不跨行拼接；丢失主框但存在 Introduction 不再伪 complete。schema 2、extractor `knowledge-2026-09-v2` 使旧缓存失效，最后完整缓存对 partial/失败刷新保护仍通过。
- SPEC 自审后公开三源 Red，统一前缀 `conda run -n lty --cwd server python -m pytest`，选项 `-q --tb=short -p no:cacheprovider`：`tests/world/test_vcpedia_fixed_acceptance.py`、basetemp `data/test_outputs/fixed-six-red-3`，**9 failed / 3 passed**。前两次 HTTP seam 参数和 HTML 首 poem 定位错误已纠正，不计产品 Red。结构补充 `test_vcpedia_content_quality.py -k 'ruby_surface or lost_main or recorded_real'`、`fixed-six-structure-red`，**2 failed / 3 passed**；分别为 HTML rt 混入和主scope缺口误 complete。
- 最终原四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`，`-k 'not live'`、禁 cacheprovider、basetemp `data/test_outputs/fixed-six-reviewed`：**233 passed / 1 deselected，14.99s**。相同范围 collect-only、独立 `fixed-six-reviewed-collect` 退出0；抓取包、LLM adapter、四组测试 compileall 与 `git diff --check` 退出0。历史 Ruby 旧预期从拼注音改为 HTML 表层，仍验证完整歌词，空白 rb 的“啦啦”明确保留，没有删除冲突测试。
- 三份原始响应（含原 HTML/wikitext、URL/revision）固化 `server/tests/world/fixtures/vcpedia_fixed_acceptance.json`，礼物真实旧响应固化 `vcpedia_recorded_gift.json`，均明确真实采集非人工。冻结目录 `browser-fixed-20260911-021300` 未改。材料已参与修复，**本轮不再独立随机**。
- 新隔离重放 `server/data/test_outputs/fixed-six-replay/`，先输出 fetcher JSON/SQLite/缓存，再输出 `html-comparison.json`；`integration-report.json` 保留原始HTML逐行输入和实际匹配：秦宣 **24/24**、刀马旦 **28/28**、纸飞机 **28/28** 每行至少一个歌词命中。三源主歌手/UP正确；二读零 HTTP、完整 JSON、单行幂等、关键词字节稳定及删除文件后补偿均通过。HTTP只重放固定响应、真实网络/模型0。独立脚本首次导入路径错误后按 server 导入环境成功运行，不计产品失败。
- 对照完整角色/简介和歌词：刀马旦/纸飞机歌词与HTML行段相同；秦宣7处读音不再混正文，唯一字符差异是源码“商於”与站点简体HTML“商于”，原文保留并在测试和比较报告明确列出。该HTML行通过“神鬼招兮悲风”片段实际命中。纸飞机冻结响应无 revid，仍保存 null；未伪造。礼物源码原有开头逗号已移除，专辑保留。简介按既定策略去动态统计句，角色及完整正文仍保留，非摘要语义验收。
- 已加载质量审查并完成作者边界自审；未添加 LLM 语义校验、unknown 自动渲染/模型或新依赖。没有运行新随机、全站、真实模型、全 Server 或生产验收；complete 不是语义保证，未加入通用繁简转换。独立审核须由主线程另派，作者自审不替代独立审查。

### 2026-09-09 独立审查 P1：不完整刷新不得覆盖完整知识（本地未提交）

- 现行 interface“保存与运行”的最后成功文件保护已覆盖本修复，无新增接口或配置。fetcher 对最后 complete 知识增加 partial 刷新保护：模型合法 `{}`、歌词 null、禁用模型留下缺口时，返回原知识且原文件字节不变；日志记录刷新 status/supplementation，不刷新旧时间或混入新 revision。首次无缓存的 partial 短 TTL 行为不变，后续完整刷新仍可写回。
- 公开 fetcher 三场景 Red：`conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_knowledge_cache.py -k partial_refresh -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/cache-p1-red`，**3 failed / 13 deselected**，均因旧完整知识被新 partial 替代；新增断言同时验证完整刷新恢复写回。
- 原四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`，同 conda 前缀、`-k 'not live' -q --tb=short -p no:cacheprovider`、basetemp `data/test_outputs/cache-p1-green`：**215 passed / 1 deselected，12.80s**（原212项加3项回归）。相同四组 collect-only、basetemp `data/test_outputs/cache-p1-collect`：**215/216 collected / 1 deselected，4.62s**；抓取包、LLM adapter、四组测试 compileall 与 `git diff --check` 通过。
- SPEC/Red/Green 作者自审完成；只改 fetcher、缓存专项测试和本完成记录，保留所有已有改动。未联网、未访问生产数据、无 commit/push/PR；本记录不解除既有真实站点验收阻断。

### 2026-09-09 最终集成离线收敛与受限真实验证（本地未提交）

- 保留 HEAD `96c8726` 后全部工作，无 commit/push/PR。现行契约与实现核对：完整作用域、开放信息框、多版本/译文、主歌词全文、业务 JSON 一页一次、unknown 不触发、必要嵌入规则、版本/TTL 缓存、规范身份、SQL rollback、关键词单文件原子替换及 skip 补偿。补齐实际 sync/extraction 配置范围、source_title 与 metadata 保存说明。无独立全批 HTTP/模型计数器；批次与每页上界间接约束，dispatch 期限不是硬取消，SQL/文件不是总事务。
- 四组统一 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -p no:cacheprovider`，独立 `data/test_outputs/final-*` basetemp：基线 **192 passed / 17 failed / 1 deselected**；最终 **212 passed / 1 deselected，13.64s**。第一次在仓库根运行因相对资源目录出现额外错误，不计产品 Red；收敛过程中一次测试字符串转义收集错误已修正，不计产品 Red。
- 17 项旧预期分别按新契约修正：unknown-only 无明确业务承载则零模型；输入预算加入确切待提歌词；旧 schema 的 requested 不沿用；canonical title fixture 与主曲一致；简介 h3/div/背景表保留；有数值统计保留、未知动态统计整句移除；h3 歌词可识别、主版本不被新版覆盖；空 Tabs 不吞后续歌词、合法 div 内歌词可递归；失效缓存尝试刷新失败才回退。仍严格比较全部原业务字段，不删字段断言。此轮未修改产品实现，新增测试为既有实现补回归，无伪造 Red。
- 新增3首历史公开材料的完整 fetcher→成功缓存二读→do_one_song→临时 SQLite→实际 SongEntityLinker 回归，分别验证30/45/40非空歌词行、角色 SQL 投影、完整 JSON（含 versions）、二读零HTTP、重跑单行且关键词文件幂等、代表歌词实际匹配。原逐字歌词/HTML离线测试保留；精简源码及歌词HTML固化在测试 fixtures，不再依赖 ignored 历史输出。所有这些是离线辅助，不能代替当次站点成功。
- collect-only **212/213 collected，1 deselected，4.60s**；抓取包、LLM adapter、四组测试 compileall 与 `git diff --check` 退出0。changed/untracked 文本扫描未发现本机路径或 secret-like token。作者质量检查已加载；parser 超过500行，职责集中于内部来源解析，本轮不夹带大拆分，独立审核仍必要。
- 当次真实脚本 `server/data/test_outputs/final-integration/verify.py` 正式加载 SecretStore→ConfigStore.read_resolved→LLMService/task。初次因内存 crawler.use_llm 未启用导致模块为空，零外部请求；修正验证脚本后注册 JSON=true、thinking=false、无工具。《煌》requests **403**，唯一 curl **403 / exit22**，立即停止站点。仅2次站点请求，未继续普通DISCO/达拉崩吧，自然模型0次；当次三首全文、revision、缓存二读和真实入库均未完成，不宣称外部验收通过。
- 独立 `model_diagnostic.py` 使用历史公开《煌》材料，明确人为设置待提角色，非自然端到端；经同一正式配置/任务注册，真实 SDK **1次**合法业务 JSON，演唱洛天依、UP主洛天依官方账号正确；未请求 summary/lyrics 不合并。prompt/completion/total tokens **2058/29/2087**，cached0，无费用信息。当前站点403不因这一诊断解除。两脚本无生产 runtime，SQL/cache/关键词隔离临时目录，finally 关闭资源并恢复环境/路径，无生产写入。
- 最终状态为离线集成通过、当次真实站点验收阻断；没有输出最终 HTML 比较或宣称完整外部交付。历史记录仅描述各时点行为，不是现行旧下标协议要求。

### 2026-09-09 提取参数约束与禁模型必要嵌入（本地未提交）

- 修正现行 PRD/interface 对参数的误解：专用提取模块启用供应商支持的 JSON object、关闭 thinking、无工具；深拷贝保留旧摘要及调用方配置，其他生成参数不变。真实 LLMService→Fake SDK 公开链 Red 为缺失 response_format，修复后连同旧摘要不变断言通过。
- fetcher 始终进入有界来源提取，`use_llm=false` 只禁模型而不禁必要嵌入规则；新增公开入口 Red 为歌词为空，Green 为局部嵌入保留两行和声且模型零调用。旧字典完全相等断言改为比较原业务字段投影，允许契约新增 extraction 元数据；业务期望未削弱。
- conda lty 四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`-k 'not live' -q -p no:cacheprovider`、独立 `data/test_outputs/tmp-<唯一标识>` basetemp：**154 passed, 1 deselected，9.51s**；同范围 collect-only、抓取包及 world 测试 compileall、`git diff --check` 均退出0。默认临时目录首次权限错误不作为行为 Red，切换隔离目录后取得真实失败。
- SPEC/Red/Green 和质量作者自审完成；未联网、未执行真实模型/站点验收、未访问生产 DB/关键词，无 commit/push/PR。本条仅为上述两项修复，不代表完整作用域、缓存、批次预算及入库补偿已交付。

### 2026-09-09 最终方案的局部信息框及歌词修复（本地未提交）

- 现行 PRD/spec 替换旧下标/证据判卷约定，架构同步业务 JSON 方向；文档明确目标不等于实现完成。迁移 PRD 标注仅兼容基线适用。本条只记录以下已验证增量，不宣布最终方案完成。
- Introduction 从 Songbox 通用字段遍历中分离，解析 group/list 复合角色和 role=value；新增 Infobox Song 开放业务字段，排除样式键。不同明确歌名的 Songbox 不再写入主作品；该判断尚不是完整章节/容器作用域实现。
- poem 保留行段、括号和互动文字，不限首 p、不删 br；LyricsKai 主 lyrics 选 original，Lyrics lb-textN 按数字顺序保留段落。尚未交付译文/版本存储；spaced_lyrics 当前保持歌词行，长行标点派生未实现。
- 公开 fetcher 新增6项业务测试。命令统一前缀 `conda run -n lty --cwd server python -m pytest`，选项 `-q --tb=short -p no:cacheprovider`。信息框 focused `tests/world/test_vcpedia_wikitext_contract.py -k business`，basetemp `data/test_outputs/final-plan-box-{red,green}`：**3 failed → 3 passed**；四组回归 `final-plan-box-regression`：**182 passed, 1 deselected**。歌词 focused `-k business_lyrics`、`final-plan-lyrics-red`：**3 failed**；两组 `-k business`、`final-plan-lyrics-green`：**6 passed**。
- 首次歌词回归 `final-plan-lyrics-regression`：**12 failed, 173 passed, 1 deselected**，为旧单行/删括号/首段与入库断言；按新契约更新对应预期，并将关键词用例改为逐行完整句实际匹配。最终四组 `final-plan-lyrics-regression-2`：**185 passed, 1 deselected，9.84s**。四组为 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`。
- 同范围 collect-only（`final-plan-partial-collect`）、compileall 抓取包及四组测试、`git diff --check` 执行退出0。没有新增网络 marker，没有访问真实站点或模型，没有启动生产 runtime 或修改生产 DB/关键词。SPEC/Red 自审核对公开入口及失败原因；加载质量审查，自审确认此增量不能代表完整作用域、完整补提或保存运行交付。无 commit/push/PR。

### 2026-09-10 提取提示词正向步骤与完整 JSON 示例（本地未提交）

- 仅改专用 prompt、对应回归及小主题 spec：三个正向步骤，简化作品材料/四字段候选/全 null 示例；程序校准示例 start/end、来源、value、evidence、role，并经原 fetcher 校验。保留 Jinja 单次插值、下标协议与全部程序校验，未处理前次四项产品质量问题。
- 核对当前 DashScope DeepSeek V4 Flash 的[关闭思考](https://help.aliyun.com/zh/model-studio/deepseek-api)及 [JSON Object](https://help.aliyun.com/zh/model-studio/json-mode)支持、已安装 OpenAI SDK 2.49.0 参数。无工具、thinking=false、json_object、token/timeout 原已满足，本轮未改参数或共享模块；配置及调用 kwargs 覆盖尝试的 Fake SDK 回归通过，旧摘要设置保留。
- 命令前缀 `conda run -n lty --cwd server python -m pytest`；focused 文件 `tests/world/test_vcpedia_source_extraction.py -k 'registered_prompt_examples or real_registration'`，统一 `-q --tb=short -p no:cacheprovider`，独立 `data/test_outputs/prompt-expression-{red,green}-1` basetemp：**1 failed / 1 passed → 2 passed**。Red 为缺完整示例；既有能力断言首次即通过，属于补回归。实际 SDK 消息中的示例可 json.loads，运行时引号、换行及 Jinja 字面量保持，原临时 SQLite/关键词链通过。
- 原四组 `-k 'not live'`、禁 cacheprovider、独立 `prompt-expression-regression-1`：**179 passed, 1 deselected，9.60s**；同范围 collect-only、独立 `prompt-expression-collect-1`：**179/180 collected，1 deselected，4.27s**。原范围 compileall 与 `git diff --check` 通过。SPEC/Red/Green 及五轴作者自审完成；无 commit/push/PR，HEAD 保持 `96c8726`，其余未提交修改保留。本轮仅查公开 API 文档，未真实调用模型或站点、未验证真实质量及全 Server/生产。

### 2026-09-10 正式配置链重新真实验证（网络及鉴权成功，字段质量未通过）

- 主机日期 `2026-09-10 +08:00`；执行 `conda run -n lty --cwd server python data/test_outputs/restart-20260910/verify.py`。先正式 `SecretStore.load_into_environment -> ConfigStore.read_resolved`，仅记录 key/base_url/model 非空且非 placeholder 的布尔校验；按 SystemRuntime 的 LLMService 配置方式创建服务、真实 task.initialize 注册 `song_knowledge_extractor` / `song_knowledge_extraction_prompt`。之前 401 来自测试漏加载 SecretStore，初始化错误本次已纠正，不作为真实 key 失效证据。
- 原 fetcher `use_llm=true`，明确直接注入 `extraction_module`、`llm_module=None` 隔离旧摘要成本（保留原 fallback）；无 mock HTTP/模型，无受控清空。实际站点 **5 请求均 HTTP 200**：三首详情 `prop=wikitext|text` 作同响应来源/HTML对照，加《普通DISCO》两次局部 parse；无挑战、无 curl 网络兜底。观测器曾把一个本地平台识别子进程误记为 curl，已保留校正说明并过滤可复用脚本的非 curl 进程，未为此重跑联网。
- 自然提取 **2 次**均成功返回合法 `fields` JSON，首次即真实歌曲鉴权请求，无问候/换 provider/key。SDK latency **14.515s / 14.422s**；prompt/completion/total tokens 分别 **10801/1868/12669**、**10887/1850/12737**（第二次 cached 10240）；SDK 未提供费用及成功 HTTP status，不猜测。JSON 开启、thinking 关闭、无工具；实际消息角色为单条 system，材料仅有界公开源码及局部文本。适配器尝试 1、SDK retry 0。
- 《煌》：规则四字段 existing，模型绕过；歌手洛天依、UP主洛天依官方账号与 HTML 一致；简介来自作品简介/国乐季琵琶主题介绍，仍残留 `殿堂曲，。`；歌词 366 字符，忽略空白逐字一致，但输出 1 行、HTML 非空 30 行。
- 《普通DISCO》：真实复杂表格使歌手/UP主自然缺失；HTML 明确洛天依、言和 / ilem。两次模型虽返回正确名字及 vocal/uploader 角色，所有候选却均为 **start=0,end=1**，与 value 不一致；歌手/UP主均严格拒绝为 failed，最终仍空。模型还越过 missing 返回已有简介/歌词候选（简介含非原文统计数字），未覆盖任何规则字段。简介保留来源正文但统计清洗留下缺词；歌词 470 字符、1 行对 HTML 45 非空行，漏掉互动台词及多处括号和声等，不完整。这是模型下标契约和规则可靠性质量问题，不是网络阻断。
- 《达拉崩吧》：规则 existing 导致模型绕过；歌手洛天依、言和正确，**UP主误为二创《吃鸡有神仙》的折腾5号，主作品 HTML 为 ilem**（歌曲名称、投稿日期等也被二创 Songbox 覆盖）。简介来自主作品简介；歌词 621 字符、1 行对 HTML 40 非空行，另有括号、注释及 `[那个巨龙]` / `[那个勇者]` 显示文字差异，未通过逐字/行完整验收。
- 局部渲染实际选择完整 `info` **285 字符**和 `TocHide` **11 字符**，均保留 title、`contentmodel=wikitext` 且无 page；整页 raw 20066 字符，非全页 expand/render。前者清洗后 119 字符、后者空；第二次模型材料 raw 20066 + render_1 119。这两片是成就提示/目录控制，**不是缺失角色所必需内容，选择相关性未通过**；虽完成自然局部 parse 调用，不能声称完成必要模板质量验收。
- 三页原规则四字段均未覆盖，拒绝结果未入库。脱敏 report、真实公开响应、模板及离线逐字对照保留于忽略目录 `server/data/test_outputs/restart-20260910/`，大响应不入 git。未启动 SystemRuntime、后台调度、DB/do_one_song，无生产 DB/关键词/cache 修改或其他外部消息；session/client finally 关闭，临时 globals/environment 恢复。未改产品/测试实现；未执行全年度、全站、数据库入库、旧摘要质量或全 Server 回归，不声称生产验收。保持 HEAD `96c8726` 和既有未提交修改，不 commit/push/PR。

### 2026-09-09 小规模真实校验：站点 403、测试初始化遗漏（未通过外部验收）

- 命令：`conda run -n lty --cwd server python data/test_outputs/live-20260909/verify.py`；原 fetcher 入口在 HTTP 边界将详情请求扩为 `prop=wikitext|text`，响应不伪造。《煌》requests **403**，既有 curl 兜底 **403 / exit 22**，随后停止站点访问；未继续第二首《普通DISCO》，未完成 2–3 页或自然复杂模板缺字段覆盖。实际站点请求 **2 次**，局部 parse **0 次**。
- 为继续独立层验证，使用先前临时目录保留的《煌》真实 `action=parse` 响应（同时含 wikitext、服务端 HTML），复制至隔离证据目录 `server/data/test_outputs/live-20260909/`。这是历史公开材料，不是本轮在线抓取成功，也不是手工 fixture 或生产知识缓存冒充源码。
- 命令：`conda run -n lty --cwd server python data/test_outputs/live-20260909/model_check.py`。真实 task.initialize 注册 LLMService 的 `song_knowledge_extractor`，使用原供应商及 `song_knowledge_extraction_prompt` / `extraction_data`，JSON 开启、thinking 关闭、无工具。配置仅内存副本；提取专用供应商配置缺省，原供应商存在，base_url/model 已解析，API key 未有效解析（只记录存在/缺失，不记录值）。适配器尝试限制为 1，SDK 重试为 0。
- 单独诊断明确禁用历史真实 source 的规则结果，调用现有 supplement 与实际 module；不是自然兜底或端到端验收。实际 SDK 提取 **1 次**，输入提示词 **3821 字符**，返回 **AuthenticationError / HTTP 401 / invalid_api_key**；没有问候、切换供应商、改密钥或追加重试。四个诊断字段保持空/failed，未产生可验证提取证据；SDK 未返回 token/费用，不推测为零。此为新链此次实测，不沿用旧 legacy 401 结论。
- 历史源码规则与同响应 HTML 对照：歌手 `洛天依`、UP主 `洛天依官方账号` 准确；简介保留国乐季琵琶主题介绍，但统计移除后残留 `殿堂曲，。`；歌词 366 字符，忽略空白后与 HTML 正文逐字一致，但 `lyrics`、`spaced_lyrics` 均 1 行，HTML 为 30 行。四字段 states 均 existing，属于规则完整/模型绕过条件，不能记为模型成功；此次未改变提取策略。
- 生产无副作用：未启动 SystemRuntime、调度、数据库或 do_one_song，未读取用户聊天或发送私人数据；无生产配置、DB、关键词、缓存写入。HTTP session 与 SDK client 已在 finally 关闭。仅新增隔离诊断脚本/脱敏证据及本记录，无产品或测试代码修改、无新 marker/skip、未重复 178 项离线回归；`git diff --check` 通过。保持 HEAD `96c8726` 及原未提交修改，不 commit/push/PR。真实站点成功、真实模型字段质量、自然局部渲染及本轮入库仍未验证。

### 2026-09-09 独立审查四项修复与摘要配置隔离（本地未提交）

- 从公开 fetcher 入口逐项 Red→Green：歌词/简介证据改为绑定选段邻接肯定上下文，拒绝缺失声明及维护指令授权广告；角色标签增加完整边界，拒绝非演唱/非投稿者及模型裁掉否定前缀的 evidence；既有规则/缓存可靠性不再受新候选长度预算影响；模板只沿明确内容参数下探，语言/版本参数保留父调用上下文；新 extraction 超时不再取消旧摘要。
- 运行均使用 `conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_source_extraction.py`、`-q --tb=short -p no:cacheprovider` 和独立 `data/test_outputs/` basetemp。局部证据 `-k review_missing`：review1-red **2 failed**，review1-green 全文件 **52 passed**；否定角色 `-k review_negated`：review2-red **2 failed**，review2-green 全文件 **54 passed**；长字段 `-k review_long`：review3-red2 **4 failed**→review3-green **4 passed**；父调用 `-k review_content_parent`：review4-red **1 failed**，review4-green `-k 'review_content_parent or unknown_templates'` **2 passed**；摘要 `-k review_extraction_timeout`：review5-red **1 failed**→review5-green **1 passed**。
- 长字段首次参数化测试 ID 过长导致部分临时目录 setup/teardown 错误，不记为产品 Red；改为短 ID 后重新取得上述四例有效失败。新增裁剪 evidence 两例为补回归，不伪造 Red。
- 原四组 `-k 'not live'`、禁 cacheprovider、basetemp `data/test_outputs/review-final-regression`：**178 passed, 1 deselected，9.95s**。保留原 166 项及真实注册 Fake SDK 链路，新增 12 项边界。相同范围 collect-only、独立 review-final-collect：**178/179 collected，1 deselected，4.77s**。conda lty compileall 抓取包、LLM API 适配器及四组测试与 `git diff --check` 通过。
- 完成作者边界自审；未新增大 DOM 层、网络请求预算或公共 helper，契约仅澄清原约束。此轮无网络、无生产配置修改；保持原分支与基线，未 commit/push/PR。上下文拒绝规则保守，可能降低无标签文本召回，不声称彻底防注入或真实页面/模型质量已验收。

### 2026-09-09 来源证据提取与按需局部渲染（本地未提交）

- 基于 `96c8726e629f96494ddebf241b9f6574e4a1b667`，保持 `refactor/vcpedia-wikitext`。按用户授权不 commit/push/PR，因此没有本轮 SPEC/Red/Green commit；未修改生产配置。
- SPEC 自审：新增补提取 PRD 和小主题契约，world README 仅短引用；专用 extraction_module 注入/注册与旧摘要分开，utils 仅补可选 SDK timeout 契约。规则、证据、材料清洗归属 world；无全局服务、数据库/调度/向量库重构。
- 实现：新增一个 220 行聚焦内部提取模块及专用 prompt，可靠规则字段不覆盖。四字段逐项验证类型/长度/角色/对应原文范围与证据，歌词由程序复制；未知、不适用、失败不强制填全。坏 JSON/超时/无证据保留原可用结果。raw 有界且 script/style/nav/widget 等噪声等长屏蔽；提示词将源码作为不可信数据，无工具。
- 局部渲染：raw 仍缺字段且包含未知模板才选最小完整调用，保留参数与 title，直接 parse 原调用，不整页 render/expandtemplates。默认最多两片段，可配置 0..2；清洁文本合计 12000 字符，至多两次提取调用。requests/curl 共享挑战、HTTP 与 JSON 失败策略。完整缓存直接返回，缺字段缓存仅取得真实 source 后补提取；不写新缓存策略。
- 测试边界：新增 50 项补提取专项测试从 fetcher/task 入口验证；真实 LLMService/PromptManager/LLMModule/OpenAI 适配器连接 Fake SDK，临时 SQLite 与关键词文件实际入库；仅 HTTP、模型供应商和进程等外部 seam 使用 Fake。已有 116 项离线基线保留。

以下 Python 命令统一前缀 `conda run -n lty --cwd server python -m pytest`，均 `-q --tb=short -p no:cacheprovider`，使用独立 `--basetemp=data/test_outputs/<名称>`。

| 阶段 | 范围 / basetemp 名称 | 实际结果 |
| --- | --- | --- |
| 源码 Red | `tests/world/test_vcpedia_source_extraction.py` / raw-red-1 | 7 failed, 1 passed；缺字段未补及无专用注册 |
| 源码 Green | 同文件 / raw-green-1 | 8 passed |
| 渲染缓存 Red | 同文件 / render-red-1 | 3 failed, 24 passed；局部歌词未采、缺字段缓存未请求源码 |
| 渲染缓存 Green | 同文件 / render-green-1 | 27 passed |
| SDK 请求超时 Red | 同文件 / sdk-red-1 | 1 failed, 39 passed；真实任务到 Fake SDK 未透传 timeout |
| SDK Green 回归 | 四组 `-k 'not live'` / regression-1 | 156 passed, 1 deselected |
| 原始噪声 Red | 同文件 `-k 'raw_hidden or configured_render_budget'` / noise-red-1 | 3 failed, 4 passed；script/style/nav 文字误作证据 |
| 噪声 Green 回归 | 四组 `-k 'not live'` / final-regression-1 | 163 passed, 1 deselected |
| 最终回归 | 四组 `-k 'not live'` / final-regression-2 | **166 passed, 1 deselected，8.58s** |

四组为 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`。同范围 `-k 'not live' --collect-only -q -p no:cacheprovider --basetemp=data/test_outputs/final-collect-1`：**166/167 collected，1 deselected，4.75s**。排除既有真实 wiki live 测试，没有新增 marker/开关。

`conda run -n lty --cwd server python -m compileall -q src/world/get_new_songs src/utils/llm/llm_api_interface.py tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`git diff --check` 通过。保留根 pytest cache 权限警告，不修改其权限。

- 额外验证异常：旧 `tests/test_llm_content_inspection.py tests/test_llm_service.py -k 'not live'`（llm-regression-1）为 **8 passed, 1 failed**。旧 `test_register_llm_module` 未标 live，实际发送其固定样例问候并按既有策略三次返回 401 invalid_api_key；此次非预期联网不算真实模型验收，未再次运行。未发送 VCPedia 页面材料或配置内容给该样例请求，不修改该无关旧测试。
- 作者自审：加载 code-review-and-quality，核对五轴及 SPEC/Red/Green；发现原始噪声证据问题后补 Red 修复。所有实现增量不足 300 行，新增测试 368 行，未用通用框架堆叠；HTTP 重用既有通道、未增加依赖。作者自审不替代独立审核。
- 未验证与限制：未成功调用真实提取模型，未重复 wiki 403；真实陌生页面召回率、模型字符范围准确率、真实模板渲染/curl 成功、全 Server 与生产未验收。严格连续原文范围可能保守漏提（包括无明确角色标签、需要跨片段拼接的歌词）；来源存在不证明页面事实本身真实。SDK 单次 timeout 已传递，但既有 SDK 内部重试与同步线程退出使外层取消不是硬实时任务期限。批次、数据库事务、缓存写入、旧摘要质量与无关故障策略不在本轮改造范围。

### 2026-09-12 提取包内部边界收敛（本地未提交）

- 仅收敛本次新增的包内边界，不改公开 interface 与可观察行为：`template_rules` 的 `_RULES` 退出跨文件面，解析器与材料合并各自需要的操作改为具名包内函数 `structure`、`template_name`、`descriptor`、`field_key`、`is_presentation_key`、`is_excluded_field`；`text_conversion` 的 `_TextConversion`/`_convert_text`/`_converted_lyrics` 改为 `TextConversion`/`convert_text`/`converted_lyrics`。
- `field_key`、`is_presentation_key` 由 `wikitext_parser` 原实现逐行移入 `template_rules`，`is_excluded_field` 承接原 `normkey in _RULES["field_exclude_params"]` 成员判断；解析器删除对应本地函数体，不再直接索引规则文档的 dict 形状。`source_extraction` 的字段名归一与结构归一改为直连 `template_rules`，取消原先经 `wikitext_parser` 的转手中转。
- `_kind` 保持私有：它只是解析器内部的六种 kind 收窄，且解析器内有同名局部变量。调用方只问"是否 embed"，改用新增包内 `is_embed(template)`，直接读规则描述而不依赖该收窄。`TextConversion` 保留跨文件引用，因其必须是"一次 protect、多次 finish"的有状态协议；类 docstring 与 `protect`/`finish` 两处注释改为陈述实测机制（结构 walk 丢弃 nowiki 标签节点，故 protect 必须在遍历前），不再使用"执行"表述。实例属性 `_prefix`/`_saved` 与 loader `_load_rules`/`_freeze`、`_RULES`/`_BY_NAME` 继续留 `_`，收敛后它们已只在定义文件内使用。
- SPEC 已满足：本轮不新增、不扩大、不改变公开 interface，无 SPEC commit；机械内部收敛无有意义运行时 Red，记"Red 不适用"。nowiki 字面量保留已有既有回归测试（`tests/world/test_vcpedia_source_extraction.py::test_text_conversion_nowiki_is_literal_in_every_field`）覆盖，不新增用例。
- 验证：改动前后同一命令 `conda run -n lty --cwd server python -m pytest tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live' -q --tb=short -p no:cacheprovider`，独立 basetemp `data/test_outputs/internal-boundary-a/pre` 与 `data/test_outputs/internal-boundary-a/post`：改前 **2 failed / 286 passed / 1 deselected，51.69s**，改后 **2 failed / 286 passed / 1 deselected，51.99s**，失败用例同为 `test_supplement_resource_is_strictly_optional[True-unavailable]` 与 `[True-malformed]`。
- 上述 2 项为本轮改前即存在的既有红，不属于本切片且未在本切片内修改：新测试要求补提 prompt 缺失或损坏时初始化仍可降级，而 `task.py` 本轮新增的 `song_knowledge_extractor` 注册没有对应容错，`register_llm_module` 直接抛 `ValueError` 中止初始化。
- 定向验证：`structure` 在 `config/vcpedia_templates.json` 及 4 个 fixtures JSON 共 **355 个字符串**上完全幂等（非幂等 0），故 `is_excluded_field` 处的二次归并不改变行为；focused `tests/world/test_vcpedia_source_extraction.py -k 'nowiki or template_resource'`、独立 basetemp `data/test_outputs/internal-boundary-a/focused` 为 **14 passed, 68 deselected**。`compileall -q src/world/get_new_songs` 与 `git diff --check` 退出 0，仅既有 zhconv pkg_resources 弃用警告与 CRLF 提示。
- 作者自审完成，不替代独立审核；保留 HEAD `96c8726` 与全部其他未提交工作，无 SPEC/Red/Green commit、commit/push/PR。零网络、零真实模型、无生产读写；未运行全 Server 回归，focused 与四组结果不作为全站验收。

### 2026-09-12 补提 prompt 缺失不再降级（契约收缩，本地未提交）

- 明确撤销"补提 prompt 缺失或损坏不影响摘要初始化"的要求：`task.initialize` 对 `extraction_llm_module` 与 `llm_module` 同等处理，prompt 缺失或损坏时 `LLMService.register_llm_module` 直接抛 `ValueError` 并中止初始化，不新增局部 try/except 降级或回退。本条替代 2026-09-09 条目中"task 仅新增可选注册、局部异常日志"的表述；历史条目不改写。
- PRD 第 15 行改为"补提配置缺省不注册且不影响原摘要；补提配置存在时其 prompt 为部署必需要件，缺失或损坏即初始化失败，不做局部降级"；提取契约同句改为补提 cfg 存在时 prompt_name 必须可加载、PromptManager 仍逐文件容错跳过坏文件但 task 不做局部降级。无公开 interface 变化，`task.initialize` 的输入输出与异常契约仅在文案上与新行为对齐。
- 测试按新契约拆分：删除 `test_supplement_resource_is_strictly_optional`（`failure`×`configured` 共 4 实例，其中 configured=True 的 2 实例为改前既有红），其中仍必需的部分保留为 `test_unconfigured_supplement_registers_only_crawler`，并补 `task.extraction_llm_module is None` 断言；另增 `test_configured_supplement_without_prompt_fails_initialization` 钉住新契约。新用例首次即通过，属补契约测试，无 Red 证据。
- 验证：focused `conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_source_extraction.py -k 'supplement or real_registration' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/supplement-contract-a/focused` → **7 passed / 73 deselected，4.47s**；该文件 collect 后 `strictly_optional` 命中 **0** 项，旧参数化 id 已不存在。四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`-k 'not live'`、独立 basetemp `data/test_outputs/supplement-contract-a/four` → **286 passed / 1 deselected，50.56s，退出 0**，本记录起工作区无既有红（改前为 2 failed / 286 passed）。`compileall -q src/world/get_new_songs tests/world` 与 `git diff --check` 退出 0。
- 风险记录：本决定使 `res/agent/prompts/song_knowledge_extraction_prompt.json` 成为部署必需要件，缺失或损坏时的后果是**主摘要任务整条初始化失败**，不只是补提不可用。该文件当前为未跟踪新增，而 `config/config.json.template` 已默认配置 `extraction_llm_module`，故该 prompt 必须与配置模板一并纳入版本库，否则默认配置下初始化将直接失败。
- 作者自审完成，不替代独立审核；保留 HEAD `96c8726` 与全部其他未提交工作，无 SPEC/Red/Green commit、commit/push/PR。零网络、零真实模型、无生产读写；未运行全 Server 回归。

### 2026-09-12 测试去重：删除严格子集与合并重复契约（本地未提交）

- 按守则 239-247 扫描 5 个 VCPedia 测试文件共 **123 个测试函数**：无私有名导入、无 `caplog`/`capsys` 日志文本断言、无对项目内部实现的 monkeypatch、无完全重复的函数体、无 `time.sleep`；19 处 `len(model.calls)` 计数对象是 Fake provider（外部 seam）且 PRD 第 13 行明列 0/1/2 次，属契约成本，保留。
- 删除 1 个严格子集：`test_vcpedia_wikitext_contract.py::test_business_main_songbox_is_not_overwritten_by_derivative`（HEAD 中不存在，属本轮新增）只断言主框 infobox 不被二创覆盖，已被 `test_vcpedia_content_quality.py::test_first_candidate_derivative_never_overwrites_main` 的 4 个参数组合（两种模板 × 同名/异名）完全覆盖，后者另断言公共正文不被后框限制。
- 合并 2 处重复契约：nowiki 字面量保留由 `test_vcpedia_content_quality.py::test_texthover_nowiki_literal_is_not_executed` 并入 `test_vcpedia_source_extraction.py::test_text_conversion_nowiki_is_literal_in_every_field`（新增 `poem` 参数，字面量补入 `{{TextHover|…}}`，保留 LC 与 wikilink）；"关闭模型仍走规则"由 `test_vcpedia_content_quality.py::test_empty_field_without_model_preserves_other_business_values` 并入 `test_disabled_llm_keeps_rules`，改名为 `test_disabled_llm_keeps_rules_and_empty_field_discards_nothing`，断言空字段不丢弃兄弟字段且模型零调用。
- 验证：focused `conda run -n lty --cwd server python -m pytest tests/world/test_vcpedia_source_extraction.py -k 'nowiki or disabled_llm' -q --tb=short -p no:cacheprovider --basetemp=data/test_outputs/prune-a/focused` → **6 passed / 75 deselected，4.19s**；四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`-k 'not live'`、独立 basetemp `data/test_outputs/prune-a/four` → **284 passed / 1 deselected，50.07s，退出 0**（去重前为 286 passed），删除的 3 个用例名 collect 命中 **0**。`compileall -q tests/world` 与 `git diff --check` 退出 0。首次 focused 因 basetemp 父目录不存在产生 setup 错误，建目录后重跑，不计产品失败。
- 未做：两处 HTML 表层期望构造器（内容质量与固定验收各有一份 ruby/rp/脚注处理）仍在各自文件内，未抽到 `support/`；该重复属辅助逻辑而非重复测试，删测试不能解决。
- 未验证：全 Server 回归、真实站点/模型与生产未验收。无产品代码改动、无公开 interface 变化；作者自审完成，保留 HEAD `96c8726` 与全部其他未提交工作，无 SPEC/Red/Green commit、commit/push/PR，零网络/真实模型/生产访问。

### 2026-09-12 页面文本断言改为规则断言（本地未提交）

- 承接上条的判定（"页面文本 + 无规则条目 = 弱测试"），把 3 个用例与 1 处单点分支改造为规则断言，去掉对具体页面的依赖。
- 删除 `test_recorded_gift_other_information_does_not_start_with_comma`：它断言"其他资料不以逗号开头"，而该行为没有规则条目，源码里也没有通用去逗号规则——实测 `_information_text` 是按 `[，,；;]` 切分后丢弃空分段与含未解析计数标记的分句的**副作用**。新增 `test_other_information_drops_count_clauses_and_keeps_other_clauses` 用合成样例钉住文档规则（spec 第 16 行"其他资料仅移除局部统计分句"），期望值 `收录于专辑《测试专辑》，2012年12月19日投稿原版` 由规则推导并与实测双向确认。
- `test_recorded_yishen_first_intro_and_public_lyrics` 改为 `test_recorded_yishen_keeps_one_complete_intro_and_public_lyrics`：删去该页 142 字简介字面量、3 处歌词首尾/和声锚点与"非空行=30"计数，保留规则断言（唯一且非空的完整简介、公共歌词与 spaced_lyrics 非空、已知字段 `投稿时间` 保留、输出字段集合固定）。真实材料仍参与离线回放，但不再把该页文本当作期望值。
- `test_fixed_summary_wrappers_and_meaningful_information` 改为 `test_fixed_infobox_never_leaks_dynamic_counts`：删去按 `刀马旦`/`纸飞机` 分支断言该页简介句与"其他资料"字面值，保留规则断言"未解析动态计数不进信息框"。`test_fixed_full_lyrics_match_same_response_surface_html` 删去 `if page["title"] == "秦宣四方"` 的单点字面量分支，保留与同响应 HTML 表层的逐行比较（规则：zh-cn 输出按站点字形）。
- 结果：测试中已无按页面分支，仅剩 `sync_outputs` 的 `title.startswith("Template:")`——那是列表模板与歌曲页的分流，不是页面特例。`content_quality` 的 `json`/`Path` 仍被其他用例使用，无新增未使用导入。
- 验证：`tests/world/test_vcpedia_content_quality.py tests/world/test_vcpedia_fixed_acceptance.py`、独立 basetemp `data/test_outputs/ruleify-a/focused` → **79 passed，6.59s**；四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py`、`-k 'not live'`、独立 basetemp `data/test_outputs/ruleify-a/four` → **284 passed / 1 deselected，51.18s，退出 0**（用例数不变，本次为等价替换而非删除）。`compileall -q tests/world` 与 `git diff --check` 退出 0。
- 副作用与待决：`fixtures/vcpedia_recorded_gift.json` 失去唯一引用（引用数 0）。按"不静默删除不确定内容"的原则未删除，待确认后清理。`test_recorded_yishen_*` 的断言强度已下降为规则级 + 真实材料冒烟，是否保留整条用例也待确认。
- 未验证：全 Server 回归、真实站点/模型与生产未验收。无产品代码改动、无公开 interface 变化；作者自审完成，保留 HEAD `96c8726` 与全部其他未提交工作，无 SPEC/Red/Green commit、commit/push/PR，零网络/真实模型/生产访问。

### 2026-09-12 冗余清理：派生规则、渲染材料、oracle、配置双写（本地未提交）

- spaced_lyrics 派生规则原有 **3 份逐字相同副本**（`wikitext_parser`、`text_conversion`、`source_extraction`），收敛为 `text_conversion.spaced_from(text)` 一处；三条输出路径不再可能静默分叉，下游 split 可消费的契约只有一个实现。
- **渲染片段不再作为模型材料**：`collect_materials` 删除 `materials[str(index)]`，渲染结果只经 `merge_missing(rendered=True)` 本地合并，模型只收到 `raw` 源码；这同时消除"模型返回已渲染文本被二次 zhconv 转换"的字形风险。按 RED→Green 完成：新增 `test_rendered_fragment_is_never_passed_to_the_model_as_material` 先在 `Extra items in the left set: '0'` 上失败，改后通过。
- 页面文本 oracle 的两份实现（内容质量与固定验收各自处理 ruby/rp/脚注）合并为 `server/tests/world/html_surface.py`，采用 rb/rt 契约（rb 非空取 rb、空白 rb 保留 rt）。合并前逐页比对：6 份冻结页完全一致，仅《达拉崩吧》不同——旧简化版会丢掉"空白 rb 的实唱啦啦"，故合并取契约版。
- 三个硬编码模板名（创作者名单/creator/creators、嵌入、歌词）与 `bilibilicount` 特例改为 `kind in {"songbox","staff"} or name.endswith("count")`；`parser` 的角色优先级元组移入配置 `role_priority`（`_load_rules` 将其列为必需顶层键，解析器改读 `role_priority()`，有序语义随之上移）。等价性验证：在配置、冻结材料与测试中出现的 **141 个模板名**上逐名比较新旧判定，5 个（infobox song/infobox songex/staff/制作人员/youtubecount）仅由"隐式跳过"变为"显式跳过"，**0 个改变处理结果**；`role_priority` 与原元组逐项相同。
- 删除死数据：`vcpedia_recorded_gift.json`（205 KB，上一条规则化后引用数归零）与 `vcpedia_list.wikitext`、`vcpedia_song.wikitext`（`96c8726` 引入且从未被任何代码或测试引用）。
- 文档职责重划分（守则第 100-105 行）：PRD 的切片措辞改为现行陈述；不可复现的 I LOVE YOU 摩斯电码验收锚点改为"仓库内冻结材料离线回放"；embed 名单补"嵌入片段"；PRD 末条的流程约束移出 PRD 并记入本条。提取契约的"不在本轮"改为明确非目标，并补记 `role_priority` 为必需顶层键（顺序属契约）、渲染文本不作为模型材料。
- 验证：四组 `tests/world tests/test_world_task_vcpedia_new_songs.py tests/test_world_runtime_config.py tests/test_world_task_event_cleanup.py -k 'not live'`、独立 basetemp `data/test_outputs/redundancy-a/final` → **285 passed / 1 deselected，50.79s，退出 0**（清理前 284 passed，新增 1 条契约测试）。`compileall -q src/world/get_new_songs tests/world` 与 `git diff --check` 退出 0。
- 本轮执行约束（由 PRD 末条转记于此）：离线固定材料回放与四组回归，不联网、不调用真实模型、不 commit/push。
- 未验证：全 Server 回归、真实站点/模型与生产未验收。作者自审完成，保留 HEAD `96c8726` 与其余未提交工作。
