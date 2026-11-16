# AI 决策记录

本文件记录 #412 规格的推荐、否决理由与非作者裁定。完整规格已通过 D3 attempt 2/3，可作为分阶段实施依据；不表示人类此前逐项批准派生设计，也不是 A1–A6 或运行代码验收通过。具体提交/实施权限仍由 lead 逐阶段授予。

- 工单：[Issue #412](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/412)，2026-11-17 读取最新 body（`updated_at=2026-11-16T15:37:16Z`），comments 为空。
- 调查基线：`ee718b21536e410ce5e4073b068f03b9bfcd68dc`；分支 `feat/component-startup-switches`。
- 交付规格：[组件级启动开关](<docs/specs/component-startup-switches.md>)。依 [开发守则](<docs/开发守则.md#L5-L9>) 已完成非作者门禁；规格阶段没有运行代码/测试/现用配置/密钥改动或业务运行、依赖安装。lead 已单独授权本次两文档原子提交，不推送、不操作 GitHub 写入。
- 2026-11-17 D3 attempt 2/3 已确认 N1/M1-S 和 N2 闭合，G1–G6 无新增必修，许可完整规格用于分阶段实施。审查冻结输入：418 行 spec SHA-256 `9a60e13c4f23447f5bb093347476354f38e36222976f918c9805c66350cffae8`；260 行 AI_DECISIONS SHA-256 `39d63748ffafd4c911a10ac25738c7e6aef50b07f74c9d6a9a399b17a47770db`。本次只机械登记报告摘要，不改已审契约；下文“待 attempt 2”等保留为历史记录，由本裁定覆盖，不代表仍需用户逐项确认。A1–A6、运行代码、真实资源与控制台均尚未验证，下一 phase 仍等 lead 明确 scope。

## 2026-11-17 在现有装配接缝选择真实或禁用 Adapter

**待定问题**：怎样让 TTS、向量资源明确不启动，又不把 `None` 和异常兜底判断散布到 Stage/所有调用方？

**背景约束**：不改配置时全量行为不变；只逐项开关，不加 preset/新环境变量。现有 [AgentRuntime](<server/src/agent_runtime/agent_runtime.py#L123-L139>)、[SharedSkills](<server/src/agent/skills/facade.py>) 已有具名装配与清理 owner；向量依赖非空，SAY 的空 TTS 是失败。

**调研参考**：2026-11-17 经 Context7 `/websites/fastapi_tiangolo` 读取 [官方 Lifespan](https://fastapi.tiangolo.com/advanced/events/) 及 [生命周期测试](https://fastapi.tiangolo.com/advanced/testing-events/)。官方示例将共享模型在接请求前加载、结束后释放，并解释模块导入时加载会拖慢独立测试；测试须进入/退出生命周期。只借鉴受控资源所有权、非 import 时昂贵初始化和完整清理；本项目已经显式拥有业务 runtime，不照搬/迁移为 FastAPI lifespan。页面为滚动文档，查询日期不是版本锁，不能推导本项目已安装的具体版本。

**候选方案**
1. **装配选择 + 禁用 Adapter**：在现有 owner 构造前选择，无后端资源；以少量只读 `enabled` 能力事实影响必要业务路径。兼容原方法，集中保障启动/关闭/回滚。
2. **依赖置 None + 到处判断**：少建类型，但使所有 caller 和依赖门禁学习禁用/关闭语义，易漏分支。
3. **首次调用 lazy 初始化或捕获失败降级**：启动看似更轻，首次对话仍可能加载资源或联网，也难区分主动关闭和真实故障。

**选择**：推荐候选 1，缺省 true；disabled Adapter 非空，业务只在语音输出和记忆投影的窄接缝作能力判断。

**选择理由**：沿既有架构取得 Locality；真实与禁用两个 Adapter 让变化明确，可用构造陷阱验证“不拥有资源”，关闭和失败回滚仍由原 owner 承担。不需要重构全局服务注册框架。

**未选原因**
- 候选 2：当前 AgentMemory/AgentRuntime 明确要求非空向量，改为 None 会扩大 Interface，并容易漏掉 prepared SAY、用户重置和初始化失败回滚。
- 候选 3：不满足 A2/A3“无需资源且禁用时不使用”的可观察契约；把任意 provider/数据库故障当禁用会降低 enabled 下的安全网。

**验证方式**：缺省/true 对比保持原装配；false 时 TTS/Chroma/embedding 构造与 HTTP 如被触发即失败；关闭/部分初始化回滚无残留。完整生命周期及真实 HTTP/WS/SQL 证明由实现阶段负责，本文未执行。

**风险与回滚**：能力事实若被解释成全局静音/全部记忆关闭会扩大语义；规格分别限定 SAY、向量投影。通过操作者在隔离配置恢复 true 并重启回退，不改其现用配置。

## 2026-11-17 默认兼容的配置与 AMAP 条件校验

**待定问题**：新键放在哪里，禁用后哪些资源可以缺失，如何避免假称当前缺 AMAP 已非阻断？

**背景约束**：[validator](<server/src/infrastructure/config/validation.py#L41-L129>) 当前仍把 JWT_SECRET 与 AMAP_KEY 都列为 core 必需；[管理 Secrets](<server/src/web/admin/admin_interface.py#L244-L261>) 也有独立 required 标记。关闭 TTS 不关闭 singing、模型引用、SQL/媒体；不为本机写密钥。

**调研参考**：上述 FastAPI 官方生命周期只支持“有需要才创建资源”的技术原则，未规定本项目的配置键/密钥政策。键的 owner 和严格配置错误采用 [SkillsConfig](<server/src/infrastructure/config/skills.py>) 与 [WorldRuntime](<server/src/world/world_runtime.py#L286-L288>) 的本项目接缝；具体产品选择由本草案提出，不冒称外部标准或用户原话。

**候选方案**
1. **所有者节点逐项 bool**：`agent_runtime.skills.speaking.enabled`、`agent_runtime.vector_store.enabled`；缺省 true，非布尔拒绝。`citywalk.enabled=false` 才解除 AMAP 核心必需，其他条件保留。
2. **全局 lightweight/development 模式**：一个键隐含关闭多种能力，或新增环境变量覆盖。
3. **按凭据是否存在自动选模式**：缺资源自动忽略或用虚构 AMAP/key 占位绕过 validator。

**选择**：推荐候选 1；对明确禁用的专属资源条件跳过校验/初始化；AMAP 条件及 Secrets required 显示由同一有效规则决定。

**选择理由**：逐项可解释，缺省兼容；顶层 citywalk false 是确定信号，不需要推断全部 per-character 覆盖。JWT 必需和核心安全检查不削弱，A5 不应为了不使用的城市漫步要求真实地图 key。

**未选原因**
- 候选 2：直接违反不 preset/新 env；隐含组合会让 A1、回滚和 README 不透明。
- 候选 3：掩盖真实错误、不满足显式选择，伪造密钥有安全/错误诊断风险。基线当前 AMAP 阻断必须如实说明，而不是靠旧 world warning 推导可启动。

**验证方式**：对两项新键及九项任务键做 omitted/true/false/非法值测试；无 AMAP + citywalk false 可通过此项，无 AMAP + omitted/true 仍按原 core 门禁；验证管理 required 显示一致，无密钥值写入/日志泄露。

**风险与回滚**：恢复 citywalk 时缺 key 将重新阻断，README/控制台必须可诊断。回滚需恢复原配置与资源再重启；不删除存储的 key，不借本变更降低全量发布资产清单。

## 2026-11-17 普通 SAY 禁用音频必须走合法文字终态

**待定问题**：TTS 关闭后怎样满足“无音频、文字可达、明确结束”，又不漏 prepared 音频或把 Call 假称可用？

**背景约束**：[SayHandler](<server/src/agent/handlers/action/say.py#L27-L112>) 在 TTS 之前走 prepared 分支；空语音是失败。[Say 值类型](<server/src/domain/agent/action_plan.py#L70-L91>) 已允许纯文字；[WS 转换](<server/src/adapter/websocket/chat/_protocol_translate.py#L118-L133>) 已有成功终态，无需扩协议。Sing 为工单明确排除的独立能力。

**调研参考**：未找到可直接借鉴且可替代本项目输出语义的外部先例；优先采用已存在的 TextFinal/Expression/MessageEnd Interface 及工单 A2。FastAPI 的资源生命周期不决定消息成功/失败语义。

**候选方案**
1. **在普通 SAY 音频分流前选择禁用成功路径**：保留正文/表情；不读预制或 TTS；输出唯一 COMPLETED 终态；Call 能力报告不可用。
2. **禁用 SpeakingSkill 返回空流**：不改 Handler，沿原输出路径消费。
3. **只禁用合成、继续 prepared 音频；或顺带全局静音含 Sing**：较少触及某一分支或更彻底静音。

**选择**：推荐候选 1；prepared 无正文瞬时反应不造气泡，仍发终态。普通 SAY 的 `audio` 始终空串；Sing 继续原行为。

**选择理由**：符合 A2 可见结果与现有协议，避免将主动禁用计算成 AUDIO_EMPTY。`supports_call_audio=false`、`call_tts_character_ids=()` 可复用现有准入和原因优先级，不发明“纯文字 Call”。

**未选原因**
- 候选 2：现有 SpeakingSkill 会 EmptySpeechError，Call 空流也为失败；会向客户端发 `TTS_EMPTY`，不是合法完成且易挂住消息消费者。
- 候选 3：继续 prepared 违反普通 SAY 无音频；全局静音则扩大到明确排除的 singing 曲库/演唱能力。两者均混淆“禁用语音合成”的本轮明确边界。

**验证方式**：真实 WS 两条连续正文、prepared 欢迎、ephemeral 无正文反应；检查全部音频字段为空且每消息唯一成功终态。补 Call capability 原原因优先级及绕过准入的拒绝；enabled 的超时/取消/空音频失败不变。

**风险与回滚**：不能用成功终态吞 sink/连接真实失败；触摸仍不显示聊天气泡；用 TTS true + 资源恢复并重启回退，不改变客户端协议。

## 2026-11-17 向量关闭保留 SQL 正本，不伪造投影成功

**待定问题**：A3“显式记忆写入不报错”应保留什么，怎样兼容维护/旧写入口而不造 upsert ID？

**背景约束**：[MemoryWriteSkill](<server/src/agent/skills/memory_write.py#L126-L175>) 将正本、upsert 确认和关联分开；[维护 writer](<server/src/agent/skills/adapters/memory/writer.py#L251-L319>) 先 embedding 后正本；[旧 intentional 提交](<server/src/agent/skills/adapters/memory/intentional_commit.py#L75-L158>) 有补偿删除与“已有记录必须有 embedding”的旧假设。未获确认的派生数据语义须明确写候选。

**调研参考**：本项目 [AgentMemory](<server/src/agent/skills/adapters/memory/facade.py#L94-L137>) 已将向量称为召回索引，命中后回 SQL 正本；[ChromaVectorStore](<server/src/infrastructure/persistence/database/vector_store.py#L164-L258>) 表明真实 upsert 确认必须来自后端。官方生命周期支持绕过昂贵实现，但没有外部资料可以替用户决定“关闭等于丢弃”还是“保留 SQL”。因此以下是本地设计推荐，不标为用户已批准或官方规定。

**候选方案**
1. **SQL-only + 空长期召回**：显式/事件/维护都可靠保存正本，跳过向量准备/upsert/link，返回真实 SQL ID；不自动回填。
2. **全部 no-op**：显式请求报告无错，但内容不保存或只保存一段临时确认。
3. **NullVectorStore 假成功 ID**：返回输入 ID/随机 ID 让旧链路继续链接，或自动启用本地 embedding 替代。

**选择**：推荐候选 1；维护结果区分 `CANONICAL_ONLY` 与真实供应商故障 `SKIPPED_EMBEDDING`。原身份/冻结候选/幂等/冲突/画像/摘要/进度职责保留。

**选择理由**：SQL 已是正本；保留用户内容不需要重资源，不捏造检索能力。写入口集中依据 enabled 事实绕过投影，旧路径对 SQL-only 的重复判断/补偿需一致，不能假成功后破坏关联。

**未选原因**
- 候选 2：用户“记住”的持久意图被无声丢弃；“不报错”并不授权假装已保存。需要额外明确产品决定才能选。
- 候选 3：破坏“关联指向真实向量”的不变量；零向量/默认本地模型仍可能加载/联网，与无需向量资源冲突。不能用假 ID 或自动回填掩盖 disabled。

**验证方式**：对真实 SQL 检查正本存在、真实 memory_ids、关联数量不增加；同源重试不重复、内容冲突不吞；维护无 embedding 且画像/摘要/进度可提交；enabled provider/SQL 故障维持原语义。重新启用不会自动回填。

**风险与回滚**：SQL-only 不可长期向量召回，语义相似去重退化；README 与确认材料准确说明。关闭不删数据，恢复 true 后原索引照旧可查，但关闭期间正本不承诺被检索。不要为了回退删除 SQL-only 正本。

## 2026-11-17 world 全关选择组合根三门控，保留不含它的边界

**待定问题**：A5 要全部 world 定时任务关闭，而工单又排除“world 任务代码改动”；是否存在不改任务内部的合法接缝？

**背景约束**：已核查 [WorldRuntime](<server/src/world/world_runtime.py#L66-L118>)、[WorldTask](<server/src/world/types/world_task.py>) 和 [WorldClock](<server/src/world/world_clock.py#L50-L93>)。六类有门控，song_knowledge/proactive_topic_check/expired_event_cleanup 无条件创建；空 tasks 当前被拒绝。不存在 `world.enabled`。

**调研参考**：本项目已有 `_task_enabled` 与六类构造前门控是最适配的成熟局部先例；FastAPI 官方共享资源生命周期支持 owner 控制存在性。没有外部项目资料能够判定本仓排除项的文字范围。已核对 `interval_seconds=0` 会报错，大周期仍注册，crawler.activated 不阻止 [远端列表获取](<server/src/world/get_new_songs/daily_new_song_fetcher.py#L149-L166>)，故不能借配置频率造禁用。

**候选方案**
1. **A：只改 WorldRuntime 装配门控**：三类按已有约定判断 enabled（缺省 true）；允许已初始化的合法空 tasks；不改任何任务内部/基类、周期和立即运行语义。
2. **B：完全不改 world 源码**：交两重组件、AMAP、管理和六类已有开关文档；准确保留三类常驻任务，A5 未满足。
3. **频率/非法 type 绕过，或新全局 world.enabled**：尝试不执行或统一关闭。

**选择**：推荐 A，并在规格保留 B 作为不含该变更的准确边界；**后续裁定：D3 attempt 1 已接受 A 属组合根允许范围，不需另等人类批准，不授权改任务内部。** 原记录中的范围不确定性已由非作者解释收敛，整体 spec 仍因 N1/N2 待复审。

**选择理由**：A 复用最小 Seam，以组合根决定是否构造，不改任务算法/触发逻辑，能够同时满足逐项选择、默认兼容和 A5。“world 任务代码”不必然等于“禁止组合根门控”，但需审核者明确解释，不能作者自行扩大已批准范围。

**未选原因**
- B：合法且可独立描述，但 A5 明确未满足，不能按 #412 全部完成验收；仅在维护者拒绝 A 时交这一边界，不悄悄删标准。
- 候选 3：频率和非法 type 不是 disable，会仍初始化/注册，伪造 `world.enabled` 又与逐项控制冲突且不在现状存在。

**验证方式**：单项 false 不构造/初始化/注册，true/省略保持原数据；全九项 false 注册和执行计数为零且空集合不拒启动；不改任务类/内部的差异审查。先取得非作者对范围的明确结论。

**风险与回滚**：D3 attempt 1 已裁定 A 不构成任务内部范围例外；不得把这一接受扩大到 citywalk scheduler/ingestor 工作流修改。节假日一次性 SQL 初始化、Stage/观测/心跳不属 world 定时任务，保留且不冒称全进程后台/联网关闭。恢复具体开关重启，旧任务按既有周期恢复，不保证补跑。

## 2026-11-17 禁用向量期间旧索引重置不得假成功

**待定问题**：向量关闭时用户清除数据，若已有旧 Chroma 文件而低层直接返回 0，重新启用后会不会恢复旧数据？

**背景约束**：[UserResetService](<server/src/application/user/user_reset.py#L69-L103>) 要严格删除向量；[旧向量兜底](<server/src/agent/skills/adapters/memory/facade.py#L211-L225>) 可能不依赖仍存在的 SQL 正本。禁止自动删除旧库/共享目录，不为清除偷启 Chroma。

**调研参考**：未找到可直接借鉴且无需新增持久状态的成熟先例。以现有 reset 的显式部分失败报告和“不得声称删除未删除的数据”的数据真实性为依据；这是风险约束和推荐候选，不是当前已实现的保护。

**候选方案**
1. **无旧资料可空成功，存在/未知则明确失败**：只读检查配置的向量路径；不存在/空目录返回 0，非空或不可判断抛诊断错误，沿现有 vectors 失败报告，指导先启用再重置。
2. **disabled 一律返回 0**：最小 no-op，SQL 其他步骤继续。
3. **持久删除意图/授权墓碑/下次启用再清理**：支持关闭时受理，但新增存储协议、启动清理和恢复机制；或直接删整个目录。

**选择**：推荐候选 1，交非作者审查其保守可用性边界。

**选择理由**：不加载禁用资源，避免隐私删除假成功，也不引入未请求的迁移系统。只对需清旧资料的重置报告未完成，不影响 A3 启动和显式记忆写入。reset 现有流程会有其他步骤部分成功，需如实披露，不伪造事务保证。

**未选原因**
- 候选 2：可能向用户宣称全部清除而留下可召回旧向量，尤其 legacy 路径有复活风险。
- 候选 3：协议与范围成本明显超出两个启动开关；直接删共享目录又可能破坏他人记录。未获明确批准不能作为“顺手修复”。

**验证方式**：分别用无索引、空目录、已有记录目录和不可读/未知路径；验证不会打开 Chroma，新空实例 reset 正常，旧资料 vectors 步骤明确失败且不会误报总成功。enabled 原严格删除回归保留。

**风险与回滚**：非空目录即使不含该用户记录也会保守拒绝“向量已清除”；接受该限制或另审持久删除意图由维护者决定。操作者在资源准备好后启用并重新执行 reset，不由本轮代理删除目录或密钥。

## 2026-11-17 管理台复用局部草稿与现有校验重启，不新增热切换

**待定问题**：A4 怎么让两项开关在控制台可操作，又不覆盖其他面板草稿或误报重启成功？

**背景约束**：[现有配置 DTO](<server/src/infrastructure/config/model_editor.py>)、[apply 路由](<server/src/web/admin/admin_interface.py#L296-L338>)、[局部面板](<server/res/admin_ui/src/main.tsx#L1521-L1649>) 已完成校验→原子保存/备份→Supervisor 重启。

**调研参考**：本项目现有管理工作流为首选；官方 FastAPI 生命周期不授权绕过它。界面针对性检索 `ui-ux-pro-max` 的 `ux` 域 `settings form save validation`：匹配 All 平台 Forms/Submit Feedback、Accessibility/Form Labels、Forms/Inline Validation；仅采用标签明确和提交加载/成功/错误反馈，不引入新视觉体系、图标依赖或页面重构。

**候选方案**
1. **原 DTO 增 component_startup 投影**：新增两复选框面板，部分 patch 映射两个配置叶子，校验/保存/重启仍走原链。
2. **新增 components 热切换端点**：分别启动/停止后台资源，不重建业务 runtime。
3. **任意 raw JSON 全量编辑保存**：界面可快做，但会携带/覆盖其他草稿及资源参数。

**选择**：推荐候选 1，`component_startup` 只是管理 DTO，不增加持久全局配置节点；两个键逐项 patch。

**选择理由**：最少网络与生命周期知识，保留未保存草稿；不破坏旧调用者省略新字段的行为。响应区分 written、restart requested 与真正 runtime running。

**未选原因**
- 候选 2：违背指定重启链，增加在途请求/资源引用切换并发问题，超出 A4。
- 候选 3：混合其他模型修改及原始 `$VAR`/密钥风险，不能保证“只改开关”。

**验证方式**：管理 API 的局部叶子映射、非布尔 422、不写入/不重启、停止状态不启动；实际浏览器分别改两项、刷新读回、其他面板草稿保留、缺资源重启显示真实失败，不拿 restarted=true 当可用证据。

**风险与回滚**：当前 restarted 表示曾运行并发起重启，不代表新 runtime 成功；UI 必须看 state。失败保留原错误/所有权，操作者恢复正确配置或备份再重启，不覆盖现用配置。

## 2026-11-17 以真实链路和同机原始值验收，不把估算当资源收益

**待定问题**：怎样提供成本可控、又足以证明 A1–A6 的证据？

**背景约束**：工单要求单元/集成、实际控制台和全量/最小资源比较；本轮仅 spec。已有 TTS 600s 为等待上限、Chroma 150–300 MB 为静态估计，不是本轮实测。

**调研参考**：FastAPI 官方生命周期测试要求观察实际启动/关闭；本仓 [开发守则](<docs/开发守则.md#L49-L67>) 要求从测试之外确认预期，不能拿 mock 返回值自证。采用规格 V0–V5 分 owner 证据预算；不重新发明基准工具链。

**候选方案**
1. **分层证据**：离线构造陷阱/真实 SQL/WS 契约，隔离实际闭环，非作者控制台/README；同机同条件全量/最小各至少三轮原始测量。
2. **只跑 mock 单测与 runtime.running**：便宜，但没有启动资源、客户端收包或 UI 证据。
3. **用 issue 中 GB/MB 估计填收益，或先做全量 CI 当全部验收**：看似数字完整，却无法证明本次功能行为。

**选择**：推荐候选 1；不同 claim 单一 owner、最小非重复测试；外部门禁由 lead/verifier 统一调度。无真实资源则明确全量比较未验证，不假测。

**选择理由**：直接覆盖用户可观察结果及禁用边界，保留底层与集成的区别；测量固定启动 t0/业务 ready、主进程 RSS 30s 窗口、递归子进程、缓存分组、清理记录。

**未选原因**
- 候选 2：替身有可能未经过正式工厂/validator，不能证明 A5 和无隐藏重资源，也不能证明 UI 可操作。
- 候选 3：静态估计不是实测，全量 CI 不能代替控制台/真实资源验证；重复并发全量还会污染资源比较。

**验证方式**：本轮仅 V0 文档结构/链接/差异与示例校验，A1–A6 保持未执行。实现后按同一环境、同一角色/模型/数据基线对照全部原始测量值，不遗漏失败轮次。远端 CI、真实供应商/设备的未测边界逐项披露。

**风险与回滚**：没有全量资源或环境无法一致就不宣称比较完成；不下载模型/安装 pip 来造证据，不改现用 secrets。检查失败先修复文档或实现，不通过降低原预期获得绿灯。

## 2026-11-17 D3 N1：混合 citywalk 选择明确的装配级执行跳过

**待定问题**：只关向量而保持 citywalk 请求开启时，既有直接向量写消费者如何准确降级，且不违反“不改 world 任务内部”？

**背景约束**：D3 attempt 1 仅要求补齐该组合，不要求新增“无向量 citywalk 仍完整成功”能力。已接受的 G1 只覆盖组合根；低层拒绝写入、无假 ID/count 仍保持。用户逐项选择不能被偷偷改成 citywalk=false，也不应把可选任务依赖关闭传播成整个聊天服务启动失败。

**调研参考**：本轮不扩展外部研究，只核对真实调用：[Task 构建服务](<server/src/world/citywalk/task.py#L233-L248>)、[service 先落报告后 ingest](<server/src/world/citywalk/runtime_scheduler.py#L19-L36>)、[ingestor add 后返回 len(docs)](<server/src/world/citywalk/memory_ingestor.py#L93-L118>)。它们没有可注入的投影 Interface。已有 [Task service=None 早返回](<server/src/world/citywalk/task.py#L105-L108>) 可由 [WorldRuntime 依赖派发](<server/src/world/world_runtime.py#L111-L117>) 选择，不必改任务内部方法；实际可实施性仍须 attempt 2 核对。

**候选方案**
1. **M1-S：组合根明确执行跳过**：vector=false 时 WorldRuntime 在依赖派发后/注册前给城市任务选择既有 citywalk_service=None 状态；保留 requested enabled、定时注册与周期，validator warning 解释“依赖关闭导致整项执行跳过”。任务触发返回原 unavailable skipped result，不进入 service.run_once，不生成报告/SQL travel/观察事实。
2. **只披露低层拒绝造成部分副作用**：不增加装配选择，允许 report 已落盘后因 add 拒绝失败，记录未提交 SQL/观察；整个聊天仍正常。这是报告推荐的最窄可接受下限，但对操作者的部分产物更易造成误解。
3. **保留完整 report/SQL，仅跳过投影**：改 scheduler/ingestor 的 capability/注入接缝，使返回 path 后继续 SQL/观察；或把低层 add 变 no-op/返回假 ID。
4. **拒绝该混合配置/自动设置 citywalk=false**：配置易诊断或容易实现，但前者阻断整个服务、后者改变用户显式逐项选择。

**选择**：推荐候选 1 送 D3 attempt 2；不是已经获准的新完整规格，也不是实现许可。保持 AMAP 按 citywalk 请求 true 的已审条件必需；warning 名为 citywalk.vector_projection 且 status=warning，不触发自动 world disablement。

**选择理由**：只在既有组合根选择不可用依赖，沿 Task 已有语义得到诚实 skipped，不造成功产物，不改任务算法/触发规则；在执行任何报告副作用前明确阻止，保留配置意图和聊天可用。重启重新启用向量可恢复原服务，不需新全局开关或重构。

**未选原因**
- 候选 2：可如实披露且不超 scope，但留下“有报告无 SQL/观察”的中间结果；依赖可用性接缝足以在执行前跳过时，不优先采用半途失败。
- 候选 3：完整保留能力需要 world 内部工作流改动，超出已接受排除；低层 no-op 又会让 ingestor 误报 len(docs)，与无假计数不变量冲突。不得借 G1 接受扩大范围。
- 候选 4：阻断启动不利于 A3，自动关配置违背逐项选择；推荐明确 requested=true / execution skipped，不把两者混为 disabled=false。

**验证方式**：真实 WorldRuntime mixed 配置下，warning 可见且配置仍 true、任务仍注册；触发原 Task 返回 ok=true/skipped=true/message=citywalk service is unavailable/data={}；service.run_once、ingestor、vector add 均不执行，无报告/SQL travel/观察事实；聊天照常且无向量资源。true/true 复核原 citywalk 链路；不用替换 Task.run_once 的自定返回值自证。

**风险与回滚**：该混合组合牺牲整个城市漫步执行而非仅索引，是必须在 README/validation 明示的能力限制，等待非作者接受。若装配接缝不能安全完成，不转为内部改动；退回已披露的候选 2 另行审定。恢复向量并重启回原状态，不补跑/清数据。

## 2026-11-17 D3 N2：固定生成器与自由模型采用不同正文判据

**待定问题**：A5 精确“核心链路412”是否错误要求真实模型逐字服从？

**背景约束**：工单要的是注册→登录→WS 文字→历史闭环，而非约束任意供应商模型的措辞。离线仍必须走真实配置、装配、网络转换、SQL 与关闭，只替换生成器，不替换整个投递链。实际模型联调和实际资源证据不能被取消。

**调研参考**：D3 attempt 1 N2 及工单 A5；不需要新研究、提示词重构或把字面文案变成人类必答问题。

**候选方案**
1. **分层断言**：离线固定生成器确切输出核心链路412，WS/历史逐字对应；真实模型保留同示例输入，要求非空实际正文、成功终态、无音频、后续继续、历史正确保存实际输入/回复及无 world 定时执行。
2. **所有场景硬断言精确文本**：把提示词服从当开关验收，必要时硬编码或强改 prompt。
3. **只保留固定生成器**：避免不确定性，但放弃真实联调证据。

**选择**：候选 1，已同步 A5、README 操作例与 V3；等待 attempt 2 对本版修订确认。

**选择理由**：离线确定性可归因，真实模型按本功能可观察结果验收；历史与 WS 实际正文对应比固定自由措辞更能证明链路正确。

**未选原因**
- 候选 2：把模型自由生成差异错误归为 #412 失败，硬编码/改 prompt 又污染范围。
- 候选 3：违反既定真实证据分层，不能因离线全绿宣称全部真实验证完成。

**验证方式**：离线精确文本与实际模型实际正文分开记录，均校验 terminal/history/后续消息/零 world timer；本轮只做文档静态核对，未执行这两路验收。

**风险与回滚**：真实模型失败、无正文、失败终态或历史丢失依旧是需诊断的真实结果，不以自由生成放宽这些标准。无需变更运行代码/配置来修正文本判据。
