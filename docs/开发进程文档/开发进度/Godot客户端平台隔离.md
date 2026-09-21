# Godot 客户端精简与平台隔离

- 大目标：保留功能与外观，删除失效路径，隔离平台能力，预留换装/箱庭/设备接口。
- PRD：[Godot 客户端](../需求说明（PRD）/Godot-Windows客户端.md)
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)
- interface：[平台隔离](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/platform-isolation.md)
- 总体状态：已完成（本轮源码范围）

## 已完成

### 2026-09-21 共享组件与基础依赖清理

- SPEC f013e61；纯路径迁移/删除无运行时 Red，不伪造失败。移走正式使用的输入框/气泡脚本并保留 UID，删除无调用的日志目录方法及旧标题栏主题资源。
- 地址规范化迁到 domain，账号哈希工具保持旧 JSON/SHA-256 形式；存储不再加载 AccountApi。账户规范化测试改从新公开入口观察相同规则。
- 修改前四组检查、登录/设置 GPU 与下拉截图检查通过；修改后基础、账户、网络、功能四组通过。日志在 client_godot/artifacts/isolation-baseline，未访问公共服务。
- 作者自审确认没有删除有效场景/状态节点、未变更协议与旧数据格式；未纳入 project.godot 或热重载 DLL 差异。不打包；移动端与实际系统 DPI 未验证。

### 2026-09-21 配置、输入、文件和音频能力注入

- Red bb80ec0：架构守卫实际发现配置/输入/媒体越界，日志 boundaries-red.log。将配置、系统输入、文件选择/导出、缓存读取流及解码器工厂分别隔离，固定FileDialog仍在场景中，配置资源逐场景隔离。
- 本片涉及同一批跨层消费者的构造注入，新增契约/平台适配/测试合计超过500行；业务算法未拆碎，保留独立能力职责。既有文件配置、图像校验、声音混音和草稿规则保持。
- 基础组通过到visual-surfaces；初次audio-settings因测试仍隐式装配解码器超时，修正测试明确注入后，audio-settings及剩余五项实际单独通过。账户、网络、功能组全部通过；缺失解码器终止一次与读取流关闭测试通过。补回归测试首次通过，不冒充额外Red。
- 自审发现并修正tscn外部资源声明顺序及接口返回类型推断；这些是实现期错误，不是Red证据。独立核验超时中止，未以其替代自审。未打包，未改DLL。

### 2026-09-21 原生、运行环境和桌面窗口隔离

- Red 2935116实际发现UI/角色/入口的系统API调用，迁移后六项架构检查通过。认证、秘密保护、Cubism、窗口宿主和环境能力各自隔离，原DLL保留。缺少加密仍能开日志，缺少模型明确显示错误，补回归测试通过。
- 基础组通过到window-chrome，图片转属触发exit/enter但不再次ready，发现宿主解绑后未重绑；改在enter_tree绑定后，image-window及后续全部基础项单独通过。账户组、登录/设置/退出GPU均通过。
- 原生三键探针曾失败；将旧host在隔离脚本复现同样失败，确认是桌面置顶浮层及DWM恢复动画旧坐标。驱动只移动已校验归属的测试窗口，等待动画并拒绝点击其它HWND；最终platform-native-final.log验证拖动/双击/八方向/三键/系统关闭与Alt+F4共两次close_requested全部PASS。
- 作者自审检查窗口信号解除与重新挂接、资源local_to_scene及不可用分支；移动/提取的既有驱动代码占本片主要体积，没有改角色算法或原生构建。不打包；Windows10、多屏、系统DPI、手机与公共服务未验证。

### 2026-09-21 应用职责拆分

- SPEC c9d41eb。ApplicationServices只构造服务图与窗口工厂；AccountLifecycle统一启动/停止账号业务；WindowCoordinator持有窗口复用、草稿汇总、保存等待与退出信号，Application只做主视图绑定及协调调用。
- 保持既有Application.setup参数、日志默认目录、场景控件和退出行为。纯职责搬迁不制造Red，既有公开界面回归为保护。
- 基础组与账户组实际通过。功能组首次运行因历史图片测试仍传旧ImagePresenter路径参数而超时；已定位并修正测试装配遗漏，完整功能组重跑通过；失败轮不计作通过。证据composition-*.log。作者自审检查各Node唯一创建者/父节点、日志退出标记及窗口工厂不提前启动请求。
- 本片未增加未来业务，不打包；未验证环境沿用此前限制。

