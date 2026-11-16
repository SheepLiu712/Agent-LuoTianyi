# AI 决策记录

## 2026-11-17 #441 opening 测试就绪契约复用（task13顺序补记）

**待定问题**：本分支未包含独立#410的测试helper修复，真实远端lookup失败场景在opening创建时固定1秒等待超时；怎样补对本树测试契约而不混入通话预算生产功能？

**背景约束**：task13只允许测试helper和新增readiness测试两个文件，不并写AI；该单元经Oracle implementation1/3与lead授权提交 `3805e0cb18e60454adf2579fe7b48c1ccc57e4c7`（parent5ee）。本条由startup-spec在task12提交3924并明确释放AI后，按lead要求依据外部47行task13报告顺序记录，不重跑其测试。

**调研参考**：复用已审 `31ff341f81d6a9b38828e2cdc3cde4657112e1e7` 的两文件测试契约，未merge/cherry-pick其生产改动。旧helper与ee同blob7a9259…；当前factory/Agent/四元组签名不改。最终helper blob `51a23805a1e4e43f6d7cbd4939eab04992ce13d8`、新测试blob `69a31421b02e84ca9def450710078dc3b3aee1f8` 与来源对象相等。

**候选方案**
1. **具名opening就绪接缝及失败清理**：捕获当次真实_realize_task并shield等待，检查ACTIVE/非终止/socket确有response.create；创建失败真实terminate并保留原异常。
2. **抬固定1秒或删除发送检查**：只能掩盖调度差异，不能保证实际opening已发。
3. **跨分支合生产改动或假成功factory**：扩大工单范围，并绕掉本树真实接口验证。

**选择/理由**：候选1，在本树旧接口上复用已审深度最小的测试同步契约。受控SQL ACTIVE提交返回门同时验证等待与失败分支，不用sleep当就绪条件。

**未选原因**：候选2无可靠阶段证据；候选3越过test-only范围，无法独立归因与回滚。

**验证方式与实际证据**：task13在本树原helper上新增2场景，真实红为 `2 failed,1warning in3.48s`（job pwsh-3c4968f8bcc84295，两个TimeoutError）；修后同新2+旧call_omni24一次 `26passed,1warning in6.30s`（job pwsh-dadbc87f8f334e92），外壳10.047/11.875秒均在20/40秒上限内。成功opening恰1次；失败保原OSError同对象、socket关闭/tasks空；finally放门/清理。定向静态通过，旧helper原I001未扩大格式化；pydub路径告警保留，不冒媒体依赖齐备。本条只转录已落原证据，不是新增运行PASS或原远端精确根因重建。

**风险与回滚**：只证明测试同步/清理契约，不改变生产预算；回滚该自然提交不删除数据。不据26通过宣整个PR/远端已绿，后续Secrets/preclaim收齐后由verifier在最终HEAD统一门禁。

## 2026-11-17 #441 Secrets 夹具补齐真实校验器能力

**待定问题**：3A状态接口共用必需密钥策略后，旧测试shell没有validator，真实远端更新Secrets失败；应改生产还是补齐测试夹具？

**背景约束**：真实AdminShell dataclass声明validator，initialize实际构造RuntimeConfigValidator并共享给Supervisor；旧测试与ee同blob但partial SimpleNamespace只提供SecretStore/read_raw/is_running。task7rev10仅原http_secret_security测试与本AI两路径；等task12提交 `3924ca6df0ef2117c5f2258d9f03e8ee66f93774` 并明确释放后才实施，不并写AI。不改production/超时/通话helper/UI/CI，不扩鉴权或实际重启平台。

**调研参考**：已读AdminShell、SecretStore、ConfigStore和RuntimeConfigValidator.required_secret_keys的现有契约；无需新框架或外部研究。更新Secrets返回secrets_status，因此需要同一真实校验规则：JWT始终required，顶层citywalk=false时AMAP非required。

**候选方案**
1. **修旧夹具为真实Store/Validator**：真实临时ConfigStore与SecretStore，validator引用同一SecretStore，citywalk false/true两代表，保原changed_keys/restart_required并核条件状态。
2. **生产status直接调用策略staticmethod**：可减少shell实例依赖，但真实AdminShell本来已有validator，为兼容失真fake改生产无必要。
3. **getattr/hardcode或lambda假validator兜底**：容易复制策略并掩盖真实协议缺失，不能验证实际配置/密钥状态。

**选择/理由**：候选1。测试以monkeypatch先登记JWT_SECRET/AMAP_KEY/RUNTIME_SECRET_TEST三个合成环境值，SecretStore之后即使覆盖也能恢复原环境；AMAP测试值保留在store，false场景直接断言required=False而非缺key。Supervisor仅is_running提示端口，不能称真实owner重启；密钥均临时合成不输出/不归档值。

**未选原因**：候选2扩大生产范围且无真实owner缺陷；候选3会为测试绿灯降低真实状态保证。

**验证方式与实际证据**：原节点先在本树V2运行，job `pwsh-4b80f9e31d584e3d` 原 `1failed,1warning in3.25s`，准确update_secrets→secrets_status L254 `AttributeError: SimpleNamespace has no attribute validator`，不是导入/前置错误。补真实夹具及两代表后，原文件+已有citywalk免AMAP不免JWT/Secrets.required两邻近节点，job `pwsh-56dafb7d9f6f4438` 为 **13passed,1warning in1.83s**，Ruff/Black该测试全通过/无需格式变动。警告为既有zhconv/pkg_resources弃用，不称零告警。未重95/17/0.15敏感计时或全CI。

```text
python -B -X utf8 -m pytest tests/integration/system/test_http_secret_security.py tests/integration/system/test_admin_runtime.py::test_citywalk_disabled_does_not_require_amap_but_jwt_stays_required tests/integration/system/test_admin_runtime.py::test_secrets_required_status_matches_citywalk_condition -q --tb=short -p no:cacheprovider
```

**风险与回滚**：本单元只修测试依赖契约与环境隔离；原远端失败历史不抹，不据13通过称整个PR已验。回滚后续自然test-only提交即可，不改用户配置/SecretStore或生产行为。两路径冻结交独立gate，未获明确许可不commit/push/GH/ready/closegoal；多个自然修复及preclaim收齐后，最终固定HEAD只由verifier统一执行原七作业，不每个小commit重复全量。

## 2026-11-17 #441 embedding 超时测试的阶段契约

**待定问题**：原633远端单元测试在真实连接EOF0后断言connected=false；该事件实际仅在完整HTTP header到达后置位，混淆了TCP接受和响应停滞。测试/实现与ee基线同blob并不豁免失败，外部真实双分支只证合法早取消同症状可达，不是远端exact cause。

