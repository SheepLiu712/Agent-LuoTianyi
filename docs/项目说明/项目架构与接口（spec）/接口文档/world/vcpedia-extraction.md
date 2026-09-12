# VCPedia 歌曲提取契约

## 入口与边界

保留 `VCPediaFetcher(config, llm_module=None, *, extraction_llm_module=None).fetch_entity_description(entity_name, short_summary=True, *, source_title=None)`；source_title 仅供已知列表目标请求，name 仍为显示名。`do_one_song(..., update=False, *, source_title=None)` 只增加可选请求目标；`sync_daily_new_songs(..., llm_module=None, *, extraction_llm_module=None)` 及 task 保持 added/failed 统计。禁用返回空字符串，抓取失败返回 None，已有缓存按 `96c8726` 原样返回，不新增写回。

结果保留 name/type/infobox/summary/lyrics/spaced_lyrics/short_summary。不输出 versions、source_info、source、extraction/cache 状态。无歌词证据时保留历史 Person fallback（不是准确人物识别）；do_one_song 保留基线不检查非 Song 的返回边界。

## 三独立规则结果

- 首个歌曲框的信息框及其相邻 staff 为信息框候选，后框不得覆盖；不按名称、标题或字段得分选择。开放业务键，排除展示控制，staff 支持 groupN/listN 和 role=value；信息框的展示/内容槽排除不误用于 staff 业务角色，“视频”保留原键，不改名 PV，空角色或样式角色不加入缺项。
- 简介与歌词各自按页面及局部内容源码顺序独立保留既有首成功候选选择（顺序不表示主次），与信息框所在 tabs 无关。简介含首个简介章节的完整段落及子标题正文；不以 short_summary 替代。模板不以名称白名单作为结构遍历门禁：参数值按源码顺序递归寻找明确歌曲框、标题和 poem；未知参数纯文本不作为简介或歌词，poem 仍须位于原有歌词章节或已知歌词槽内，不把简介引用当歌词；局部标题不跨兄弟参数或改变外层章节。已知内容槽及 LyricsKai 原译语义优先，已消费内容不重复遍历，nowiki/注释保持不透明；不生成页面图或版本记录。
- 歌词保留原文换行、空段、括号与和声；Lyrics lb-textN、LyricsKai original、Small 歌词等已确认参数直读，不混 rb-textN/translated。标准 markup、Ruby 表层和空白表层时实际唱词保留；未知模板参数不盲拼。
- zhconv 普通 `convert(..., 'zh-hans')` 仅用于结构比较和已知字段键，不叠加 zh-cn 地区词替换，未知键保留；不承诺与其他转换库全字库等价。普通提取正文（infobox values、summary、lyrics、spaced_lyrics）使用 zhconv 转 zh-cn；无标志 `-{繁體}-` 解包并保护字形。闭合 nowiki 仅去外层标签，内部文字、LC、template、link、空白和换行原样保留且不执行。仅支持常见 noFlag 与 nowiki，不扩展 R/A/H 或未闭合语法。
- 原 source、请求 title、链接 target、页面身份及 data.name 不转换。内部在解析前暂存 nowiki，普通 LC 内联 template/link/HTML 仍按原提取规则处理，仅最终可见字形受保护，在字段最终一次转换后还原；不新增结果字段或 protected-content 映射。模型补提新字段与新 short_summary 同样转换并保护其保留的标记，已有字段不再转换；摘要 fallback 直接截取已完成正文，不二次转换。局部 HTML 已渲染、失去保护标记，沿用站点文本，不盲目转换。模型材料允许保留源码标记，无法恢复模型主动丢弃的标记。
- 动态计数缺失时简介移除完整统计句；其他资料仅移除局部统计分句，不为计数联网。spaced_lyrics 从原文行及标点派生，沿用旧关键词 split，不添加长窗口或改消费者。

## 模板资源配置