### 2026-09-21 三个未来模块的最小接口

- AppearanceService/WorldService/DeviceService独立Resource接口，默认能力false、start返回ERR_UNAVAILABLE、操作返回NOT_IMPLEMENTED，无页面、连接、轮询、请求队列或假完成。Application通过三个独立注入槽交给账号生命周期；音频工厂也由场景明确注入。
- 本片为尚未实现业务的接口定义与不可用默认行为，运行时功能Red不适用；契约测试首次运行通过，未将缺文件/解析错误伪装Red。测试实际验证默认拒绝、取消/重复停止无完成、能力快照副本。
- 真实Application与本地账户接口登录两个账号，仅未来外部模块使用Probe：上下文仅三个允许字段、不可相互修改、账号scope不同且generation递增；每次退出调用停止，销毁不重复停止。证据extensions.log。没有验证真实换装、世界或设备功能。
- 作者自审确认未向扩展传token/password，未接入新协议或导航，不打包。

### 2026-09-21 最终依赖核验中的图片默认实现收尾

- SPEC 240641b、Red 943bee6：扩展架构守卫发现ChatSession在未注入时仍创建具体文件图片缓存。改为HistoryImageSource不可用接口，正式组装继续注入HistoryImages，独立会话不再隐式访问磁盘。
- 七项架构守卫及真实HTTP历史图片/账号切换/缓存恢复/聊天原图回归通过（image-source-green.log），原图片算法未改。作者自审确认没有删除消息或更改线上协议。

### 2026-09-21 独立核验后的生命周期边界修正

- 独立只读核验发现重复signed_in重启及确认显示后新保存竞争。SPEC f7ff7c2，Red 9ca5539：通过真实set_login_options复现扩展重复启停；通过设置公开save_changes复现确认后立刻登出并在迟到保存中访问已销毁控件。
- AccountLifecycle按账号scope及连接令牌的内部指纹抑制同会话重复启动；指纹不暴露给扩展。WindowCoordinator在确认时重新检查保存，失效确认先等待再重新汇总。
- 两个聚焦回归实际由Red转Green，包含跨账号上下文、幂等停止、保存失败后取消仍保留账号和草稿，lifecycle-green-*.log通过。作者自审检查无新协议、无认证信息进入扩展。

### 2026-09-21 整体验收与文档同步

- 最终源码的基础、账户、网络、功能四组完整回归全部通过，七项依赖守卫已接入账户检查。初次账户组因unittest默认stderr被PowerShell视为错误而中断，改为stdout后完整四组重跑PASS；没有将中断轮计为成功。日志final-check*.log。
- GPU登录、设置加载/失败/保存及四档内容缩放、退出确认、主界面、动态、下拉圆角、文字/图片气泡与角色交互全部通过；真实HWND验证动态/日志独立、设置跟随，以及系统拖拽/双击/八方向缩放/三键/Alt+F4通过。final-gpu*.log及final-native-window-controls.log为证据。已亲自查看最终登录、主聊天、加载设置和发布浮层截图，未改原界面设计。
- 当前GPU短采样（1200×800，90帧）：磨砂median 6.067ms/P95 7.526ms，实底median 6.063ms/P95 8.698ms；对应228/227 draw calls、约112.8MB静态内存。采样仅描述本机瞬时数据，不用于宣称性能提升或集显认证。
- 场景/脚本/资源引用全量检查、现行接口文档链接检查、git diff --check通过。共享脚本移动保留UID，新接口UID补齐；release.json仍0.1.3。原接口总表归档保留历史，当前索引与核心业务契约分开，PRD/总体设计/历史平台问题/测试说明同步。
- SPEC/Red/Green与纯迁移提交均完成作者自审；独立探子只读核验提供两个有效问题并已用真实回归修复，不替代正式他人审核。本轮仅本地提交，无远端PR/推送，未打包，旧交付包不变。
- 用户原project.godot属性重排与两项热重载DLL删除未纳入。Windows10、真实系统DPI、多屏/显示器移除、手机、集显、公共服务与长期性能未验收；未来三模块只有接口和不可用实现，Android仍需平台后端/权限/移动宿主。

### 2026-09-21 远程提交前的无关文件清理