**背景约束**：lead task12及Oracle设计许可只改本测试文件与本记录，实施树issue-412/5ee；保同步embed_query真实wall-clock请求0.15秒、总2秒、清理1秒、单次尝试。严格响应stall必须仍有真实header和真实socket关闭证据，不生产改动、不抬等待、不加依赖或通用时钟框架，AI由本单元独占。

**调研参考**：[HTTPX0.28.1 trace扩展](https://github.com/encode/httpx/blob/0.28.1/docs/advanced/extensions.md)支持异步连接/发送/响应阶段观察；只用事件名，不记录info/headers/body/密钥。[Python3.10事件循环](https://docs.python.org/3.10/library/asyncio-eventloop.html#asyncio.loop.call_later)允许计时回调提前一个时钟分辨率，[wait_for](https://docs.python.org/3.10/library/asyncio-task.html#asyncio.wait_for)超时取消且等待实际清理。项目已有局部loop.time受控验证；这里只覆盖新建客户端loop实例，pytest/server loop和全局monotonic不变。

**候选方案与选择**：选择两个互补场景：原同步真实时钟入口按accepted/header/EOF/closed分类，且只认TimeoutError、attempts1；另在专用新线程/loop从请求前原点冻结time，真实header及receive_response_headers阶段后推进未到期点，再跨原0.15期限，验证原wait_for取消和真实EOF。单独放宽header断言会失去响应stall覆盖；只抬超时或去掉断言仍没有阶段保证，均不选。无需新公共helper或生产API。

**验证方式**：先在原测试注入send_headers.started事件门，job pwsh-90eda9dfe8424940有效red为1failed/7deselected/0.88秒，精确header事件false与EOF0。阶段分类两分支2passed/0.47秒。严格clock初版及0.149负对照都通过，后者暴露安全网不足，不能计为有效边界证据：本机loop分辨率0.015625秒，0.149与0.14距0.15均不足一个分辨率。按官方容忍取前点0.15-2*resolution（本机0.11875），原timer观察为0.15/2.0；不跨期负对照job pwsh-01acc6d3af094a8d为1failed/8deselected/1.70秒，精确stopped仍false。恢复跨点0.16，原异常发生时虚时必须0.16并在finally恢复真实time前记录；最终本文件job pwsh-143e9e8af51d4668为9passed/0.62秒，Ruff通过。此后仅按Black整理新增部分，不重测或夹旧响应字典格式清理；静态/冻结细节另列实施归档。未重17/95或全CI，旧633失败和新5ee集成失败仍保留。

**同attempt1收尾修正**：Oracle发现真实看门超时后finally无界gather会抵消watchdog，原匿名gate也不能由owner解除。新增唯一坏路径吞计时取消直到可释放网络门，外部父5秒取得gateentered后hang红（job pwsh-0b4e1f0b0d3b4e8e，tree-kill0/reapedtrue，含启动总11.57秒，非产品失败）。最窄改为只在worker仍未结束的异常看门路径线程安全放门/取消实际client POST task、先关自有server/writers，再真实有限等待worker；invoke的finally标记与Task已done共同证明同步调用及其asyncio.run已退出，不取消to_thread包装冒充join。正常产品Timeout分支不主动close，仍须自行EOF。修后job pwsh-12406541a72344e0：坏节点1passed/0.56秒，本文件10passed/1.09秒，父分别7.2113/6.250039秒均有界且reaped；仅此网络门回归可解除，不宣称可强杀任意恶意Python无限线程。随后只有新增格式静态/指纹更新，不再业务测试。

**风险与回滚**：局部loop时钟只服务该严格测试，原点不在header后重置；pytest/server真实watchdog不虚时，finally恢复实例方法、关闭async client/server/writer、收齐handler与线程。前界须远于平台clock_resolution，不能声称毫秒级精度。真实worker若在有限等待内仍未退出必须明确失败，不能宣清理成功；任意不可协作线程不在此测试保证。回退本测试单元不改变产品行为；若计时器或trace依赖版本改变，测试应明确失败，不用扩大产品预算或soft-pass掩盖。

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

## 2026-11-17 Phase412-1：在既有语音 Skill 内显式禁用，普通 SAY 正常完成

**待定问题**：按已审完整规格实施第一自然阶段，怎样证明 false 真正不创建 TTS 资源，而不是只返回空流或绕过生产选择接缝？

**背景约束**：规格提交 `b50ab5309b3c0a5ec99d7d5fbc856c85d30bdb29`，D3 attempt 2 已通过；lead 将 task-7 CAS 至 revision 3，仅授权配置/TTS/合法文字、相应测试与模板。向量、world、AMAP 条件重构、DTO/UI/README 及完整 A1–A6 闭环属后续阶段；Oracle 实现 gate 前不提交本阶段。不改现用配置、密钥或依赖环境。

**调研参考**：沿规格已核实的 FastAPI 官方资源生命周期原则与本项目 SpeakingSkill/SpeechBackend/SharedSkills/SayHandler Interface，不再扩展技术研究。预期来源为 [已审规格 A2/输出契约](<docs/specs/component-startup-switches.md#L209-L226>)，而不是从测试替身返回值推断。

**候选方案**
1. **既有 Skill 显式禁用状态**：严格解析默认 true 的 bool；false 时不创建 SpeechBackend/AsyncTTS，公开只读 enabled、Call false、幂等 stop/abort，直接 speak 抛 SpeakingDisabledError；普通非 CALL SAY 在 prepared/TTS 分流前输出正文/表情和唯一成功终态。
2. **新建平行 DisabledSpeaking 类并改所有装配调用者**：可行，但当前 Skill 已拥有资源与生命周期，额外层对本阶段没有更多行为收益。
3. **None/空流/吞错误降级**：少改构造，但会走 EmptySpeechError/失败终态，或丢 prepared 限制，不能证明不持有资源。

**选择**：候选 1。SharedSkills 的现有 `SpeakingSkill(config.get("speaking"))` 已是完整选择接缝，保持该文件零差异；不为显示“有装配变更”而添加无用工厂。SAY 读取 enabled 时为既有测试/预制调用的无能力属性替身保留默认 true，仅显式 false 进入新分支；真实 Skill 始终提供严格 bool。CALL 在已有许可校验后返回 DEPENDENCY_UNAVAILABLE，不走文字成功回退；Sing 未修改。

**选择理由**：最小实现集中拥有资源的 owner，无新全局框架。启用分支的 TTS、预制音频、取消、故障、输出回执规则均不改；禁用 speak 在计量/供应商工作前明确拒绝。validator 只对 false 跳过 TTS 专属资源，缺省/true 仍按原必需；模板只增加 true 新叶。

**未选原因**
- 候选 2：会扩大 facade/类型/测试面，两个行为分支在同一资源 owner 内即可清楚表达；本阶段无需新层。
- 候选 3：空流是音频故障，不满足合法纯文字成功；prepared 还有独立读取分支，不能只关合成；吞 sink 失败又会虚报交付。

**验证方式与本轮实际证据**：使用已安装 Python `3.10.21`，pytest 默认不跑外部/真实模型。

- 首条红灯：新增 `test_disabled_speaking_creates_no_backend_and_closes_idempotently`，真实构造 false 仍调用 SpeechBackend，触发禁止资源构造陷阱，`1 failed in 0.66s`；最小改动后 `1 passed in 0.10s`。
- 直接 speak 红灯为 `_tts=None` 后 AttributeError，`1 failed in 0.66s`；明确禁用异常后两条语音资源/直接拒绝用例 `2 passed in 0.08s`。最终还覆盖默认注入 engine 保持启用、false 不使用注入 engine、非法值矩阵。
- SkillsConfig 公开解析对六类非 bool 原先均未抛出，`6 failed in 0.63s`；严格校验后，含真实 SharedSkills/AgentMemory/MemoryStore 装配共 `7 passed in 0.07s`。装配测试只给模型注册端口和现有向量依赖，不替换技能类或 speaking 选择；它证明共享技能子系统选择，不冒称完整 ServerRuntime 启动。
- 普通 SAY 经真实 Agent 与公开 Adapter `open/next_output/complete_output`，初始得到 AUDIO_GENERATION_FAILED，`1 failed in 1.53s`；prepared/瞬时反应原先仍触读取陷阱、未交付终态，`2 failed in 5.28s`。修复后该三场景 `3 passed in 0.57s`，后续补上纯文字无 sound_content、Call（含 prepared）拒绝、sink 失败不伪发成功、消息身份/序号/唯一终态。
- validator false 无 TTS 配置原为 `core_ok=false`，`1 failed in 2.89s`；条件化后纳入定向绿灯。补 false 留有失效路径也不检查、非法 bool 仍阻断、true/省略仍要求资源。
- 中间一次新增 ChatEndpoint 忘记 `connection_generation`，导致 `3 failed,180 passed in 7.75s`；这是新增测试端口缺字段，不是产品红灯/平台差异。补齐真实 Adapter 所需端口后相同 12 文件回归 `183 passed in 5.84s`；再补无音源 SAY 用例后 `184 passed in 5.53s`。最终冻结回归结果在交 lead 的阶段报告中列出，不能把这些中间数字当全量验收。
- 最终候选执行上述 12 文件：`185 passed, 2 warnings in 5.76s`（job `pwsh-935d3a94355e4e73`，exit 0）。小范围 Ruff `0.14.10` / Black `26.5.1` 对五份改动生产源码通过；对两新增测试及 Call 追加测试也通过。旧测试文件原有格式未顺手全格式化。所有新增文件仍按最终状态检查差异空白/路径白名单。

当前重复回归命令（cwd 为 `server/`，`python` 指已安装的 agent 环境）：

```text
python -B -m pytest tests/unit/agent/test_speaking.py tests/unit/agent/test_speaking_module_ownership.py tests/unit/agent/test_call_say_permit.py tests/unit/agent/test_call_say_output_metadata.py tests/unit/agent/test_tts_cancellation_boundary.py tests/unit/test_call_transport_capability.py tests/unit/web/test_call_capability.py tests/integration/runtime/test_component_speaking_startup.py tests/integration/websocket/test_disabled_speaking.py tests/integration/websocket/test_websocket_adapter.py tests/integration/system/test_admin_runtime.py tests/integration/agent/test_skill_configuration.py -q -p no:cacheprovider
```

**风险与回滚**：最初 PATH 找不到 ffmpeg，测试有 pydub warning；ci-verifier 实际确认 agent 环境 `Library/bin` 的 ffmpeg/ffprobe `8.1.2`，仅测试子进程临时前置该目录，后续无 ffmpeg warning，未安装或修改全局 PATH。剩余 Starlette BlockingPortal 与 zhconv/pkg_resources 弃用警告如实保留。未运行全量 CI、真实 TTS 权重、完整账号/HTTP/WS/SQL 闭环、浏览器、真实模型或资源对比；Phase412-1 局部绿灯不等于 A1–A6 通过。要恢复语音需操作者准备原资源、设 true 并重启；不用删除用户数据。当前阶段实现未提交，等待 lead/Oracle gate。

## 2026-11-17 Phase412-2：禁用向量保留真实 SQL 正本，不伪造投影

**待定问题**：按照已审 §3.5，在向量资源完全不启动时，怎样保持显式写入、维护、授权召回与旧入口的真实持久化/失败语义？

**背景约束**：Phase412-1 已在 Oracle implementation attempt 1/3 PASS 后由 lead 授权原子提交 `42ce9e9843bf62b1af022d53c4d950c61be6b6c8`，工作树干净且未推送。lead 将 task-7 CAS 至 revision 4 授权本阶段 exact19路径；只做向量/SQL-only，不能修改 MemoryStore/schema、world/M1-S、AMAP、DTO/UI/README 或自动回填。Phase2 gate 前不提交推送；阶段绿灯不是 A1–A6 全交付。

**调研参考**：沿用 [已审 §3.5](<docs/specs/component-startup-switches.md#L228-L295>) 与既有正本/向量 Interface；call-repair 提供独立只读五项安全输入，指出 legacy 补偿、无条件 True、maintenance_id 跨角色碰撞与 reset 隐私边界。本轮不重新研究/扩架构，不把辅助提示当实际测试或 gate。

**候选方案**
1. **非空 DisabledVectorStore + 正本成功后跳投影**：真实工厂在 Chroma/embedding/线程池/目录之前选择禁用实现；低层读空、误写/嵌入明确拒绝，正本/维护写入口依明确能力事实绕过投影与 link；保留原受信身份/冻结/SQL幂等和错误传播。
2. **Null 实现返回输入 ID 或空向量，再照旧链接/补偿**：caller 少改，但不存在的索引会被写入关联，或 legacy 无 ID 补偿反而删除正本。
3. **统一移除向量、重写事务/旧记忆体系或自动补索引**：能统一接口，却扩大到 schema/存储 owner、数据迁移与新平台，超出本阶段及工单。

**选择**：候选1。复用 `init_vector_store`/工厂与 AgentRuntime 原装配；AgentRuntime、CognitiveMaintenanceSkill 保持零差异。Base VectorStore 的只读 enabled 默认 true，禁用实现 false；缺省/true 仍原 Chroma，不把真实故障转 disabled。MemoryWriteResult 仅新增默认 true 的 `retrieval_enabled` 事实供确认材料，不造通用状态平台。

**选择理由**：原 SQL 是正本，向量为可选召回投影；if_absent 的真实身份/内容冲突检查已足够，不改 MemoryStore。维护 CANONICAL_ONLY 是正本已可靠保存而没有投影，不混同 SKIPPED_EMBEDDING；原维护 owner 在所有写成功后才提交画像/摘要/进度，真实 SQL 错误/取消/冲突继续向上。

**未选原因**
- 候选2：假 ID、假计数会破坏正本→真实向量不变量；返回空值会令旧补偿链当损坏并删除合法 SQL-only 正本。直接查询也不能先触 embedding 再故障降级。
- 候选3：不需要新增事务/迁移/删除队列就能达成已审契约；新平台扩大回滚/授权风险，也违反无自动回填与当前19路径限制。

**受限旧入口 commit=False 裁定**：lead 已明确要求“本次不提交则不得声称已保存”，不改变 enabled 原行为。disabled 的 `commit_user_memory` 若没有已持久同身份正本，返回 `("",False)` 且不写正本/update/link；已存在则严格核 owner/user/type/visibility/source/content 后返回真实旧 ID+False，冲突拒绝。disabled 两个 bool 入口同样不写且返回 False；False 是“本次未保存”，不是正常保存成功。三个入口的 commit=True 都走真实严格 if_absent，跨入口用户事实使用原稳定 ID、同日事件使用 owner/user/date/规范文本确定 ID，不伪造向量标识。风险是旧 caller 不能再把 disabled+commit=False 当已持久化承诺；主 `commit_fact` 始终真提交，不受这条旧接口限制影响。

**已实施的最小契约**：

- 真实工厂 strict bool，false 不建目录、Chroma、embedding 或专用池；低层 search/get_by_id 空，add/upsert/update/prepare/embed 明确 VectorStoreDisabledError，close 幂等。strict delete 对不存在/已确认空路径才0，非空/文件/符号链接/不可判断均 VectorDeletionUnavailable，不开旧Chroma、不删数据。reset沿既有部分成功/HTTP500/fence释放，不新增错误协议。
- 显式/事件写保持稳定来源身份、冻结候选复用、真实 SQL ID与 CREATED/DUPLICATE/NO_CANDIDATE；disabled跳upsert/link而非假返回。用户确认只在实际正本成功后，材料明确“已保存正文；长期检索关闭，恢复时不自动建索引”，不强制模型逐字措辞。
- 维护 disabled 非空候选全部 SQL 成功后 CANONICAL_ONLY/日志 index=disabled；无 embedding/link，memory_skipped_count=0。维护批次ID算法不改；同 maintenance_id/index 的敌对跨角色或跨用户碰撞由既有 if_absent 拒绝，不吞成重复或覆盖。真实部分 SQL失败/取消/冲突不推进画像/摘要/进度，允许原 owned-operation 已完成的部分正本留待同批重试。
- MemoryRetrievalSkill 先校 USER身份/角色/MemoryQuery，再屏蔽 USER/CHARACTER含 YesterdayCityWalk；公共歌曲 SQL/目录不变。AgentMemory一般话题召回也提前空，避免直接调用先 embed。重新创建真实启用Chroma不自动将 SQL-only 记录补入；既有索引和数据不删除。

**红→绿与实际证据**（agent Python `3.10.21`，Ruff `0.14.10`、Black `26.5.1`，cwd `server/`）：

| 垂直片 | 原始红灯 | 修复后已执行证据 |
| --- | --- | --- |
| 公开 init_vector_store 资源构造 | `pwsh-691dcbf5265940b1`：false 仍走真实 Chroma 构造并触 ThreadPoolExecutor 陷阱，`1 failed in 1.42s` | 同条 `pwsh-12d9ac6784ea4521`：`1 passed in 0.07s`；strictbool/误写拒绝/strictdelete矩阵随后 `12 passed in 0.10s`。未替换工厂/ChromaVectorStore自证。 |
| 显式 SQL-only | `pwsh-86f642289ff04e0b`：正本后仍 upsert，VectorStoreDisabledError，`1 failed in 1.51s` | 三个C/U组合/异内容冲突/无关联/SQL失败与维护首批及旧enabled记忆回归 `16 passed in 3.84s`。 |
| 维护候选 | `pwsh-8fe00488508649b3`：仍 prepare_embeddings，`1 failed in 0.92s` | CANONICAL_ONLY、同批重试、敌对跨C/U冲突、真实维护成功/第二SQL失败/取消/冲突不越进度均进入最终集合；enabled embedding outage保持原skip。 |
| 授权召回 | `pwsh-83c292bb63b040f9`：仍先 embed_query，`1 failed in 2.88s` | 私有/角色/Yesterday空、身份错误仍拒绝、公共歌曲真实SQL，`2 passed in 0.54s`及最终集合。 |
| legacy intentional/bool | `pwsh-deb843fa8d044def`：add触禁用拒绝，`1 failed in 0.95s`；`pwsh-6f99db71487848f9`：bool两入口 `2 failed,1 passed in 1.60s` | 窄 disabled 正本分支+原enabled投影补偿基线 `8 passed in 0.78s`；commitFalse无写/已存仍在/冲突与SQL异常后续加入。 |
| 确认材料 | `pwsh-d5d89fa8a1524ab3`：没有“已保存正文/长期检索关闭”材料，`1 failed in 0.72s` | 真实Handler编排+相关记忆用例 `24 passed in 3.85s`。 |
| validator strictbool | `pwsh-97c63735866b45a1`：六非法值 core_ok仍true，`6 failed in 3.24s` | strictbool/disabled状态报告与AgentRuntime真实工厂装配加入最终集合。 |

**非产品失败如实排除**：新 AgentRuntime 测试首次提供 media_resolver=None 后调用 ensure_dependencies，导致夹具缺依赖（`1 failed,6 passed in 19.48s`）；补非空媒体端口后误断言 Agent 公开 character_id（实际无此属性），`1 failed,1 passed in 1.82s`。均仅修测试，不能算产品红灯/平台差异。旧enabled真实Chroma回归使用临时库并替换 embedding HTTP方法，不表示使用真实供应商；未删/跳该基线。

**最终阶段验证**：`pwsh-b50507fbcb0e4f21` 执行下列精确相关集合，`163 passed, 3 warnings in 14.28s`，exit0。其中warning为 zhconv/pkg_resources 与两处 Chroma embedding get_config弃用；未称零告警。十份生产改动 Ruff/Black通过，三新增测试 Ruff/Black通过；受影响旧测试只追加，不全格式化。源码最终版本与新增文件全部进入外部冻结manifest；本阶段不重跑Phase1的185或全量CI。

```text
python -B -m pytest tests/unit/infrastructure/test_disabled_vector_store.py tests/integration/persistence/test_disabled_vector_memory.py tests/integration/runtime/test_component_vector_startup.py tests/unit/agent/test_intentional_memory.py tests/unit/agent/test_maintenance_memory_writer.py tests/integration/persistence/test_memory_write_skill.py tests/integration/persistence/test_intentional_memory_storage.py tests/integration/persistence/test_memory_retrieval_skill.py tests/integration/persistence/test_maintenance_memory_projection.py tests/integration/agent/test_topic_reply_pipeline.py tests/integration/system/test_admin_runtime.py tests/unit/agent/test_cognitive_maintenance.py::test_embedding_outage_skips_memory_but_commits_profile_summary_and_progress tests/unit/agent/test_cognitive_maintenance.py::test_cas_conflict_does_not_compact_or_overwrite_progress tests/unit/agent/test_cognitive_maintenance.py::test_cancellation_before_progress_does_not_advance_marker tests/integration/agent/test_call_threshold_maintenance.py::test_call_embedding_outage_keeps_threshold_summary_profile_and_ending_progress -q -p no:cacheprovider
```

**风险与回滚**：无自动回填，SQL-only 记录重新启用也不保证可长期召回；旧非空/未知索引reset会明确部分失败，不代表事务回滚。恢复向量需操作者准备原资源并设true重启，不删SQL/目录。Phase3 M1-S城市漫步依赖降级尚未实施，本阶段不得宣称 vector=false/citywalk=true 已安全完成；AMAP core必需、world、UI与真实闭环/真实模型/真实full-min资源对比仍待后续，不预判资产缺失，也不以静态估值或fakebenchmark交付。本阶段未提交推送，等lead/Oracle实现gate。

## 2026-11-17 Phase3A：world 组合根门控与条件依赖同步

**待定问题**：怎样在不改任务内部算法/周期的范围内，让全部 world 定时任务真正不构造/不注册，并诚实处理 citywalk 请求开启但向量关闭的混合组合？

**背景约束**：Phase2 在163定向+Oracle implementation1/3 PASS后由lead许可原子提交 `6c3f5e7d7c7419535c375fe556dad566b57b017e`，未推送；task-7 revision5批准本单元exact8路径。3B DTO、3C UI/README、3D实际隔离闭环、真实模型/资源比较另行分阶段，不能在此顺带实现。用户现用config/密钥不改，不新preset/env；非作者D3 attempt2已接受G1/M1-S，不重开产品取舍。

**调研参考**：沿既有 WorldRuntime 构造→initialize→注册与 CitywalkTask 的公开可空 citywalk_service/早返回接缝；validator 与 Secrets管理原接口。设计依据是[已审world/M1-S契约](<docs/specs/component-startup-switches.md#L181-L208>)与[混合组合](<docs/specs/component-startup-switches.md#L281-L295>)。独立phase3只读准备报告只作定位，不是运行证据；本轮不新增研究。

**候选方案**
1. **既有组合根补三门控、合法空集合与依赖选择**：三项默认true；任务基础初始化后/注册前，向量false使已请求citywalk的optional service=None，保留原请求开关/定时名称/周期，触发真实skipped。AMAP条件与Secrets共用同一规则，显式disabled凭据不检查。
2. **改任务内部/调整周期或非法type冒充关闭**：能少改某些构造，但不满足无任务/零执行或超出内部流程排除。
3. **自动关citywalk或混合组合阻断整个服务**：表面避免写向量，却改变逐项请求或让可选依赖导致聊天起不来。

**选择**：候选1。World目录生产差异仅WorldRuntime；不编辑Task/RuntimeService/Ingestor/WorldClock。三门控外只移除“已完成初始化但tasks空仍拒绝”的检查。保留一次性ensure_holidays，零world定时动作不冒称全进程零后台。

**选择理由**：已有owner与Seam足够，不需重构注册系统。M1-S在任何任务执行前完成，既有Task.run_once自然返回 `ok=true,skipped=true,message=citywalk service is unavailable,data={}`；无report/SQL travel/观察/向量成功计数。重新构造向量true实例恢复原service，不补跑/删数据。

**未选原因**
- 候选2：延迟不是disable，0频率非法，改任务内部则违排除；不能用猴补丁生产Task或假vector消除错误。
- 候选3：raw requested=true不代表依赖一定ready，但不可悄悄持久化false；warning必须非disabled并保留apply_world_disablements现有规则，不因向量关闭丧失整个聊天可用。

**条件校验**：九任务顶层enabled严格bool，代表非法值与角色覆盖校验不truthiness；缺省true。`required_secret_keys(config)`由validator对外提供，JWT始终必需，仅顶层citywalk=false解除AMAP，角色true不能反开顶层false；mixed citywalk=true/vector=false仍AMAP必需。Secrets.status使用同一规则，不读/写真实值。显式关闭B站/自动学歌不检查其credential路径；mixed增加world citywalk.vector_projection warning，不走自动关。模板补齐缺少的七个true叶，已有auto_song_learner/qq_refresh true保留，其他配置不改。

**实际红→绿**（agent Python3.10.21，Ruff0.14.10/Black26.5.1）：

| 断言与来源 | 红灯 | 绿灯/覆盖 |
| --- | --- | --- |
| 已审A5改变旧三无条件任务错误预期 | `pwsh-66cddd390c3342ae`：disabled仍注册三项，`1 failed,1 warning in1.51s` | 三构造门控后同条 `pwsh-b99faf22db2240a6`：`1 passed,1 warning in0.77s`。不是为了绿灯降旧保证，而是已审契约改变条件行为。 |
| 真实九项构造trap+原Clock全空 | `pwsh-eb336ec89ebd49fb`：所有Task未构造但tasks=[]被ensure拒绝，`1 failed,1 warning in1.08s` | 合法空集合后 `pwsh-43d432fad47d45ea`：`1 passed,1 warning in0.51s`；一次holiday工作仍启动/清理，原Clock注册表与运行任务都0。 |
| 真实M1-S初始化与执行入口 | `pwsh-a252ebc6c87f4210`：原城市服务仍存在，`1 failed,1 warning in1.31s` | 根依赖选择后两个真实world场景 `pwsh-20029638bc924423`：`2 passed,1 warning in0.82s`；Task.initialize/run_once未替换，SQLite event无写、无观察，服务执行设trap不触发，恢复true service可重建/周期不变。 |
| AMAP条件 | `pwsh-cec97631e8954522`：citywalk=false缺key仍core阻断，`1 failed,1 warning in2.36s` | shared条件后JWT保留、顶层false压角色true，mixedtrue仍AMAP必需。 |
| Secrets.required一致性 | `pwsh-f6aa6d9f3f5a46e9`：AMAP仍required，`1 failed,1 passed,1 warning in2.63s` | 管理页投影使用validator同一条件，不维护第二份hardcode列表。 |
| world strictbool代表 | `pwsh-03607ee1107e4cf6`：九任务字符串false未拒，`9 failed,45 deselected,1 warning in2.54s` | 同一验证helper九任务代表非法值覆盖（不继续机械9x6矩阵），默认/角色顶层优先与enabled周期原回归保留。 |

**候选主体及窄修验证**：下列5文件先完成 `106 passed,1 warning in3.25s`，job `pwsh-fe165188d6e14b29` exit0；三生产源Ruff/Black PASS。随后lead指出本新增world容器路径须安全报告：required_secret_keys已用安全_get，但_validate_world_switches遇world=[]仍.get抛AttributeError。根/section两个代表用例 `pwsh-61a13d603b3943ee` 得 `1 failed,1 passed,1 warning in3.07s`；仅给new switches根容器core.world error、optionals非法根直接跳过，原8scope不扩。修后代表/邻近AMAP/Secrets/mixedwarning/禁用credential/真实world共 `8 passed,1 warning in2.14s`（`pwsh-c24bd1e220424972`），validation Ruff/Black通过；不重跑106/163。旧candidate 0c9bce…仅修前，不算当前已通过，按新manifest冻结再交同attempt1增量审核。新world证据文件Ruff/Black及原world测试Ruff也通过（先前综合job `pwsh-5951e1b1a05f4c74`），唯一警告为既有zhconv/pkg_resources弃用。没有业务夹具红失败误记为产品修复，格式初查行宽/Black问题已在授权文件内修正。

```text
python -B -m pytest tests/unit/world/test_world_runtime.py tests/unit/world/test_world_clock.py tests/integration/world/test_disabled_world_startup.py tests/integration/system/test_admin_runtime.py tests/unit/world/test_world_task_citywalk.py -q -p no:cacheprovider
```

**风险与回滚**：world关闭会停止清理/提醒/学习等，明确不保证补跑；M1-S是整项citywalk跳过而非只少索引。AMAP重新请求true时需准备key，JWT不放宽。恢复具体开关/依赖并重启；不删除用户数据/资源/凭据。当前仅组合根与条件校验闭合，未证明完整注册登录/网络WS/历史/媒体/管理UI或资源性能。真实资源前置已确认资产存在与路径/密钥缺口，但只stat不能冒称可推理/full-min收益；不fakebenchmark、不擅自付费调用/迁移现用路径。3A未提交，等Oracle与lead明确许可。

## 2026-11-17 Phase3B：管理DTO逐叶映射与原保存重启契约

**待定问题**：如何在不重构管理工作流的前提下，让两个组件开关可读取/保存，并准确拒绝非法输入、不覆盖角色/模型/密钥占位、不破坏旧owner安全停止？

**背景约束**：3A已在同attempt1增量PASS后由lead授权原子提交 `80739a5b86a1e1d3f3b8096b5017ff58ebb6b969`，未推送；task7rev6仅五路径：model_editor/admin_interface/两个新测试/本AI。UI/README/build由desktop-ui独占另scope，完整真实A4/A5与资源测量在后续；不并发改AI、不改Supervisor内部或world/模板。

**调研参考**：沿[已审管理DTO契约](<docs/specs/component-startup-switches.md#L297-L315>)和现有 `apply_llm_config_draft→validator→ConfigStore.write_raw→RuntimeSupervisor.restart`，不新增研究/热切换端点。

**候选方案**
1. **新增DTO投影+专用组件输入校验**：GET始终给两个有效bool（缺省true）；POST对象/叶可省略；严格bool/未知叶由ComponentStartupDraftError携完整DTO路径，route只把这个新增错误映射422；逐叶merge到原raw owner节点。
2. **保存整个UI草稿到raw或统一catch所有ValueError**：便于处理，却可能丢characters/embedding/model/$VAR，或改变旧模型错误语义。
3. **独立组件热应用/新Supervisor**：额外端点和并发资源切换，超出既定重启规则。

**选择**：候选1。新component parser为窄helper，主apply函数调用它但不增加额外分支（避免C901从10到11）；仅新错误映射422，旧call_transport/model分支行为不变。component_startup不是新持久配置节点。GET使用现有路径读取，正常保存后反映false/true，默认缺省兼容。

**选择理由**：最小改动就能复用备份/原子写、校验和原Supervisor安全owner门禁。没有新restart逻辑；`restarted=true`仍只表示曾运行并请求重启，response.runtime.state/running反映实际失败/成功，UI阶段据此展示。

**未选原因**
- 候选2：覆盖整raw会把本面板外内容混入，或改写占位/配置；泛捕旧ValueError使非本契约报错改变，难定位与回滚。
- 候选3：不满足复用现有保存/重启要求，增加在途资源引用竞争及维护面。

**实际红→绿证据**（agent Python3.10.21/Ruff0.14.10/Black26.5.1）：

- 默认投影首红 `pwsh-8d6c2ab3edf440bb`：KeyError component_startup，`1 failed in0.61s`；最小projection后同条 `pwsh-a0458d7a7ce34612`：`1 passed in0.03s`。
- 单叶patch映raw红 `pwsh-b74bd328377a4097`：speaking.enabled没写，`1 failed in0.61s`；新helper映射后新/旧字段真实配置比较通过，输入副本不变、另叶/characters/embedding/$VAR全保留、无持久DTO节点。
- 真实AdminAuth setup/login/Bearer管理route非法输入红 `pwsh-a6481893b7cf482c`：stringfalse、int0、未知叶、对象null均200，`4 failed,2warnings in3.14s`；专用新增错误422后新两文件绿灯。
- 中间fixture每例真实登录消耗同进程5次/300s限流，`pwsh-8c67ea829ef04dab` 得 `7passed,3errors,2warnings in9.26s`。这是测试隔离错误，不是组件产品红灯；沿已有 `_reset_rate_limit_state` 在测试fixture重置，不改生产限流/不跳鉴权/不等sleep。
- 完整新DTO/管理集成 `pwsh-3ec5040fe56a44fc`：`12passed,2warnings in4.62s`。实际使用临时ConfigStore、SecretStore、validator、FastAPI路由与AdminAuth；检查未鉴权401、非法422无写无restart、validation失败不写不停、停止保存只validate不自启、运行调用原重启、备份字节等原raw。
- 两条使用**真实RuntimeSupervisor**的重启集成保留其stop/start方法，只替换外部昂贵ServerRuntime.initialize和旧owner资源；成功事件为old.shutdown→new.initialize，旧shutdown抛清理未完成时不构造新runtime、保留旧owner、response显示failed/running=false。不是用自定义restart结果自证安全，也不冒称完整ServerRuntime或实际浏览器A4。
- 最终相关旧管理字段回归 `pwsh-5169ea34903c4064`：5文件 `95passed,2warnings in4.60s`；旧音频模型/config/module_bindings/skills配置保障保留。Ruff对两生产/两新增测试通过，Black对应四文件通过；唯一先前静态C901已用窄新helper修正，不重写旧core。

```text
python -B -m pytest tests/unit/infrastructure/test_component_startup_config.py tests/integration/system/test_component_startup_admin.py tests/unit/infrastructure/test_admin_audio_config.py tests/integration/agent/test_skill_configuration.py tests/integration/system/test_admin_runtime.py -q -p no:cacheprovider
```

**风险与回滚**：控制台前端尚待3C，本阶段真实route+受控资源端口不能当实际浏览器A4；实际业务初始化失败与旧资源清理失败继续由原Supervisor报告，不因HTTP200/written/restarted误称运行成功。未进行真实LLM/TTS/full-min性能/完整A5，不修改现用config/secret、不付费调用。五路径候选冻结后交Oracle gate，未提交推送；UI脚本导入backend需待本阶段明确commit ready后运行。

## 2026-11-17 Phase3C：组件启动独立面板与使用说明（顺序转录）

**待定问题**：两个开关如何加入原四面板而不串草稿、不把请求重启误说成就绪？

**背景约束**：3B已由lead许可提交 `f8f6f9263f26c9752db9691340e0b00252d191a6`；desktop-ui仅拥有UI/README/资源锁scope，不并写AI。本条由startup-spec按lead明确要求从外部UI报告第2节顺序摘录；UI经Oracle implementation1/3 PASS和lead许可精确七记录提交 `80b783ad24942828fc6787cdbc870e8967a2849e`，不夹本阶段宿主。

**调研参考**：desktop-ui查询React官方受控checkbox/不可变对象更新，沿本仓原panelDraft/select工作流与原生标签，不新控件库。

**候选方案**
1. **独立第五面板/逐叶提交**：两个严格bool checkbox，只提交相对savedConfig有变的叶；成功仅清本面板，其他草稿保留；实际runtime.state/running决定就绪文案。
2. **整面板/raw替换**：省事，但覆盖其他配置/未保存草稿并放大输入面。
3. **restarted即成功/重设计布局**：反馈简单但虚报starting/failed；换布局/控件库额外风险且无需求。

**选择**：候选1。默认true，当前面板无变化不HTTP写；failed/blocked明确检查last_error，running且true才称运行中；旧四模型面板顺序/机制不变。README说明两新键与九world默认/严格bool、M1-S整项跳过、SQL-only无回填、SAY/Sing/Call区别、隔离路径与JWT/AMAP条件、管理员邀请/RSA登录/两轮聊天后真实`/history`刷新（不是initial-history缓存）。

**选择理由/未选原因**：原工作流足够且保草稿边界；候选2会把面板外内容带入，候选3把请求当完成或无需求扩大改动。

**验证方式与实际证据**：原真实旧bundle对五面板契约红（4≠5，job `pwsh-55161cc9afab4a33`）；固定3B ready后同树Node22.23.5/npm10.9.9执行npm ci与tsc/Vite7.3.6构建，最终stub Chromium脚本exit0/pageerror0，验证隔离草稿、单叶payload、刷新、实际状态文案。该stub拦截API，仅证前端交互，不是实际A4重启。安装报告6漏洞（1moderate/5high），未auditfix。真实整份release资源check PASS；JS `index-smbr_9OT.js` 245260B SHA256 `13625ee3a225a22dbc7de46b52173a81c9abc0a8b29679110c8f2260e04daf72`；HTML423B/CR0 SHA `7fa2c373bb070829688a71049d4d937d686a6024f90e0fc7deec2effa1f7ed7e`；CSS原内容不变。README唯一Oracle机械修正/history后候选47f192…通过，同attempt1无需重build。

**风险与回滚**：原styles/布局不变不是全设备视觉验收；实际管理API与重资源恢复另验，不能借stub勾A4。可回滚UI自然提交，不删除数据；本条只有顺序决策转录，3C已提交且UI文件不属下述3D四路径。

## 2026-11-17 Phase3D：真实隔离生产链与实际控制台证据

**待定问题**：怎样证明关闭重资源后仍能走真实生命周期/鉴权/WS/历史，而不以fakeRuntime或付费供应商填补缺证？

**背景约束**：task7rev7明确四路径（新host/E2E/真console脚本/AI），父版本为3C `80b783ad24942828fc6787cdbc870e8967a2849e`。90秒有界单探针，五DIR先于server_main导入；不改生产/现用config或secret，不下载权重、不调用真实供应商，不fake RSS。只有底层模型API factory可确定化，UI脚本用新bundle/真实API不拦截。

**调研参考**：复用已有production-loopback host的run_server/ServerLifecycle接缝及真实RSA/WS/voice协议，不复制旧call宿主数百诊断路由。事前标准库AST签名/内存JSON设计核对PASS，没有项目导入或业务启动。

**候选方案**
1. **真实生产链+最底层确定性接口**：保留LLMService/PromptManager/Modules/on_delta、Runtime、SQL/RSA/Stage/Adapter/媒体，四资源构造点计数后失败，关闭时全0。
2. **旧fake Runtime/TTS/vector装配**：容易启动，却用替身抹去本需求的资源分支/持久化/owner问题。
3. **真实供应商/full-min现场benchmark**：更强证据，但当前key配置false/远程成本未授权，不能越权或用静态估值冒充。

**选择/理由**：候选1，仅验证明确允许的离线真实生产契约。host标准库顶层先隔离CONFIG/DATA/RUNTIME/RESOURCE/ASSET，生成实例随机JWT不输出、合法persona/tone/prompt、songs空表/关键词、空唱库/prepared元信息；不复制用户数据。沿真实run_server→Lifecycle→AdminShell/validator/Supervisor→ServerRuntime→shutdown。只有LLM/VLM/audio create_interface替外部生成端，TTS/Chroma/embedding/vector执行器是触发即失败的trap而非成功替身。

**未选原因**：候选2无法证明实际装配；候选3未获远端授权/资源口径未齐，不以离线fake基准或MB/百分比填空。触碰反应配置清空仅隔离fixture普通聊天接缝，不代表生产功能删减或所有能力均验。

**验证方式与分层实际结果**：
- 首真实HTTP管理员setup/login/invite生成→RSA注册登录→网络WS两轮唯一成功终态/audio空→真实文字history→全关world0/资源trap0/真实模块注册，job `pwsh-dfbeaea5abfa4db0`：`1passed in10.71s`，原run_server finally退出0。非真实模型回答。
- 媒体fixture错误分别保留：job `pwsh-d970e0bdf9cb4ae4` 23.96s误等ack而协议server_ack；`pwsh-bd4812506aac41ed` 10.44s把finalize接纳ACK当落盘完成后立即断WS，下载404。均只修测试，不产品红；后等真实语音理解/回复终态，job `pwsh-aa2c9516daa44633`：`1passed in11.72s`，原AAC字节下载200/无token与坏token401/另一真实RSA账号404，文字history对应两轮，正常关闭/exit0。
- 真实console最初RESOURCE隔离未提供bundle使生产ui_register fallback、Setup token超时；其次setup/login页面切换未等导致登录失败；均按原log与退出0记录为fixture问题。lead明确允许复制锁列HTML/JS/CSS三个约260KB代码产物，前后核size/SHA，不复制用户assets/权重；同步真实setup200→登录heading→login200后，job `pwsh-70e789dea7384efe` exit0：`ACTUAL_CONSOLE_API=PASS`，pageerror0。实际停止业务后vectortrue保存/刷新不自启→false还原；TTStrue缺配置validator拒写/原文件不变/草稿保留/放弃刷新。没有page.route，保存结果只含bool，不归档临时config/token。
- **字节边界**：11.72媒体在bundlecopy变化前（当时代码bundle硬链接版、媒体不读取UI）；真实consolegreen基于copyfile版；后仅三个新文件Black/import排序、host固定copy/model重写与E2E环境小helper的原语提取、print字符串拆分，无等待预算/执行顺序/生产行为变化。按lead允许分层复用旧场景，不声称当前全文重跑；新三文件Ruff/Black最终PASS（job `pwsh-8272b78f732345af`）。

**证据限制与风险/回滚**：实际console只停止态保存/刷新与TTS拒写，**不等同运行中apply实际restart/真资源恢复的完整A4**；正常exit0/Lifecycleclosed不等全句柄泄漏审计；媒体原字节权限+处理终态不等已独立核音频history条目（文字history已核）。知识库合法空表不等公开歌曲查询全验。独立server-handoff只读证据桥认可保真链并提出以上三披露，不是另一次运行PASS。真实freeLLM、完整模型/full-min同口径3次30秒RSS收益未验证；资产存在的stat不是可推理或性能证据，工单证据仍未齐。3D局部可提交请求review而非验收闭合；未自行GH/push/goalcomplete，最终固定HEAD全CI另由verifier执行。四路径当前候选冻结待Oracle/lead，不删除数据，回滚证据代码不影响生产配置。

## 2026-11-17 A4补验：实际运行态保存、更换owner及同库继续聊天

**待定问题**：Draft #441中真实控制台只证明停止态保存/拒写，怎样在不启用重资源、不改生产的范围内证明运行中保存真的安全重启，而不相信restarted布尔？

**背景约束**：已提交633aa32/Draft441保持原历史；task7rev9新增仅旧host/旧actualconsole/本AI三路径，独立gate/新commit，不amend。两组件及九world始终false，仅外部模型API接口确定化，真实Supervisor/Runtime/SQL/RSA/Stage不替。一个实例/一次运行态保存，总≤90s，不复跑旧停态或整个17/95集合；供应商/真资源恢复/A6/V5仍非本单元。

**调研参考**：沿已存在真实run_server及Supervisor.restart的stop→start顺序；Playwright Python v1.63官方文档查询确认expect_response配合真实点击读取响应，沿旧浏览器鉴权和已有E2E网络helper，不加依赖/endpoint平台。

**候选方案**
1. **只观察原Runtime生命周期并从真模型面板触发重启**：测试host用弱引用给实例代号，包装原initialize/shutdown并逐次await原方法，记录begin/complete；模型字段发生真实变化，重启后同库账号重新WS和HTTP历史验证。
2. **只看restarted/running或同false点保存**：无需观测，但前者不能排除未换owner，后者UI no-op根本不发HTTP，证据不成立。
3. **启用真TTS/vector或替一个成功owner**：前者需要未授权资源/供应商，后者绕掉实际重启，两者都不满足当前证据目标。

**选择/理由**：候选1。RuntimeObserver只持weakref.ref和无凭据序号/事件，不强持旧owner，不更改原Supervisor。脚本`--running-restart`模式从真实模型面板将非空模型标识改为offline-restart-verified，两组件false不动；真实API校验/写入/备份/原restart，随后同账号重新连WS并GET history。旧停态模式保留复用，不混入本次一次保存。

**未选原因**：候选2是请求状态误证或no-op；候选3或越权或成功替身自证。字段变化不证明真实供应商用了新模型；只用于启动原重启工作流。

**验证方式与实际结果**：先建立assert_running_restart，标准库AST单独抽出断言，对“响应ok/written/restarted/running都true但owner相同”输入真实失败`restarted response retained the old runtime owner`。这是**断言敏感性红灯，不是产品功能原先失败**。还要求旧/新ID均非None、不同，新增事件恰为old shutdown.begin→complete→new initialize.begin→complete，两能力false、四资源计数0。

首有界运行`pwsh-6f6ff5634e1c4a50`生产初始化成功后，脚本helper导入被已安装tests命名空间遮挡，ModuleNotFoundError: tests.e2e，发生在管理员setup/模型保存之前；finally正常退出0/closedtrue，无业务重启执行，不算产品红。lead准仅按确定文件路径importlib加载既有E2E helper，纯导入preflight `pwsh-52070b31241c4b07` PASS（文件位置/三callable/无项目业务启动、无全局path改动）。

修后唯一场景`pwsh-033880145eb8404a` exit0：`ACTUAL_CONSOLE_API=PASS; running-restart/same-account-ws-history; not full TTS/provider reenabling`。实际runtime-1→runtime-2；旧shutdown完整结束先于新initialize；TTS/Chroma/embedding/vector-executor计数全0；重启前后同一账号分别得到核心链路412/第二条回复、真实history包含二者，pageerror0；原关闭链退出0/closedtrue、父子总<90s断言完成。两源码最终Ruff/Black PASS（`pwsh-dbf8eda47fbc4306`），没有额外矩阵/全量CI，未改生产/UI/README/E2E文件。

```text
python -B scripts/check_component_startup_console.py --running-restart --output <外部无凭据结果JSON>
```

**风险与回滚/准确结论**：本单元消除了“实际运行态保存工作流、新owner和重启后聊天未验证”这一局部缺证，**不是TTS/embedding true资源恢复，更不是A4全部步骤/A6非作者README/V5真实RSS或供应商验收**。Observer事件仅成功await原方法后标complete，若原方法抛错不会补成功事件；弱引用观察不是逐句柄泄漏审计。回滚后续证据自然提交即可，不回滚已发布633或删除数据。候选冻结后交独立Oracle gate，未经明确新许可不commit/push/GH/ready/closegoal；原633全量及远端CI结果不能倒写为新补丁完整通过。