既有模板描述集中于 `server/config/vcpedia_templates.json`（UTF-8 规则配置，不属于知识库），内部加载器按源码 resolved 路径在模块初始化时加载一次并冻结；不新增 fetcher 配置键、环境变量、热更新或服务定位器。文件/JSON/描述错误明确抛出含资源与字段位置的异常，不回退内置规则。名称使用同一 zhconv zh-hans 结构归一及大小写比较；同描述内等价别名合并，不同描述占用同名拒绝。资源顶层键固定为 `description`、`templates`、`field_aliases` 与字段列表（`known_fields`、`presentation_params`、`presentation_contains`、`field_exclude_params`、`role_priority`），缺键或形状错误即启动失败；`role_priority` 为有序角色名列表，单列信息框按其中首次命中决定字段名，故顺序是契约的一部分。默认业务输出及参数源码顺序、重复键、原译和角色语义保持。

资源使用固定 `kind`、名字列表、参数/前缀列表、有序角色优先级及字段别名；不接受正则、脚本、eval 或网络指令。修改 `inline` 的 `text_params`（如 `["2"]`）可改变取文槽；给 `wrapper` 的 `body_params` 增加 `payload` 可继承正文上下文；歌词原译槽、tabs 正文/标签前缀、信息框别名/展示排除及 staff group/list 可在资源中调整，无需改 Python。`text_params` 按优先级取最后一次出现的参数，数值槽仍用字符串表示。新增处理 kind 才需代码与测试；Ruby/Utawari 标准算法、整体排除、标题识别及未知参数明确结构发现仍在代码中，并非全部 if 配置化。TextHover 使用 inline 参数1作为可见文字，参数2替代文案不拼入，参数3 before/after 与 tag/span 等展示参数不参与选择；参数4为 pic 时整体排除。font、其他 hover 能力及高级 LC R/A/H 不在当前契约内，是明确非目标。

inline 可选 `skip_if` 为非空参数名到非空字符串列表的非空对象，例如 `{"kind":"inline","names":["TextHover"],"text_params":["1"],"skip_if":{"4":["pic"]}}`。任一条件的参数原值与列表任一值经 strip/casefold 相等即不输出；缺失参数按空字符串比较，条件不解析模板、正则或表达式，不转换正文。错误形状沿用启动时明确报错。通用结构发现不下探已声明 inline 的参数（取文仍由 inline 路径完成），避免替代文案、展示结构和图片文件名成为独立正文。新增同类模板仅需 JSON 名称、取文槽及上述可复用条件，不新增模板专用 Python 分支。

测试从公开 fetcher 观察临时资源中的自定义 inline 参数2、容器 payload、原译/角色与嵌入行为；只替换外部文件读取，不改仓库资源，不调用私有 helper。默认使用同输入快照离线比较完整业务结果。

## 缺失补提

内部一次得到独立结果及临时缺失清单，不持久化 requested/metadata。明确空业务字段（含 staff 非空角色的空值）、已确认歌曲缺简介/歌词为缺口。仅在已进入明确简介/歌词正文的取文路径中，未能处理的非空正文槽内容标记对应 needed 布尔值；页外未知模板、资料/控制参数、空调用及已配置跳过项本身不构成缺口。Ruby 等含表层的结构只提交实际采用分支的缺口：表层非空时不因未采用的注音内容标记，表层为空而回退取注音时按注音的实际取文结果标记。未完成目标不因别处候选非空而清除；保留既有单字段首成功返回行为，源码顺序不表示主版本，不增加选首失败即空、拼接全部歌词或版本标签。可选补提仍只按 requested 字段及类型合并，允许替换已标记不完整的单字段；完整且未请求的字段不覆盖，材料为一次字形转换并剔除计数统计后的源码文本，不向模型指示主次。未知参数仍不盲拼，不新增模板专用解释规则。

新抓取 Song 保持原摘要时机（不受 short_summary 展示参数影响）：use_llm=true 且 llm_module 可用时独立生成一次纯文本摘要。完整页仅1次摘要；仍有缺项且 extraction_llm_module 可用时先1次 JSON 补提、仅合并缺口，再以合并后的 song_data 生成1次摘要，共2次。补提失败仍执行摘要；摘要失败取已合并简介前100字符，不二次转换。Person 保持已有可选缺项补提，不新增摘要或分类。关闭模型或缓存命中均0次模型调用。