- 用户授权清理、推送fork并向原项目提交PR。删除54,080,418 bytes的本地文件清单File report.txt、两份~热重载DLL、未使用的model.json和与正式入口逐字节相同的model.model3_copy.json；正式model.model3.json、原生DLL、许可、测试、预览与旧交付包保留。
- 根/客户端gitignore新增精确生成物规则。检查正式模型及DLL仍存在、不被忽略；引用与加载入口核对完成。清理不改变业务/interface，运行时Red不适用；完整基础检查实际通过（artifacts/pr-cleanup-check.log）。作者自审确认project.godot的本地属性重排不混入提交。

### 2026-09-21 上游PR候选复验

- 从upstream/dev b367bb2建立独立feat/godot-client-013提交工作树，导入清理后的完整Godot子项目及必要契约/文档；开发分支历史不改写。原项目此前没有Godot工程，候选为完整子项目首次引入。
- 验证客户端/聊天契约树与本地清理版本一致，server/client/app/.github差异为空；未含File report、热重载DLL、dist、artifacts或.godot缓存。检查高置信凭据特征未发现匹配。末尾空行检查发现旧语音测试多余空行，已在两个工作树一致整理。
- 全新缓存第一次导入时，引擎在纹理缓存生成前加载全局主题报ctex缺失，保留cold-import.log；资源导入结束后完整基础、账户、网络、功能检查全部通过，7项架构检查通过。独立工作树登录与设置GPU复验通过。证据位于client_godot/artifacts/pr-submission；初次失败不计通过。
- 未打包、未升级版本，用户project.godot属性重排仍留在原工作区。真实系统DPI、多屏、移动端等未验证范围不变。

### 2026-09-21 推送与原项目PR

- 已推送到Hun1Bk/Agent-LuoTianyi的feat/godot-client-013分支，并向SheepLiu712/Agent-LuoTianyi的dev创建[PR #186](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/186)，创建时head为7bc091b，状态open、非draft。
- 本次PR使用基于upstream/dev的干净完整客户端提交，不改写本地开发分支或已有远程分支历史。未自动合并、未打包；本条只补充远程提交事实，运行源码与上述已验证候选一致。

### 2026-09-22 PR #186 反馈修复（本地）

- 交付行为：账户启动先验证聊天 transport，失败时逆序回滚；重复账号激活保持幂等；可选换装/世界/设备能力返回 ERR_UNAVAILABLE 时不阻断文字聊天。ChatSession 增加瞬态 user_typing 入口，输入、发送、断线和退出清理 typing 状态。模型委托只接受严格受限的 PNG/JPEG/WebP data URI；图片历史在 JPEG/WebP/PNG 解码前预检可信尺寸。
- 交付行为：语音缓存启动时清理孤儿配对；ClientLog 实际执行单次字节/条数上限并原子替换运行元数据；WindowsSecurity 返回受控 native stage/code，DLL 缺失明确为 SECURITY_UNAVAILABLE；非法纯数字点分 IP 被拒绝。测试 runner 隔离 APPDATA/LOCALAPPDATA、严格检查退出码/FAIL/PASS，冷导入与契约检查分离，发布构建使用全新目录和锁定哈希校验。
- interface：`ChatSession.start(session) -> Error`、`ChatSession.set_typing(active,text_length=0) -> Error`、`AccountLifecycle.start(session) -> Error`；客户端核心服务、平台隔离和日志/缓存契约已同步。
- 提交：`33f349e`（原生安全与地址）、`f23b7df`（锁定安全 DLL）、`92e7f67`（账户/图片生命周期）、`a3166cc`（缓存/日志）、`5aed027`（测试/发布编排）、`27f8abb`（回归入口）。这些提交均在本地 `fix/godot-pr186-feedback`，未推送远程。
- 验证：Godot 4.7.1 冷导入及基础检查通过；账户、网络、功能检查通过；模型执行、历史图片、音频缓存、客户端日志、Windows CNG/DPAPI 与 Python 解密互操作通过；依赖边界 9/9、Python 编译和 `git diff --check` 通过。新增生命周期和 typing 回归首次作为补回归测试运行，未伪造 Red 证据。
- 未处理：N1 的 PR 阶段祖先链/巨型提交例外、动态窗口状态、图片按钮键盘操作、登录窗框和主题集中度仍未在本切片处理。未验证 Windows 10、真实系统 DPI、多屏、手机端、公共服务和长期运行性能。用户现有 `client_godot/project.godot` 属性改动未纳入提交。