crawler.llm_module 与可选 crawler.extraction_llm_module 是两个显式完整配置，分别注册 song_knowledge_crawler 与 song_knowledge_extractor。只依据各自 cfg 注册，无继承、深拷贝派生、拼接 prompt 或参数覆盖；沿原 provider/client 委托、JSON/thinking/tools/timeout/params 路径。原摘要 prompt 文件恢复96c8726纯文本原值，配置模板原摘要 JSON 设置不变。补提模板独立指定 song_knowledge_extraction_prompt、provider 引用及 use_json=true；仅原配置不自动启用补提，无新开关，use_llm 统一控制调用。

VCPediaFetcher(config, llm_module=None, *, extraction_llm_module=None) 与 sync_daily_new_songs(config, llm_module=None, *, extraction_llm_module=None) 仅增加 keyword-only 注入；task.initialize 注册两配置，run_once 显式传递。LLMService/LLMModule 没有 per-call prompt override，复用原注册与 generate_response API。补提 cfg 缺省不注册、不主动读取额外补提文件；补提 cfg 存在时其 prompt_name 必须可加载，PromptManager 仍逐文件容错跳过坏文件，但 task.initialize 不为该配置做局部降级，prompt 缺失或损坏即直接失败。

独立补提 prompt 只请求 needed 信息框字符串字典、summary 字符串数组、lyrics 原文字符串，不请求 short_summary；提供正向示例及材料不足填 null 示例。输入 song_data、needed、materials 均必填，materials.text 为一次字形转换后的源码文本。响应只解析 JSON 对象与字段类型，坏 JSON/null/异常/超时保持规则值继续摘要；只合并请求的缺项。补提新字段按材料同一次转换的结果作为最终文本合入，不做第二次转换；新摘要沿已有保护转换一次。已标记不完整的请求字段可被替换，完整且未请求的字段不覆盖，不做语义判卷。source_extraction 只收集材料与合并，不调用模型；必要嵌入先于模型，程序渲染后直接合并（保持站点字形，不再二次转换），渲染文本不作为模型材料——材料只含源码文本，模型的价值在读源码而非重读已渲染制品——因而不改变其预算。材料在转换后、截断前按既有计数政策剔除不可展开的统计：散文行移除含计数模板的完整句子（同简介政策），以 `|` 起的模板参数行仅移除含计数模板的分句（同其他资料政策），判据为模板名后缀 `count`；因此材料不含计数模板，成就表述随统计句一并移除，其他非计数模板照旧。`source_extraction.material_text(source)` 是唯一材料构造入口，collect_materials 与 `scripts/vcpedia_prompt_lab.py` 都经它取材料。

仅明确目标区域的 Embed/嵌入/嵌入片段/CollectCodeData 允许局部 parse 完整调用；归属只由章节及已知正文槽传递，page 等普通参数里的“歌词/简介”不授权，局部标题不跨兄弟参数，无法归属则不获取并保留规则缺口；最多两片，去重且不递归渲染结果，单片8000字符、总文本12000字符保护。原材料与模型响应最多24000字符；失败保持本地结果。不建立通用 unknown renderer。HTTP 挑战与 curl 沿既有通道。标题 page 请求仍 GET；仅局部 render_fragment 使用 POST，UTF-8 表单编码正文放 request body，curl 以 `--data-binary @-` stdin 传输并带 `Content-Type: application/x-www-form-urlencoded`，不把长源码放 URL/argv；原 HTTP 状态、challenge、write-out 校验不变。

## 明确退役与验证

此前 scope/version/derivative、canonical 元数据、缓存 schema/extractor/TTL/hashed identity/partial保护及写回、SQL upsert/事务改造、关键词补偿/原子替换/归属清理/长窗口、batch/deadline/failureTTL/skipped/budget_exhausted 契约全部退役。恢复 `96c8726` 对应行为，不恢复被用户删除的 owner 表述。

从公开 fetcher 验证首信息框不限制公共歌词、首个完整简介及繁体正文、未知不触发及一次补提；从列表/sync 验证 target 请求和 display 入库。保留历史真实 fixtures 离线回放及基线回归，不以本地测试声称全站或真实模型验收。
